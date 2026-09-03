<script lang="ts">
	import { cn } from '$lib/utils';
	import type { ShimmerProps } from './types';

	let {
		children,
		as = 'p',
		class: className,
		duration = 2,
		spread = 2,
		content_length = 30,
		...rest
	}: ShimmerProps = $props();

	// Calculate dynamic spread based on text length
	let dynamicSpread = $derived(content_length * spread);

	// NOTE (CEF perf): the shimmer animates background-position, a paint
	// property — Chromium repaints the element every frame while mounted.
	// A compositable (transform-based) version is not achievable pixel-
	// identically: bg-clip-text pins the gradient to this element's own
	// background, and translating an overlay would move the glyphs instead
	// of the highlight band. Therefore every usage site MUST gate <Shimmer>
	// behind an "actually streaming/working" condition — never render it in
	// an idle or history-loaded state.
</script>

<svelte:element
	this={as}
	class={cn(
		'relative inline-block bg-[length:250%_100%,auto] bg-clip-text text-transparent',
		'[--bg:linear-gradient(90deg,#0000_calc(50%-var(--spread)),var(--background),#0000_calc(50%+var(--spread)))] [background-repeat:no-repeat,padding-box]',
		'animate-shimmer',
		className
	)}
	style="--spread: {dynamicSpread}px; --shimmer-duration: {duration}s; background-image: var(--bg), linear-gradient(var(--muted-foreground), var(--muted-foreground)); background-position: 100% center;"
	{...rest}
>
	{@render children()}
</svelte:element>

<style>
	@keyframes shimmer {
		from {
			background-position: 100% center;
		}
		to {
			background-position: 0% center;
		}
	}

	:global(.animate-shimmer) {
		animation: shimmer var(--shimmer-duration, 2s) linear infinite;
	}
	@media (prefers-reduced-motion: reduce) {
		:global(.animate-shimmer) {
			animation: none;
		}
	}
</style>
