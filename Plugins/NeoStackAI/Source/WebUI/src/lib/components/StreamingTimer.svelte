<script lang="ts">
	import { onMount, onDestroy } from 'svelte';

	let elapsed = $state(0);
	let timer: ReturnType<typeof setInterval>;

	onMount(() => {
		const start = Date.now();
		timer = setInterval(() => {
			elapsed = Date.now() - start;
		}, 500);
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	let display = $derived.by(() => {
		const sec = elapsed / 1000;
		if (sec < 60) return `${sec.toFixed(1)}s`;
		const m = Math.floor(sec / 60);
		const s = Math.floor(sec % 60);
		return `${m}m ${s}s`;
	});
</script>

<span class="text-muted-foreground/30 tabular-nums">{display}</span>
