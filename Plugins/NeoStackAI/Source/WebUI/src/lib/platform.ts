// Platform helpers for the embedded Web UI. Computed once at module load
// because CEF inside Unreal does not change platform across the session.

function detectMac(): boolean {
	if (typeof navigator === 'undefined') return false;
	// `navigator.platform` is deprecated but still the cheapest reliable
	// signal in CEF. Fall back to userAgent for safety.
	const p = (navigator.platform || '').toLowerCase();
	if (p) return p.startsWith('mac') || p === 'iphone' || p === 'ipad';
	return /mac|iphone|ipad/i.test(navigator.userAgent || '');
}

export const isMac = detectMac();

/** "⌘" on Mac, "Ctrl" elsewhere — for keyboard hint labels. */
export const modKey = isMac ? '⌘' : 'Ctrl+';
