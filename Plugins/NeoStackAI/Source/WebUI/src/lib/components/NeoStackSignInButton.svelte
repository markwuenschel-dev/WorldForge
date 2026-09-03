<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import { Login01Icon, CheckmarkCircle02Icon, AlertCircleIcon } from '@hugeicons/core-free-icons';
	import { neostackAuth, retrySignIn, signOut, startSignIn } from '$lib/stores/neostackAuth.js';

	// Caller props.
	let {
		label = 'Sign in with NeoStack',
		variant = 'primary',
		onsuccess
	}: {
		label?: string;
		variant?: 'primary' | 'secondary';
		onsuccess?: () => void;
	} = $props();

	// Read state from the singleton store — one global listener feeds it, so
	// every sign-in entry point stays in sync. The component covers the whole
	// lifecycle: signed out → button, signing in → waiting + retry, signed
	// in → account line + sign out.
	const auth = $derived($neostackAuth);
	const planName = $derived(auth.entitlement?.planName || auth.entitlement?.plan || '');

	async function handleClick() {
		const terminal = await startSignIn();
		if (terminal.status === 'signedIn') {
			onsuccess?.();
		}
	}

	async function handleRetry() {
		const terminal = await retrySignIn();
		if (terminal.status === 'signedIn') {
			onsuccess?.();
		}
	}
</script>

{#if auth.status === 'signedIn'}
	<div class="flex items-center gap-2.5">
		<Icon
			icon={CheckmarkCircle02Icon}
			size={16}
			strokeWidth={2}
			class="shrink-0 text-emerald-500"
		/>
		<div class="min-w-0 leading-tight">
			<p class="truncate text-[13px] font-medium text-foreground">
				{auth.user?.email || auth.user?.name || 'Signed in'}
			</p>
			{#if planName}
				<p class="text-muted-foreground/60 truncate text-[11px]">{planName}</p>
			{/if}
		</div>
		<button
			type="button"
			onclick={() => signOut()}
			class="hover:bg-card/70 shrink-0 rounded-md border border-border bg-card px-2.5 py-1 text-[12px] font-medium text-foreground"
		>
			Sign out
		</button>
	</div>
{:else if auth.unreachable}
	<!-- Signed out only because NeoStack was unreachable. The credential is
	     still valid and the plugin is retrying on its own, so this must not
	     look like a logout — a paying user asked to "sign in again" during an
	     outage reasonably concludes their licence broke. Sign-in stays
	     available as an escape hatch, just not as the headline. -->
	<div class="flex items-center gap-2.5">
		<div
			class="border-muted-foreground/20 border-t-muted-foreground/70 h-4 w-4 shrink-0 animate-spin rounded-full border-2"
		></div>
		<div class="min-w-0 leading-tight">
			<p class="truncate text-[13px] font-medium text-foreground">
				{auth.user?.email ? `Reconnecting ${auth.user.email}…` : 'Reconnecting to NeoStack…'}
			</p>
			<p class="text-muted-foreground/60 truncate text-[11px]">
				Couldn’t reach NeoStack. Your licence is unaffected — retrying automatically.
			</p>
		</div>
		<button
			type="button"
			onclick={handleRetry}
			class="hover:bg-card/70 shrink-0 rounded-md border border-border bg-card px-2.5 py-1 text-[12px] font-medium text-foreground"
		>
			Sign in
		</button>
	</div>
{:else if auth.status === 'signingIn'}
	<div class="flex items-center gap-2.5">
		<div
			class="border-muted-foreground/20 border-t-muted-foreground/70 h-4 w-4 shrink-0 animate-spin rounded-full border-2"
		></div>
		<span class="text-muted-foreground/70 text-[13px]">Waiting for browser…</span>
		<button
			type="button"
			onclick={handleRetry}
			class="text-[12px] text-[var(--ue-accent)] underline-offset-2 hover:underline"
		>
			Retry
		</button>
	</div>
{:else}
	<button
		type="button"
		onclick={handleClick}
		class="group flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-[14px] font-medium transition-all {variant ===
		'primary'
			? 'bg-[var(--ue-accent)] text-white hover:opacity-90'
			: 'hover:bg-card/70 border border-border bg-card text-foreground'}"
	>
		<Icon icon={Login01Icon} size={16} strokeWidth={2} />
		{label}
	</button>

	{#if auth.error}
		<div class="mt-2 flex items-center gap-1.5 text-[12px] text-destructive">
			<Icon icon={AlertCircleIcon} size={14} strokeWidth={2} />
			<span>{auth.error}</span>
		</div>
	{/if}
{/if}
