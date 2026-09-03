<script lang="ts">
	import { onMount } from 'svelte';

	let {
		base64,
		mimeType,
		width = 0,
		height = 0,
		alt = 'Tool result'
	}: {
		base64: string;
		mimeType: string;
		width?: number;
		height?: number;
		alt?: string;
	} = $props();

	let objectUrl = $state('');
	let failed = $state(false);

	onMount(() => {
		let disposed = false;
		const schedule = window.requestIdleCallback
			? (callback: () => void) => window.requestIdleCallback(callback, { timeout: 200 })
			: (callback: () => void) => window.setTimeout(callback, 0);
		const handle = schedule(() => {
			try {
				const binary = atob(base64);
				const bytes = new Uint8Array(binary.length);
				for (let index = 0; index < binary.length; index += 1) {
					bytes[index] = binary.charCodeAt(index);
				}
				const url = URL.createObjectURL(new Blob([bytes], { type: mimeType }));
				if (disposed) URL.revokeObjectURL(url);
				else objectUrl = url;
			} catch {
				failed = true;
			}
		});

		return () => {
			disposed = true;
			if (window.cancelIdleCallback) window.cancelIdleCallback(handle);
			else window.clearTimeout(handle);
			if (objectUrl) URL.revokeObjectURL(objectUrl);
		};
	});
</script>

{#if objectUrl}
	<img
		src={objectUrl}
		{alt}
		{width}
		{height}
		loading="lazy"
		decoding="async"
		class="max-h-[400px] w-auto max-w-full rounded-md object-contain ring-1 ring-inset ring-black/10 dark:ring-white/10"
	/>
{:else if failed}
	<div class="border-border/50 rounded-md border px-3 py-2 text-[11px] text-muted-foreground">
		Image unavailable
	</div>
{:else}
	<div
		class="border-border/50 bg-secondary/40 h-20 w-32 animate-pulse rounded-md border motion-reduce:animate-none"
		aria-label="Loading image"
	></div>
{/if}
