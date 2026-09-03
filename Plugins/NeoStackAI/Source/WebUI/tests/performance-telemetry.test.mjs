import assert from 'node:assert/strict';
import test from 'node:test';

import {
	beginKeyedPerformanceSpan,
	beginPerformanceSpan,
	endKeyedPerformanceSpan,
	endPerformanceSpan,
	getPerformanceSnapshot,
	PERFORMANCE_BUDGETS,
	resetPerformanceTelemetryForTests,
	takePerformanceRecordsForExport
} from '../src/lib/performanceTelemetry.js';

test.beforeEach(resetPerformanceTelemetryForTests);

test('performance records are bounded and include explicit budgets', () => {
	for (let index = 0; index < 250; index += 1) {
		endPerformanceSpan(beginPerformanceSpan('composer_input', { index }));
	}
	const snapshot = getPerformanceSnapshot();
	assert.equal(snapshot.records.length, 200);
	assert.equal(snapshot.budgets.composer_input, 50);
	assert.equal(snapshot.budgets.dom_nodes, 2_500);
});

test('keyed spans isolate concurrent sessions', () => {
	beginKeyedPerformanceSpan('prompt_to_first_visible_update', 'session-a');
	beginKeyedPerformanceSpan('prompt_to_first_visible_update', 'session-b');
	assert.equal(getPerformanceSnapshot().activeSpanCount, 2);

	endKeyedPerformanceSpan('prompt_to_first_visible_update', 'session-a');
	assert.equal(getPerformanceSnapshot().activeSpanCount, 1);
	endKeyedPerformanceSpan('prompt_to_first_visible_update', 'session-b');
	assert.equal(getPerformanceSnapshot().activeSpanCount, 0);
	assert.equal(PERFORMANCE_BUDGETS.prompt_to_first_visible_update, 10_000);
});

test('native export takes each bounded record at most once', () => {
	endPerformanceSpan(
		beginPerformanceSpan('composer_input', { privateSessionId: 'never-exported' })
	);
	const first = takePerformanceRecordsForExport();
	assert.equal(first.length, 1);
	assert.equal(typeof first[0].sequence, 'number');
	assert.equal(takePerformanceRecordsForExport().length, 0);

	endPerformanceSpan(beginPerformanceSpan('long_task'));
	const second = takePerformanceRecordsForExport();
	assert.deepEqual(
		second.map((record) => record.name),
		['long_task']
	);
});
