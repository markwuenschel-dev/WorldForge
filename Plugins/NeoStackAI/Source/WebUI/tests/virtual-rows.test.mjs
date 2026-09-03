import assert from 'node:assert/strict';
import test from 'node:test';

import {
	buildVirtualRows,
	getAnchorAdjustment,
	getVisibleVirtualRows
} from '../src/lib/virtualRows.js';

const messages = Array.from({ length: 10_000 }, (_, index) => ({ id: `message-${index}` }));

test('long transcripts mount a bounded viewport subset', () => {
	const layout = buildVirtualRows(
		messages,
		(message) => message.id,
		{},
		() => 120
	);
	const visible = getVisibleVirtualRows(layout.rows, 600_000, 900, 600);

	assert.equal(layout.totalHeight, 1_200_000);
	assert.ok(visible.length > 0);
	assert.ok(visible.length <= 20, `expected no more than 20 mounted rows, got ${visible.length}`);
	assert.ok(visible[0].index > 4_000);
});

test('measured heights replace estimates and preserve cumulative positions', () => {
	const layout = buildVirtualRows(
		messages.slice(0, 4),
		(message) => message.id,
		{ 'message-1': 360 },
		() => 100
	);

	assert.deepEqual(
		layout.rows.map(({ top, height }) => ({ top, height })),
		[
			{ top: 0, height: 100 },
			{ top: 100, height: 360 },
			{ top: 460, height: 100 },
			{ top: 560, height: 100 }
		]
	);
	assert.equal(layout.totalHeight, 660);
});

test('height changes above the viewport return an exact anchor correction', () => {
	assert.equal(getAnchorAdjustment(100, 500, 120, 320), 200);
	assert.equal(getAnchorAdjustment(600, 500, 120, 320), 0);
});
