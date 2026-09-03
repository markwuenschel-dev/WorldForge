import { writable, derived, get } from 'svelte/store';
import { toast } from 'svelte-sonner';
import {
	getSessions,
	onSessionsChanged,
	createSession,
	resumeSession,
	deleteSession as bridgeDeleteSession,
	onSessionListUpdated,
	refreshSessionList as bridgeRefreshSessionList,
	type SessionInfo
} from '$lib/bridge.js';
import { agents, canonicalAgentName, selectedAgent } from '$lib/stores/agents.js';
import { disposeSessionState, markSessionActive } from '$lib/stores/sessionLifecycle.js';
import { createOperationVersionTracker } from '$lib/operationVersions.js';
import {
	beginPerformanceSpan,
	endPerformanceSpan,
	endKeyedPerformanceSpanAfterPaint,
	beginKeyedPerformanceSpan
} from '$lib/performanceTelemetry.js';

export const sessions = writable<SessionInfo[]>([]);
export const currentSessionId = writable<string | null>(null);
export const isLoadingSessions = writable(false);
/** True while agents are being connected for session listing (initial load or manual refresh) */
export const isConnectingAgents = writable(false);

// ── Date Grouping ────────────────────────────────────────────────────

export type SessionGroup = {
	label: string;
	sessions: SessionInfo[];
};

/** Group sessions by date (Today, Yesterday, This Week, This Month, Older) */
export const groupedSessions = derived(sessions, ($sessions) => {
	const groups: SessionGroup[] = [];
	const groupMap = new Map<string, SessionInfo[]>();

	const now = new Date();
	const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
	const yesterday = new Date(today.getTime() - 86400000);
	const weekAgo = new Date(today.getTime() - 7 * 86400000);
	const monthAgo = new Date(today.getTime() - 30 * 86400000);

	for (const session of $sessions) {
		const date = new Date(session.lastModifiedAt);
		let label: string;

		if (date >= today) {
			label = 'Today';
		} else if (date >= yesterday) {
			label = 'Yesterday';
		} else if (date >= weekAgo) {
			label = 'This Week';
		} else if (date >= monthAgo) {
			label = 'This Month';
		} else {
			label = 'Older';
		}

		if (!groupMap.has(label)) {
			groupMap.set(label, []);
		}
		groupMap.get(label)!.push(session);
	}

	// Maintain consistent order
	const order = ['Today', 'Yesterday', 'This Week', 'This Month', 'Older'];
	for (const label of order) {
		const items = groupMap.get(label);
		if (items && items.length > 0) {
			groups.push({ label, sessions: items });
		}
	}

	return groups;
});

// ── Session Lifecycle ────────────────────────────────────────────────

/** Load all sessions from the backend, sorted by most recent first.
 *  This pulls cached data — agents connected later will push updates. */
export async function loadSessions(): Promise<void> {
	isLoadingSessions.set(true);
	try {
		const rawList = (await getSessions()).map((session) => ({
			...session,
			agentName: canonicalAgentName(session.agentName)
		}));
		// The bridge aggregates several sources (agent histories, chat store) —
		// dedupe by id up front; duplicates crash every keyed each downstream.
		const seenIds = new Set<string>();
		const list = rawList.filter((session) => {
			if (seenIds.has(session.sessionId)) return false;
			seenIds.add(session.sessionId);
			return true;
		});
		for (const session of list) markSessionActive(session.sessionId);
		list.sort(
			(a, b) => new Date(b.lastModifiedAt).getTime() - new Date(a.lastModifiedAt).getTime()
		);
		// Merge with existing sessions instead of replacing — push updates may
		// have already arrived from agents while this async call was in flight.
		sessions.update((current) => {
			if (current.length === 0) return list;
			const merged = [...current];
			for (const s of list) {
				const existingIndex = merged.findIndex((item) => item.sessionId === s.sessionId);
				if (existingIndex === -1) {
					merged.push(s);
					continue;
				}
				const existing = merged[existingIndex];
				const hasCustom = existing.hasCustomTitle || s.hasCustomTitle;
				merged[existingIndex] = {
					...existing,
					...s,
					// Preserve custom titles — never let remote sync overwrite a user rename
					title: hasCustom
						? existing.hasCustomTitle
							? existing.title
							: s.title
						: s.title || existing.title,
					hasCustomTitle: hasCustom,
					messageCount: s.messageCount ?? existing.messageCount,
					createdAt: s.createdAt ?? existing.createdAt,
					lastModifiedAt: s.lastModifiedAt ?? existing.lastModifiedAt,
					isConnected: s.isConnected ?? existing.isConnected,
					isActive: (existing.isActive ?? false) || (s.isActive ?? false)
				};
			}
			merged.sort(
				(a, b) =>
					new Date(b.lastModifiedAt || 0).getTime() - new Date(a.lastModifiedAt || 0).getTime()
			);
			return merged;
		});
	} catch (e) {
		console.warn('Failed to load sessions from bridge:', e);
	} finally {
		isLoadingSessions.set(false);
	}
}

