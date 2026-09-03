export function createLongTranscriptFixture() {
	const messages = Array.from({ length: 3_000 }, (_, index) => ({
		messageId: `message-${index}`,
		role: index % 2 === 0 ? 'user' : 'assistant',
		contentBlocks: [{ type: 'text', text: `Fixture message ${index}` }]
	}));

	const heavyBlocks = [{ type: 'tool_call', toolCallId: 'task-0', toolName: 'Task' }];
	for (let depth = 1; depth < 50; depth += 1) {
		heavyBlocks.push({
			type: 'tool_call',
			toolCallId: `task-${depth}`,
			toolName: 'Task',
			parentToolCallId: `task-${depth - 1}`
		});
	}
	for (let index = 0; index < 500; index += 1) {
		heavyBlocks.push({
			type: 'tool_call',
			toolCallId: `tool-${index}`,
			toolName: 'Read',
			parentToolCallId: 'task-49'
		});
		heavyBlocks.push({ type: 'tool_result', toolCallId: `tool-${index}`, toolResult: 'ok' });
	}

	const markdown = [
		'# Finalized response fixture',
		'```typescript',
		'const value = "long code fence";'.repeat(2_000),
		'```',
		'```mermaid',
		'graph TD; A-->B;',
		'```',
		'Inline math $E = mc^2$ and display math $$\\int_0^1 x^2 dx$$.',
		'![blocked tracker](https://tracker.invalid/pixel.png)'
	].join('\n');

	return {
		messages,
		heavyBlocks,
		multiMegabyteLine: 'x'.repeat(2 * 1024 * 1024),
		images: Array.from({ length: 128 }, (_, index) => ({
			id: `image-${index}`,
			mimeType: 'image/png',
			data: 'iVBORw0KGgo='
		})),
		markdown
	};
}
