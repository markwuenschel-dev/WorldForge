<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import { ReloadIcon } from '@hugeicons/core-free-icons';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import { selectedAgent } from '$lib/stores/agents.js';
	import {
		currentRateLimits,
		hasRateLimits,
		peakUsagePercent,
		formatResetTime,
		formatWindowDuration,
		formatLastUpdated,
		currencySymbol,
		usageColor,
		refreshCurrentUsage
	} from '$lib/stores/rateLimits.js';

	let refreshing = $state(false);

	async function handleRefresh(e: MouseEvent) {
		e.stopPropagation();
		if (refreshing) return;
		refreshing = true;
		try {
			await refreshCurrentUsage();
		} finally {
			setTimeout(() => (refreshing = false), 1500);
		}
	}
</script>

{#if $hasRateLimits && $currentRateLimits}
	{@const data = $currentRateLimits}
	{@const peak = $peakUsagePercent}
	{@const color = data.hasData ? usageColor(peak) : '#71717a'}
	<Tooltip.Root>
		<Tooltip.Trigger
			class="hover:bg-accent/50 flex items-center gap-1.5 rounded-md px-1.5 py-1 transition-colors"
		>
			{#if data.isLoading && !data.hasData}
				<!-- Loading spinner when no data yet -->
				<div
					class="border-muted-foreground/30 border-t-muted-foreground/70 h-3 w-3 animate-spin rounded-full border"
				></div>
				<span class="text-muted-foreground/50 text-[11px]">...</span>
			{:else if data.hasData}
				<!-- Compact horizontal bar -->
				<div class="bg-muted-foreground/15 flex h-[6px] w-[40px] overflow-hidden rounded-full">
					<div
						class="h-full rounded-full transition-all duration-500"
						style="width: {peak}%; background-color: {color};"
					></div>
				</div>
				<span class="text-[11px] tabular-nums" style="color: {color};">{peak}%</span>
			{/if}
		</Tooltip.Trigger>
		<Tooltip.Content
			side="bottom"
			sideOffset={8}
			class="w-[290px] rounded-lg border border-border bg-surface-bar p-3 text-[12px] text-foreground shadow-xl"
		>
			<!-- Header with agent name + plan + refresh -->
			<div class="mb-2.5 flex items-center justify-between">
				<div class="flex items-baseline gap-2">
					<span class="text-[13px] font-medium">
						{data.agentName || $selectedAgent?.name || 'Usage'}
					</span>
					{#if data.planType}
						<span
							class="bg-muted-foreground/10 rounded px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
						>
							{data.planType}
						</span>
					{/if}
				</div>
				<button
					class="text-muted-foreground/40 hover:bg-accent/50 hover:text-muted-foreground/80 rounded p-1 transition-colors {refreshing
						? 'animate-spin'
						: ''}"
					onclick={handleRefresh}
					title="Refresh usage"
				>
					<Icon icon={ReloadIcon} size={12} strokeWidth={1.5} />
				</button>
			</div>
			<div class="text-muted-foreground/50 mb-2.5 text-[11px] leading-relaxed">
				Your API rate limit — how many requests your plan allows in a time window. Resets
				automatically.
			</div>

			{#if data.isLoading && !data.hasData}
				<!-- Loading state (no data yet) -->
				<div class="flex items-center justify-center gap-2 py-4">
					<div
						class="border-muted-foreground/20 border-t-muted-foreground/60 h-3.5 w-3.5 animate-spin rounded-full border-2"
					></div>
					<span class="text-muted-foreground/50 text-[11px]">Fetching usage data...</span>
				</div>
			{:else if data.hasData}
				<!-- Rate limit windows -->
				<div class="flex flex-col gap-2.5">
					{#if data.primary.hasData}
						{@const pct = Math.round(data.primary.usedPercent)}
						<div>
							<div class="mb-1 flex items-baseline justify-between">
								<span class="text-muted-foreground">
									Session ({formatWindowDuration(data.primary.windowDurationMinutes)})
								</span>
								<span class="font-medium tabular-nums" style="color: {usageColor(pct)};"
									>{pct}%</span
								>
							</div>
							<div class="bg-muted-foreground/15 h-1.5 w-full overflow-hidden rounded-full">
								<div
									class="h-full rounded-full transition-all duration-300"
									style="width: {pct}%; background-color: {usageColor(pct)};"
								></div>
							</div>
							{#if data.primary.resetsAt}
								<div class="text-muted-foreground/40 mt-0.5 text-[11px]">
									Resets in {formatResetTime(data.primary.resetsAt)}
								</div>
							{/if}
						</div>
					{/if}

					{#if data.secondary.hasData}
						{@const pct = Math.round(data.secondary.usedPercent)}
						<div>
							<div class="mb-1 flex items-baseline justify-between">
								<span class="text-muted-foreground">
									All Models ({formatWindowDuration(data.secondary.windowDurationMinutes)})
								</span>
								<span class="font-medium tabular-nums" style="color: {usageColor(pct)};"
									>{pct}%</span
								>
							</div>
							<div class="bg-muted-foreground/15 h-1.5 w-full overflow-hidden rounded-full">
								<div
									class="h-full rounded-full transition-all duration-300"
									style="width: {pct}%; background-color: {usageColor(pct)};"
								></div>
							</div>
							{#if data.secondary.resetsAt}
								<div class="text-muted-foreground/40 mt-0.5 text-[11px]">
									Resets in {formatResetTime(data.secondary.resetsAt)}
								</div>
							{/if}
						</div>
					{/if}

					{#if data.modelSpecific.hasData}
						{@const pct = Math.round(data.modelSpecific.usedPercent)}
						{@const label = data.modelSpecificLabel ? `${data.modelSpecificLabel} Only` : 'Model'}
						<div>
							<div class="mb-1 flex items-baseline justify-between">
								<span class="text-muted-foreground">
									{label} ({formatWindowDuration(data.modelSpecific.windowDurationMinutes)})
								</span>
								<span class="font-medium tabular-nums" style="color: {usageColor(pct)};"
									>{pct}%</span
								>
							</div>
							<div class="bg-muted-foreground/15 h-1.5 w-full overflow-hidden rounded-full">
								<div
									class="h-full rounded-full transition-all duration-300"
									style="width: {pct}%; background-color: {usageColor(pct)};"
								></div>
							</div>
							{#if data.modelSpecific.resetsAt}
								<div class="text-muted-foreground/40 mt-0.5 text-[11px]">
									Resets in {formatResetTime(data.modelSpecific.resetsAt)}
								</div>
							{/if}
						</div>
					{/if}
				</div>

				<!-- Claude Extra usage -->
				{#if data.extraUsage.hasData}
					{@const sym = currencySymbol(data.extraUsage.currencyCode)}
					{@const extraPct =
						data.extraUsage.limitAmount > 0
							? Math.min(100, (data.extraUsage.usedAmount / data.extraUsage.limitAmount) * 100)
							: 0}
					<div class="border-border/40 mt-2.5 border-t pt-2">
						<div class="mb-1 flex items-baseline justify-between">
							<span class="text-muted-foreground">Claude Extra</span>
							<span class="font-medium tabular-nums" style="color: {usageColor(extraPct)};">
								{sym}{data.extraUsage.usedAmount.toFixed(2)} / {sym}{data.extraUsage.limitAmount.toFixed(
									2
								)}
							</span>
						</div>
						<div class="bg-muted-foreground/15 h-1.5 w-full overflow-hidden rounded-full">
							<div
								class="h-full rounded-full transition-all duration-300"
								style="width: {extraPct}%; background-color: {usageColor(extraPct)};"
							></div>
						</div>
						<div class="text-muted-foreground/40 mt-0.5 text-[11px]">Monthly spend</div>
					</div>
				{/if}

				<!-- Error message -->
				{#if data.errorMessage}
					<div class="mt-2 text-[11px] text-amber-400/70">{data.errorMessage}</div>
				{/if}

				<!-- Last updated -->
				{#if data.lastUpdated}
					<div class="text-muted-foreground/30 mt-2 text-[10px]">
						{formatLastUpdated(data.lastUpdated)}
					</div>
				{/if}
			{:else if data.errorMessage}
				<!-- Error with no data -->
				<div class="py-2 text-[11px] text-amber-400/70">{data.errorMessage}</div>
			{:else}
				<!-- Unsupported agent -->
				<div class="text-muted-foreground/40 py-2 text-center text-[11px]">
					Usage tracking is available for<br />Claude Code and Codex CLI agents.
				</div>
			{/if}
		</Tooltip.Content>
	</Tooltip.Root>
{/if}
