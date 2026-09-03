import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const sourceRoot = new URL('../../NeoStackAI/', import.meta.url);
const webRoot = new URL('../src/lib/', import.meta.url);

test('generic ACP settings are advertised and preserve boolean wire types', async () => {
	const [requests, client] = await Promise.all([
		readFile(new URL('Private/ACPRequests.cpp', sourceRoot), 'utf8'),
		readFile(new URL('Private/ACPClient.cpp', sourceRoot), 'utf8')
	]);

	assert.match(requests, /SetObjectField\(TEXT\("configOptions"\)/);
	assert.match(requests, /SetObjectField\(TEXT\("boolean"\)/);
	assert.match(requests, /SetField\(TEXT\("value"\), Value\)/);
	assert.match(requests, /SetStringField\(TEXT\("type"\), TEXT\("boolean"\)\)/);
	assert.match(client, /OnConfigOptionsAvailable\.Broadcast\(SessionConfigOptions\)/);
});

test('config option values parse as bare JSON scalars (UE rejects top-level scalars)', async () => {
	const service = await readFile(new URL('Private/AgentService.cpp', sourceRoot), 'utf8');

	// The web UI sends JSON.stringify(value) — a bare scalar like `true` or
	// `"opus"`. UE's TJsonReader errors on any top-level token that is not `{`
	// or `[`, so the service must wrap the payload in an array to parse it.
	// Parsing the raw scalar directly regresses to every setting change being
	// rejected as invalid_value.
	assert.match(service, /Create\(FString::Printf\(TEXT\("\[%s\]"\), \*ValueJson\)\)/);
	assert.doesNotMatch(service, /TJsonReaderFactory<>::Create\(ValueJson\)/);
});

test('the composer renders every generic select and boolean without native select', async () => {
	const [chatPane, menu, bridge] = await Promise.all([
		readFile(new URL('components/ChatPane.svelte', webRoot), 'utf8'),
		readFile(new URL('components/AgentConfigMenu.svelte', webRoot), 'utf8'),
		readFile(new URL('bridge.ts', webRoot), 'utf8')
	]);

	assert.match(chatPane, /<AgentConfigMenu/);
	assert.match(chatPane, /!hasGenericModelOption/);
	assert.match(chatPane, /!hasGenericReasoningOption/);
	assert.match(chatPane, /!hasGenericModeOption/);
	assert.match(menu, /option\.type === 'boolean'/);
	assert.match(menu, /selectGroups\(option\)/);
	assert.doesNotMatch(menu, /<select\b/i);
	assert.match(bridge, /setSessionConfigOption/);
});

test('the session mirror carries generic config and process identity to remote clients', async () => {
	const [deviceLink, mirrorHeader, upload, remote] = await Promise.all([
		readFile(new URL('Private/NeoStackDeviceLink.cpp', sourceRoot), 'utf8'),
		readFile(new URL('Public/NeoStackSessionMirror.h', sourceRoot), 'utf8'),
		readFile(new URL('Private/NeoStackSessionMirrorUpload.cpp', sourceRoot), 'utf8'),
		readFile(new URL('Private/NeoStackSessionMirrorRemote.cpp', sourceRoot), 'utf8')
	]);

	assert.match(deviceLink, /SetStringField\(TEXT\("connectionId"\)/);
	assert.match(deviceLink, /SetObjectField\(TEXT\("agentManifest"\)/);
	assert.match(deviceLink, /GetAvailableAgentNames\(\)/);
	assert.match(deviceLink, /ProductAgentIdFor\(Name\)/);
	assert.match(mirrorHeader, /LastPushedConfigOptions/);
	assert.match(upload, /SetArrayField\(TEXT\("configOptions"\)/);
	assert.match(remote, /SetStringField\(TEXT\("connectionId"\)/);
	assert.match(remote, /if \(!DispatchCommand/);
});
