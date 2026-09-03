<script lang="ts">
	import { ContextMenu as ContextMenuPrimitive } from 'bits-ui';
	import { cn } from '$lib/utils.js';

	let {
		ref = $bindable(null),
		class: className,
		inset,
		variant = 'default',
		...restProps
	}: ContextMenuPrimitive.ItemProps & {
		inset?: boolean;
		variant?: 'default' | 'destructive';
	} = $props();
</script>

<ContextMenuPrimitive.Item
	bind:ref
	data-slot="context-menu-item"
	data-inset={inset}
	data-variant={variant}
	class={cn(
		"data-[variant=destructive]:data-[highlighted]:bg-destructive/10 dark:data-[variant=destructive]:data-[highlighted]:bg-destructive/20 relative flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-accent data-[inset]:ps-8 data-[highlighted]:text-accent-foreground data-[variant=destructive]:data-[highlighted]:text-destructive data-[variant=destructive]:text-destructive data-[disabled]:opacity-50 [&_svg:not([class*='text-'])]:text-muted-foreground [&_svg:not([class*='w-'])]:h-4 [&_svg:not([class*='w-'])]:w-4 [&_svg]:pointer-events-none [&_svg]:shrink-0 data-[variant=destructive]:[&_svg]:!text-destructive",
		className
	)}
	{...restProps}
/>
