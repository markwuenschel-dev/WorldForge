<script lang="ts">
	import { agentUpdates, updatingAgents, updateAgent } from '$lib/stores/registry.js';
	import { selectedAgent, withAlpha } from '$lib/stores/agents.js';

	// Match the active agent (by registryId, since updates are keyed by ACP agent id).
	let update = $derived(
		$selectedAgent?.registryId
			? $agentUpdates.find((u) => u.agentId === $selectedAgent!.registryId)
			: undefined
	);

	let isUpdating = $derived(update ? $updatingAgents.has(update.agentId) : false);
	let agentColor = $derived($selectedAgent?.color ?? '#888');

	async function handleUpdate() {
		if (!update || isUpdating) return;
		await updateAgent(update.agentId);
	}
</script>

{#if update}
	<div class="mx-auto mb-3 w-full max-w-3xl">
		<div
			class="border-border/40 flex items-center gap-3 overflow-hidden rounded-lg border px-3.5 py-2"
			style="background: linear-gradient(135deg, #252525, #1f1f1f);"
		>
			<!-- Download icon -->
			<div
				class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
				style="background-color: {withAlpha(agentColor, 0.12)};"
			>
				<svg
					class="h-3.5 w-3.5"
					style="color: {agentColor};"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
					stroke-width="2"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M12 4v12m0 0l-4-4m4 4l4-4M4 20h16"
					/>
				</svg>
			</div>

			<div class="min-w-0 flex-1">
				<div class="text-foreground/85 text-[12.5px] font-medium">
					Update available for {update.agentName}
				</div>
				<div class="text-muted-foreground/50 text-[11px]">
					v{update.installedVersion} → v{update.latestVersion}
					{#if update.isNpx}
						<span class="ml-1 opacity-60">(via npx)</span>
					{/if}
				</div>
			</div>

			<button
				class="rounded-md px-3 py-1.5 text-[12px] font-medium text-white transition-all hover:brightness-110 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
				style="background-color: {agentColor};"
				disabled={isUpdating}
				onclick={handleUpdate}
				title="Update now. Open a new chat to start using v{update.latestVersion}."
			>
				{#if isUpdating}
					<span class="inline-flex items-center gap-1.5">
						<span class="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white"
						></span>
						Updating…
					</span>
				{:else}
					Update to v{update.latestVersion}
				{/if}
			</button>
		</div>
	</div>
{/if}
