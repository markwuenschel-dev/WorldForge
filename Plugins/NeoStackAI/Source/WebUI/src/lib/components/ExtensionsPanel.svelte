<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import ExtensionCard, {
		type ExtensionCardAction,
		type ExtensionCardStatus
	} from '$lib/components/ExtensionCard.svelte';
	import { ArrowReloadHorizontalIcon, PlayIcon, Search01Icon } from '@hugeicons/core-free-icons';
	import {
		getIntegrationSettings,
		restartEditor,
		setIntegrationOverride,
		setIntegrationPluginsEnabled,
		type IntegrationInfo,
		type IntegrationSettingsState
	} from '$lib/bridge.js';
	import { SvelteMap } from 'svelte/reactivity';

	type IntegrationState =
		| 'active'
		| 'manual-disabled'
		| 'plugin-disabled'
		| 'plugin-missing'
		| 'restart'
		| 'failed'
		| 'unavailable';

	type IntegrationGroup = {
		key: string;
		label: string;
		sortOrder: number;
		items: IntegrationInfo[];
	};

	let settings = $state<IntegrationSettingsState>({
		coreApiVersion: 0,
		projectFile: '',
		restartRequired: false,
		integrations: []
	});
	let isLoading = $state(false);
	let hasLoadedOnce = $state(false);
	let busyIntegrationId = $state('');
	let actionError = $state('');
	let searchQuery = $state('');

	let filteredIntegrations = $derived(settings.integrations.filter(matchesSearch));
	let groups = $derived(groupIntegrations(filteredIntegrations));
	let activeCount = $derived(
		settings.integrations.filter((integration) => integrationState(integration) === 'active').length
	);
	let restartCount = $derived(
		settings.integrations.filter((integration) => integrationState(integration) === 'restart')
			.length
	);
	let needsSetupCount = $derived(
		settings.integrations.filter((integration) =>
			['plugin-disabled', 'plugin-missing', 'failed', 'unavailable'].includes(
				integrationState(integration)
			)
		).length
	);

	export async function load() {
		if (isLoading) return;
		isLoading = true;
		actionError = '';
		try {
			settings = await getIntegrationSettings();
		} catch (error) {
			console.warn('Failed to load integration settings:', error);
			actionError = 'Could not load integration status from Unreal Editor.';
		} finally {
			isLoading = false;
			hasLoadedOnce = true;
		}
	}

	function matchesSearch(integration: IntegrationInfo): boolean {
		const query = searchQuery.trim().toLowerCase();
		if (!query) return true;
		return [
			integration.displayName,
			integration.legacyPluginName,
			integration.description,
			integration.agentSummary,
			integration.whenToEnable,
			...(integration.enablesAgentTo ?? []),
			...(integration.dependencies ?? []).map((dependency) => dependency.name)
		]
			.join(' ')
			.toLowerCase()
			.includes(query);
	}

	function groupIntegrations(integrations: IntegrationInfo[]): IntegrationGroup[] {
		const byDomain = new SvelteMap<string, IntegrationGroup>();
		for (const integration of integrations) {
			const key = integration.domain || 'other';
			const group = byDomain.get(key) ?? {
				key,
				label: integration.domainLabel || 'Other integrations',
				sortOrder: integration.sortOrder || 999,
				items: []
			};
			group.sortOrder = Math.min(group.sortOrder, integration.sortOrder || 999);
			group.items.push(integration);
			byDomain.set(key, group);
		}

		return Array.from(byDomain.values())
			.map((group) => ({
				...group,
				items: group.items.sort((a, b) => a.displayName.localeCompare(b.displayName))
			}))
			.sort((a, b) => a.sortOrder - b.sortOrder || a.label.localeCompare(b.label));
	}

	function integrationState(integration: IntegrationInfo): IntegrationState {
		if (integration.hasExplicitProjectEntry) return 'manual-disabled';
		if (integration.dependencies.some((dependency) => !dependency.installed))
			return 'plugin-missing';
		if (integration.restartRequired) return 'restart';
		if (integration.dependencies.some((dependency) => !dependency.enabled))
			return 'plugin-disabled';
		if (integration.runtimeState === 'failed' || integration.runtimeState === 'incompatible') {
			return 'failed';
		}
		if (integration.runtimeState === 'unavailable') return 'unavailable';
		if (integration.activeInSession) return 'active';
		return 'unavailable';
	}

	function cardStatus(state: IntegrationState): ExtensionCardStatus {
		switch (state) {
			case 'active':
				return 'active';
			case 'manual-disabled':
				return 'disabled';
			case 'restart':
				return 'restart';
			case 'failed':
				return 'failed';
			default:
				return 'unavailable';
		}
	}

	function stateLabel(state: IntegrationState): string {
		switch (state) {
			case 'active':
				return 'Active';
			case 'manual-disabled':
				return 'Disabled by manual override';
			case 'plugin-disabled':
				return 'Backing plugin disabled';
			case 'plugin-missing':
				return 'Backing plugin missing';
			case 'restart':
				return 'Restart required';
			case 'failed':
				return 'Load failed';
			case 'unavailable':
				return 'Unavailable in this build';
		}
	}

	function stateMessage(integration: IntegrationInfo): string {
		const state = integrationState(integration);
		if (state === 'plugin-missing') {
			return `Not installed: ${integration.dependencies
				.filter((dependency) => !dependency.installed)
				.map((dependency) => dependency.name)
				.join(', ')}.`;
		}
		if (state === 'plugin-disabled') {
			return `Enable ${integration.dependencies
				.filter((dependency) => dependency.installed && !dependency.enabled)
				.map((dependency) => dependency.name)
				.join(', ')} and restart the editor.`;
		}
		return integration.statusMessage || '';
	}

	async function setAutomaticUse(integration: IntegrationInfo, enabled: boolean) {
		if (busyIntegrationId) return;
		busyIntegrationId = integration.integrationId;
		actionError = '';
		try {
			const result = await setIntegrationOverride(integration.integrationId, !enabled);
			if (!result.success) {
				actionError = result.error || `Could not update ${integration.displayName}.`;
				return;
			}
			await load();
		} catch (error) {
			console.warn('Failed to update integration override:', error);
			actionError = `Could not update ${integration.displayName}.`;
		} finally {
			busyIntegrationId = '';
		}
	}

	async function enableRequiredPlugins(integration: IntegrationInfo) {
		if (busyIntegrationId) return;
		const pluginNames = integration.dependencies
			.filter((dependency) => dependency.installed && !dependency.enabled)
			.map((dependency) => dependency.name);
		if (pluginNames.length === 0) return;

		busyIntegrationId = integration.integrationId;
		actionError = '';
		try {
			const result = await setIntegrationPluginsEnabled(integration.integrationId, true);
			if (!result.success) {
				actionError = result.error || `Could not enable plugins for ${integration.displayName}.`;
				return;
			}
			await load();
		} catch (error) {
			console.warn('Failed to enable backing plugins:', error);
			actionError = `Could not enable plugins for ${integration.displayName}.`;
		} finally {
			busyIntegrationId = '';
		}
	}

	function actionsFor(integration: IntegrationInfo): ExtensionCardAction[] {
		const state = integrationState(integration);
		const busy = busyIntegrationId === integration.integrationId;
		if (state === 'manual-disabled') {
			return [
				{
					label: busy ? 'Saving…' : 'Use automatically',
					tone: 'primary',
					disabled: busy,
					onclick: () => setAutomaticUse(integration, true)
				}
			];
		}

		const actions: ExtensionCardAction[] = [];
		if (state === 'plugin-disabled') {
			actions.push({
				label: busy ? 'Saving…' : 'Enable required plugins',
				tone: 'warning',
				disabled: busy,
				onclick: () => enableRequiredPlugins(integration)
			});
		}
		if (state !== 'plugin-missing') {
			actions.push({
				label: busy ? 'Saving…' : 'Disable integration',
				tone: 'neutral',
				disabled: busy,
				onclick: () => setAutomaticUse(integration, false)
			});
		}
		return actions;
	}
