<script lang="ts">
	import './layout.css';
	import '@fontsource/geist/latin-400.css';
	import '@fontsource/geist/latin-500.css';
	import '@fontsource/geist/latin-600.css';
	import '@fontsource/geist/latin-700.css';
	import '@fontsource/geist-mono/latin-400.css';
	import '@fontsource/geist-mono/latin-500.css';
	import '$lib/polyfills.js';
	import { onMount } from 'svelte';
	import { loadAgents, bindAgentsAuthRefresh } from '$lib/stores/agents.js';
	import { loadSessions, bindSessionListListener } from '$lib/stores/sessions.js';
	import { bindAgentStateListener } from '$lib/stores/agentState.js';
	import { bindMessageListener } from '$lib/stores/messages.js';
	import { bindPermissionListener } from '$lib/stores/permissions.js';
	import { bindModeListener } from '$lib/stores/modes.js';
	import { bindInstallListeners } from '$lib/stores/setup.js';
	import { bindCommandsListener } from '$lib/stores/commands.js';
	import { bindPlanListener } from '$lib/stores/plan.js';
	import { bindModelsListener } from '$lib/stores/models.js';
	import { bindConfigOptionsListener } from '$lib/stores/configOptions.js';
	import { bindUsageListener } from '$lib/stores/rateLimits.js';
	import { bindCloudAccountListener, refreshCloudAccount } from '$lib/stores/cloudAccount.js';
	import { bindNeoStackAuthListener } from '$lib/stores/neostackAuth.js';
	import { bindAttachmentsListener, pasteImage } from '$lib/stores/attachments.js';
	import { bindLoginListener } from '$lib/stores/auth.js';
	import { loadSourceControlStatus } from '$lib/stores/sourceControl.js';
	import {
		copyToClipboard,
		getClipboardText,
		waitForBridge,
		expectsEmbeddedBridge,
		startBridgeLifecycleMonitor,
		onBridgeAvailabilityChanged,
		capturePerformanceSnapshot,
		openUrl,
		openPath
	} from '$lib/bridge.js';
	import { classifyLinkHref } from '$lib/linkPolicy.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import { ModeWatcher } from 'mode-watcher';
	import { Toaster } from 'svelte-sonner';
	import TopNav from '$lib/components/TopNav.svelte';
	import EntitlementBanner from '$lib/components/EntitlementBanner.svelte';
	import ConnectingBanner from '$lib/components/ConnectingBanner.svelte';
	import {
		themeChoice,
		accentHue,
		accentIntensity,
		reduceTransparency,
		uiFontSize,
		codeFontSize,
		uiFontFamily,
		codeFontFamily,
		fontSmoothing,
		DEFAULT_UI_FONT_STACK,
		DEFAULT_CODE_FONT_STACK,
		normalizeFontStack
	} from '$lib/stores/settings.js';
	import { modKey } from '$lib/platform.js';
	import {
		startPerformanceMonitoring,
		takePerformanceRecordsForExport
	} from '$lib/performanceTelemetry.js';

	let { children } = $props();

	// ── Appearance: apply user prefs to <html> as CSS variables / classes ──
	// Single source of truth. Components read CSS vars; we just write them.
	$effect(() => {
		if (typeof document === 'undefined') return;
		const root = document.documentElement;

		// Theme class (replaces existing class so we don't accumulate)
		root.classList.remove('theme-dark', 'theme-light', 'theme-high-contrast');
		root.classList.add(`theme-${$themeChoice}`);
		root.classList.toggle('dark', $themeChoice !== 'light');

		// Accent: HSL derived from hue + intensity slider
		// Base saturation 80%, lightness 55% — chosen to match the original #2b8ceb.
		const hue = $accentHue;
		const sat = Math.max(0, Math.min(100, $accentIntensity)) * 0.8;
		root.style.setProperty('--ue-accent', `hsl(${hue} ${sat}% 55%)`);
		root.style.setProperty('--ue-accent-hover', `hsl(${hue} ${sat}% 65%)`);
		root.style.setProperty('--ue-accent-muted', `hsl(${hue} ${sat}% 42%)`);

		// Typography
		root.style.setProperty('--ui-font-size', `${$uiFontSize}px`);
		root.style.setProperty('--code-font-size', `${$codeFontSize}px`);
		root.style.setProperty(
			'--ui-font-family',
			normalizeFontStack($uiFontFamily, DEFAULT_UI_FONT_STACK)
		);
		root.style.setProperty(
			'--code-font-family',
			normalizeFontStack($codeFontFamily, DEFAULT_CODE_FONT_STACK)
		);

		// Body classes for toggles that need CSS-side overrides
		document.body.classList.toggle('no-translucency', $reduceTransparency);
		document.body.classList.toggle('font-smoothing-off', !$fontSmoothing);
	});

	// True while a slow editor startup is still binding the bridge (shown after
	// a short delay so it never flashes on normal startups).
	let waitingForBridge = $state(false);

	onMount(() => {
		const stopPerformanceMonitoring = startPerformanceMonitoring();
		const performanceExportInterval = setInterval(() => {
			void capturePerformanceSnapshot(takePerformanceRecordsForExport());
		}, 60_000);
		let initRan = false;
		const bridgeWaitController = new AbortController();
		const hydrateFromBridge = () => {
			loadAgents();
			loadSessions();
			refreshCloudAccount();
			loadSourceControlStatus();
		};

		// Store guards intentionally register each JS callback once. The bridge
		// registry replays those callbacks exactly once when CEF replaces the
		// native bridge object, so the stores do not need ad-hoc reset hooks.
		const runInit = () => {
			if (initRan) return;
			initRan = true;
			waitingForBridge = false;

			bindAgentStateListener();
			bindMessageListener();
			bindPermissionListener();
			bindModeListener();
			bindInstallListeners();
			bindCommandsListener();
			bindPlanListener();
			bindModelsListener();
			bindConfigOptionsListener();
			bindUsageListener();
			bindCloudAccountListener();
			bindNeoStackAuthListener();
			bindAgentsAuthRefresh();
			bindAttachmentsListener();
			bindLoginListener();
			bindSessionListListener();
			hydrateFromBridge();
		};

		// Surface "Connecting to editor…" only when the bridge is late.
		const connectingDelay = setTimeout(() => {
			if (!initRan) waitingForBridge = true;
		}, 2000);
		const stopBridgeMonitor = startBridgeLifecycleMonitor(bridgeWaitController.signal);
		const unsubscribeBridgeAvailability = onBridgeAvailabilityChanged((available) => {
			if (!available) {
				if (initRan) waitingForBridge = true;
				return;
			}

			clearTimeout(connectingDelay);
			waitingForBridge = false;
			if (initRan) hydrateFromBridge();
			else runInit();
		});

		if (expectsEmbeddedBridge()) {
			// Embedded pages carry an explicit marker from the plugin, so keep
			// waiting until BindUObject succeeds instead of permanently falling
			// back to mock initialization after an arbitrary timeout.
			waitForBridge(undefined, bridgeWaitController.signal).then((available) => {
				if (!available) return;
				clearTimeout(connectingDelay);
				runInit();
			});
		} else {
			// Standalone/remote development has no embedded marker and should not
			// pay a timeout before its mock or relay-backed UI becomes available.
			clearTimeout(connectingDelay);
			runInit();
		}

		return () => {
			void capturePerformanceSnapshot(takePerformanceRecordsForExport());
			clearInterval(performanceExportInterval);
			stopPerformanceMonitoring();
			clearTimeout(connectingDelay);
			unsubscribeBridgeAvailability();
			stopBridgeMonitor();
			bridgeWaitController.abort();
		};
	});

	/**
	 * CEF in off-screen rendering mode doesn't execute default clipboard/selection
	 * actions for keyboard shortcuts. We handle them explicitly via the UE bridge.
	 */
	function handleGlobalKeydown(e: KeyboardEvent) {
		if (!e.metaKey && !e.ctrlKey) return;

		const key = e.key.toLowerCase();
		const el = document.activeElement as HTMLInputElement | HTMLTextAreaElement | null;
		const isInput = el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA');

		if (key === 'a') {
			// Select all
			if (isInput) {
				e.preventDefault();
				el.select();
			}
		} else if (key === 'c') {
			// Copy
			const selection = isInput
				? el.value.substring(el.selectionStart ?? 0, el.selectionEnd ?? 0)
				: (window.getSelection()?.toString() ?? '');
			if (selection) {
				e.preventDefault();
				copyToClipboard(selection);
			}
		} else if (key === 'x') {
			// Cut
			if (isInput && el.selectionStart !== el.selectionEnd) {
				const start = el.selectionStart ?? 0;
				const end = el.selectionEnd ?? 0;
				const selection = el.value.substring(start, end);
				e.preventDefault();
				copyToClipboard(selection);
				// Delete the selected text
				el.setRangeText('', start, end, 'end');
				el.dispatchEvent(new Event('input', { bubbles: true }));
			}
		} else if (key === 'v') {
			// Paste
			if (isInput) {
				e.preventDefault();
				getClipboardText().then(async (text) => {
					// Text has priority for normal paste. If clipboard text is empty and the
					// focused field is a textarea, try image paste into chat attachments.
					if (text === '' && el.tagName === 'TEXTAREA') {
						const sessionId = el.dataset.chatSessionId ?? '';
						if (sessionId) await pasteImage(sessionId);
						return;
					}

					if (!text) return;
					const start = el.selectionStart ?? 0;
					const end = el.selectionEnd ?? 0;
					el.setRangeText(text, start, end, 'end');
					el.dispatchEvent(new Event('input', { bubbles: true }));
				});
			}
		}
	}

	// ── Global right-click context menu (CEF blocks native menus) ──
	let globalCtxVisible = $state(false);
	let globalCtxX = $state(0);
	let globalCtxY = $state(0);
	let globalCtxHasSelection = $state(false);
	let globalCtxIsInput = $state(false);
	let globalCtxTarget = $state<HTMLInputElement | HTMLTextAreaElement | null>(null);

	function isEditableElement(el: EventTarget | null): el is HTMLInputElement | HTMLTextAreaElement {
		if (!el) return false;
		return (
			(el instanceof HTMLInputElement &&
				el.type !== 'checkbox' &&
				el.type !== 'radio' &&
				el.type !== 'button' &&
				el.type !== 'submit') ||
			el instanceof HTMLTextAreaElement
		);
	}

	function handleGlobalContextMenu(e: MouseEvent) {
		// If a bits-ui context menu trigger will handle this, let it through
		if ((e.target as HTMLElement)?.closest?.('[data-slot="context-menu-trigger"]')) return;
		e.preventDefault();
		// If the chat pane's own context menu handler will handle this, skip
		if ((e.target as HTMLElement)?.closest?.('.chat-scroll-area, .chat-composer')) return;
		const target = e.target as EventTarget | null;
		globalCtxIsInput = isEditableElement(target);
		globalCtxTarget = globalCtxIsInput ? (target as HTMLInputElement | HTMLTextAreaElement) : null;
		if (globalCtxIsInput && globalCtxTarget) {
			globalCtxHasSelection =
				(globalCtxTarget.selectionStart ?? 0) !== (globalCtxTarget.selectionEnd ?? 0);
		} else {
			globalCtxHasSelection = !!window.getSelection()?.toString();
		}
		const vw = window.innerWidth;
		const vh = window.innerHeight;
		globalCtxX = Math.min(e.clientX, vw - 200);
		globalCtxY = Math.min(e.clientY, vh - 160);
		globalCtxVisible = true;
	}

	function handleGlobalCtxCopy() {
		if (globalCtxIsInput && globalCtxTarget) {
			const sel = globalCtxTarget.value.substring(
				globalCtxTarget.selectionStart ?? 0,
				globalCtxTarget.selectionEnd ?? 0
			);
			if (sel) copyToClipboard(sel);
		} else {
			const sel = window.getSelection()?.toString() ?? '';
			if (sel) copyToClipboard(sel);
		}
		globalCtxVisible = false;
	}

	function handleGlobalCtxCut() {
		if (!globalCtxIsInput || !globalCtxTarget) return;
		const s = globalCtxTarget.selectionStart ?? 0;
		const end = globalCtxTarget.selectionEnd ?? 0;
		const sel = globalCtxTarget.value.substring(s, end);
		if (sel) {
			copyToClipboard(sel);
			globalCtxTarget.setRangeText('', s, end, 'end');
			globalCtxTarget.dispatchEvent(new Event('input', { bubbles: true }));
		}
		globalCtxVisible = false;
	}

	async function handleGlobalCtxPaste() {
		if (!globalCtxIsInput || !globalCtxTarget) return;
		const text = await getClipboardText();
		if (text) {
			const s = globalCtxTarget.selectionStart ?? 0;
			const end = globalCtxTarget.selectionEnd ?? 0;
			globalCtxTarget.setRangeText(text, s, end, 'end');
			globalCtxTarget.dispatchEvent(new Event('input', { bubbles: true }));
		}
		globalCtxVisible = false;
	}

	function handleGlobalCtxSelectAll() {
		if (globalCtxIsInput && globalCtxTarget) {
			globalCtxTarget.select();
		} else {
			const sel = window.getSelection();
			const range = document.createRange();
			range.selectNodeContents(document.body);
			sel?.removeAllRanges();
			sel?.addRange(range);
		}
		globalCtxVisible = false;
	}

	// ── Link clicks never navigate ──────────────────────────────────
	// One handler for every anchor in the app — chat markdown, Studio job
	// results, agent repository links, Discord. The panel has no address bar
	// and no Back button, so a single same-frame navigation strands the user
	// in unstyled DOM (see the reasoning in $lib/linkPolicy.js). Bubble phase
	// with a defaultPrevented check, so a component that already handled its
	// own click keeps winning; the browser's default navigation still happens
	// after bubbling, so cancelling here is enough.
	function handleGlobalLinkClick(e: MouseEvent) {
		if (e.defaultPrevented) return;
		const anchor = (e.target as Element | null)?.closest?.('a[href]');
		if (!(anchor instanceof HTMLAnchorElement)) return;

		// getAttribute, not .href: the DOM property resolves '/Game/BP' against
		// the server origin and hands back 'http://localhost:PORT/Game/BP',
		// which is the navigation we're here to stop, not the author's intent.
		const target = classifyLinkHref(anchor.getAttribute('href'));

		// An in-page anchor is the one click we must NOT cancel: it scrolls
		// without a document load, so it strands nobody, and cancelling it just
		// makes the link dead. Leave it entirely to the browser.
		if (target.kind === 'fragment') return;

		// Everything else is cancelled. An href we can't classify has nowhere
		// useful to go, and letting it through is what breaks the panel.
		e.preventDefault();

		if (target.kind === 'external') {
			void openUrl(target.url);
		} else if (target.kind === 'local') {
			void openPath(target.path, target.line);
		}
	}
