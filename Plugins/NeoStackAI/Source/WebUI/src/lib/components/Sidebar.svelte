<script lang="ts">
	import { onDestroy } from 'svelte';
	import Icon from '$lib/components/Icon.svelte';
	import {
		Settings02Icon,
		ArrowDown01Icon,
		MessageMultiple01Icon,
		Delete02Icon,
		ReloadIcon
	} from '@hugeicons/core-free-icons';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu/index.js';
	import * as ContextMenu from '$lib/components/ui/context-menu/index.js';
	import { AlertDialog } from 'bits-ui';
	import { agents, selectedAgent, statusDotColor, type Agent } from '$lib/stores/agents.js';
	import {
		sessions,
		currentSessionId,
		isLoadingSessions,
		isConnectingAgents,
		groupedSessions,
		createNewSession,
		selectSession,
		removeSession,
		refreshSessions,
		formatTimeAgo
	} from '$lib/stores/sessions.js';
	import {
		sessionStates,
		recentlyFinished,
		getSessionSidebarStatus,
		getSessionSidebarDotStyle,
		type SessionSidebarKind
	} from '$lib/stores/agentState.js';
	import { sessionsNeedingAttention } from '$lib/stores/permissions.js';
	import { loadModelsForAgent } from '$lib/stores/models.js';
	import { enterSetup, setupAgent } from '$lib/stores/setup.js';
	import { openSettings, terminalEnabled } from '$lib/stores/settings.js';
	import {
		exportSessionToMarkdown,
		renameSession,
		getSessionTerminalResumeCommand,
		type SessionInfo
	} from '$lib/bridge.js';
	import { currentTab } from '$lib/stores/navigation.js';
	import { pendingTerminalPaste } from '$lib/stores/pendingTerminalPaste.js';
	import { PencilEdit01Icon } from '@hugeicons/core-free-icons';
	import { t } from '$lib/i18n.js';
	import { toast } from 'svelte-sonner';
	import NeoStackAccountCard from '$lib/components/NeoStackAccountCard.svelte';

	import { Search01Icon } from '@hugeicons/core-free-icons';

	let searchQuery = $state('');
	let debouncedSearchQuery = $state('');
	let sessionListEl = $state<HTMLDivElement | undefined>();
	let sessionListScrollTop = $state(0);
	let sessionListViewportHeight = $state(500);
	const SESSION_ROW_HEIGHT = 36;
	const SESSION_GROUP_HEIGHT = 30;
	const SESSION_OVERSCAN_PX = 180;

	$effect(() => {
		const nextQuery = searchQuery.trim().toLowerCase();
		const timer = setTimeout(() => {
			debouncedSearchQuery = nextQuery;
			sessionListScrollTop = 0;
			if (sessionListEl) sessionListEl.scrollTop = 0;
		}, 120);
		return () => clearTimeout(timer);
	});

	let filteredGroupedSessions = $derived.by(() => {
		const q = debouncedSearchQuery;
		if (!q) return $groupedSessions;
		return $groupedSessions
			.map((group) => ({
				...group,
				sessions: group.sessions.filter(
					(s) => (s.title || '').toLowerCase().includes(q) || s.agentName.toLowerCase().includes(q)
				)
			}))
			.filter((group) => group.sessions.length > 0);
	});

	type VirtualSessionRow =
		| { kind: 'group'; key: string; label: string; top: number; height: number }
		| { kind: 'session'; key: string; session: SessionInfo; top: number; height: number };

	let flattenedSessionRows = $derived.by(() => {
		const rows: VirtualSessionRow[] = [];
		// Row keys must be unique or Svelte 5 hard-crashes the whole app
		// (each_key_duplicate). Session ids can collide across merged sources
		// (agent histories vs local store) — render each id once, defensively.
		const seenKeys = new Set<string>();
		let top = 0;
		for (const group of filteredGroupedSessions) {
			const groupKey = `group:${group.label}`;
			if (seenKeys.has(groupKey)) continue;
			seenKeys.add(groupKey);
			rows.push({
				kind: 'group',
				key: groupKey,
				label: group.label,
				top,
				height: SESSION_GROUP_HEIGHT
			});
			top += SESSION_GROUP_HEIGHT;
			for (const session of group.sessions) {
				const sessionKey = `session:${session.sessionId}`;
				if (seenKeys.has(sessionKey)) {
					console.warn('Duplicate session id in list, skipping:', session.sessionId);
					continue;
				}
				seenKeys.add(sessionKey);
				rows.push({
					kind: 'session',
					key: sessionKey,
					session,
					top,
					height: SESSION_ROW_HEIGHT
				});
				top += SESSION_ROW_HEIGHT;
			}
		}
		return rows;
	});
	let totalSessionListHeight = $derived(
		flattenedSessionRows.length > 0
			? flattenedSessionRows[flattenedSessionRows.length - 1].top +
					flattenedSessionRows[flattenedSessionRows.length - 1].height
			: 0
	);
	let visibleSessionRows = $derived(
		flattenedSessionRows.filter(
			(row) =>
				row.top + row.height >= sessionListScrollTop - SESSION_OVERSCAN_PX &&
				row.top <= sessionListScrollTop + sessionListViewportHeight + SESSION_OVERSCAN_PX
		)
	);
	let agentByName = $derived.by(() => {
		const index: Record<string, Agent> = Object.create(null);
		for (const agent of $agents) index[agent.name] = agent;
		return index;
	});

	function handleSessionListScroll(): void {
		if (sessionListEl) sessionListScrollTop = sessionListEl.scrollTop;
	}

	let isRefreshing = $state(false);
	let sessionActionStatusMessage = $state('');
	let sessionActionStatusTone = $state<'success' | 'error'>('success');
	let statusMessageTimeout: ReturnType<typeof setTimeout> | null = null;

	function setSessionActionStatus(message: string, tone: 'success' | 'error'): void {
		sessionActionStatusMessage = message;
		sessionActionStatusTone = tone;
		if (statusMessageTimeout) {
			clearTimeout(statusMessageTimeout);
		}
		statusMessageTimeout = setTimeout(() => {
			sessionActionStatusMessage = '';
			statusMessageTimeout = null;
		}, 5000);
	}

	onDestroy(() => {
		if (statusMessageTimeout) {
			clearTimeout(statusMessageTimeout);
		}
	});

	async function handleSelectAgent(agent: Agent) {
		if (agent.status !== 'available') {
			currentSessionId.set(null);
			enterSetup(agent);
		} else {
			setupAgent.set(null);
			selectedAgent.set(agent);
			await createNewSession(agent.name);
			loadModelsForAgent(agent.name);
		}
	}

	async function handleNewChat() {
		if ($selectedAgent) {
			if ($selectedAgent.status !== 'available') {
				currentSessionId.set(null);
				enterSetup($selectedAgent);
			} else {
				setupAgent.set(null);
				await createNewSession($selectedAgent.name);
			}
		}
	}

	let deleteCandidate = $state<SessionInfo | null>(null);
	let isDeletingSession = $state(false);

	function requestDelete(session: SessionInfo): void {
		deleteCandidate = session;
	}

	async function confirmDelete(): Promise<void> {
		if (!deleteCandidate || isDeletingSession) return;
		const session = deleteCandidate;
		isDeletingSession = true;
		const success = await removeSession(session.sessionId);
		isDeletingSession = false;
		if (success) {
			deleteCandidate = null;
			setSessionActionStatus('Chat deleted.', 'success');
			return;
		}

		setSessionActionStatus('Could not delete this chat. Nothing was removed.', 'error');
		toast.error('Could not delete chat', {
			description: 'The agent or local history store rejected the delete request. Try again.'
		});
	}

	// ── Inline rename ───────────────────────────────────────────────
	let renamingSessionId = $state<string | null>(null);
	let renameValue = $state('');
	let renameInputEl = $state<HTMLInputElement | undefined>();

	function startRename(sessionId: string, currentTitle: string) {
		renamingSessionId = sessionId;
		renameValue = currentTitle;
		// Focus after DOM update
		requestAnimationFrame(() => renameInputEl?.select());
	}

	async function commitRename() {
		if (!renamingSessionId) return;
		const trimmed = renameValue.trim();
		if (trimmed) {
			try {
				const result = await renameSession(renamingSessionId, trimmed);
				if (result.success) {
					// Update local session list so UI reflects immediately
					sessions.update((list) =>
						list.map((s) =>
							s.sessionId === renamingSessionId ? { ...s, title: trimmed, hasCustomTitle: true } : s
						)
					);
				} else {
					toast.error($t('rename_failed'));
				}
			} catch (e) {
				toast.error($t('rename_failed'), {
					description: e instanceof Error ? e.message : String(e)
				});
			}
		}
		renamingSessionId = null;
		renameValue = '';
	}

	function cancelRename() {
		renamingSessionId = null;
		renameValue = '';
	}

	function handleRenameKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			e.preventDefault();
			commitRename();
		} else if (e.key === 'Escape') {
			e.preventDefault();
			cancelRename();
		}
	}

	async function handleExport(sessionId: string) {
		try {
			let result = await exportSessionToMarkdown(sessionId);
			let errorText = (result.error || '').toLowerCase();
			const isLoadStateError =
				errorText.includes('not loaded in memory') || errorText.includes('still loading from acp');

			if (!result.success && !result.canceled && isLoadStateError) {
				if ($currentSessionId !== sessionId) {
					await selectSession(sessionId);
				}

				const deadline = Date.now() + 7000;
				while (!result.success && !result.canceled && Date.now() < deadline) {
					await new Promise((resolve) => setTimeout(resolve, 500));
					result = await exportSessionToMarkdown(sessionId);
					errorText = (result.error || '').toLowerCase();
					if (
						!errorText.includes('not loaded in memory') &&
						!errorText.includes('still loading from acp')
					) {
						break;
					}
				}
			}

			if (result.success) {
				const pathLabel = result.savedPath ? ` to ${result.savedPath}` : '';
				setSessionActionStatus(`Exported chat${pathLabel}`, 'success');
				return;
			}
			if (result.canceled) {
				return;
			}
			const errorMessage = result.error || 'Failed to export session.';
			setSessionActionStatus(errorMessage, 'error');
			console.warn('Failed to export session:', errorMessage);
		} catch (e) {
			setSessionActionStatus('Failed to export session.', 'error');
			console.warn('Failed to export session:', e);
		}
	}

	async function handleContinueInTerminal(sessionId: string) {
		const result = await getSessionTerminalResumeCommand(sessionId);
		if (!result.supported || !result.command) {
			console.warn('Continue in terminal:', result.error ?? 'Unsupported');
			return;
		}
		currentTab.set('terminal');
		pendingTerminalPaste.set({ line: result.command, openInNewTab: true });
	}

	async function handleRefresh() {
		isRefreshing = true;
		try {
			await refreshSessions();
		} finally {
			// Keep the spinner for at least 1s so it's visible
			setTimeout(() => {
				isRefreshing = false;
			}, 1000);
		}
	}
