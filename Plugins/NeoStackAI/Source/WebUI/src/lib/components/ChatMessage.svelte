<script lang="ts">
	import { tick } from 'svelte';
	import { Response } from '$lib/components/ai-elements/response/index.js';
	import {
		Reasoning,
		ReasoningTrigger,
		ReasoningContent
	} from '$lib/components/ai-elements/reasoning/index.js';
	import { Shimmer } from '$lib/components/ai-elements/shimmer/index.js';
	import Icon from '$lib/components/Icon.svelte';
	import ToolCallBlock from '$lib/components/ToolCallBlock.svelte';
	import StreamingTimer from '$lib/components/StreamingTimer.svelte';
	import { Alert02Icon, Copy01Icon, CheckmarkCircle02Icon } from '@hugeicons/core-free-icons';
	import type { ChatMessage, ContentBlock } from '$lib/bridge.js';
	import { openPath, copyToClipboard } from '$lib/bridge.js';
	import { buildMessageBlockIndex } from '$lib/messageBlockIndex.js';

	let { message }: { message: ChatMessage } = $props();

	// ── Block windowing ─────────────────────────────────────────────
	// A whole agent turn accumulates into ONE assistant message, so a
	// tool-heavy turn can reach hundreds of content blocks. ChatPane windows
	// by message count, which does nothing here — without a per-message block
	// cap the entire turn stays in the DOM and every streaming frame re-touches
	// all of it. Render only the trailing window (streaming appends at the
	// tail, so the live blocks are always visible); earlier activity loads on
	// demand. Keys use the absolute block index so existing blocks keep their
	// identity as the window slides or grows.
	const INITIAL_BLOCK_WINDOW = 60;
	const BLOCK_WINDOW_INCREMENT = 120;
	let blockWindow = $state(INITIAL_BLOCK_WINDOW);
	let rootEl: HTMLElement | null = $state(null);

	async function showEarlierBlocks() {
		// Anchor the viewport: expanding prepends content above the visible
		// blocks, which would otherwise shove the reading position down.
		const scrollParent = rootEl?.closest('.chat-scroll-area') ?? null;
		const prevHeight = scrollParent?.scrollHeight ?? 0;
		blockWindow += BLOCK_WINDOW_INCREMENT;
		await tick();
		if (scrollParent) {
			scrollParent.scrollTop += scrollParent.scrollHeight - prevHeight;
		}
	}

	// ── Path detection for clickable code spans ─────────────────────
	// Matches UE asset paths, filesystem paths, and file:line patterns.

	const PATH_PATTERNS = [
		// UE asset paths: /Game/..., /Engine/..., /Script/...
		/^\/(?:Game|Engine|Script|Temp)\//,
		// Absolute filesystem paths
		/^\/(?:Users|home|var|tmp|opt|usr|etc)\//,
		/^[A-Z]:\\/,
		// Common source/project relative paths
		/^(?:Source|Plugins|Content|Config|Docs|Tests|Scripts|Binaries|Intermediate|Saved)\//
	];

	const FILE_EXTENSIONS =
		/\.(?:h|cpp|c|cs|py|js|ts|svelte|json|ini|txt|md|uasset|umap|uplugin|uproject|build\.cs)$/i;

	/** Check if a codespan looks like a clickable path */
	function isClickablePath(text: string): boolean {
		const clean = parsePath(text).path;
		if (PATH_PATTERNS.some((p) => p.test(clean))) return true;
		if (FILE_EXTENSIONS.test(clean)) return true;
		return false;
	}

	/** Parse path and optional line number from "path:line" format */
	function parsePath(text: string): { path: string; line: number } {
		const match = text.match(/^(.+?)(?::(\d+))?$/);
		if (match) {
			return { path: match[1], line: match[2] ? parseInt(match[2]) : 0 };
		}
		return { path: text, line: 0 };
	}

	function handlePathClick(text: string) {
		const { path, line } = parsePath(text);
		openPath(path, line);
	}

	// ── Block index ─────────────────────────────────────────────────
	// Single-pass index built once per message update. Provides:
	//   - resultByCallId:    tool_call_id → tool_result block
	//   - toolCallById:      tool_call_id → tool_call block
	//   - childToParent:     child tool_call_id → parent tool_call_id
	//   - parentToChildren:  parent tool_call_id → [child tool_call_ids]
	//
	// Parent-child works for both new sessions (explicit parentToolCallId) and
	// old sessions (positional heuristic: tool_calls between a Task's tool_call
	// and its tool_result are inferred as children).

	let blockIndex = $derived(buildMessageBlockIndex(message.contentBlocks));

	let hiddenBlockCount = $derived(
		message.role === 'assistant' ? Math.max(0, blockIndex.topLevelRows.length - blockWindow) : 0
	);
	let visibleRows = $derived(
		hiddenBlockCount > 0 ? blockIndex.topLevelRows.slice(hiddenBlockCount) : blockIndex.topLevelRows
	);

	/** Find the matching tool_result block for a tool_call */
	function findToolResult(toolCallId: string | undefined): ContentBlock | undefined {
		if (!toolCallId) return undefined;
		return blockIndex.resultByCallId[toolCallId];
	}

	/** Get direct child tool_call blocks for a parent toolCallId */
	function getChildToolCalls(parentToolCallId: string | undefined): ContentBlock[] {
		if (!parentToolCallId) return [];
		const childIds = blockIndex.parentToChildren[parentToolCallId];
		if (!childIds?.length) return [];
		const out: ContentBlock[] = [];
		for (const id of childIds) {
			const b = blockIndex.toolCallById[id];
			if (b) out.push(b);
		}
		return out;
	}

	// ── Copy support ────────────────────────────────────────────────
	let copied = $state(false);

	// All roles: join every text block. User/system messages replayed from
	// history can carry multiple blocks — rendering only [0] drops content.
	let messageText = $derived(
		message.contentBlocks
			.filter((b) => b.type === 'text')
			.map((b) => b.text)
			.join('\n\n')
	);

	async function handleCopy() {
		if (!messageText) return;
		await copyToClipboard(messageText);
		copied = true;
		setTimeout(() => {
			copied = false;
		}, 1500);
	}
