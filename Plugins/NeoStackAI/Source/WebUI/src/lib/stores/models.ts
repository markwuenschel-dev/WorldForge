import { writable, get } from 'svelte/store';
import {
	getModels,
	getAllModels,
	setModel as bridgeSetModel,
	getReasoningLevel,
	setReasoningLevel as bridgeSetReasoningLevel,
	onModelsAvailable,
	type ModelInfo
} from '$lib/bridge.js';
import { selectedAgent } from '$lib/stores/agents.js';
import { createOperationVersionTracker } from '$lib/operationVersions.js';

export type ReasoningLevel = 'none' | 'low' | 'medium' | 'high' | 'max';

export type AgentModelState = {
	models: ModelInfo[];
	currentModelId: string;
	isLoading: boolean;
	reasoningLevel: ReasoningLevel;
	isLoadingReasoning: boolean;
	reasoningLoaded: boolean;
};

const createDefaultAgentModelState = (): AgentModelState => ({
	models: [],
	currentModelId: '',
	isLoading: false,
	reasoningLevel: 'high',
	isLoadingReasoning: false,
	reasoningLoaded: false
});

/** Authoritative model/reasoning state keyed by agent for every visible pane. */
export const modelStatesByAgent = writable<Record<string, AgentModelState>>({});

// Legacy focused-agent stores are retained for the route-level model browser.
// Chat panes must read modelStatesByAgent using their own session agent.
export const models = writable<ModelInfo[]>([]);
export const currentModelId = writable<string>('');
export const isLoadingModels = writable(false);
export const reasoningLevel = writable<ReasoningLevel>('high');
export const modelBrowserOpen = writable(false);
export const allModels = writable<ModelInfo[]>([]);
export const isLoadingAllModels = writable(false);

const fullModelCache = new Map<string, ModelInfo[]>();
const modelLoadVersions = createOperationVersionTracker();
const reasoningLoadVersions = createOperationVersionTracker();
const modelMutationVersions = createOperationVersionTracker();
const reasoningMutationVersions = createOperationVersionTracker();

function getAgentModelState(agentName: string): AgentModelState {
	return get(modelStatesByAgent)[agentName] ?? createDefaultAgentModelState();
}

function syncFocusedAgentStores(agentName: string, state: AgentModelState): void {
	if (get(selectedAgent)?.name !== agentName) return;
	models.set(state.models);
	currentModelId.set(state.currentModelId);
	isLoadingModels.set(state.isLoading);
	reasoningLevel.set(state.reasoningLevel);
}

function updateAgentModelState(
	agentName: string,
	update: Partial<AgentModelState> | ((state: AgentModelState) => AgentModelState)
): AgentModelState {
	let nextState = createDefaultAgentModelState();
	modelStatesByAgent.update((states) => {
		const current = states[agentName] ?? createDefaultAgentModelState();
		nextState = typeof update === 'function' ? update(current) : { ...current, ...update };
		return { ...states, [agentName]: nextState };
	});
	syncFocusedAgentStores(agentName, nextState);
	return nextState;
}

/** Load models for an agent without changing another pane's visible state. */
export async function loadModelsForAgent(agentName: string): Promise<void> {
	if (!agentName) return;
	const existing = getAgentModelState(agentName);
	if (existing.isLoading) return;
	if (existing.models.length > 0 && !existing.isLoading) {
		syncFocusedAgentStores(agentName, existing);
		return;
	}

	const requestVersion = modelLoadVersions.begin(agentName);
	updateAgentModelState(agentName, { isLoading: true });
	try {
		const state = await getModels(agentName);
		if (!modelLoadVersions.isCurrent(agentName, requestVersion)) return;
		const nextModels = state.models ?? [];
		const currentId = state.currentModelId || nextModels[0]?.id || '';
		updateAgentModelState(agentName, {
			models: nextModels,
			currentModelId: currentId,
			isLoading: false
		});
	} catch (error) {
		if (!modelLoadVersions.isCurrent(agentName, requestVersion)) return;
		console.warn(`Failed to load models for ${agentName}:`, error);
		updateAgentModelState(agentName, { models: [], currentModelId: '', isLoading: false });
	}
}

