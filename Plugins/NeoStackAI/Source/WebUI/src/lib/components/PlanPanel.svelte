<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import {
		CheckmarkCircle02Icon,
		Loading03Icon,
		RadioIcon,
		ArrowDown01Icon,
		ArrowUp01Icon
	} from '@hugeicons/core-free-icons';
	import type { PlanUpdate } from '$lib/bridge.js';

	let { plan }: { plan: PlanUpdate | null } = $props();

	let expanded = $state(false);

	let currentTask = $derived(plan?.entries.find((e) => e.status === 'in_progress'));

	let progress = $derived(
		plan && plan.totalCount > 0 ? Math.round((plan.completedCount / plan.totalCount) * 100) : 0
	);

	let statusIcon = (status: string) => {
		switch (status) {
			case 'completed':
				return CheckmarkCircle02Icon;
			case 'in_progress':
				return Loading03Icon;
			default:
				return RadioIcon;
		}
	};

	let statusColor = (status: string) => {
		switch (status) {
			case 'completed':
				return 'text-emerald-400/60';
			case 'in_progress':
				return 'text-blue-400';
			default:
				return 'text-muted-foreground/30';
		}
	};

	let textColor = (status: string) => {
		switch (status) {
			case 'completed':
				return 'text-muted-foreground/40 line-through';
			case 'in_progress':
				return 'text-foreground';
			default:
				return 'text-muted-foreground/60';
		}
	};
</script>

{#if plan && plan.entries.length > 0}
	<div class="border-border/50 border-b">
		<!-- Header — clickable to toggle -->
		<button
			class="hover:bg-accent/20 flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] transition-colors"
			onclick={() => (expanded = !expanded)}
		>
			{#if expanded}
				<!-- Expanded: show "Tasks" label + count -->
				<div class="flex flex-1 items-center gap-2">
					<span class="text-foreground/80 font-medium">Tasks</span>
					<span class="text-muted-foreground/50 text-[11px]">
						{plan.completedCount}/{plan.totalCount}
					</span>
				</div>
			{:else}
				<!-- Collapsed: show current task + count -->
				<div class="flex min-w-0 flex-1 items-center gap-2">
					{#if currentTask}
						<span class="text-blue-400">
							<Icon icon={Loading03Icon} size={13} strokeWidth={1.5} class="animate-spin" />
						</span>
						<span class="text-foreground/70 truncate text-[12px]">
							{currentTask.activeForm || currentTask.content}
						</span>
					{:else}
						<span class="text-emerald-400/60">
							<Icon icon={CheckmarkCircle02Icon} size={13} strokeWidth={1.5} />
						</span>
						<span class="text-muted-foreground/50 truncate text-[12px]">All tasks complete</span>
					{/if}
					<span class="text-muted-foreground/40 shrink-0 text-[11px]">
						{plan.completedCount}/{plan.totalCount}
					</span>
				</div>
			{/if}

			<!-- Progress bar -->
			<div class="bg-muted-foreground/15 h-1.5 w-16 shrink-0 overflow-hidden rounded-full">
				<div
					class="h-full rounded-full bg-emerald-500 transition-all duration-300"
					style="width: {progress}%;"
				></div>
			</div>

			<span class="text-muted-foreground/50 shrink-0">
				<Icon icon={expanded ? ArrowUp01Icon : ArrowDown01Icon} size={12} strokeWidth={1.5} />
			</span>
		</button>

		<!-- Task list (expanded only) -->
		{#if expanded}
			<div class="border-border/30 border-t px-1 py-1">
				{#each plan.entries as entry (`${entry.content}:${entry.status}`)}
					<div class="flex items-start gap-2 rounded-lg px-2 py-1">
						<span
							class="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center {statusColor(
								entry.status
							)}"
						>
							<Icon
								icon={statusIcon(entry.status)}
								size={13}
								strokeWidth={1.5}
								class={entry.status === 'in_progress' ? 'animate-spin' : ''}
							/>
						</span>
						<div class="min-w-0 flex-1">
							<div class="text-[12px] leading-relaxed {textColor(entry.status)}">
								{#if entry.status === 'in_progress' && entry.activeForm}
									{entry.activeForm}
								{:else}
									{entry.content}
								{/if}
							</div>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}
