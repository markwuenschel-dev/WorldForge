<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu/index.js';
	import { ArrowDown01Icon, FlashIcon, Settings02Icon } from '@hugeicons/core-free-icons';
	import type {
		ConfigSelectGroup,
		ConfigSelectValue,
		SessionConfigOption,
		SessionSelectConfigOption
	} from '$lib/bridge.js';

	type Props = {
		options: SessionConfigOption[];
		disabled?: boolean;
		onselect: (configId: string, value: string | boolean) => void;
	};

	let { options, disabled = false, onselect }: Props = $props();

	let primaryOption = $derived(
		options.find(
			(option): option is SessionSelectConfigOption =>
				option.type === 'select' && (option.category === 'model' || option.id === 'model')
		)
	);
	let otherOptions = $derived(options.filter((option) => option.id !== primaryOption?.id));
	let primaryLabel = $derived(
		primaryOption
			? findSelectValue(primaryOption, primaryOption.currentValue)?.name ||
					primaryOption.currentValue ||
					primaryOption.name
			: 'Options'
	);

	// Fast mode is id "fast" on claude-agent-acp and "fast-mode" on codex-acp —
	// a boolean toggle, or an on/off select for clients without boolean config
	// options.
	let fastOption = $derived(
		options.find((option) => {
			const id = option.id.toLowerCase().replace(/[-_]/g, '');
			return id === 'fast' || id === 'fastmode';
		})
	);
	let fastModeOn = $derived(
		fastOption
			? fastOption.type === 'boolean'
				? fastOption.currentValue === true
				: fastOption.currentValue === 'on'
			: false
	);

	let effortOption = $derived(
		options.find(
			(option): option is SessionSelectConfigOption =>
				option.type === 'select' &&
				(option.category === 'thought_level' || option.id === 'effort' || option.id === 'thinking')
		)
	);
	let effortValue = $derived(
		effortOption ? findSelectValue(effortOption, effortOption.currentValue) : undefined
	);
	let effortLabel = $derived(
		effortOption ? abbreviateEffort(effortOption.currentValue, effortValue?.name) : ''
	);
	// Muted at the low end, warming toward amber/orange as effort climbs.
	const EFFORT_TIER_CLASSES = [
		'text-muted-foreground/60',
		'text-muted-foreground',
		'text-amber-500/80',
		'text-orange-500/80'
	] as const;

	let effortClass = $derived(
		effortOption ? EFFORT_TIER_CLASSES[effortTier(effortOption.currentValue)] : ''
	);

	// Keyed by value so display order of the adapter's list doesn't matter.
	const EFFORT_ABBREVIATIONS: Record<string, string> = {
		off: 'Off',
		none: 'Off',
		minimal: 'Min',
		low: 'Low',
		medium: 'Med',
		high: 'High',
		xhigh: 'XHigh',
		max: 'Max'
	};

	function abbreviateEffort(value: string, name: string | undefined): string {
		const known = EFFORT_ABBREVIATIONS[value.toLowerCase()];
		if (known) return known;
		const label = name || value;
		return label.length > 5 ? label.slice(0, 4) : label;
	}

	function effortTier(value: string): number {
		switch (value.toLowerCase()) {
			case 'off':
			case 'none':
			case 'minimal':
			case 'low':
				return 0;
			case 'medium':
				return 1;
			case 'high':
				return 2;
			case 'xhigh':
			case 'max':
				return 3;
			default:
				return 1;
		}
	}

	function isSelectGroup(value: ConfigSelectValue | ConfigSelectGroup): value is ConfigSelectGroup {
		return 'options' in value && Array.isArray(value.options);
	}

	function isSelectValue(value: ConfigSelectValue | ConfigSelectGroup): value is ConfigSelectValue {
		return !isSelectGroup(value);
	}

	function selectGroups(option: SessionSelectConfigOption): ConfigSelectGroup[] {
		const values = option.options ?? [];
		if (values.length === 0) return [];
		if (isSelectGroup(values[0])) return values.filter(isSelectGroup);
		return [{ group: '', name: '', options: values.filter(isSelectValue) }];
	}

	function findSelectValue(
		option: SessionSelectConfigOption,
		value: string
	): ConfigSelectValue | undefined {
		return selectGroups(option)
			.flatMap((group) => group.options)
			.find((candidate) => candidate.value === value);
	}

	function currentSelectLabel(option: SessionSelectConfigOption): string {
		return findSelectValue(option, option.currentValue)?.name || option.currentValue || option.name;
	}
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger
		class="flex min-h-10 max-w-[220px] items-center gap-1.5 rounded-lg px-2 py-2 text-[12px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
		{disabled}
		aria-label="Session settings"
		title={fastModeOn ? 'Session settings — Fast mode on' : 'Session settings'}
	>
		{#if !primaryOption}
			<Icon icon={Settings02Icon} size={13} strokeWidth={1.5} />
		{/if}
		{#if fastModeOn}
			<Icon icon={FlashIcon} size={12} strokeWidth={1.5} class="shrink-0 text-amber-400/90" />
		{/if}
		<span class="truncate">{primaryLabel}</span>
		{#if effortLabel}
			<span class="shrink-0 text-[10px] font-medium {effortClass}">{effortLabel}</span>
		{/if}
		<Icon icon={ArrowDown01Icon} size={10} strokeWidth={1.5} class="shrink-0 opacity-50" />
	</DropdownMenu.Trigger>

	<DropdownMenu.Content
		class="max-h-[65vh] w-[280px] overflow-y-auto"
		side="top"
		align="start"
		sideOffset={4}
	>
		<DropdownMenu.Label class="text-[11px] text-muted-foreground"
			>Session settings</DropdownMenu.Label
		>

		{#if primaryOption}
			{#each selectGroups(primaryOption) as group, groupIndex (`${primaryOption.id}-${group.group}-${groupIndex}`)}
				{#if group.name}
					{#if groupIndex > 0}<DropdownMenu.Separator />{/if}
					<DropdownMenu.Label class="text-[11px] text-muted-foreground"
						>{group.name}</DropdownMenu.Label
					>
				{/if}
				{#each group.options as choice (choice.value)}
					<DropdownMenu.Item
						class="flex items-center gap-2 px-2 py-1.5"
						onclick={() => onselect(primaryOption.id, choice.value)}
					>
						<div class="min-w-0 flex-1">
							<div class="truncate text-[13px]">{choice.name}</div>
							{#if choice.description}
								<div class="text-muted-foreground/60 truncate text-[11px]">
									{choice.description}
								</div>
							{/if}
						</div>
						{#if choice.value === primaryOption.currentValue}
							<span class="h-1.5 w-1.5 shrink-0 rounded-full bg-foreground"></span>
						{/if}
					</DropdownMenu.Item>
				{/each}
			{/each}
		{/if}

		{#if primaryOption && otherOptions.length > 0}<DropdownMenu.Separator />{/if}

		{#each otherOptions as option (option.id)}
			{#if option.type === 'boolean'}
				<DropdownMenu.Item
					class="flex items-center gap-2 px-2 py-1.5"
					role="menuitemcheckbox"
					aria-checked={option.currentValue}
					onclick={() => onselect(option.id, !option.currentValue)}
				>
					<div class="min-w-0 flex-1">
						<div class="truncate text-[13px]">{option.name}</div>
						{#if option.description}
							<div class="text-muted-foreground/60 truncate text-[11px]">{option.description}</div>
						{/if}
					</div>
					<span
						class="h-4 w-7 shrink-0 rounded-full p-0.5 transition-colors {option.currentValue
							? 'bg-[var(--ue-accent)]'
							: 'bg-muted-foreground/30'}"
					>
						<span
							class="block h-3 w-3 rounded-full bg-white transition-transform {option.currentValue
								? 'translate-x-3'
								: 'translate-x-0'}"
						></span>
					</span>
				</DropdownMenu.Item>
			{:else}
				<DropdownMenu.Sub>
					<DropdownMenu.SubTrigger class="flex items-center gap-2 px-2 py-1.5">
						<div class="min-w-0 flex-1">
							<div class="truncate text-[13px]">{option.name}</div>
							<div class="text-muted-foreground/60 truncate text-[11px]">
								{currentSelectLabel(option)}
							</div>
						</div>
					</DropdownMenu.SubTrigger>
					<DropdownMenu.SubContent class="max-h-[65vh] w-[260px] overflow-y-auto">
						{#if option.description}
							<DropdownMenu.Label class="text-[11px] text-muted-foreground">
								{option.description}
							</DropdownMenu.Label>
						{/if}
						{#each selectGroups(option) as group, groupIndex (`${option.id}-${group.group}-${groupIndex}`)}
							{#if group.name}
								{#if groupIndex > 0 || option.description}<DropdownMenu.Separator />{/if}
								<DropdownMenu.Label class="text-[11px] text-muted-foreground"
									>{group.name}</DropdownMenu.Label
								>
							{/if}
							{#each group.options as choice (choice.value)}
								<DropdownMenu.Item
									class="flex items-center gap-2 px-2 py-1.5"
									onclick={() => onselect(option.id, choice.value)}
								>
									<div class="min-w-0 flex-1">
										<div class="truncate text-[13px]">{choice.name}</div>
										{#if choice.description}
											<div class="text-muted-foreground/60 truncate text-[11px]">
												{choice.description}
											</div>
										{/if}
									</div>
									{#if choice.value === option.currentValue}
										<span class="h-1.5 w-1.5 shrink-0 rounded-full bg-foreground"></span>
									{/if}
								</DropdownMenu.Item>
							{/each}
						{/each}
					</DropdownMenu.SubContent>
				</DropdownMenu.Sub>
			{/if}
		{/each}
	</DropdownMenu.Content>
</DropdownMenu.Root>
