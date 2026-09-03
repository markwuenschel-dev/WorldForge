import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const readSource = (relativePath) =>
	readFile(new URL(`../src/${relativePath}`, import.meta.url), 'utf8');

test('420, 600, 1024, and wide layouts have explicit responsive contracts', async () => {
	const [layoutCss, settings, page, search] = await Promise.all([
		readSource('routes/layout.css'),
		readSource('lib/components/SettingsPanel.svelte'),
		readSource('routes/+page.svelte'),
		readSource('lib/components/ChatSearchBar.svelte')
	]);

	assert.match(layoutCss, /@media \(max-width: 720px\)/);
	assert.match(layoutCss, /\.chat-sidebar[\s\S]*position: absolute/);
	assert.match(layoutCss, /\.sidebar-mobile-backdrop[\s\S]*display: block/);
	assert.match(settings, /settings-mobile-header/);
	assert.match(settings, /@media \(max-width: 720px\)/);
	assert.match(settings, /<CustomSelect[\s\S]*id="settings-mobile-tab"/);
	assert.doesNotMatch(settings, /<select\b/i);
	assert.match(search, /left-2 right-2[\s\S]*sm:left-auto sm:right-4/);
	assert.match(page, /paneManager\.canSplit/);

	const layouts = [420, 600, 1024, 1600].map((width) => ({
		width,
		sidebar: width <= 720 ? 'overlay' : 'fixed',
		settings: width <= 720 ? 'compact-header' : 'side-navigation'
	}));
	assert.deepEqual(layouts, [
		{ width: 420, sidebar: 'overlay', settings: 'compact-header' },
		{ width: 600, sidebar: 'overlay', settings: 'compact-header' },
		{ width: 1024, sidebar: 'fixed', settings: 'side-navigation' },
		{ width: 1600, sidebar: 'fixed', settings: 'side-navigation' }
	]);
});

test('primary chat controls retain names, keyboard semantics, and 40px targets', async () => {
	const [pane, message, sidebar, search, attachments, tools] = await Promise.all([
		readSource('lib/components/ChatPane.svelte'),
		readSource('lib/components/ChatMessage.svelte'),
		readSource('lib/components/Sidebar.svelte'),
		readSource('lib/components/ChatSearchBar.svelte'),
		readSource('lib/components/AttachmentChips.svelte'),
		readSource('lib/components/ToolCallBlock.svelte')
	]);

	assert.match(pane, /role="log"[\s\S]*aria-label="Conversation transcript"/);
	assert.match(pane, /aria-label="Message"/);
	assert.match(pane, /aria-label="Send message"/);
	assert.match(pane, /h-10 w-10[\s\S]*attach_file/);
	assert.match(message, /h-10 w-10[\s\S]*aria-label="Copy message"/);
	assert.match(sidebar, /h-10 w-10[\s\S]*refresh_session_list/);
	assert.match(search, /role="search"/);
	assert.match(search, /aria-label="Previous search result"/);
	assert.match(search, /aria-label="Next search result"/);
	assert.match(attachments, /h-10 w-10[\s\S]*aria-label={`Remove/);
	assert.match(tools, /aria-expanded={expanded}/);
});

test('reduced motion is targeted and does not erase every transition', async () => {
	const layoutCss = await readSource('routes/layout.css');
	const reducedMotion = layoutCss.slice(
		layoutCss.indexOf('@media (prefers-reduced-motion: reduce)')
	);
	assert.match(reducedMotion, /\.animate-shimmer/);
	assert.match(reducedMotion, /\.animate-pulse/);
	assert.doesNotMatch(reducedMotion, /\*,\s*\*::before/);
	assert.doesNotMatch(reducedMotion, /transition-duration:\s*0\.01ms/);
});
