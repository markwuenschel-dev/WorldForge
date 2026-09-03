<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import {
		ArrowDown01Icon,
		ArrowUp01Icon,
		CheckmarkCircle02Icon,
		Loading03Icon,
		Image01Icon,
		Copy01Icon
	} from '@hugeicons/core-free-icons';
	import type { ContentBlock } from '$lib/bridge.js';
	import { copyToClipboard } from '$lib/bridge.js';

	let {
		block,
		resultBlock
	}: {
		block: ContentBlock;
		resultBlock?: ContentBlock;
	} = $props();

	let expanded = $state(true);
	let copied = $state(false);

	let status = $derived(
		!resultBlock ? 'running' : resultBlock.toolSuccess !== false ? 'success' : 'error'
	);

	let statusColor = $derived(
		status === 'running'
			? 'text-blue-400'
			: status === 'success'
				? 'text-emerald-400'
				: 'text-red-400'
	);

	// ── Parse arguments ─────────────────────────────────────────────

	let args = $derived.by(() => {
		if (!block.toolArguments) return null;
		try {
			return JSON.parse(block.toolArguments) as {
				mode?: string;
				asset_path?: string;
				view_mode?: string;
				focus_actor?: string;
				max_dimension?: number;
			};
		} catch {
			return null;
		}
	});

	let captureMode = $derived(args?.mode ?? 'active');
	let assetPath = $derived(args?.asset_path ?? '');
	let viewMode = $derived(args?.view_mode ?? '');
	let focusActor = $derived(args?.focus_actor ?? '');

	// ── Parse result text ───────────────────────────────────────────

	let resultText = $derived(resultBlock?.toolResult ?? '');

	/** Parse "Camera: Location=(...) Rotation=(...) FOV=90.0" from result */
	let cameraInfo = $derived.by(() => {
		if (!resultText) return null;
		const locMatch = resultText.match(/Location=\(([^)]+)\)/);
		const rotMatch = resultText.match(/Rotation=\(([^)]+)\)/);
		const fovMatch = resultText.match(/FOV=([\d.]+)/);
		const resMatch = resultText.match(/\((\d+x\d+)\)/);
		if (!locMatch && !rotMatch && !fovMatch && !resMatch) return null;
		return {
			location: locMatch?.[1] ?? '',
			rotation: rotMatch?.[1] ?? '',
			fov: fovMatch?.[1] ?? '',
			resolution: resMatch?.[1] ?? ''
		};
	});

	/** First line = description, e.g. "Level viewport screenshot captured (Lit mode)" */
	let captureDescription = $derived.by(() => {
		if (!resultText) return '';
		return resultText.split('\n')[0] ?? '';
	});

	let hasImages = $derived((resultBlock?.images && resultBlock.images.length > 0) ?? false);

	let primaryImage = $derived(resultBlock?.images?.[0] ?? null);

	/** Mode badge text */
	let modeBadge = $derived.by(() => {
		if (captureMode === 'asset')
			return assetPath ? (assetPath.split('/').pop() ?? 'Asset') : 'Asset';
		if (captureMode === 'level') return viewMode || 'Level';
		return 'Active';
	});

	let modeBadgeColor = $derived.by(() => {
		if (captureMode === 'asset') return 'text-violet-400 bg-violet-500/15';
		if (captureMode === 'level') return 'text-sky-400 bg-sky-500/15';
		return 'text-neutral-400 bg-neutral-500/15';
	});

	function handleCopy() {
		if (resultText) {
			copyToClipboard(resultText);
			copied = true;
			setTimeout(() => {
				copied = false;
			}, 1500);
		}
	}

	function imageDataUrl(base64: string, mimeType: string): string {
		return `data:${mimeType};base64,${base64}`;
	}
</script>

