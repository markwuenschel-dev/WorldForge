import { writable, get } from 'svelte/store';
import { getModes, setMode, onModesAvailable, onModeChanged, type ModeInfo } from '$lib/bridge.js';
import { selectedAgent } from '$lib/stores/agents.js';
import { createOperationVersionTracker } from '$lib/operationVersions.js';

export type AgentModeState = {
	modes: ModeInfo[];
	currentModeId: string;
	isLoading: boolean;
	loaded: boolean;
};

const createDefaultAgentModeState = (): AgentModeState => ({
	modes: [],
	currentModeId: '',
	isLoading: false,
	loaded: false
});

/** Authoritative mode state keyed by agent for every visible pane. */
export const modeStatesByAgent = writable<Record<string, AgentModeState>>({});

// Legacy focused-agent stores remain for route-level UI. ChatPane reads the map.
export const availableModes = writable<ModeInfo[]>([]);
export const currentModeId = writable<string>('');

const modeLoadVersions = createOperationVersionTracker();
const modeMutationVersions = createOperationVersionTracker();

function getAgentModeState(agentName: string): AgentModeState {
	return get(modeStatesByAgent)[agentName] ?? createDefaultAgentModeState();
}

function syncFocusedAgentStores(agentName: string, state: AgentModeState): void {
	if (get(selectedAgent)?.name !== agentName) return;
	availableModes.set(state.modes);
	currentModeId.set(state.currentModeId);
}

function updateAgentModeState(
	agentName: string,
	update: Partial<AgentModeState> | ((state: AgentModeState) => AgentModeState)
): AgentModeState {
	let nextState = createDefaultAgentModeState();
	modeStatesByAgent.update((states) => {
		const current = states[agentName] ?? createDefaultAgentModeState();
		nextState = typeof update === 'function' ? update(current) : { ...current, ...update };
		return { ...states, [agentName]: nextState };
	});
	syncFocusedAgentStores(agentName, nextState);
	return nextState;
}

/** Load modes for an agent without changing another pane's controls. */
export async function loadModesForAgent(agentName: string): Promise<void> {
	if (!agentName) return;
	const existing = getAgentModeState(agentName);
	if (existing.isLoading) return;
	if (existing.loaded && !existing.isLoading) {
		syncFocusedAgentStores(agentName, existing);
		return;
	}

	const requestVersion = modeLoadVersions.begin(agentName);
	updateAgentModeState(agentName, { isLoading: true });
	try {
		const state = await getModes(agentName);
		if (!modeLoadVersions.isCurrent(agentName, requestVersion)) return;
		updateAgentModeState(agentName, {
			modes: state.modes ?? [],
			currentModeId: state.currentModeId || state.modes?.[0]?.id || '',
			isLoading: false,
			loaded: true
		});
	} catch (error) {
		if (!modeLoadVersions.isCurrent(agentName, requestVersion)) return;
		console.warn(`Failed to load modes for ${agentName}:`, error);
		updateAgentModeState(agentName, {
			modes: [],
			currentModeId: '',
			isLoading: false,
			loaded: false
		});
	}
}

/** Change mode without allowing an old failure to roll back a newer choice. */
export async function changeMode(agentName: string, modeId: string): Promise<void> {
	if (!agentName || !modeId) return;
	const previousModeId = getAgentModeState(agentName).currentModeId;
	const mutationVersion = modeMutationVersions.begin(agentName);
	updateAgentModeState(agentName, { currentModeId: modeId, loaded: true });
	try {
		await setMode(agentName, modeId);
	} catch (error) {
		if (modeMutationVersions.isCurrent(agentName, mutationVersion)) {
			updateAgentModeState(agentName, { currentModeId: previousModeId });
		}
		throw error;
	}
}

/** Check if currently in plan mode. */
export function isInPlanMode(modeId: string): boolean {
	const lower = modeId.toLowerCase();
	return lower === 'plan' || lower === 'architect' || lower.includes('plan');
}

let bound = false;

/** Cache mode callbacks by agent; panes select only their own agent's state. */
export function bindModeListener(): void {
	if (bound) return;
	bound = true;

	onModesAvailable((agentName, modeState) => {
		updateAgentModeState(agentName, {
			modes: modeState.modes ?? [],
			currentModeId: modeState.currentModeId || modeState.modes?.[0]?.id || '',
			isLoading: false,
			loaded: true
		});
	});

	onModeChanged((agentName, modeId) => {
		updateAgentModeState(agentName, { currentModeId: modeId, loaded: true });
	});
}
