import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { MAX_TRANSCRIPT_SEARCH_RESULTS, searchTranscript } from '../src/lib/transcriptSearch.js';

describe('transcript search', () => {
	it('searches messages that are outside the mounted window', () => {
		const messages = Array.from({ length: 2_000 }, (_, index) => ({
			messageId: `message-${index}`,
			contentBlocks: [{ text: index === 10 ? 'needle in old history' : `message ${index}` }]
		}));

		assert.deepEqual(searchTranscript(messages, 'needle'), [
			{ messageId: 'message-10', blockIndex: 0, offset: 0 }
		]);
	});

	it('caps pathological result counts', () => {
		const messages = [{ messageId: 'many', contentBlocks: [{ text: 'x '.repeat(5_000) }] }];
		assert.equal(searchTranscript(messages, 'x').length, MAX_TRANSCRIPT_SEARCH_RESULTS);
	});
});
