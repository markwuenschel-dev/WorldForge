import { writable } from 'svelte/store';
import { toast } from 'svelte-sonner';
import {
	pasteClipboardImage,
	openImagePicker,
	removeAttachment,
	getAttachments,
	onAttachmentsChanged,
	onAttachmentError,
	type AttachmentInfo
} from '$lib/bridge.js';
import { isSessionDisposed, onSessionDisposed } from '$lib/stores/sessionLifecycle.js';
import { beginPerformanceSpan, endPerformanceSpan } from '$lib/performanceTelemetry.js';
import { clearSessionAttachments, setSessionAttachments } from '$lib/attachmentState.js';

export const attachmentsBySession = writable<Record<string, AttachmentInfo[]>>({});

// ── Binding ──────────────────────────────────────────────────────────

let bound = false;

/** Wire up attachment change callbacks. Call once on mount. */
export function bindAttachmentsListener(): void {
	if (bound) return;
	bound = true;

	onAttachmentsChanged((sessionId, list) => {
		if (isSessionDisposed(sessionId)) return;
		attachmentsBySession.update((current) => setSessionAttachments(current, sessionId, list));
	});
	onAttachmentError((_sessionId, message) => toast.error(message));
}

/** Hydrate one pane in case native attachments predate the WebUI listener. */
export async function loadAttachments(sessionId: string): Promise<void> {
	if (!sessionId || isSessionDisposed(sessionId)) return;
	const list = await getAttachments(sessionId);
	if (isSessionDisposed(sessionId)) return;
	attachmentsBySession.update((current) => setSessionAttachments(current, sessionId, list));
}

// ── Actions ──────────────────────────────────────────────────────────

/** Paste image from system clipboard */
export async function pasteImage(sessionId: string): Promise<boolean> {
	const span = beginPerformanceSpan('attachment_mutation', { action: 'paste', sessionId });
	const result = await pasteClipboardImage(sessionId);
	endPerformanceSpan(span, { success: result.success });
	if (!result.success && result.error) toast.error(result.error);
	return result.success;
}

/** Open native file picker for attachments (images + common docs) */
export async function pickAttachments(sessionId: string): Promise<void> {
	const result = await openImagePicker(sessionId);
	if (result.error) toast.error(result.error);
}

/** Remove an attachment by ID */
export async function removeItem(sessionId: string, id: string): Promise<void> {
	const span = beginPerformanceSpan('attachment_mutation', { action: 'remove', sessionId });
	try {
		await removeAttachment(sessionId, id);
		endPerformanceSpan(span, { success: true });
	} catch (error) {
		endPerformanceSpan(span, { success: false });
		throw error;
	}
}

export function cleanupAttachmentsForSession(sessionId: string): void {
	attachmentsBySession.update((current) => clearSessionAttachments(current, sessionId));
}

onSessionDisposed(cleanupAttachmentsForSession);
