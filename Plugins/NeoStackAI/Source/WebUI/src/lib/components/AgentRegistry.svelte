<script lang="ts">
	import { onMount } from 'svelte';
	import {
		registryAgents,
		registryLoaded,
		registryLoading,
		installingAgents,
		updatingAgents,
		loadRegistry,
		refreshRegistryData,
		installAgent,
		uninstallAgent,
		updateAgent
	} from '$lib/stores/registry.js';
	import type { RegistryAgent } from '$lib/bridge.js';
	import { toast } from 'svelte-sonner';
	import {
		Download04Icon,
		RefreshIcon,
		CheckmarkCircle02Icon,
		Globe02Icon
	} from '@hugeicons/core-free-icons';
	import Icon from '$lib/components/Icon.svelte';

	let searchQuery = $state('');
	let showInstalled = $state(true);
	let showNotInstalled = $state(true);

	let filteredAgents = $derived.by(() => {
		let agents = $registryAgents;

		// Filter by install status
		if (!showInstalled || !showNotInstalled) {
			agents = agents.filter((a) => {
				if (a.isInstalled && !showInstalled) return false;
				if (!a.isInstalled && !showNotInstalled) return false;
				return true;
			});
		}

		// Filter by search
		if (searchQuery.trim()) {
			const q = searchQuery.toLowerCase();
			agents = agents.filter(
				(a) =>
					a.name.toLowerCase().includes(q) ||
					a.id.toLowerCase().includes(q) ||
					a.description.toLowerCase().includes(q)
			);
		}

		// Sort: installed first, then alphabetical
		return agents.sort((a, b) => {
			if (a.isInstalled !== b.isInstalled) return a.isInstalled ? -1 : 1;
			return a.name.localeCompare(b.name);
		});
	});

	let installedCount = $derived($registryAgents.filter((a) => a.isInstalled).length);
	let totalCount = $derived($registryAgents.length);

	onMount(() => {
		if (!$registryLoaded) {
			loadRegistry();
		}
	});

	function handleInstall(agent: RegistryAgent) {
		installAgent(agent.id, 'auto').catch((e: unknown) => {
			toast.error(`Failed to install ${agent.name}`, {
				description: e instanceof Error ? e.message : String(e)
			});
		});
	}

	function handleUninstall(agent: RegistryAgent) {
		uninstallAgent(agent.id);
	}

	function handleUpdate(agent: RegistryAgent) {
		updateAgent(agent.id);
	}
</script>

