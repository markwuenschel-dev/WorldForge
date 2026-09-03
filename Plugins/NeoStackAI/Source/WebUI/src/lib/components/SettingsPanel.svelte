<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import {
		Settings02Icon,
		ArrowLeft02Icon,
		Wrench01Icon,
		UserIcon,
		Notification03Icon,
		InformationCircleIcon,
		Add01Icon,
		CheckmarkCircle02Icon,
		Database02Icon,
		Alert02Icon,
		Link01Icon,
		Book02Icon,
		Analytics01Icon,
		PaintBoardIcon
	} from '@hugeicons/core-free-icons';
	import CustomSelect from '$lib/components/ui/custom-select/CustomSelect.svelte';
	import ProjectIndexPanel from '$lib/components/ProjectIndexPanel.svelte';
	import McpConnectionsPanel from '$lib/components/McpConnectionsPanel.svelte';
	import ExtensionsPanel from '$lib/components/ExtensionsPanel.svelte';
	import SkillsPanel from '$lib/components/SkillsPanel.svelte';
	import NotificationsPanel from '$lib/components/NotificationsPanel.svelte';
	import AgentRegistry from '$lib/components/AgentRegistry.svelte';
	import NeoStackSignInButton from '$lib/components/NeoStackSignInButton.svelte';
	import NeoStackAccountCard from '$lib/components/NeoStackAccountCard.svelte';
	import FontPicker from '$lib/components/FontPicker.svelte';
	import { refreshCloudAccount, cloudAccount, formatTierLabel } from '$lib/stores/cloudAccount.js';
	import PrerequisitesPanel from '$lib/components/PrerequisitesPanel.svelte';
	import SetupChecklist from '$lib/components/SetupChecklist.svelte';
	import { locale, localeNames, releasedLocales, setLocale, t, type Locale } from '$lib/i18n.js';
	import {
		settingsTab,
		closeSettings,
		enterToSend,
		studioEnabled,
		terminalEnabled,
		themeChoice,
		accentHue,
		accentIntensity,
		reduceTransparency,
		uiFontSize,
		codeFontSize,
		uiFontFamily,
		codeFontFamily,
		fontSmoothing,
		hideEmail,
		toolCallDensity,
		DEFAULT_CODE_FONT_STACK,
		normalizeFontStack
	} from '$lib/stores/settings.js';
	import {
		checkForPluginUpdate,
		getPluginUpdateStatus,
		type PluginUpdateStatus,
		getProviderSettings,
		addProvider,
		removeProvider,
		setProviderApiKey,
		setProviderBaseUrl,
		refreshProviderModels,
		createCustomProvider,
		deleteCustomProvider,
		updateCustomProvider,
		addCustomProviderModel,
		removeCustomProviderModel,
		importCustomProviderModels,
		setCustomProviderModelDiscovery,
		setCustomProviderRequiresApiKey,
		getAgentExecutionSettings,
		setAgentExecutionSetting,
		type AgentExecutionSettings,
		type ProviderSettings,
		type ProviderConfig,
		getAllModels,
		getEnabledModels,
		setModelEnabled,
		setEnabledModels,
		type ModelInfo,
		getCrashHistory,
		reportCrash,
		type CrashRecord,
		openPluginSettings,
		getIssueReportSettings,
		setIssueReportDisabled,
		type IssueReportSettings
	} from '$lib/bridge.js';

	let tabs = $derived([
		{ id: 'general', label: $t('tab_general'), icon: Settings02Icon },
		{ id: 'appearance', label: $t('tab_appearance'), icon: PaintBoardIcon },
		{ id: 'setup', label: $t('tab_setup'), icon: CheckmarkCircle02Icon },
		{ id: 'indexing', label: $t('tab_indexing'), icon: Database02Icon },
		{ id: 'extensions', label: $t('tab_extensions'), icon: Add01Icon },
		{ id: 'skills', label: $t('tab_skills'), icon: Book02Icon },
		{ id: 'mcp', label: $t('tab_mcp'), icon: Link01Icon },
		{ id: 'agents', label: $t('tab_agents'), icon: UserIcon },
		{ id: 'usage', label: $t('tab_usage'), icon: Analytics01Icon },
		{ id: 'generation', label: $t('tab_generation'), icon: Wrench01Icon },
		{ id: 'notifications', label: $t('tab_notifications'), icon: Notification03Icon },
		{ id: 'crashes', label: $t('tab_crashes'), icon: Alert02Icon },
		{ id: 'about', label: $t('tab_about'), icon: InformationCircleIcon }
	]);

	// ── Crash History State ─────────────────────────────────────────
	let crashRecords = $state<CrashRecord[]>([]);
	let isLoadingCrashes = $state(false);
	let reportingCrashId = $state('');

	async function loadCrashHistory() {
		isLoadingCrashes = true;
		try {
			crashRecords = await getCrashHistory();
		} catch {
			crashRecords = [];
		}
		isLoadingCrashes = false;
	}

	async function handleReportCrash(crashId: string) {
		reportingCrashId = crashId;
		try {
			const result = await reportCrash(crashId);
			if (result.success) {
				await loadCrashHistory();
			}
		} catch {
			/* ignore */
		}
		reportingCrashId = '';
	}

	let isCheckingForUpdates = $state(false);
	let updateCheckMessage = $state('');
	let updateStatus = $state<PluginUpdateStatus | null>(null);

	// ── Issue Report Settings ───────────────────────────────────────
	let issueReportSettings = $state<IssueReportSettings>({ disabled: false });
	let isSavingIssueReport = $state(false);

	async function loadIssueReportSettings() {
		try {
			issueReportSettings = await getIssueReportSettings();
		} catch (e) {
			console.warn('Failed to load issue report settings:', e);
		}
	}

	async function handleToggleIssueReports() {
		const next = !issueReportSettings.disabled;
		const prev = issueReportSettings.disabled;
		issueReportSettings = { disabled: next };
		isSavingIssueReport = true;
		try {
			await setIssueReportDisabled(next);
		} catch (e) {
			console.warn('Failed to save issue report setting:', e);
			issueReportSettings = { disabled: prev };
		} finally {
			isSavingIssueReport = false;
		}
	}

	// ── Agent Execution Settings ────────────────────────────────────
	let agentExecutionSettings = $state<AgentExecutionSettings>({
		systemPromptAppend: '',
		toolTimeout: 60,
		agentResponseTimeout: 0
	});
	let isLoadingAgentExecution = $state(false);
	type AgentExecutionSettingKey = 'systemPromptAppend' | 'toolTimeout' | 'agentResponseTimeout';
	// Per-key timers — a shared timer would let editing field B cancel field A's pending save.
	let agentExecutionSaveTimers: Partial<
		Record<AgentExecutionSettingKey, ReturnType<typeof setTimeout>>
	> = {};

	// ── Provider Settings ────────────────────────────────────────────
	let providerSettings = $state<ProviderSettings>({ priority: [], providers: [] });
	let isLoadingProviders = $state(false);
	let selectedProviderId = $state('openrouter');
	let providerApiKeyInput = $state('');
	let providerActionError = $state('');
	let providerSaveTimeout: ReturnType<typeof setTimeout> | undefined;

	let selectedProvider = $derived(
		providerSettings.providers.find((p) => p.id === selectedProviderId)
	);
	// Providers in priority order (configured ones)
	let priorityProviders = $derived(
		providerSettings.priority
			.map((id) => providerSettings.providers.find((p) => p.id === id))
			.filter((p): p is ProviderConfig => !!p)
	);
	// Providers not yet in priority list
	let availableToAdd = $derived(providerSettings.providers.filter((p) => !p.inPriorityList));

	async function onNeoStackCloudChanged() {
		await refreshCloudAccount();
		await loadProviderSettings();
	}

	async function loadProviderSettings() {
		if (isLoadingProviders) return;
		isLoadingProviders = true;
		try {
			providerActionError = '';
			providerSettings = await getProviderSettings();
			if (providerSettings.priority.length > 0) {
				selectedProviderId = providerSettings.priority[0];
			}
			providerApiKeyInput = '';
		} catch (e) {
			console.warn('Failed to load provider settings:', e);
			providerActionError =
				'Could not load chat providers. Reopen Settings or restart the editor if this keeps happening.';
		} finally {
			isLoadingProviders = false;
		}
	}

	async function handleAddProvider(providerId: string) {
		try {
			providerActionError = '';
			await addProvider(providerId);
			providerSettings = await getProviderSettings();
			selectedProviderId = providerId;
		} catch (e) {
			console.warn('Failed to add provider:', e);
			providerActionError = 'Could not add this chat provider.';
		}
	}

	async function handleRemoveProvider(providerId: string) {
		try {
			providerActionError = '';
			// For custom providers, fully delete (removes config + models + priority)
			const prov = providerSettings.providers.find((p) => p.id === providerId);
			if (prov?.isUserDefined) {
				await deleteCustomProvider(providerId);
			} else {
				await removeProvider(providerId);
			}
			providerSettings = await getProviderSettings();
			if (selectedProviderId === providerId && providerSettings.priority.length > 0) {
				selectedProviderId = providerSettings.priority[0];
			}
		} catch (e) {
			console.warn('Failed to remove provider:', e);
			providerActionError = 'Could not remove this chat provider.';
		}
	}

	async function handleProviderApiKeySave(providerId: string, key: string) {
		try {
			providerActionError = '';
			await setProviderApiKey(providerId, key);
			if (providerId === 'neostack') {
				await refreshCloudAccount();
			}
			providerSettings = await getProviderSettings();
			providerApiKeyInput = '';
			// Refresh models since new key may enable a provider
			await refreshProviderModels();
		} catch (e) {
			console.warn('Failed to save provider API key:', e);
			providerActionError = 'Could not save the API key. Check the key and try again.';
		}
	}

	function debouncedProviderBaseUrl(providerId: string, url: string) {
		clearTimeout(providerSaveTimeout);
		providerSaveTimeout = setTimeout(async () => {
			try {
				providerActionError = '';
				await setProviderBaseUrl(providerId, url);
			} catch (e) {
				console.warn('Failed to save provider base URL:', e);
				providerActionError = 'Could not save the provider base URL.';
			}
		}, 600);
	}

	// ── Custom Provider State ────────────────────────────────────
	let showNewCustomProviderForm = $state(false);
	let newCustomProviderName = $state('');
	let newCustomProviderUrl = $state('');
	let showAddModelForm = $state(false);
	let newModelId = $state('');
	let newModelName = $state('');
	let newModelDesc = $state('');
	let showImportModal = $state(false);
	let importJsonText = $state('');
	let importResult = $state<{ imported: number; errors: string[] } | null>(null);
	let isImporting = $state(false);
	let showDeleteConfirm = $state('');
	let customProviderUpdateTimeout: ReturnType<typeof setTimeout> | undefined;

	// Only show built-in providers in the "available to add" buttons (not custom ones)
	let builtinAvailableToAdd = $derived(availableToAdd.filter((p) => !p.isUserDefined));

	async function handleCreateCustomProvider() {
		if (!newCustomProviderName.trim()) return;
		try {
			providerActionError = '';
			const result = await createCustomProvider(
				newCustomProviderName.trim(),
				newCustomProviderUrl.trim()
			);
			providerSettings = await getProviderSettings();
			selectedProviderId = result.providerId;
			newCustomProviderName = '';
			newCustomProviderUrl = '';
			showNewCustomProviderForm = false;
		} catch (e) {
			console.warn('Failed to create custom provider:', e);
			providerActionError = 'Could not create the custom provider.';
		}
	}

	async function handleDeleteCustomProvider(providerId: string) {
		try {
			providerActionError = '';
			await deleteCustomProvider(providerId);
			providerSettings = await getProviderSettings();
			showDeleteConfirm = '';
			if (selectedProviderId === providerId && providerSettings.priority.length > 0) {
				selectedProviderId = providerSettings.priority[0];
			}
		} catch (e) {
			console.warn('Failed to delete custom provider:', e);
			providerActionError = 'Could not delete the custom provider.';
		}
	}

	function debouncedCustomProviderUpdate(providerId: string, name: string, baseUrl: string) {
		clearTimeout(customProviderUpdateTimeout);
		customProviderUpdateTimeout = setTimeout(async () => {
			try {
				providerActionError = '';
				await updateCustomProvider(providerId, name, baseUrl);
				// Don't reload full settings for debounced updates — just sync
			} catch (e) {
				console.warn('Failed to update custom provider:', e);
				providerActionError = 'Could not save the custom provider settings.';
			}
		}, 600);
	}

	async function handleAddModel(providerId: string) {
		if (!newModelId.trim()) return;
		try {
			providerActionError = '';
			await addCustomProviderModel(
				providerId,
				newModelId.trim(),
				newModelName.trim(),
				newModelDesc.trim()
			);
			providerSettings = await getProviderSettings();
			newModelId = '';
			newModelName = '';
			newModelDesc = '';
			showAddModelForm = false;
		} catch (e) {
			console.warn('Failed to add model:', e);
			providerActionError = 'Could not add that model.';
		}
	}

	async function handleRemoveModel(providerId: string, modelId: string) {
		try {
			providerActionError = '';
			await removeCustomProviderModel(providerId, modelId);
			providerSettings = await getProviderSettings();
		} catch (e) {
			console.warn('Failed to remove model:', e);
			providerActionError = 'Could not remove that model.';
		}
	}

	async function handleImportModels(providerId: string) {
		if (!importJsonText.trim()) return;
		isImporting = true;
		importResult = null;
		try {
			providerActionError = '';
			importResult = await importCustomProviderModels(providerId, importJsonText.trim());
			if (importResult.imported > 0) {
				providerSettings = await getProviderSettings();
			}
		} catch (e) {
			importResult = { imported: 0, errors: ['Import failed: ' + String(e)] };
			providerActionError = 'Could not import models from JSON.';
		} finally {
			isImporting = false;
		}
	}

	async function handleToggleModelDiscovery(providerId: string, enabled: boolean) {
		try {
			providerActionError = '';
			await setCustomProviderModelDiscovery(providerId, enabled);
			providerSettings = await getProviderSettings();
		} catch (e) {
			console.warn('Failed to toggle model discovery:', e);
			providerActionError = 'Could not save model discovery setting.';
		}
	}

	async function handleToggleRequiresApiKey(providerId: string, requiresApiKey: boolean) {
		try {
			providerActionError = '';
			await setCustomProviderRequiresApiKey(providerId, requiresApiKey);
			providerSettings = await getProviderSettings();
			providerApiKeyInput = '';
		} catch (e) {
			console.warn('Failed to toggle API key requirement:', e);
			providerActionError = 'Could not save the API key requirement.';
		}
	}

	// ── Model Enable/Disable ────────────────────────────────────
	let settingsModels = $state<ModelInfo[]>([]);
	const enabledModelIds = new SvelteSet<string>();
	let hasCustomModelSelection = $state(false);
	let isLoadingModels = $state(false);
	let modelSearchQuery = $state('');
	let debouncedModelSearchQuery = $state('');
	let settingsModelListEl = $state<HTMLDivElement | undefined>();
	let settingsModelScrollTop = $state(0);
	let settingsModelViewportHeight = $state(400);
	const SETTINGS_MODEL_ROW_HEIGHT = 56;
	const SETTINGS_MODEL_OVERSCAN = 6;

	$effect(() => {
		const query = modelSearchQuery.trim().toLowerCase();
		const timer = setTimeout(() => {
			debouncedModelSearchQuery = query;
			settingsModelScrollTop = 0;
			if (settingsModelListEl) settingsModelListEl.scrollTop = 0;
		}, 120);
		return () => clearTimeout(timer);
	});

	let filteredSettingsModels = $derived(
		debouncedModelSearchQuery
			? settingsModels.filter(
					(m) =>
						m.name.toLowerCase().includes(debouncedModelSearchQuery) ||
						m.id.toLowerCase().includes(debouncedModelSearchQuery)
				)
			: settingsModels
	);
	let settingsModelWindowStart = $derived(
		Math.max(
			0,
			Math.floor(settingsModelScrollTop / SETTINGS_MODEL_ROW_HEIGHT) - SETTINGS_MODEL_OVERSCAN
		)
	);
	let settingsModelWindowEnd = $derived(
		Math.min(
			filteredSettingsModels.length,
			Math.ceil(
				(settingsModelScrollTop + settingsModelViewportHeight) / SETTINGS_MODEL_ROW_HEIGHT
			) + SETTINGS_MODEL_OVERSCAN
		)
	);
	let visibleSettingsModels = $derived(
		filteredSettingsModels.slice(settingsModelWindowStart, settingsModelWindowEnd)
	);

	function handleSettingsModelScroll(): void {
		if (settingsModelListEl) settingsModelScrollTop = settingsModelListEl.scrollTop;
	}

	function replaceEnabledModelIds(ids: Iterable<string>): void {
		enabledModelIds.clear();
		for (const id of ids) enabledModelIds.add(id);
	}
	let enabledModelCount = $derived(
		hasCustomModelSelection ? enabledModelIds.size : settingsModels.length
	);

	async function loadModelsForSettings() {
		if (isLoadingModels) return;
		isLoadingModels = true;
		try {
			const [allModelsState, enabledState] = await Promise.all([
				getAllModels('Local & BYOK Chat'),
				getEnabledModels()
			]);
			settingsModels = allModelsState.models.filter((m) => m.id);
			settingsModels.sort((a, b) => a.name.localeCompare(b.name));
			hasCustomModelSelection = enabledState.hasCustomSelection;
			replaceEnabledModelIds(enabledState.enabledModels);
		} catch (e) {
			console.warn('Failed to load models for settings:', e);
		} finally {
			isLoadingModels = false;
		}
	}

	async function handleToggleModel(modelId: string, enabled: boolean) {
		const prevIds = [...enabledModelIds];
		const prevHasCustom = hasCustomModelSelection;
		if (!hasCustomModelSelection) {
			// First toggle: initialize enabled set with all models, then apply the change
			const allIds = new SvelteSet(settingsModels.map((m) => m.id));
			if (!enabled) allIds.delete(modelId);
			replaceEnabledModelIds(allIds);
			hasCustomModelSelection = true;
			try {
				await setEnabledModels([...allIds]);
			} catch (e) {
				console.warn('Failed to initialize model selection:', e);
				replaceEnabledModelIds(prevIds);
				hasCustomModelSelection = prevHasCustom;
			}
			return;
		}
		const next = new SvelteSet(enabledModelIds);
		if (enabled) {
			next.add(modelId);
		} else {
			next.delete(modelId);
		}
		replaceEnabledModelIds(next);
		try {
			await setModelEnabled(modelId, enabled);
		} catch (e) {
			console.warn('Failed to toggle model:', e);
			replaceEnabledModelIds(prevIds);
		}
	}

	function isModelEnabled(modelId: string): boolean {
		if (!hasCustomModelSelection) return true;
		return enabledModelIds.has(modelId);
	}

	async function handleEnableAllModels() {
		const prevIds = [...enabledModelIds];
		const prevHasCustom = hasCustomModelSelection;
		const allIds = new SvelteSet(settingsModels.map((m) => m.id));
		replaceEnabledModelIds(allIds);
		hasCustomModelSelection = true;
		try {
			await setEnabledModels([...allIds]);
		} catch (e) {
			console.warn('Failed to enable all models:', e);
			replaceEnabledModelIds(prevIds);
			hasCustomModelSelection = prevHasCustom;
		}
	}

	async function handleDisableAllModels() {
		const prevIds = [...enabledModelIds];
		const prevHasCustom = hasCustomModelSelection;
		replaceEnabledModelIds([]);
		hasCustomModelSelection = true;
		try {
			await setEnabledModels([]);
		} catch (e) {
			console.warn('Failed to disable all models:', e);
			replaceEnabledModelIds(prevIds);
			hasCustomModelSelection = prevHasCustom;
		}
	}

	async function handleShowAllModels() {
		const prevIds = [...enabledModelIds];
		const prevHasCustom = hasCustomModelSelection;
		replaceEnabledModelIds([]);
		hasCustomModelSelection = false;
		try {
			await setEnabledModels([]);
		} catch (e) {
			console.warn('Failed to reset model selection:', e);
			replaceEnabledModelIds(prevIds);
			hasCustomModelSelection = prevHasCustom;
		}
	}

	// ── Indexing Panel ref ───────────────────────────────────────────
	let indexPanel: ProjectIndexPanel | undefined = $state();
	let extensionsPanel: ExtensionsPanel | undefined = $state();
	let notifPanel: NotificationsPanel | undefined = $state();

	$effect(() => {
		const tab = $settingsTab;
		queueMicrotask(() => {
			if (tab === 'extensions') {
				void extensionsPanel?.load();
			} else if (tab === 'agents') {
				void loadProviderSettings();
				void loadModelsForSettings();
				void loadAgentExecutionSettings();
			} else if (tab === 'notifications') {
				void notifPanel?.load();
			} else if (tab === 'indexing') {
				void indexPanel?.load();
			} else if (tab === 'crashes') {
				void loadCrashHistory();
			} else if (tab === 'general') {
				void loadIssueReportSettings();
			} else if (tab === 'about') {
				// Show the installed version immediately; the check is manual.
				void loadUpdateStatus();
			}
		});
	});

	async function loadAgentExecutionSettings() {
		if (isLoadingAgentExecution) return;
		isLoadingAgentExecution = true;
		try {
			agentExecutionSettings = await getAgentExecutionSettings();
		} catch (e) {
			console.warn('Failed to load agent execution settings:', e);
		} finally {
			isLoadingAgentExecution = false;
		}
	}

	function scheduleAgentExecutionSave(key: AgentExecutionSettingKey, value: string) {
		if (agentExecutionSaveTimers[key]) clearTimeout(agentExecutionSaveTimers[key]);
		agentExecutionSaveTimers[key] = setTimeout(async () => {
			try {
				await setAgentExecutionSetting(key, value);
			} catch (e) {
				console.warn(`Failed to save agent execution setting '${key}':`, e);
			}
		}, 400);
	}

	async function loadUpdateStatus() {
		try {
			updateStatus = await getPluginUpdateStatus();
		} catch (e) {
			console.warn('Failed to read update status:', e);
		}
	}

	/**
	 * Trigger the check, then wait for the answer.
	 *
	 * The UE side is fire-and-forget and pushes nothing back, so we poll. It
	 * used to just say "check started" and stop — and because the editor only
	 * raises a toast when an update EXISTS, an up-to-date user saw nothing at
	 * all and the button looked broken.
	 */
	async function handleCheckForUpdates() {
		if (isCheckingForUpdates) return;
		isCheckingForUpdates = true;
		updateCheckMessage = '';
		try {
			await checkForPluginUpdate();
			// ~15s ceiling: the check is one request, and leaving the spinner
			// up forever on a wedged network is worse than reporting timeout.
			for (let attempt = 0; attempt < 30; attempt++) {
				await new Promise((resolve) => setTimeout(resolve, 500));
				await loadUpdateStatus();
				if (updateStatus && updateStatus.state !== 'checking') break;
			}
			if (updateStatus?.state === 'checking') {
				updateCheckMessage = $t('update_check_failed');
			}
		} catch (e) {
			console.warn('Failed to trigger update check:', e);
			updateCheckMessage = $t('update_check_failed');
		} finally {
			isCheckingForUpdates = false;
		}
	}

	function handleLocaleChange(nextLocale: Locale) {
		setLocale(nextLocale);
	}
