import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const sourceRoot = new URL('../../NeoStackAI/', import.meta.url);
const webRoot = new URL('../', import.meta.url);

test('NeoStack Cloud uses the v6 gateway contract and stable model ids', async () => {
	const [provider, session] = await Promise.all([
		readFile(
			new URL('Private/Chat/Providers/NeoStackCloudProvider.cpp', sourceRoot),
			'utf8'
		),
		readFile(new URL('Private/Chat/ChatSession.cpp', sourceRoot), 'utf8')
	]);

	assert.match(provider, /GatewayUrl\(\) \+ TEXT\("\/api\/v1"\)/);
	assert.match(provider, /SetHeader\(TEXT\("x-neostack-org"\)/);
	for (const model of ['auto', 'deepseek-v4-pro', 'mimo-v2.5', 'minimax-m3', 'kimi-k3', 'grok-4.5']) {
		assert.ok(provider.includes(`TEXT("${model}")`), `missing stable model ${model}`);
	}
	assert.doesNotMatch(provider, /Add\(TEXT\("xai\/grok-4\.5"/);
	assert.match(session, /SupportsImagesForModel\(SelectedModelId\)/);
});

test('plugin account state uses gateway access and percentage-only weekly usage', async () => {
	const [auth, bridge, settings] = await Promise.all([
		readFile(new URL('Private/NeoStackAuthManager.cpp', sourceRoot), 'utf8'),
		readFile(new URL('src/lib/bridge.ts', webRoot), 'utf8'),
		readFile(new URL('src/lib/components/SettingsPanel.svelte', webRoot), 'utf8')
	]);

	assert.match(auth, /GatewayUrl\(\) \+ TEXT\("\/api\/access"\)/);
	assert.match(auth, /GatewayUrl\(\) \+ TEXT\("\/api\/usage"\)/);
	assert.match(auth, /SetObjectField\(TEXT\("usage"\), Usage\)/);
	assert.match(bridge, /remainingPercent: number/);
	assert.match(settings, /weekly AI usage/);
	assert.match(settings, /\{weeklyRemaining\}% remaining/);
	assert.doesNotMatch(bridge, /limitUsd|usedUsd/);
});

test('Studio uses authenticated durable media jobs without direct provider fallbacks', async () => {
	const [client, bridge, studio, settings] = await Promise.all([
		readFile(new URL('Private/MediaGenerationClient.cpp', sourceRoot), 'utf8'),
		readFile(new URL('src/lib/bridge.ts', webRoot), 'utf8'),
		readFile(new URL('src/lib/stores/studio.ts', webRoot), 'utf8'),
		readFile(new URL('Public/ACPSettings.h', sourceRoot), 'utf8')
	]);

	assert.match(client, /GatewayUrl\(\) \+ Path/);
	assert.match(client, /Authorization/);
	assert.match(client, /x-neostack-org/);
	assert.match(bridge, /submitmediajob/);
	assert.match(studio, /listMediaJobs/);
	assert.match(studio, /ACTIVE.*submitting.*queued.*running/);
	for (const legacy of [
		'MeshyApiKey',
		'TripoApiKey',
		'ElevenLabsApiKey',
		'FalApiKey',
		'OpenAIApiKey'
	]) {
		assert.ok(!settings.includes(legacy), `legacy setting remains: ${legacy}`);
	}
});
