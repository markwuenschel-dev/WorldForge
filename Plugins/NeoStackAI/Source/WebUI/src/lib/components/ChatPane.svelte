<script lang="ts">
	import { tick, onMount, onDestroy } from 'svelte';
	import ChatMessageComponent from '$lib/components/ChatMessage.svelte';
	import PermissionDialog from '$lib/components/PermissionDialog.svelte';
	import AskUserDialog from '$lib/components/AskUserDialog.svelte';
	import ContextPopup from '$lib/components/ContextPopup.svelte';
	import CommandPopup from '$lib/components/CommandPopup.svelte';
	import PlanPanel from '$lib/components/PlanPanel.svelte';
	import { loadAgentUpdates } from '$lib/stores/registry.js';
	import AttachmentChips from '$lib/components/AttachmentChips.svelte';
	import ChatSearchBar from '$lib/components/ChatSearchBar.svelte';
	import AgentConfigMenu from '$lib/components/AgentConfigMenu.svelte';
	import { Shimmer } from '$lib/components/ai-elements/shimmer/index.js';
	import Icon from '$lib/components/Icon.svelte';
	import { modKey } from '$lib/platform.js';
	import {
		Add01Icon,
		ArrowUp01Icon,
		ArrowDown01Icon,
		StopIcon,
		GitBranchIcon,
		ChangeScreenModeIcon
	} from '@hugeicons/core-free-icons';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu/index.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import {
		messagesBySession,
		streamingBySession,
		cancellingBySession,
		sendMessage,
		cancelCurrentPrompt,
		loadMessages
	} from '$lib/stores/messages.js';
	import { sessions } from '$lib/stores/sessions.js';
	import { agents, selectedAgent } from '$lib/stores/agents.js';
	import { isPromptingState, sessionStates, mcpStatusMap } from '$lib/stores/agentState.js';
	import { permissionQueues, sessionsNeedingAttention } from '$lib/stores/permissions.js';
	import { commandsBySession } from '$lib/stores/commands.js';
	import { planBySession } from '$lib/stores/plan.js';
	import {
		modelStatesByAgent,
		changeModel,
		changeReasoningLevel,
		loadModelsForAgent,
		loadReasoningLevel,
		reasoningLabels,
		type ReasoningLevel
	} from '$lib/stores/models.js';
	import {
		modeStatesByAgent,
		changeMode,
		loadModesForAgent,
		isInPlanMode
	} from '$lib/stores/modes.js';
	import {
		configOptionStatesBySession,
		changeSessionConfigOption,
		loadConfigOptionsForSession
	} from '$lib/stores/configOptions.js';
	import {
		usageBySession,
		defaultUsage,
		formatTokens,
		formatCost,
		formatDurationMs
	} from '$lib/stores/usage.js';
	import { scEnabled, branchName, hasChanges, changesLabel } from '$lib/stores/sourceControl.js';
	import { openSourceControlChangelist, openSourceControlSubmit } from '$lib/bridge.js';
	import { pasteImage, pickAttachments, loadAttachments } from '$lib/stores/attachments.js';
	import { addDraftToHistory, getComposerHistoryEntries } from '$lib/stores/composerHistory.js';
	import { enterToSend } from '$lib/stores/settings.js';
	import {
		copyToClipboard,
		getClipboardText,
		type SlashCommand,
		type PermissionRequest
	} from '$lib/bridge.js';
	import { t } from '$lib/i18n.js';
	import { toast } from 'svelte-sonner';
	import {
		buildVirtualRows,
		getAnchorAdjustment,
		getVisibleVirtualRows
	} from '$lib/virtualRows.js';
	import { recordInteractionLatency } from '$lib/performanceTelemetry.js';

	interface Props {
		sessionId: string | null;
		isFocused: boolean;
		showPaneHeader?: boolean;
		onStartSession?: (agentName: string) => void;
	}

	let { sessionId, isFocused, showPaneHeader = false, onStartSession }: Props = $props();

	// ── Per-pane state ──────────────────────────────────────────────────
	let scrollContainer: HTMLDivElement | undefined = $state();
	let bottomSentinel: HTMLDivElement | undefined = $state();
	let textareaEl: HTMLTextAreaElement | undefined = $state();
	let inputText = $state('');
	let userNearBottom = $state(true);
	let isTextComposing = $state(false);
	let historyIndex = $state<number | null>(null);
	let draftBeforeHistory = $state('');
	let lastEscapeAt = $state(0);
	let dragOver = $state(false);

	// Popup state
	let contextPopupVisible = $state(false);
	let contextQuery = $state('');
	let contextPopupRef: ContextPopup | undefined = $state();
	let mentionStartPos = $state(-1);
	let completedMention: { start: number; end: number; value: string } | null = $state(null);
	let commandPopupVisible = $state(false);
	let commandQuery = $state('');
	let commandPopupRef: CommandPopup | undefined = $state();

	// In-chat search
	let chatSearchVisible = $state(false);

	function handleGlobalKeydown(e: KeyboardEvent) {
		if (isFocused && (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'f') {
			e.preventDefault();
			chatSearchVisible = true;
		}
	}

	onMount(() => {
		window.addEventListener('keydown', handleGlobalKeydown);
		// Lazily check for agent updates so the banner can render. Cheap (just reads cached
		// FACPRegistryClient state); the registry refresh ticker handles network polling.
		loadAgentUpdates();
	});

	onDestroy(() => {
		window.removeEventListener('keydown', handleGlobalKeydown);
		if (resizeRafId !== null) {
			cancelAnimationFrame(resizeRafId);
			resizeRafId = null;
		}
		if (scrollRafId !== null) {
			cancelAnimationFrame(scrollRafId);
			scrollRafId = null;
		}
		if (searchHighlightTimer) clearTimeout(searchHighlightTimer);
	});

	// Context menu
	let ctxMenuVisible = $state(false);
	let ctxMenuX = $state(0);
	let ctxMenuY = $state(0);
	let ctxMenuHasSelection = $state(false);
	let ctxMenuIsInput = $state(false);

	const DOUBLE_ESCAPE_WINDOW_MS = 900;
	const COMMON_FILESYSTEM_ROOTS = new Set([
		'Applications',
		'Users',
		'private',
		'tmp',
		'var',
		'etc',
		'System',
		'Volumes',
		'home',
		'opt',
		'usr',
		'bin',
		'sbin',
		'dev'
	]);

	// ── Derived state ───────────────────────────────────────────────────
	let paneMessages = $derived(sessionId ? ($messagesBySession[sessionId] ?? []) : []);
	let paneIsStreaming = $derived(sessionId ? ($streamingBySession[sessionId] ?? false) : false);
	let paneIsCancelling = $derived(sessionId ? ($cancellingBySession[sessionId] ?? false) : false);
	let sessionInfo = $derived($sessions.find((s) => s.sessionId === sessionId));
	let sessionAgent = $derived(sessionInfo?.agentName ?? '');
	let sessionAgentInfo = $derived($agents.find((a) => a.name === sessionAgent));
	let paneModelState = $derived(sessionAgent ? $modelStatesByAgent[sessionAgent] : undefined);
	let paneModeState = $derived(sessionAgent ? $modeStatesByAgent[sessionAgent] : undefined);
	let paneConfigOptionState = $derived(
		sessionId ? $configOptionStatesBySession[sessionId] : undefined
	);
	let paneState = $derived(sessionId ? $sessionStates[sessionId] : undefined);
	let isWorking = $derived(isPromptingState(paneState?.state));
	let isQueued = $derived(paneState?.state === 'prompting_queued_tool');
	let needsAttention = $derived(sessionId ? $sessionsNeedingAttention.has(sessionId) : false);
	let waitingForMcp = $derived(sessionId ? $mcpStatusMap[sessionId] === 'waiting' : false);

	// Permission for THIS pane's session
	let panePermission = $derived.by((): PermissionRequest | null => {
		if (!sessionId) return null;
		const queue = $permissionQueues[sessionId] ?? [];
		return queue[0] ?? null;
	});

	// Commands for this pane
	let paneCommands = $derived<SlashCommand[]>(
		sessionId ? ($commandsBySession[sessionId] ?? []) : []
	);

	// Plan for this pane (reads from per-session plan store)
	let panePlan = $derived(sessionId ? ($planBySession[sessionId] ?? null) : null);
	let paneHasPlan = $derived(panePlan !== null && panePlan.entries.length > 0);

	// Each mounted pane loads configuration for its own agent. The stores cache
	// by agent, so panes never borrow the focused pane's controls and duplicate
	// panes for the same agent share one authoritative backend state.
	$effect(() => {
		const agentName = sessionAgent;
		if (!agentName) return;
		void loadModelsForAgent(agentName);
		void loadReasoningLevel(agentName);
		void loadModesForAgent(agentName);
	});

	$effect(() => {
		const activeSessionId = sessionId;
		if (!activeSessionId) return;
		void loadConfigOptionsForSession(activeSessionId);
	});

	// Model/reasoning/mode changes revert their optimistic store update and
	// rethrow on failure — surface that instead of an unhandled rejection.
	function handleChangeModel(agentName: string, modelId: string) {
		changeModel(agentName, modelId).catch((e: unknown) => {
			toast.error($t('change_model_failed'), {
				description: e instanceof Error ? e.message : String(e)
			});
		});
	}

	function handleChangeReasoningLevel(level: ReasoningLevel, agentName: string) {
		changeReasoningLevel(level, agentName).catch((e: unknown) => {
			toast.error($t('change_reasoning_failed'), {
				description: e instanceof Error ? e.message : String(e)
			});
		});
	}

	function handleChangeMode(agentName: string, modeId: string) {
		changeMode(agentName, modeId).catch((e: unknown) => {
			toast.error($t('change_mode_failed'), {
				description: e instanceof Error ? e.message : String(e)
			});
		});
	}

	function handleChangeConfigOption(configId: string, value: string | boolean) {
		if (!sessionId) return;
		changeSessionConfigOption(sessionId, configId, value).catch((e: unknown) => {
			toast.error('Could not change session setting', {
				description: e instanceof Error ? e.message : String(e)
			});
		});
	}

	// Model/reasoning for this pane's composer
	let paneModels = $derived(paneModelState?.models ?? []);
	let paneCurrentModelId = $derived(paneModelState?.currentModelId ?? '');
	let paneModelsLoading = $derived(paneModelState?.isLoading ?? false);
	let paneReasoningLevel = $derived(paneModelState?.reasoningLevel ?? 'high');
	let hasModels = $derived(paneModels.length > 0);
	let paneConfigOptions = $derived(paneConfigOptionState?.options ?? []);
	let hasConfigOptions = $derived(paneConfigOptions.length > 0);
	let hasGenericModelOption = $derived(
		paneConfigOptions.some(
			(option) => option.type === 'select' && (option.category === 'model' || option.id === 'model')
		)
	);
	let hasGenericReasoningOption = $derived(
		paneConfigOptions.some(
			(option) =>
				option.type === 'select' &&
				(option.category === 'thought_level' || option.id === 'thinking')
		)
	);
	let hasGenericModeOption = $derived(
		paneConfigOptions.some(
			(option) => option.type === 'select' && (option.category === 'mode' || option.id === 'mode')
		)
	);
	let modelOptions = $derived(paneModels);
	let currentModel = $derived(paneModels.find((m) => m.id === paneCurrentModelId));
	let modelDisplayName = $derived(currentModel?.name ?? paneCurrentModelId ?? 'Model');
	let groupedModelOptions = $derived.by(() => {
		const groups: { provider: string; models: typeof modelOptions }[] = [];
		const modelsByProvider: Record<string, typeof modelOptions> = Object.create(null);
		const providerOrder: string[] = [];
		// Duplicate model ids crash the keyed each (Svelte 5 hard-errors) —
		// render each id once no matter what the backend pushed.
		const seenModelIds = new Set<string>();
		for (const m of modelOptions) {
			if (seenModelIds.has(m.id)) continue;
			seenModelIds.add(m.id);
			const key = m.providerDisplayName || m.provider || '';
			if (!modelsByProvider[key]) {
				modelsByProvider[key] = [];
				providerOrder.push(key);
			}
			modelsByProvider[key].push(m);
		}
		// Custom/non-OpenRouter providers first, then OpenRouter
		for (const provider of providerOrder) {
			if (provider.toLowerCase() !== 'openrouter') {
				groups.push({ provider, models: modelsByProvider[provider] });
			}
		}
		const orModels = modelsByProvider.OpenRouter ?? modelsByProvider.openrouter;
		if (orModels) groups.push({ provider: 'OpenRouter', models: orModels });
		// If only one group or no provider names, return flat
		return groups;
	});
	let currentModelSupportsReasoning = $derived(currentModel?.supportsReasoning ?? false);
	const reasoningLevels: ReasoningLevel[] = ['none', 'low', 'medium', 'high', 'max'];

	// Mode selector
	let paneModes = $derived(paneModeState?.modes ?? []);
	let paneCurrentModeId = $derived(paneModeState?.currentModeId ?? '');
	let hasModes = $derived(paneModes.length > 0);
	let currentMode = $derived(paneModes.find((m) => m.id === paneCurrentModeId));
	let modeDisplayName = $derived(currentMode?.name ?? paneCurrentModeId ?? 'Default');
	let isPlanMode = $derived(isInPlanMode(paneCurrentModeId));

	// Usage display
	let paneUsage = $derived(
		sessionId ? ($usageBySession[sessionId] ?? { ...defaultUsage }) : { ...defaultUsage }
	);
	let paneContextPercent = $derived(
		paneUsage.contextSize > 0
			? Math.min(100, Math.round((paneUsage.contextUsed / paneUsage.contextSize) * 100))
			: 0
	);
	let usageHasContext = $derived(paneUsage.contextSize > 0);
	let usageHasTokens = $derived(paneUsage.inputTokens > 0 || paneUsage.outputTokens > 0);
	let usageHasCost = $derived(paneUsage.costAmount > 0);
	let usageContextLabel = $derived.by(() => {
		if (usageHasContext) return `${paneContextPercent}%`;
		if (usageHasTokens) return `${formatTokens(paneUsage.inputTokens + paneUsage.outputTokens)}`;
		return '';
	});

	let agentReady = $derived.by(() => {
		if (waitingForMcp) return false;
		const state = paneState?.state;
		if (state === 'ready' || state === 'in_session' || isPromptingState(state)) return true;
		if (!state && sessionId) return true;
		return false;
	});

	let canSend = $derived(
		inputText.trim().length > 0 && !!sessionId && !paneIsStreaming && !isWorking && agentReady
	);

	let inputPlaceholder = $derived(
		waitingForMcp
			? $t('connecting_tools')
			: !agentReady
				? $t('waiting_for_agent')
				: paneMessages.length > 0
					? $t('ask_follow_up')
					: $t('describe_task')
	);

	// ── Measured transcript virtualization ──────────────────────────────
	// Rows begin with a role-based estimate, then ResizeObserver measurements refine
	// the layout. Only the viewport and a small pixel overscan are mounted.
	const TRANSCRIPT_OVERSCAN = 700;
	let measuredMessageHeights: Record<string, number> = $state({});
	let transcriptScrollTop = $state(0);
	let transcriptViewportHeight = $state(800);
	let prevWindowSessionId: string | null = null;
	$effect(() => {
		if (sessionId !== prevWindowSessionId) {
			prevWindowSessionId = sessionId;
			measuredMessageHeights = {};
			transcriptScrollTop = 0;
			userNearBottom = true;
		}
	});

	function estimateMessageHeight(message: (typeof paneMessages)[number]) {
		if (message.role === 'system') return 64;
		if (message.role === 'user') return 88;
		return Math.max(140, Math.min(420, 92 + message.contentBlocks.length * 72));
	}

	let virtualLayout = $derived(
		buildVirtualRows(
			paneMessages,
			(message) => message.messageId,
			measuredMessageHeights,
			estimateMessageHeight
		)
	);
	let virtualRowById = $derived(new Map(virtualLayout.rows.map((row) => [row.key, row])));
	let visibleVirtualRows = $derived(
		getVisibleVirtualRows(
			virtualLayout.rows,
			transcriptScrollTop,
			transcriptViewportHeight,
			TRANSCRIPT_OVERSCAN
		)
	);
	let shouldShowEmptyState = $derived(
		paneMessages.length === 0 && !paneIsStreaming && (sessionInfo?.messageCount ?? 0) === 0
	);

	function measureVirtualMessage(node: HTMLElement, messageId: string) {
		let currentMessageId = messageId;
		const measure = () => {
			const nextHeight = Math.ceil(node.getBoundingClientRect().height);
			if (nextHeight <= 0) return;
			const row = virtualRowById.get(currentMessageId);
			if (!row || Math.abs(row.height - nextHeight) < 1) return;

			const adjustment = getAnchorAdjustment(row.top, transcriptScrollTop, row.height, nextHeight);
			measuredMessageHeights = { ...measuredMessageHeights, [currentMessageId]: nextHeight };
			if (adjustment !== 0 && scrollContainer) {
				scrollContainer.scrollTop += adjustment;
				transcriptScrollTop = scrollContainer.scrollTop;
			}
		};
		const observer = new ResizeObserver(measure);
		observer.observe(node);
		measure();

		return {
			update(nextMessageId: string) {
				currentMessageId = nextMessageId;
				measure();
			},
			destroy() {
				observer.disconnect();
			}
		};
	}

	let searchHighlightTimer: ReturnType<typeof setTimeout> | null = null;
	async function revealSearchMatch(messageId: string) {
		const row = virtualRowById.get(messageId);
		if (!row || !scrollContainer) return;
		scrollContainer.scrollTop = Math.max(
			0,
			row.top - transcriptViewportHeight / 2 + row.height / 2
		);
		transcriptScrollTop = scrollContainer.scrollTop;
		await tick();

		const element = scrollContainer?.querySelector<HTMLElement>(
			`[data-message-id="${CSS.escape(messageId)}"]`
		);
		if (!element) return;
		element.classList.add('chat-search-current');
		if (searchHighlightTimer) clearTimeout(searchHighlightTimer);
		searchHighlightTimer = setTimeout(() => element.classList.remove('chat-search-current'), 1200);
	}

	// ── Auto-scroll (RAF-throttled) ─────────────────────────────────────
	let scrollRafId: number | null = null;
	// Composer textarea auto-resize RAF id — see resizeTextarea().
	let resizeRafId: number | null = null;

	$effect(() => {
		const lastMessage = paneMessages.at(-1);
		const lastBlock = lastMessage?.contentBlocks.at(-1);
		const scrollSignal = `${lastMessage?.messageId ?? ''}:${lastBlock?.text.length ?? 0}:${panePermission?.requestId ?? ''}`;
		if (scrollSignal && isFocused && userNearBottom && bottomSentinel && scrollRafId === null) {
			scrollRafId = requestAnimationFrame(() => {
				scrollRafId = null;
				bottomSentinel?.scrollIntoView({ block: 'end' });
			});
		}
	});

	// Load messages when sessionId changes, then scroll to bottom
	$effect(() => {
		if (sessionId) {
			const requestedSessionId = sessionId;
			loadAttachments(requestedSessionId);
			loadMessages(requestedSessionId).then(() => {
				if (sessionId !== requestedSessionId) return;
				// After history loads, force scroll to bottom on next frame.
				// The auto-scroll $effect may have missed it if onscroll fired
				// during DOM insertion and set userNearBottom = false.
				userNearBottom = true;
				tick().then(() => {
					if (sessionId === requestedSessionId) bottomSentinel?.scrollIntoView({ block: 'end' });
				});
			});
		}
	});

	// ── Composer functions ───────────────────────────────────────────────
	async function handleSend() {
		if (!canSend || !sessionId) return;
		const text = inputText.trim();
		historyIndex = null;
		draftBeforeHistory = '';
		lastEscapeAt = 0;
		inputText = '';
		// Always scroll to bottom when user sends a message
		userNearBottom = true;
		await tick();
		resizeTextarea();
		const result = await sendMessage(sessionId, text);
		if (!result.sent) {
			inputText = text;
			await tick();
			resizeTextarea();
			toast.error($t('send_prompt_failed'), { description: result.error });
		}
	}

	async function handleCancel() {
		if (!sessionId || paneIsCancelling) return;
		const result = await cancelCurrentPrompt(sessionId);
		if (!result.cancelled) {
			toast.error($t('cancel_prompt_failed'), { description: result.error });
		}
	}

	function resizeTextarea() {
		// Auto-grow the composer without blocking keystrokes on layout.
		//
		// The naive `height='auto'; height=scrollHeight` pattern forces a synchronous
		// reflow of the whole document inside the `oninput` handler. With a long chat
		// history (many ChatMessage components, markdown blocks, tool-call panels),
		// that reflow runs into the tens of milliseconds in UE's embedded CEF, so
		// every keystroke stalls until layout completes — which manifests as input
		// lag that gets progressively worse as the session grows.
		//
		// Coalescing into a single rAF callback keeps the input handler O(1): the
		// keystroke is acknowledged immediately and the textarea grows on the next
		// frame. Multiple resize requests within the same frame share one reflow.
		if (!textareaEl || resizeRafId !== null) return;
		resizeRafId = requestAnimationFrame(() => {
			resizeRafId = null;
			if (!textareaEl) return;
			textareaEl.style.height = 'auto';
			textareaEl.style.height = Math.min(textareaEl.scrollHeight, 200) + 'px';
		});
	}

	function clearComposerPopups() {
		contextPopupVisible = false;
		mentionStartPos = -1;
		commandPopupVisible = false;
	}

	function placeCaret(position: 'start' | 'end') {
		if (!textareaEl) return;
		const offset = position === 'start' ? 0 : inputText.length;
		textareaEl.selectionStart = offset;
		textareaEl.selectionEnd = offset;
		textareaEl.focus();
	}

	function updateComposerText(text: string, caretPosition: 'start' | 'end') {
		inputText = text;
		clearComposerPopups();
		tick().then(() => {
			placeCaret(caretPosition);
			resizeTextarea();
			detectAtMention();
		});
	}

	function isCaretAtStart(): boolean {
		if (!textareaEl) return inputText.length === 0;
		return (textareaEl.selectionStart ?? 0) === 0 && (textareaEl.selectionEnd ?? 0) === 0;
	}

	function isCaretAtEnd(): boolean {
		if (!textareaEl) return true;
		return (
			(textareaEl.selectionStart ?? inputText.length) === inputText.length &&
			(textareaEl.selectionEnd ?? inputText.length) === inputText.length
		);
	}

	function navigateHistory(direction: -1 | 1) {
		const entries = getComposerHistoryEntries();
		if (entries.length === 0) return;
		if (direction === -1) {
			if (historyIndex === null) {
				draftBeforeHistory = inputText;
				historyIndex = entries.length - 1;
				updateComposerText(entries[historyIndex].text, 'start');
				return;
			}
			if (historyIndex === 0) return;
			historyIndex = historyIndex - 1;
			updateComposerText(entries[historyIndex].text, 'start');
			return;
		}
		if (historyIndex === null) return;
		if (historyIndex >= entries.length - 1) {
			const draft = draftBeforeHistory;
			historyIndex = null;
			draftBeforeHistory = '';
			updateComposerText(draft, 'end');
			return;
		}
		historyIndex = historyIndex + 1;
		updateComposerText(entries[historyIndex].text, 'start');
	}

	function handleDoubleEscape(): boolean {
		const now = Date.now();
		if (now - lastEscapeAt > DOUBLE_ESCAPE_WINDOW_MS) {
			lastEscapeAt = now;
			return true;
		}
		lastEscapeAt = 0;
		if (inputText.trim()) addDraftToHistory(inputText);
		historyIndex = null;
		draftBeforeHistory = '';
		updateComposerText('', 'start');
		return true;
	}

	function isImeCompositionEvent(e: KeyboardEvent): boolean {
		return isTextComposing || e.isComposing || e.key === 'Process' || e.keyCode === 229;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (isImeCompositionEvent(e)) return;
		if (!e.metaKey && !e.ctrlKey && !e.altKey) e.stopPropagation();
		if (contextPopupVisible && contextPopupRef?.handleKeydown(e)) return;
		if (commandPopupVisible && commandPopupRef?.handleKeydown(e)) return;
		if (e.key === 'Escape') {
			e.preventDefault();
			handleDoubleEscape();
			return;
		}
		lastEscapeAt = 0;
		if (!e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
			if (e.key === 'ArrowUp' && isCaretAtStart()) {
				e.preventDefault();
				navigateHistory(-1);
				return;
			}
			if (e.key === 'ArrowDown' && historyIndex !== null && isCaretAtEnd()) {
				e.preventDefault();
				navigateHistory(1);
				return;
			}
		}
		if (e.key === 'Enter') {
			if ($enterToSend) {
				// Enter sends, Shift+Enter for newline (default)
				if (!e.shiftKey) {
					e.preventDefault();
					handleSend();
				}
			} else {
				// Enter for newline, Ctrl/Cmd+Enter sends
				if (e.metaKey || e.ctrlKey) {
					e.preventDefault();
					handleSend();
				}
			}
		}
	}

	function handleKeyup(e: KeyboardEvent) {
		if (isImeCompositionEvent(e)) return;
		if (!e.metaKey && !e.ctrlKey && !e.altKey) e.stopPropagation();
	}

	function handleInput(event: Event) {
		recordInteractionLatency('composer_input', event.timeStamp, { streaming: paneIsStreaming });
		lastEscapeAt = 0;
		if (
			completedMention &&
			inputText.slice(completedMention.start, completedMention.end) !== completedMention.value
		) {
			completedMention = null;
		}
		if (historyIndex !== null) {
			historyIndex = null;
			draftBeforeHistory = '';
		}
		resizeTextarea();
		detectAtMention();
	}

	function detectAtMention() {
		if (!textareaEl) return;
		const cursorPos = textareaEl.selectionStart;
		const text = inputText;

		if (text.startsWith('/') && paneCommands.length > 0) {
			const firstSpace = text.indexOf(' ');
			if (firstSpace === -1 || cursorPos <= firstSpace) {
				commandQuery = text.slice(1, cursorPos);
				commandPopupVisible = true;
				contextPopupVisible = false;
				return;
			}
		}
		commandPopupVisible = false;

		// Scan backward for nearest @ (at start or after whitespace). Allow spaces in query
		// so multi-word asset names work (e.g. "@My Character"). Only @ terminates the scan.
		let atPos = -1;
		for (let i = cursorPos - 1; i >= 0; i--) {
			if (text[i] === '@') {
				const belongsToCompletedMention =
					completedMention &&
					completedMention.start === i &&
					cursorPos >= completedMention.end &&
					text.slice(completedMention.start, completedMention.end) === completedMention.value;
				if (!belongsToCompletedMention && (i === 0 || /\s/.test(text[i - 1]))) atPos = i;
				break;
			}
		}

		if (atPos >= 0) {
			const q = text.slice(atPos + 1, cursorPos);
			// A newline or a deliberate double-space ends an unselected mention.
			// Single spaces remain searchable so names like "My Character" work.
			if (q.includes('\n') || q.endsWith('  ')) {
				contextPopupVisible = false;
				mentionStartPos = -1;
				return;
			}
			mentionStartPos = atPos;
			contextQuery = q;
			contextPopupVisible = true;
		} else {
			contextPopupVisible = false;
			mentionStartPos = -1;
		}
	}

	function handleContextSelect(item: import('$lib/bridge.js').ContextItem) {
		if (!textareaEl || mentionStartPos < 0) return;
		const cursorPos = textareaEl.selectionStart;
		const before = inputText.slice(0, mentionStartPos);
		const after = inputText.slice(cursorPos);
		const mention = `@${item.path} `;
		inputText = before + mention + after;
		completedMention = {
			start: before.length,
			end: before.length + mention.length,
			value: mention
		};
		contextPopupVisible = false;
		mentionStartPos = -1;
		tick().then(() => {
			if (textareaEl) {
				const newPos = before.length + mention.length;
				textareaEl.selectionStart = newPos;
				textareaEl.selectionEnd = newPos;
				textareaEl.focus();
				resizeTextarea();
			}
		});
	}

	function handleContextNavigate(folderPath: string) {
		// Drill into folder: replace the text after @ with the folder path + /
		if (!textareaEl || mentionStartPos < 0) return;
		const cursorPos = textareaEl.selectionStart;
		const before = inputText.slice(0, mentionStartPos + 1); // keep the @
		const after = inputText.slice(cursorPos);
		const nav = `${folderPath}/`;
		inputText = before + nav + after;
		// contextQuery will be updated by detectAtMention on next tick
		tick().then(() => {
			if (textareaEl) {
				const newPos = mentionStartPos + 1 + nav.length;
				textareaEl.selectionStart = newPos;
				textareaEl.selectionEnd = newPos;
				textareaEl.focus();
				detectAtMention();
			}
		});
	}

	function handleCommandSelect(cmd: SlashCommand) {
		if (!textareaEl) return;
		const replacement = `/${cmd.name}${cmd.inputHint ? ' ' : ''}`;
		inputText = replacement;
		commandPopupVisible = false;
		tick().then(() => {
			if (textareaEl) {
				textareaEl.selectionStart = replacement.length;
				textareaEl.selectionEnd = replacement.length;
				textareaEl.focus();
				resizeTextarea();
			}
		});
	}

	function handleScroll() {
		if (!scrollContainer) return;
		const { scrollTop, scrollHeight, clientHeight } = scrollContainer;
		transcriptScrollTop = scrollTop;
		userNearBottom = scrollHeight - scrollTop - clientHeight < 80;
	}

	function handlePaste(e: ClipboardEvent) {
		const items = e.clipboardData?.items;
		if (items) {
			for (const item of items) {
				if (item.type.startsWith('image/') && sessionId) {
					e.preventDefault();
					pasteImage(sessionId);
					return;
				}
			}
		}
	}

	function handleDragOver(e: DragEvent) {
		e.preventDefault();
		dragOver = true;
	}
	function handleDragLeave() {
		dragOver = false;
	}
	function handleDrop(e: DragEvent) {
		e.preventDefault();
		dragOver = false;
		// OS files/assets are ingested by SACPAttachmentDropTarget using native paths.
		// Never copy file bytes through CEF/JavaScript as base64.
		const paths = extractDroppedMentionPaths(e.dataTransfer!);
		if (paths.length > 0) insertMentionTags(paths);
	}

	function extractDroppedMentionPaths(dataTransfer: DataTransfer): string[] {
		const found: string[] = [];
		for (let i = 0; i < dataTransfer.types.length; i++) {
			const raw = dataTransfer.getData(dataTransfer.types[i]);
			const matches = raw.match(/(?:Source\/[^\s,'"()]+|\/[^\s,'"()]+)/g);
			if (matches) {
				for (const m of matches) {
					let path = m
						.trim()
						.replace(/^[([{"']+/, '')
						.replace(/[)\]},"';:.]+$/, '');
					const si = path.indexOf('Source/');
					if (si > 0) path = path.slice(si);
					path = path.replace(/\\/g, '/');
					if (
						path.startsWith('Source/') ||
						(path.startsWith('/') && !COMMON_FILESYSTEM_ROOTS.has(path.split('/')[1] ?? ''))
					) {
						if (!found.includes(path)) found.push(path);
					}
				}
			}
		}
		return found;
	}

	function insertMentionTags(paths: string[]) {
		if (paths.length === 0) return;
		const mentionText = `${paths.map((p) => `@${p}`).join(' ')} `;
		if (!textareaEl) {
			inputText += (inputText.length > 0 && !/\s$/.test(inputText) ? ' ' : '') + mentionText;
			return;
		}
		const start = textareaEl.selectionStart ?? inputText.length;
		const end = textareaEl.selectionEnd ?? start;
		const before = inputText.slice(0, start);
		const after = inputText.slice(end);
		const needsSpace = before.length > 0 && !/\s$/.test(before);
		inputText = `${before}${needsSpace ? ' ' : ''}${mentionText}${after}`;
		tick().then(() => {
			if (!textareaEl) return;
			const cursorPos = before.length + (needsSpace ? 1 : 0) + mentionText.length;
			textareaEl.selectionStart = cursorPos;
			textareaEl.selectionEnd = cursorPos;
			textareaEl.focus();
			resizeTextarea();
		});
	}

	// Context menu
	const CTX_MENU_WIDTH = 200;
	const CTX_MENU_HEIGHT = 160;
	function clampMenuPosition(x: number, y: number): [number, number] {
		const vw = window.innerWidth;
		const vh = window.innerHeight;
		return [Math.min(x, vw - CTX_MENU_WIDTH), Math.min(y, vh - CTX_MENU_HEIGHT)];
	}
	function handleChatContextMenu(e: MouseEvent) {
		e.preventDefault();
		e.stopPropagation();
		ctxMenuHasSelection = !!window.getSelection()?.toString();
		ctxMenuIsInput = false;
		[ctxMenuX, ctxMenuY] = clampMenuPosition(e.clientX, e.clientY);
		ctxMenuVisible = true;
	}
	function handleInputContextMenu(e: MouseEvent) {
		e.preventDefault();
		e.stopPropagation();
		if (!textareaEl) return;
		ctxMenuHasSelection = (textareaEl.selectionStart ?? 0) !== (textareaEl.selectionEnd ?? 0);
		ctxMenuIsInput = true;
		[ctxMenuX, ctxMenuY] = clampMenuPosition(e.clientX, e.clientY);
		ctxMenuVisible = true;
	}
	function handleCtxCopy() {
		if (ctxMenuIsInput && textareaEl) {
			const sel = textareaEl.value.substring(
				textareaEl.selectionStart ?? 0,
				textareaEl.selectionEnd ?? 0
			);
			if (sel) copyToClipboard(sel);
		} else {
			const sel = window.getSelection()?.toString() ?? '';
			if (sel) copyToClipboard(sel);
		}
		ctxMenuVisible = false;
	}
	function handleCtxCut() {
		if (!ctxMenuIsInput || !textareaEl) return;
		const s = textareaEl.selectionStart ?? 0,
			e = textareaEl.selectionEnd ?? 0;
		const sel = textareaEl.value.substring(s, e);
		if (sel) {
			copyToClipboard(sel);
			textareaEl.setRangeText('', s, e, 'end');
			textareaEl.dispatchEvent(new Event('input', { bubbles: true }));
		}
		ctxMenuVisible = false;
	}
	async function handleCtxPaste() {
		if (!textareaEl) return;
		const text = await getClipboardText();
		if (text) {
			const s = textareaEl.selectionStart ?? 0,
				e = textareaEl.selectionEnd ?? 0;
			textareaEl.setRangeText(text, s, e, 'end');
			textareaEl.dispatchEvent(new Event('input', { bubbles: true }));
		}
		ctxMenuVisible = false;
	}
	function handleCtxSelectAll() {
		if (ctxMenuIsInput && textareaEl) textareaEl.select();
		else if (scrollContainer) {
			const r = document.createRange();
			r.selectNodeContents(scrollContainer);
			const s = window.getSelection();
			s?.removeAllRanges();
			s?.addRange(r);
		}
		ctxMenuVisible = false;
	}

	// Export for parent
	export function getInputText(): string {
		return inputText;
	}
	export function setInputText(text: string) {
		inputText = text;
		tick().then(() => resizeTextarea());
	}
</script>

<div class="flex h-full flex-col overflow-hidden">
	{#if !sessionId}
		<div class="flex h-full flex-col items-center justify-center gap-4 px-6">
			<span class="text-muted-foreground/40 text-[13px]">{$t('start_with')}</span>
			<div class="flex flex-wrap items-center justify-center gap-2">
				{#each $agents.filter((a) => a.status === 'available') as agent (agent.name)}
					<button
						class="border-border/60 bg-secondary/40 flex items-center gap-2 rounded-lg border px-3 py-2 text-[12px] text-foreground transition-colors hover:border-border hover:bg-secondary"
						onclick={() => onStartSession?.(agent.name)}
					>
						{#if agent.iconUrl}
							<span
								class="flex h-4 w-4 shrink-0 items-center justify-center"
								style="color: {agent.color};"
							>
								<img src={agent.iconUrl} alt="" class="h-4 w-4 opacity-70 dark:invert" />
							</span>
						{:else}
							<span
								class="flex h-4 w-4 shrink-0 items-center justify-center rounded text-[7px] font-bold text-white"
								style="background-color: {agent.color};">{agent.letter}</span
							>
						{/if}
						<span>{agent.shortName}</span>
					</button>
				{/each}
			</div>
			<span class="text-muted-foreground/25 text-[11px]">or select a session from the sidebar</span>
		</div>
	{:else}
		<!-- Pane header (only in multi-pane mode) -->
		{#if showPaneHeader}
			<div
				class="border-border/40 flex h-7 shrink-0 items-center justify-between border-b px-3 text-[11px]"
			>
				<div class="flex min-w-0 items-center gap-1.5">
					{#if needsAttention}
						<span
							class="h-2 w-2 shrink-0 animate-pulse rounded-full bg-amber-500"
							title="Needs permission"
						></span>
					{:else if isQueued}
						<span
							class="h-2 w-2 shrink-0 animate-pulse rounded-full bg-amber-500"
							title="Queued behind another tool"
						></span>
					{:else if isWorking}
						<span
							class="h-2 w-2 shrink-0 animate-pulse rounded-full bg-blue-500"
							title={paneState?.message || 'Working'}
						></span>
					{/if}
					<span class="truncate text-muted-foreground">{sessionInfo?.title || $t('new_chat')}</span>
					<span class="text-muted-foreground/40 shrink-0">{sessionAgent}</span>
				</div>
			</div>
		{/if}

		<!-- Transcript and composer share layout flow so tall permission/plan/attachment
		     states can never cover the final messages. -->
		<div class="relative flex flex-1 flex-col overflow-hidden">
			{#if chatSearchVisible}
				<ChatSearchBar
					messages={paneMessages}
					onselect={revealSearchMatch}
					onclose={() => {
						chatSearchVisible = false;
					}}
				/>
			{/if}
			<!-- Messages (scrollable) -->
			<div
				class="chat-scroll-area min-h-0 flex-1 overflow-y-auto px-6 py-4 [overflow-anchor:none]"
				bind:this={scrollContainer}
				bind:clientHeight={transcriptViewportHeight}
				onscroll={handleScroll}
				oncontextmenu={handleChatContextMenu}
				role="log"
				aria-label="Conversation transcript"
			>
				{#if shouldShowEmptyState}
					<div
						class="text-muted-foreground/40 flex h-full flex-col items-center justify-center gap-3"
					>
						{#if sessionAgentInfo?.iconUrl ?? $selectedAgent?.iconUrl}
							<span
								style="color: {sessionAgentInfo?.color ?? $selectedAgent?.color}; opacity: 0.3;"
							>
								<img
									src={sessionAgentInfo?.iconUrl ?? $selectedAgent?.iconUrl}
									alt=""
									class="h-10 w-10 opacity-70 dark:invert"
								/>
							</span>
						{/if}
						<span class="text-[14px]">{$t('send_message_to_get_started')}</span>
					</div>
				{:else}
					<div class="relative" style:height={`${virtualLayout.totalHeight}px`}>
						{#each visibleVirtualRows as row (row.key)}
							<div
								class="absolute inset-x-0 top-0"
								style:transform={`translateY(${row.top}px)`}
								use:measureVirtualMessage={row.key}
							>
								<ChatMessageComponent message={row.item} />
							</div>
						{/each}
					</div>
				{/if}
				{#if paneIsStreaming && paneMessages[paneMessages.length - 1]?.role !== 'assistant'}
					<div class="mb-4 flex justify-start">
						<div class="flex items-center gap-2 text-[12px]">
							<Shimmer><span>{$t('generating')}</span></Shimmer>
						</div>
					</div>
				{/if}
				<div class="h-px" bind:this={bottomSentinel} aria-hidden="true"></div>
			</div>

			<!-- Context menu -->
			{#if ctxMenuVisible}
				<button
					class="fixed inset-0 z-[100] cursor-default"
					onclick={() => (ctxMenuVisible = false)}
					oncontextmenu={(e) => {
						e.preventDefault();
						ctxMenuVisible = false;
					}}
					aria-label="Close context menu"
				></button>
				<div
					class="fixed z-[101] min-w-[180px] rounded-lg border border-border bg-popover p-1 shadow-lg"
					style="left: {ctxMenuX}px; top: {ctxMenuY}px;"
					role="menu"
				>
					{#if ctxMenuIsInput}
						<button
							class="flex min-h-10 w-full items-center justify-between rounded-md px-3 py-2 text-[13px] text-popover-foreground {ctxMenuHasSelection
								? 'cursor-default hover:bg-accent'
								: 'cursor-not-allowed opacity-40'}"
							onclick={handleCtxCut}
							disabled={!ctxMenuHasSelection}
							>{$t('cut')}<span class="text-muted-foreground/60 ml-auto text-[11px]">{modKey}X</span
							></button
						>
					{/if}
					<button
						class="flex min-h-10 w-full items-center justify-between rounded-md px-3 py-2 text-[13px] text-popover-foreground {ctxMenuHasSelection
							? 'cursor-default hover:bg-accent'
							: 'cursor-not-allowed opacity-40'}"
						onclick={handleCtxCopy}
						disabled={!ctxMenuHasSelection}
						>{$t('copy')}<span class="text-muted-foreground/60 ml-auto text-[11px]">{modKey}C</span
						></button
					>
					{#if ctxMenuIsInput}
						<button
							class="flex min-h-10 w-full cursor-default items-center justify-between rounded-md px-3 py-2 text-[13px] text-popover-foreground hover:bg-accent"
							onclick={handleCtxPaste}
							>{$t('paste')}<span class="text-muted-foreground/60 ml-auto text-[11px]"
								>{modKey}V</span
							></button
						>
					{/if}
					<div class="my-1 h-px bg-border"></div>
					<button
						class="flex min-h-10 w-full cursor-default items-center justify-between rounded-md px-3 py-2 text-[13px] text-popover-foreground hover:bg-accent"
						onclick={handleCtxSelectAll}
						>{$t('select_all')}<span class="text-muted-foreground/60 ml-auto text-[11px]"
							>{modKey}A</span
						></button
					>
				</div>
			{/if}

			<!-- Composer in normal flow -->
			<div class="z-10 shrink-0 px-6 pb-3 pt-2">
				<div class="mx-auto max-w-3xl">
					<div
						class="relative rounded-2xl border transition-colors focus-within:border-[var(--ue-accent-muted)] {dragOver
							? 'border-dashed border-blue-400/60 bg-blue-500/5'
							: 'border-border bg-card'}"
						style="box-shadow: 0 0 0 1px rgba(0,0,0,0.2), 0 2px 8px rgba(0,0,0,0.15);"
						role="region"
						aria-label="Message input"
						ondragover={handleDragOver}
						ondragleave={handleDragLeave}
						ondrop={handleDrop}
					>
						{#if paneHasPlan}
							<PlanPanel plan={panePlan} />
						{/if}
						{#if panePermission}
							<div class="p-3">
								{#if paneIsStreaming}
									<div class="mb-2 flex justify-end">
										<button
											class="flex min-h-10 items-center gap-1.5 rounded-lg bg-red-500/90 px-3 py-2 text-[12px] text-white transition-colors hover:bg-red-500 active:scale-95 disabled:cursor-wait disabled:opacity-60"
											onclick={handleCancel}
											disabled={paneIsCancelling}
											aria-busy={paneIsCancelling}
											title={paneIsCancelling ? $t('cancelling') : $t('stop_generating')}
											aria-label={paneIsCancelling ? $t('cancelling') : $t('stop_generating')}
										>
											<Icon icon={StopIcon} size={13} strokeWidth={2.5} />
											{paneIsCancelling ? $t('cancelling') : $t('stop_generating')}
										</button>
									</div>
								{/if}
								{#if panePermission.isAskUserQuestion}
									<AskUserDialog request={panePermission} sessionId={sessionId ?? ''} />
								{:else}
									<PermissionDialog request={panePermission} sessionId={sessionId ?? ''} />
								{/if}
							</div>
						{:else}
							<ContextPopup
								bind:this={contextPopupRef}
								query={contextQuery}
								visible={contextPopupVisible}
								onselect={handleContextSelect}
								onnavigate={handleContextNavigate}
								ondismiss={() => {
									contextPopupVisible = false;
									mentionStartPos = -1;
								}}
							/>
							<CommandPopup
								bind:this={commandPopupRef}
								query={commandQuery}
								visible={commandPopupVisible}
								commands={paneCommands}
								onselect={handleCommandSelect}
								ondismiss={() => {
									commandPopupVisible = false;
								}}
							/>
							{#if waitingForMcp}
								<div class="flex items-center gap-2 px-4 pb-1 pt-3">
									<span class="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500"></span>
									<span class="text-[13px] text-amber-400/80">{$t('connecting_tools')}</span>
								</div>
							{/if}
							{#if sessionId}<AttachmentChips {sessionId} />{/if}
							<textarea
								bind:this={textareaEl}
								bind:value={inputText}
								placeholder={inputPlaceholder}
								disabled={!sessionId || !agentReady}
								rows={1}
								spellcheck="false"
								autocomplete="off"
								class="placeholder:text-muted-foreground/60 w-full resize-none bg-transparent px-4 pb-3 pt-3.5 text-[14px] leading-normal text-foreground focus:outline-none disabled:opacity-50"
								onkeydown={handleKeydown}
								onkeyup={handleKeyup}
								oncompositionstart={() => (isTextComposing = true)}
								oncompositionend={() => {
									isTextComposing = false;
									detectAtMention();
								}}
								oninput={handleInput}
								onpaste={handlePaste}
								oncontextmenu={handleInputContextMenu}
								data-chat-session-id={sessionId ?? ''}
								aria-label="Message"
							></textarea>
							<div class="flex items-center justify-between px-3 pb-2.5">
								<div class="flex items-center gap-1.5">
									<button
										class="flex h-10 w-10 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
										onclick={() => sessionId && pickAttachments(sessionId)}
										title={$t('attach_file')}
										aria-label={$t('attach_file')}
									>
										<Icon icon={Add01Icon} size={18} strokeWidth={1.5} />
									</button>
									{#if hasConfigOptions}
										<AgentConfigMenu
											options={paneConfigOptions}
											disabled={!agentReady || paneIsStreaming}
											onselect={handleChangeConfigOption}
										/>
									{/if}
									<!-- Legacy model picker for agents without generic ACP config options -->
									{#if !hasGenericModelOption && (hasModels || paneModelsLoading)}
										<DropdownMenu.Root>
											<DropdownMenu.Trigger
												class="flex min-h-10 items-center gap-1 rounded-lg px-2 py-2 text-[12px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
												disabled={paneModelsLoading}
											>
												{#if paneModelsLoading}
													<span
														class="border-muted-foreground/30 inline-block h-3 w-3 animate-spin rounded-full border-2 border-t-muted-foreground"
													></span>
												{:else}
													{modelDisplayName}
													<Icon
														icon={ArrowDown01Icon}
														size={10}
														strokeWidth={1.5}
														class="opacity-50"
													/>
												{/if}
											</DropdownMenu.Trigger>
											<DropdownMenu.Content
												class="max-h-[300px] w-[280px] overflow-y-auto"
												side="top"
												align="start"
												sideOffset={4}
											>
												{#each groupedModelOptions as group, gi (group.provider)}
													{#if gi > 0}
														<DropdownMenu.Separator />
													{/if}
													<DropdownMenu.Label class="text-[11px] text-muted-foreground"
														>{group.provider || $t('model_label')}</DropdownMenu.Label
													>
													{#each group.models as model (model.id)}
														<DropdownMenu.Item
															class="flex items-center gap-2 px-2 py-1.5"
															onclick={() =>
																sessionAgent && handleChangeModel(sessionAgent, model.id)}
														>
															<div class="min-w-0 flex-1">
																<div class="truncate text-[13px]">{model.name}</div>
																{#if model.description}
																	<div class="text-muted-foreground/40 truncate text-[11px]">
																		{model.description}
																	</div>
																{/if}
															</div>
															{#if model.id === paneCurrentModelId}
																<span class="h-1.5 w-1.5 shrink-0 rounded-full bg-foreground"
																></span>
															{/if}
														</DropdownMenu.Item>
													{/each}
												{/each}
											</DropdownMenu.Content>
										</DropdownMenu.Root>
									{/if}
									<!-- Reasoning level picker -->
									{#if !hasGenericReasoningOption && hasModels && !paneModelsLoading && currentModelSupportsReasoning}
										<DropdownMenu.Root>
											<DropdownMenu.Trigger
												class="flex min-h-10 items-center gap-1 rounded-lg px-2 py-2 text-[12px] transition-colors {paneReasoningLevel !==
												'none'
													? 'text-[var(--ue-accent)] hover:text-[var(--ue-accent-hover)]'
													: 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
											>
												{reasoningLabels[paneReasoningLevel]}
												<Icon
													icon={ArrowDown01Icon}
													size={10}
													strokeWidth={1.5}
													class="opacity-50"
												/>
											</DropdownMenu.Trigger>
											<DropdownMenu.Content
												class="w-[160px]"
												side="top"
												align="start"
												sideOffset={4}
											>
												<DropdownMenu.Label class="text-[11px] text-muted-foreground"
													>{$t('effort')}</DropdownMenu.Label
												>
												{#each reasoningLevels as level (level)}
													<DropdownMenu.Item
														class="flex items-center justify-between px-2 py-1.5"
														onclick={() => handleChangeReasoningLevel(level, sessionAgent)}
													>
														<span class="text-[13px]">{reasoningLabels[level]}</span>
														{#if level === paneReasoningLevel}
															<span class="h-1.5 w-1.5 shrink-0 rounded-full bg-foreground"></span>
														{/if}
													</DropdownMenu.Item>
												{/each}
											</DropdownMenu.Content>
										</DropdownMenu.Root>
									{/if}
								</div>
								<div class="flex items-center gap-1.5">
									{#if paneIsStreaming}
										<button
											class="flex h-10 w-10 items-center justify-center rounded-full bg-red-500/90 text-white transition-all hover:scale-105 hover:bg-red-500 active:scale-95 disabled:cursor-wait disabled:opacity-60"
											style="box-shadow: 0 0 10px rgba(220,80,40,0.3);"
											onclick={handleCancel}
											disabled={paneIsCancelling}
											aria-busy={paneIsCancelling}
											title={paneIsCancelling ? $t('cancelling') : $t('stop_generating')}
											aria-label={paneIsCancelling ? $t('cancelling') : $t('stop_generating')}
										>
											<Icon icon={StopIcon} size={16} strokeWidth={2.5} />
										</button>
									{:else}
										<button
											class="flex h-10 w-10 items-center justify-center rounded-full transition-all {canSend
												? 'text-white hover:scale-105 active:scale-95'
												: 'bg-muted-foreground/20 text-muted-foreground/40 cursor-not-allowed'}"
											style={canSend
												? 'background: var(--ue-accent); box-shadow: 0 0 12px rgba(50,130,230,0.35);'
												: ''}
											onclick={handleSend}
											disabled={!canSend}
											aria-label="Send message"
										>
											<Icon icon={ArrowUp01Icon} size={18} strokeWidth={2.5} />
										</button>
									{/if}
								</div>
							</div>
						{/if}
					</div>
					<!-- Bottom status bar -->
					<div
						class="text-muted-foreground/70 mt-2.5 flex items-center justify-between px-1 text-[12px]"
					>
						<div class="flex items-center gap-4">
							{#if hasModes && !hasGenericModeOption}
								<DropdownMenu.Root>
									<DropdownMenu.Trigger
										class="flex min-h-10 items-center gap-1.5 transition-colors hover:text-foreground {isPlanMode
											? 'text-blue-400'
											: ''}"
									>
										<Icon icon={ChangeScreenModeIcon} size={14} strokeWidth={1.5} />
										{modeDisplayName}
										<Icon icon={ArrowDown01Icon} size={10} strokeWidth={1.5} class="opacity-50" />
									</DropdownMenu.Trigger>
									<DropdownMenu.Content class="w-[220px]" side="top" align="start" sideOffset={4}>
										<DropdownMenu.Label class="text-[11px] text-muted-foreground"
											>{$t('mode_label')}</DropdownMenu.Label
										>
										{#each paneModes as mode (mode.id)}
											<DropdownMenu.Item
												class="flex items-center gap-2 px-2 py-1.5"
												onclick={() => sessionAgent && handleChangeMode(sessionAgent, mode.id)}
											>
												<div class="min-w-0 flex-1">
													<div class="truncate text-[13px]">{mode.name}</div>
													{#if mode.description}
														<div class="text-muted-foreground/40 truncate text-[11px]">
															{mode.description}
														</div>
													{/if}
												</div>
												{#if mode.id === paneCurrentModeId}
													<span class="h-1.5 w-1.5 shrink-0 rounded-full bg-foreground"></span>
												{/if}
											</DropdownMenu.Item>
										{/each}
									</DropdownMenu.Content>
								</DropdownMenu.Root>
							{/if}
						</div>
						<div class="flex items-center gap-3">
							{#if usageHasContext || usageHasTokens}
								<Tooltip.Root>
									<Tooltip.Trigger
										class="flex min-h-10 items-center gap-1.5 tabular-nums transition-colors hover:text-foreground"
										aria-label="Session usage"
									>
										{@const pct = paneContextPercent}
										{@const strokeColor = pct < 50 ? '#22c55e' : pct < 80 ? '#eab308' : '#ef4444'}
										{@const circumference = 2 * Math.PI * 7}
										{@const dashOffset = circumference * (1 - pct / 100)}
										<svg width="16" height="16" viewBox="0 0 18 18">
											<circle
												cx="9"
												cy="9"
												r="7"
												fill="none"
												stroke="currentColor"
												stroke-width="2.5"
												opacity="0.15"
											/>
											<circle
												cx="9"
												cy="9"
												r="7"
												fill="none"
												stroke={strokeColor}
												stroke-width="2.5"
												stroke-dasharray={circumference}
												stroke-dashoffset={dashOffset}
												stroke-linecap="round"
												transform="rotate(-90 9 9)"
											/>
										</svg>
										<span class="text-[12px]">{usageContextLabel}</span>
									</Tooltip.Trigger>
									<Tooltip.Content
										side="top"
										sideOffset={6}
										class="w-[260px] !bg-popover p-3 text-[12px] !text-popover-foreground"
										arrowClasses="!bg-popover"
									>
										<div class="mb-1.5 text-[13px] font-medium">{$t('context_window')}</div>
										<div class="text-muted-foreground/50 mb-2.5 text-[11px] leading-relaxed">
											{$t('context_window_desc')}
										</div>
										{#if usageHasContext}
											{@const pctVal = paneContextPercent}
											{@const remaining = 100 - pctVal}
											<div class="mb-1 text-muted-foreground">
												{$t('used_left_pct', { used: pctVal, left: remaining })}
											</div>
											<div
												class="bg-muted-foreground/15 mb-2 h-1.5 w-full overflow-hidden rounded-full"
											>
												<div
													class="h-full rounded-full transition-all duration-300"
													style="width: {pctVal}%; background-color: {pctVal < 50
														? '#22c55e'
														: pctVal < 80
															? '#eab308'
															: '#ef4444'};"
												></div>
											</div>
											<div class="text-muted-foreground">
												{$t('tokens_used', {
													used: formatTokens(paneUsage.contextUsed),
													total: formatTokens(paneUsage.contextSize)
												})}
											</div>
										{:else if usageHasTokens}
											<div class="text-muted-foreground">
												{formatTokens(paneUsage.inputTokens)} input, {formatTokens(
													paneUsage.outputTokens
												)} output
											</div>
										{/if}
										{#if paneUsage.cacheReadTokens > 0}
											<div class="text-muted-foreground/60 mt-1">
												{$t('cached', { count: formatTokens(paneUsage.cacheReadTokens) })}
											</div>
										{/if}
										{#if usageHasCost}
											<div class="border-border/40 mt-1.5 border-t pt-1.5 text-muted-foreground">
												{$t('session_cost')}: {formatCost(
													paneUsage.costAmount,
													paneUsage.costCurrency
												)}
												{#if paneUsage.turnCostUSD > 0}
													<span class="text-muted-foreground/50"
														>{$t('last_turn_cost', {
															cost: formatCost(paneUsage.turnCostUSD)
														})}</span
													>
												{/if}
											</div>
										{/if}
										{#if paneUsage.numTurns > 0}
											<div class="text-muted-foreground/50 mt-1">
												{$t('turns', { count: paneUsage.numTurns })}
												{#if paneUsage.durationMs > 0}
													&middot; {formatDurationMs(paneUsage.durationMs)}
												{/if}
											</div>
										{/if}
									</Tooltip.Content>
								</Tooltip.Root>
							{/if}
							{#if $scEnabled}
								<DropdownMenu.Root>
									<DropdownMenu.Trigger
										class="flex min-h-10 items-center gap-1.5 transition-colors hover:text-foreground"
									>
										<Icon icon={GitBranchIcon} size={14} strokeWidth={1.5} />
										{$branchName || '...'}
										{#if $hasChanges}
											<span
												class="rounded-full bg-amber-500/20 px-1.5 text-[10px] font-medium text-amber-400"
												>{$changesLabel}</span
											>
										{/if}
										<Icon icon={ArrowDown01Icon} size={10} strokeWidth={1.5} class="opacity-50" />
									</DropdownMenu.Trigger>
									<DropdownMenu.Content class="w-[200px]" side="top" align="end" sideOffset={4}>
										<DropdownMenu.Label class="text-[11px] text-muted-foreground"
											>{$t('source_control')}</DropdownMenu.Label
										>
										<DropdownMenu.Item
											class="flex items-center gap-2 px-2 py-1.5"
											onclick={() => openSourceControlChangelist()}
										>
											<span class="text-[13px]">{$t('view_changelists')}</span>
										</DropdownMenu.Item>
										<DropdownMenu.Item
											class="flex items-center gap-2 px-2 py-1.5"
											onclick={() => openSourceControlSubmit()}
										>
											<span class="text-[13px]">{$t('submit_changes')}</span>
										</DropdownMenu.Item>
									</DropdownMenu.Content>
								</DropdownMenu.Root>
							{:else}
								<span class="text-muted-foreground/40 flex items-center gap-1.5">
									<Icon icon={GitBranchIcon} size={14} strokeWidth={1.5} />
									{$t('no_vcs')}
								</span>
							{/if}
						</div>
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>
