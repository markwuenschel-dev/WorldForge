export const MAX_RENDERED_TOOL_TEXT_CHARS = 200_000;

/**
 * Bounds tool output before it reaches a <pre>. It never splits the complete
 * string into an array, so a multi-megabyte single line cannot bypass the cap
 * or create a second large allocation.
 *
 * @param {string} text
 * @param {number} previewLines
 * @param {number} [maxChars]
 */
export function createBoundedTextView(text, previewLines, maxChars = MAX_RENDERED_TOOL_TEXT_CHARS) {
	const truncated = text.length > maxChars;
	const full = truncated ? text.slice(0, maxChars) : text;
	let lineCount = full.length > 0 ? 1 : 0;
	let previewEnd = full.length;
	let previewLineCount = 1;

	for (let index = 0; index < full.length; index += 1) {
		if (full.charCodeAt(index) !== 10) continue;
		lineCount += 1;
		if (previewLineCount < previewLines) {
			previewLineCount += 1;
		} else if (previewEnd === full.length) {
			previewEnd = index;
		}
	}

	const preview = full.slice(0, previewEnd);
	return {
		full,
		preview,
		lineCount,
		hasMore: previewEnd < full.length || truncated,
		remainingLines: Math.max(0, lineCount - previewLines),
		truncated,
		omittedChars: Math.max(0, text.length - full.length)
	};
}
