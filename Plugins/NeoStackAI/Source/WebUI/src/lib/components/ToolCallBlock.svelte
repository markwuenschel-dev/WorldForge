<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import ToolCallBlock from '$lib/components/ToolCallBlock.svelte';
	import AssetReadBlock from '$lib/components/AssetReadBlock.svelte';
	import ScreenshotBlock from '$lib/components/ScreenshotBlock.svelte';
	import ToolResultImage from '$lib/components/ToolResultImage.svelte';
	import { createBoundedTextView } from '$lib/textBudget.js';
	import {
		ArrowDown01Icon,
		ArrowUp01Icon,
		CheckmarkCircle02Icon,
		Cancel01Icon,
		Loading03Icon,
		CommandLineIcon,
		File01Icon
	} from '@hugeicons/core-free-icons';
	import type { ContentBlock } from '$lib/bridge.js';
	import { openPath } from '$lib/bridge.js';
	import { toolCallDensity } from '$lib/stores/settings.js';

	let {
		block,
		resultBlock,
		childBlocks = [],
		toolIndex,
		depth = 0
	}: {
		block: ContentBlock;
		resultBlock?: ContentBlock;
		childBlocks?: ContentBlock[];
		toolIndex: {
			resultByCallId: Record<string, ContentBlock>;
			toolCallById: Record<string, ContentBlock>;
			parentToChildren: Record<string, string[]>;
		};
		depth?: number;
	} = $props();

	// In Detailed density, tool blocks expand by default. In Compact (the
	// historical default), they collapse and reveal on click. The effect
	// resyncs when the user flips the density preference.
	let expanded = $derived($toolCallDensity === 'detailed');

	/** Stripped tool name — removes MCP prefix like mcp__neostack__read_asset → read_asset */
	let toolName = $derived(block.toolName?.replace(/^mcp__[^_]+__/, '') ?? 'tool');

	let isTask = $derived(block.toolName === 'Task');
	let isBash = $derived(block.toolName === 'Bash');
	let isScreenshot = $derived(toolName === 'screenshot');
	let isAssetRead = $derived(toolName === 'read_asset');
	let isReadLike = $derived(
		toolName === 'Read' || toolName === 'read_file' || toolName === 'ReadFile'
	);

	let status = $derived(
		!resultBlock
			? block.isStreaming === false
				? 'cancelled'
				: 'running'
			: resultBlock.toolSuccess !== false
				? 'success'
				: 'error'
	);

	let statusIcon = $derived(
		status === 'running'
			? Loading03Icon
			: status === 'success'
				? CheckmarkCircle02Icon
				: Cancel01Icon
	);

	let statusColor = $derived(
		status === 'running'
			? 'text-blue-400'
			: status === 'success'
				? 'text-emerald-400'
				: status === 'cancelled'
					? 'text-muted-foreground'
					: 'text-red-400'
	);

	// ── Task-specific parsed fields ──────────────────────────────────

	let taskArgs = $derived.by(() => {
		if (!isTask || !block.toolArguments) return null;
		try {
			return JSON.parse(block.toolArguments) as {
				description?: string;
				subagent_type?: string;
				prompt?: string;
				model?: string;
				max_turns?: number;
			};
		} catch {
			return null;
		}
	});

	let subagentType = $derived(taskArgs?.subagent_type || 'Task');
	let taskDescription = $derived(taskArgs?.description || '');
	let taskPrompt = $derived(taskArgs?.prompt || '');
	let taskModel = $derived(
		taskArgs?.model ? taskArgs.model.charAt(0).toUpperCase() + taskArgs.model.slice(1) : ''
	);

	/** "Explore(Check SC windows)" style heading */
	let taskHeading = $derived(
		taskDescription ? `${subagentType}(${taskDescription})` : subagentType
	);

	// ── Bash-specific parsed fields ─────────────────────────────────

	let bashArgs = $derived.by(() => {
		if (!isBash || !block.toolArguments) return null;
		try {
			return JSON.parse(block.toolArguments) as {
				command?: string;
				description?: string;
				timeout?: number;
			};
		} catch {
			return null;
		}
	});

	let bashCommand = $derived(bashArgs?.command ?? '');
	let bashDescription = $derived(bashArgs?.description ?? '');
	let bashOutput = $derived(resultBlock?.toolResult ?? '');
	const BASH_PREVIEW_LINES = 4;
	let bashOutputView = $derived(createBoundedTextView(bashOutput, BASH_PREVIEW_LINES));
	// ── Read-specific parsed fields ─────────────────────────────────

	let readArgs = $derived.by(() => {
		if (!isReadLike || !block.toolArguments) return null;
		try {
			const parsed = JSON.parse(block.toolArguments);
			// Try common field names across different ACPs
			const filePath = parsed.file_path || parsed.path || parsed.file || parsed.filename || '';
			if (!filePath) return null;
			return {
				filePath: filePath as string,
				offset: (parsed.offset ?? parsed.start_line ?? parsed.line) as number | undefined,
				limit: (parsed.limit ?? parsed.end_line ?? parsed.lines) as number | undefined
			};
		} catch {
			return null;
		}
	});

	/** If we parsed Read args successfully, use custom UI; otherwise fall back to generic */
	let isRead = $derived(isReadLike && readArgs !== null);

	let readFilePath = $derived(readArgs?.filePath ?? '');
	let readFileName = $derived.by(() => {
		const p = readFilePath;
		if (!p) return '';
		const parts = p.replace(/\\/g, '/').split('/');
		return parts[parts.length - 1] || p;
	});
	let readDirPath = $derived.by(() => {
		const p = readFilePath;
		if (!p) return '';
		const normalized = p.replace(/\\/g, '/');
		const lastSlash = normalized.lastIndexOf('/');
		return lastSlash >= 0 ? normalized.substring(0, lastSlash) : '';
	});
	let readLineRange = $derived.by(() => {
		if (!readArgs) return '';
		const { offset, limit } = readArgs;
		if (offset && limit) return `Lines ${offset}–${offset + limit - 1}`;
		if (offset) return `From line ${offset}`;
		if (limit) return `${limit} lines`;
		return '';
	});

	/** Strip leading/trailing "..." truncation markers from Read results */
	let readOutput = $derived.by(() => {
		let raw = resultBlock?.toolResult ?? '';
		if (!raw) return '';
		// Strip leading "...\n" and trailing "\n..."
		raw = raw.replace(/^\.\.\.\n?/, '').replace(/\n?\.\.\.$/, '');
		return raw;
	});
	const READ_PREVIEW_LINES = 6;
	let readOutputView = $derived(createBoundedTextView(readOutput, READ_PREVIEW_LINES));

	let hasImages = $derived((resultBlock?.images && resultBlock.images.length > 0) ?? false);

	let hasChildren = $derived(childBlocks.length > 0);

	// ── Task result parsing ──────────────────────────────────────────
	// The raw result contains metadata like:
	//   "4\nagentId: abc123 (for resuming...)\n<usage>total_tokens: 40876\ntool_uses: 0\nduration_ms: 2216</usage>"
	// We extract the clean content, usage stats, and agentId separately.

	let taskResultParsed = $derived.by(() => {
		const raw = resultBlock?.toolResult ?? '';
		if (!raw || !isTask) return { content: raw, tokens: '', tools: '', duration: '', agentId: '' };

		let text = raw;

		// Extract <usage>...</usage> block
		let tokens = '';
		let tools = '';
		let duration = '';
		const usageMatch = text.match(/<usage>([\s\S]*?)<\/usage>/);
		if (usageMatch) {
			const usageBlock = usageMatch[1];
			const tokensMatch = usageBlock.match(/total_tokens:\s*(\d+)/);
			const toolsMatch = usageBlock.match(/tool_uses:\s*(\d+)/);
			const durationMatch = usageBlock.match(/duration_ms:\s*(\d+)/);
			if (tokensMatch) {
				const n = parseInt(tokensMatch[1]);
				tokens = n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
			}
			if (toolsMatch) tools = toolsMatch[1];
			if (durationMatch) {
				const ms = parseInt(durationMatch[1]);
				duration = ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
			}
			text = text.replace(/<usage>[\s\S]*?<\/usage>/, '');
		}

		// Extract agentId line
		let agentId = '';
		const agentMatch = text.match(/^agentId:\s*([a-f0-9-]+).*$/m);
		if (agentMatch) {
			agentId = agentMatch[1];
			text = text.replace(/^agentId:.*$/m, '');
		}

		// Clean up leftover whitespace
		const content = createBoundedTextView(text.trim(), 8).full;

		return { content, tokens, tools, duration, agentId };
	});

	function findChildResult(toolCallId: string | undefined): ContentBlock | undefined {
		if (!toolCallId) return undefined;
		return toolIndex.resultByCallId[toolCallId];
	}

	function getGrandchildren(childToolCallId: string | undefined): ContentBlock[] {
		if (!childToolCallId) return [];
		return (toolIndex.parentToChildren[childToolCallId] ?? [])
			.map((id) => toolIndex.toolCallById[id])
			.filter((child): child is ContentBlock => Boolean(child));
	}

	function formatArgs(args: string | undefined): string {
		if (!args) return '';
		const bounded = createBoundedTextView(args, 8, 64_000);
		if (bounded.truncated) return `${bounded.full}\n… ${bounded.omittedChars} characters omitted`;
		try {
			return JSON.stringify(JSON.parse(bounded.full), null, 2);
		} catch {
			return bounded.full;
		}
	}

	let genericResultView = $derived(createBoundedTextView(resultBlock?.toolResult ?? '', 8));