/** Load an agent's reasoning level with per-agent stale-response protection. */
export async function loadReasoningLevel(agentName: string): Promise<void> {
	if (!agentName) return;
	const existing = getAgentModelState(agentName);
	if (existing.isLoadingReasoning) return;
	if (existing.reasoningLoaded && !existing.isLoadingReasoning) {
		syncFocusedAgentStores(agentName, existing);
		return;
	}

	const requestVersion = reasoningLoadVersions.begin(agentName);
	updateAgentModelState(agentName, { isLoadingReasoning: true });
	try {
		const level = await getReasoningLevel(agentName);
		if (!reasoningLoadVersions.isCurrent(agentName, requestVersion)) return;
		updateAgentModelState(agentName, {
			reasoningLevel: (level || 'high') as ReasoningLevel,
			isLoadingReasoning: false,
			reasoningLoaded: true
		});
	} catch (error) {
		if (!reasoningLoadVersions.isCurrent(agentName, requestVersion)) return;
		console.warn(`Failed to load reasoning level for ${agentName}:`, error);
		updateAgentModelState(agentName, { isLoadingReasoning: false });
	}
}

/** Change an agent's active model without allowing an old failure to roll back a newer choice. */
export async function changeModel(agentName: string, modelId: string): Promise<void> {
	if (!agentName || !modelId) return;
	const previousState = getAgentModelState(agentName);
	const mutationVersion = modelMutationVersions.begin(agentName);
	updateAgentModelState(agentName, { currentModelId: modelId });

	try {
		await bridgeSetModel(agentName, modelId);
		if (!modelMutationVersions.isCurrent(agentName, mutationVersion)) return;

		const current = getAgentModelState(agentName);
		if (!current.models.some((model) => model.id === modelId)) {
			const knownFromFull = fullModelCache.get(agentName)?.find((model) => model.id === modelId);
			if (knownFromFull) {
				updateAgentModelState(agentName, {
					models: [knownFromFull, ...current.models],
					currentModelId: modelId
				});
			}
		}
	} catch (error) {
		if (modelMutationVersions.isCurrent(agentName, mutationVersion)) {
			updateAgentModelState(agentName, {
				models: previousState.models,
				currentModelId: previousState.currentModelId
			});
		}
		throw error;
	}
}

/** Open searchable full model browser for an agent. */
export async function openModelBrowser(agentName: string): Promise<void> {
	modelBrowserOpen.set(true);

	const cached = fullModelCache.get(agentName);
	if (cached && cached.length > 0) {
		allModels.set(cached);
		return;
	}

	isLoadingAllModels.set(true);
	try {
		const state = await getAllModels(agentName);
		const list = state.models
			.filter((model) => model.id)
			.sort((a, b) => a.name.localeCompare(b.name));
		fullModelCache.set(agentName, list);
		allModels.set(list);
	} catch (error) {
		console.warn('Failed to load full model catalog:', error);
		allModels.set([]);
	} finally {
		isLoadingAllModels.set(false);
	}
}

export function closeModelBrowser(): void {
	modelBrowserOpen.set(false);
}

/** Change reasoning effort without allowing an old failure to roll back a newer choice. */
export async function changeReasoningLevel(
	level: ReasoningLevel,
	agentName?: string
): Promise<void> {
	const targetAgentName = agentName || get(selectedAgent)?.name;
	if (!targetAgentName) return;

	const previousLevel = getAgentModelState(targetAgentName).reasoningLevel;
	const mutationVersion = reasoningMutationVersions.begin(targetAgentName);
	updateAgentModelState(targetAgentName, { reasoningLevel: level, reasoningLoaded: true });
	try {
		await bridgeSetReasoningLevel(targetAgentName, level);
	} catch (error) {
		if (reasoningMutationVersions.isCurrent(targetAgentName, mutationVersion)) {
			updateAgentModelState(targetAgentName, { reasoningLevel: previousLevel });
		}
		throw error;
	}
}

/** Display labels for reasoning levels. */
export const reasoningLabels: Record<ReasoningLevel, string> = {
	none: 'Off',
	low: 'Low',
	medium: 'Medium',
	high: 'High',
	max: 'Max'
};

let bound = false;

/** Cache model pushes by agent; panes select only their own agent's state. */
export function bindModelsListener(): void {
	if (bound) return;
	bound = true;

	onModelsAvailable((agentName, modelState) => {
		const nextModels = modelState.models ?? [];
		updateAgentModelState(agentName, {
			models: nextModels,
			currentModelId: modelState.currentModelId || nextModels[0]?.id || '',
			isLoading: false
		});
	});
}
