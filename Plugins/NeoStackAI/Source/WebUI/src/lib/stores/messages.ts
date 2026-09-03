import { writable, get } from 'svelte/store';
import {
	getSessionMessages,
	sendPrompt,
	cancelPrompt,
	onMessage,
	type ChatMessage,
	type StreamingUpdate
} from '$lib/bridge.js';
import { currentSessionId } from '$lib/stores/sessions.js';
import {
	isPromptingState,
	sessionStates,
	type AgentConnectionState
} from '$lib/stores/agentState.js';
import { handleUsageUpdate } from '$lib/stores/usage.js';
import { setAuthRequired } from '$lib/stores/auth.js';
import { sessions } from '$lib/stores/sessions.js';
import { addSubmittedPromptToHistory } from '$lib/stores/composerHistory.js';
import { createUUID } from '$lib/utils.js';
import { isAssistantMessageUpdate } from '$lib/stores/streamingUpdateRouting.js';
import { paneManager } from '$lib/stores/panes.svelte.js';
import { isSessionDisposed, onSessionDisposed } from '$lib/stores/sessionLifecycle.js';
import {
	beginKeyedPerformanceSpan,
	endKeyedPerformanceSpan,
	endKeyedPerformanceSpanAfterPaint
} from '$lib/performanceTelemetry.js';
import { createPromptLifecycleRegistry } from '$lib/promptLifecycle.js';

export const messages = writable<ChatMessage[]>([]);
export const isStreaming = writable(false);
export const messagesBySession = writable<Record<string, ChatMessage[]>>({});
export const streamingBySession = writable<Record<string, boolean>>({});
export const cancellingBySession = writable<Record<string, boolean>>({});
// Per-session load counters so concurrent loads for different sessions
// don't cancel each other. Only same-session loads should cancel prior ones.
const loadRequestIds = new Map<string, number>();
const loadedSessionIds = new Set<string>();
const sessionEstimatedBytes = new Map<string, number>();
let loadRequestCounter = 0;

// ── Streaming gating ─────────────────────────────────────────────────
const promptLifecycle = createPromptLifecycleRegistry();

/** A turn is live for this session — locally sent (prompt lifecycle) OR
 *  remotely initiated (desktop/web prompted this executor; inferred from the
 *  agent's prompting state, since no local composer send ever happened). */
function isTurnLive(sessionId: string): boolean {
	return promptLifecycle.isActive(sessionId) || get(streamingBySession)[sessionId] === true;
}

// ACP session/load replays are history snapshots, not live prompt turns. Keep
// replay chunks out of the visible cache until the replay is complete.
const replayActiveForSession = new Set<string>();
const replayPreserveCachedForSession = new Set<string>();
const replayBuffers = new Map<string, StreamingUpdate[]>();
const replayEpochs = new Map<string, number>();
let replayEpochCounter = 0;

// ── Store helpers ────────────────────────────────────────────────────

function setSessionMessages(sessionId: string, msgs: ChatMessage[], markLoaded = true): void {
	if (markLoaded) loadedSessionIds.add(sessionId);
	sessionEstimatedBytes.set(sessionId, estimateTranscriptBytes(msgs));
	messagesBySession.update((all) => ({ ...all, [sessionId]: msgs }));
	if (get(currentSessionId) === sessionId) {
		messages.set(msgs);
	}
}

function updateSessionMessages(
	sessionId: string,
	updater: (msgs: ChatMessage[]) => ChatMessage[]
): void {
	loadedSessionIds.add(sessionId);
	let nextMsgs: ChatMessage[] = [];
	messagesBySession.update((all) => {
		nextMsgs = updater(all[sessionId] ?? []);
		return { ...all, [sessionId]: nextMsgs };
	});
	if (get(currentSessionId) === sessionId) {
		messages.set(nextMsgs);
	}
}

function setSessionStreaming(sessionId: string, streaming: boolean): void {
	streamingBySession.update((all) => ({ ...all, [sessionId]: streaming }));
	if (get(currentSessionId) === sessionId) {
		isStreaming.set(streaming);
	}
}

function setSessionCancelling(sessionId: string, cancelling: boolean): void {
	cancellingBySession.update((all) => {
		if (cancelling) return { ...all, [sessionId]: true };
		if (!(sessionId in all)) return all;
		const next = { ...all };
		delete next[sessionId];
		return next;
	});
}

function normalizeLoadedMessages(msgs: ChatMessage[]): ChatMessage[] {
	for (const msg of msgs) {
		if (msg.isStreaming) {
			msg.isStreaming = false;
		}
		for (const b of msg.contentBlocks) {
			if (b.isStreaming) b.isStreaming = false;
		}
	}
	return msgs;
}

