<script lang="ts">
	import { ContextMenu as ContextMenuPrimitive } from 'bits-ui';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import { cn, type WithoutChild } from '$lib/utils.js';

	let {
		ref = $bindable(null),
		class: className,
		inset,
		children,
		...restProps
	}: WithoutChild<ContextMenuPrimitive.SubTriggerProps> & {
		inset?: boolean;
	} = $props();
</script>

<ContextMenuPrimitive.SubTrigger
	bind:ref
	data-slot="context-menu-sub-trigger"
	data-inset={inset}
	class={cn(
		"flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-accent data-[state=open]:bg-accent data-[inset]:ps-8 data-[highlighted]:text-accent-foreground data-[state=open]:text-accent-foreground data-[disabled]:opacity-50 [&_svg:not([class*='text-'])]:text-muted-foreground [&_svg:not([class*='w-'])]:h-4 [&_svg:not([class*='w-'])]:w-4 [&_svg]:pointer-events-none [&_svg]:shrink-0",
		className
	)}
	{...restProps}
>
	{@render children?.()}
	<ChevronRightIcon class="ms-auto" />
</ContextMenuPrimitive.SubTrigger>
