/**
 * Creates a keyed monotonic operation tracker. Async work owns the version it
 * receives from `begin`; only the latest owner for that key may commit or roll
 * back state when it completes.
 *
 * @returns {{
 *   begin: (key: string) => number;
 *   isCurrent: (key: string, version: number) => boolean;
 *   invalidate: (key: string) => number;
 * }}
 */
export function createOperationVersionTracker() {
	/** @type {Map<string, number>} */
	const versions = new Map();

	/** @param {string} key */
	const begin = (key) => {
		const version = (versions.get(key) ?? 0) + 1;
		versions.set(key, version);
		return version;
	};

	return {
		begin,
		isCurrent: (key, version) => versions.get(key) === version,
		invalidate: begin
	};
}
