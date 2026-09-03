<script lang="ts">
	import { Streamdown, type StreamdownProps } from 'svelte-streamdown';
	import { cn } from '$lib/utils';
	import { DEFAULT_ALLOWED_RESPONSE_IMAGE_PREFIXES } from '$lib/imagePolicy.js';
	import { DEFAULT_ALLOWED_RESPONSE_LINK_PREFIXES } from '$lib/linkPolicy.js';

	type Props = StreamdownProps & {
		class?: string;
	};

	let {
		class: className,
		allowedImagePrefixes,
		allowedLinkPrefixes,
		...restProps
	}: Props = $props();
</script>

<!--
	allowedLinkPrefixes admits local paths on purpose. Streamdown's default
	allowlist passes http(s) only, so an agent pointing at a file on disk
	rendered as an inert "[blocked]" span — visible, unexplained, unusable. The
	widened list makes them real anchors; the layout's click handler routes them
	to the editor, and no anchor in this panel is ever allowed to navigate.
-->
<Streamdown
	class={cn('size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0', className)}
	baseTheme="shadcn"
	static={true}
	parseIncompleteMarkdown={false}
	animation={{ enabled: false }}
	allowedImagePrefixes={allowedImagePrefixes ?? [...DEFAULT_ALLOWED_RESPONSE_IMAGE_PREFIXES]}
	allowedLinkPrefixes={allowedLinkPrefixes ?? [...DEFAULT_ALLOWED_RESPONSE_LINK_PREFIXES]}
	{...restProps}
/>
