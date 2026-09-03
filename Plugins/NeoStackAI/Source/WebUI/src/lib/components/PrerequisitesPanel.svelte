<script lang="ts">
	import { onMount } from 'svelte';
	import {
		getPrerequisiteStatus,
		type PrerequisiteStatus,
		type PrerequisiteTool,
		openUrl
	} from '$lib/bridge.js';
	import { CheckmarkCircle02Icon, Alert02Icon, RefreshIcon } from '@hugeicons/core-free-icons';
	import Icon from '$lib/components/Icon.svelte';

	let status = $state<PrerequisiteStatus | null>(null);
	let isLoading = $state(false);
	let errorMessage = $state('');

	const tools: Array<{
		key: keyof PrerequisiteStatus;
		name: string;
		required: boolean;
		description: string;
		installUrl: string;
		installTip: string;
	}> = [
		{
			key: 'node',
			name: 'Node.js',
			required: true,
			description: 'Required for most ACP agents (npx)',
			installUrl: 'https://nodejs.org/',
			installTip: 'Download from nodejs.org or run: brew install node'
		},
		{
			key: 'npm',
			name: 'npm',
			required: false,
			description: 'Comes with Node.js',
			installUrl: '',
			installTip: 'Included with Node.js'
		},
		{
			key: 'npx',
			name: 'npx',
			required: false,
			description: 'Runs ACP agents on demand',
			installUrl: '',
			installTip: 'Included with Node.js'
		},
		{
			key: 'git',
			name: 'Git',
			required: false,
			description: 'Used by some agents for source control',
			installUrl: 'https://git-scm.com/',
			installTip: 'Download from git-scm.com or run: brew install git'
		},
		{
			key: 'uv',
			name: 'uv',
			required: false,
			description: 'Required for Python-based agents (uvx)',
			installUrl: 'https://docs.astral.sh/uv/',
			installTip: 'Run: curl -LsSf https://astral.sh/uv/install.sh | sh'
		},
		{
			key: 'bun',
			name: 'Bun',
			required: false,
			description: 'Alternative JS runtime',
			installUrl: 'https://bun.sh/',
			installTip: 'Run: curl -fsSL https://bun.sh/install | bash'
		}
	];

	async function checkPrerequisites() {
		isLoading = true;
		errorMessage = '';
		try {
			status = await getPrerequisiteStatus();
		} catch (e) {
			console.warn('Failed to check prerequisites:', e);
			errorMessage =
				'Could not check local prerequisites. Reopen Settings or restart the editor if this keeps happening.';
		} finally {
			isLoading = false;
		}
	}

	onMount(() => {
		checkPrerequisites();
	});

	function getTool(key: keyof PrerequisiteStatus): PrerequisiteTool {
		if (!status) return { found: false, path: '' };
		return status[key] ?? { found: false, path: '' };
	}
</script>

<div class="flex flex-col gap-3">
	<div class="flex items-center justify-between">
		<div>
			<h3 class="text-[14px] font-medium text-foreground">Prerequisites</h3>
			<p class="text-muted-foreground/60 text-[12px]">Tools needed to run ACP agents.</p>
		</div>
		<button
			class="border-border/60 hover:bg-accent/20 flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
			onclick={checkPrerequisites}
			disabled={isLoading}
		>
			<Icon icon={RefreshIcon} size={12} class={isLoading ? 'animate-spin' : ''} />
			Recheck
		</button>
	</div>

	{#if errorMessage}
		<div
			class="rounded-md border border-red-500/25 bg-red-500/[0.05] px-3 py-2 text-[12px] text-red-300"
		>
			{errorMessage}
		</div>
	{:else if !status}
		<div class="text-muted-foreground/50 flex items-center gap-2 py-4 text-[12px]">
			<span
				class="border-muted-foreground/30 inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-t-muted-foreground"
			></span>
			Checking...
		</div>
	{:else}
		<div class="border-border/60 divide-border/40 divide-y rounded-lg border bg-card">
			{#each tools as tool (tool.key)}
				{@const info = getTool(tool.key)}
				<div class="flex items-center gap-3 px-4 py-2.5">
					<!-- Status icon -->
					{#if info.found}
						<Icon icon={CheckmarkCircle02Icon} size={16} class="shrink-0 text-emerald-400" />
					{:else}
						<Icon
							icon={Alert02Icon}
							size={16}
							class="{tool.required ? 'text-red-400' : 'text-muted-foreground/30'} shrink-0"
						/>
					{/if}

					<!-- Name + description -->
					<div class="min-w-0 flex-1">
						<div class="flex items-baseline gap-2">
							<span class="text-[13px] font-medium text-foreground">{tool.name}</span>
							{#if tool.required}
								<span class="text-[10px] text-amber-400">Required</span>
							{/if}
						</div>
						<p class="text-muted-foreground/50 truncate text-[11px]">{tool.description}</p>
					</div>

					<!-- Version / Install link -->
					<div class="shrink-0 text-right">
						{#if info.found}
							<span class="text-[11px] text-emerald-400/80">{info.version || 'Found'}</span>
							{#if info.path}
								<p
									class="text-muted-foreground/30 max-w-[200px] truncate text-[10px]"
									title={info.path}
								>
									{info.path}
								</p>
							{/if}
						{:else if tool.installUrl}
							<button
								class="text-[11px] text-[var(--ue-accent)] hover:underline"
								onclick={() => openUrl(tool.installUrl)}
							>
								Install
							</button>
							<p class="text-muted-foreground/30 text-[10px]">{tool.installTip}</p>
						{:else}
							<span class="text-muted-foreground/30 text-[11px]">Not found</span>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
