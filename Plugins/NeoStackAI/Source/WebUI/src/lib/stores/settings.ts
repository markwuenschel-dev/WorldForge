import { writable } from 'svelte/store';

export const settingsOpen = writable(false);
export const settingsTab = writable<string>('general');

/** Must match tab `id` values in SettingsPanel.svelte */
const SETTINGS_TAB_IDS = [
	'general',
	'appearance',
	'setup',
	'indexing',
	'extensions',
	'skills',
	'mcp',
	'agents',
	'usage',
	'generation',
	'notifications',
	'crashes',
	'about'
] as const;

function isKnownSettingsTab(tab: string): tab is (typeof SETTINGS_TAB_IDS)[number] {
	return (SETTINGS_TAB_IDS as readonly string[]).includes(tab);
}

// Enter-to-send preference (persisted to localStorage)
const ENTER_TO_SEND_KEY = 'aik-enter-to-send';
function getInitialEnterToSend(): boolean {
	if (typeof window === 'undefined') return true;
	const stored = localStorage.getItem(ENTER_TO_SEND_KEY);
	return stored === null ? true : stored === 'true';
}
export const enterToSend = writable<boolean>(getInitialEnterToSend());
enterToSend.subscribe((value) => {
	if (typeof window !== 'undefined') {
		localStorage.setItem(ENTER_TO_SEND_KEY, String(value));
	}
});

// Top-nav tab visibility (Chat is always on; Studio/Terminal are togglable).
// Persisted to localStorage so the choice survives editor restarts.
function makeBoolStore(key: string, fallback: boolean) {
	const getInitial = (): boolean => {
		if (typeof window === 'undefined') return fallback;
		const stored = localStorage.getItem(key);
		return stored === null ? fallback : stored === 'true';
	};
	const store = writable<boolean>(getInitial());
	store.subscribe((value) => {
		if (typeof window !== 'undefined') {
			localStorage.setItem(key, String(value));
		}
	});
	return store;
}

export const studioEnabled = makeBoolStore('aik-studio-enabled', true);
export const terminalEnabled = makeBoolStore('aik-terminal-enabled', true);

// String-valued preferences (font family, theme, accent hue, density, etc.).
// Mirror of makeBoolStore — keeps localStorage shape uniform across prefs.
function makeStringStore<T extends string>(key: string, fallback: T) {
	const getInitial = (): T => {
		if (typeof window === 'undefined') return fallback;
		const stored = localStorage.getItem(key);
		return (stored ?? fallback) as T;
	};
	const store = writable<T>(getInitial());
	store.subscribe((value) => {
		if (typeof window !== 'undefined') {
			localStorage.setItem(key, value);
		}
	});
	return store;
}

function makeNumberStore(key: string, fallback: number) {
	const getInitial = (): number => {
		if (typeof window === 'undefined') return fallback;
		const stored = localStorage.getItem(key);
		if (stored === null) return fallback;
		const n = Number(stored);
		return Number.isFinite(n) ? n : fallback;
	};
	const store = writable<number>(getInitial());
	store.subscribe((value) => {
		if (typeof window !== 'undefined') {
			localStorage.setItem(key, String(value));
		}
	});
	return store;
}

export const DEFAULT_UI_FONT_STACK =
	'"Geist", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
export const DEFAULT_CODE_FONT_STACK =
	'"Geist Mono", ui-monospace, "SF Mono", Menlo, Monaco, "Cascadia Mono", "Courier New", monospace';

export function quoteFontFamily(family: string): string {
	return `"${family.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

export function normalizeFontStack(value: string, fallback: string): string {
	const trimmed = value.trim();
	if (!trimmed) return fallback;
	if (trimmed.includes(',') || /\b(ui-|system-ui|sans-serif|serif|monospace)\b/.test(trimmed)) {
		return trimmed;
	}
	return `${quoteFontFamily(trimmed)}, ${fallback}`;
}

// ── Appearance preferences ──────────────────────────────────────────
// All applied as CSS variables / body classes by AppearanceController in
// +layout.svelte. None of these touch C++/UACPSettings — they're per-user
// per-machine UI prefs.

export type ToolCallDensity = 'compact' | 'detailed';
export const toolCallDensity = makeStringStore<ToolCallDensity>('aik-tool-call-density', 'compact');

export type ThemeChoice = 'dark' | 'light' | 'high-contrast';
export const themeChoice = makeStringStore<ThemeChoice>('aik-theme', 'dark');

export const accentHue = makeNumberStore('aik-accent-hue', 209); // matches #2b8ceb
export const accentIntensity = makeNumberStore('aik-accent-intensity', 100); // 0-100 %
export const reduceTransparency = makeBoolStore('aik-reduce-transparency', false);

export const uiFontSize = makeNumberStore('aik-ui-font-size', 13);
export const codeFontSize = makeNumberStore('aik-code-font-size', 12);
export const uiFontFamily = makeStringStore<string>('aik-ui-font-family', '');
export const codeFontFamily = makeStringStore<string>('aik-code-font-family', '');
export const fontSmoothing = makeBoolStore('aik-font-smoothing', true);

export const hideEmail = makeBoolStore('aik-hide-email', false);

export function openSettings(tab?: string) {
	// Only accept known string ids (avoids `onclick={openSettings}` passing a MouseEvent, etc.)
	if (typeof tab === 'string' && isKnownSettingsTab(tab)) {
		settingsTab.set(tab);
	} else {
		settingsTab.set('general');
	}
	settingsOpen.set(true);
}

export function closeSettings() {
	settingsOpen.set(false);
}
