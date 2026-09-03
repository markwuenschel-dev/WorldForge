import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { describe, it } from 'node:test';
import {
	disposeSessionState,
	isSessionDisposed,
	markSessionActive,
	onSessionDisposed
} from '../src/lib/stores/sessionLifecycle.js';

describe('session lifecycle', () => {
	it('fans deletion out once to every registered store and rejects late events', () => {
		const calls = [];
		const removeFirst = onSessionDisposed((sessionId) => calls.push(`first:${sessionId}`));
		const removeSecond = onSessionDisposed((sessionId) => calls.push(`second:${sessionId}`));

		disposeSessionState('deleted-session');
		assert.deepEqual(calls, ['first:deleted-session', 'second:deleted-session']);
		assert.equal(isSessionDisposed('deleted-session'), true);

		markSessionActive('deleted-session');
		assert.equal(isSessionDisposed('deleted-session'), false);

		removeFirst();
		removeSecond();
	});

	it('keeps every session-owned production store on the central disposal fan-out', async () => {
		const storeNames = [
			'agentState.ts',
			'attachments.ts',
			'commands.ts',
			'configOptions.ts',
			'messages.ts',
			'panes.svelte.ts',
			'permissions.ts',
			'plan.ts',
			'usage.ts'
		];
		for (const storeName of storeNames) {
			const source = await readFile(
				new URL(`../src/lib/stores/${storeName}`, import.meta.url),
				'utf8'
			);
			assert.match(source, /onSessionDisposed\(/, `${storeName} bypasses central session disposal`);
		}
		const sessionsSource = await readFile(
			new URL('../src/lib/stores/sessions.ts', import.meta.url),
			'utf8'
		);
		assert.match(sessionsSource, /disposeSessionState\(sessionId\)/);
	});
});