</script>

<div class="settings-shell flex h-full w-full">
	<div
		class="settings-mobile-header hidden shrink-0 items-center gap-2 border-b border-border bg-sidebar px-3 py-2"
	>
		<button
			class="focus-ring flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground"
			onclick={closeSettings}
			aria-label={$t('back_to_chat')}
		>
			<Icon icon={ArrowLeft02Icon} size={16} strokeWidth={1.5} />
		</button>
		<div class="min-w-0 flex-1 [&_[role=combobox]>button]:h-10">
			<CustomSelect
				id="settings-mobile-tab"
				ariaLabel={$t('settings')}
				options={tabs.map((tab) => ({ value: tab.id, label: tab.label }))}
				value={$settingsTab}
				onchange={(value) => settingsTab.set(value)}
			/>
		</div>
	</div>
	<!-- Left tab nav -->
	<nav class="settings-sidebar flex w-[200px] shrink-0 flex-col border-r border-border bg-sidebar">
		<div class="flex items-center gap-2 px-4 pb-3 pt-4">
			<button
				class="focus-ring flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground"
				onclick={closeSettings}
				title={$t('back_to_chat')}
				aria-label={$t('back_to_chat')}
			>
				<Icon icon={ArrowLeft02Icon} size={16} strokeWidth={1.5} />
			</button>
			<span class="text-[14px] font-medium text-foreground">{$t('settings')}</span>
		</div>

		<div class="flex flex-col gap-0.5 px-2">
			{#each tabs as tab (tab.id)}
				<button
					class="flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] transition-colors {$settingsTab ===
					tab.id
						? 'bg-sidebar-accent text-foreground'
						: 'hover:bg-sidebar-accent/60 text-muted-foreground hover:text-foreground'}"
					onclick={() => settingsTab.set(tab.id)}
				>
					<Icon icon={tab.icon} size={15} strokeWidth={1.5} />
					{tab.label}
				</button>
			{/each}
		</div>
	</nav>

	<!-- Right content area -->
	<div class="settings-content min-w-0 flex-1 overflow-y-auto p-8">
		<div class="mx-auto max-w-3xl">
			{#if $settingsTab === 'general'}
				<div class="mb-6">
					<h2 class="mb-1 text-[18px] font-medium text-foreground">{$t('general_heading')}</h2>
				</div>

				<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
					<h3 class="mb-1 text-[14px] font-medium text-foreground">{$t('language_heading')}</h3>
					<p class="text-muted-foreground/60 mb-3 text-[12px]">{$t('language_desc')}</p>
					<div class="flex flex-wrap gap-2">
						{#each releasedLocales as currentLocale (currentLocale)}
							<button
								class="rounded-md border px-3 py-1.5 text-[13px] transition-colors {$locale ===
								currentLocale
									? 'bg-[var(--ue-accent)]/10 border-[var(--ue-accent)] text-foreground'
									: 'border-border/60 text-muted-foreground hover:border-border hover:text-foreground'}"
								onclick={() => handleLocaleChange(currentLocale)}
							>
								{localeNames[currentLocale]}
							</button>
						{/each}
					</div>
				</div>

				<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
					<div class="flex items-center justify-between">
						<div>
							<h3 class="text-[14px] font-medium text-foreground">Enter to send</h3>
							<p class="text-muted-foreground/60 mt-0.5 text-[12px]">
								{$enterToSend
									? 'Enter sends message, Shift+Enter for new line'
									: 'Enter for new line, Cmd/Ctrl+Enter sends message'}
							</p>
						</div>
						<button
							role="switch"
							aria-checked={$enterToSend}
							aria-label="Enter to send"
							class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors {$enterToSend
								? 'bg-[var(--ue-accent)]'
								: 'bg-muted-foreground/30'}"
							onclick={() => enterToSend.set(!$enterToSend)}
						>
							<span
								class="pointer-events-none inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform {$enterToSend
									? 'translate-x-[18px]'
									: 'translate-x-[3px]'}"
							></span>
						</button>
					</div>
				</div>

				<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
					<div class="mb-3">
						<h3 class="text-[14px] font-medium text-foreground">Top Navigation Tabs</h3>
						<p class="text-muted-foreground/60 mt-0.5 text-[12px]">
							Show or hide the top-bar tabs. Chat is always visible.
						</p>
					</div>

					<div class="flex items-center justify-between py-2">
						<div>
							<p class="text-[13px] text-foreground">Studio</p>
							<p class="text-muted-foreground/50 mt-0.5 text-[11px]">
								AI image and 3D generation workspace.
							</p>
						</div>
						<button
							role="switch"
							aria-label="Toggle Studio tab"
							aria-checked={$studioEnabled}
							class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors {$studioEnabled
								? 'bg-[var(--ue-accent)]'
								: 'bg-muted-foreground/30'}"
							onclick={() => studioEnabled.set(!$studioEnabled)}
						>
							<span
								class="pointer-events-none inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform {$studioEnabled
									? 'translate-x-[18px]'
									: 'translate-x-[3px]'}"
							></span>
						</button>
					</div>

					<div class="flex items-center justify-between py-2">
						<div>
							<p class="text-[13px] text-foreground">Terminal</p>
							<p class="text-muted-foreground/50 mt-0.5 text-[11px]">
								Integrated terminal for running CLI tools. Disabling stops the PTY.
							</p>
						</div>
						<button
							role="switch"
							aria-label="Toggle Terminal tab"
							aria-checked={$terminalEnabled}
							class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors {$terminalEnabled
								? 'bg-[var(--ue-accent)]'
								: 'bg-muted-foreground/30'}"
							onclick={() => terminalEnabled.set(!$terminalEnabled)}
						>
							<span
								class="pointer-events-none inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform {$terminalEnabled
									? 'translate-x-[18px]'
									: 'translate-x-[3px]'}"
							></span>
						</button>
					</div>
				</div>

				<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
					<div class="flex items-center justify-between">
						<div class="pr-4">
							<h3 class="text-[14px] font-medium text-foreground">Agent Issue Reports</h3>
							<p class="text-muted-foreground/60 mt-0.5 text-[12px]">
								Lets agents flag missing bindings, wrong tool results, or other shortcomings to
								neostack.dev so we can improve them. Reports include only what the agent describes —
								no asset paths or script traces are auto-attached.
							</p>
							{#if issueReportSettings.disabled}
								<p class="text-muted-foreground/50 mt-1.5 text-[11px]">
									Disabled — <code class="bg-muted/50 rounded px-1">report_issue()</code> short-circuits
									before any HTTP call.
								</p>
							{/if}
						</div>
						<button
							role="switch"
							aria-label="Allow agent issue reports"
							aria-checked={!issueReportSettings.disabled}
							disabled={isSavingIssueReport}
							class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors disabled:opacity-50 {!issueReportSettings.disabled
								? 'bg-[var(--ue-accent)]'
								: 'bg-muted-foreground/30'}"
							onclick={handleToggleIssueReports}
						>
							<span
								class="pointer-events-none inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform {!issueReportSettings.disabled
									? 'translate-x-[18px]'
									: 'translate-x-[3px]'}"
							></span>
						</button>
					</div>
				</div>
			{:else if $settingsTab === 'appearance'}
				{@const accentColor = `hsl(${$accentHue} ${$accentIntensity * 0.8}% 55%)`}
				{@const accentMuted = `hsl(${$accentHue} ${$accentIntensity * 0.8}% 42%)`}
				{@const hueGradient =
					'linear-gradient(to right, hsl(0 80% 55%), hsl(60 80% 55%), hsl(120 80% 55%), hsl(180 80% 55%), hsl(240 80% 55%), hsl(300 80% 55%), hsl(360 80% 55%))'}

				<div class="mb-8">
					<h2 class="mb-1 text-[18px] font-medium text-foreground">{$t('appearance_heading')}</h2>
					<p class="text-muted-foreground/60 text-[13px]">{$t('appearance_desc')}</p>
				</div>

				<!-- THEME — visual tiles -->
				<section class="mb-8">
					<div
						class="text-muted-foreground/55 mb-3 text-[11px] font-medium uppercase tracking-wider"
					>
						{$t('appearance_theme')}
					</div>
					<div class="grid grid-cols-3 gap-3">
						{#each [{ id: 'dark', label: $t('appearance_theme_dark'), bg: '#1e1e1e', surface: '#2d2d2d', text: '#c8c8c8', dim: '#444' }, { id: 'light', label: $t('appearance_theme_light'), bg: '#f7f8fa', surface: '#ffffff', text: '#1a1c20', dim: '#d4d8df' }, { id: 'high-contrast', label: $t('appearance_theme_high_contrast'), bg: '#000000', surface: '#0a0a0a', text: '#ffffff', dim: '#ffffff' }] as opt (opt.id)}
							{@const selected = $themeChoice === opt.id}
							<button
								class="group relative overflow-hidden rounded-lg border-2 text-left transition-all {selected
									? 'shadow-[0_0_0_3px_var(--ue-accent)]/15 border-[var(--ue-accent)]'
									: 'border-border/60 hover:border-border'}"
								onclick={() => themeChoice.set(opt.id as 'dark' | 'light' | 'high-contrast')}
								aria-pressed={selected}
							>
								<!-- Mini theme preview -->
								<div class="flex h-[68px] w-full" style="background: {opt.bg};">
									<div class="flex w-1/3 flex-col gap-1.5 p-2" style="background: {opt.surface};">
										<div
											class="h-1 w-3/4 rounded-full"
											style="background: {opt.dim}; opacity: 0.7"
										></div>
										<div
											class="h-1 w-1/2 rounded-full"
											style="background: {opt.dim}; opacity: 0.5"
										></div>
										<div
											class="h-1 w-2/3 rounded-full"
											style="background: {opt.dim}; opacity: 0.5"
										></div>
										<div
											class="mt-auto h-1.5 w-1/2 rounded-full"
											style="background: {accentColor};"
										></div>
									</div>
									<div class="flex flex-1 flex-col gap-1.5 p-2">
										<div
											class="h-1.5 w-2/5 rounded-full"
											style="background: {opt.text}; opacity: 0.8"
										></div>
										<div
											class="h-1 w-full rounded-full"
											style="background: {opt.text}; opacity: 0.3"
										></div>
										<div
											class="h-1 w-3/4 rounded-full"
											style="background: {opt.text}; opacity: 0.3"
										></div>
									</div>
								</div>
								<div
									class="border-border/40 flex items-center justify-between border-t bg-card px-3 py-2"
								>
									<span
										class="text-[12.5px] font-medium {selected
											? 'text-foreground'
											: 'text-muted-foreground'}">{opt.label}</span
									>
									{#if selected}
										<span
											class="flex h-4 w-4 items-center justify-center rounded-full"
											style="background: {accentColor}"
										>
											<svg viewBox="0 0 16 16" class="h-3 w-3 text-white"
												><path fill="currentColor" d="M6.5 10.6 4 8.1l-1 1 3.5 3.4 7-7-1-1z" /></svg
											>
										</span>
									{/if}
								</div>
							</button>
						{/each}
					</div>
				</section>

				<!-- ACCENT — gradient slider + presets + intensity -->
				<section class="mb-8">
					<div class="mb-3 flex items-center justify-between">
						<div class="text-muted-foreground/55 text-[11px] font-medium uppercase tracking-wider">
							{$t('appearance_colors')}
						</div>
						<button
							class="text-muted-foreground/55 text-[11px] underline-offset-2 hover:text-foreground hover:underline"
							onclick={() => {
								accentHue.set(209);
								accentIntensity.set(100);
							}}>{$t('appearance_reset_colors')}</button
						>
					</div>

					<div class="border-border/60 rounded-lg border bg-card">
						<!-- Accent preview row -->
						<div class="flex items-center gap-3 px-4 py-3">
							<div
								class="ring-border/40 flex h-10 w-10 shrink-0 items-center justify-center rounded-full ring-2"
								style="background: {accentColor}"
							>
								<span class="block h-5 w-5 rounded-full" style="background: {accentMuted}"></span>
							</div>
							<div class="min-w-0 flex-1">
								<p class="text-[12.5px] text-foreground">{$t('appearance_hue')}</p>
								<p class="text-muted-foreground/55 mt-0.5 font-mono text-[10.5px]">
									H {$accentHue}° · S {$accentIntensity}%
								</p>
							</div>
							<div class="flex flex-wrap items-center gap-1.5">
								{#each [{ hue: 209, label: 'Blue' }, { hue: 265, label: 'Violet' }, { hue: 145, label: 'Green' }, { hue: 25, label: 'Orange' }, { hue: 350, label: 'Pink' }] as p (p.hue)}
									<button
										class="h-5 w-5 rounded-full ring-2 transition-all hover:scale-110 {$accentHue ===
										p.hue
											? 'ring-foreground'
											: 'ring-transparent'}"
										style="background: hsl({p.hue} 80% 55%)"
										onclick={() => accentHue.set(p.hue)}
										title={p.label}
										aria-label={p.label}
									></button>
								{/each}
							</div>
						</div>

						<div class="border-border/40 border-t px-4 py-3">
							<label for="appearance-hue" class="sr-only">Hue</label>
							<input
								id="appearance-hue"
								type="range"
								min="0"
								max="360"
								step="1"
								bind:value={$accentHue}
								class="hue-slider w-full"
								style="--hue-gradient: {hueGradient}"
							/>
						</div>

						<div class="border-border/40 border-t px-4 py-3">
							<div class="mb-1.5 flex items-center justify-between gap-3">
								<label for="appearance-intensity" class="text-[12.5px] text-foreground"
									>{$t('appearance_intensity')}</label
								>
								<span class="text-muted-foreground/55 text-[11px] tabular-nums"
									>{$accentIntensity}%</span
								>
							</div>
							<input
								id="appearance-intensity"
								type="range"
								min="0"
								max="100"
								step="1"
								bind:value={$accentIntensity}
								class="w-full accent-[var(--ue-accent)]"
							/>
						</div>

						<div
							class="border-border/40 flex items-center justify-between gap-4 border-t px-4 py-3"
						>
							<div class="min-w-0">
								<p class="text-[12.5px] text-foreground">{$t('appearance_reduce_transparency')}</p>
								<p class="text-muted-foreground/55 mt-0.5 text-[11.5px]">
									{$t('appearance_reduce_transparency_desc')}
								</p>
							</div>
							<button
								role="switch"
								aria-checked={$reduceTransparency}
								aria-label={$t('appearance_reduce_transparency')}
								class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors {$reduceTransparency
									? 'bg-[var(--ue-accent)]'
									: 'bg-muted-foreground/30'}"
								onclick={() => reduceTransparency.set(!$reduceTransparency)}
							>
								<span
									class="pointer-events-none inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform {$reduceTransparency
										? 'translate-x-[18px]'
										: 'translate-x-[3px]'}"
								></span>
							</button>
						</div>
					</div>
				</section>

				<!-- CHAT — density segmented control -->
				<section class="mb-8">
					<div
						class="text-muted-foreground/55 mb-3 text-[11px] font-medium uppercase tracking-wider"
					>
						{$t('appearance_chat')}
					</div>
					<div class="border-border/60 rounded-lg border bg-card">
						<div class="flex items-center justify-between gap-4 px-4 py-3">
							<div class="min-w-0">
								<p class="text-[12.5px] text-foreground">{$t('appearance_density')}</p>
								<p class="text-muted-foreground/55 mt-0.5 text-[11.5px]">
									{$t('appearance_density_desc')}
								</p>
							</div>
							<div class="bg-muted/40 relative flex shrink-0 rounded-md p-0.5">
								{#each [{ id: 'compact', label: $t('appearance_density_compact') }, { id: 'detailed', label: $t('appearance_density_detailed') }] as opt (opt.id)}
									<button
										class="relative z-10 rounded px-3 py-1 text-[11.5px] font-medium transition-colors {$toolCallDensity ===
										opt.id
											? 'text-foreground'
											: 'text-muted-foreground hover:text-foreground'}"
										onclick={() => toolCallDensity.set(opt.id as 'compact' | 'detailed')}
										aria-pressed={$toolCallDensity === opt.id}
									>
										{#if $toolCallDensity === opt.id}
											<span
												class="ring-border/60 absolute inset-0 -z-10 rounded bg-background shadow-sm ring-1"
											></span>
										{/if}
										{opt.label}
									</button>
								{/each}
							</div>
						</div>
					</div>
				</section>

				<!-- TYPOGRAPHY -->
				<section class="mb-8">
					<div
						class="text-muted-foreground/55 mb-3 text-[11px] font-medium uppercase tracking-wider"
					>
						{$t('appearance_typography')}
					</div>
					<div class="border-border/60 rounded-lg border bg-card">
						<!-- Sizes row -->
						<div class="grid grid-cols-2 gap-6 px-4 py-3">
							<div class="flex items-center justify-between gap-3">
								<label for="appearance-ui-size" class="text-[12.5px] text-foreground"
									>{$t('appearance_ui_font_size')}</label
								>
								<div class="border-border/60 flex items-center rounded-md border">
									<button
										class="flex h-7 w-7 items-center justify-center text-muted-foreground hover:bg-accent hover:text-foreground"
										aria-label="Decrease UI font size"
										onclick={() => uiFontSize.set(Math.max(11, $uiFontSize - 1))}>−</button
									>
									<input
										id="appearance-ui-size"
										type="number"
										min="11"
										max="18"
										bind:value={$uiFontSize}
										class="border-border/60 w-9 border-x bg-transparent py-1 text-center text-[12.5px] tabular-nums text-foreground [-moz-appearance:textfield] focus:outline-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
									/>
									<button
										class="flex h-7 w-7 items-center justify-center text-muted-foreground hover:bg-accent hover:text-foreground"
										aria-label="Increase UI font size"
										onclick={() => uiFontSize.set(Math.min(18, $uiFontSize + 1))}>+</button
									>
								</div>
							</div>
							<div class="flex items-center justify-between gap-3">
								<label for="appearance-code-size" class="text-[12.5px] text-foreground"
									>{$t('appearance_code_font_size')}</label
								>
								<div class="border-border/60 flex items-center rounded-md border">
									<button
										class="flex h-7 w-7 items-center justify-center text-muted-foreground hover:bg-accent hover:text-foreground"
										aria-label="Decrease code font size"
										onclick={() => codeFontSize.set(Math.max(10, $codeFontSize - 1))}>−</button
									>
									<input
										id="appearance-code-size"
										type="number"
										min="10"
										max="18"
										bind:value={$codeFontSize}
										class="border-border/60 w-9 border-x bg-transparent py-1 text-center text-[12.5px] tabular-nums text-foreground [-moz-appearance:textfield] focus:outline-none [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
									/>
									<button
										class="flex h-7 w-7 items-center justify-center text-muted-foreground hover:bg-accent hover:text-foreground"
										aria-label="Increase code font size"
										onclick={() => codeFontSize.set(Math.min(18, $codeFontSize + 1))}>+</button
									>
								</div>
							</div>
						</div>

						<!-- UI family row -->
						<div
							class="border-border/40 flex items-center justify-between gap-4 border-t px-4 py-3"
						>
							<span class="text-[12.5px] text-foreground">{$t('appearance_ui_font_family')}</span>
							<FontPicker kind="sans" bind:value={$uiFontFamily} />
						</div>

						<!-- Code family + live preview -->
						<div
							class="border-border/40 flex items-center justify-between gap-4 border-t px-4 py-3"
						>
							<span class="text-[12.5px] text-foreground">{$t('appearance_code_font_family')}</span>
							<FontPicker kind="mono" bind:value={$codeFontFamily} />
						</div>
						<div class="border-border/40 bg-background/30 border-t px-4 py-3">
							<pre
								class="text-foreground/80 overflow-x-auto leading-relaxed"
								style="font-size: {$codeFontSize}px; font-family: {normalizeFontStack(
									$codeFontFamily,
									DEFAULT_CODE_FONT_STACK
								)}"><code
									><span class="text-purple-400">function</span> <span class="text-blue-400"
										>greet</span
									><span class="text-muted-foreground/70">(</span><span class="text-orange-300"
										>name</span
									><span class="text-muted-foreground/70">)</span> <span
										class="text-muted-foreground/70">&#123;</span
									>
  <span class="text-purple-400">return</span> <span class="text-green-400"
										>{'`Hello, ${name}!`'}</span
									><span class="text-muted-foreground/70">;</span>
