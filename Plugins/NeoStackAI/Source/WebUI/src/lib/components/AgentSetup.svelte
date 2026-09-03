<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import NeoStackSignInButton from '$lib/components/NeoStackSignInButton.svelte';
	import {
		Alert02Icon,
		Tick02Icon,
		Cancel01Icon,
		Download04Icon,
		Copy01Icon,
		Settings02Icon,
		ReloadIcon,
		Key01Icon,
		Login01Icon
	} from '@hugeicons/core-free-icons';
	import { copyToClipboard, openUrl, openPluginSettings, restartEditor } from '$lib/bridge.js';
	import { type Agent } from '$lib/stores/agents.js';
	import {
		setupState,
		setupProgress,
		setupError,
		setupInstallInfo,
		startInstall,
		recheckStatus,
		exitSetup
	} from '$lib/stores/setup.js';

	let { agent }: { agent: Agent } = $props();

	let copied = $state(false);
	let copiedError = $state(false);
	const isNeoStackCloud = $derived(
		[agent.registryId, agent.id].some((id) => id?.trim().toLowerCase() === 'neostack') ||
			agent.name.trim().toLowerCase() === 'neostack cloud'
	);

	function parseColorToRgb(color: string): { r: number; g: number; b: number } | null {
		const value = color.trim().toLowerCase();

		if (value.startsWith('#')) {
			const hex = value.slice(1);
			if (hex.length === 3) {
				const r = parseInt(hex[0] + hex[0], 16);
				const g = parseInt(hex[1] + hex[1], 16);
				const b = parseInt(hex[2] + hex[2], 16);
				return { r, g, b };
			}
			if (hex.length === 6) {
				const r = parseInt(hex.slice(0, 2), 16);
				const g = parseInt(hex.slice(2, 4), 16);
				const b = parseInt(hex.slice(4, 6), 16);
				return { r, g, b };
			}
		}

		const rgbMatch = value.match(/^rgba?\(([^)]+)\)$/);
		if (rgbMatch) {
			const parts = rgbMatch[1].split(',').map((part) => Number.parseFloat(part.trim()));
			if (parts.length >= 3 && parts.slice(0, 3).every((num) => Number.isFinite(num))) {
				return {
					r: Math.max(0, Math.min(255, parts[0])),
					g: Math.max(0, Math.min(255, parts[1])),
					b: Math.max(0, Math.min(255, parts[2]))
				};
			}
		}

		return null;
	}

	function isLightColor(color: string): boolean {
		const rgb = parseColorToRgb(color);
		if (!rgb) return false;
		const luminance = (0.299 * rgb.r + 0.587 * rgb.g + 0.114 * rgb.b) / 255;
		return luminance >= 0.65;
	}

	function primaryTextClass(color: string): string {
		return isLightColor(color) ? 'text-[#111827]' : 'text-white';
	}

	async function handleCopyCommand() {
		const command = $setupInstallInfo?.installCommand;
		if (command) {
			await copyToClipboard(command);
			copied = true;
			setTimeout(() => (copied = false), 2000);
		}
	}

	async function handleCopyError() {
		if ($setupError) {
			await copyToClipboard($setupError);
			copiedError = true;
			setTimeout(() => (copiedError = false), 2000);
		}
	}

	async function handleDownload() {
		const url = $setupInstallInfo?.installUrl;
		if (url) {
			await openUrl(url);
		}
	}

	async function handleOpenSettings() {
		await openPluginSettings();
	}

	async function handleRestart() {
		await restartEditor();
	}
</script>

