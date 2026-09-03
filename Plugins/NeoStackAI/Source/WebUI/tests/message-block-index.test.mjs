import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { buildMessageBlockIndex } from '../src/lib/messageBlockIndex.js';

describe('message block index', () => {
	it('keeps a live Task parent visible while nesting hundreds of children', () => {
		const blocks = [{ type: 'tool_call', toolCallId: 'task', toolName: 'Task' }];
		for (let index = 0; index < 500; index += 1) {
			blocks.push({ type: 'tool_call', toolCallId: `child-${index}`, toolName: 'Read' });
			blocks.push({ type: 'tool_result', toolCallId: `child-${index}` });
		}

		const index = buildMessageBlockIndex(blocks);

		assert.deepEqual(
			index.topLevelRows.map((row) => row.block.toolCallId),
			['task']
		);
		assert.equal(index.parentToChildren.task.length, 500);
		assert.equal(index.resultByCallId['child-499'].type, 'tool_result');
	});

	it('normalizes deeply nested legacy Tasks without duplicating rows', () => {
		const blocks = [];
		for (let depth = 0; depth < 50; depth += 1) {
			blocks.push({ type: 'tool_call', toolCallId: `task-${depth}`, toolName: 'Task' });
		}
		blocks.push({ type: 'tool_call', toolCallId: 'leaf', toolName: 'Read' });
		blocks.push({ type: 'tool_result', toolCallId: 'leaf' });
		for (let depth = 49; depth >= 0; depth -= 1) {
			blocks.push({ type: 'tool_result', toolCallId: `task-${depth}` });
		}

		const index = buildMessageBlockIndex(blocks);

		assert.equal(index.topLevelRows.length, 1);
		assert.equal(index.topLevelRows[0].block.toolCallId, 'task-0');
		assert.deepEqual(index.parentToChildren['task-49'], ['leaf']);
	});
});