// ── Auth / error helpers ─────────────────────────────────────────────

function isLikelyAuthError(update: StreamingUpdate, agentName: string): string | null {
	if (update.errorCode === -32000) {
		return 'Authentication is required to continue.';
	}
	const lowerText = (update.errorMessage ?? update.text ?? '').toLowerCase();
	if (!lowerText) return null;
	const isClaudeOrCodex = agentName === 'Claude Code' || agentName === 'Codex CLI';
	if (!isClaudeOrCodex) return null;
	if (lowerText.includes('query closed before response received')) {
		return `Your ${agentName === 'Claude Code' ? 'Claude' : 'Codex'} CLI session may be signed out. Sign in and try again.`;
	}
	if (lowerText.includes('not authenticated') || lowerText.includes('authentication required')) {
		return `Your ${agentName === 'Claude Code' ? 'Claude' : 'Codex'} CLI needs authentication.`;
	}
	if (lowerText.includes("run 'claude'") || lowerText.includes("run 'codex'")) {
		return 'Run the CLI sign-in flow and return to the editor.';
	}
	return null;
}

function formatAgentError(update: StreamingUpdate, agentName: string): string {
	const raw = (update.errorMessage ?? update.text ?? '').trim();
	const lower = raw.toLowerCase();
	const codeSuffix = typeof update.errorCode === 'number' ? ` (code ${update.errorCode})` : '';
	if (!raw || lower === 'unknown error' || lower === 'agent error') {
		return `Agent error${codeSuffix}. Please retry, and if it repeats open setup for ${agentName || 'this agent'} to verify installation/authentication.`;
	}
	if (lower.includes('failed to connect') || lower.includes('cannot send prompt')) {
		return `${raw}${codeSuffix}. The agent process failed to start or reconnect. Open setup and verify the CLI is installed and authenticated.`;
	}
	return codeSuffix ? `${raw}${codeSuffix}` : raw;
}

export function finishStreamingForSession(sessionId: string): void {
	promptLifecycle.finish(sessionId);
	setSessionCancelling(sessionId, false);
	updateSessionMessages(sessionId, (msgs) => {
		const last = msgs[msgs.length - 1];
		if (last?.isStreaming) {
			const finished: ChatMessage = {
				...last,
				isStreaming: false,
				contentBlocks: last.contentBlocks.map((b) => ({ ...b, isStreaming: false }))
			};
			return [...msgs.slice(0, -1), finished];
		}
		return msgs;
	});
	setSessionStreaming(sessionId, false);
	const sessionMessages = get(messagesBySession)[sessionId];
	if (sessionMessages)
		sessionEstimatedBytes.set(sessionId, estimateTranscriptBytes(sessionMessages));
	evictStaleSessionCaches(get(currentSessionId) ?? sessionId);
}

// LRU bookkeeping for the transcript cache: every session ever visited used to
// stay in memory forever — including base64 screenshot payloads — growing the
// CEF heap across a workday. Evicted sessions cold-load from SQLite on reopen.
const sessionTouchOrder = new Map<string, number>();
let sessionTouchCounter = 0;
const MAX_CACHED_SESSIONS = 12;
const MAX_CACHED_TRANSCRIPT_BYTES = 32 * 1024 * 1024;

function estimateTranscriptBytes(msgs: ChatMessage[]): number {
	let bytes = 0;
	for (const msg of msgs) {
		bytes += 256 + msg.messageId.length * 2 + msg.timestamp.length * 2;
		for (const block of msg.contentBlocks) {
			bytes += 192 + block.text.length * 2;
			bytes += (block.toolCallId?.length ?? 0) * 2;
			bytes += (block.toolName?.length ?? 0) * 2;
			bytes += (block.toolArguments?.length ?? 0) * 2;
			bytes += (block.toolResult?.length ?? 0) * 2;
			for (const image of block.images ?? []) {
				bytes += 128 + image.base64.length * 2 + image.mimeType.length * 2;
			}
		}
	}
	return bytes;
}

