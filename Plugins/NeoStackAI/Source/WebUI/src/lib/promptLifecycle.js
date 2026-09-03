/** Creates an isolated prompt/cancel acknowledgement registry. */
export function createPromptLifecycleRegistry() {
	/** @type {Map<string, { requestId: string, acknowledged: boolean }>} */
	const prompts = new Map();
	/** @type {Map<string, string>} */
	const cancellations = new Map();

	return {
		/** @param {string} sessionId @param {string} requestId */
		beginPrompt(sessionId, requestId) {
			prompts.set(sessionId, { requestId, acknowledged: false });
			cancellations.delete(sessionId);
		},

		/** @param {string} sessionId @param {string} requestId @param {boolean} accepted */
		acknowledgePrompt(sessionId, requestId, accepted) {
			const prompt = prompts.get(sessionId);
			if (!prompt || prompt.requestId !== requestId) return 'stale';
			if (!accepted) {
				prompts.delete(sessionId);
				cancellations.delete(sessionId);
				return 'rejected';
			}
			prompt.acknowledged = true;
			return 'accepted';
		},

		/** @param {string} sessionId @param {string} requestId */
		beginCancellation(sessionId, requestId) {
			if (cancellations.has(sessionId)) return false;
			cancellations.set(sessionId, requestId);
			return true;
		},

		/** @param {string} sessionId @param {string} requestId @param {boolean} accepted */
		acknowledgeCancellation(sessionId, requestId, accepted) {
			if (cancellations.get(sessionId) !== requestId) return 'stale';
			cancellations.delete(sessionId);
			if (!accepted) return 'rejected';
			prompts.delete(sessionId);
			return 'accepted';
		},

		/** @param {string} sessionId */
		isActive(sessionId) {
			return prompts.has(sessionId);
		},

		/** @param {string} sessionId */
		getPromptRequestId(sessionId) {
			return prompts.get(sessionId)?.requestId;
		},

		/** @param {string} sessionId */
		isCancellationPending(sessionId) {
			return cancellations.has(sessionId);
		},

		/** @param {string} sessionId */
		finish(sessionId) {
			prompts.delete(sessionId);
			cancellations.delete(sessionId);
		},

		/** @param {string} sessionId */
		dispose(sessionId) {
			prompts.delete(sessionId);
			cancellations.delete(sessionId);
		}
	};
}
