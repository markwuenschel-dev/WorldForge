/** @typedef {(sessionId: string) => void} SessionDisposalListener */

/** @type {Set<SessionDisposalListener>} */
const disposalListeners = new Set();
/** @type {Set<string>} */
const disposedSessionIds = new Set();

/**
 * Register one singleton store's per-session cleanup hook.
 * @param {SessionDisposalListener} listener
 */
export function onSessionDisposed(listener) {
	disposalListeners.add(listener);
	return () => disposalListeners.delete(listener);
}

/**
 * Fan a confirmed deletion out to every session-scoped frontend store.
 * @param {string} sessionId
 */
export function disposeSessionState(sessionId) {
	disposedSessionIds.add(sessionId);
	for (const listener of disposalListeners) listener(sessionId);
}

/**
 * Ignore callbacks that race a confirmed deletion.
 * @param {string} sessionId
 */
export function isSessionDisposed(sessionId) {
	return disposedSessionIds.has(sessionId);
}

/**
 * Allows canonical hydration to re-admit an ID if a backend restores it.
 * @param {string} sessionId
 */
export function markSessionActive(sessionId) {
	disposedSessionIds.delete(sessionId);
}
