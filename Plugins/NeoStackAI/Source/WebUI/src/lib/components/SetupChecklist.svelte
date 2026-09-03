<script lang="ts">
	import { onMount } from 'svelte';
	import Icon from '$lib/components/Icon.svelte';
	import NeoStackSignInButton from '$lib/components/NeoStackSignInButton.svelte';
	import {
		AlertCircleIcon,
		CheckmarkCircle02Icon,
		Link01Icon,
		RefreshIcon,
		UserIcon
	} from '@hugeicons/core-free-icons';
	import {
		getEntitlementStatus,
		getMcpConnectionInfo,
		getPrerequisiteStatus,
		getProviderSettings,
		type EntitlementStatus,
		type McpConnectionInfo,
		type PrerequisiteStatus,
		type ProviderSettings
	} from '$lib/bridge.js';
	import { neostackAuth } from '$lib/stores/neostackAuth.js';

	type ChecklistState = 'ready' | 'warning' | 'action' | 'loading';
	type ChecklistItem = {
		title: string;
		description: string;
		state: ChecklistState;
		detail?: string;
	};

	let entitlement = $state<EntitlementStatus | null>(null);
	let providers = $state<ProviderSettings | null>(null);
	let prerequisites = $state<PrerequisiteStatus | null>(null);
	let mcp = $state<McpConnectionInfo | null>(null);
	let isLoading = $state(false);
	let loadError = $state('');

	const neostackSignedIn = $derived($neostackAuth.status === 'signedIn');
	const configuredProviders = $derived(
		providers?.providers.filter(
			(provider) => provider.configured || provider.hasApiKey || !provider.requiresApiKey
		) ?? []
	);
	const hasChatRuntime = $derived(configuredProviders.length > 0);
	const hasNodeRuntime = $derived(!!prerequisites?.node?.found || !!prerequisites?.npx?.found);

	const checklist = $derived.by((): ChecklistItem[] => [
		{
			title: 'Connect NeoStack',
			description:
				'Used for subscription checks, NeoStack Cloud chat, extensions, and remote access.',
			state:
				neostackSignedIn || entitlement?.entitled
					? 'ready'
					: // 'network' means we couldn't reach NeoStack, not that the
						// user still has to do something — the plugin retries on
						// its own, so this is pending, never an action item.
						entitlement?.status === 'unknown' ||
							entitlement?.status === 'network' ||
							$neostackAuth.unreachable
							? 'loading'
							: 'action',
			detail: neostackSignedIn
				? 'Signed in to NeoStack.'
				: entitlement?.status === 'network' || $neostackAuth.unreachable
					? 'Couldn’t reach NeoStack — retrying automatically. Your licence is unaffected.'
					: 'Sign in with NeoStack to unlock the easiest path.'
		},
		{
			title: 'Choose how chat runs',
			description: 'Use NeoStack Cloud for the simplest setup, or configure a local/BYOK provider.',
			state: hasChatRuntime ? 'ready' : providers ? 'action' : 'loading',
			detail: hasChatRuntime
				? `${configuredProviders.length} chat provider${configuredProviders.length === 1 ? '' : 's'} ready.`
				: 'Open Settings > Chat & Agents > Chat Providers and configure NeoStack Cloud, OpenRouter, Ollama, or a custom endpoint.'
		},
		{
			title: 'Verify project tools',
			description: 'Confirms the Unreal MCP server is reachable for agents and external clients.',
			state: mcp?.isRunning ? 'ready' : mcp ? 'warning' : 'loading',
			detail: mcp?.isRunning
				? `MCP server is running on port ${mcp.port}.`
				: 'MCP endpoint is not available yet. Restart the editor if it stays offline.'
		},
		{
			title: 'Check local prerequisites',
			description:
				'Needed only for external ACP agents such as Claude Code, Codex, or Copilot CLI.',
			state: hasNodeRuntime ? 'ready' : prerequisites ? 'warning' : 'loading',
			detail: hasNodeRuntime
				? 'Node.js/npx is available for adapter-based agents.'
				: 'Install Node.js if you plan to run external ACP agents.'
		}
	]);

	const allReady = $derived(checklist.every((item) => item.state === 'ready'));

	async function refresh() {
		if (isLoading) return;
		isLoading = true;
		loadError = '';
		try {
			const [nextEntitlement, nextProviders, nextMcp, nextPrerequisites] = await Promise.all([
				getEntitlementStatus(),
				getProviderSettings(),
				getMcpConnectionInfo(),
				getPrerequisiteStatus()
			]);
			entitlement = nextEntitlement;
			providers = nextProviders;
			mcp = nextMcp;
			prerequisites = nextPrerequisites;
		} catch (error) {
			console.warn('Failed to load setup checklist:', error);
			loadError = error instanceof Error ? error.message : 'Could not load setup status.';
		} finally {
			isLoading = false;
		}
	}

	function stateClass(state: ChecklistState): string {
		if (state === 'ready') return 'border-emerald-500/25 bg-emerald-500/[0.04]';
		if (state === 'action') return 'border-amber-500/25 bg-amber-500/[0.05]';
		if (state === 'warning') return 'border-sky-500/25 bg-sky-500/[0.04]';
		return 'border-border/60 bg-card/60';
	}

	function iconClass(state: ChecklistState): string {
		if (state === 'ready') return 'text-emerald-400';
		if (state === 'action') return 'text-amber-400';
		if (state === 'warning') return 'text-sky-400';
		return 'text-muted-foreground/50';
	}

	onMount(() => {
		refresh();
	});
