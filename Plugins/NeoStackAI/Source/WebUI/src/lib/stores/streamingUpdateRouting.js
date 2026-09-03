/** @typedef {import('../bridge.js').StreamingUpdate} StreamingUpdate */

const assistantMessageUpdateTypes = new Set([
	'text_chunk',
	'thought_chunk',
	'tool_call',
	'tool_result',
	'error'
]);

/**
 * Plan, usage, replay-control, and unknown events have dedicated routes and
 * must never create a visible assistant turn.
 * @param {StreamingUpdate} update
 */
export function isAssistantMessageUpdate(update) {
	return assistantMessageUpdateTypes.has(update.type);
}
