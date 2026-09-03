<script lang="ts">
	import type { Component } from 'svelte';
	import type { StreamdownProps } from 'svelte-streamdown';
	import { cn } from '$lib/utils';

	type Props = StreamdownProps & {
		class?: string;
	};

	let {
		class: className,
		content,
		parseIncompleteMarkdown = false,
		...restProps
	}: Props = $props();

	let RichResponse: Component<Props> | null = $state(null);
	let richLoadVersion = 0;

	// Keep the Markdown parser and its code/diagram/math graph out of the hot
	// streaming path. A finalized visible block loads it once and upgrades from
	// cheap text to rich output; an obsolete async import may not mutate a block
	// that resumed streaming or was destroyed.
	$effect(() => {
		if (parseIncompleteMarkdown || RichResponse) return;
		const version = ++richLoadVersion;
		void import('./RichResponse.svelte').then((module) => {
			if (version === richLoadVersion && !parseIncompleteMarkdown) {
				RichResponse = module.default;
			}
		});
		return () => {
			richLoadVersion += 1;
		};
	});
</script>

{#if !parseIncompleteMarkdown && RichResponse}
	<RichResponse class={className} {content} parseIncompleteMarkdown={false} {...restProps} />
{:else}
	<div
		class={cn(
			'size-full whitespace-pre-wrap break-words [&>*:first-child]:mt-0 [&>*:last-child]:mb-0',
			className
		)}
	>
		{content}
	</div>
{/if}