function evictStaleSessionCaches(currentSid: string): void {
	const all = get(messagesBySession);
	const ids = Object.keys(all);
	const byteSizes = new Map(
		ids.map((id) => {
			const bytes = sessionEstimatedBytes.get(id) ?? estimateTranscriptBytes(all[id]);
			sessionEstimatedBytes.set(id, bytes);
			return [id, bytes];
		})
	);
	let totalBytes = ids.reduce((total, id) => total + (byteSizes.get(id) ?? 0), 0);
	if (ids.length <= MAX_CACHED_SESSIONS && totalBytes <= MAX_CACHED_TRANSCRIPT_BYTES) return;

	const pinnedSessionIds = new Set(
		paneManager.panes
			.map((pane) => pane.sessionId)
			.filter((sessionId): sessionId is string => Boolean(sessionId))
	);
	pinnedSessionIds.add(currentSid);

	const evictable = ids
		.filter(
			(id) =>
				!pinnedSessionIds.has(id) &&
				!promptLifecycle.isActive(id) &&
				!replayActiveForSession.has(id)
		)
		.sort((a, b) => (sessionTouchOrder.get(a) ?? 0) - (sessionTouchOrder.get(b) ?? 0));
	const evicted: string[] = [];
	for (const id of evictable) {
		if (
			ids.length - evicted.length <= MAX_CACHED_SESSIONS &&
			totalBytes <= MAX_CACHED_TRANSCRIPT_BYTES
		) {
			break;
		}
		evicted.push(id);
		totalBytes -= byteSizes.get(id) ?? 0;
	}
	if (evicted.length === 0) return;

	messagesBySession.update((m) => {
		const next = { ...m };
		for (const id of evicted) {
			delete next[id];
			sessionTouchOrder.delete(id);
			loadedSessionIds.delete(id);
			sessionEstimatedBytes.delete(id);
		}
		return next;
	});
}

// Keep active-view stores in sync when current session changes.
currentSessionId.subscribe((sid) => {
	if (!sid) {
		messages.set([]);
		isStreaming.set(false);
		return;
	}
	const allMessages = get(messagesBySession);
	messages.set(allMessages[sid] ?? []);
	const allStreaming = get(streamingBySession);
	isStreaming.set(allStreaming[sid] ?? false);
	sessionTouchOrder.set(sid, ++sessionTouchCounter);
	evictStaleSessionCaches(sid);
});

/** Load saved messages for a session */
export async function loadMessages(sessionId: string): Promise<void> {
	// Cached sessions render instantly from memory. Refetching on every switch
	// replaced the array with backend-ID'd copies — every message key changed,
	// so the whole pane destroyed and re-parsed each ChatMessage (a visible
	// multi-hundred-ms hitch) — and a snapshot racing a live stream could
	// overwrite chunks that arrived after the fetch started. The streaming and
	// replay paths own cache updates; the backend fetch is only for cold loads.
	if (loadedSessionIds.has(sessionId)) {
		return;
	}
	if (promptLifecycle.isActive(sessionId)) {
		return;
	}

	const requestId = ++loadRequestCounter;
	loadRequestIds.set(sessionId, requestId);
	const replayEpochAtStart = replayEpochs.get(sessionId) ?? 0;
	try {
		const msgs = await getSessionMessages(sessionId);
		if (loadRequestIds.get(sessionId) !== requestId) return;
		if (
			replayActiveForSession.has(sessionId) ||
			(replayEpochs.get(sessionId) ?? 0) !== replayEpochAtStart
		) {
			return;
		}
		setSessionMessages(sessionId, normalizeLoadedMessages(msgs));
		setSessionStreaming(
			sessionId,
			promptLifecycle.isActive(sessionId) ||
				isPromptingState(get(sessionStates)[sessionId]?.state)
		);
	} catch (e) {
		if (loadRequestIds.get(sessionId) !== requestId) return;
		if (
			replayActiveForSession.has(sessionId) ||
			(replayEpochs.get(sessionId) ?? 0) !== replayEpochAtStart
		) {
			return;
		}
		console.warn('Failed to load messages:', e);
		setSessionMessages(sessionId, [], false);
		setSessionStreaming(sessionId, false);
	}
}

export type PromptSubmissionResult = { sent: boolean; error?: string };

/** Send a user message and commit optimistic state only after native acceptance. */
export async function sendMessage(
	sessionId: string,
	text: string
): Promise<PromptSubmissionResult> {
	if (!sessionId || !text.trim())
		return { sent: false, error: 'A session and prompt are required.' };
	const requestId = createUUID();
	const userMsg: ChatMessage = {
		messageId: createUUID(),
		role: 'user',
		isStreaming: false,
		timestamp: new Date().toISOString(),
		contentBlocks: [{ type: 'text', text: text.trim(), isStreaming: false }]
	};
	promptLifecycle.beginPrompt(sessionId, requestId);
	beginKeyedPerformanceSpan('prompt_to_first_visible_update', sessionId, { requestId });
	setSessionStreaming(sessionId, true);
	updateSessionMessages(sessionId, (msgs) => [...msgs, userMsg]);
	try {
		const result = await sendPrompt(sessionId, text.trim(), requestId);
		if (result.requestId !== requestId) {
			throw new Error('The editor acknowledged a different prompt request.');
		}
		const acknowledgement = promptLifecycle.acknowledgePrompt(
			sessionId,
			requestId,
			result.accepted
		);
		if (!result.accepted) {
			if (acknowledgement === 'rejected') setSessionStreaming(sessionId, false);
			throw new Error(result.message || 'The agent rejected this prompt.');
		}
		addSubmittedPromptToHistory(text.trim());
		return { sent: true };
	} catch (e) {
		endKeyedPerformanceSpan('prompt_to_first_visible_update', sessionId, {
			requestId,
			failedBeforeResponse: true
		});
		console.warn('Failed to send prompt:', e);
		if (promptLifecycle.getPromptRequestId(sessionId) === requestId) {
			promptLifecycle.finish(sessionId);
			setSessionStreaming(sessionId, false);
		}
		updateSessionMessages(sessionId, (msgs) =>
			msgs.filter((m) => m.messageId !== userMsg.messageId)
		);
		return {
			sent: false,
			error: e instanceof Error ? e.message : String(e)
		};
	}
}

