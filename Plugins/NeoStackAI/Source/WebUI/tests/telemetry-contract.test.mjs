import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = (relativePath) =>
	readFileSync(new URL(`../../${relativePath}`, import.meta.url), 'utf8');

test('launch telemetry source targets the v6 gateway with durable insert ids', () => {
	const telemetry = source('NeoStackAI/Private/NeoTelemetry.cpp');
	assert.match(telemetry, /\/telemetry\/v1\/capture/);
	assert.match(telemetry, /TEXT\("\$insert_id"\)/);
	assert.match(telemetry, /InFlightBatch/);
	assert.match(telemetry, /Authorization/);
	assert.match(telemetry, /Capture\(TEXT\("plugin_first_opened"\)\)/);
	assert.match(telemetry, /Queue\[Count\]\.OrganizationId == BatchOrganizationId/);
	assert.match(telemetry, /SetHeader\(TEXT\("x-neostack-org"\), BatchOrganizationId\)/);
	assert.match(telemetry, /DiscardPendingIdentifiedEvents/);
	assert.doesNotMatch(telemetry, /EndpointUrl\.Empty\(\)/);
});

test('launch telemetry remains metadata-only even if reserved content config is set', () => {
	const settings = source('NeoStackAI/Public/ACPSettings.h');
	const telemetry = source('NeoStackAI/Private/NeoTelemetry.cpp');
	assert.match(settings, /AI Content Telemetry \(Unavailable\)/);
	assert.match(settings, /bEnableAIContentTelemetry = false/);
	assert.match(
		telemetry,
		/bool FNeoTelemetry::IsAIContentEnabled\(\) const\s*\{[\s\S]*?return false;\s*\}/
	);
	assert.doesNotMatch(telemetry, /SetStringField\(TEXT\("email"\)/);
	assert.doesNotMatch(telemetry, /SetStringField\(TEXT\("name"\)/);
});

test('onboarding and WebUI performance exports use fixed metadata-only shapes', () => {
	const bridge = source('WebUI/src/lib/bridge.ts');
	const nativeBridge = source('NeoStackAI/Private/WebUIBridge.cpp');
	assert.match(nativeBridge, /TEXT\("onboarding_completed"\)/);
	assert.match(nativeBridge, /TEXT\("onboarding_skipped"\)/);
	assert.match(nativeBridge, /TEXT\("agent_selected"\)/);
	assert.match(bridge, /const safeRecords = records\.flatMap/);
	assert.doesNotMatch(bridge, /captureperformancesnapshot\(JSON\.stringify\(records\)\)/);
});

test('automatic crash reporting requires NeoStack involvement and enabled telemetry', () => {
	const crashReporter = source('NeoStackAI/Private/NSAICrashReporter.cpp');
	assert.match(crashReporter, /if \(HasActiveCrashContext\(\)\)/);
	assert.doesNotMatch(crashReporter, /EngineData\.Contains\(TEXT\("NSAI\.Loaded"\)\)/);
	assert.match(
		crashReporter,
		/bEnableAnalytics && Settings->bEnableCrashReporting &&\s*Settings->bAlwaysSendCrashLogs/
	);
});