</script>

<div class="mb-5 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
	<div class="min-w-0">
		<h2 class="text-[18px] font-medium text-foreground">Integrations</h2>
		<p class="text-muted-foreground/60 mt-1 max-w-[48rem] text-[12.5px] leading-relaxed">
			NeoStackAI detects the Unreal systems your project already uses and loads their tools
			automatically. Nothing here installs or downloads plugins.
		</p>
	</div>

	<button
		class="border-border/55 inline-flex shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-[12px] text-muted-foreground transition-colors hover:border-border hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
		onclick={load}
		disabled={isLoading || !!busyIntegrationId}
		aria-label="Refresh integration status"
	>
		<Icon icon={ArrowReloadHorizontalIcon} size={12} strokeWidth={1.5} />
		Refresh
	</button>
</div>

<div class="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
	<div class="border-border/55 rounded-lg border bg-card px-3.5 py-3">
		<div class="text-muted-foreground/45 text-[10px] font-medium uppercase tracking-[0.08em]">
			Active
		</div>
		<div class="mt-1 text-[20px] font-medium tabular-nums text-foreground">
			{activeCount}
		</div>
	</div>
	<div class="rounded-lg border border-amber-400/20 bg-amber-500/[0.025] px-3.5 py-3">
		<div class="text-muted-foreground/45 text-[10px] font-medium uppercase tracking-[0.08em]">
			Ready after restart
		</div>
		<div class="mt-1 text-[20px] font-medium tabular-nums text-foreground">
			{restartCount}
		</div>
	</div>
	<div class="border-border/55 rounded-lg border bg-card px-3.5 py-3">
		<div class="text-muted-foreground/45 text-[10px] font-medium uppercase tracking-[0.08em]">
			Needs setup
		</div>
		<div class="mt-1 text-[20px] font-medium tabular-nums text-foreground">
			{needsSetupCount}
		</div>
	</div>
