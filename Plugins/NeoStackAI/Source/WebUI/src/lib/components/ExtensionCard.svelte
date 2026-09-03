<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import {
		BulbIcon,
		CheckmarkCircle02Icon,
		InformationCircleIcon
	} from '@hugeicons/core-free-icons';

	type IconData = readonly (readonly [string, Readonly<Record<string, string | number>>])[];

	export type ExtensionCardTone = 'neutral' | 'primary' | 'danger' | 'warning';

	export type ExtensionCardAction = {
		label: string;
		tone?: ExtensionCardTone;
		icon?: IconData;
		disabled?: boolean;
		title?: string;
		onclick: () => void;
	};

	export type ExtensionCardDependency = {
		name: string;
		optional: boolean;
		enabled: boolean;
		installed: boolean;
	};

	export type ExtensionCardStatus =
		| 'active'
		| 'restart'
		| 'unavailable'
		| 'failed'
		| 'disabled'
		| 'idle';

	type DetailRow = {
		label: string;
		value: string;
	};

	interface Props {
		name: string;
		pluginName: string;
		version?: string;
		vendor?: string;
		summary?: string;
		description?: string;
		enablesAgentTo?: string[];
		whenToEnable?: string;
		dependencies?: ExtensionCardDependency[];
		status?: ExtensionCardStatus;
		statusLabel?: string;
		statusMessage?: string;
		changelog?: string;
		updateLabel?: string;
		isThirdParty?: boolean;
		details?: DetailRow[];
		actions?: ExtensionCardAction[];
		queued?: boolean;
	}

	let {
		name,
		pluginName,
		version = '',
		vendor = '',
		summary = '',
		description = '',
		enablesAgentTo = [],
		whenToEnable = '',
		dependencies = [],
		status = 'idle',
		statusLabel = '',
		statusMessage = '',
		changelog = '',
		updateLabel = '',
		isThirdParty = false,
		details = [],
		actions = [],
		queued = false
	}: Props = $props();

	let displaySummary = $derived(summary || description);
	let needsAttention = $derived(
		status === 'restart' || status === 'unavailable' || status === 'failed'
	);

	function statusDotClass(s: ExtensionCardStatus): string {
		switch (s) {
			case 'active':
				return 'bg-emerald-400';
			case 'restart':
				return 'bg-amber-300';
			case 'unavailable':
				return 'bg-amber-300';
			case 'failed':
				return 'bg-red-400';
			case 'disabled':
				return 'bg-muted-foreground/35';
			default:
				return 'bg-muted-foreground/35';
		}
	}

	function actionClass(action: ExtensionCardAction): string {
		switch (action.tone) {
			case 'primary':
				return 'border-foreground/35 bg-foreground/[0.04] text-foreground hover:bg-foreground/[0.08]';
			case 'danger':
				return 'border-border/60 text-muted-foreground/80 hover:border-red-400/40 hover:text-red-300';
			case 'warning':
				return 'border-amber-400/35 text-amber-100/90 hover:bg-amber-500/10';
			default:
				return 'border-border/55 text-muted-foreground hover:border-border hover:text-foreground';
		}
	}

	function depClass(dep: ExtensionCardDependency): string {
		if (!dep.installed) return 'border-amber-400/30 text-amber-200/85';
		if (!dep.enabled && !dep.optional) return 'border-red-400/30 text-red-200/85';
		return 'border-border/50 text-muted-foreground/70';
	}
</script>

<div
	class="rounded-lg border p-4 transition-colors {queued
		? 'border-foreground/25 bg-foreground/[0.025]'
		: 'border-border/60 bg-card'}"