</script>

<aside class="flex h-full w-[280px] shrink-0 flex-col border-r border-border bg-sidebar">
	<!-- New chat / Setup agents -->
	<div class="px-3 pb-1 pt-2.5">
		{#if $agents.length === 0}
			<button
				class="border-border/80 flex w-full items-center justify-center gap-2 rounded-lg border border-dashed px-3 py-2.5 text-[13px] text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
				onclick={() => {
					openSettings();
				}}
			>
				<span>Set up agents in Settings</span>
			</button>
		{:else}
			<div class="flex items-stretch">
				<button
					class="border-border/80 bg-secondary/50 flex min-h-10 flex-1 items-center gap-2 rounded-l-lg border px-3 py-2 text-[13px] text-sidebar-foreground transition-colors hover:bg-secondary"
					onclick={handleNewChat}
				>
					{#if $selectedAgent?.iconUrl}
						<img
							src={$selectedAgent.iconUrl}
							alt=""
							class="h-4 w-4 shrink-0 opacity-70 dark:invert"
						/>
					{:else if $selectedAgent}
						<span
							class="flex h-5 w-5 items-center justify-center rounded text-[9px] font-bold text-white"
							style="background-color: {$selectedAgent.color};"
						>
							{$selectedAgent.letter}
						</span>
					{/if}
					<span class="truncate">{$selectedAgent ? $selectedAgent.shortName : 'New Chat'}</span>
				</button>
				<DropdownMenu.Root>
					<DropdownMenu.Trigger
						class="border-border/80 bg-secondary/50 flex min-h-10 min-w-10 items-center justify-center rounded-r-lg border border-l-0 transition-colors hover:bg-secondary"
						aria-label="Choose agent for new chat"
					>
						<Icon
							icon={ArrowDown01Icon}
							size={14}
							strokeWidth={1.5}
							class="text-muted-foreground"
						/>
					</DropdownMenu.Trigger>
					<DropdownMenu.Content class="w-[248px]" side="bottom" align="start" sideOffset={4}>
						<DropdownMenu.Label class="text-[11px] text-muted-foreground"
							>{$t('start_with')}</DropdownMenu.Label
						>
						{#each $agents as agent (agent.name)}
							<DropdownMenu.Item
								class="flex min-h-10 items-center gap-2.5 px-2 py-2"
								onclick={() => handleSelectAgent(agent)}
							>
								{#if agent.iconUrl}
									<span
										class="flex h-6 w-6 shrink-0 items-center justify-center"
										style="color: {agent.color};"
									>
										<img src={agent.iconUrl} alt="" class="h-4.5 w-4.5 opacity-70 dark:invert" />
									</span>
								{:else}
									<span
										class="flex h-6 w-6 items-center justify-center rounded text-[9px] font-bold text-white"
										style="background-color: {agent.color};"
									>
										{agent.letter}
									</span>
								{/if}
								<div class="min-w-0 flex-1">
									<div class="flex items-baseline gap-1.5">
										<span class="truncate text-[13px]">{agent.name}</span>
										{#if agent.provider}
											<span class="text-muted-foreground/50 shrink-0 text-[11px]"
												>{agent.provider}</span
											>
										{/if}
									</div>
									{#if agent.status === 'not_installed'}
										<div class="truncate text-[11px] text-amber-400/60">
											{agent.statusMessage || $t('setup_click')}
										</div>
									{:else if agent.status === 'missing_key'}
										<div class="truncate text-[11px] text-amber-400/60">
											{agent.statusMessage || $t('api_key_needed')}
										</div>
									{/if}
								</div>
								<span class="h-2 w-2 shrink-0 rounded-full {statusDotColor(agent.status)}"></span>
							</DropdownMenu.Item>
							{#if agent.id === 'Local & BYOK Chat' || agent.id === 'OpenRouter'}
								<DropdownMenu.Separator />
							{/if}
						{/each}
						<DropdownMenu.Separator />
						<DropdownMenu.Item
							class="text-muted-foreground/60 flex min-h-10 items-center gap-2.5 px-2 py-2 text-[13px]"
							onclick={() => openSettings('agents')}
						>
							<span
								class="text-muted-foreground/40 flex h-6 w-6 shrink-0 items-center justify-center"
								>+</span
							>
							<span>Browse more agents...</span>
						</DropdownMenu.Item>
					</DropdownMenu.Content>
				</DropdownMenu.Root>
			</div>
		{/if}
	</div>

	<!-- Sessions header -->
	<div class="flex items-center justify-between px-4 pb-1 pt-3">
		<span class="text-[11px] font-medium uppercase tracking-wider text-muted-foreground"
			>{$t('sessions')}</span
		>
		<button
			class="text-muted-foreground/50 hover:bg-sidebar-accent/60 flex h-10 w-10 items-center justify-center rounded transition-colors hover:text-muted-foreground"
			onclick={handleRefresh}
			title={$t('refresh_session_list')}
			aria-label={$t('refresh_session_list')}
		>
			<Icon
				icon={ReloadIcon}
				size={12}
				strokeWidth={1.5}
				class={isRefreshing || $isConnectingAgents ? 'animate-spin' : ''}
			/>
		</button>
	</div>
	{#if $sessions.length > 0}
		<div class="px-3 pb-1">
			<div class="relative">
				<span class="text-muted-foreground/40 absolute left-2 top-1/2 -translate-y-1/2">
					<Icon icon={Search01Icon} size={12} strokeWidth={1.5} />
				</span>
				<input
					type="text"
					bind:value={searchQuery}
					placeholder={$t('search_sessions_placeholder')}
					spellcheck="false"
					class="border-border/50 bg-secondary/30 placeholder:text-muted-foreground/40 min-h-10 w-full rounded-md border py-2 pl-7 pr-2.5 text-[12px] text-foreground focus:border-[var(--ue-accent-muted)] focus:outline-none"
					aria-label={$t('search_sessions_placeholder')}
				/>
			</div>
		</div>
	{/if}
	{#if sessionActionStatusMessage}
		<div
			class="px-4 pb-1 text-[11px] {sessionActionStatusTone === 'success'
				? 'text-emerald-400/80'
				: 'text-red-400/85'}"
		>
			{sessionActionStatusMessage}
		</div>
	{/if}

	<!-- Session list (scrollable, grouped by date) -->
	<div
		bind:this={sessionListEl}
		bind:clientHeight={sessionListViewportHeight}
		class="min-h-0 flex-1 overflow-y-auto px-2 pb-2"
		onscroll={handleSessionListScroll}
	>
		{#if $isLoadingSessions}
			<div class="flex flex-col gap-0.5 pt-0.5">
				{#each [0, 1, 2, 3] as skeleton (skeleton)}
					<div class="flex animate-pulse items-center gap-2 rounded-md px-2 py-1.5">
						<div class="bg-muted-foreground/10 h-4 w-4 shrink-0 rounded"></div>
						<div class="bg-muted-foreground/10 h-3.5 flex-1 rounded"></div>
						<div class="bg-muted-foreground/10 h-3 w-6 shrink-0 rounded"></div>
					</div>
				{/each}
			</div>
		{:else if $sessions.length === 0 && $isConnectingAgents}
			<!-- Agents are connecting, sessions haven't arrived yet -->
			<div class="text-muted-foreground/50 flex flex-col items-center justify-center gap-2 py-8">
				<div class="animate-spin">
					<Icon icon={ReloadIcon} size={20} strokeWidth={1.5} />
				</div>
				<span class="text-[12px]">{$t('loading_sessions')}</span>
			</div>
		{:else if $sessions.length === 0}
			<div class="text-muted-foreground/50 flex flex-col items-center justify-center gap-3 py-8">
				<Icon icon={MessageMultiple01Icon} size={24} strokeWidth={1.5} />
				<span class="text-[12px]">{$t('no_sessions_yet')}</span>
				<button
					class="text-muted-foreground/60 text-[11px] underline underline-offset-2 transition-colors hover:text-muted-foreground"
					onclick={handleRefresh}
				>
					{$t('retry_loading')}
				</button>
			</div>
		{:else if searchQuery.trim() && filteredGroupedSessions.length === 0}
			<div class="text-muted-foreground/50 flex flex-col items-center justify-center gap-2 py-8">
				<Icon icon={Search01Icon} size={20} strokeWidth={1.5} />
				<span class="text-[12px]">{$t('no_matching_sessions')}</span>
			</div>
		{:else}
			<div class="relative" style:height={`${totalSessionListHeight}px`}>
				{#each visibleSessionRows as row (row.key)}
					<div
						class="absolute left-0 right-0"
						style:height={`${row.height}px`}
						style:transform={`translateY(${row.top}px)`}
					>
						{#if row.kind === 'group'}
							<div class="flex h-full items-end px-2 pb-1">
								<span class="text-muted-foreground/50 text-[11px] font-medium">{row.label}</span>
							</div>
						{:else}
							{@const session = row.session}
							{@const agent = agentByName[session.agentName]}
							{@const sessionStatus = getSessionSidebarStatus(
								session.sessionId,
								$sessionStates,
								$recentlyFinished
							)}
							{@const needsAttention =
								$sessionsNeedingAttention.has(session.sessionId) &&
								$currentSessionId !== session.sessionId}
							{@const dotKind = (
								needsAttention
									? 'needs_attention'
									: sessionStatus === 'working'
										? 'working'
										: sessionStatus === 'finished'
											? 'finished'
											: null
							) as SessionSidebarKind | null}
							{@const dotStyle = dotKind ? getSessionSidebarDotStyle(dotKind) : null}
							{@const dotTitle =
								dotKind === 'needs_attention'
									? 'Needs permission approval'
									: dotKind === 'working'
										? $t('working')
										: dotKind === 'finished'
											? $t('finished')
											: ''}
							<ContextMenu.Root>
								<ContextMenu.Trigger>
									<button
										class="flex h-10 w-full items-center gap-2 rounded-md px-2 text-left transition-colors {$currentSessionId ===
										session.sessionId
											? 'bg-sidebar-accent text-sidebar-foreground'
											: 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60'}"
										onclick={() => {
											setupAgent.set(null);
											selectSession(session.sessionId);
										}}
									>
										{#if agent?.iconUrl}
											<span
												class="flex h-4 w-4 shrink-0 items-center justify-center"
												style="color: {agent.color};"
											>
												<img
													src={agent.iconUrl}
													alt=""
													class="h-3.5 w-3.5 opacity-70 dark:invert"
												/>
											</span>
										{:else}
											<span
												class="flex h-4 w-4 shrink-0 items-center justify-center rounded text-[7px] font-bold text-white"
												style="background-color: {agent?.color ?? '#666'};"
											>
												{agent?.letter ?? '?'}
											</span>
										{/if}
										{#if renamingSessionId === session.sessionId}
											<!-- svelte-ignore a11y_autofocus -->
											<input
												bind:this={renameInputEl}
												bind:value={renameValue}
												class="ring-[var(--ue-accent)]/50 min-w-0 flex-1 rounded bg-secondary px-1 py-0.5 text-[13px] text-foreground outline-none ring-1"
												onkeydown={handleRenameKeydown}
												onblur={commitRename}
												onclick={(event) => event.stopPropagation()}
												autofocus
											/>
										{:else}
											<span class="flex-1 truncate text-[13px]"
												>{session.title || $t('new_chat')}</span
											>
										{/if}
										<span class="ml-1 flex shrink-0 items-center gap-1.5">
											{#if dotStyle}
												<span
													class="h-2 w-2 shrink-0 rounded-full {dotStyle.dotClass} {dotStyle.pulse
														? 'animate-pulse'
														: ''}"
													title={dotTitle}
												></span>
											{/if}
											<span class="text-[11px] text-muted-foreground"
												>{formatTimeAgo(session.lastModifiedAt)}</span
											>
										</span>
									</button>
								</ContextMenu.Trigger>
								<ContextMenu.Content class="w-[220px]">
									<ContextMenu.Item
										class="flex items-center gap-2 text-[13px]"
										onclick={() => startRename(session.sessionId, session.title || '')}
									>
										<Icon icon={PencilEdit01Icon} size={14} strokeWidth={1.5} />
										{$t('rename')}
									</ContextMenu.Item>
									<ContextMenu.Separator />
									<ContextMenu.Item
										class="text-[13px]"
										disabled={!session.terminalResumeSupported || !$terminalEnabled}
										onclick={() => handleContinueInTerminal(session.sessionId)}
									>
										{$t('continue_in_terminal')}
									</ContextMenu.Item>
									<ContextMenu.Separator />
									<ContextMenu.Item
										class="text-[13px]"
										disabled={sessionStatus === 'working'}
										onclick={() => handleExport(session.sessionId)}
									>
										{$t('export_as_markdown')}
									</ContextMenu.Item>
									<ContextMenu.Separator />
									<ContextMenu.Item
										class="flex items-center gap-2 text-[13px] text-red-400 data-[highlighted]:text-red-400"
										disabled={sessionStatus === 'working'}
										onclick={() => requestDelete(session)}
									>
										<Icon icon={Delete02Icon} size={14} strokeWidth={1.5} />
										{$t('delete')}
									</ContextMenu.Item>
								</ContextMenu.Content>
							</ContextMenu.Root>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>

	<!-- Bottom: account row with inline Discord + Settings icons -->
	<div class="flex items-center gap-1 border-t border-border px-2 py-1.5">
		<div class="min-w-0 flex-1">
			<NeoStackAccountCard variant="sidebar" />
		</div>
		<a
			href="https://discord.gg/betide"
			target="_blank"
			rel="noopener noreferrer"
			class="focus-ring text-sidebar-foreground/70 flex h-10 w-10 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
			title="Discord"
			aria-label="Discord"
		>
			<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" class="shrink-0">
				<path
					d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.095 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"
				/>
			</svg>
		</a>
		<button
			class="focus-ring text-sidebar-foreground/70 flex h-10 w-10 shrink-0 items-center justify-center rounded-md transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
			onclick={() => openSettings()}
			title={$t('settings')}
			aria-label={$t('settings')}
		>
			<Icon icon={Settings02Icon} size={14} strokeWidth={1.5} />
		</button>
	</div>
</aside>

{#if deleteCandidate}
	{@const deleteMessageCount = deleteCandidate.messageCount ?? 0}
	<AlertDialog.Root
		open={true}
		onOpenChange={(open) => {
			if (!open && !isDeletingSession) deleteCandidate = null;
		}}
	>
		<AlertDialog.Portal>
			<AlertDialog.Overlay class="fixed inset-0 z-[80] bg-black/60 backdrop-blur-[1px]" />
			<AlertDialog.Content
				class="fixed left-1/2 top-1/2 z-[81] w-[min(420px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-border bg-card p-5 shadow-2xl outline-none"
			>
				<AlertDialog.Title class="text-[15px] font-medium text-foreground">
					Delete this chat?
				</AlertDialog.Title>
				<AlertDialog.Description class="mt-2 text-[13px] leading-relaxed text-muted-foreground">
					“{deleteCandidate.title || $t('new_chat')}”{deleteMessageCount > 0
						? ` contains ${deleteMessageCount} message${deleteMessageCount === 1 ? '' : 's'}.`
						: ''}
					This permanently removes local and agent history. It cannot be undone.
				</AlertDialog.Description>
				<div class="mt-5 flex justify-end gap-2">
					<AlertDialog.Cancel
						class="focus-ring min-h-10 rounded-md px-4 text-[13px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
						disabled={isDeletingSession}
					>
						Cancel
					</AlertDialog.Cancel>
					<button
						type="button"
						class="focus-ring min-h-10 rounded-md bg-red-500 px-4 text-[13px] font-medium text-white transition-colors hover:bg-red-400 disabled:cursor-wait disabled:opacity-60"
						disabled={isDeletingSession}
						onclick={confirmDelete}
					>
						{isDeletingSession ? 'Deleting…' : 'Delete permanently'}
					</button>
				</div>
			</AlertDialog.Content>
		</AlertDialog.Portal>
	</AlertDialog.Root>
{/if}