<div class="flex flex-1 flex-col items-center justify-center px-6">
	<div class="flex w-full max-w-md flex-col items-center gap-6">
		{#if $setupState === 'idle'}
			<!-- ─── Idle: Agent not set up ─── -->
			{#if agent.iconUrl}
				<span style="color: {agent.color}; opacity: 0.5;">
					<img src={agent.iconUrl} alt="" class="h-14 w-14 opacity-70 dark:invert" />
				</span>
			{:else}
				<span
					class="flex h-14 w-14 items-center justify-center rounded-xl text-lg font-bold text-white"
					style="background-color: {agent.color}; opacity: 0.7;"
				>
					{agent.letter}
				</span>
			{/if}

			<div class="flex flex-col items-center gap-2 text-center">
				<h2 class="text-foreground/80 text-lg font-medium">{agent.name} is not set up</h2>
				<p class="text-muted-foreground/50 max-w-xs text-[13px] leading-relaxed">
					{agent.name} needs to be installed before you can start a conversation.
				</p>
				{#if $setupError}
					<p class="max-w-xs text-[12px] leading-relaxed text-amber-400/70">{$setupError}</p>
				{/if}
			</div>

			{#if $setupInstallInfo?.installCommand}
				<div class="w-full max-w-sm">
					<p class="text-muted-foreground/40 mb-2 text-[12px]">Install command:</p>
					<div class="relative rounded-lg bg-surface-sunken p-3">
						<pre
							class="overflow-x-auto pr-10 text-[12px] leading-relaxed text-emerald-400/80">{$setupInstallInfo.installCommand}</pre>
						<button
							class="text-muted-foreground/40 hover:text-muted-foreground/70 absolute right-2 top-2 rounded-md p-1.5 transition-colors hover:bg-white/5"
							onclick={handleCopyCommand}
							title="Copy command"
						>
							{#if copied}
								<Icon icon={Tick02Icon} size={14} strokeWidth={2} class="text-emerald-400" />
							{:else}
								<Icon icon={Copy01Icon} size={14} strokeWidth={1.5} />
							{/if}
						</button>
					</div>
				</div>
			{/if}

			<button
				class={`rounded-xl px-6 py-2.5 text-[14px] font-medium transition-all hover:brightness-110 ${primaryTextClass(agent.color)}`}
				style="background-color: {agent.color};"
				onclick={() => startInstall(agent.name)}
			>
				Set up {agent.shortName}
			</button>
		{:else if $setupState === 'checking'}
			<!-- ─── Checking prerequisites ─── -->
			<div class="flex flex-col items-center gap-4">
				<div
					class="border-muted-foreground/20 border-t-muted-foreground/60 h-10 w-10 animate-spin rounded-full border-2"
				></div>
				<p class="text-muted-foreground/60 text-[14px]">
					{$setupProgress || 'Checking prerequisites...'}
				</p>
			</div>
		{:else if $setupState === 'installing'}
			<!-- ─── Installing ─── -->
			<div class="flex flex-col items-center gap-4">
				{#if agent.iconUrl}
					<span style="color: {agent.color}; opacity: 0.4;">
						<img src={agent.iconUrl} alt="" class="h-10 w-10 opacity-70 dark:invert" />
					</span>
				{/if}
				<div
					class="border-muted-foreground/20 border-t-muted-foreground/60 h-10 w-10 animate-spin rounded-full border-2"
				></div>
				<div class="flex flex-col items-center gap-1.5">
					<p class="text-foreground/70 text-[14px]">Setting up {agent.name}...</p>
					<p class="text-muted-foreground/40 max-w-xs text-center text-[12px]">{$setupProgress}</p>
				</div>
			</div>
		{:else if $setupState === 'cli_missing'}
			<!-- ─── CLI Required ─── -->
			<div class="flex w-full flex-col items-center gap-5">
				<div class="flex h-12 w-12 items-center justify-center rounded-full bg-amber-500/10">
					<Icon icon={Alert02Icon} size={24} strokeWidth={1.5} class="text-amber-400" />
				</div>

				<div class="flex flex-col items-center gap-2 text-center">
					<h2 class="text-foreground/80 text-lg font-medium">
						{$setupInstallInfo?.baseExecutableName || 'CLI'} Required
					</h2>
					<p class="text-muted-foreground/50 max-w-xs text-[13px] leading-relaxed">
						{#if $setupInstallInfo?.requiresAdapter}
							The adapter is ready, but {agent.name} requires the
						{:else}
							{agent.name} requires the
						{/if}
						<span class="text-foreground/60 font-mono">{$setupInstallInfo?.baseExecutableName}</span
						>
						CLI to be installed on your system.
					</p>
				</div>

				{#if $setupInstallInfo?.installCommand}
					<div class="w-full">
						<p class="text-muted-foreground/40 mb-2 text-[12px]">Run this in your terminal:</p>
						<div class="relative rounded-lg bg-surface-sunken p-3">
							<pre
								class="overflow-x-auto pr-10 text-[13px] leading-relaxed text-emerald-400/80">{$setupInstallInfo.installCommand}</pre>
							<button
								class="text-muted-foreground/40 hover:text-muted-foreground/70 absolute right-2 top-2 rounded-md p-1.5 transition-colors hover:bg-white/5"
								onclick={handleCopyCommand}
								title="Copy command"
							>
								{#if copied}
									<Icon icon={Tick02Icon} size={14} strokeWidth={2} class="text-emerald-400" />
								{:else}
									<Icon icon={Copy01Icon} size={14} strokeWidth={1.5} />
								{/if}
							</button>
						</div>
					</div>
				{/if}

				<div class="flex flex-wrap justify-center gap-2.5">
					{#if $setupInstallInfo?.installUrl}
						<button
							class="border-border/50 bg-secondary/50 text-foreground/70 flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-[13px] transition-colors hover:bg-secondary"
							onclick={handleDownload}
						>
							<Icon icon={Download04Icon} size={14} strokeWidth={1.5} />
							Download Page
						</button>
					{/if}
					<button
						class={`flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-[13px] font-medium transition-all hover:brightness-110 ${primaryTextClass(agent.color)}`}
						style="background-color: {agent.color};"
						onclick={() => recheckStatus(agent.name)}
					>
						<Icon icon={ReloadIcon} size={14} strokeWidth={1.5} />
						Try Again
					</button>
				</div>
			</div>
		{:else if $setupState === 'missing_key'}
			<!-- ─── Account or API Key Required ─── -->
			<div class="flex w-full flex-col items-center gap-5">
				<div class="flex h-12 w-12 items-center justify-center rounded-full bg-amber-500/10">
					<Icon
						icon={isNeoStackCloud ? Login01Icon : Key01Icon}
						size={24}
						strokeWidth={1.5}
						class="text-amber-400"
					/>
				</div>

				<div class="flex flex-col items-center gap-2 text-center">
					{#if isNeoStackCloud}
						<h2 class="text-foreground/80 text-lg font-medium">Sign in to NeoStack</h2>
						<p class="text-muted-foreground/50 max-w-xs text-[13px] leading-relaxed">
							NeoStack Cloud uses your NeoStack account. Sign in securely in your browser — no API
							key needed.
						</p>
					{:else}
						<h2 class="text-foreground/80 text-lg font-medium">API Key Required</h2>
						<p class="text-muted-foreground/50 max-w-xs text-[13px] leading-relaxed">
							{agent.name} requires an API key. Configure it in
							<span class="text-foreground/60"
								>Settings &gt; Chat &amp; Agents &gt; Chat Providers</span
							>.
						</p>
					{/if}
					{#if $setupError && !isNeoStackCloud}
						<p class="max-w-xs text-[12px] leading-relaxed text-amber-400/80">{$setupError}</p>
					{/if}
				</div>

				{#if isNeoStackCloud}
					<NeoStackSignInButton
						label="Sign in with NeoStack"
						variant="primary"
						onsuccess={exitSetup}
					/>
				{:else}
					<div class="flex flex-wrap justify-center gap-2.5">
						<button
							class="border-border/50 bg-secondary/50 text-foreground/70 flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-[13px] transition-colors hover:bg-secondary"
							onclick={handleOpenSettings}
						>
							<Icon icon={Settings02Icon} size={14} strokeWidth={1.5} />
							Open Settings
						</button>
						<button
							class={`flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-[13px] font-medium transition-all hover:brightness-110 ${primaryTextClass(agent.color)}`}
							style="background-color: {agent.color};"
							onclick={() => recheckStatus(agent.name)}
						>
							<Icon icon={ReloadIcon} size={14} strokeWidth={1.5} />
							Check Again
						</button>
					</div>
				{/if}
			</div>
		{:else if $setupState === 'success'}
			<!-- ─── Success ─── -->
			<div class="flex flex-col items-center gap-5">
				<div class="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/10">
					<Icon icon={Tick02Icon} size={28} strokeWidth={2} class="text-emerald-400" />
				</div>

				<div class="flex flex-col items-center gap-2 text-center">
					<h2 class="text-lg font-medium text-emerald-400">{agent.name} is ready!</h2>
					<p class="text-muted-foreground/50 max-w-xs text-[13px] leading-relaxed">
						Please restart the editor to start using {agent.name}. The agent will be available after
						relaunch.
					</p>
				</div>

				<button
					class="border-border/50 bg-secondary/50 text-foreground/70 rounded-lg border px-4 py-2 text-[13px] transition-colors hover:bg-secondary"
					onclick={handleRestart}
				>
					Restart
				</button>
			</div>
		{:else if $setupState === 'error'}
			<!-- ─── Error ─── -->
			<div class="flex w-full flex-col items-center gap-5">
				<div class="flex h-12 w-12 items-center justify-center rounded-full bg-red-500/10">
					<Icon icon={Cancel01Icon} size={24} strokeWidth={1.5} class="text-red-400" />
				</div>

				<div class="flex flex-col items-center gap-2 text-center">
					<h2 class="text-lg font-medium text-red-400">Setup Failed</h2>
				</div>

				{#if $setupError}
					<div class="relative w-full rounded-lg bg-surface-sunken p-3">
						<pre
							class="text-muted-foreground/60 max-h-[160px] overflow-auto text-[12px] leading-relaxed">{$setupError}</pre>
						<button
							class="text-muted-foreground/40 hover:text-muted-foreground/70 absolute right-2 top-2 rounded-md p-1.5 transition-colors hover:bg-white/5"
							onclick={handleCopyError}
							title="Copy error"
						>
							{#if copiedError}
								<Icon icon={Tick02Icon} size={14} strokeWidth={2} class="text-emerald-400" />
							{:else}
								<Icon icon={Copy01Icon} size={14} strokeWidth={1.5} />
							{/if}
						</button>
					</div>
				{/if}

				<div class="flex flex-wrap justify-center gap-2.5">
					<button
						class="border-border/50 bg-secondary/50 text-foreground/70 rounded-lg border px-3.5 py-2 text-[13px] transition-colors hover:bg-secondary"
						onclick={exitSetup}
					>
						Cancel
					</button>
					<button
						class={`flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-[13px] font-medium transition-all hover:brightness-110 ${primaryTextClass(agent.color)}`}
						style="background-color: {agent.color};"
						onclick={() => startInstall(agent.name)}
					>
						<Icon icon={ReloadIcon} size={14} strokeWidth={1.5} />
						Try Again
					</button>
				</div>
			</div>
		{/if}
	</div>
</div>
