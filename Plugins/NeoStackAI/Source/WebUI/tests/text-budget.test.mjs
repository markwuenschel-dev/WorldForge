import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { createBoundedTextView, MAX_RENDERED_TOOL_TEXT_CHARS } from '../src/lib/textBudget.js';

describe('tool output text budget', () => {
	it('caps a multi-megabyte single line before rendering', () => {
		const view = createBoundedTextView('x'.repeat(2 * 1024 * 1024), 4);
		assert.equal(view.full.length, MAX_RENDERED_TOOL_TEXT_CHARS);
		assert.equal(view.preview.length, MAX_RENDERED_TOOL_TEXT_CHARS);
		assert.equal(view.truncated, true);
		assert.equal(view.omittedChars, 2 * 1024 * 1024 - MAX_RENDERED_TOOL_TEXT_CHARS);
	});

	it('builds a preview without splitting the complete output', () => {
		const view = createBoundedTextView('one\ntwo\nthree\nfour\nfive', 4);
		assert.equal(view.preview, 'one\ntwo\nthree\nfour');
		assert.equal(view.lineCount, 5);
		assert.equal(view.remainingLines, 1);
	});
});
