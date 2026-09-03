/**
 * Keeps native event subscriptions attached to the current bridge object.
 * A CEF bridge replacement is treated as a new generation, while repeated
 * readiness events for the same object are idempotent.
 */
export function createBridgeBindingRegistry() {
	/** @typedef {{ bind: (bridge: any) => void, lastBridge: any | null }} BridgeBinding */
	/** @type {Map<string, { bind: (bridge: any) => void, lastBridge: any | null }>} */
	const bindings = new Map();
	/** @type {Set<(available: boolean, generation: number) => void>} */
	const availabilityListeners = new Set();
	/** @type {any | null} */
	let currentBridge = null;
	let generation = 0;

	/** @param {BridgeBinding} entry */
	const bindCurrent = (entry) => {
		if (!currentBridge || entry.lastBridge === currentBridge) return;
		entry.bind(currentBridge);
		entry.lastBridge = currentBridge;
	};

	return {
		/** @param {string} key @param {(bridge: any) => void} bind */
		register(key, bind) {
			const existing = bindings.get(key);
			const entry = { bind, lastBridge: existing?.lastBridge ?? null };
			bindings.set(key, entry);
			bindCurrent(entry);
		},
		/** @param {any | null | undefined} bridge */
		refresh(bridge) {
			const nextBridge = bridge ?? null;
			if (nextBridge === currentBridge) return;
			currentBridge = nextBridge;
			generation += 1;

			if (!currentBridge) {
				for (const entry of bindings.values()) entry.lastBridge = null;
			} else {
				for (const entry of bindings.values()) bindCurrent(entry);
			}

			for (const listener of availabilityListeners) {
				listener(Boolean(currentBridge), generation);
			}
		},
		/** @param {(available: boolean, generation: number) => void} listener */
		subscribe(listener) {
			availabilityListeners.add(listener);
			return () => availabilityListeners.delete(listener);
		},
		isAvailable() {
			return Boolean(currentBridge);
		}
	};
}
