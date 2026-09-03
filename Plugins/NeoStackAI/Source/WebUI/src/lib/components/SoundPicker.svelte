<script lang="ts">
	import { ArrowDown01Icon, PlayIcon, Cancel01Icon } from '@hugeicons/core-free-icons';
	import Icon from '$lib/components/Icon.svelte';
	import {
		listSoundAssets,
		previewNotificationSound,
		soundAssetExists,
		type SoundAsset
	} from '$lib/bridge.js';

	let {
		label,
		value = $bindable(''),
		volume = 1,
		onchange
	}: {
		label: string;
		value: string;
		volume?: number;
		onchange?: (newValue: string) => void;
	} = $props();

	let open = $state(false);
	let query = $state('');
	let sounds = $state<SoundAsset[]>([]);
	let isLoading = $state(false);
	let isMissing = $state(false);
	let containerEl: HTMLDivElement | undefined = $state();
	let searchInputEl: HTMLInputElement | undefined = $state();
	let debounceTimer: ReturnType<typeof setTimeout> | undefined = $state();

	$effect(() => {
		const current = value;
		if (!current) {
			isMissing = false;
			return;
		}
		let cancelled = false;
		soundAssetExists(current).then((exists) => {
			if (!cancelled) isMissing = !exists;
		});
		return () => {
			cancelled = true;
		};
	});

	const selectedName = $derived(() => {
		if (!value) return '(default)';
		// FSoftObjectPath shape: "/Game/Sounds/MySound.MySound" or "/Game/Sounds/MySound"
		const afterDot = value.includes('.') ? value.split('.').pop()! : value.split('/').pop()!;
		return afterDot || value;
	});

	async function fetchSounds(q: string) {
		isLoading = true;
		try {
			sounds = await listSoundAssets(q);
		} catch (e) {
			console.warn('Failed to list sound assets:', e);
			sounds = [];
		} finally {
			isLoading = false;
		}
	}

	function scheduleFetch(q: string) {
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => fetchSounds(q), 120);
	}

	function toggle() {
		open = !open;
		if (open) {
			fetchSounds(query);
			// Focus the search field once the dropdown has rendered
			queueMicrotask(() => searchInputEl?.focus());
		}
	}

	function select(path: string) {
		value = path;
		open = false;
		onchange?.(path);
	}

	function clear(e: MouseEvent) {
		e.stopPropagation();
		value = '';
		onchange?.('');
	}

	async function preview(e: MouseEvent, path: string) {
		e.stopPropagation();
		try {
			await previewNotificationSound(path, volume);
		} catch (err) {
			console.warn('Preview failed:', err);
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			open = false;
		}
	}

	function handleClickOutside(e: MouseEvent) {
		if (containerEl && !containerEl.contains(e.target as Node)) {
			open = false;
		}
	}

	$effect(() => {
		if (open) {
			document.addEventListener('click', handleClickOutside, true);
			return () => document.removeEventListener('click', handleClickOutside, true);
		}
	});
</script>

<div class="flex items-center justify-between gap-3 rounded-md px-1 py-2.5">
	<div class="min-w-0 flex-1">
		<p class="text-[13px] text-foreground">{label}</p>
		<p
			class="mt-0.5 truncate text-[11px]"
			class:text-muted-foreground={!isMissing}
			class:opacity-50={!isMissing}
			class:text-red-400={isMissing}
			title={isMissing ? `${value} (asset not found)` : value}
		>
			{selectedName()}{#if isMissing}
				<span class="text-red-400">(missing)</span>{/if}
		</p>
	</div>

	<div
		bind:this={containerEl}
		class="relative w-56 shrink-0"
		role="combobox"
		aria-label="Notification sound picker"
		aria-expanded={open}
		aria-controls="notification-sound-options"
		aria-haspopup="listbox"
		tabindex="-1"
		onkeydown={handleKeydown}
	>
		<div class="flex items-center gap-1">
			<button
				type="button"
				class="border-border/60 hover:border-foreground/20 focus:border-foreground/30 flex flex-1 items-center justify-between rounded-md border bg-transparent px-3 py-1.5 text-left text-[12px] text-foreground transition-colors focus:outline-none"
				onclick={toggle}
			>
				<span class="truncate">Change</span>
				<span class="text-muted-foreground/60 ml-2 transition-transform" class:rotate-180={open}>
					<Icon icon={ArrowDown01Icon} size={12} />
				</span>
			</button>

			{#if value}
				<button
					type="button"
					class="border-border/60 text-muted-foreground/60 rounded-md border px-1.5 py-1.5 transition-colors hover:text-foreground"
					onclick={(e) => preview(e, value)}
					title="Preview"
				>
					<Icon icon={PlayIcon} size={12} />
				</button>
				<button
					type="button"
					class="border-border/60 text-muted-foreground/60 rounded-md border px-1.5 py-1.5 transition-colors hover:text-red-400"
					onclick={clear}
					title="Clear"
				>
					<Icon icon={Cancel01Icon} size={12} />
				</button>
			{/if}
		</div>

		{#if open}
			<div
				id="notification-sound-options"
				role="listbox"
				class="border-border/60 absolute right-0 top-full z-50 mt-1 w-72 overflow-hidden rounded-md border bg-surface-popup shadow-lg"
			>
				<div class="border-border/40 border-b p-2">
					<input
						bind:this={searchInputEl}
						type="text"
						placeholder="Search sounds..."
						bind:value={query}
						oninput={() => scheduleFetch(query)}
						class="border-border/60 placeholder:text-muted-foreground/40 focus:border-foreground/30 w-full rounded-md border bg-transparent px-2 py-1 text-[12px] text-foreground focus:outline-none"
					/>
				</div>

				<div class="max-h-64 overflow-y-auto">
					{#if isLoading}
						<div class="text-muted-foreground/50 px-3 py-4 text-center text-[12px]">Loading…</div>
					{:else if sounds.length === 0}
						<div class="text-muted-foreground/50 px-3 py-4 text-center text-[12px]">
							{query ? 'No matches' : 'No SoundBase assets in /Game'}
						</div>
					{:else}
						{#each sounds as sound (sound.path)}
							<div
								class="hover:bg-foreground/5 group flex items-center gap-1 px-2 py-1.5 transition-colors"
							>
								<button
									type="button"
									class="min-w-0 flex-1 text-left"
									onclick={() => select(sound.path)}
								>
									<span class="block truncate text-[12px] text-foreground">{sound.name}</span>
									<span class="text-muted-foreground/50 block truncate text-[10px]"
										>{sound.folder}</span
									>
								</button>
								<button
									type="button"
									class="focus-ring text-muted-foreground/50 flex h-10 w-10 items-center justify-center rounded transition-all hover:text-foreground focus:opacity-100 group-hover:opacity-100"
									onclick={(e) => preview(e, sound.path)}
									title="Preview"
									aria-label={`Preview ${sound.name}`}
								>
									<Icon icon={PlayIcon} size={11} />
								</button>
							</div>
						{/each}
					{/if}
				</div>
			</div>
		{/if}
	</div>
</div>