</script>

<svelte:window
	onkeydown={handleGlobalKeydown}
	oncontextmenu={handleGlobalContextMenu}
	onclick={handleGlobalLinkClick}
/>

<svelte:head>
	<title>Agent Chat</title>
</svelte:head>

<ModeWatcher defaultMode={$themeChoice === 'light' ? 'light' : 'dark'} />
<Toaster theme={$themeChoice === 'light' ? 'light' : 'dark'} position="top-right" richColors />

<Tooltip.Provider delayDuration={0} skipDelayDuration={0}>
	<div class="flex h-screen w-screen flex-col overflow-hidden">
		<TopNav />
		<ConnectingBanner visible={waitingForBridge} />
		<EntitlementBanner />
		<div class="flex min-h-0 flex-1 overflow-hidden">
			{@render children()}
		</div>
	</div>
</Tooltip.Provider>

{#if globalCtxVisible}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div
		class="fixed inset-0 z-[200]"
		onclick={() => (globalCtxVisible = false)}
		oncontextmenu={(e) => {
			e.preventDefault();
			globalCtxVisible = false;
		}}
	></div>
	<div
		class="fixed z-[201] min-w-[180px] rounded-lg border border-border bg-popover p-1 shadow-lg"
		style="left: {globalCtxX}px; top: {globalCtxY}px;"
	>
		{#if globalCtxIsInput}
			<button
				class="flex w-full items-center justify-between rounded-md px-3 py-1.5 text-[13px] text-popover-foreground {globalCtxHasSelection
					? 'cursor-default hover:bg-accent'
					: 'cursor-not-allowed opacity-40'}"
				onclick={handleGlobalCtxCut}
				disabled={!globalCtxHasSelection}
				>Cut<span class="text-muted-foreground/60 ml-auto text-[11px]">{modKey}X</span></button
			>
		{/if}
		<button
			class="flex w-full items-center justify-between rounded-md px-3 py-1.5 text-[13px] text-popover-foreground {globalCtxHasSelection
				? 'cursor-default hover:bg-accent'
				: 'cursor-not-allowed opacity-40'}"
			onclick={handleGlobalCtxCopy}
			disabled={!globalCtxHasSelection}
			>Copy<span class="text-muted-foreground/60 ml-auto text-[11px]">{modKey}C</span></button
		>
		{#if globalCtxIsInput}
			<button
				class="flex w-full cursor-default items-center justify-between rounded-md px-3 py-1.5 text-[13px] text-popover-foreground hover:bg-accent"
				onclick={handleGlobalCtxPaste}
				>Paste<span class="text-muted-foreground/60 ml-auto text-[11px]">{modKey}V</span></button
			>
		{/if}
		<div class="bg-border/40 my-1 h-px"></div>
		<button
			class="flex w-full cursor-default items-center justify-between rounded-md px-3 py-1.5 text-[13px] text-popover-foreground hover:bg-accent"
			onclick={handleGlobalCtxSelectAll}
			>Select All<span class="text-muted-foreground/60 ml-auto text-[11px]">{modKey}A</span></button
		>
	</div>
{/if}
