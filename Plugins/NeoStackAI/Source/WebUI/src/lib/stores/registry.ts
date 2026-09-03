import { writable } from 'svelte/store';
import {
	type RegistryAgent,
	type AgentUpdateInfo,
	getRegistryAgents,
	getAgentUpdates,
	installRegistryAgent,
	uninstallRegistryAgent,
	updateRegistryAgent,
	refreshRegistry
} from '$lib/bridge.js';
import { loadAgents } from '$lib/stores/agents.js';

// ── State ───────────────────────────────────────────────────────────

export const registryAgents = writable<RegistryAgent[]>([]);
export const registryLoaded = writable(false);
export const registryLoading = writable(false);

/** Track which agents are currently being installed */
export const installingAgents = writable<Set<string>>(new Set());

/** Updates available for installed agents (refreshed alongside the registry). */
export const agentUpdates = writable<AgentUpdateInfo[]>([]);

/** Track which agents are currently being updated (button spinner state). */
export const updatingAgents = writable<Set<string>>(new Set());

// ── Actions ─────────────────────────────────────────────────────────

export async function loadAgentUpdates(): Promise<void> {
	try {
		const updates = await getAgentUpdates();
		agentUpdates.set(updates);
	} catch (e) {
		console.warn('Failed to load agent updates:', e);
	}
}

export async function loadRegistry(): Promise<void> {
	registryLoading.set(true);
	try {
		const agents = await getRegistryAgents();
		registryAgents.set(agents);
		registryLoaded.set(true);
		// Refresh update info alongside the registry so the chat banner stays in sync.
		await loadAgentUpdates();
	} catch (e) {
		console.warn('Failed to load registry:', e);
	} finally {
		registryLoading.set(false);
	}
}

export async function refreshRegistryData(): Promise<void> {
	await refreshRegistry();
	// After CDN refresh, reload the data
	await loadRegistry();
}

export async function installAgent(agentId: string, method: string = 'auto'): Promise<void> {
	installingAgents.update((set) => {
		const next = new Set(set);
		next.add(agentId);
		return next;
	});

	try {
		await installRegistryAgent(agentId, method);
		// Reload registry panel + sidebar agent list
		await loadRegistry();
		await loadAgents();
	} catch (e) {
		console.warn('Install failed:', e);
		throw e;
	} finally {
		installingAgents.update((set) => {
			const next = new Set(set);
			next.delete(agentId);
			return next;
		});
	}
}

export async function uninstallAgent(agentId: string): Promise<void> {
	try {
		await uninstallRegistryAgent(agentId);
		await loadRegistry();
		await loadAgents();
	} catch (e) {
		console.warn('Uninstall failed:', e);
	}
}

/**
 * Trigger an update for a registry agent. Removes the old install so the next launch
 * downloads the latest version. The user must open a new session to pick it up — this
 * function does NOT force-disconnect the active session (that would lose unsaved chat
 * state); the banner copy makes the restart requirement explicit.
 */
export async function updateAgent(agentId: string): Promise<void> {
	updatingAgents.update((set) => {
		const next = new Set(set);
		next.add(agentId);
		return next;
	});

	try {
		await updateRegistryAgent(agentId);
		// Refresh registry + updates so the banner clears (updateAvailable=false now).
		await loadRegistry();
		await loadAgents();
	} catch (e) {
		console.warn('Update failed:', e);
	} finally {
		updatingAgents.update((set) => {
			const next = new Set(set);
			next.delete(agentId);
			return next;
		});
	}
}