</div>

{#if settings.restartRequired}
	<div
		class="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-400/25 bg-amber-500/[0.035] px-3.5 py-3"
	>
		<div>
			<p class="text-[12.5px] font-medium text-foreground">Restart required</p>
			<p class="text-muted-foreground/65 mt-0.5 text-[11.5px]">
				Your integration changes will apply when Unreal Editor restarts.
			</p>
		</div>
		<button
			class="inline-flex items-center gap-1.5 rounded-md border border-amber-400/35 px-3 py-1.5 text-[11.5px] text-amber-100/90 transition-colors hover:bg-amber-500/10"
			onclick={restartEditor}
		>
			<Icon icon={PlayIcon} size={11} strokeWidth={1.8} />
			Restart editor
		</button>
	</div>
{/if}

<label class="relative mb-5 block">
	<span class="sr-only">Search integrations</span>
	<span
		class="text-muted-foreground/40 pointer-events-none absolute inset-y-0 left-3 flex items-center"
	>
		<Icon icon={Search01Icon} size={14} strokeWidth={1.5} />
	</span>
	<input
		class="border-border/55 placeholder:text-muted-foreground/35 focus:border-foreground/40 w-full rounded-md border bg-transparent py-2 pl-9 pr-3 text-[13px] text-foreground outline-none"
		placeholder="Search integrations or Unreal plugins…"
		bind:value={searchQuery}
	/>
</label>

{#if actionError}
	<div
		class="mb-4 rounded-md border border-red-400/25 bg-red-500/[0.035] px-3 py-2 text-[12px] text-red-200/85"
	>
		{actionError}
	</div>
{/if}

{#if isLoading && !hasLoadedOnce}
	<div
		class="border-border/50 text-muted-foreground/55 rounded-lg border px-4 py-10 text-center text-[12.5px]"
	>
		Reading integration status…
	</div>
{:else if settings.integrations.length === 0 && hasLoadedOnce}
	<div class="border-border/50 rounded-lg border px-4 py-10 text-center">
		<p class="text-foreground/80 text-[13px]">No integration manifest was returned.</p>
		<p class="text-muted-foreground/50 mt-1 text-[11.5px]">
			Refresh after NeoStackAI finishes starting up.
		</p>
	</div>
{:else if filteredIntegrations.length === 0}
	<div
		class="border-border/50 text-muted-foreground/55 rounded-lg border px-4 py-10 text-center text-[12.5px]"
	>
		No integrations match “{searchQuery.trim()}”.
	</div>
{:else}
	<div class="space-y-6">
		{#each groups as group (group.key)}
			<section aria-labelledby={`integration-group-${group.key}`}>
				<div class="mb-2 flex items-center gap-2">
					<h3
						id={`integration-group-${group.key}`}
						class="text-muted-foreground/55 text-[11px] font-medium uppercase tracking-[0.08em]"
					>
						{group.label}
					</h3>
					<span class="text-muted-foreground/35 text-[10.5px] tabular-nums"
						>{group.items.length}</span
					>
					<div class="bg-border/40 h-px flex-1"></div>
				</div>

				<div class="space-y-2.5">
					{#each group.items as integration (integration.integrationId)}
						{@const state = integrationState(integration)}
						<ExtensionCard
							name={integration.displayName}
							pluginName={integration.legacyPluginName}
							vendor={integration.vendor}
							summary={integration.agentSummary || integration.description}
							enablesAgentTo={integration.enablesAgentTo}
							whenToEnable={integration.whenToEnable}
							dependencies={integration.dependencies}
							status={cardStatus(state)}
							statusLabel={stateLabel(state)}
							statusMessage={stateMessage(integration)}
							actions={actionsFor(integration)}
							details={[
								{ label: 'Integration', value: integration.integrationId },
								{ label: 'State', value: stateLabel(state) }
							]}
						/>
					{/each}
				</div>
			</section>
		{/each}
	</div>
{/if}