export type PromptCancellationResult = { cancelled: boolean; error?: string };

/** Cancel the current streaming prompt, keeping local state active until acknowledged. */
export async function cancelCurrentPrompt(sessionId: string): Promise<PromptCancellationResult> {
	if (!sessionId) return { cancelled: false, error: 'A session is required.' };
	if (get(cancellingBySession)[sessionId]) {
		return { cancelled: false, error: 'Cancellation is already in progress.' };
	}
	const requestId = createUUID();
	if (!promptLifecycle.beginCancellation(sessionId, requestId)) {
		return { cancelled: false, error: 'Cancellation is already in progress.' };
	}
	setSessionCancelling(sessionId, true);
	try {
		const result = await cancelPrompt(sessionId, requestId);
		if (result.requestId !== requestId) {
			throw new Error('The editor acknowledged a different cancellation request.');
		}
		promptLifecycle.acknowledgeCancellation(sessionId, requestId, result.accepted);
		if (!result.accepted) {
			throw new Error(result.message || 'The agent rejected cancellation.');
		}
		finishStreamingForSession(sessionId);
		return { cancelled: true };
	} catch (e) {
		promptLifecycle.acknowledgeCancellation(sessionId, requestId, false);
		console.warn('Failed to cancel prompt:', e);
		setSessionCancelling(sessionId, false);
		return {
			cancelled: false,
			error: e instanceof Error ? e.message : String(e)
		};
	}
}

/** Mark the current streaming message as complete */
export function finishStreaming(): void {
	const sid = get(currentSessionId);
	if (!sid) {
		isStreaming.set(false);
		return;
	}
	finishStreamingForSession(sid);
}

// ── Streaming Update Mutation ────────────────────────────────────────

function getOrCreateAssistantMessage(msgs: ChatMessage[]): ChatMessage {
	const last = msgs[msgs.length - 1];
	if (last?.role === 'assistant') {
		last.isStreaming = true;
		return last;
	}
	const newMsg: ChatMessage = {
		messageId: createUUID(),
		role: 'assistant',
		isStreaming: true,
		timestamp: new Date().toISOString(),
		contentBlocks: []
	};
	msgs.push(newMsg);
	return newMsg;
}

function appendToBlock(
	msg: ChatMessage,
	blockType: 'text' | 'thought',
	chunk: string,
	mutatedIndices: Set<number>
): void {
	const blocks = msg.contentBlocks;
	const lastIdx = blocks.length - 1;
	const lastBlock = blocks[lastIdx];
	if (lastBlock?.type === blockType) {
		lastBlock.text += chunk;
		lastBlock.isStreaming = true;
		mutatedIndices.add(lastIdx);
	} else {
		blocks.push({ type: blockType, text: chunk, isStreaming: true });
		mutatedIndices.add(blocks.length - 1);
	}
}

function stopStreamingOnMessage(msg: ChatMessage, mutatedIndices: Set<number>): void {
	msg.isStreaming = false;
	const blocks = msg.contentBlocks;
	for (let i = 0; i < blocks.length; i++) {
		if (blocks[i].isStreaming) {
			blocks[i].isStreaming = false;
			mutatedIndices.add(i);
		}
	}
}

/**
 * Apply a single streaming update to a working copy of the message array.
 * Mutates `msgs` in place and records touched block indices into
 * `mutatedIndices` so `cloneMessage` can clone only what actually changed.
 * Returns the modified assistant message.
 */
