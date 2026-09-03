/**
 * @template T
 * @param {Record<string, T[]>} current
 * @param {string} sessionId
 * @param {T[]} attachments
 */
export function setSessionAttachments(current, sessionId, attachments) {
	return { ...current, [sessionId]: attachments };
}

/**
 * @template T
 * @param {Record<string, T[]>} current
 * @param {string} sessionId
 */
export function clearSessionAttachments(current, sessionId) {
	if (!(sessionId in current)) return current;
	const next = { ...current };
	delete next[sessionId];
	return next;
}
