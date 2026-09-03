import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { isAssistantMessageUpdate } from '../src/lib/stores/streamingUpdateRouting.js';

const update = (type, text = '') => ({ agentName: 'fixture-agent', type, text });

describe('streaming update routing', () => {
	it('preserves mixed renderable chronology and rejects blank-message events', () => {
		const fixture = [
			update('text_chunk', 'first'),
			update('thought_chunk', 'second'),
			update('text_chunk', 'third'),
			update('plan', 'not a message'),
			update('unknown', 'not a message')
		];

		const routed = fixture.filter(isAssistantMessageUpdate);
		assert.deepEqual(
			routed.map(({ type, text }) => [type, text]),
			[
				['text_chunk', 'first'],
				['thought_chunk', 'second'],
				['text_chunk', 'third']
			]
		);
	});

	it('accepts only assistant content events', () => {
		assert.equal(isAssistantMessageUpdate(update('tool_result')), true);
		assert.equal(isAssistantMessageUpdate(update('error')), true);
		assert.equal(isAssistantMessageUpdate(update('usage')), false);
		assert.equal(isAssistantMessageUpdate(update('history_replay_finished')), false);
	});
});