function applyStreamingUpdate(
	msgs: ChatMessage[],
	sessionId: string,
	update: StreamingUpdate,
	isActivePrompt: boolean,
	mutatedIndices: Set<number>
): ChatMessage | null {
	// Plan, usage, replay-control, and unknown events are routed elsewhere. Do
	// not create an empty assistant turn merely because one reached this reducer.
	if (!isAssistantMessageUpdate(update)) {
		return null;
	}
	const msg = getOrCreateAssistantMessage(msgs);

	switch (update.type) {
		case 'text_chunk':
			if (update.systemStatus) {
				const existingSystemIdx = msg.contentBlocks.findIndex(
					(b) => b.type === 'system' && b.systemStatus === 'compacting'
				);
				if (update.systemStatus === 'compacted' && existingSystemIdx >= 0) {
					const existingSystem = msg.contentBlocks[existingSystemIdx];
					existingSystem.text = update.text;
					existingSystem.systemStatus = 'compacted';
					existingSystem.isStreaming = false;
					mutatedIndices.add(existingSystemIdx);
				} else {
					msg.contentBlocks.push({
						type: 'system',
						text: update.text,
						isStreaming: update.systemStatus === 'compacting',
						systemStatus: update.systemStatus
					});
					mutatedIndices.add(msg.contentBlocks.length - 1);
				}
			} else {
				appendToBlock(msg, 'text', update.text, mutatedIndices);
			}
			break;

		case 'thought_chunk':
			appendToBlock(msg, 'thought', update.text, mutatedIndices);
			break;

		case 'tool_call': {
			const tcId = update.toolCallId || `gen_${createUUID()}`;
			const existingIdx = msg.contentBlocks.findIndex(
				(b) => b.type === 'tool_call' && b.toolCallId === tcId
			);
			if (existingIdx >= 0) {
				const existing = msg.contentBlocks[existingIdx];
				if (update.toolArguments) existing.toolArguments = update.toolArguments;
				if (update.toolName && !existing.toolName) existing.toolName = update.toolName;
				if (update.locations?.length) existing.locations = update.locations;
				if (update.parentToolCallId && !existing.parentToolCallId)
					existing.parentToolCallId = update.parentToolCallId;
				mutatedIndices.add(existingIdx);
			} else {
				// Stop streaming on any text/thought predecessors — record each touched index.
				const blocks = msg.contentBlocks;
				for (let i = 0; i < blocks.length; i++) {
					const b = blocks[i];
					if ((b.type === 'text' || b.type === 'thought') && b.isStreaming) {
						b.isStreaming = false;
						mutatedIndices.add(i);
					}
				}
				blocks.push({
					type: 'tool_call',
					text: '',
					isStreaming: isActivePrompt,
					toolCallId: tcId,
					toolName: update.toolName,
					toolArguments: update.toolArguments,
					locations: update.locations,
					parentToolCallId: update.parentToolCallId
				});
				mutatedIndices.add(blocks.length - 1);
			}
			break;
		}

		case 'tool_result': {
			const resultTcId = update.toolCallId;
			let toolCallIdx = msg.contentBlocks.findIndex(
				(b) => b.type === 'tool_call' && b.toolCallId === resultTcId
			);
			if (toolCallIdx < 0 && resultTcId) {
				msg.contentBlocks.push({
					type: 'tool_call',
					text: '',
					isStreaming: false,
					toolCallId: resultTcId,
					toolName: update.toolName || 'tool',
					toolArguments: '',
					parentToolCallId: update.parentToolCallId
				});
				toolCallIdx = msg.contentBlocks.length - 1;
				mutatedIndices.add(toolCallIdx);
			}
			if (toolCallIdx >= 0) {
				msg.contentBlocks[toolCallIdx].isStreaming = false;
				mutatedIndices.add(toolCallIdx);
			}
			const existingResultIdx = msg.contentBlocks.findIndex(
				(b) => b.type === 'tool_result' && b.toolCallId === resultTcId
			);
			if (existingResultIdx >= 0) {
				const existingResult = msg.contentBlocks[existingResultIdx];
				existingResult.toolResult = update.toolResult;
				existingResult.toolSuccess = update.toolSuccess;
				if (update.images) existingResult.images = update.images;
				mutatedIndices.add(existingResultIdx);
			} else {
				msg.contentBlocks.push({
					type: 'tool_result',
					text: '',
					isStreaming: false,
					toolCallId: resultTcId,
					toolResult: update.toolResult,
					toolSuccess: update.toolSuccess,
					images: update.images,
					parentToolCallId: update.parentToolCallId
				});
				mutatedIndices.add(msg.contentBlocks.length - 1);
			}
			break;
		}

		case 'error': {
			const sessionAgent =
				update.agentName || get(sessions).find((s) => s.sessionId === sessionId)?.agentName || '';
			const authReason = isLikelyAuthError(update, sessionAgent);
			if (authReason) {
				setAuthRequired(sessionAgent, authReason);
				stopStreamingOnMessage(msg, mutatedIndices);
				break;
			}
			const formattedError = formatAgentError(update, sessionAgent);
			const lastBlock = msg.contentBlocks[msg.contentBlocks.length - 1];
			if (lastBlock?.type === 'error' && lastBlock.text === formattedError) {
				mutatedIndices.add(msg.contentBlocks.length - 1);
			} else {
				msg.contentBlocks.push({
					type: 'error',
					text: formattedError,
					isStreaming: false
				});
				mutatedIndices.add(msg.contentBlocks.length - 1);
			}
			stopStreamingOnMessage(msg, mutatedIndices);
			break;
		}

		default:
			break;
	}

	if (!isActivePrompt) stopStreamingOnMessage(msg, mutatedIndices);
	return msg;
}

