import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { createOperationVersionTracker } from '../src/lib/operationVersions.js';

function deferred() {
	let resolve;
	const promise = new Promise((complete) => {
		resolve = complete;
	});
	return { promise, resolve };
}

describe('operation versions', () => {
	it('rejects an older completion after a newer operation commits', async () => {
		const tracker = createOperationVersionTracker();
		const slow = deferred();
		const fast = deferred();
		let state = 'initial';

		const apply = async (request, value) => {
			const version = tracker.begin('selected-session');
			await request.promise;
			if (tracker.isCurrent('selected-session', version)) state = value;
		};

		const oldOperation = apply(slow, 'session-a');
		const newOperation = apply(fast, 'session-b');
		fast.resolve();
		await newOperation;
		slow.resolve();
		await oldOperation;

		assert.equal(state, 'session-b');
	});

	it('isolates versions by agent and invalidates pending work explicitly', () => {
		const tracker = createOperationVersionTracker();
		const claudeVersion = tracker.begin('claude');
		const codexVersion = tracker.begin('codex');

		tracker.invalidate('claude');

		assert.equal(tracker.isCurrent('claude', claudeVersion), false);
		assert.equal(tracker.isCurrent('codex', codexVersion), true);
	});

	it('isolates concurrent pane model, mode, and reasoning mutations by agent', () => {
		const tracker = createOperationVersionTracker();
		const paneState = {
			Claude: { model: 'claude-a', mode: 'code', reasoning: 'high' },
			Codex: { model: 'codex-a', mode: 'agent', reasoning: 'medium' }
		};

		const claudeModel = tracker.begin('Claude:model');
		const codexModel = tracker.begin('Codex:model');
		const claudeMode = tracker.begin('Claude:mode');
		const codexReasoning = tracker.begin('Codex:reasoning');
		paneState.Claude.model = 'claude-b';
		paneState.Codex.model = 'codex-b';
		paneState.Claude.mode = 'plan';
		paneState.Codex.reasoning = 'max';

		assert.equal(tracker.isCurrent('Claude:model', claudeModel), true);
		assert.equal(tracker.isCurrent('Codex:model', codexModel), true);
		assert.equal(tracker.isCurrent('Claude:mode', claudeMode), true);
		assert.equal(tracker.isCurrent('Codex:reasoning', codexReasoning), true);
		assert.deepEqual(paneState.Claude, {
			model: 'claude-b',
			mode: 'plan',
			reasoning: 'high'
		});
		assert.deepEqual(paneState.Codex, {
			model: 'codex-b',
			mode: 'agent',
			reasoning: 'max'
		});
	});
});