</script>

<!-- Custom codespan snippet: makes paths clickable -->
{#snippet codespan({
	children,
	token
}: {
	children: import('svelte').Snippet;
	token: { text: string };
})}
	{#if isClickablePath(token.text)}
		<button
			class="cursor-pointer rounded bg-muted px-1.5 py-0.5 font-mono text-[0.9em] text-blue-400 underline decoration-blue-400/30 transition-colors hover:text-blue-300 hover:decoration-blue-300/50"
			onclick={() => handlePathClick(token.text)}
		>
			{token.text}
		</button>
	{:else}
		{@render children()}
	{/if}
{/snippet}

{#if message.role === 'user'}
	<!-- User message — right-aligned bubble -->
	<div
		class="group/msg mb-4 flex items-start justify-end gap-1"
		data-message-id={message.messageId}
	>
		<button
			class="text-muted-foreground/40 mt-1 flex h-10 w-10 shrink-0 items-center justify-center rounded transition-colors hover:bg-accent hover:text-muted-foreground"
			onclick={handleCopy}
			title="Copy"
			aria-label="Copy message"
		>
			<Icon icon={copied ? CheckmarkCircle02Icon : Copy01Icon} size={14} strokeWidth={1.5} />
		</button>
		<div
			class="border-border/50 max-w-[70%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md border bg-card px-4 py-2.5 text-[14px] text-card-foreground"
		>
			{messageText}
		</div>
	</div>
{:else if message.role === 'system'}
	<!-- System message — centered divider -->
	<div class="my-4 flex items-center gap-3" data-message-id={message.messageId}>
		<div class="bg-border/40 h-px flex-1"></div>
		<span class="text-muted-foreground/60 whitespace-pre-wrap text-[12px] italic">
			{messageText}
		</span>
		<div class="bg-border/40 h-px flex-1"></div>
	</div>
{:else}
	<!-- Assistant message — left-aligned, renders content blocks -->
	<div
		class="group/msg mb-4 flex justify-start"
		bind:this={rootEl}
		data-message-id={message.messageId}
	>
		<div class="w-full min-w-0 max-w-[85%]">
			{#if hiddenBlockCount > 0}
				<div class="flex justify-center py-2">
					<button
						class="border-border/50 bg-secondary/40 text-muted-foreground/60 min-h-10 rounded-md border px-3 py-2 text-[11px] transition-colors hover:bg-secondary hover:text-muted-foreground"
						onclick={showEarlierBlocks}
					>
						Show {Math.min(BLOCK_WINDOW_INCREMENT, hiddenBlockCount)} earlier steps
					</button>
				</div>
			{/if}
			{#each visibleRows as row (row.block.toolCallId ?? `${row.block.type}:${row.sourceIndex}`)}
				{@const block = row.block}
				{#if block.type === 'text'}
					<!-- Text block — AI Elements Response (theme-aware Streamdown wrapper).
					     Same component instance across the streaming → complete flip: only
					     parseIncompleteMarkdown changes, so the finished block never
					     remounts/re-parses in one jump. Streamdown lexes per block and only
					     re-parses the trailing block while streaming. -->
					<div class="max-w-none text-[14px] leading-relaxed text-foreground">
						<Response
							content={block.text}
							parseIncompleteMarkdown={block.isStreaming ?? false}
							class="text-[14px] leading-relaxed"
							{codespan}
						/>
					</div>
				{:else if block.type === 'thought'}
					<!-- Thinking block — AI Elements Reasoning. defaultOpen only while the
					     block is live-streaming: history-loaded blocks mount closed instead
					     of playing a delayed collapse animation each session load. -->
					<Reasoning
						isStreaming={block.isStreaming ?? false}
						defaultOpen={block.isStreaming ?? false}
						class="my-2"
					>
						<ReasoningTrigger />
						<ReasoningContent>
							<Response
								content={block.text}
								parseIncompleteMarkdown={block.isStreaming ?? false}
								class="text-sm leading-relaxed"
								{codespan}
							/>
						</ReasoningContent>
					</Reasoning>
				{:else if block.type === 'tool_call'}
					<ToolCallBlock
						{block}
						resultBlock={findToolResult(block.toolCallId)}
						childBlocks={getChildToolCalls(block.toolCallId)}
						toolIndex={blockIndex}
					/>
				{:else if block.type === 'tool_result'}
					<!-- Tool results are rendered as part of their paired tool_call — skip standalone -->
				{:else if block.type === 'error'}
					<!-- Error block -->
					<div
						class="my-2 flex items-start gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-[13px] text-red-400"
					>
						<Icon icon={Alert02Icon} size={16} strokeWidth={1.5} class="mt-0.5 shrink-0" />
						<span>{block.text}</span>
					</div>
				{:else if block.type === 'system'}
					<!-- Inline system status (compaction, etc.). The animated variant is
					     gated on isStreaming too: a stale 'compacting' block loaded from
					     history must not run a perpetual pulse/shimmer. -->
					{#if block.systemStatus === 'compacting' && block.isStreaming}
						<div class="my-3 flex items-center gap-3">
							<div class="bg-border/30 h-px flex-1"></div>
							<div class="text-muted-foreground/60 flex items-center gap-2 text-[12px]">
								<span
									class="bg-muted-foreground/40 inline-block h-1.5 w-1.5 animate-pulse rounded-full"
								></span>
								<Shimmer><span>{block.text}</span></Shimmer>
							</div>
							<div class="bg-border/30 h-px flex-1"></div>
						</div>
					{:else}
						<div class="my-3 flex items-center gap-3">
							<div class="bg-border/30 h-px flex-1"></div>
							<span class="text-muted-foreground/50 text-[12px]">{block.text}</span>
							<div class="bg-border/30 h-px flex-1"></div>
						</div>
					{/if}
				{/if}
			{/each}
			<!-- Streaming indicator — AI Elements Shimmer -->
			{#if message.isStreaming}
				<div class="mt-2 flex items-center gap-2 text-[12px]">
					<Shimmer><span>Generating</span></Shimmer>
					<StreamingTimer />
				</div>
			{:else if message.contentBlocks.some((b) => b.type === 'text' && b.text)}
				<div class="mt-1 flex">
					<button
						class="text-muted-foreground/40 flex h-10 w-10 items-center justify-center rounded transition-colors hover:bg-accent hover:text-muted-foreground"
						onclick={handleCopy}
						title="Copy"
						aria-label="Copy message"
					>
						<Icon icon={copied ? CheckmarkCircle02Icon : Copy01Icon} size={14} strokeWidth={1.5} />
					</button>
				</div>
			{/if}
		</div>
	</div>
{/if}
