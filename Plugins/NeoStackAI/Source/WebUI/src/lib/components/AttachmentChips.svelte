<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import { Cancel01Icon, Image01Icon, CodeIcon } from '@hugeicons/core-free-icons';
	import { attachmentsBySession, removeItem } from '$lib/stores/attachments.js';

	interface Props {
		sessionId: string;
	}

	let { sessionId }: Props = $props();
	let attachments = $derived($attachmentsBySession[sessionId] ?? []);
	const byteFormatter = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
	function formatBytes(bytes: number) {
		if (bytes < 1024) return `${byteFormatter.format(bytes)} B`;
		if (bytes < 1024 * 1024) return `${byteFormatter.format(bytes / 1024)} KB`;
		return `${byteFormatter.format(bytes / (1024 * 1024))} MB`;
	}
</script>

{#if attachments.length > 0}
	<div class="flex flex-wrap gap-1.5 px-4 pb-1 pt-3">
		{#each attachments as att (att.id)}
			<div
				class="border-border/60 bg-card/60 text-foreground/80 group flex min-h-10 items-center gap-1.5 rounded-lg border px-2 py-1 text-[12px] transition-colors hover:border-border"
			>
				{#if att.type === 'image'}
					{#if att.thumbnail}
						<img
							src={`data:${att.mimeType ?? 'image/png'};base64,${att.thumbnail}`}
							alt={att.displayName}
							class="h-5 w-5 shrink-0 rounded object-cover"
						/>
					{:else}
						<Icon
							icon={Image01Icon}
							size={14}
							strokeWidth={1.5}
							class="shrink-0 text-blue-400/70"
						/>
					{/if}
				{:else}
					<Icon icon={CodeIcon} size={14} strokeWidth={1.5} class="shrink-0 text-orange-400/70" />
				{/if}
				<span class="max-w-[140px] truncate">{att.displayName}</span>
				{#if att.type === 'image' && att.width && att.height}
					<span class="text-muted-foreground/50 text-[10px]">{att.width}&times;{att.height}</span>
				{:else if att.type === 'file' && att.sizeBytes}
					<span class="text-muted-foreground/50 text-[10px]">{formatBytes(att.sizeBytes)}</span>
				{/if}
				<button
					class="text-muted-foreground/50 hover:bg-destructive/20 ml-0.5 flex h-10 w-10 items-center justify-center rounded transition-colors hover:text-red-400"
					onclick={() => removeItem(sessionId, att.id)}
					title="Remove"
					aria-label={`Remove ${att.displayName}`}
				>
					<Icon icon={Cancel01Icon} size={12} strokeWidth={2} />
				</button>
			</div>
		{/each}
	</div>
{/if}