>
	<div class="flex items-start justify-between gap-4">
		<div class="min-w-0 flex-1">
			<div class="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
				<div class="min-w-0">
					<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
						<span
							class="h-1.5 w-1.5 shrink-0 rounded-full {statusDotClass(status)}"
							aria-hidden="true"
						></span>
						<h3 class="text-[14px] font-medium leading-5 text-foreground">{name}</h3>
						{#if version}
							<span class="text-muted-foreground/50 text-[11px] tabular-nums">v{version}</span>
						{/if}
					</div>

					{#if vendor}
						<div class="text-muted-foreground/45 mt-0.5 text-[11px]">
							<span>{vendor}</span>
						</div>
					{/if}
				</div>

				{#if isThirdParty || (statusLabel && needsAttention) || updateLabel}
					<div class="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
						{#if isThirdParty}
							<span
								class="rounded-full border border-amber-400/35 bg-amber-500/[0.06] px-2 py-0.5 text-[10.5px] font-medium text-amber-100/90"
								title="Third-party extension. Review before enabling."
							>
								Third-party
							</span>
						{/if}
						{#if statusLabel && needsAttention}
							<span
								class="rounded-full border border-amber-400/25 px-2 py-0.5 text-[10.5px] text-amber-100/85"
							>
								{statusLabel}
							</span>
						{/if}
						{#if updateLabel}
							<span
								class="border-border/45 text-muted-foreground/65 rounded-full border px-2 py-0.5 text-[10.5px]"
							>
								{updateLabel}
							</span>
						{/if}
					</div>
				{/if}
			</div>

			{#if displaySummary}
				<p class="text-foreground/82 mt-2 max-w-[58rem] text-[12.5px] leading-relaxed">
					{displaySummary}
				</p>
			{/if}

			{#if statusMessage}
				<p class="mt-2 text-[11px] leading-relaxed text-amber-200/80">{statusMessage}</p>
			{/if}

			{#if changelog}
				<p class="text-muted-foreground/55 mt-2 text-[11px] leading-relaxed">{changelog}</p>
			{/if}

			{#if dependencies.length > 0}
				<div class="mt-3">
					<p class="text-muted-foreground/40 text-[10px] uppercase tracking-wide">
						Unreal Engine plugins
					</p>
					<ul class="mt-1 flex flex-wrap gap-1.5">
						{#each dependencies as dep (dep.name)}
							<li
								class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] {depClass(
									dep
								)}"
								title={!dep.installed
									? `${dep.name} is not installed`
									: !dep.enabled && !dep.optional
										? `${dep.name} is disabled`
										: dep.optional
											? `${dep.name} is optional`
											: dep.name}
							>
								<span class="font-mono">{dep.name}</span>
								<span class="text-muted-foreground/45"
									>{dep.optional ? 'optional' : 'required'}</span
								>
							</li>
						{/each}
					</ul>
				</div>
			{/if}

			<details class="group mt-3 text-[11px]">
				<summary
					class="text-muted-foreground/45 hover:text-muted-foreground/75 inline-flex cursor-pointer select-none items-center gap-1.5"
				>
					<Icon icon={InformationCircleIcon} size={12} strokeWidth={1.6} />
					<span>Technical details</span>
				</summary>
				<div class="text-muted-foreground/55 mt-2 grid gap-3">
					{#if enablesAgentTo.length > 0}
						<div>
							<div
								class="text-muted-foreground/45 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide"
							>
								<Icon icon={CheckmarkCircle02Icon} size={12} strokeWidth={1.7} />
								<span>Adds</span>
							</div>
							<ul class="mt-1 grid gap-1.5 sm:grid-cols-2">
								{#each enablesAgentTo as item (item)}
									<li
										class="border-border/35 bg-foreground/[0.018] text-muted-foreground/78 flex min-w-0 items-start gap-1.5 rounded-md border px-2 py-1.5 text-[11.5px] leading-snug"
									>
										<span
											class="bg-foreground/45 mt-[0.35rem] h-1 w-1 shrink-0 rounded-full"
											aria-hidden="true"
										></span>
										<span>{item}</span>
									</li>
								{/each}
							</ul>
						</div>
					{/if}

					{#if whenToEnable}
						<div class="border-foreground/18 border-l pl-3">
							<div
								class="text-muted-foreground/45 flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide"
							>
								<Icon icon={BulbIcon} size={12} strokeWidth={1.7} />
								<span>Best for</span>
							</div>
							<p class="text-muted-foreground/76 mt-1 text-[11.5px] leading-relaxed">
								{whenToEnable}
							</p>
						</div>
					{/if}

					<div class="grid gap-1">
						<div class="flex gap-2">
							<span class="text-muted-foreground/40 w-20 shrink-0">Plugin</span>
							<span class="text-muted-foreground/65 truncate font-mono">{pluginName}</span>
						</div>
						{#each details as row (row.label)}
							{#if row.value}
								<div class="flex gap-2">
									<span class="text-muted-foreground/40 w-20 shrink-0">{row.label}</span>
									<span class="truncate">{row.value}</span>
								</div>
							{/if}
						{/each}
					</div>
				</div>
			</details>
		</div>

		{#if actions.length > 0}
			<div class="flex shrink-0 flex-col items-end gap-1.5">
				{#each actions as action (action.label)}
					<button
						class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11.5px] transition-colors disabled:cursor-not-allowed disabled:opacity-50 {actionClass(
							action
						)}"
						onclick={action.onclick}
						disabled={action.disabled}
						title={action.title}
					>
						{#if action.icon}
							<Icon icon={action.icon} size={11} strokeWidth={1.8} />
						{/if}
						{action.label}
					</button>
				{/each}
			</div>
		{/if}
	</div>
</div>