</script>

{#snippet locationLinks()}
	{#if block.locations?.length}
		<div class="border-border/20 flex flex-wrap gap-1.5 border-t px-3 py-2">
			{#each block.locations as location (`${location.path}:${location.line ?? 0}`)}
				<button
					class="border-border/50 bg-secondary/40 min-h-10 max-w-full truncate rounded-md border px-2 py-2 font-mono text-[11px] text-blue-400 transition-colors hover:bg-secondary hover:text-blue-300"
					onclick={() => openPath(location.path, location.line ?? 0)}
					title={location.path}
				>
					{location.path}{location.line ? `:${location.line}` : ''}
				</button>
			{/each}
		</div>
	{/if}
{/snippet}

{#if isTask}
	<!-- ════════════════════════════════════════════════════════════════
	     Task / Subagent block
	     ════════════════════════════════════════════════════════════════ -->
	<div class="bg-card/40 my-1.5 w-full rounded-lg border border-border">
		<!-- Header: status · heading · model badge · tool count · chevron -->
		<button
			class="hover:bg-accent/30 flex min-h-10 w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors"
			onclick={() => (expanded = !expanded)}
			aria-expanded={expanded}
		>
			<span class="flex h-4 w-4 shrink-0 items-center justify-center {statusColor}">
				<Icon
					icon={statusIcon}
					size={14}
					strokeWidth={1.5}
					class={status === 'running' ? 'animate-spin' : ''}
				/>
			</span>
			<span class="text-foreground/80 min-w-0 flex-1 truncate font-medium">
				{taskHeading}
			</span>
			{#if taskModel}
				<span
					class="bg-secondary/60 text-muted-foreground/60 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium"
				>
					{taskModel}
				</span>
			{/if}
			{#if hasChildren}
				<span class="text-muted-foreground/50 shrink-0 text-[11px] tabular-nums">
					{childBlocks.length} tool{childBlocks.length !== 1 ? 's' : ''}
				</span>
			{/if}
			<span class="text-muted-foreground/50 shrink-0">
				<Icon icon={expanded ? ArrowUp01Icon : ArrowDown01Icon} size={12} strokeWidth={1.5} />
			</span>
		</button>

		<!-- Usage stats bar (always visible when done) -->
		{#if status !== 'running' && (taskResultParsed.tokens || taskResultParsed.duration || taskResultParsed.tools)}
			<div class="border-border/15 flex items-center gap-2 border-t px-3 py-1">
				{#if taskResultParsed.tokens}
					<span class="text-muted-foreground/55 text-[10px]">{taskResultParsed.tokens} tokens</span>
				{/if}
				{#if taskResultParsed.tools && taskResultParsed.tools !== '0'}
					<span class="text-muted-foreground/45 text-[10px]">·</span>
					<span class="text-muted-foreground/55 text-[10px]"
						>{taskResultParsed.tools} tool uses</span
					>
				{/if}
				{#if taskResultParsed.duration}
					<span class="text-muted-foreground/45 text-[10px]">·</span>
					<span class="text-muted-foreground/55 text-[10px]">{taskResultParsed.duration}</span>
				{/if}
			</div>
		{/if}

		<!-- Expanded content -->
		{#if expanded}
			{@render locationLinks()}
			<!-- Prompt -->
			{#if taskPrompt}
				<div class="border-border/20 border-t px-3 py-2">
					<div
						class="text-muted-foreground/55 mb-1 text-[10px] font-medium uppercase tracking-wider"
					>
						Prompt
					</div>
					<div
						class="text-muted-foreground/70 whitespace-pre-wrap break-words text-[12px] leading-relaxed"
					>
						{taskPrompt}
					</div>
				</div>
			{/if}

			<!-- Clean result content -->
			{#if taskResultParsed.content}
				<div class="border-border/20 border-t px-3 py-2">
					<div
						class="text-muted-foreground/55 mb-1 text-[10px] font-medium uppercase tracking-wider"
					>
						Result
					</div>
					<pre
						class="bg-secondary/50 text-foreground/70 max-h-[300px] overflow-auto rounded p-2 font-mono text-[11px] leading-relaxed">{taskResultParsed.content}</pre>
				</div>
			{/if}

			<!-- Nested child tool calls -->
			{#if hasChildren}
				<div class="border-border/20 border-t py-1 pl-3 pr-1">
					{#each childBlocks as child (child.toolCallId)}
						<ToolCallBlock
							block={child}
							resultBlock={findChildResult(child.toolCallId)}
							childBlocks={getGrandchildren(child.toolCallId)}
							{toolIndex}
							depth={depth + 1}
						/>
					{/each}
				</div>
			{/if}
		{/if}
	</div>
{:else if isBash}
	<!-- ════════════════════════════════════════════════════════════════
	     Bash / Terminal block
	     ════════════════════════════════════════════════════════════════ -->
	<div class="bg-card/40 my-1 w-full overflow-hidden rounded-lg border border-border">
		<!-- Header -->
		<button
			class="hover:bg-accent/30 flex min-h-10 w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors"
			onclick={() => (expanded = !expanded)}
			aria-expanded={expanded}
		>
			<span class="flex h-4 w-4 shrink-0 items-center justify-center {statusColor}">
				{#if status === 'running'}
					<Icon icon={Loading03Icon} size={14} strokeWidth={1.5} class="animate-spin" />
				{:else}
					<Icon icon={CommandLineIcon} size={14} strokeWidth={1.5} />
				{/if}
			</span>

			<span class="flex min-w-0 flex-1 items-center gap-1.5 truncate">
				<span class="text-foreground/80 shrink-0 font-medium">Bash</span>
				{#if bashDescription}
					<span class="text-muted-foreground/50">&middot;</span>
					<span class="text-muted-foreground/60 truncate">{bashDescription}</span>
				{/if}
			</span>

			{#if status === 'error'}
				<span
					class="shrink-0 rounded bg-red-500/15 px-1.5 py-0.5 text-[10px] font-medium text-red-400/80"
				>
					failed
				</span>
			{/if}
			<span class="text-muted-foreground/50 shrink-0">
				<Icon icon={expanded ? ArrowUp01Icon : ArrowDown01Icon} size={12} strokeWidth={1.5} />
			</span>
		</button>

		<!-- Command line (always visible) -->
		<div class="border-border/50 border-t px-3 py-1.5">
			<pre
				class="text-foreground/50 max-w-full overflow-x-auto font-mono text-[11px] leading-relaxed"><span
					class="select-none text-emerald-500/50">$</span
				> {bashCommand}</pre>
		</div>
		{@render locationLinks()}

		<!-- Output preview / full output -->
		{#if bashOutput}
			<div class="border-border/50 border-t">
				{#if expanded}
					<pre
						class="max-h-[400px] overflow-auto px-3 py-2 font-mono text-[11px] leading-relaxed {status ===
						'error'
							? 'text-red-400/70'
							: 'text-muted-foreground/60'}">{bashOutputView.full}</pre>
					{#if bashOutputView.truncated}
						<div class="border-border/30 border-t px-3 py-1 text-[10px] text-amber-400/70">
							Output capped; {bashOutputView.omittedChars.toLocaleString()} characters omitted.
						</div>
					{/if}
				{:else}
					<!-- Preview: first few lines with fade -->
					<div class="relative">
						<pre
							class="px-3 py-2 font-mono text-[11px] leading-relaxed {status === 'error'
								? 'text-red-400/70'
								: 'text-muted-foreground/60'}">{bashOutputView.preview}</pre>
						{#if bashOutputView.hasMore}
							<div
								class="absolute inset-x-0 bottom-0 flex h-8 items-end justify-center"
								style="background: linear-gradient(to top, hsl(var(--card)) 30%, transparent);"
							>
								<span class="text-muted-foreground/55 pb-1 text-[10px]">
									{bashOutputView.truncated
										? 'Large output — open to view capped result'
										: `${bashOutputView.remainingLines} more line${bashOutputView.remainingLines !== 1 ? 's' : ''}`}
								</span>
							</div>
						{/if}
					</div>
				{/if}
			</div>
		{:else if status === 'running'}
			<div class="border-border/50 border-t px-3 py-2">
				<span class="text-muted-foreground/55 animate-pulse font-mono text-[11px]">Running...</span>
			</div>
		{/if}
	</div>
{:else if isRead}
	<!-- ════════════════════════════════════════════════════════════════
	     Read / File block
	     ════════════════════════════════════════════════════════════════ -->
	<div class="bg-card/40 my-1 w-full overflow-hidden rounded-lg border border-border">
		<!-- Header: file icon + filename -->
		<button
			class="hover:bg-accent/30 flex min-h-10 w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors"
			onclick={() => (expanded = !expanded)}
			aria-expanded={expanded}
		>
			<span class="flex h-4 w-4 shrink-0 items-center justify-center {statusColor}">
				{#if status === 'running'}
					<Icon icon={Loading03Icon} size={14} strokeWidth={1.5} class="animate-spin" />
				{:else}
					<Icon icon={File01Icon} size={14} strokeWidth={1.5} />
				{/if}
			</span>

			<span class="flex min-w-0 flex-1 items-center gap-1.5 truncate">
				<span class="text-foreground/80 shrink-0 font-medium">Read</span>
				<span class="text-muted-foreground/50">&middot;</span>
				<span class="text-muted-foreground/60 truncate">{readFileName}</span>
			</span>

			{#if readLineRange}
				<span class="text-muted-foreground/55 shrink-0 text-[10px]">
					{readLineRange}
				</span>
			{:else if status !== 'running' && readOutputView.lineCount > 0}
				<span class="text-muted-foreground/55 shrink-0 text-[10px] tabular-nums">
					{readOutputView.lineCount} line{readOutputView.lineCount !== 1 ? 's' : ''}
				</span>
			{/if}
			{#if status === 'error'}
				<span
					class="shrink-0 rounded bg-red-500/15 px-1.5 py-0.5 text-[10px] font-medium text-red-400/80"
				>
					failed
				</span>
			{/if}
			<span class="text-muted-foreground/50 shrink-0">
				<Icon icon={expanded ? ArrowUp01Icon : ArrowDown01Icon} size={12} strokeWidth={1.5} />
			</span>
		</button>

		<!-- Path (always visible, muted) -->
		<div class="border-border/50 border-t px-3 py-1">
			<span class="text-muted-foreground/50 block truncate font-mono text-[10px]"
				>{readDirPath}/</span
			>
		</div>
		{@render locationLinks()}

		<!-- Content preview / full content -->
		{#if readOutput}
			<div class="border-border/50 border-t">
				{#if expanded}
					<pre
						class="text-muted-foreground/60 max-h-[400px] overflow-auto px-2 py-1.5 font-mono text-[11px] leading-snug">{readOutputView.full}</pre>
					{#if readOutputView.truncated}
						<div class="border-border/30 border-t px-3 py-1 text-[10px] text-amber-400/70">
							Output capped; {readOutputView.omittedChars.toLocaleString()} characters omitted.
						</div>
					{/if}
				{:else}
					<div class="relative">
						<pre
							class="text-muted-foreground/60 px-2 py-1.5 font-mono text-[11px] leading-snug">{readOutputView.preview}</pre>
						{#if readOutputView.hasMore}
							<div
								class="absolute inset-x-0 bottom-0 flex h-8 items-end justify-center"
								style="background: linear-gradient(to top, hsl(var(--card)) 30%, transparent);"
							>
								<span class="text-muted-foreground/55 pb-1 text-[10px]">
									{readOutputView.truncated
										? 'Large file — open to view capped result'
										: `${readOutputView.remainingLines} more line${readOutputView.remainingLines !== 1 ? 's' : ''}`}
								</span>
							</div>
						{/if}
					</div>
				{/if}
			</div>
		{:else if status === 'running'}
			<div class="border-border/50 border-t px-3 py-2">
				<span class="text-muted-foreground/55 animate-pulse font-mono text-[11px]">Reading...</span>
			</div>
		{:else if status === 'error'}
			<div class="border-border/50 border-t px-3 py-1.5">
				<pre
					class="font-mono text-[11px] leading-relaxed text-red-400/70">{resultBlock?.toolResult ??
						'File not found'}</pre>
			</div>
		{/if}
	</div>
{:else if isScreenshot}
	<!-- ════════════════════════════════════════════════════════════════
	     Screenshot block
	     ════════════════════════════════════════════════════════════════ -->
	<ScreenshotBlock {block} {resultBlock} />
{:else if isAssetRead}
	<!-- ════════════════════════════════════════════════════════════════
	     Asset Read block (read_asset)
	     ════════════════════════════════════════════════════════════════ -->
	<AssetReadBlock {block} {resultBlock} />
{:else}
	<!-- ════════════════════════════════════════════════════════════════
	     Regular tool call block (non-Task)
	     ════════════════════════════════════════════════════════════════ -->
	<div class="bg-card/40 my-1 w-full rounded-lg border border-border">
		<button
			class="hover:bg-accent/30 flex min-h-10 w-full items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors"
			onclick={() => (expanded = !expanded)}
			aria-expanded={expanded}
		>
			<span class="flex h-4 w-4 shrink-0 items-center justify-center {statusColor}">
				<Icon
					icon={statusIcon}
					size={14}
					strokeWidth={1.5}
					class={status === 'running' ? 'animate-spin' : ''}
				/>
			</span>
			<span class="text-foreground/80 flex-1 truncate font-medium">{toolName}</span>
			<span class="text-muted-foreground/50">
				<Icon icon={expanded ? ArrowUp01Icon : ArrowDown01Icon} size={12} strokeWidth={1.5} />
			</span>
		</button>
		{@render locationLinks()}

		<!-- Inline image preview when collapsed -->
		{#if !expanded && hasImages && resultBlock?.images}
			<button
				class="border-border/50 hover:bg-accent/20 min-h-10 w-full border-t px-3 py-2 text-left text-[11px] text-muted-foreground transition-colors hover:text-foreground"
				onclick={() => (expanded = true)}
			>
				{resultBlock.images.length} image{resultBlock.images.length === 1 ? '' : 's'} — open to load
			</button>
		{/if}

		{#if expanded}
			<div class="border-border/50 border-t px-3 py-2 text-[12px]">
				{#if block.toolArguments}
					<div class="mb-2">
						<div
							class="text-muted-foreground/50 mb-1 text-[11px] font-medium uppercase tracking-wider"
						>
							Arguments
						</div>
						<pre
							class="bg-secondary/50 text-foreground/70 max-h-[200px] overflow-auto rounded p-2 font-mono text-[11px] leading-relaxed">{formatArgs(
								block.toolArguments
							)}</pre>
					</div>
				{/if}
				{#if hasImages && resultBlock?.images}
					<div class="mb-2">
						<div
							class="text-muted-foreground/50 mb-1 text-[11px] font-medium uppercase tracking-wider"
						>
							Images
						</div>
						<div class="flex flex-wrap gap-2">
							{#each resultBlock.images as img, imageIndex (`${img.mimeType}:${img.width}:${img.height}:${imageIndex}`)}
								<div class="border-border/50 overflow-hidden rounded-md border bg-black/20">
									<ToolResultImage
										base64={img.base64}
										mimeType={img.mimeType}
										width={img.width}
										height={img.height}
									/>
									{#if img.width > 0 && img.height > 0}
										<div class="text-muted-foreground/55 px-2 py-1 text-[10px]">
											{img.width}&times;{img.height}
										</div>
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{/if}
				{#if resultBlock?.toolResult}
					<div>
						<div
							class="text-muted-foreground/50 mb-1 text-[11px] font-medium uppercase tracking-wider"
						>
							Result
						</div>
						<pre
							class="bg-secondary/50 text-foreground/70 max-h-[300px] overflow-auto rounded p-2 font-mono text-[11px] leading-relaxed">{genericResultView.full}</pre>
						{#if genericResultView.truncated}
							<div class="mt-1 text-[10px] text-amber-400/70">
								Output capped; {genericResultView.omittedChars.toLocaleString()} characters omitted.
							</div>
						{/if}
					</div>
				{/if}
			</div>
		{/if}
	</div>
{/if}
