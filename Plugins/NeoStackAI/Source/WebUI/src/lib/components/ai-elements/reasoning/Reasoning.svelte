<script lang="ts">
	import { untrack } from 'svelte';
	import { cn } from '$lib/utils';
	import { watch } from 'runed';
	import { Collapsible } from '$lib/components/ui/collapsible/index.js';
	import { ReasoningContext, setReasoningContext } from './reasoning-context.svelte';

	interface Props {
		class?: string;
		isStreaming?: boolean;
		open?: boolean;
		defaultOpen?: boolean;
		onOpenChange?: (open: boolean) => void;
		duration?: number;
		children?: import('svelte').Snippet;
	}

	let {
		class: className = '',
		isStreaming = false,
		open = $bindable(),
		defaultOpen = true,
		onOpenChange,
		duration = $bindable(),
		children,
		...props
	}: Props = $props();

	let AUTO_CLOSE_DELAY = 1000;
	let MS_IN_S = 1000;

	// defaultOpen is an initial-state prop (callers may pass a live value such
	// as the block's isStreaming). Capture it once so the auto-close watch
	// below still fires after the prop flips false when streaming ends.
	const openedByDefault = untrack(() => defaultOpen);
	const initialIsStreaming = untrack(() => isStreaming);
	const initialOpen = untrack(() => open ?? defaultOpen);
	const initialDuration = untrack(() => duration ?? 0);

	// Create the reasoning context
	let reasoningContext = new ReasoningContext({
		isStreaming: initialIsStreaming,
		isOpen: initialOpen,
		duration: initialDuration
	});

	// Set up controllable state for open
	let isOpen = $state(initialOpen);
	let hasAutoClosed = $state(false);
	let startTime = $state<number | null>(null);

	// Sync external props to context and local state
	$effect(() => {
		reasoningContext.isStreaming = isStreaming;
	});

	$effect(() => {
		if (open !== undefined) {
			isOpen = open;
			reasoningContext.isOpen = open;
		}
	});

	$effect(() => {
		if (duration !== undefined) {
			reasoningContext.duration = duration;
		}
	});

	// Track duration when streaming starts and ends
	watch(
		() => isStreaming,
		(isStreamingValue) => {
			if (isStreamingValue) {
				if (startTime === null) {
					startTime = Date.now();
				}
			} else if (startTime !== null) {
				let newDuration = Math.ceil((Date.now() - startTime) / MS_IN_S);
				reasoningContext.duration = newDuration;
				if (duration !== undefined) {
					duration = newDuration;
				}
				startTime = null;
			}
		}
	);

	// Auto-close when streaming ends (once only) — only for blocks that
	// mounted open (openedByDefault), i.e. live-streamed ones.
	watch(
		() => [isStreaming, isOpen, hasAutoClosed] as const,
		([isStreamingValue, isOpenValue, hasAutoClosedValue]) => {
			if (openedByDefault && !isStreamingValue && isOpenValue && !hasAutoClosedValue) {
				// Add a small delay before closing to allow user to see the content
				let timer = setTimeout(() => {
					handleOpenChange(false);
					hasAutoClosed = true;
				}, AUTO_CLOSE_DELAY);

				return () => clearTimeout(timer);
			}
		}
	);

	let handleOpenChange = (newOpen: boolean) => {
		isOpen = newOpen;
		reasoningContext.setIsOpen(newOpen);

		if (open !== undefined) {
			open = newOpen;
		}

		onOpenChange?.(newOpen);
	};

	// Set the context for child components
	setReasoningContext(reasoningContext);
</script>

<Collapsible
	class={cn('not-prose mb-4', className)}
	bind:open={isOpen}
	onOpenChange={handleOpenChange}
	{...props}
>
	{@render children?.()}
</Collapsible>