<div class="flex flex-col gap-4">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<div>
			<h2 class="mb-1 text-[18px] font-medium text-foreground">ACP Agent Registry</h2>
			<p class="text-muted-foreground/60 text-[13px]">
				{installedCount} installed of {totalCount} available agents.
			</p>
		</div>
		<button
			class="border-border/60 hover:bg-accent/20 flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground"
			onclick={() => refreshRegistryData()}
			disabled={$registryLoading}
		>
			<Icon icon={RefreshIcon} size={14} class={$registryLoading ? 'animate-spin' : ''} />
			Refresh
		</button>
	</div>

	<!-- Search + Filters -->
	<div class="flex gap-2">
		<input
			type="text"
			placeholder="Search agents..."
			bind:value={searchQuery}
			class="border-border/60 placeholder:text-muted-foreground/40 focus:border-foreground/30 flex-1 rounded-md border bg-transparent px-3 py-2 text-[13px] text-foreground focus:outline-none"
		/>
		<button
			class="rounded-md border px-3 py-2 text-[11px] transition-colors {showInstalled &&
			showNotInstalled
				? 'border-border/60 hover:bg-accent/20 text-muted-foreground'
				: showInstalled
					? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
					: 'border-border/60 text-muted-foreground/40'}"
			onclick={() => {
				if (showInstalled && showNotInstalled) {
					showNotInstalled = false;
				} else if (showInstalled) {
					showInstalled = false;
					showNotInstalled = true;
				} else {
					showInstalled = true;
					showNotInstalled = true;
				}
			}}
		>
			{showInstalled && showNotInstalled ? 'All' : showInstalled ? 'Installed' : 'Not Installed'}
		</button>
	</div>

	<!-- Loading -->
	{#if $registryLoading && !$registryLoaded}
		<div class="text-muted-foreground/50 flex items-center justify-center gap-2 py-12">
			<span
				class="border-muted-foreground/30 inline-block h-4 w-4 animate-spin rounded-full border-2 border-t-muted-foreground"
			></span>
			Loading registry...
		</div>
	{:else if filteredAgents.length === 0}
		<div class="text-muted-foreground/40 py-12 text-center text-[13px]">
			{searchQuery ? 'No agents match your search.' : 'No agents available.'}
		</div>
	{:else}
		<!-- Agent Grid -->
		<div class="grid gap-3">
			{#each filteredAgents as agent (agent.id)}
				{@const isInstalling = $installingAgents.has(agent.id)}
				{@const isUpdating = $updatingAgents.has(agent.id)}
				<div
					class="group rounded-lg border p-4 transition-colors {agent.isInstalled
						? 'border-border/60 bg-card'
						: 'border-border/30 bg-card/50'}"
				>
					<div class="flex items-start gap-3">
						<!-- Icon -->
						<div
							class="border-border/40 flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-background"
						>
							{#if agent.icon && agent.icon.startsWith('http')}
								<img src={agent.icon} alt="" class="h-5 w-5 opacity-70 dark:invert" />
							{:else}
								<span class="text-muted-foreground/40 text-[14px] font-semibold">
									{agent.name.charAt(0)}
								</span>
							{/if}
						</div>

						<!-- Info -->
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2">
								<h3 class="text-[14px] font-medium text-foreground">{agent.name}</h3>
								<span
									class="bg-muted/50 rounded-full px-2 py-0.5 text-[10px] text-muted-foreground"
								>
									v{agent.version}
								</span>
								{#if agent.isInstalled}
									<span
										class="flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400"
									>
										<Icon icon={CheckmarkCircle02Icon} size={10} />
										Installed
									</span>
								{/if}
							</div>
							<p class="text-muted-foreground/70 mt-0.5 line-clamp-2 text-[12px]">
								{agent.description}
							</p>

							<!-- Distribution badges -->
							<div class="mt-2 flex flex-wrap items-center gap-1.5">
								{#if agent.hasBinary}
									<span
										class="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400"
										>Binary</span
									>
								{/if}
								{#if agent.hasNpx}
									<span
										class="rounded bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-medium text-blue-400"
										>npx</span
									>
								{/if}
								{#if agent.hasUvx}
									<span
										class="rounded bg-purple-500/10 px-1.5 py-0.5 text-[10px] font-medium text-purple-400"
										>uvx</span
									>
								{/if}
								{#if agent.license}
									<span class="text-muted-foreground/30 text-[10px]">{agent.license}</span>
								{/if}
							</div>
						</div>

						<!-- Actions -->
						<div class="flex shrink-0 items-center gap-2">
							{#if agent.repository}
								<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- external registry URL -->
								<a
									href={agent.repository}
									target="_blank"
									rel="noopener noreferrer"
									class="text-muted-foreground/40 hover:bg-accent/20 flex items-center justify-center rounded-md p-1.5 transition-colors hover:text-foreground"
									title="View source"
								>
									<Icon icon={Globe02Icon} size={14} />
								</a>
							{/if}

							{#if agent.isInstalled}
								{#if agent.updateAvailable}
									<button
										class="flex items-center gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/20 px-3 py-1.5 text-[12px] font-medium text-amber-400 transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
										onclick={() => handleUpdate(agent)}
										disabled={isUpdating}
									>
										{#if isUpdating}
											<span
												class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-amber-400/30 border-t-amber-400"
											></span>
											Updating...
										{:else}
											<Icon icon={Download04Icon} size={14} />
											Update to {agent.latestVersion}
										{/if}
									</button>
								{/if}
								<button
									class="border-border/60 flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] text-muted-foreground transition-colors hover:border-red-500/30 hover:bg-red-500/10 hover:text-red-400"
									onclick={() => handleUninstall(agent)}
								>
									Remove
								</button>
							{:else}
								<button
									class="flex items-center gap-1.5 rounded-md bg-[var(--ue-accent)] px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
									onclick={() => handleInstall(agent)}
									disabled={isInstalling}
								>
									{#if isInstalling}
										<span
											class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white"
										></span>
										Adding...
									{:else}
										<Icon icon={Download04Icon} size={14} />
										Install
									{/if}
								</button>
							{/if}
						</div>
					</div>
				</div>
			{/each}
		</div>

		<!-- Count -->
		<p class="text-muted-foreground/40 text-[11px]">
			Showing {filteredAgents.length} of {totalCount} agents
		</p>
	{/if}
</div>