<div class="bg-card/50 my-2.5 w-full overflow-hidden rounded-xl border border-border">
	<!-- Header -->
	<div class="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-[13px]">
		<!-- Status icon -->
		<span class="flex h-4 w-4 shrink-0 items-center justify-center {statusColor}">
			<Icon
				icon={status === 'running' ? Loading03Icon : Image01Icon}
				size={15}
				strokeWidth={1.5}
				class={status === 'running' ? 'animate-spin' : ''}
			/>
		</span>

		<!-- Title -->
		<span class="min-w-0 flex-1 truncate font-medium text-foreground"> Screenshot </span>

		<!-- Mode badge -->
		<span class="shrink-0 rounded-md px-2 py-0.5 text-[10px] font-medium {modeBadgeColor}">
			{modeBadge}
		</span>

		<!-- Resolution -->
		{#if cameraInfo?.resolution}
			<span class="text-muted-foreground/60 shrink-0 text-[10px] tabular-nums">
				{cameraInfo.resolution}
			</span>
		{/if}

		{#if status === 'error'}
			<span
				class="shrink-0 rounded-md bg-red-500/15 px-1.5 py-0.5 text-[10px] font-medium text-red-400"
			>
				failed
			</span>
		{/if}

		<!-- Expand/collapse toggle -->
		<button
			class="text-muted-foreground/60 hover:bg-accent/30 shrink-0 rounded p-1 transition-colors hover:text-foreground"
			onclick={() => (expanded = !expanded)}
			title={expanded ? 'Collapse' : 'Expand'}
		>
			<Icon icon={expanded ? ArrowUp01Icon : ArrowDown01Icon} size={12} strokeWidth={1.5} />
		</button>
	</div>

	<!-- Image content -->
	{#if status === 'running'}
		<div class="border-border/50 flex items-center justify-center border-t px-3.5 py-6">
			<span class="animate-pulse font-mono text-[11px] text-muted-foreground"
				>Capturing screenshot...</span
			>
		</div>
	{:else if hasImages && primaryImage}
		{#if expanded}
			<!-- Full image view -->
			<div class="border-border/50 border-t">
				<div class="relative bg-black/30">
					<img
						src={imageDataUrl(primaryImage.base64, primaryImage.mimeType)}
						alt={captureDescription || 'Screenshot'}
						class="h-auto w-full object-contain"
						style="max-height: 500px;"
					/>
				</div>

				<!-- Info bar below image -->
				<div class="text-muted-foreground/70 flex items-center gap-2 px-3.5 py-2 text-[10px]">
					<span class="min-w-0 flex-1 truncate">{captureDescription}</span>

					{#if focusActor}
						<span
							class="bg-secondary/60 text-muted-foreground/60 shrink-0 rounded px-1.5 py-0.5 font-mono"
						>
							{focusActor}
						</span>
					{/if}

					<button
						class="text-muted-foreground/50 shrink-0 rounded p-0.5 transition-colors hover:text-foreground"
						onclick={handleCopy}
						title="Copy info"
					>
						{#if copied}
							<Icon
								icon={CheckmarkCircle02Icon}
								size={12}
								strokeWidth={1.5}
								class="text-emerald-400"
							/>
						{:else}
							<Icon icon={Copy01Icon} size={12} strokeWidth={1.5} />
						{/if}
					</button>
				</div>
			</div>
		{:else}
			<!-- Collapsed: smaller preview -->
			<button class="border-border/50 block w-full border-t" onclick={() => (expanded = true)}>
				<div class="relative bg-black/30">
					<img
						src={imageDataUrl(primaryImage.base64, primaryImage.mimeType)}
						alt={captureDescription || 'Screenshot'}
						class="h-auto w-full object-contain"
						style="max-height: 120px;"
					/>
				</div>
			</button>
		{/if}
	{:else if status === 'error'}
		<div class="border-border/50 border-t px-3.5 py-2.5">
			<pre class="font-mono text-[11px] leading-relaxed text-red-400/80">{resultText ||
					'Screenshot failed'}</pre>
		</div>
	{:else}
		<!-- Success but no images (shouldn't happen normally) -->
		<div class="border-border/50 border-t px-3.5 py-2.5">
			<pre class="text-foreground/60 font-mono text-[11px] leading-relaxed">{resultText}</pre>
		</div>
	{/if}
</div>
