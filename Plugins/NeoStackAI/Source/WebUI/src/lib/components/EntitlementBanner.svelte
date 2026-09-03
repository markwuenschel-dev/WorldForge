<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getEntitlementStatus, type EntitlementStatus } from '$lib/bridge';
	import { neostackAuth } from '$lib/stores/neostackAuth.js';

	let entitlement = $state<EntitlementStatus>({
		entitled: true,
		status: 'unknown',
		isBinaryBuild: false
	});
	let entitlementResolved = $state(false);
	let dismissed = $state(false);
	let pollHandle: ReturnType<typeof setInterval> | null = null;

	async function refresh() {
		try {
			entitlement = await getEntitlementStatus();
			entitlementResolved = true;
			// Stop polling once we have a definitive answer (anything other
			// than "unknown"). Network errors are definitive too — the user
			// needs to see the banner so they know what's happening.
			if (entitlement.status !== 'unknown' && pollHandle) {
				clearInterval(pollHandle);
				pollHandle = null;
			}
		} catch {
			// Bridge not ready yet — keep polling.
		}
	}

	onMount(() => {
		refresh();
		// Entitlement check is fired 0s after StartupModule but the HTTP
		// request takes ~100-500ms; poll every 1s for the first ~12s while
		// the editor warms up.
		let attempts = 0;
		pollHandle = setInterval(() => {
			attempts += 1;
			refresh();
			if (attempts > 12 && pollHandle) {
				clearInterval(pollHandle);
				pollHandle = null;
			}
		}, 1000);
	});

	onDestroy(() => {
		if (pollHandle) clearInterval(pollHandle);
	});

	// Re-check whenever the sign-in state changes (sign-in, sign-out, plan
	// fetch landing) so the banner clears/appears without waiting for a poll.
	$effect(() => {
		void $neostackAuth;
		refresh();
	});

	const visible = $derived(
		!dismissed && entitlementResolved && !entitlement.entitled && entitlement.status !== 'unknown'
	);

	const headline = $derived(
		entitlement?.status === 'network'
			? entitlement.isBinaryBuild
				? 'Subscription verification offline'
				: 'Couldn’t reach NeoStack Cloud'
			: 'NeoStack access required'
	);

	const body = $derived(
		entitlement?.status === 'network'
			? entitlement.isBinaryBuild
				? 'Tools are paused until we can verify access. Your licence is unaffected and we’re retrying automatically.'
				: 'Reconnect to enable plugin updates and the cloud chat provider.'
			: 'Sign in with NeoStack, connect your lifetime purchase, or activate a subscription.'
	);

	// An outage is not a billing problem. Sending someone to their billing page
	// because a request timed out is what convinced a lifetime owner (and the
	// agent driving his editor) that his licence had broken.
	const offline = $derived(entitlement?.status === 'network');
</script>

{#if visible}
	<div class="entitlement-banner" role="alert">
		<div class="msg">
			<strong>{headline}</strong>
			<span>{body}</span>
		</div>
		<div class="actions">
			{#if offline}
				<button class="primary" type="button" onclick={() => refresh()}>Retry</button>
			{:else}
				<a
					class="primary"
					href="https://neostack.dev/billing"
					target="_blank"
					rel="noopener noreferrer"
				>
					Open billing
				</a>
			{/if}
			<button type="button" class="ghost" onclick={() => (dismissed = true)} aria-label="Dismiss">
				&times;
			</button>
		</div>
	</div>
{/if}

<style>
	.entitlement-banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.625rem 1rem;
		background: rgba(220, 38, 38, 0.1);
		color: var(--fg-4, inherit);
		border-bottom: 1px solid rgba(220, 38, 38, 0.2);
		font-size: 0.875rem;
	}
	.msg {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.msg strong {
		font-weight: 600;
	}
	.msg span {
		opacity: 0.8;
	}
	.actions {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-shrink: 0;
	}
	.actions a.primary,
	.actions button {
		font-size: 0.8125rem;
		font-weight: 500;
		padding: 0.375rem 0.75rem;
		border-radius: 9999px;
		border: 1px solid rgba(220, 38, 38, 0.4);
		background: transparent;
		color: inherit;
		cursor: pointer;
		text-decoration: none;
	}
	/* Retry is the primary action during an outage, so it styles as one too. */
	.actions a.primary,
	.actions button.primary {
		background: rgb(220, 38, 38);
		color: white;
		border-color: rgb(220, 38, 38);
	}
	.actions button.ghost {
		border-color: transparent;
		opacity: 0.6;
		padding: 0.25rem 0.5rem;
	}
	.actions button.ghost:hover {
		opacity: 1;
	}
</style>
