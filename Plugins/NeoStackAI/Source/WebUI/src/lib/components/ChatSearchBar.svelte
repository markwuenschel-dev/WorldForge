<script lang="ts">
	import { onMount } from 'svelte';
	import Icon from '$lib/components/Icon.svelte';
	import { ArrowUp01Icon, ArrowDown01Icon, Cancel01Icon } from '@hugeicons/core-free-icons';
	import { t } from '$lib/i18n.js';
	import type { ChatMessage } from '$lib/bridge.js';
	import { searchTranscript } from '$lib/transcriptSearch.js';

	interface Props {
		messages: ChatMessage[];
		onselect: (messageId: string) => void;
		onclose: () => void;
	}

	let { messages, onselect, onclose }: Props = $props();
	let query = $state('');
	let inputEl: HTMLInputElement | undefined = $state();
	let currentIndex = $state(-1);
	let matches = $derived(searchTranscript(messages, query));

	onMount(() => inputEl?.focus());

	$effect(() => {
		const firstMatch = matches[0];
		currentIndex = firstMatch ? 0 : -1;
		if (firstMatch) onselect(firstMatch.messageId);
	});

	function selectCurrent() {
		if (currentIndex < 0 || !matches[currentIndex]) return;
		onselect(matches[currentIndex].messageId);
	}

	function goNext() {
		if (matches.length === 0) return;
		currentIndex = (currentIndex + 1) % matches.length;
		selectCurrent();
	}

	function goPrev() {
		if (matches.length === 0) return;
		currentIndex = (currentIndex - 1 + matches.length) % matches.length;
		selectCurrent();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!e.metaKey && !e.ctrlKey && !e.altKey) e.stopPropagation();
		if (e.key === 'Escape') onclose();
		else if (e.key === 'Enter') {
			e.preventDefault();
			if (e.shiftKey) goPrev();
			else goNext();
		}
	}
</script>

<div
	class="absolute left-2 right-2 top-2 z-20 flex items-center gap-1 rounded-lg border border-border bg-card px-2 py-1.5 shadow-lg sm:left-auto sm:right-4"
	style="box-shadow: 0 2px 12px rgba(0,0,0,0.25);"
	role="search"
>
	<label class="min-w-0 flex-1 sm:flex-none">
		<span class="sr-only">{$t('search_in_chat')}</span>
		<input
			bind:this={inputEl}
			bind:value={query}
			onkeydown={handleKeydown}
			placeholder={$t('search_in_chat')}
			spellcheck="false"
			class="placeholder:text-muted-foreground/50 min-h-10 w-full min-w-0 bg-transparent px-1.5 text-[13px] text-foreground focus:outline-none sm:w-[200px]"
		/>
	</label>
	<span class="text-muted-foreground/60 min-w-[60px] text-center text-[11px]" aria-live="polite">
		{#if query.trim()}
			{matches.length > 0
				? $t('n_of_m_matches', { n: currentIndex + 1, m: matches.length })
				: $t('no_matches')}
		{/if}
	</span>
	<button
		class="text-muted-foreground/60 flex h-10 w-10 items-center justify-center rounded transition-colors hover:bg-accent hover:text-foreground disabled:opacity-30"
		onclick={goPrev}
		disabled={matches.length === 0}
		aria-label="Previous search result"
	>
		<Icon icon={ArrowUp01Icon} size={14} strokeWidth={2} />
	</button>
	<button
		class="text-muted-foreground/60 flex h-10 w-10 items-center justify-center rounded transition-colors hover:bg-accent hover:text-foreground disabled:opacity-30"
		onclick={goNext}
		disabled={matches.length === 0}
		aria-label="Next search result"
	>
		<Icon icon={ArrowDown01Icon} size={14} strokeWidth={2} />
	</button>
	<button
		class="text-muted-foreground/60 flex h-10 w-10 items-center justify-center rounded transition-colors hover:bg-accent hover:text-foreground"
		onclick={onclose}
		aria-label="Close transcript search"
	>
		<Icon icon={Cancel01Icon} size={14} strokeWidth={2} />
	</button>
</div>
