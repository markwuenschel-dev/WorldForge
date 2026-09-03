import { get, writable } from 'svelte/store';
import {
	getSessionConfigOptions,
	onConfigOptionsAvailable,
	setSessionConfigOption,
	type SessionConfigOption
} from '$lib/bridge.js';
import { createOperationVersionTracker } from '$lib/operationVersions.js';
import { isSessionDisposed, onSessionDisposed } from '$lib/stores/sessionLifecycle.js';

export type SessionConfigOptionState = {
	options: SessionConfigOption[];
	isLoading: boolean;
	loaded: boolean;
};

const createDefaultState = (): SessionConfigOptionState => ({
	options: [],
	isLoading: false,
	loaded: false
});

export const configOptionStatesBySession = writable<Record<string, SessionConfigOptionState>>({});

const loadVersions = createOperationVersionTracker();
const mutationVersions = createOperationVersionTracker();

function getSessionState(sessionId: string): SessionConfigOptionState {
	return get(configOptionStatesBySession)[sessionId] ?? createDefaultState();
}

function updateSessionState(
	sessionId: string,
	update:
		| Partial<SessionConfigOptionState>
		| ((state: SessionConfigOptionState) => SessionConfigOptionState)
): void {
	if (isSessionDisposed(sessionId)) return;
	configOptionStatesBySession.update((states) => {
		const current = states[sessionId] ?? createDefaultState();
		const next = typeof update === 'function' ? update(current) : { ...current, ...update };
		return { ...states, [sessionId]: next };
	});
}

export async function loadConfigOptionsForSession(sessionId: string): Promise<void> {
	if (!sessionId) return;
	const existing = getSessionState(sessionId);
	if (existing.isLoading || existing.loaded) return;

	const version = loadVersions.begin(sessionId);
	updateSessionState(sessionId, { isLoading: true });
	try {
		const options = await getSessionConfigOptions(sessionId);
		if (!loadVersions.isCurrent(sessionId, version)) return;
		updateSessionState(sessionId, { options: options ?? [], isLoading: false, loaded: true });
	} catch (error) {
		if (!loadVersions.isCurrent(sessionId, version)) return;
		console.warn(`Failed to load config options for ${sessionId}:`, error);
		updateSessionState(sessionId, { isLoading: false, loaded: false });
	}
}

export async function changeSessionConfigOption(
	sessionId: string,
	configId: string,
	value: string | boolean
): Promise<void> {
	if (!sessionId || !configId) return;
	const previousOptions = getSessionState(sessionId).options;
	const mutationKey = `${sessionId}:${configId}`;
	const version = mutationVersions.begin(mutationKey);

	updateSessionState(sessionId, (state) => ({
		...state,
		options: state.options.map((option) =>
			option.id === configId ? ({ ...option, currentValue: value } as SessionConfigOption) : option
		)
	}));

	try {
		await setSessionConfigOption(sessionId, configId, value);
	} catch (error) {
		if (mutationVersions.isCurrent(mutationKey, version)) {
			updateSessionState(sessionId, { options: previousOptions });
		}
		throw error;
	}
}

let bound = false;

export function bindConfigOptionsListener(): void {
	if (bound) return;
	bound = true;
	onConfigOptionsAvailable((sessionId, _agentName, options) => {
		if (!sessionId || isSessionDisposed(sessionId)) return;
		updateSessionState(sessionId, { options: options ?? [], isLoading: false, loaded: true });
	});
}

onSessionDisposed((sessionId) => {
	loadVersions.invalidate(sessionId);
	configOptionStatesBySession.update((states) => {
		const next = { ...states };
		delete next[sessionId];
		return next;
	});
});