/** De-duplicate one UI origin without blocking independent panes. */
const sessionCreationsByOrigin = new Map<string, Promise<string | null>>();

/** Create a new session for the given agent and make it current */
export async function createNewSession(
	agentName: string,
	requestOrigin = `default:${agentName}`
): Promise<string | null> {
	const existing = sessionCreationsByOrigin.get(requestOrigin);
	if (existing) return existing;

	const operation = (async (): Promise<string | null> => {
		try {
			const result = await createSession(agentName);
			markSessionActive(result.sessionId);
			const newSession: SessionInfo = {
				sessionId: result.sessionId,
				agentName: result.agentName,
				title: '',
				messageCount: 0,
				createdAt: new Date().toISOString(),
				lastModifiedAt: new Date().toISOString(),
				isConnected: false,
				isActive: true
			};
			// Prepend to list (most recent first)
			sessions.update((list) => [newSession, ...list]);
			currentSessionId.set(result.sessionId);
			return result.sessionId;
		} catch (e) {
			console.warn('Failed to create session:', e);
			toast.error(`Failed to start a ${agentName} session`, {
				description: e instanceof Error ? e.message : String(e)
			});
			return null;
		}
	})();

	sessionCreationsByOrigin.set(requestOrigin, operation);
	try {
		return await operation;
	} finally {
		if (sessionCreationsByOrigin.get(requestOrigin) === operation) {
			sessionCreationsByOrigin.delete(requestOrigin);
		}
	}
}

/** Select a session — flips UI immediately, then resumes from disk in the
 *  background. The game-thread resumeSession call can take hundreds of ms,
 *  so we update currentSessionId optimistically for instant sidebar feedback.
 *  Returns the agent name on success for downstream model/mode loading. */
const sessionSelectionVersions = createOperationVersionTracker();

export async function selectSession(sessionId: string): Promise<string | null> {
	beginKeyedPerformanceSpan('session_switch_visible', 'active-selection', { sessionId });
	const resumeSpan = beginPerformanceSpan('session_resume_bridge', { sessionId });
	markSessionActive(sessionId);
	const selectionVersion = sessionSelectionVersions.begin('selection');
	const previousSessionId = get(currentSessionId);
	const previousAgent = get(selectedAgent);
	const isCurrentSelection = () =>
		sessionSelectionVersions.isCurrent('selection', selectionVersion) &&
		get(currentSessionId) === sessionId;

	// Optimistic UI flip: sidebar highlights the new chat immediately.
	// If the session exists in the list we can also pre-select its agent
	// from cached session metadata so the composer stops showing the old agent.
	const cachedSession = get(sessions).find((s) => s.sessionId === sessionId);
	if (cachedSession?.agentName) {
		const sessionAgent = get(agents).find(
			(a) => a.name === canonicalAgentName(cachedSession.agentName)
		);
		if (sessionAgent) selectedAgent.set(sessionAgent);
	}
	currentSessionId.set(sessionId);
	endKeyedPerformanceSpanAfterPaint('session_switch_visible', 'active-selection', { sessionId });

	const agentLabel = cachedSession?.agentName
		? canonicalAgentName(cachedSession.agentName)
		: 'agent';
	try {
		const result = await resumeSession(sessionId);
		endPerformanceSpan(resumeSpan, { success: result.success });
		if (!isCurrentSelection()) return null;
		const resumedAgentName = result.agentName;
		if (result.success && resumedAgentName) {
			// Confirm agent (in case cached metadata was stale)
			const canonicalName = canonicalAgentName(resumedAgentName);
			const sessionAgent = get(agents).find((a) => a.name === canonicalName);
			if (sessionAgent) selectedAgent.set(sessionAgent);
			return canonicalName;
		}
		// Backend reported failure without throwing — the pane would stay blank
		// with no explanation otherwise.
		console.warn('Failed to resume session:', result.error);
		toast.error(`Failed to resume ${agentLabel} session`, {
			description: result.error || 'The agent could not load this session.'
		});
	} catch (e) {
		endPerformanceSpan(resumeSpan, { failed: true });
		if (!isCurrentSelection()) return null;
		console.warn('Failed to resume session:', e);
		toast.error(`Failed to resume ${agentLabel} session`, {
			description: e instanceof Error ? e.message : String(e)
		});
	}

	// Roll back only if this failed request is still the user's active choice.
	// A later click owns the UI and must never be overwritten by this completion.
	if (isCurrentSelection()) {
		currentSessionId.set(previousSessionId);
		selectedAgent.set(previousAgent);
	}
	return null;
}

/** Delete a session, clearing current if it's the active one */
export async function removeSession(sessionId: string): Promise<boolean> {
	try {
		const result = await bridgeDeleteSession(sessionId);
		if (result.success) {
			disposeSessionState(sessionId);
			sessions.update((list) => list.filter((s) => s.sessionId !== sessionId));
			if (get(currentSessionId) === sessionId) {
				currentSessionId.set(null);
			}
		}
		return result.success;
	} catch (e) {
		console.warn('Failed to delete session:', e);
		return false;
	}
}

