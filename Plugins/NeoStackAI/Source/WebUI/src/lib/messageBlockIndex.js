/**
 * Normalize a message's flat content-block stream into stable top-level rows
 * and O(1) tool result/child lookups. Legacy Task sessions without explicit
 * parent ids are reconstructed with a stack in one pass.
 *
 * @template {{ type: string, toolCallId?: string, toolName?: string, parentToolCallId?: string }} T
 * @param {T[]} blocks
 */
export function buildMessageBlockIndex(blocks) {
	/** @type {Record<string, T>} */
	const resultByCallId = {};
	/** @type {Record<string, T>} */
	const toolCallById = {};
	/** @type {Record<string, string>} */
	const childToParent = {};
	/** @type {Record<string, string[]>} */
	const parentToChildren = {};

	for (const block of blocks) {
		if (block.type === 'tool_call' && block.toolCallId) {
			toolCallById[block.toolCallId] = block;
			if (block.parentToolCallId) {
				childToParent[block.toolCallId] = block.parentToolCallId;
				(parentToChildren[block.parentToolCallId] ??= []).push(block.toolCallId);
			}
		} else if (block.type === 'tool_result' && block.toolCallId) {
			resultByCallId[block.toolCallId] = block;
		}
	}

	/** @type {string[]} */
	const legacyTaskStack = [];
	for (const block of blocks) {
		if (block.type === 'tool_call' && block.toolCallId && !block.parentToolCallId) {
			const parentId = legacyTaskStack.at(-1);
			if (parentId && !childToParent[block.toolCallId]) {
				childToParent[block.toolCallId] = parentId;
				(parentToChildren[parentId] ??= []).push(block.toolCallId);
			}
			if (block.toolName === 'Task') legacyTaskStack.push(block.toolCallId);
		} else if (block.type === 'tool_result' && block.toolCallId) {
			const taskIndex = legacyTaskStack.lastIndexOf(block.toolCallId);
			if (taskIndex >= 0) legacyTaskStack.splice(taskIndex);
		}
	}

	const topLevelRows = blocks
		.map((block, sourceIndex) => ({ block, sourceIndex }))
		.filter(
			({ block }) =>
				block.type !== 'tool_result' &&
				!(block.type === 'tool_call' && block.toolCallId && childToParent[block.toolCallId])
		);

	return {
		resultByCallId,
		toolCallById,
		childToParent,
		parentToChildren,
		topLevelRows
	};
}
