<script lang="ts">
	import { onMount, onDestroy, tick } from 'svelte';
	import { Terminal, type ITerminalAddon } from '@xterm/xterm';
	import { WebLinksAddon } from '@xterm/addon-web-links';
	import {
		startTerminal,
		writeTerminal,
		resizeTerminal,
		closeTerminal,
		subscribeTerminalOutput,
		subscribeTerminalExit,
		openUrl
	} from '$lib/bridge.js';
	import {
		codeFontFamily,
		codeFontSize,
		DEFAULT_CODE_FONT_STACK,
		normalizeFontStack
	} from '$lib/stores/settings.js';

	interface Props {
		isActiveTab: boolean;
		onBridgeId?: (bridgeId: string) => void;
		onBridgeLost?: () => void;
	}

	type TerminalWithCore = Terminal & {
		_core?: {
			_renderService?: {
				dimensions?: { css?: { cell?: { width?: number; height?: number } } };
			};
		};
	};

	let { isActiveTab, onBridgeId, onBridgeLost }: Props = $props();

	class FitAddon implements ITerminalAddon {
		private _terminal: Terminal | undefined;
		activate(terminal: Terminal) {
			this._terminal = terminal;
		}
		dispose() {
			this._terminal = undefined;
		}

		proposeDimensions(): { cols: number; rows: number } | undefined {
			const t = this._terminal;
			if (!t?.element?.parentElement) return undefined;
			const cell = (t as TerminalWithCore)._core?._renderService?.dimensions?.css?.cell;
			const cellWidth = cell?.width;
			const cellHeight = cell?.height;
			if (!cellWidth || !cellHeight) return undefined;
			const parentEl = t.element.parentElement;
			const cw = parentEl.clientWidth;
			const ch = parentEl.clientHeight;
			if (cw < cellWidth || ch < cellHeight) return undefined;
			const cols = Math.max(2, Math.floor(cw / cellWidth));
			const rows = Math.max(1, Math.floor(ch / cellHeight));
			return { cols, rows };
		}

		fit() {
			const t = this._terminal;
			if (!t?.element?.parentElement) return;
			const dims = this.proposeDimensions();
			if (!dims) return;
			if (t.rows !== dims.rows || t.cols !== dims.cols) t.resize(dims.cols, dims.rows);
		}
	}

	let containerEl: HTMLDivElement | undefined = $state();
	let terminal: Terminal | undefined = $state();
	let fitAddon: FitAddon | undefined = $state();
	let terminalId: string | undefined = $state();
	let status: 'connecting' | 'connected' | 'exited' | 'error' = $state('connecting');
	let resizeTimeout: ReturnType<typeof setTimeout> | undefined;
	let resizeObserver: ResizeObserver | undefined;
	let intersectionObserver: IntersectionObserver | undefined;
	let unsubOutput: (() => void) | undefined;
	let unsubExit: (() => void) | undefined;
	const terminalFontFamily = $derived(normalizeFontStack($codeFontFamily, DEFAULT_CODE_FONT_STACK));

	function handleOutput(id: string, base64Data: string) {
		if (id !== terminalId || !terminal) return;
		const bytes = Uint8Array.from(atob(base64Data), (c) => c.charCodeAt(0));
		terminal.write(bytes);
	}

	function handleExit(id: string, code: number) {
		if (id !== terminalId) return;
		status = 'exited';
		onBridgeLost?.();
		terminal?.write(`\r\n\x1b[90m[Process exited with code ${code}]\x1b[0m\r\n`);
	}

	function handleVisibilityChange(visible: boolean) {
		if (!visible || !fitAddon || !terminal) return;
		setTimeout(() => {
			fitAddon!.fit();
			const dims = fitAddon!.proposeDimensions();
			if (dims && terminalId && status === 'connected') {
				resizeTerminal(terminalId, dims.cols, dims.rows);
			}
		}, 50);
	}

	$effect(() => {
		if (!terminal) return;
		terminal.options.fontFamily = terminalFontFamily;
		terminal.options.fontSize = $codeFontSize;
		queueMicrotask(() => {
			fitAddon?.fit();
			const dims = fitAddon?.proposeDimensions();
			if (dims && terminalId && status === 'connected') {
				resizeTerminal(terminalId, dims.cols, dims.rows);
			}
		});
	});

	async function initTerminal() {
		if (!containerEl) return;

		terminal = new Terminal({
			fontFamily: terminalFontFamily,
			fontSize: $codeFontSize,
			lineHeight: 1.2,
			scrollback: 5000,
			cursorBlink: true,
			cursorStyle: 'bar',
			allowProposedApi: true,
			theme: {
				background: '#1a1a1a',
				foreground: '#d4d4d4',
				cursor: '#d4d4d4',
				cursorAccent: '#1a1a1a',
				selectionBackground: '#264f78',
				selectionForeground: '#ffffff',
				black: '#1a1a1a',
				red: '#f44747',
				green: '#6a9955',
				yellow: '#d7ba7d',
				blue: '#569cd6',
				magenta: '#c586c0',
				cyan: '#4ec9b0',
				white: '#d4d4d4',
				brightBlack: '#808080',
				brightRed: '#f44747',
				brightGreen: '#6a9955',
				brightYellow: '#d7ba7d',
				brightBlue: '#569cd6',
				brightMagenta: '#c586c0',
				brightCyan: '#4ec9b0',
				brightWhite: '#ffffff'
			}
		});

		fitAddon = new FitAddon();
		terminal.loadAddon(fitAddon);
		terminal.loadAddon(
			new WebLinksAddon((_event, uri) => {
				openUrl(uri);
			})
		);

		terminal.open(containerEl);
		fitAddon.fit();

		unsubOutput = subscribeTerminalOutput(handleOutput);
		unsubExit = subscribeTerminalExit(handleExit);

		terminal.onData((data) => {
			if (terminalId && status === 'connected') {
				writeTerminal(terminalId, data);
			}
		});

		const result = await startTerminal();
		if (result.terminalId) {
			terminalId = result.terminalId;
			status = 'connected';
			onBridgeId?.(result.terminalId);

			const dims = fitAddon.proposeDimensions();
			if (dims) {
				resizeTerminal(terminalId, dims.cols, dims.rows);
			}
		} else {
			status = 'error';
			terminal.write(
				`\x1b[31mFailed to start terminal: ${result.error || 'Unknown error'}\x1b[0m\r\n`
			);
		}

		resizeObserver = new ResizeObserver(() => {
			if (resizeTimeout) clearTimeout(resizeTimeout);
			resizeTimeout = setTimeout(() => {
				if (!fitAddon || !terminal || !terminalId) return;
				if (containerEl && (containerEl.clientWidth < 8 || containerEl.clientHeight < 8)) return;
				fitAddon.fit();
				const dims = fitAddon.proposeDimensions();
				if (dims && status === 'connected') {
					resizeTerminal(terminalId, dims.cols, dims.rows);
				}
			}, 150);
		});
		resizeObserver.observe(containerEl);

		intersectionObserver = new IntersectionObserver(
			(entries) => {
				handleVisibilityChange(entries[0].isIntersecting);
			},
			{ threshold: 0.1 }
		);
		intersectionObserver.observe(containerEl);
	}

	async function restartTerminal() {
		if (terminalId) {
			await closeTerminal(terminalId);
			onBridgeLost?.();
		}
		terminal?.clear();
		terminal?.reset();
		status = 'connecting';
		terminalId = undefined;

		const result = await startTerminal();
		if (result.terminalId) {
			terminalId = result.terminalId;
			status = 'connected';
			onBridgeId?.(result.terminalId);
			const dims = fitAddon?.proposeDimensions();
			if (dims) {
				resizeTerminal(terminalId, dims.cols, dims.rows);
			}
		} else {
			status = 'error';
			terminal?.write(
				`\x1b[31mFailed to restart terminal: ${result.error || 'Unknown error'}\x1b[0m\r\n`
			);
		}
	}

	$effect(() => {
		if (!isActiveTab || !fitAddon || !terminal || !terminalId || status !== 'connected') return;
		tick().then(() => {
			if (!isActiveTab || !fitAddon || !terminal || !terminalId) return;
			fitAddon.fit();
			const dims = fitAddon.proposeDimensions();
			if (dims) {
				resizeTerminal(terminalId, dims.cols, dims.rows);
			}
		});
	});

	onMount(() => {
		initTerminal();
	});

	onDestroy(() => {
		unsubOutput?.();
		unsubExit?.();
		resizeObserver?.disconnect();
		intersectionObserver?.disconnect();
		if (resizeTimeout) clearTimeout(resizeTimeout);
		if (terminalId) {
			closeTerminal(terminalId);
		}
		onBridgeLost?.();
		terminal?.dispose();
	});
</script>

<div class="flex h-full min-h-0 w-full min-w-0 flex-col bg-surface-popup">
	<div
		class="border-border/50 flex h-7 shrink-0 items-center justify-end border-b bg-surface-bar px-2"
	>
		{#if status === 'exited' || status === 'error'}
			<button
				type="button"
				class="rounded px-2 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
				onclick={restartTerminal}
			>
				Restart
			</button>
		{/if}
	</div>
	<div class="min-h-0 flex-1 p-1" bind:this={containerEl}></div>
</div>
