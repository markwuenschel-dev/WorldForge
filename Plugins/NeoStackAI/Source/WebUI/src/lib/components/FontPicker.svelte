<script lang="ts">
	import { onMount } from 'svelte';
	import { ArrowDown01Icon, Tick02Icon } from '@hugeicons/core-free-icons';
	import Icon from '$lib/components/Icon.svelte';
	import { listSystemFonts, type SystemFontInfo } from '$lib/bridge.js';
	import {
		DEFAULT_CODE_FONT_STACK,
		DEFAULT_UI_FONT_STACK,
		normalizeFontStack,
		quoteFontFamily
	} from '$lib/stores/settings.js';

	type FontSource = 'bundled' | 'system' | 'default';

	type FontOption = {
		value: string;
		label: string;
		family: string;
		source: FontSource;
		isMonospace?: boolean;
		isAvailable?: boolean;
	};

	let {
		value = $bindable(''),
		kind = 'sans',
		onchange
	}: {
		value: string;
		kind?: 'sans' | 'mono';
		onchange?: (value: string) => void;
	} = $props();

	const fallbackStack = $derived(kind === 'mono' ? DEFAULT_CODE_FONT_STACK : DEFAULT_UI_FONT_STACK);
	const sample = $derived(
		kind === 'mono'
			? 'const greet = (name) => `Hi ${name}`;'
			: 'The quick brown fox jumps · Ag 0123'
	);

	const bundledSans = ['Geist', 'Inter', 'Roboto'];
	const bundledMono = [
		'Geist Mono',
		'JetBrains Mono',
		'Fira Code',
		'Source Code Pro',
		'IBM Plex Mono'
	];

	let systemFonts = $state<SystemFontInfo[]>([]);
	let isLoadingFonts = $state(false);
	let query = $state('');
	let open = $state(false);
	let containerEl: HTMLDivElement | undefined = $state();
	let searchInputEl: HTMLInputElement | undefined = $state();
	let fontCheckVersion = $state(0);

	function stackForFamily(family: string): string {
		return `${quoteFontFamily(family)}, ${fallbackStack}`;
	}

	function optionForFamily(family: string, source: FontSource, isMonospace?: boolean): FontOption {
		return {
			value: stackForFamily(family),
			label: family,
			family,
			source,
			isMonospace,
			isAvailable: source === 'system' || fontLooksAvailable(family)
		};
	}

	function fontLooksAvailable(family: string): boolean {
		if (
			typeof document !== 'undefined' &&
			document.fonts?.check?.(`12px ${quoteFontFamily(family)}`)
		) {
			return true;
		}
		if (typeof document === 'undefined') return true;
		const canvas = document.createElement('canvas');
		const ctx = canvas.getContext('2d');
		if (!ctx) return true;
		const text = 'mmmmmmmmmlliWW0123456789';
		const generic = kind === 'mono' ? 'monospace' : 'sans-serif';
		ctx.font = `16px ${generic}`;
		const baseline = ctx.measureText(text).width;
		ctx.font = `16px ${quoteFontFamily(family)}, ${generic}`;
		return Math.abs(ctx.measureText(text).width - baseline) > 0.1;
	}

	function matchesKind(font: SystemFontInfo): boolean {
		return kind === 'mono' ? !!font.isMonospace : !font.isMonospace;
	}

	const defaultOption = $derived<FontOption>({
		value: '',
		label: kind === 'mono' ? 'System monospace' : 'System default',
		family: '',
		source: 'default',
		isMonospace: kind === 'mono',
		isAvailable: true
	});

	const bundledOptions = $derived(
		(() => {
			if (fontCheckVersion < 0) return [];
			return (kind === 'mono' ? bundledMono : bundledSans).map((family) =>
				optionForFamily(family, 'bundled', kind === 'mono')
			);
		})()
	);

	const systemOptions = $derived(
		systemFonts
			.filter((font) => font.family && matchesKind(font))
			.map((font) => optionForFamily(font.family, 'system', font.isMonospace))
	);

	const filteredSystemOptions = $derived.by(() => {
		const q = query.trim().toLowerCase();
		const matches = q
			? systemOptions.filter((opt) => opt.label.toLowerCase().includes(q))
			: systemOptions;
		return matches.slice(0, 120);
	});

	const allOptions = $derived([defaultOption, ...bundledOptions, ...systemOptions]);
	const selectedOption = $derived.by(() => {
		const normalized = normalizeFontStack(value, fallbackStack);
		return (
			allOptions.find((o) => o.value === value || o.value === normalized || o.family === value) ??
			(value
				? { ...optionForFamily(value, 'system', kind === 'mono'), value: normalized }
				: defaultOption)
		);
	});
	const selectedStack = $derived(selectedOption.value || fallbackStack);

	onMount(async () => {
		isLoadingFonts = true;
		try {
			const result = await listSystemFonts();
			systemFonts = result.fonts;
			await document.fonts?.ready;
			// Recompute bundled availability after fontsource CSS has finished loading.
			fontCheckVersion += 1;
		} catch (e) {
			console.warn('Failed to list system fonts:', e);
			systemFonts = [];
		} finally {
			isLoadingFonts = false;
		}
	});

	function toggle() {
		open = !open;
		if (open) {
			queueMicrotask(() => searchInputEl?.focus());
		}
	}

	function select(opt: FontOption) {
		value = opt.value;
		open = false;
		onchange?.(opt.value);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') open = false;
	}

	function handleClickOutside(e: MouseEvent) {
		if (containerEl && !containerEl.contains(e.target as Node)) open = false;
	}

	$effect(() => {
		if (open) {
			document.addEventListener('click', handleClickOutside, true);
			return () => document.removeEventListener('click', handleClickOutside, true);
		}
	});
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div bind:this={containerEl} class="relative" onkeydown={handleKeydown}>
	<button
		type="button"
		class="border-border/60 hover:border-foreground/20 focus:border-foreground/30 flex w-56 items-center gap-2 rounded-md border bg-transparent px-2 py-1 text-left text-[12.5px] text-foreground transition-colors focus:outline-none"
		onclick={toggle}
		aria-haspopup="listbox"
		aria-expanded={open}
	>
		<span
			class="border-border/50 bg-muted/30 flex h-6 w-6 shrink-0 items-center justify-center rounded border text-[12px] text-foreground"
			style="font-family: {selectedStack}; line-height: 1;">Aa</span
		>
		<span class="min-w-0 flex-1 truncate" style="font-family: {selectedStack};">
			{selectedOption.label}
		</span>
		<span class="text-muted-foreground/55 transition-transform" class:rotate-180={open}>
			<Icon icon={ArrowDown01Icon} size={13} />
		</span>
	</button>

	{#if open}
		<div
			class="border-border/60 absolute right-0 top-full z-50 mt-1 w-[360px] overflow-hidden rounded-md border bg-popover shadow-xl"
			role="listbox"
		>
			<div class="border-border/40 border-b p-2">
				<input
					bind:this={searchInputEl}
					type="text"
					placeholder="Search installed fonts..."
					bind:value={query}
					class="border-border/60 placeholder:text-muted-foreground/40 focus:border-foreground/30 w-full rounded-md border bg-transparent px-2 py-1 text-[12px] text-foreground focus:outline-none"
				/>
			</div>
			<div class="max-h-[420px] overflow-y-auto py-1.5">
				{#snippet group(title: string, items: FontOption[])}
					<div
						class="text-muted-foreground/55 px-3 pb-1 pt-1.5 text-[10px] font-medium uppercase tracking-wider"
					>
						{title}
					</div>
					{#each items as opt (opt.value)}
						{@const isSelected =
							opt.value === value || opt.value === normalizeFontStack(value, fallbackStack)}
						<button
							type="button"
							class="hover:bg-foreground/5 flex w-full items-start gap-3 px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45 {isSelected
								? 'bg-[var(--ue-accent)]/10'
								: ''}"
							role="option"
							aria-selected={isSelected}
							disabled={opt.isAvailable === false}
							onclick={() => select(opt)}
						>
							<div class="min-w-0 flex-1">
								<div class="flex items-center gap-2">
									<span
										class="truncate text-[14px] text-foreground"
										style="font-family: {opt.value || fallbackStack};"
									>
										{opt.label}
									</span>
									{#if opt.source === 'bundled'}
										<span
											class="bg-[var(--ue-accent)]/15 text-[var(--ue-accent)]/75 shrink-0 rounded px-1 py-0.5 text-[9px] font-medium uppercase tracking-wider"
										>
											Bundled
										</span>
									{:else if opt.source === 'system'}
										<span
											class="bg-muted-foreground/15 text-muted-foreground/70 shrink-0 rounded px-1 py-0.5 text-[9px] font-medium uppercase tracking-wider"
										>
											System
										</span>
									{/if}
									{#if opt.isAvailable === false}
										<span
											class="shrink-0 rounded bg-red-500/15 px-1 py-0.5 text-[9px] font-medium uppercase tracking-wider text-red-300/80"
										>
											Missing
										</span>
									{/if}
								</div>
								<div
									class="text-muted-foreground/65 mt-0.5 truncate text-[12px]"
									style="font-family: {opt.value || fallbackStack};"
								>
									{opt.source === 'default'
										? `Use the platform's ${kind === 'mono' ? 'monospace' : 'system'} font`
										: sample}
								</div>
							</div>
							{#if isSelected}
								<span class="mt-1 shrink-0 text-[var(--ue-accent)]">
									<Icon icon={Tick02Icon} size={14} strokeWidth={2.5} />
								</span>
							{/if}
						</button>
					{/each}
				{/snippet}

				{#if !query.trim()}
					{@render group('Default', [defaultOption])}
					{@render group('Bundled fonts', bundledOptions)}
					<div class="bg-border/40 mx-3 my-1 h-px"></div>
				{/if}

				{#if isLoadingFonts}
					<div class="text-muted-foreground/50 px-3 py-4 text-center text-[12px]">
						Loading installed fonts…
					</div>
				{:else if filteredSystemOptions.length}
					{@render group(
						query.trim() ? 'Installed matches' : 'Installed on this system',
						filteredSystemOptions
					)}
				{:else}
					<div class="text-muted-foreground/50 px-3 py-4 text-center text-[12px]">
						{query.trim()
							? 'No installed font matches'
							: 'No installed fonts reported by the editor'}
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
