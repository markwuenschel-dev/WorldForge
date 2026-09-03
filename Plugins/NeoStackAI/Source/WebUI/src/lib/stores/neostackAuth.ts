import { writable, get } from 'svelte/store';
import {
	getNeoStackAuthState,
	onNeoStackAuthChanged,
	setNeoStackActiveOrg,
	signOutNeoStack as bridgeSignOut,
	startNeoStackSignIn as bridgeStartSignIn,
	type NeoStackAuthState
} from '$lib/bridge.js';

// Single source of truth for the NeoStack sign-in state. The bridge exposes a
// single-slot push channel (bindonneostackauthchanged), so exactly one global
// listener feeds this store; every sign-in button and account panel reads it
// instead of binding its own callback.

const SIGNED_OUT: NeoStackAuthState = { status: 'signedOut' };

export const neostackAuth = writable<NeoStackAuthState>(SIGNED_OUT);

let listenerBound = false;

/** Subscribe the store to bridge broadcasts and pull the current snapshot.
 *  Idempotent — call once at app mount alongside the other listener binders. */
export function bindNeoStackAuthListener(): void {
	if (listenerBound) return;
	listenerBound = true;
	onNeoStackAuthChanged((next) => {
		neostackAuth.set(next);
	});
	// Pushes only fire on transitions — a silent resume may already have
	// signed the session in before the WebUI mounted, so fetch once.
	getNeoStackAuthState()
		.then((state) => neostackAuth.set(state))
		.catch((e) => console.warn('Failed to load NeoStack auth state:', e));
}

/** Start the browser sign-in flow. Resolves with the *terminal* state
 *  (`signedIn`, or `signedOut` on failure/cancel) so callers can wait for a
 *  definitive outcome before firing their own `onsuccess` callback. */
export function startSignIn(): Promise<NeoStackAuthState> {
	// Optimistic — show the waiting state instantly without waiting for the
	// C++ flow's first broadcast.
	neostackAuth.update((s) => ({ ...s, status: 'signingIn', error: undefined }));

	const terminal = waitForTerminal();

	// Fire-and-forget; the listener pushes updates into the store. If the
	// bridge call itself throws, surface that as an error on the store too.
	bridgeStartSignIn().catch((e) => {
		neostackAuth.set({
			status: 'signedOut',
			error: e instanceof Error ? e.message : 'Couldn’t start sign-in.'
		});
	});

	return terminal;
}

/** Abandon a stuck sign-in attempt and open a fresh browser flow. The C++
 *  SignIn() no-ops while a flow is in flight, so retry goes through
 *  SignOut() first (which cancels the pending loopback listener). */
export async function retrySignIn(): Promise<NeoStackAuthState> {
	try {
		await bridgeSignOut();
	} catch {
		// Ignore — nothing to cancel is fine; the fresh SignIn decides.
	}
	return startSignIn();
}

/** Server-side revoke + clear the local credential. State lands via push. */
export async function signOut(): Promise<void> {
	await bridgeSignOut();
}

/** Returns a promise resolving with the first non-signingIn state seen after
 *  this call. Used by callers that want to await a terminal outcome. */
function waitForTerminal(): Promise<NeoStackAuthState> {
	return new Promise((resolve) => {
		const unsubscribe = neostackAuth.subscribe((s) => {
			if (s.status !== 'signingIn') {
				// Defer unsubscribe so the subscribe() callback finishes first.
				queueMicrotask(() => unsubscribe());
				resolve(s);
			}
		});
	});
}

export function getNeoStackAuthSnapshot(): NeoStackAuthState {
	return get(neostackAuth);
}

/** Switch the acting organization ('' = follow the token's claim). The C++
 *  side persists the choice, reconnects the gateway sockets, re-announces the
 *  device, and broadcasts the new state into this store. Old-org sessions are
 *  released (they keep working locally as forks). */
export async function switchOrganization(orgId: string): Promise<void> {
	await setNeoStackActiveOrg(orgId);
}
