<script lang="ts">
	import { t } from '$lib/i18n.js';

	// Shown by +layout.svelte while the UE bridge is still binding on a slow
	// editor startup — only after a short delay so it never flashes normally.
	let { visible }: { visible: boolean } = $props();
</script>

{#if visible}
	<div class="connecting-banner" role="status">
		<span class="spinner" aria-hidden="true"></span>
		<span>{$t('connecting_to_editor')}</span>
	</div>
{/if}

<style>
	.connecting-banner {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.375rem 1rem;
		background: rgba(120, 120, 120, 0.08);
		color: var(--fg-4, inherit);
		border-bottom: 1px solid rgba(120, 120, 120, 0.15);
		font-size: 0.8125rem;
		opacity: 0.8;
	}
	.spinner {
		width: 0.75rem;
		height: 0.75rem;
		border-radius: 9999px;
		border: 2px solid rgba(120, 120, 120, 0.3);
		border-top-color: currentColor;
		animation: connecting-spin 0.8s linear infinite;
		flex-shrink: 0;
	}
	@keyframes connecting-spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation: none;
		}
	}
</style>