/**
 * Clone a message: new message ref, new contentBlocks array. Only blocks whose
 * indices are in `mutatedIndices` get fresh spreads — untouched blocks keep
 * their original references so downstream `$derived`/`$effect` chains that
 * reference individual blocks don't invalidate unnecessarily.
 */
function cloneMessage(msg: ChatMessage, mutatedIndices: Set<number>): ChatMessage {
	const blocks = msg.contentBlocks.slice();
	for (const i of mutatedIndices) {
		if (i >= 0 && i < blocks.length) {
			blocks[i] = { ...blocks[i] };
		}
	}
	return { ...msg, contentBlocks: blocks };
}

function finishStreamingInArray(msgs: ChatMessage[]): ChatMessage[] {
	const last = msgs[msgs.length - 1];
	if (!last?.isStreaming) return msgs;
	const finished: ChatMessage = {
		...last,
		isStreaming: false,
		contentBlocks: last.contentBlocks.map((b) => ({ ...b, isStreaming: false }))
	};
	return [...msgs.slice(0, -1), finished];
}

export function reduceStreamingUpdate(
	msgs: ChatMessage[],
	sessionId: string,
	update: StreamingUpdate,
	isActivePrompt: boolean
): ChatMessage[] {
	if (update.type === 'user_message_chunk') {
		const userMsg: ChatMessage = {
			messageId: createUUID(),
			role: 'user',
			isStreaming: false,
			timestamp: new Date().toISOString(),
			contentBlocks: [{ type: 'text', text: update.text, isStreaming: false }]
		};
		return [...finishStreamingInArray(msgs), userMsg];
	}
	if (!isAssistantMessageUpdate(update)) return msgs;

	const working = [...msgs];
	const mutatedIndices = new Set<number>();
	const msg = applyStreamingUpdate(working, sessionId, update, isActivePrompt, mutatedIndices);
	if (msg) {
		const idx = working.indexOf(msg);
		if (idx >= 0) working[idx] = cloneMessage(msg, mutatedIndices);
	}
	return working;
}

/** Reduce a private replay event batch in place and publish only once. */
function reduceReplayUpdates(sessionId: string, updates: StreamingUpdate[]): ChatMessage[] {
	let working: ChatMessage[] = [];
	for (const update of updates) {
		if (update.type === 'user_message_chunk') {
			working = finishStreamingInArray(working);
			working.push({
				messageId: createUUID(),
				role: 'user',
				isStreaming: false,
				timestamp: new Date().toISOString(),
				contentBlocks: [{ type: 'text', text: update.text, isStreaming: false }]
			});
			continue;
		}
		if (!isAssistantMessageUpdate(update)) continue;
		applyStreamingUpdate(working, sessionId, update, false, new Set<number>());
	}
	return working;
}

// ── RAF Batching ─────────────────────────────────────────────────────
// Accumulate streaming updates and flush once per animation frame.
// All updates for the same session are applied in a single mutation pass
// with ONE store write at the end — not one per update.

let pendingUpdates: Array<{ sessionId: string; update: StreamingUpdate }> = [];
let rafId: number | null = null;
let hiddenFlushTimer: ReturnType<typeof setTimeout> | null = null;

/** Cancel any scheduled RAF flush and apply the queue synchronously. */
function flushPendingUpdatesNow(): void {
	if (rafId !== null) {
		cancelAnimationFrame(rafId);
		rafId = null;
	}
	if (pendingUpdates.length > 0) {
		flushPendingUpdates();
	}
}

function beginHistoryReplay(sessionId: string, preserveCached: boolean): void {
	flushPendingUpdates();
	replayActiveForSession.add(sessionId);
	if (preserveCached) {
		replayPreserveCachedForSession.add(sessionId);
	} else {
		replayPreserveCachedForSession.delete(sessionId);
	}
	replayBuffers.set(sessionId, []);
	replayEpochs.set(sessionId, ++replayEpochCounter);
	setSessionStreaming(sessionId, false);
}

