import { writable, derived } from 'svelte/store';
import { onCommandsAvailable, type SlashCommand } from '$lib/bridge.js';
import { currentSessionId } from '$lib/stores/sessions.js';
import { isSessionDisposed, onSessionDisposed } from '$lib/stores/sessionLifecycle.js';

/** Per-session command lists (cached so they survive session switches) */
export const commandsBySession = writable<Record<string, SlashCommand[]>>({});

/** Current session's available commands (derived) */
export const availableCommands = derived(
	[commandsBySession, currentSessionId],
	([$bySession, $sid]) => ($sid ? ($bySession[$sid] ?? []) : [])
);

let commandsBound = false;

/** Wire up commands availability callback. Call once on mount. */
export function bindCommandsListener(): void {
	if (commandsBound) return;
	commandsBound = true;

	onCommandsAvailable((sessionId, commands) => {
		if (isSessionDisposed(sessionId)) return;
		// Store for ALL sessions — fixes lost commands for background sessions
		commandsBySession.update((all) => ({ ...all, [sessionId]: commands }));
	});
}

onSessionDisposed(cleanupCommandsForSession);

/** Clean up command data for deleted sessions */
export function cleanupCommandsForSession(sessionId: string): void {
	commandsBySession.update((all) => {
		const next = { ...all };
		delete next[sessionId];
		return next;
	});
}
