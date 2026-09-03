export const MAX_TRANSCRIPT_SEARCH_RESULTS = 500;

/**
 * Search the complete normalized transcript, independent of which rows happen
 * to be mounted. Results are stable message/block identifiers rather than DOM
 * Range objects that detach during streaming.
 *
 * @param {Array<{messageId: string, contentBlocks: Array<{text?: string, toolArguments?: string, toolResult?: string}>}>} messages
 * @param {string} query
 * @param {number} [limit]
 */
export function searchTranscript(messages, query, limit = MAX_TRANSCRIPT_SEARCH_RESULTS) {
	const needle = query.trim().toLocaleLowerCase();
	if (!needle) return [];
	const results = [];

	for (const message of messages) {
		for (let blockIndex = 0; blockIndex < message.contentBlocks.length; blockIndex += 1) {
			const block = message.contentBlocks[blockIndex];
			const haystack = [block.text, block.toolArguments, block.toolResult]
				.filter(Boolean)
				.join('\n')
				.toLocaleLowerCase();
			let offset = 0;
			while (offset < haystack.length) {
				const matchOffset = haystack.indexOf(needle, offset);
				if (matchOffset < 0) break;
				results.push({ messageId: message.messageId, blockIndex, offset: matchOffset });
				if (results.length >= limit) return results;
				offset = matchOffset + Math.max(needle.length, 1);
			}
		}
	}

	return results;
}
