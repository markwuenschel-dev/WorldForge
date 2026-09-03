import { writable, derived } from 'svelte/store';
import { getSourceControlStatus, type SourceControlStatus } from '$lib/bridge.js';

const emptyStatus: SourceControlStatus = {
	enabled: false,
	provider: '',
	branch: '',
	changesCount: -1,
	connected: false
};

/** Current source control status */
export const scStatus = writable<SourceControlStatus>({ ...emptyStatus });

/** Whether source control is enabled */
export const scEnabled = derived(scStatus, (s) => s.enabled);

/** Current branch name (empty if no VCS) */
export const branchName = derived(scStatus, (s) => s.branch || '');

/** Whether there are known pending changes (changesCount > 0) */
export const hasChanges = derived(scStatus, (s) => s.changesCount > 0);

/** Display label for change count, e.g. "+3" — empty if unknown or zero */
export const changesLabel = derived(scStatus, (s) =>
	s.changesCount > 0 ? `+${s.changesCount}` : ''
);

let pollInterval: ReturnType<typeof setInterval> | null = null;
let visibilityListenerBound = false;

/** Fetch source control status from C++ bridge */
async function fetchStatus(): Promise<void> {
	try {
		const status = await getSourceControlStatus();
		scStatus.set(status);
	} catch (e) {
		console.warn('Source control status fetch failed:', e);
	}
}

/** Tick the poll — skipped when the tab is hidden to avoid idle bridge chatter. */
function tick(): void {
	if (typeof document !== 'undefined' && document.hidden) return;
	fetchStatus();
}

/** Load source control status once and start polling every 30s */
export function loadSourceControlStatus(): void {
	fetchStatus();
	if (!pollInterval) {
		pollInterval = setInterval(tick, 30_000);
	}
	if (!visibilityListenerBound && typeof document !== 'undefined') {
		visibilityListenerBound = true;
		// Refresh immediately when the tab becomes visible again.
		document.addEventListener('visibilitychange', () => {
			if (!document.hidden) fetchStatus();
		});
	}
}

/** Stop polling (call on unmount if needed) */
export function stopSourceControlPolling(): void {
	if (pollInterval) {
		clearInterval(pollInterval);
		pollInterval = null;
	}
}
