import assert from 'node:assert/strict';
import test from 'node:test';

import { classifyLinkHref, DEFAULT_ALLOWED_RESPONSE_LINK_PREFIXES } from '../src/lib/linkPolicy.js';

test('site-relative hrefs open in the editor instead of navigating the panel', () => {
	// The reported bug: streamdown renders these as <a href="/Game/…"> with no
	// target, the click navigates the CEF view, the SPA fallback serves
	// index.html under a bogus path, and every asset 404s. Nothing here may
	// come back as anything but 'local'.
	assert.deepEqual(classifyLinkHref('/Game/Blueprints/BP_PartyMenu'), {
		kind: 'local',
		path: '/Game/Blueprints/BP_PartyMenu',
		line: 0
	});
	assert.deepEqual(classifyLinkHref('/Users/devesh/notes.md'), {
		kind: 'local',
		path: '/Users/devesh/notes.md',
		line: 0
	});
});

test('windows paths resolve to a filesystem path, drive colon intact', () => {
	assert.deepEqual(classifyLinkHref('A:\\Unreal Projects\\Saved\\Kit.zip'), {
		kind: 'local',
		path: 'A:\\Unreal Projects\\Saved\\Kit.zip',
		line: 0
	});
	assert.deepEqual(classifyLinkHref('C:/Users/loicp/Kit.zip'), {
		kind: 'local',
		path: 'C:/Users/loicp/Kit.zip',
		line: 0
	});
	// A bare drive is not a 'path:line' split.
	assert.deepEqual(classifyLinkHref('C:\\build'), {
		kind: 'local',
		path: 'C:\\build',
		line: 0
	});
});

test('file:// urls are decoded to the path UE can open', () => {
	assert.deepEqual(classifyLinkHref('file:///A:/Unreal%20Projects/Saved/Kit.zip'), {
		kind: 'local',
		path: 'A:/Unreal Projects/Saved/Kit.zip',
		line: 0
	});
	// POSIX keeps its leading slash; only a drive-letter path loses it.
	assert.deepEqual(classifyLinkHref('file:///Users/devesh/notes.md'), {
		kind: 'local',
		path: '/Users/devesh/notes.md',
		line: 0
	});
	// UNC stays UNC rather than collapsing to a relative name.
	assert.deepEqual(classifyLinkHref('file://buildbox/share/Kit.zip'), {
		kind: 'local',
		path: '//buildbox/share/Kit.zip',
		line: 0
	});
});

test('a trailing :line is split off, and only when it is really a line', () => {
	assert.deepEqual(classifyLinkHref('/Users/devesh/main.cpp:42'), {
		kind: 'local',
		path: '/Users/devesh/main.cpp',
		line: 42
	});
	assert.deepEqual(classifyLinkHref('C:/src/main.cpp:42'), {
		kind: 'local',
		path: 'C:/src/main.cpp',
		line: 42
	});
	assert.deepEqual(classifyLinkHref('/Game/Maps/Level_01'), {
		kind: 'local',
		path: '/Game/Maps/Level_01',
		line: 0
	});
});

test('project-relative paths agents actually write are recognised', () => {
	assert.deepEqual(classifyLinkHref('Source/NeoStackAI/Private/WebUIBridge.cpp:12'), {
		kind: 'local',
		path: 'Source/NeoStackAI/Private/WebUIBridge.cpp',
		line: 12
	});
	assert.deepEqual(classifyLinkHref('Saved/CustomerPackages'), {
		kind: 'local',
		path: 'Saved/CustomerPackages',
		line: 0
	});
});

test('web links go to the system browser', () => {
	assert.deepEqual(classifyLinkHref('https://discord.gg/Fcj68FJzAj'), {
		kind: 'external',
		url: 'https://discord.gg/Fcj68FJzAj'
	});
	assert.deepEqual(classifyLinkHref('mailto:support@betide.studio'), {
		kind: 'external',
		url: 'mailto:support@betide.studio'
	});
	assert.deepEqual(classifyLinkHref('neostack.dev/docs'), {
		kind: 'external',
		url: 'https://neostack.dev/docs'
	});
});

test('executable schemes are never forwarded to the editor or the browser', () => {
	for (const href of [
		'javascript:alert(1)',
		'JavaScript:alert(1)',
		'data:text/html,<script>alert(1)</script>',
		'vbscript:msgbox(1)'
	]) {
		assert.deepEqual(classifyLinkHref(href), { kind: 'none' }, href);
	}
});

test('in-page anchors are left to the browser, not swallowed', () => {
	// 'fragment' has to be distinct from 'none'. The layout cancels every click
	// it cannot route, so folding fragments into 'none' meant a heading link
	// scrolled nowhere — the one navigation that was always safe.
	for (const href of ['#setup', '#', '#a-b_c']) {
		assert.deepEqual(classifyLinkHref(href), { kind: 'fragment' }, href);
	}
});

test('unclassifiable hrefs resolve to none rather than navigating', () => {
	for (const href of ['', '   ', 'not a link', null, undefined, 42]) {
		assert.equal(classifyLinkHref(href).kind, 'none', String(href));
	}
});

test('the streamdown allowlist admits local paths that used to render [blocked]', () => {
	// Drive letters have to be enumerated: 'A:\…' parses as scheme 'a:' and the
	// allowlist matches on origin, so a wildcard never covers them.
	assert.ok(DEFAULT_ALLOWED_RESPONSE_LINK_PREFIXES.includes('*'));
	assert.ok(DEFAULT_ALLOWED_RESPONSE_LINK_PREFIXES.includes('file:///'));
	assert.ok(DEFAULT_ALLOWED_RESPONSE_LINK_PREFIXES.includes('A:'));
	assert.ok(DEFAULT_ALLOWED_RESPONSE_LINK_PREFIXES.includes('Z:'));
});