<span class="text-muted-foreground/70">&#125;</span></code
								></pre>
						</div>

						<!-- Smoothing -->
						<div
							class="border-border/40 flex items-center justify-between gap-4 border-t px-4 py-3"
						>
							<div class="min-w-0">
								<p class="text-[12.5px] text-foreground">{$t('appearance_font_smoothing')}</p>
								<p class="text-muted-foreground/55 mt-0.5 text-[11.5px]">
									{$t('appearance_font_smoothing_desc')}
								</p>
							</div>
							<button
								role="switch"
								aria-checked={$fontSmoothing}
								aria-label={$t('appearance_font_smoothing')}
								class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors {$fontSmoothing
									? 'bg-[var(--ue-accent)]'
									: 'bg-muted-foreground/30'}"
								onclick={() => fontSmoothing.set(!$fontSmoothing)}
							>
								<span
									class="pointer-events-none inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform {$fontSmoothing
										? 'translate-x-[18px]'
										: 'translate-x-[3px]'}"
								></span>
							</button>
						</div>
					</div>
				</section>

				<!-- PRIVACY -->
				<section class="mb-8">
					<div
						class="text-muted-foreground/55 mb-3 text-[11px] font-medium uppercase tracking-wider"
					>
						{$t('appearance_privacy')}
					</div>
					<div class="border-border/60 rounded-lg border bg-card">
						<div class="flex items-center justify-between gap-4 px-4 py-3">
							<div class="min-w-0">
								<p class="text-[12.5px] text-foreground">{$t('appearance_hide_email')}</p>
								<p class="text-muted-foreground/55 mt-0.5 text-[11.5px]">
									{$t('appearance_hide_email_desc')}
								</p>
							</div>
							<button
								role="switch"
								aria-checked={$hideEmail}
								aria-label={$t('appearance_hide_email')}
								class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors {$hideEmail
									? 'bg-[var(--ue-accent)]'
									: 'bg-muted-foreground/30'}"
								onclick={() => hideEmail.set(!$hideEmail)}
							>
								<span
									class="pointer-events-none inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform {$hideEmail
										? 'translate-x-[18px]'
										: 'translate-x-[3px]'}"
								></span>
							</button>
						</div>
					</div>
				</section>
			{:else if $settingsTab === 'indexing'}
				<ProjectIndexPanel bind:this={indexPanel} />
			{:else if $settingsTab === 'setup'}
				<div class="mb-6">
					<h2 class="mb-1 text-[18px] font-medium text-foreground">Setup</h2>
					<p class="text-muted-foreground/60 text-[13px]">
						Start here if NeoStack AI is not ready to chat yet. Advanced MCP and agent controls stay
						in their own tabs.
					</p>
				</div>
				<div class="mb-6">
					<SetupChecklist />
				</div>
				<div class="mb-6">
					<PrerequisitesPanel />
				</div>
				<McpConnectionsPanel />
			{:else if $settingsTab === 'extensions'}
				<ExtensionsPanel bind:this={extensionsPanel} />
			{:else if $settingsTab === 'skills'}
				<SkillsPanel />
			{:else if $settingsTab === 'mcp'}
				<div class="mb-6">
					<h2 class="mb-1 text-[18px] font-medium text-foreground">MCP Connections</h2>
					<p class="text-muted-foreground/60 text-[13px]">
						Connect external MCP clients (Claude Code, Gemini, Codex, etc.) to this editor instance.
					</p>
				</div>
				<McpConnectionsPanel />
			{:else if $settingsTab === 'about'}
				<div class="mb-6">
					<h2 class="mb-1 text-[18px] font-medium text-foreground">{$t('about_heading')}</h2>
					<p class="text-muted-foreground/60 text-[13px]">{$t('about_desc')}</p>
				</div>

				<div class="border-border/60 rounded-lg border bg-card p-4">
					<div class="mb-3">
						<h3 class="text-[14px] font-medium text-foreground">{$t('updates_heading')}</h3>
						<p class="text-muted-foreground/60 mt-1 text-[12px]">{$t('updates_desc')}</p>
					</div>

					<button
						class="border-border/60 rounded-md border px-3 py-2 text-[13px] text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
						onclick={handleCheckForUpdates}
						disabled={isCheckingForUpdates}
					>
						{isCheckingForUpdates ? $t('checking') : $t('check_for_updates')}
					</button>

					{#if updateStatus?.currentVersion}
						<p class="text-muted-foreground/70 mt-2 text-[12px]">
							Installed: <span class="text-foreground">v{updateStatus.currentVersion}</span>
						</p>
					{/if}

					<!-- The verdict, which used to exist only as an editor toast that
					     never fires when you are already current. -->
					<!-- Ordered so an in-flight download or install is never mistaken
					     for "up to date": those states still carry latestVersion,
					     so they have to be claimed before the up-to-date branch. -->
					{#if updateStatus?.state === 'updateAvailable' && updateStatus.latestVersion}
						<p class="mt-1 text-[12px] text-[var(--ue-accent)]">
							Update available: v{updateStatus.latestVersion} — use the editor
							notification to download and install.
						</p>
					{:else if updateStatus?.state === 'downloading'}
						<p class="mt-1 text-[12px] text-[var(--ue-accent)]">
							Downloading v{updateStatus.latestVersion}… {Math.round(
								updateStatus.downloadProgress * 100
							)}%
						</p>
					{:else if updateStatus?.state === 'downloaded'}
						<p class="mt-1 text-[12px] text-[var(--ue-accent)]">
							v{updateStatus.latestVersion} is ready to install — use the editor
							notification.
						</p>
					{:else if updateStatus?.state === 'installing'}
						<p class="mt-1 text-[12px] text-[var(--ue-accent)]">
							Installing v{updateStatus.latestVersion} — the editor will restart.
						</p>
					{:else if updateStatus?.state === 'failed'}
						<p class="mt-1 text-[12px] text-amber-400/80">
							{updateStatus.error || 'The update check failed. Try again shortly.'}
						</p>
					{:else if updateStatus?.checked && updateStatus.latestVersion}
						<p class="mt-1 text-[12px] text-emerald-500">You're on the latest version.</p>
					{:else if updateStatus?.checked && !isCheckingForUpdates}
						<!-- Server had no live build for this engine + platform — not the
						     same as being up to date, and worth saying so plainly. A
						     failed check no longer lands here: it reports state=failed. -->
						<p class="text-muted-foreground/70 mt-1 text-[12px]">
							No build published for this engine and platform yet.
						</p>
					{/if}

					{#if updateCheckMessage}
						<p class="text-muted-foreground/70 mt-2 text-[12px]">{updateCheckMessage}</p>
					{/if}
				</div>

				<div class="border-border/60 mt-4 rounded-lg border bg-card p-4">
					<div class="mb-3">
						<h3 class="text-[14px] font-medium text-foreground">Project Settings (Recovery)</h3>
						<p class="text-muted-foreground/60 mt-1 text-[12px]">
							Bootstrap options — auto-update, MCP port, API tokens, custom agents — live in
							Unreal's Project Settings. Use this if the web UI is unreachable or misconfigured.
						</p>
					</div>

					<button
						class="border-border/60 rounded-md border px-3 py-2 text-[13px] text-foreground transition-colors hover:bg-accent"
						onclick={() => openPluginSettings()}
					>
						Open Project Settings
					</button>
				</div>
			{:else if $settingsTab === 'agents'}
				<div class="mb-6">
					<h2 class="mb-1 text-[18px] font-medium text-foreground">Chat Providers & Agents</h2>
					<p class="text-muted-foreground/60 text-[13px]">
						Configure NeoStack Cloud, local/BYOK providers, and advanced ACP agent execution.
					</p>
				</div>

				<NeoStackAccountCard variant="settings" />

				<div class="border-border/60 mb-6 rounded-lg border bg-card p-4">
					<div class="mb-3">
						<h3 class="text-[14px] font-medium text-foreground">Recommended first step</h3>
						<p class="text-muted-foreground/60 mt-1 text-[12px]">
							Use NeoStack Cloud for the simplest setup. Local/BYOK providers and ACP agents remain
							available below.
						</p>
					</div>
					<NeoStackSignInButton
						label="Connect NeoStack Cloud"
						variant="primary"
						onsuccess={() => onNeoStackCloudChanged()}
					/>
				</div>

				{#if providerActionError}
					<div
						class="mb-4 rounded-md border border-red-500/25 bg-red-500/[0.05] px-3 py-2 text-[12px] text-red-300"
					>
						{providerActionError}
					</div>
				{/if}

				<div class="mb-6">
					<AgentRegistry />
				</div>

				<!-- Agent Execution Settings -->
				<div class="border-border/40 mb-6 border-t pt-6">
					<h2 class="mb-1 text-[18px] font-medium text-foreground">Agent Execution</h2>
					<p class="text-muted-foreground/60 text-[13px]">
						System prompt and tool timeout used across all ACP-based agents.
					</p>
				</div>

				<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
					<div class="mb-3">
						<h3 class="text-[14px] font-medium text-foreground">Custom System Prompt</h3>
						<p class="text-muted-foreground/60 mt-1 text-[12px]">
							Extra instructions appended to the system prompt for ACP agents (Claude Code, Gemini
							CLI, Codex, OpenCode, Cursor Agent).
						</p>
					</div>
					<textarea
						rows="14"
						class="border-border/60 focus:border-foreground/30 w-full rounded-md border bg-transparent px-3 py-2 font-mono text-[12px] text-foreground focus:outline-none"
						value={agentExecutionSettings.systemPromptAppend}
						oninput={(e) => {
							const v = (e.currentTarget as HTMLTextAreaElement).value;
							agentExecutionSettings = { ...agentExecutionSettings, systemPromptAppend: v };
							scheduleAgentExecutionSave('systemPromptAppend', v);
						}}
					></textarea>
				</div>

				<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
					<div class="mb-3">
						<h3 class="text-[14px] font-medium text-foreground">Tool Execution Timeout</h3>
						<p class="text-muted-foreground/60 mt-1 text-[12px]">
							Seconds a tool can run before the agent receives a timeout error. The tool keeps
							running in the background. 0 disables the timeout.
						</p>
					</div>
					<div class="flex items-center gap-3">
						<input
							type="number"
							min="0"
							max="600"
							class="border-border/60 focus:border-foreground/30 w-28 rounded-md border bg-transparent px-3 py-1.5 text-[13px] text-foreground focus:outline-none"
							value={agentExecutionSettings.toolTimeout}
							oninput={(e) => {
								const raw = parseInt((e.currentTarget as HTMLInputElement).value, 10);
								const clamped = Number.isFinite(raw) ? Math.max(0, Math.min(600, raw)) : 60;
								agentExecutionSettings = { ...agentExecutionSettings, toolTimeout: clamped };
								scheduleAgentExecutionSave('toolTimeout', String(clamped));
							}}
						/>
						<span class="text-muted-foreground/60 text-[12px]">seconds</span>
					</div>
				</div>

				<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
					<div class="mb-3">
						<h3 class="text-[14px] font-medium text-foreground">Agent Response Timeout</h3>
						<p class="text-muted-foreground/60 mt-1 text-[12px]">
							Seconds an ACP agent prompt can be silent before NeoStack reports a timeout. Any agent
							activity refreshes the timer. 0 disables the timeout.
						</p>
					</div>
					<div class="flex items-center gap-3">
						<input
							type="number"
							min="0"
							max="86400"
							class="border-border/60 focus:border-foreground/30 w-28 rounded-md border bg-transparent px-3 py-1.5 text-[13px] text-foreground focus:outline-none"
							value={agentExecutionSettings.agentResponseTimeout}
							oninput={(e) => {
								const raw = parseInt((e.currentTarget as HTMLInputElement).value, 10);
								const clamped = Number.isFinite(raw) ? Math.max(0, Math.min(86400, raw)) : 0;
								agentExecutionSettings = {
									...agentExecutionSettings,
									agentResponseTimeout: clamped
								};
								scheduleAgentExecutionSave('agentResponseTimeout', String(clamped));
							}}
						/>
						<span class="text-muted-foreground/60 text-[12px]">seconds</span>
					</div>
				</div>

				<div class="border-border/40 mb-6 border-t pt-6">
					<h2 class="mb-1 text-[18px] font-medium text-foreground">{$t('providers_heading')}</h2>
					<p class="text-muted-foreground/60 text-[13px]">{$t('providers_desc')}</p>
				</div>

				{#if isLoadingProviders}
					<div class="text-muted-foreground/50 flex items-center gap-2 py-8">
						<span
							class="border-muted-foreground/30 inline-block h-4 w-4 animate-spin rounded-full border-2 border-t-muted-foreground"
						></span>
						Loading...
					</div>
				{:else}
					<!-- Provider priority list -->
					<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
						<h3 class="mb-1 text-[14px] font-medium text-foreground">
							{$t('active_provider_label')}
						</h3>
						<p class="text-muted-foreground/60 mb-3 text-[12px]">{$t('active_provider_desc')}</p>

						{#if priorityProviders.length === 0}
							<p class="text-muted-foreground/40 py-3 text-[12px]">
								No providers configured. Add one below.
							</p>
						{:else}
							<div class="flex flex-col gap-1">
								{#each priorityProviders as provider (provider.id)}
									<div
										class="border-border/40 hover:bg-accent/20 group flex items-center gap-2 rounded-md border px-3 py-2 transition-colors {selectedProviderId ===
										provider.id
											? 'border-[var(--ue-accent)]/30 bg-[var(--ue-accent)]/5'
											: ''}"
									>
										<!-- Provider info -->
										<button
											class="flex-1 text-left"
											onclick={() => {
												selectedProviderId = provider.id;
												providerApiKeyInput = '';
												showAddModelForm = false;
												showImportModal = false;
												showDeleteConfirm = '';
											}}
										>
											<span class="text-[13px] font-medium text-foreground">{provider.name}</span>
											{#if provider.isUserDefined}
												<span
													class="bg-[var(--ue-accent)]/10 text-[var(--ue-accent)]/70 ml-1 rounded px-1 py-0.5 text-[9px]"
													>custom</span
												>
											{/if}
											{#if provider.configured}
												<span class="ml-1.5 text-[10px] text-emerald-400">&#x2022; ready</span>
											{:else if provider.requiresApiKey && !provider.hasApiKey}
												<span class="ml-1.5 text-[10px] text-amber-400">&#x2022; needs key</span>
											{/if}
										</button>
										<!-- Remove button -->
										<button
											class="text-muted-foreground/50 hover:bg-destructive/10 flex h-10 w-10 items-center justify-center rounded transition-colors hover:text-red-400"
											onclick={() => handleRemoveProvider(provider.id)}
											title="Remove"
											aria-label={`Remove ${provider.name}`}>&#x2715;</button
										>
									</div>
								{/each}
							</div>
						{/if}

						<!-- Add built-in provider -->
						{#if builtinAvailableToAdd.length > 0}
							<div class="mt-3 flex flex-wrap gap-1.5">
								{#each builtinAvailableToAdd as provider (provider.id)}
									<button
										class="border-border/40 text-muted-foreground/40 rounded-md border border-dashed px-2.5 py-1 text-[12px] transition-colors hover:border-border hover:text-muted-foreground"
										onclick={() => handleAddProvider(provider.id)}>+ {provider.name}</button
									>
								{/each}
							</div>
						{/if}

						<!-- Add custom provider -->
						<div class="border-border/20 mt-3 border-t pt-3">
							{#if showNewCustomProviderForm}
								<div class="flex flex-col gap-2">
									<input
										type="text"
										bind:value={newCustomProviderName}
										class="border-border/60 placeholder:text-muted-foreground/40 focus:border-foreground/30 w-full rounded-md border bg-transparent px-3 py-2 text-[13px] text-foreground focus:outline-none"
										placeholder="Provider name (e.g. My vLLM Server)"
									/>
									<input
										type="text"
										bind:value={newCustomProviderUrl}
										class="border-border/60 placeholder:text-muted-foreground/40 focus:border-foreground/30 w-full rounded-md border bg-transparent px-3 py-2 text-[13px] text-foreground focus:outline-none"
										placeholder="Base URL (e.g. http://localhost:8000/v1)"
									/>
									<div class="flex gap-2">
										<button
											class="border-border/60 rounded-md border px-3 py-1.5 text-[12px] text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
											onclick={handleCreateCustomProvider}
											disabled={!newCustomProviderName.trim()}>Create</button
										>
										<button
											class="text-muted-foreground/60 rounded-md px-3 py-1.5 text-[12px] transition-colors hover:text-foreground"
											onclick={() => {
												showNewCustomProviderForm = false;
												newCustomProviderName = '';
												newCustomProviderUrl = '';
											}}>Cancel</button
										>
									</div>
								</div>
							{:else}
								<button
									class="border-[var(--ue-accent)]/30 text-[var(--ue-accent)]/60 hover:border-[var(--ue-accent)]/60 rounded-md border border-dashed px-2.5 py-1 text-[12px] transition-colors hover:text-[var(--ue-accent)]"
									onclick={() => {
										showNewCustomProviderForm = true;
									}}>+ Add Custom Provider</button
								>
							{/if}
						</div>
					</div>

					<!-- Selected provider config -->
					{#if selectedProvider}
						<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
							<div class="mb-3 flex items-start justify-between">
								<div>
									<div class="flex items-center gap-2">
										<h4 class="text-[14px] font-medium text-foreground">{selectedProvider.name}</h4>
										{#if selectedProvider.isUserDefined}
											<span
												class="bg-[var(--ue-accent)]/10 rounded px-1.5 py-0.5 text-[9px] font-medium text-[var(--ue-accent)]"
												>custom</span
											>
										{/if}
									</div>
									<p class="text-muted-foreground/60 mt-0.5 text-[12px]">
										{selectedProvider.description}
									</p>
								</div>
								{#if selectedProvider.isUserDefined}
									{#if showDeleteConfirm === selectedProvider.id}
										<div class="flex items-center gap-1.5">
											<span class="text-[11px] text-red-400">Delete?</span>
											<button
												class="rounded px-2 py-0.5 text-[11px] text-red-400 transition-colors hover:bg-red-500/10"
												onclick={() => handleDeleteCustomProvider(selectedProvider.id)}>Yes</button
											>
											<button
												class="rounded px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-accent"
												onclick={() => {
													showDeleteConfirm = '';
												}}>No</button
											>
										</div>
									{:else}
										<button
											class="text-muted-foreground/30 rounded p-1 transition-colors hover:text-red-400"
											onclick={() => {
												showDeleteConfirm = selectedProvider.id;
											}}
											title="Delete provider">&#x2715;</button
										>
									{/if}
								{/if}
							</div>

							<div class="grid gap-4">
								{#if selectedProvider.isUserDefined}
									<label
										class="border-border/40 bg-background/40 flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2"
									>
										<input
											type="checkbox"
											checked={selectedProvider.requiresApiKey}
											onchange={(e) =>
												handleToggleRequiresApiKey(
													selectedProviderId,
													(e.currentTarget as HTMLInputElement).checked
												)}
											class="h-3.5 w-3.5 rounded border-border accent-[var(--ue-accent)]"
										/>
										<span class="text-[12px] text-muted-foreground"
											>Require an API key for this provider</span
										>
									</label>
								{/if}

								<!-- Auth: NeoStack signs in with the browser; other providers take an API key -->
								{#if selectedProviderId === 'neostack'}
									<div>
										<span class="mb-1.5 block text-[12px] font-medium text-muted-foreground"
											>Account</span
										>
										<NeoStackSignInButton
											label="Sign in with NeoStack"
											variant="primary"
											onsuccess={() => onNeoStackCloudChanged()}
										/>
										<p class="text-muted-foreground/60 mt-1.5 text-[11px]">
											Opens your browser to sign in securely — no API key needed.
										</p>
									</div>
								{:else if selectedProvider.requiresApiKey}
									<div>
										<span class="mb-1.5 block text-[12px] font-medium text-muted-foreground"
											>{$t('provider_api_key_label')}</span
										>
										{#if selectedProvider.hasApiKey}
											<div class="mb-1.5 flex items-center gap-2">
												<span class="text-muted-foreground/50 font-mono text-[12px]"
													>····{selectedProvider.apiKeyMasked.slice(-4)}</span
												>
												<span
													class="rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-400"
													>{$t('provider_key_set')}</span
												>
											</div>
										{/if}
										<div class="flex gap-2">
											<input
												type="password"
												bind:value={providerApiKeyInput}
												class="border-border/60 placeholder:text-muted-foreground/40 focus:border-foreground/30 flex-1 rounded-md border bg-transparent px-3 py-2 text-[13px] text-foreground focus:outline-none"
												placeholder={selectedProvider.hasApiKey
													? $t('provider_api_key_replace')
													: $t('provider_api_key_enter')}
											/>
											<button
												class="border-border/60 rounded-md border px-3 py-2 text-[13px] text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
												onclick={() =>
													handleProviderApiKeySave(selectedProviderId, providerApiKeyInput)}
												disabled={!providerApiKeyInput.trim()}>{$t('save')}</button
											>
										</div>
									</div>
								{:else}
									<div
										class="rounded-md bg-emerald-500/5 px-3 py-2 text-[12px] text-emerald-400/80"
									>
										{$t('provider_no_key_needed')}
									</div>
								{/if}

								<!-- Base URL -->
								<div>
									<span class="mb-1.5 block text-[12px] font-medium text-muted-foreground"
										>{$t('provider_base_url_label')}</span
									>
									{#if selectedProvider.isUserDefined}
										<input
											type="text"
											value={selectedProvider.baseUrl}
											oninput={(e) => {
												const url = (e.currentTarget as HTMLInputElement).value;
												providerSettings = {
													...providerSettings,
													providers: providerSettings.providers.map((p) =>
														p.id === selectedProviderId ? { ...p, baseUrl: url } : p
													)
												};
												debouncedCustomProviderUpdate(selectedProviderId, '', url);
											}}
											class="border-border/60 placeholder:text-muted-foreground/40 focus:border-foreground/30 w-full rounded-md border bg-transparent px-3 py-2 text-[13px] text-foreground focus:outline-none"
											placeholder="https://api.example.com/v1"
										/>
									{:else}
										<input
											type="text"
											value={selectedProvider.baseUrl}
											oninput={(e) => {
												const url = (e.currentTarget as HTMLInputElement).value;
												providerSettings = {
													...providerSettings,
													providers: providerSettings.providers.map((p) =>
														p.id === selectedProviderId ? { ...p, baseUrl: url } : p
													)
												};
												debouncedProviderBaseUrl(selectedProviderId, url);
											}}
											class="border-border/60 placeholder:text-muted-foreground/40 focus:border-foreground/30 w-full rounded-md border bg-transparent px-3 py-2 text-[13px] text-foreground focus:outline-none"
											placeholder={selectedProvider.defaultBaseUrl}
										/>
									{/if}
									<p class="text-muted-foreground/50 mt-1 text-[11px]">
										{$t('provider_base_url_help')}
									</p>
								</div>

								<!-- Provider: Model Management -->
								{#if selectedProvider.isUserDefined || selectedProvider.supportsModelDiscovery}
									<div class="border-border/30 border-t pt-3">
										<div class="mb-2 flex items-center justify-between">
											<span class="text-[12px] font-medium text-muted-foreground">Models</span>
											<div class="flex items-center gap-2">
												{#if !selectedProvider.isUserDefined && selectedProvider.supportsModelDiscovery}
													<button
														class="border-border/60 rounded-md border px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
														onclick={async () => {
															await refreshProviderModels();
														}}>Refresh</button
													>
												{/if}
												{#if selectedProvider.isUserDefined}
													<button
														class="border-border/60 rounded-md border px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
														onclick={() => {
															importJsonText = '';
															importResult = null;
															showImportModal = true;
														}}>Import JSON</button
													>
												{/if}
												<button
													class="border-border/60 rounded-md border px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
													onclick={() => {
														newModelId = '';
														newModelName = '';
														newModelDesc = '';
														showAddModelForm = !showAddModelForm;
													}}>+ Add</button
												>
											</div>
										</div>
										{#if !selectedProvider.isUserDefined && selectedProvider.supportsModelDiscovery}
											<p class="text-muted-foreground/50 mb-2 text-[11px]">
												Models are auto-discovered from the provider's /models endpoint. Use + Add
												for models not yet discovered.
											</p>
										{/if}

										<!-- Add model form -->
										{#if showAddModelForm}
											<div
												class="border-border/40 bg-background/50 mb-2 flex flex-col gap-1.5 rounded-md border p-2"
											>
												<input
													type="text"
													bind:value={newModelId}
													class="border-border/40 placeholder:text-muted-foreground/40 focus:border-foreground/30 w-full rounded border bg-transparent px-2 py-1 text-[12px] text-foreground focus:outline-none"
													placeholder="Model ID (required, e.g. gpt-4o)"
												/>
												<input
													type="text"
													bind:value={newModelName}
													class="border-border/40 placeholder:text-muted-foreground/40 focus:border-foreground/30 w-full rounded border bg-transparent px-2 py-1 text-[12px] text-foreground focus:outline-none"
													placeholder="Display name (optional)"
												/>
												<input
													type="text"
													bind:value={newModelDesc}
													class="border-border/40 placeholder:text-muted-foreground/40 focus:border-foreground/30 w-full rounded border bg-transparent px-2 py-1 text-[12px] text-foreground focus:outline-none"
													placeholder="Description (optional)"
												/>
												<div class="flex gap-1.5">
													<button
														class="border-border/60 rounded border px-2 py-0.5 text-[11px] text-foreground transition-colors hover:bg-accent disabled:opacity-40"
														onclick={() => handleAddModel(selectedProviderId)}
														disabled={!newModelId.trim()}>Add</button
													>
													<button
														class="text-muted-foreground/60 rounded px-2 py-0.5 text-[11px] transition-colors hover:text-foreground"
														onclick={() => {
															showAddModelForm = false;
														}}>Cancel</button
													>
												</div>
											</div>
										{/if}

										<!-- Model list -->
										{#if selectedProvider.models && selectedProvider.models.length > 0}
											<div class="border-border/30 max-h-[200px] overflow-y-auto rounded-md border">
												{#each selectedProvider.models as model (model.id)}
													<div
														class="border-border/20 group flex items-center gap-2 border-b px-3 py-1.5 last:border-b-0"
													>
														<div class="min-w-0 flex-1">
															<span class="text-[12px] text-foreground"
																>{model.name || model.id}</span
															>
															<span class="text-muted-foreground/40 ml-1.5 text-[10px]"
																>{model.id}</span
															>
														</div>
														<button
															class="text-muted-foreground/50 hover:bg-destructive/10 flex h-10 w-10 items-center justify-center rounded transition-colors hover:text-red-400"
															onclick={() => handleRemoveModel(selectedProviderId, model.id)}
															title="Remove"
															aria-label={`Remove ${model.name || model.id}`}>&#x2715;</button
														>
													</div>
												{/each}
											</div>
										{:else if selectedProvider.isUserDefined}
											<p class="text-muted-foreground/40 py-2 text-[11px]">
												No models defined. Add manually or import from JSON.
											</p>
										{:else}
											<p class="text-muted-foreground/40 py-2 text-[11px]">
												No extra models added. Discovered models appear in the model picker.
											</p>
										{/if}

										<!-- Model discovery toggle (custom providers only) -->
										{#if selectedProvider.isUserDefined}
											<label class="mt-2 flex cursor-pointer items-center gap-2">
												<input
													type="checkbox"
													checked={selectedProvider.enableModelDiscovery}
													onchange={(e) =>
														handleToggleModelDiscovery(
															selectedProviderId,
															(e.currentTarget as HTMLInputElement).checked
														)}
													class="h-3.5 w-3.5 rounded border-border accent-[var(--ue-accent)]"
												/>
												<span class="text-[12px] text-muted-foreground"
													>Auto-discover models from /models endpoint</span
												>
											</label>
										{/if}
									</div>

									<!-- Import Modal (custom providers only) -->
									{#if showImportModal && selectedProvider.isUserDefined}
										<div class="border-border/30 border-t pt-3">
											<span class="mb-1.5 block text-[12px] font-medium text-muted-foreground"
												>Import Models from JSON</span
											>
											<p class="text-muted-foreground/50 mb-2 text-[11px]">
												Paste a JSON array of models. Format: [&#123;"id": "model-id", "name":
												"Display Name"&#125;] or an OpenAI /models response.
											</p>
											<textarea
												bind:value={importJsonText}
												class="border-border/60 placeholder:text-muted-foreground/40 focus:border-foreground/30 h-[120px] w-full resize-y rounded-md border bg-transparent px-3 py-2 font-mono text-[11px] text-foreground focus:outline-none"
												placeholder={'[{"id": "my-model", "name": "My Model"}]'}
											></textarea>
											{#if importResult}
												<div
													class="mt-1.5 rounded-md px-2 py-1 text-[11px] {importResult.errors
														.length > 0
														? 'bg-red-500/5 text-red-400'
														: 'bg-emerald-500/5 text-emerald-400'}"
												>
													{importResult.imported} model{importResult.imported !== 1 ? 's' : ''} imported.
													{#each importResult.errors as error, errorIndex (`${errorIndex}:${error}`)}
														<div class="mt-0.5 text-red-400/80">{error}</div>
													{/each}
												</div>
											{/if}
											<div class="mt-2 flex gap-2">
												<button
													class="border-border/60 rounded-md border px-3 py-1 text-[12px] text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
													onclick={() => handleImportModels(selectedProviderId)}
													disabled={!importJsonText.trim() || isImporting}
												>
													{isImporting ? 'Importing...' : 'Import'}
												</button>
												<button
													class="text-muted-foreground/60 rounded-md px-3 py-1 text-[12px] transition-colors hover:text-foreground"
													onclick={() => {
														showImportModal = false;
														importResult = null;
													}}>Close</button
												>
											</div>
										</div>
									{/if}
								{/if}
							</div>
						</div>
					{/if}

					<div class="bg-foreground/5 text-muted-foreground/50 rounded-md px-3 py-2 text-[11px]">
						{$t('provider_reconnect_note')}
					</div>

					<!-- Models enable/disable -->
					<div class="mb-4 mt-6">
						<h2 class="mb-1 text-[18px] font-medium text-foreground">Models</h2>
						<p class="text-muted-foreground/60 text-[13px]">
							Choose which models appear in the model selector. {#if hasCustomModelSelection}<span
									class="text-[var(--ue-accent)]">{enabledModelCount} enabled</span
								>{:else}All models shown{/if}
						</p>
					</div>

					{#if isLoadingModels}
						<div class="text-muted-foreground/50 flex items-center gap-2 py-4">
							<span
								class="border-muted-foreground/30 inline-block h-3 w-3 animate-spin rounded-full border-2 border-t-muted-foreground"
							></span>
							Loading models...
						</div>
					{:else if settingsModels.length > 0}
						<!-- Search + actions -->
						<div class="mb-3 flex items-center gap-2">
							<input
								type="text"
								bind:value={modelSearchQuery}
								class="border-border/60 placeholder:text-muted-foreground/40 focus:border-foreground/30 flex-1 rounded-md border bg-transparent px-3 py-2 text-[13px] text-foreground focus:outline-none"
								placeholder="Search models..."
							/>
						</div>
						<div class="mb-3 flex items-center gap-2">
							<button
								class="border-border/60 rounded-md border px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
								onclick={handleEnableAllModels}>Enable All</button
							>
							<button
								class="border-border/60 rounded-md border px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
								onclick={handleDisableAllModels}>Disable All</button
							>
							{#if hasCustomModelSelection}
								<button
									class="border-border/60 text-muted-foreground/60 rounded-md border border-dashed px-2.5 py-1 text-[11px] transition-colors hover:border-border hover:text-muted-foreground"
									onclick={handleShowAllModels}>Reset (Show All)</button
								>
							{/if}
							<span class="text-muted-foreground/40 ml-auto text-[11px]"
								>{filteredSettingsModels.length} models</span
							>
						</div>

						<!-- Model list -->
						<div class="border-border/60 rounded-lg border bg-card">
							<div
								bind:this={settingsModelListEl}
								bind:clientHeight={settingsModelViewportHeight}
								class="max-h-[400px] overflow-y-auto"
								onscroll={handleSettingsModelScroll}
							>
								<div
									class="relative"
									style:height={`${filteredSettingsModels.length * SETTINGS_MODEL_ROW_HEIGHT}px`}
								>
									{#each visibleSettingsModels as model, visibleIndex (model.id)}
										{@const modelIndex = settingsModelWindowStart + visibleIndex}
										<label
											class="border-border/20 hover:bg-accent/20 absolute left-0 right-0 flex cursor-pointer items-center gap-3 border-b px-4 transition-colors"
											style:height={`${SETTINGS_MODEL_ROW_HEIGHT}px`}
											style:transform={`translateY(${modelIndex * SETTINGS_MODEL_ROW_HEIGHT}px)`}
										>
											<input
												type="checkbox"
												checked={isModelEnabled(model.id)}
												onchange={(e) =>
													handleToggleModel(
														model.id,
														(e.currentTarget as HTMLInputElement).checked
													)}
												class="h-3.5 w-3.5 shrink-0 rounded border-border accent-[var(--ue-accent)]"
											/>
											<div class="min-w-0 flex-1">
												<div class="flex items-center gap-1.5">
													<span class="truncate text-[13px] text-foreground">{model.name}</span>
													{#if model.providerDisplayName}
														<span
															class="bg-foreground/5 text-muted-foreground/40 shrink-0 rounded px-1 py-0.5 text-[9px]"
															>{model.providerDisplayName}</span
														>
													{/if}
												</div>
												<div class="text-muted-foreground/40 truncate text-[11px]">{model.id}</div>
											</div>
										</label>
									{/each}
								</div>
							</div>
						</div>
						{#if filteredSettingsModels.length === 0 && modelSearchQuery.trim()}
							<p class="text-muted-foreground/40 py-4 text-center text-[12px]">
								No models match your search.
							</p>
						{/if}
					{:else}
						<p class="text-muted-foreground/40 py-4 text-[12px]">
							No models available. Configure a provider above first.
						</p>
					{/if}
				{/if}

				<!-- Prerequisites -->
				<div class="border-border/40 mt-8 border-t pt-6">
					<PrerequisitesPanel />
				</div>
			{:else if $settingsTab === 'usage'}
				{@const acct = $cloudAccount}
				{@const conn = acct?.connectionState ?? 'disconnected'}
				{@const weeklyRemaining = Math.round(acct?.usage?.remainingPercent ?? 0)}
				{@const periodPct = Math.round(acct?.quota?.period?.percent ?? 0)}
				{@const burstPct = Math.round(acct?.quota?.burst?.percent ?? 0)}
				<div class="mb-6 flex items-start justify-between gap-3">
					<div>
						<h2 class="mb-1 text-[18px] font-medium text-foreground">{$t('usage_heading')}</h2>
						<p class="text-muted-foreground/60 text-[13px]">{$t('usage_desc')}</p>
					</div>
					<button
						class="border-border/60 text-muted-foreground/70 rounded-md border px-2.5 py-1.5 text-[12px] transition-colors hover:bg-accent hover:text-foreground"
						onclick={() => refreshCloudAccount()}>{$t('usage_refresh')}</button
					>
				</div>

				{#if conn !== 'connected' && conn !== 'offline'}
					<div class="border-border/60 bg-card/40 rounded-lg border p-6 text-center">
						<p class="text-muted-foreground/70 text-[13px]">{$t('usage_signin_prompt')}</p>
						<div class="mt-3 inline-block">
							<NeoStackSignInButton
								label={$t('usage_signin_button')}
								variant="primary"
								onsuccess={() => onNeoStackCloudChanged()}
							/>
						</div>
					</div>
				{:else}
					{#if acct?.usage}
						{@const usageColor =
							weeklyRemaining > 40 ? '#22c55e' : weeklyRemaining > 15 ? '#eab308' : '#ef4444'}
						<div class="border-border/60 bg-card/40 mb-6 rounded-lg border p-4">
							<div class="mb-2 flex items-center justify-between gap-3">
								<div>
									<h3 class="text-[13px] font-medium text-foreground">
										{acct.usage.tier === 'pro'
											? 'Pro'
											: acct.usage.tier === 'trial'
												? 'Trial'
												: acct.usage.tier === 'comp'
													? 'Complimentary'
													: 'Free'} weekly AI usage
									</h3>
									<p class="text-muted-foreground/50 mt-0.5 text-[10.5px]">
										Resets {new Date(acct.usage.resetsAt).toLocaleDateString(undefined, {
											weekday: 'long',
											month: 'short',
											day: 'numeric'
										})}
									</p>
								</div>
								<span class="text-[12px] font-medium tabular-nums" style="color: {usageColor}">
									{weeklyRemaining}% remaining
								</span>
							</div>
							<div class="bg-muted-foreground/15 h-2 w-full overflow-hidden rounded-full">
								<div
									class="h-full rounded-full transition-all"
									style="width: {weeklyRemaining}%; background-color: {usageColor};"
								></div>
							</div>
							<p class="text-muted-foreground/45 mt-2 text-[10.5px] leading-relaxed">
								Includes every model call made while an agent works.
							</p>
						</div>
					{/if}

					{#if acct?.credits}
						<div class="border-border/60 bg-card/40 mb-6 rounded-lg border p-4">
							<div class="flex items-baseline justify-between">
								<h3 class="text-[13px] font-medium text-foreground">{$t('usage_credits')}</h3>
								<span class="text-[16px] font-medium tabular-nums text-foreground"
									>${acct.credits.total.toFixed(2)}</span
								>
							</div>
							<div class="text-muted-foreground/60 mt-2 grid grid-cols-2 gap-4 text-[11.5px]">
								<div>
									<div class="text-muted-foreground/55">{$t('usage_credits_subscription')}</div>
									<div class="text-foreground/80 tabular-nums">
										${acct.credits.subscriptionBalanceUsd.toFixed(2)}
									</div>
								</div>
								<div>
									<div class="text-muted-foreground/55">{$t('usage_credits_permanent')}</div>
									<div class="text-foreground/80 tabular-nums">
										${acct.credits.permanentBalanceUsd.toFixed(2)}
									</div>
								</div>
							</div>
						</div>
					{/if}

					{#if acct?.quota}
						<div class="border-border/60 bg-card/40 mb-6 rounded-lg border p-4">
							<h3 class="mb-3 text-[13px] font-medium text-foreground">{$t('usage_quota')}</h3>
							{#if acct.quota.period}
								{@const color = periodPct < 60 ? '#22c55e' : periodPct < 85 ? '#eab308' : '#ef4444'}
								<div class="mb-3">
									<div
										class="text-muted-foreground/60 mb-1 flex items-center justify-between text-[11.5px]"
									>
										<span>{$t('usage_quota_period')}</span>
										<span class="tabular-nums" style="color: {color}">{periodPct}%</span>
									</div>
									<div class="bg-muted-foreground/15 h-1.5 w-full overflow-hidden rounded-full">
										<div
											class="h-full rounded-full transition-all"
											style="width: {periodPct}%; background-color: {color};"
										></div>
									</div>
								</div>
							{/if}
							{#if acct.quota.burst}
								{@const color = burstPct < 60 ? '#22c55e' : burstPct < 85 ? '#eab308' : '#ef4444'}
								<div>
									<div
										class="text-muted-foreground/60 mb-1 flex items-center justify-between text-[11.5px]"
									>
										<span>{$t('usage_quota_burst')}</span>
										<span class="tabular-nums" style="color: {color}">{burstPct}%</span>
									</div>
									<div class="bg-muted-foreground/15 h-1.5 w-full overflow-hidden rounded-full">
										<div
											class="h-full rounded-full transition-all"
											style="width: {burstPct}%; background-color: {color};"
										></div>
									</div>
								</div>
							{/if}
						</div>
					{/if}

					{#if acct?.planName || acct?.entitled}
						{@const tier =
							acct?.clientStatus === 'lifetime' || acct?.clientStatus === 'subscription'
								? formatTierLabel(acct.clientStatus)
								: ''}
						<div class="border-border/60 bg-card/40 rounded-lg border p-4 text-[12px]">
							<h3 class="mb-2 text-[13px] font-medium text-foreground">{$t('usage_plan')}</h3>
							<div class="text-muted-foreground/70 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
								{#if tier}
									<span class="text-muted-foreground/55">{$t('usage_plan_entitlement')}</span>
									<span class="text-foreground/85">{tier}</span>
								{/if}
								{#if acct?.planName}
									<span class="text-muted-foreground/55">{$t('usage_plan_cloud')}</span>
									<span class="text-foreground/85">{acct.planName}</span>
								{/if}
								{#if acct?.organization?.name || acct?.organization?.slug}
									<span class="text-muted-foreground/55">{$t('usage_plan_workspace')}</span>
									<span class="text-foreground/85"
										>{acct?.organization?.name || acct?.organization?.slug}</span
									>
								{/if}
								{#if acct && !acct.entitled && acct.reason}
									<span class="text-muted-foreground/55">{$t('usage_plan_reason')}</span>
									<span class="text-amber-400/90">{acct.reason}</span>
								{/if}
							</div>
						</div>
					{/if}
				{/if}
			{:else if $settingsTab === 'generation'}
				<div class="mb-6">
					<h2 class="mb-1 text-[18px] font-medium text-foreground">Generation</h2>
					<p class="text-muted-foreground/60 text-[13px]">
						Image, 3D, and audio generation runs through your signed-in NeoStack Cloud account.
					</p>
				</div>
				<div class="border-border/60 rounded-lg border bg-card p-4">
					<h3 class="text-[14px] font-medium text-foreground">Managed by NeoStack Cloud</h3>
					<p class="text-muted-foreground/60 mt-1 text-[12px]">
						Models, provider credentials, durable jobs, and usage accounting are managed securely by
						the Gateway. Open Studio to create and monitor jobs.
					</p>
				</div>
			{:else if $settingsTab === 'crashes'}
				<div class="mb-6">
					<h2 class="mb-1 text-[18px] font-medium text-foreground">Crash History</h2>
					<p class="text-muted-foreground/60 text-[13px]">
						Recent crashes detected by NeoStack AI. You can send crash reports to help us fix
						issues.
					</p>
				</div>

				{#if isLoadingCrashes}
					<div class="text-muted-foreground/50 flex items-center gap-2 py-8">
						<span
							class="border-muted-foreground/30 inline-block h-4 w-4 animate-spin rounded-full border-2 border-t-muted-foreground"
						></span>
						Loading crash history...
					</div>
				{:else if crashRecords.length === 0}
					<div class="border-border/60 rounded-lg border bg-card p-6 text-center">
						<p class="text-muted-foreground/60 text-[13px]">No crashes recorded. That's good!</p>
					</div>
				{:else}
					<div class="space-y-3">
						{#each crashRecords as crash (crash.crashId)}
							{@const status =
								crash.fullLogSent || crash.manuallyReported
									? 'sent'
									: crash.fullLogDeclined
										? 'declined'
										: crash.basicReported
											? 'basic'
											: 'none'}
							<div class="border-border/60 overflow-hidden rounded-lg border bg-card">
								<div class="p-4">
									<!-- Header -->
									<div class="mb-2 flex items-center justify-between">
										<div class="flex items-center gap-2">
											<span
												class="inline-block h-2 w-2 rounded-full {status === 'sent'
													? 'bg-emerald-400'
													: status === 'basic'
														? 'bg-amber-400'
														: status === 'declined'
															? 'bg-red-400/60'
															: 'bg-muted-foreground/30'}"
											></span>
											<span class="text-muted-foreground/70 font-mono text-[12px]"
												>{crash.crashType || 'Crash'}</span
											>
										</div>
										<span class="text-muted-foreground/50 text-[11px]">
											{new Date(crash.timestamp).toLocaleDateString(undefined, {
												month: 'short',
												day: 'numeric',
												hour: '2-digit',
												minute: '2-digit'
											})}
										</span>
									</div>

									<!-- Error message -->
									<p
										class="mb-3 line-clamp-3 break-all font-mono text-[12px] leading-relaxed text-red-400/80"
									>
										{crash.errorMessage}
									</p>

									<!-- Status & Action -->
									<div class="flex items-center justify-between">
										<span class="text-muted-foreground/50 text-[11px]">
											{#if status === 'sent'}
												Full report sent
											{:else if status === 'basic'}
												Basic report sent
											{:else if status === 'declined'}
												Full log not sent
											{:else}
												Not reported
											{/if}
										</span>

										{#if status !== 'sent'}
											<button
												class="border-border/60 rounded-md border px-3 py-1.5 text-[12px] text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
												onclick={() => handleReportCrash(crash.crashId)}
												disabled={reportingCrashId === crash.crashId}
											>
												{#if reportingCrashId === crash.crashId}
													Sending...
												{:else}
													Send Full Report
												{/if}
											</button>
										{/if}
									</div>
								</div>
							</div>
						{/each}
					</div>

					<p class="text-muted-foreground/40 mt-4 text-[11px]">
						Can't send from here? Share crash details on our <a
							href="https://discord.gg/betide"
							target="_blank"
							rel="noopener"
							class="underline hover:text-foreground">Discord</a
						>.
					</p>
				{/if}
			{:else if $settingsTab === 'notifications'}
				<NotificationsPanel bind:this={notifPanel} />
			{:else}
				<h2 class="mb-1 text-[18px] font-medium text-foreground">
					{tabs.find((t) => t.id === $settingsTab)?.label ?? $t('settings')}
				</h2>
				<p class="text-muted-foreground/60 text-[13px]">{$t('coming_soon')}</p>
			{/if}
		</div>
	</div>
</div>

<style>
	@media (max-width: 720px) {
		.settings-shell {
			flex-direction: column;
		}

		.settings-sidebar {
			display: none;
		}

		.settings-mobile-header {
			display: flex;
		}

		.settings-content {
			padding: 1rem;
		}
	}
</style>
