import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { createBridgeBindingRegistry } from '../src/lib/bridgeLifecycle.js';

describe('bridge lifecycle', () => {
	it('binds each event exactly once per bridge generation and recovers after loss', () => {
		const registry = createBridgeBindingRegistry();
		const bridgeA = { name: 'a' };
		const bridgeB = { name: 'b' };
		const messageBindings = [];
		const stateBindings = [];

		registry.register('message', (bridge) => messageBindings.push(bridge.name));
		registry.register('state', (bridge) => stateBindings.push(bridge.name));
		registry.refresh(null);
		registry.refresh(bridgeA);
		registry.refresh(bridgeA);
		registry.refresh(null);
		registry.refresh(bridgeB);
		registry.refresh(bridgeB);

		assert.deepEqual(messageBindings, ['a', 'b']);
		assert.deepEqual(stateBindings, ['a', 'b']);
	});

	it('binds a listener registered after the bridge is already ready', () => {
		const registry = createBridgeBindingRegistry();
		const bridge = { name: 'late-listener' };
		const bindings = [];

		registry.refresh(bridge);
		registry.register('message', (current) => bindings.push(current.name));

		assert.deepEqual(bindings, ['late-listener']);
	});

	it('recovers after an embedded bridge arrives more than 60 seconds late', () => {
		const registry = createBridgeBindingRegistry();
		const bindings = [];
		let elapsedMs = 0;
		registry.register('message', (bridge) => bindings.push({ bridge: bridge.name, elapsedMs }));

		for (let attempt = 0; attempt < 120; attempt += 1) {
			elapsedMs += 500;
			registry.refresh(null);
		}
		registry.refresh({ name: 'late-native-bridge' });
		registry.refresh({ name: 'replacement-bridge' });

		assert.deepEqual(bindings, [
			{ bridge: 'late-native-bridge', elapsedMs: 60_000 },
			{ bridge: 'replacement-bridge', elapsedMs: 60_000 }
		]);
	});
});