async function finishHistoryReplay(sessionId: string, replayEmpty: boolean): Promise<void> {
	flushPendingUpdates();
	const buffered = normalizeLoadedMessages(
		reduceReplayUpdates(sessionId, replayBuffers.get(sessionId) ?? [])
	);
	const preserveCached = replayPreserveCachedForSession.has(sessionId);
	replayActiveForSession.delete(sessionId);
	replayPreserveCachedForSession.delete(sessionId);
	replayBuffers.delete(sessionId);
	const finishEpoch = ++replayEpochCounter;
	replayEpochs.set(sessionId, finishEpoch);

	if (buffered.length > 0 && !preserveCached) {
		setSessionMessages(sessionId, buffered);
		setSessionStreaming(sessionId, false);
		return;
	}
	if (preserveCached && (get(messagesBySession)[sessionId]?.length ?? 0) > 0) {
		setSessionStreaming(sessionId, false);
		return;
	}

	// Empty replays can happen with older adapters. Keep the SQLite-backed cache if
	// one is already visible; otherwise ask the backend for its canonical snapshot.
	if (replayEmpty && (get(messagesBySession)[sessionId]?.length ?? 0) > 0) {
		setSessionStreaming(sessionId, false);
		return;
	}

	try {
		const msgs = await getSessionMessages(sessionId);
		if (
			(replayEpochs.get(sessionId) ?? 0) !== finishEpoch ||
			replayActiveForSession.has(sessionId)
		) {
			return;
		}
		if (msgs.length > 0) {
			setSessionMessages(sessionId, normalizeLoadedMessages(msgs));
		}
	} catch (e) {
		console.warn('Failed to refresh replayed messages:', e);
	}
	setSessionStreaming(sessionId, false);
}

function bufferReplayUpdate(sessionId: string, update: StreamingUpdate): void {
	if (update.type === 'usage' || update.type === 'plan' || update.type === 'unknown') {
		return;
	}
	const current = replayBuffers.get(sessionId) ?? [];
	current.push(update);
	replayBuffers.set(sessionId, current);
}

function queueStreamingUpdate(sessionId: string, update: StreamingUpdate): void {
	if (isSessionDisposed(sessionId)) return;
	if (update.type === 'history_replay_started') {
		beginHistoryReplay(sessionId, update.replayPreserveCached === true);
		return;
	}
	if (update.type === 'history_replay_finished') {
		void finishHistoryReplay(sessionId, update.replayEmpty === true);
		return;
	}
	if (replayActiveForSession.has(sessionId)) {
		bufferReplayUpdate(sessionId, update);
		return;
	}
	// Usage updates bypass RAF (low frequency, no DOM impact)
	if (update.type === 'usage') {
		handleUsageUpdate(update, sessionId);
		return;
	}
	if (update.type !== 'user_message_chunk' && !isAssistantMessageUpdate(update)) {
		return;
	}
	if (isAssistantMessageUpdate(update)) {
		endKeyedPerformanceSpanAfterPaint('prompt_to_first_visible_update', sessionId, {
			updateType: update.type
		});
	}
	// Errors and user_message_chunk are important — process immediately
	if (update.type === 'error' || update.type === 'user_message_chunk') {
		handleImmediateUpdate(sessionId, update);
		return;
	}
	pendingUpdates.push({ sessionId, update });
	if (rafId === null) {
		rafId = requestAnimationFrame(flushPendingUpdates);
	}
	// requestAnimationFrame never fires while CEF has the page hidden (chat tab
	// closed but the browser window kept alive for instant reopen) — arm a timer
	// fallback so updates keep applying and the queue can't grow unboundedly in
	// the background.
	if (hiddenFlushTimer === null && typeof document !== 'undefined' && document.hidden) {
		hiddenFlushTimer = setTimeout(() => {
			hiddenFlushTimer = null;
			flushPendingUpdatesNow();
		}, 250);
	}
}

function handleImmediateUpdate(sessionId: string, update: StreamingUpdate): void {
	// Preserve arrival order: RAF-queued chunks must land before this immediate
	// update, or the tail of the previous assistant turn gets appended into a
	// fresh message AFTER the interleaved user message (visible reordering).
	flushPendingUpdatesNow();

	const activeRequestId = promptLifecycle.getPromptRequestId(sessionId);
	if (
		update.type === 'error' &&
		update.requestId &&
		activeRequestId &&
		update.requestId !== activeRequestId
	) {
		console.warn(
			`Ignoring stale prompt error for ${sessionId}: expected ${activeRequestId}, received ${update.requestId}`
		);
		return;
	}

	if (update.type === 'user_message_chunk') {
		finishStreamingForSession(sessionId);
		const userMsg: ChatMessage = {
			messageId: createUUID(),
			role: 'user',
			isStreaming: false,
			timestamp: new Date().toISOString(),
			contentBlocks: [{ type: 'text', text: update.text, isStreaming: false }]
		};
		updateSessionMessages(sessionId, (msgs) => [...msgs, userMsg]);
		return;
	}

	// Error: apply via standard updateSessionMessages so store properly spreads
	const isActivePrompt = promptLifecycle.isActive(sessionId);
	promptLifecycle.finish(sessionId);
	setSessionCancelling(sessionId, false);
	updateSessionMessages(sessionId, (msgs) => {
		const working = [...msgs];
		const mutatedIndices = new Set<number>();
		const msg = applyStreamingUpdate(working, sessionId, update, isActivePrompt, mutatedIndices);
		if (msg) {
			const idx = working.indexOf(msg);
			if (idx >= 0) working[idx] = cloneMessage(msg, mutatedIndices);
		}
		return working;
	});
	setSessionStreaming(sessionId, false); // errors always stop streaming
}