const relativeTimeFormatter = new Intl.RelativeTimeFormat(undefined, {
	numeric: 'auto',
	style: 'narrow'
});

/** Format an ISO date string using the user's locale. */
export function formatTimeAgo(isoDate?: string): string {
	if (!isoDate) return relativeTimeFormatter.format(0, 'second');
	const now = Date.now();
	const then = new Date(isoDate).getTime();
	if (!Number.isFinite(then)) return relativeTimeFormatter.format(0, 'second');
	const seconds = Math.floor((now - then) / 1000);

	if (seconds < 60) return relativeTimeFormatter.format(0, 'second');
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return relativeTimeFormatter.format(-minutes, 'minute');
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return relativeTimeFormatter.format(-hours, 'hour');
	const days = Math.floor(hours / 24);
	if (days < 30) return relativeTimeFormatter.format(-days, 'day');
	const months = Math.floor(days / 30);
	return relativeTimeFormatter.format(-months, 'month');
}

// ── Session List Push Updates ─────────────────────────────────────────

let sessionListBound = false;
let connectingTimeout: ReturnType<typeof setTimeout> | null = null;

/** Bind to push-based session list updates from agents. Call once on mount. */
export function bindSessionListListener(): void {
	if (sessionListBound) return;
	sessionListBound = true;

	// Chats created outside this page (a chat assigned from web/desktop that
	// the session mirror adopts, a native panel opening one) used to appear
	// only after a manual refresh. The native side pings; refetch the list —
	// loadSessions() merges, so an in-flight load is safe. Debounced because
	// adoption fires created+active-changed back to back.
	let sessionsChangedTimer: ReturnType<typeof setTimeout> | null = null;
	onSessionsChanged(() => {
		if (sessionsChangedTimer) clearTimeout(sessionsChangedTimer);
		sessionsChangedTimer = setTimeout(() => {
			sessionsChangedTimer = null;
			void loadSessions();
		}, 150);
	});

	onSessionListUpdated((agentName, remoteSessions) => {
		for (const session of remoteSessions) markSessionActive(session.sessionId);
		// Sessions arrived — clear connecting state
		isConnectingAgents.set(false);
		if (connectingTimeout) {
			clearTimeout(connectingTimeout);
			connectingTimeout = null;
		}

		sessions.update((current) => {
			// Remove old remote sessions for this agent (keep active/in-memory ones)
			const kept = current.filter((s) => s.agentName !== agentName || s.isActive);

			// Build lookup for remote sessions
			const remoteMap = new Map(remoteSessions.map((rs) => [rs.sessionId, rs]));

			// Update local active sessions with remote data (title, messageCount, etc.)
			for (const s of kept) {
				const remote = remoteMap.get(s.sessionId);
				if (remote && s.isActive) {
					// Never let remote sync overwrite a user-renamed title
					if (remote.hasCustomTitle) {
						s.title = remote.title;
						s.hasCustomTitle = true;
					} else if (remote.title && !s.hasCustomTitle) {
						s.title = remote.title;
					}
					if (remote.messageCount !== undefined) s.messageCount = remote.messageCount;
					if (remote.lastModifiedAt) s.lastModifiedAt = remote.lastModifiedAt;
					if (remote.registryId !== undefined) s.registryId = remote.registryId;
					if (remote.terminalResumeSupported !== undefined) {
						s.terminalResumeSupported = remote.terminalResumeSupported;
					}
				}
			}

			// Merge in new remote sessions, skipping any that already exist —
			// including duplicates WITHIN this push (paginated agent listings
			// can repeat a session across cursor pages; a duplicate id crashes
			// every keyed each over the list).
			const existingIds = new Set(kept.map((s) => s.sessionId));
			for (const rs of remoteSessions) {
				if (!existingIds.has(rs.sessionId)) {
					existingIds.add(rs.sessionId);
					kept.push(rs);
				}
			}

			// Sort by most recent
			kept.sort(
				(a, b) =>
					new Date(b.lastModifiedAt || 0).getTime() - new Date(a.lastModifiedAt || 0).getTime()
			);
			return kept;
		});
	});

	// The C++ side auto-connects agents when this listener binds.
	// Show connecting state so the user sees activity.
	isConnectingAgents.set(true);

	// Safety timeout: stop showing "connecting" after 15 seconds even
	// if no sessions arrive (agents may be unavailable).
	connectingTimeout = setTimeout(() => {
		isConnectingAgents.set(false);
		connectingTimeout = null;
	}, 15000);
}

/** Manually refresh session lists from all agents */
export async function refreshSessions(): Promise<void> {
	isConnectingAgents.set(true);
	if (connectingTimeout) clearTimeout(connectingTimeout);

	try {
		await bridgeRefreshSessionList();
	} catch (e) {
		console.warn('Failed to refresh session list:', e);
	}

	// Timeout: stop showing connecting state after 15 seconds
	connectingTimeout = setTimeout(() => {
		isConnectingAgents.set(false);
		connectingTimeout = null;
	}, 15000);
}
