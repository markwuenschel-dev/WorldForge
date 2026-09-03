// Where a clicked link is allowed to go.
//
// The panel is an embedded CEF view built with ShowControls(false) — no address
// bar, no Back button. A same-frame navigation is therefore UNRECOVERABLE: the
// local file server answers any unknown path with the SPA's index.html (the
// "SvelteKit SPA fallback" branch in NeoStackAIModule.cpp), and SvelteKit's
// relative asset URLs then resolve under that bogus path, so every CSS/JS
// bundle 404s. The user is left staring at the app's unstyled DOM with no way
// back but closing the tab.
//
// Markdown links reach exactly that. svelte-streamdown renders any href
// starting with '/' — a UE asset path, a POSIX path — as a plain
// `<a href="/Game/…">` with no target, because it reads it as a site-relative
// route. Clicking it kills the panel. So: nothing in this UI navigates. Every
// href is classified here and handed to the editor instead.

/**
 * @typedef {{ kind: 'external', url: string }} ExternalLink
 * @typedef {{ kind: 'local', path: string, line: number }} LocalLink
 * @typedef {{ kind: 'fragment' }} FragmentLink
 * @typedef {{ kind: 'none' }} NoLink
 * @typedef {ExternalLink | LocalLink | FragmentLink | NoLink} LinkTarget
 */

/** @type {NoLink} */
const NONE = { kind: 'none' };
/** @type {FragmentLink} */
const FRAGMENT = { kind: 'fragment' };

// Schemes the OS browser should own.
const EXTERNAL_SCHEME = /^(?:https?|mailto):/i;
// Anything that executes rather than locates — never forwarded anywhere.
const ACTIVE_SCHEME = /^(?:javascript|data|vbscript|blob):/i;
// 'C:\…' or 'C:/…'. The trailing separator matters: it separates a drive from
// a scheme like 'mailto:'.
const WINDOWS_DRIVE = /^[A-Za-z]:[\\/]/;
// Paths an agent writes relative to the project root.
const PROJECT_RELATIVE =
	/^(?:Source|Content|Config|Plugins|Saved|Binaries|Intermediate|Docs|Tests|Scripts)[\\/]/;
// A 'path:line' suffix. Anchored to the end and digits-only so it cannot eat a
// drive colon ('C:' has no digits after it) or a scheme.
const TRAILING_LINE = /^(.*[^\\/]):(\d+)$/;

// svelte-streamdown blocks every href whose scheme isn't http(s) — a local path
// renders as an inert "[blocked]" span the user can see but not use. These
// prefixes re-admit the local forms so they render as anchors; the click
// handler then routes them to the editor. Drive letters have to be enumerated
// because 'A:\…' parses as scheme 'a:', and the allowlist matches on origin.
const DRIVE_PREFIXES = Array.from({ length: 26 }, (_, i) => `${String.fromCharCode(65 + i)}:`);

export const DEFAULT_ALLOWED_RESPONSE_LINK_PREFIXES = Object.freeze([
	'*',
	'file:///',
	...DRIVE_PREFIXES
]);

/**
 * Convert a file:// URL to the filesystem path UE expects.
 * @param {string} href
 * @returns {string}
 */
function filePathFromFileUrl(href) {
	let rest = href.replace(/^file:\/\//i, '');
	try {
		rest = decodeURIComponent(rest);
	} catch {
		// A malformed escape is not worth dropping the whole link over — the
		// raw text still resolves for every path without percent-escapes.
	}
	// 'file:///C:/x' → '/C:/x' → 'C:/x'. Only a drive-letter path gets the
	// leading slash stripped; '/Users/x' must keep it.
	if (/^\/[A-Za-z]:[\\/]/.test(rest)) return rest.slice(1);
	// 'file://server/share' → '//server/share' (UNC), not 'server/share'.
	if (rest && !rest.startsWith('/')) return `//${rest}`;
	return rest;
}

/**
 * Split a trailing ':line' off a path.
 * @param {string} raw
 * @returns {{ path: string, line: number }}
 */
function splitLine(raw) {
	const match = TRAILING_LINE.exec(raw);
	if (!match) return { path: raw, line: 0 };
	return { path: match[1], line: Number.parseInt(match[2], 10) };
}

/**
 * Decide what a clicked href should do. Never returns something that navigates
 * the panel — an href this function doesn't recognise resolves to 'none' and
 * the click is swallowed, which is strictly better than a dead WebUI.
 *
 * @param {string | null | undefined} href
 * @returns {LinkTarget}
 */
export function classifyLinkHref(href) {
	if (typeof href !== 'string') return NONE;
	const trimmed = href.trim();
	if (!trimmed) return NONE;

	// In-page anchors are the one navigation that is safe and meaningful — the
	// browser scrolls without a document load, so nothing is stranded. They get
	// their own kind rather than 'none' precisely so the caller can tell "leave
	// this alone" apart from "there is nowhere to go": collapsing the two is
	// what made every fragment link dead on arrival.
	if (trimmed.startsWith('#')) return FRAGMENT;
	if (ACTIVE_SCHEME.test(trimmed)) return NONE;
	if (EXTERNAL_SCHEME.test(trimmed)) return { kind: 'external', url: trimmed };

	if (/^file:/i.test(trimmed)) {
		const path = filePathFromFileUrl(trimmed);
		return path ? { kind: 'local', path, line: 0 } : NONE;
	}

	if (WINDOWS_DRIVE.test(trimmed)) {
		const { path, line } = splitLine(trimmed);
		return { kind: 'local', path, line };
	}

	// '/Game/…' (UE asset), '/Users/…' (POSIX). Both are what streamdown
	// mistakes for a site-relative route.
	if (trimmed.startsWith('/')) {
		const { path, line } = splitLine(trimmed);
		return { kind: 'local', path, line };
	}

	if (PROJECT_RELATIVE.test(trimmed)) {
		const { path, line } = splitLine(trimmed);
		return { kind: 'local', path, line };
	}

	// Bare hostnames ('neostack.dev/docs') are the one ambiguous case worth
	// resolving: an agent writes them constantly and they are unmistakably
	// external once they carry a dot before the first slash.
	if (/^[\w-]+(\.[\w-]+)+(\/|$)/.test(trimmed)) {
		return { kind: 'external', url: `https://${trimmed}` };
	}

	return NONE;
}
