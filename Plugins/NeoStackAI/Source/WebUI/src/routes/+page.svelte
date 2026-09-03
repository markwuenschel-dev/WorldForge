<script lang="ts">
	import { onMount, type Component } from 'svelte';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import ChatPane from '$lib/components/ChatPane.svelte';
	import { currentTab } from '$lib/stores/navigation.js';
	import { paneManager } from '$lib/stores/panes.svelte.js';
	import UsageBar from '$lib/components/UsageBar.svelte';
	import AuthBanner from '$lib/components/AuthBanner.svelte';
	import UpdateAvailableBanner from '$lib/components/UpdateAvailableBanner.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import {
		SidebarLeftIcon,
		ArrowDown01Icon,
		LayoutLeftIcon,
		Cancel01Icon
	} from '@hugeicons/core-free-icons';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu/index.js';
	import { Dialog } from 'bits-ui';
	import {
		agents,
		selectedAgent,
		agentsLoaded,
		statusDotColor,
		type Agent
	} from '$lib/stores/agents.js';
	import { showOnboarding, onboardingLoading, checkOnboarding } from '$lib/stores/onboarding.js';
	import {
		sessions,
		currentSessionId,
		createNewSession,
		selectSession
	} from '$lib/stores/sessions.js';
	import {
		models,
		currentModelId,
		modelBrowserOpen,
		allModels,
		isLoadingAllModels,
		changeModel,
		closeModelBrowser,
		loadModelsForAgent,
		loadReasoningLevel
	} from '$lib/stores/models.js';
	import { currentState, activeSessionId, stateDisplay } from '$lib/stores/agentState.js';
	import { availableModes, currentModeId, loadModesForAgent } from '$lib/stores/modes.js';
	import { setupAgent, enterSetup } from '$lib/stores/setup.js';
	import { loadAgentUsage } from '$lib/stores/rateLimits.js';
	import { resetAuth } from '$lib/stores/auth.js';
	import { settingsOpen, studioEnabled, terminalEnabled } from '$lib/stores/settings.js';
	import { t } from '$lib/i18n.js';
	import { toast } from 'svelte-sonner';
	import { stopAllPolling, resumeActivePolling } from '$lib/stores/studio.js';

	let sidebarOpen = $state(
		(() => {
			try {
				const v = localStorage.getItem('sidebar_open');
				return v !== null ? v === 'true' : true;
			} catch {
				return true;
			}
		})()
	);
	let sidebarMounted = $state(false);
	onMount(() => {
		const narrowViewport = window.matchMedia('(max-width: 720px)');
		const collapseForNarrowViewport = (event: MediaQueryList | MediaQueryListEvent) => {
			if (event.matches) sidebarOpen = false;
		};
		collapseForNarrowViewport(narrowViewport);
		narrowViewport.addEventListener('change', collapseForNarrowViewport);
		return () => narrowViewport.removeEventListener('change', collapseForNarrowViewport);
	});
	$effect(() => {
		requestAnimationFrame(() => {
			sidebarMounted = true;
		});
	});
	let studioMountedOnce = $state(false);
	let terminalMountedOnce = $state(false);
	let SettingsPanelComponent = $state<Component | null>(null);
	let AgentSetupComponent = $state<Component<{ agent: Agent }> | null>(null);
	let OnboardingWizardComponent = $state<Component | null>(null);
	let StudioPageComponent = $state<Component | null>(null);
	let TerminalPaneComponent = $state<Component | null>(null);

	$effect(() => {
		if ($settingsOpen && !SettingsPanelComponent) {
			import('$lib/components/SettingsPanel.svelte').then((module) => {
				SettingsPanelComponent = module.default;
			});
		}
		if ($setupAgent && !AgentSetupComponent) {
			import('$lib/components/AgentSetup.svelte').then((module) => {
				AgentSetupComponent = module.default;
			});
		}
		if (!$onboardingLoading && $showOnboarding && !OnboardingWizardComponent) {
			import('$lib/components/OnboardingWizard.svelte').then((module) => {
				OnboardingWizardComponent = module.default;
			});
		}
	});

	// Check onboarding status once agents are loaded
	$effect(() => {
		if ($agentsLoaded) {
			checkOnboarding();
		}
	});

	// Sync activeSessionId for agent state tracking
	$effect(() => {
		activeSessionId.set($currentSessionId);
	});

	// Initialize pane manager when first session is selected.
	// Only sync focused pane when currentSessionId actually changes (not on focus switch).
	let prevSyncedSessionId: string | null = null;
	$effect(() => {
		const sid = $currentSessionId;
		if (!sid) return;
		if (paneManager.paneCount === 0) {
			paneManager.init(sid);
			prevSyncedSessionId = sid;
		} else if (sid !== prevSyncedSessionId) {
			// currentSessionId changed externally (sidebar click, new chat) — update focused pane
			prevSyncedSessionId = sid;
			const focusedPane = paneManager.focusedPane;
			if (focusedPane && focusedPane.sessionId !== sid) {
				paneManager.openInFocused(sid);
			}
		}
	});

	function handleSplitPane() {
		if (paneManager.canSplit) {
			paneManager.split(null); // New empty pane, user picks a session
		}
	}

	function handleUnsplit() {
		paneManager.unsplit();
	}

	function handlePaneFocus(index: number) {
		paneManager.setFocus(index);
		// Sync currentSessionId to focused pane's session
		const pane = paneManager.panes[index];
		if (pane?.sessionId && pane.sessionId !== $currentSessionId) {
			void selectSession(pane.sessionId);
		}
	}

	// Load models and modes when session is active (requires both agent + session)
	$effect(() => {
		const agent = $selectedAgent;
		const sid = $currentSessionId;
		if (agent && sid) {
			loadModelsForAgent(agent.name);
			loadReasoningLevel(agent.name);
			loadModesForAgent(agent.name);
		} else {
			// No session — clear agent-specific UI state
			models.set([]);
			currentModelId.set('');
			availableModes.set([]);
			currentModeId.set('');
		}
	});

	// Load rate limit data when selected agent changes
	$effect(() => {
		const agent = $selectedAgent;
		if (agent && agent.status === 'available') {
			loadAgentUsage(agent.name);
		}
	});

	// Reset route-level transient state when the focused session changes.
	// ChatPane owns message loading because each pane has its own sessionId.
	$effect(() => {
		const sid = $currentSessionId;
		if (sid) resetAuth();
	});

	// If the currently-active top-nav tab gets disabled from settings, fall back to chat.
	$effect(() => {
		if ($currentTab === 'studio' && !$studioEnabled) currentTab.set('chat');
		if ($currentTab === 'terminal' && !$terminalEnabled) currentTab.set('chat');
		if ($currentTab === 'studio' && $studioEnabled) {
			studioMountedOnce = true;
			if (!StudioPageComponent) {
				import('$lib/components/StudioPage.svelte').then((mod) => {
					StudioPageComponent = mod.default;
				});
			}
		}
		if ($currentTab === 'terminal' && $terminalEnabled) {
			terminalMountedOnce = true;
			if (!TerminalPaneComponent) {
				import('$lib/components/TerminalPane.svelte').then((mod) => {
					TerminalPaneComponent = mod.default;
				});
			}
		}
	});

	// Studio job polling only runs while the Studio tab is actually visible.
	// The page stays mounted (hidden) across tab switches, so without this a
	// single visit to Studio would leave its 3s polls running for the editor's
	// lifetime. Resume when the tab is shown again so in-flight jobs update.
	$effect(() => {
		if ($currentTab === 'studio' && !$settingsOpen) {
			resumeActivePolling();
		} else {
			stopAllPolling();
		}
	});

	// Current session title for the header
	let currentSession = $derived($sessions.find((s) => s.sessionId === $currentSessionId));
	let headerTitle = $derived(
		$currentSessionId ? currentSession?.title || $t('new_chat') : $t('agent_chat')
	);
	let headerAgent = $derived(
		$currentSessionId ? (currentSession?.agentName ?? $selectedAgent?.name ?? '') : ''
	);

	// Connection state
	let connectionInfo = $derived($currentState ? stateDisplay[$currentState.state] : null);

	// Model browser
	let modelSearchQuery = $state('');
	let modelSearchInput = $state<HTMLInputElement | undefined>();
	let modelListEl = $state<HTMLDivElement | undefined>();
	let modelListScrollTop = $state(0);
	let modelListViewportHeight = $state(520);
	const MODEL_ROW_HEIGHT = 64;
	const MODEL_ROW_OVERSCAN = 6;
	let filteredAllModels = $derived.by(() => {
		const q = modelSearchQuery.trim().toLowerCase();
		if (!q) return $allModels;
		return $allModels.filter(
			(model) =>
				model.name.toLowerCase().includes(q) ||
				model.id.toLowerCase().includes(q) ||
				(model.description ?? '').toLowerCase().includes(q)
		);
	});
	let modelWindowStart = $derived(
		Math.max(0, Math.floor(modelListScrollTop / MODEL_ROW_HEIGHT) - MODEL_ROW_OVERSCAN)
	);
	let modelWindowEnd = $derived(
		Math.min(
			filteredAllModels.length,
			Math.ceil((modelListScrollTop + modelListViewportHeight) / MODEL_ROW_HEIGHT) +
				MODEL_ROW_OVERSCAN
		)
	);
	let visibleCatalogModels = $derived(filteredAllModels.slice(modelWindowStart, modelWindowEnd));

	$effect(() => {
		if (!$modelBrowserOpen) return;
		modelSearchQuery = '';
		modelListScrollTop = 0;
		requestAnimationFrame(() => {
			if (modelListEl) modelListEl.scrollTop = 0;
			modelSearchInput?.focus();
		});
	});

	function handleModelCatalogScroll(): void {
		if (!modelListEl) return;
		modelListScrollTop = modelListEl.scrollTop;
		modelListViewportHeight = modelListEl.clientHeight;
	}
	async function handleSelectModelFromBrowser(modelId: string) {
		if (!$selectedAgent) return;
		try {
			await changeModel($selectedAgent.name, modelId);
		} catch (e) {
			// changeModel reverts its optimistic update and rethrows — keep the
			// browser open so the user can pick again.
			toast.error($t('change_model_failed'), {
				description: e instanceof Error ? e.message : String(e)
			});
			return;
		}
		closeModelBrowser();
	}

	function toggleSidebar() {
		sidebarOpen = !sidebarOpen;
		try {
			localStorage.setItem('sidebar_open', String(sidebarOpen));
		} catch {
			// Storage can be unavailable in hardened embedded-browser profiles.
		}
	}

	async function selectAgent(agent: Agent) {
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

	async function handlePaneStartSession(agentName: string) {
		const agent = $agents.find((a) => a.name === agentName);
		if (!agent || agent.status !== 'available') return;
		setupAgent.set(null);
		selectedAgent.set(agent);
		await createNewSession(agent.name, paneManager.focusedPane?.paneId ?? `pane:${agent.name}`);
		loadModelsForAgent(agent.name);
	}

	async function handleNewChat() {
		if ($selectedAgent) {
			if ($selectedAgent.status !== 'available') {
				currentSessionId.set(null);
				enterSetup($selectedAgent);
			} else {
				setupAgent.set(null);
				await createNewSession($selectedAgent.name);
				loadModelsForAgent($selectedAgent.name);
			}
		}
	}
</script>

<!-- Only the active heavy surface is mounted. Transcript state lives in stores,
     while inactive Markdown trees, subscriptions, and autoscroll stay suspended. -->
{#if $settingsOpen && SettingsPanelComponent}
	<div class="flex min-w-0 flex-1">
		<SettingsPanelComponent />
	</div>
{/if}

<!-- Studio page — only mounted when enabled. Hidden when chat is active or settings is open (preserves state). -->
{#if !$settingsOpen && $currentTab === 'studio' && $studioEnabled && studioMountedOnce && StudioPageComponent}
	<div class="flex min-w-0 flex-1">
		<StudioPageComponent />
	</div>
{/if}

<!-- Terminal page — only mounted when enabled. Hidden when not active or settings is open (preserves PTY session). -->
{#if !$settingsOpen && $currentTab === 'terminal' && $terminalEnabled && terminalMountedOnce && TerminalPaneComponent}
	<div class="flex min-w-0 flex-1">
		<TerminalPaneComponent />
	</div>
{/if}

{#if !$settingsOpen && $currentTab === 'chat'}
	<div class="relative flex min-w-0 flex-1">
		{#if sidebarOpen}
			<button
				class="sidebar-mobile-backdrop absolute inset-0 z-30 bg-black/45"
				onclick={() => (sidebarOpen = false)}
				aria-label="Close sidebar"
			></button>
		{/if}
		<!-- Sidebar with animated width -->
		<div
			class="chat-sidebar shrink-0 overflow-hidden {sidebarOpen
				? 'chat-sidebar-open'
				: ''} {sidebarMounted ? 'duration-250 transition-[width,transform] ease-out' : ''}"
		>
			<div class="h-full w-[280px]">
				<Sidebar />
			</div>
		</div>

		<!-- Main chat area -->
		<main class="flex min-w-0 flex-1 flex-col">
			<!-- Top header bar — matches UE toolbar style -->
			<header
				class="flex h-10 shrink-0 items-center justify-between border-b border-border bg-surface-bar px-3"
			>
				<div class="flex min-w-0 flex-1 items-center gap-2 text-[13px]">
					<!-- Sidebar toggle -->
					<button
						class="focus-ring flex h-10 w-10 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
						onclick={toggleSidebar}
						title={sidebarOpen ? $t('hide_sidebar') : $t('show_sidebar')}
						aria-label={sidebarOpen ? $t('hide_sidebar') : $t('show_sidebar')}
					>
						<Icon icon={SidebarLeftIcon} size={16} strokeWidth={1.5} />
					</button>
					<div class="flex min-w-0 flex-1 items-center gap-2">
						<span class="min-w-0 flex-1 truncate font-medium text-foreground" title={headerTitle}>
							{headerTitle}
						</span>
						{#if headerAgent}
							<span class="max-w-[120px] truncate text-muted-foreground" title={headerAgent}>
								{headerAgent}
							</span>
						{/if}
					</div>
					{#if paneManager.isMultiPane}
						<button
							class="focus-ring flex h-10 w-10 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
							onclick={handleUnsplit}
							title="Close split panes"
							aria-label="Close split panes"
						>
							<Icon icon={Cancel01Icon} size={14} strokeWidth={1.5} />
						</button>
					{/if}
					{#if paneManager.canSplit && $currentSessionId}
						<button
							class="focus-ring flex h-10 w-10 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
							onclick={handleSplitPane}
							title="Split pane"
							aria-label="Split pane"
						>
							<Icon icon={LayoutLeftIcon} size={16} strokeWidth={1.5} />
						</button>
					{/if}
				</div>
				<div class="ml-2 flex shrink-0 items-center gap-2">
					<UsageBar />
					{#if connectionInfo}
						<span
							class="border-border/80 bg-secondary/30 flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] text-muted-foreground"
						>
							<span
								class="h-2 w-2 shrink-0 rounded-full {connectionInfo.dotClass} {connectionInfo.pulse
									? 'animate-pulse'
									: ''}"
							></span>
							{connectionInfo.label}
						</span>
					{/if}
					<!-- New thread button (visible when sidebar is collapsed) -->
					{#if !sidebarOpen}
						<div class="flex items-stretch">
							<button
								class="border-border/80 bg-secondary/50 flex min-h-10 items-center gap-1.5 rounded-l-md border px-2 py-2 text-[12px] text-sidebar-foreground transition-colors hover:bg-secondary"
								title={$t('new_chat_agent', { agentName: $selectedAgent?.shortName ?? '' })}
								onclick={handleNewChat}
							>
								{#if $selectedAgent?.iconUrl}
									<span
										class="flex h-4 w-4 shrink-0 items-center justify-center"
										style="color: {$selectedAgent.color};"
									>
										<img
											src={$selectedAgent.iconUrl}
											alt=""
											class="h-3.5 w-3.5 opacity-70 dark:invert"
										/>
									</span>
								{:else if $selectedAgent}
									<span
										class="flex h-4 w-4 items-center justify-center rounded text-[7px] font-bold text-white"
										style="background-color: {$selectedAgent.color};"
									>
										{$selectedAgent.letter}
									</span>
								{/if}
								<span>{$t('new_short')}</span>
							</button>
							<DropdownMenu.Root>
								<DropdownMenu.Trigger
									class="border-border/80 bg-secondary/50 flex min-h-10 min-w-10 items-center justify-center rounded-r-md border border-l-0 transition-colors hover:bg-secondary"
									aria-label="Choose agent for new chat"
								>
									<Icon
										icon={ArrowDown01Icon}
										size={12}
										strokeWidth={1.5}
										class="text-muted-foreground"
									/>
								</DropdownMenu.Trigger>
								<DropdownMenu.Content class="w-[220px]" side="bottom" align="end" sideOffset={4}>
									<DropdownMenu.Label class="text-[11px] text-muted-foreground"
										>{$t('start_with')}</DropdownMenu.Label
									>
									{#each $agents as agent (agent.name)}
										<DropdownMenu.Item
											class="flex min-h-10 items-center gap-2.5 px-2 py-2"
											onclick={() => selectAgent(agent)}
										>
											{#if agent.iconUrl}
												<span
													class="flex h-5 w-5 shrink-0 items-center justify-center"
													style="color: {agent.color};"
												>
													<img src={agent.iconUrl} alt="" class="h-4 w-4 opacity-70 dark:invert" />
												</span>
											{:else}
												<span
													class="flex h-5 w-5 items-center justify-center rounded text-[8px] font-bold text-white"
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
														{$t('setup_click')}
													</div>
												{:else if agent.status === 'missing_key'}
													<div class="truncate text-[11px] text-amber-400/60">
														{$t('api_key_needed')}
													</div>
												{:else if agent.description}
													<div class="text-muted-foreground/40 truncate text-[11px]">
														{agent.description}
													</div>
												{/if}
											</div>
											<span class="h-2 w-2 shrink-0 rounded-full {statusDotColor(agent.status)}"
											></span>
										</DropdownMenu.Item>
										{#if agent.id === 'Local & BYOK Chat' || agent.id === 'OpenRouter'}
											<DropdownMenu.Separator />
										{/if}
									{/each}
								</DropdownMenu.Content>
							</DropdownMenu.Root>
						</div>
					{/if}
				</div>
			</header>
			<div class="shrink-0 px-6 pt-3">
				<AuthBanner />
				<UpdateAvailableBanner />
			</div>

			{#if $currentSessionId}
				<!-- Content area — each pane has its own messages + composer -->
				<div class="flex-1 overflow-hidden">
					{#if paneManager.paneCount <= 1}
						<!-- Single pane mode — no PaneForge overhead -->
						<ChatPane sessionId={$currentSessionId} isFocused={true} />
					{:else}
						<!-- Multi-pane mode — PaneForge resizable split -->
						<PaneGroup direction="horizontal" autoSaveId="chat-panes">
							{#each paneManager.panes as pane, idx (pane.paneId)}
								<Pane
									defaultSize={Math.round(100 / paneManager.paneCount)}
									minSize={20}
									order={idx + 1}
								>
									<div
										class="h-full {paneManager.focusedIndex === idx
											? 'ring-[var(--ue-accent)]/20 ring-1 ring-inset'
											: ''}"
										onpointerdown={() => handlePaneFocus(idx)}
										onfocusin={() => handlePaneFocus(idx)}
										role="region"
										tabindex="-1"
									>
										<ChatPane
											sessionId={pane.sessionId}
											isFocused={paneManager.focusedIndex === idx}
											showPaneHeader={true}
											onStartSession={handlePaneStartSession}
										/>
									</div>
								</Pane>
								{#if idx < paneManager.paneCount - 1}
									<PaneResizer>
										<div
											class="bg-border/40 hover:bg-[var(--ue-accent)]/40 h-full w-1 cursor-col-resize transition-colors"
										></div>
									</PaneResizer>
								{/if}
							{/each}
						</PaneGroup>
					{/if}
				</div>
			{:else if !$onboardingLoading && $showOnboarding && OnboardingWizardComponent}
				<!-- First-launch onboarding wizard -->
				<OnboardingWizardComponent />
			{:else if $setupAgent && AgentSetupComponent}
				<!-- Agent setup flow — agent not installed or missing key -->
				<AgentSetupComponent agent={$setupAgent} />
			{:else}
				<!-- Welcome screen — no active session -->
				<div class="flex flex-1 flex-col items-center justify-center gap-8 px-6">
					<div class="flex flex-col items-center gap-3">
						{#if $selectedAgent?.iconUrl}
							<span style="color: {$selectedAgent.color}; opacity: 0.4;">
								<img src={$selectedAgent.iconUrl} alt="" class="h-12 w-12 opacity-70 dark:invert" />
							</span>
						{/if}
						<h2 class="text-foreground/70 text-balance text-center text-lg font-light">
							{$t('start_new_conversation')}
						</h2>
						<p class="text-muted-foreground/50 text-pretty text-center text-[13px]">
							{$t('choose_agent_below')}
						</p>
					</div>

					<div class="flex flex-wrap justify-center gap-2.5">
						{#each $agents.filter((a) => a.status === 'available') as agent (agent.name)}
							<button
								class="bg-card/40 text-foreground/80 hover:bg-card/70 flex items-center gap-2.5 rounded-xl border border-border px-4 py-2.5 text-[13px] transition-all hover:border-[var(--ue-accent-muted)] active:scale-[0.98]"
								onclick={async () => {
									selectedAgent.set(agent);
									await createNewSession(agent.name);
								}}
							>
								{#if agent.iconUrl}
									<span
										class="flex h-5 w-5 items-center justify-center"
										style="color: {agent.color};"
									>
										<img src={agent.iconUrl} alt="" class="h-4.5 w-4.5 opacity-70 dark:invert" />
									</span>
								{:else}
									<span
										class="flex h-5 w-5 items-center justify-center rounded text-[8px] font-bold text-white"
										style="background-color: {agent.color};"
									>
										{agent.letter}
									</span>
								{/if}
								{agent.shortName}
							</button>
						{/each}
					</div>

					{#if $agents.some((a) => a.status !== 'available')}
						<div class="flex flex-wrap justify-center gap-2">
							{#each $agents.filter((a) => a.status !== 'available') as agent (agent.name)}
								<button
									class="text-muted-foreground/40 hover:bg-card/30 hover:text-muted-foreground/60 flex min-h-10 cursor-pointer items-center gap-1.5 rounded-lg px-3 py-2 text-[12px] transition-colors"
									onclick={() => enterSetup(agent)}
								>
									{#if agent.iconUrl}
										<span style="color: {agent.color}; opacity: 0.35;">
											<img src={agent.iconUrl} alt="" class="h-3.5 w-3.5 opacity-70 dark:invert" />
										</span>
									{/if}
									{agent.shortName}
									<span class="text-[10px]"
										>({agent.status === 'not_installed'
											? $t('set_up')
											: agent.status === 'missing_key'
												? $t('configure')
												: $t('unavailable')})</span
									>
								</button>
							{/each}
						</div>
					{/if}
				</div>
			{/if}

			<Dialog.Root
				open={$modelBrowserOpen}
				onOpenChange={(open) => {
					if (!open) closeModelBrowser();
				}}
			>
				<Dialog.Portal>
					<Dialog.Overlay class="fixed inset-0 z-50 bg-black/55 backdrop-blur-[1px]" />
					<Dialog.Content
						class="fixed left-1/2 top-1/2 z-[51] flex h-[min(78vh,720px)] w-[min(768px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl outline-none"
					>
						<div class="flex items-center justify-between border-b border-border px-4 py-3">
							<div>
								<Dialog.Title class="text-[15px] font-medium text-foreground">
									{$t('browse_openrouter_models')}
								</Dialog.Title>
								<Dialog.Description class="text-[12px] text-muted-foreground">
									{$t('search_full_catalog')}
								</Dialog.Description>
							</div>
							<Dialog.Close
								class="focus-ring min-h-10 rounded-md px-3 text-[12px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
							>
								{$t('close')}
							</Dialog.Close>
						</div>

						<div class="border-b border-border px-4 py-3">
							<input
								bind:this={modelSearchInput}
								type="text"
								bind:value={modelSearchQuery}
								placeholder={$t('search_models_placeholder')}
								class="bg-secondary/40 placeholder:text-muted-foreground/55 w-full rounded-lg border border-border px-3 py-2 text-[13px] text-foreground focus:border-[var(--ue-accent-muted)] focus:outline-none"
								aria-label={$t('search_models_placeholder')}
							/>
						</div>

						<div
							bind:this={modelListEl}
							class="min-h-0 flex-1 overflow-y-auto px-2"
							onscroll={handleModelCatalogScroll}
							role="listbox"
							aria-label={$t('browse_openrouter_models')}
						>
							{#if $isLoadingAllModels}
								<div
									class="text-muted-foreground/70 flex items-center justify-center py-10 text-[13px]"
								>
									{$t('loading_models')}
								</div>
							{:else if filteredAllModels.length === 0}
								<div
									class="text-muted-foreground/70 flex items-center justify-center py-10 text-[13px]"
								>
									{$t('no_models_match_search')}
								</div>
							{:else}
								<div
									class="relative"
									style:height={`${filteredAllModels.length * MODEL_ROW_HEIGHT}px`}
								>
									{#each visibleCatalogModels as model, visibleIndex (model.id)}
										{@const catalogIndex = modelWindowStart + visibleIndex}
										<button
											class="hover:bg-accent/60 absolute left-0 right-0 flex items-center gap-3 rounded-lg px-3 py-2 text-left transition-colors"
											style:height={`${MODEL_ROW_HEIGHT}px`}
											style:transform={`translateY(${catalogIndex * MODEL_ROW_HEIGHT}px)`}
											onclick={() => handleSelectModelFromBrowser(model.id)}
											role="option"
											aria-selected={model.id === $currentModelId}
										>
											<div class="min-w-0 flex-1">
												<div class="flex items-center gap-2 truncate">
													<span class="text-[13px] text-foreground">{model.name}</span>
													{#if model.providerDisplayName}
														<span
															class="bg-foreground/5 text-muted-foreground/40 shrink-0 rounded px-1 py-0.5 text-[9px] uppercase tracking-wider"
															>{model.providerDisplayName}</span
														>
													{/if}
												</div>
												<div class="text-muted-foreground/70 truncate font-mono text-[11px]">
													{model.id}
												</div>
												{#if model.description}
													<div class="text-muted-foreground/55 truncate text-[11px]">
														{model.description}
													</div>
												{/if}
											</div>
											{#if model.id === $currentModelId}
												<span class="h-2 w-2 shrink-0 rounded-full bg-foreground"></span>
											{/if}
										</button>
									{/each}
								</div>
							{/if}
						</div>
					</Dialog.Content>
				</Dialog.Portal>
			</Dialog.Root>
		</main>
	</div>
	<!-- /chat wrapper -->
{/if}
