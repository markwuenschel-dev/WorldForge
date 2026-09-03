import assert from 'node:assert/strict';
import test from 'node:test';

import { isResponseImageSourceAllowed } from '../src/lib/imagePolicy.js';
import { buildMessageBlockIndex } from '../src/lib/messageBlockIndex.js';
import { createBoundedTextView, MAX_RENDERED_TOOL_TEXT_CHARS } from '../src/lib/textBudget.js';
import { buildVirtualRows, getVisibleVirtualRows } from '../src/lib/virtualRows.js';
import { createLongTranscriptFixture } from './fixtures/long-transcript.mjs';

const fixture = createLongTranscriptFixture();

test('renderer fixture covers every pathological transcript shape', () => {
	assert.equal(fixture.messages.length, 3_000);
	assert.equal(fixture.images.length, 128);
	assert.ok(fixture.multiMegabyteLine.length >= 2 * 1024 * 1024);
	assert.match(fixture.markdown, /```typescript/);
	assert.match(fixture.markdown, /```mermaid/);
	assert.match(fixture.markdown, /E = mc\^2/);
	assert.match(fixture.markdown, /https:\/\/tracker\.invalid/);
});

test('thousands of messages and hundreds of tools stay bounded', () => {
	const layout = buildVirtualRows(
		fixture.messages,
		(message) => message.messageId,
		{},
		() => 120
	);
	const visible = getVisibleVirtualRows(layout.rows, 180_000, 900, 700);
	assert.ok(visible.length <= 24, `mounted row count was ${visible.length}`);

	const index = buildMessageBlockIndex(fixture.heavyBlocks);
	assert.equal(index.parentToChildren['task-49'].length, 500);
	assert.equal(index.topLevelRows.length, 1);
	assert.equal(index.resultByCallId['tool-499'].toolResult, 'ok');

	const output = createBoundedTextView(fixture.multiMegabyteLine, 8);
	assert.equal(output.full.length, MAX_RENDERED_TOOL_TEXT_CHARS);
	assert.equal(output.truncated, true);
});

test('remote response images are blocked while bounded local sources remain available', () => {
	assert.equal(isResponseImageSourceAllowed('https://tracker.invalid/pixel.png'), false);
	assert.equal(isResponseImageSourceAllowed('http://tracker.invalid/pixel.png'), false);
	assert.equal(isResponseImageSourceAllowed('data:image/png;base64,iVBORw0KGgo='), true);
	assert.equal(isResponseImageSourceAllowed('blob:http://localhost/image-id'), true);
});