</script>

<div class="border-border/60 bg-card/70 rounded-2xl border p-5">
	<div class="flex flex-wrap items-start justify-between gap-4">
		<div>
			<div class="flex items-center gap-2">
				<Icon icon={UserIcon} size={17} strokeWidth={1.6} class="text-[var(--ue-accent)]" />
				<h2 class="text-[16px] font-medium text-foreground">Setup Checklist</h2>
			</div>
			<p class="text-muted-foreground/65 mt-1 max-w-2xl text-[12.5px] leading-relaxed">
				Get to a first successful chat by connecting NeoStack AI, choosing a chat runtime, and
				verifying project tools.
			</p>
		</div>
		<button
			class="border-border/60 inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[12px] text-foreground transition-colors hover:bg-accent disabled:opacity-50"
			onclick={refresh}
			disabled={isLoading}
		>
			<Icon icon={RefreshIcon} size={13} class={isLoading ? 'animate-spin' : ''} />
			Refresh
		</button>
	</div>

	{#if loadError}
		<div
			class="mt-4 rounded-md border border-red-500/25 bg-red-500/[0.05] px-3 py-2 text-[12px] text-red-300"
		>
			{loadError}
		</div>
	{/if}

	<div class="mt-4 grid gap-3 md:grid-cols-2">
		{#each checklist as item (item.title)}
			<div class={`rounded-xl border p-3 ${stateClass(item.state)}`}>
				<div class="flex items-start gap-3">
					{#if item.state === 'ready'}
						<Icon
							icon={CheckmarkCircle02Icon}
							size={17}
							strokeWidth={1.7}
							class={`mt-0.5 ${iconClass(item.state)}`}
						/>
					{:else if item.state === 'loading'}
						<span
							class="border-muted-foreground/25 border-t-muted-foreground/70 mt-1 inline-block h-4 w-4 animate-spin rounded-full border-2"
						></span>
					{:else}
						<Icon
							icon={AlertCircleIcon}
							size={17}
							strokeWidth={1.7}
							class={`mt-0.5 ${iconClass(item.state)}`}
						/>
					{/if}
					<div class="min-w-0">
						<h3 class="text-[13px] font-medium text-foreground">{item.title}</h3>
						<p class="text-muted-foreground/60 mt-1 text-[11.5px] leading-relaxed">
							{item.description}
						</p>
						{#if item.detail}
							<p class="text-muted-foreground/50 mt-2 text-[11px] leading-relaxed">{item.detail}</p>
						{/if}
					</div>
				</div>
			</div>
		{/each}
	</div>

	<div
		class="border-border/50 mt-4 flex flex-wrap items-center justify-between gap-3 border-t pt-4"
	>
		<div
			class="flex items-center gap-2 text-[12px] {allReady
				? 'text-emerald-300/90'
				: 'text-muted-foreground/65'}"
		>
			<Icon icon={allReady ? CheckmarkCircle02Icon : Link01Icon} size={15} strokeWidth={1.6} />
			{allReady ? 'Ready to chat.' : 'Finish the action items above, then start a new chat.'}
		</div>
		{#if !neostackSignedIn}
			<NeoStackSignInButton label="Connect NeoStack" variant="secondary" onsuccess={refresh} />
		{/if}
	</div>
</div>
