const DEFAULT_VIEWPORT_HEIGHT = 800;

/**
 * Builds a measured layout without touching the DOM. Unknown rows use the supplied
 * estimate until their ResizeObserver measurement arrives.
 *
 * @template T
 * @param {T[]} items
 * @param {(item: T) => string} getKey
 * @param {Record<string, number>} measuredHeights
 * @param {(item: T) => number} estimateHeight
 */
export function buildVirtualRows(items, getKey, measuredHeights, estimateHeight) {
	let top = 0;
	const rows = items.map((item, index) => {
		const key = getKey(item);
		const measured = measuredHeights[key];
		const height = Number.isFinite(measured) && measured > 0 ? measured : estimateHeight(item);
		const row = { item, key, index, top, height };
		top += height;
		return row;
	});

	return { rows, totalHeight: top };
}

/**
 * Finds the small row subset intersecting the viewport plus a pixel overscan.
 * Binary search keeps viewport updates logarithmic even for very long transcripts.
 *
 * @template T
 * @param {{ item: T, key: string, index: number, top: number, height: number }[]} rows
 * @param {number} scrollTop
 * @param {number} viewportHeight
 * @param {number} [overscan]
 */
export function getVisibleVirtualRows(
	rows,
	scrollTop,
	viewportHeight = DEFAULT_VIEWPORT_HEIGHT,
	overscan = 600
) {
	if (rows.length === 0) return [];

	const startOffset = Math.max(0, scrollTop - overscan);
	const endOffset = Math.max(startOffset, scrollTop + Math.max(1, viewportHeight) + overscan);

	let low = 0;
	let high = rows.length;
	while (low < high) {
		const middle = (low + high) >>> 1;
		const row = rows[middle];
		if (row.top + row.height < startOffset) low = middle + 1;
		else high = middle;
	}
	const startIndex = low;

	low = startIndex;
	high = rows.length;
	while (low < high) {
		const middle = (low + high) >>> 1;
		if (rows[middle].top <= endOffset) low = middle + 1;
		else high = middle;
	}

	return rows.slice(startIndex, low);
}

/**
 * Returns the scroll delta needed to preserve the same visual anchor when a row
 * above the viewport changes from its estimate to its measured height.
 *
 * @param {number} rowTop
 * @param {number} scrollTop
 * @param {number} previousHeight
 * @param {number} nextHeight
 */
export function getAnchorAdjustment(rowTop, scrollTop, previousHeight, nextHeight) {
	return rowTop < scrollTop ? nextHeight - previousHeight : 0;
}
