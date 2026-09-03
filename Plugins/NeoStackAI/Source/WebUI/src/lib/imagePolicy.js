export const DEFAULT_ALLOWED_RESPONSE_IMAGE_PREFIXES = Object.freeze(['data:image/', 'blob:']);

/** @param {string} source @param {readonly string[]} [allowedPrefixes] */
export function isResponseImageSourceAllowed(
	source,
	allowedPrefixes = DEFAULT_ALLOWED_RESPONSE_IMAGE_PREFIXES
) {
	return allowedPrefixes.some((prefix) => source.startsWith(prefix));
}