function flushPendingUpdates(): void {
	rafId = null;
	const batch = pendingUpdates;
	pendingUpdates = [];

	// Group by sessionId to do one store write per session
	const bySession = new Map<string, StreamingUpdate[]>();
	for (const { sessionId, update } of batch) {
		let arr = bySession.get(sessionId);
		if (!arr) {
			arr = [];
			bySession.set(sessionId, arr);
		}
		arr.push(update);
	}

	for (const [sessionId, updates] of bySession) {
		const isActivePrompt = isTurnLive(sessionId);

		// ONE store write per session per frame
		updateSessionMessages(sessionId, (msgs) => {
			const working = [...msgs];
			let modifiedMsg: ChatMessage | null = null;
			// Accumulate touched block indices across every update in this batch
			// so cloneMessage only spreads the blocks that actually changed.
			const mutatedIndices = new Set<number>();

			for (const update of updates) {
				modifiedMsg = applyStreamingUpdate(
					working,
					sessionId,
					update,
					isActivePrompt,
					mutatedIndices
				);
			}

			// Clone the modified message so Svelte's keyed {#each} detects the change
			if (modifiedMsg) {
				const idx = working.indexOf(modifiedMsg);
				if (idx >= 0) working[idx] = cloneMessage(modifiedMsg, mutatedIndices);
			}

			return working;
		});

		// Set streaming state once per session per frame. isTurnLive, not the
		// prompt lifecycle alone: a remotely-initiated turn has no local
		// lifecycle entry, and reading only it here reset the remote turn's
		// streaming flag to false on every animation frame.
		setSessionStreaming(sessionId, isTurnLive(sessionId));
	}
}

// ── Binding ──────────────────────────────────────────────────────────

let messageBound = false;

/** Wire up streaming callbacks. Call once on mount. */
export function bindMessageListener(): void {
	if (messageBound) return;
	messageBound = true;

	onMessage(queueStreamingUpdate);

	const prevStates: Record<string, AgentConnectionState> = {};
	sessionStates.subscribe((states) => {
		for (const [sessionId, sessionState] of Object.entries(states)) {
			const prev = prevStates[sessionId];
			const cur = sessionState.state;
			if (isPromptingState(prev) && !isPromptingState(cur)) {
				finishStreamingForSession(sessionId);
			}
			// A turn started that this page did not send (remote surface
			// prompted this executor): mirror it as streaming so the pane
			// shows the working state and a live stop button, exactly like a
			// local send. Local sends already set this in sendMessage.
			if (
				!isPromptingState(prev) &&
				isPromptingState(cur) &&
				!promptLifecycle.isActive(sessionId)
			) {
				setSessionStreaming(sessionId, true);
			}
			prevStates[sessionId] = cur;
		}
	});
}

export function cleanupMessagesForSession(sessionId: string): void {
	loadRequestIds.delete(sessionId);
	loadedSessionIds.delete(sessionId);
	sessionEstimatedBytes.delete(sessionId);
	promptLifecycle.dispose(sessionId);
	replayActiveForSession.delete(sessionId);
	replayPreserveCachedForSession.delete(sessionId);
	replayBuffers.delete(sessionId);
	replayEpochs.delete(sessionId);
	sessionTouchOrder.delete(sessionId);
	pendingUpdates = pendingUpdates.filter((item) => item.sessionId !== sessionId);

	messagesBySession.update((all) => {
		const next = { ...all };
		delete next[sessionId];
		return next;
	});
	streamingBySession.update((all) => {
		const next = { ...all };
		delete next[sessionId];
		return next;
	});
	cancellingBySession.update((all) => {
		const next = { ...all };
		delete next[sessionId];
		return next;
	});
	if (get(currentSessionId) === sessionId) {
		messages.set([]);
		isStreaming.set(false);
	}
}

onSessionDisposed(cleanupMessagesForSession);
