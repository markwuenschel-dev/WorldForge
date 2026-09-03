/**
 * TypeScript wrapper for the UE ↔ JS bridge (window.ue.bridge).
 * All calls are async (UE returns Promises from bound UFUNCTIONs).
 *
 * Transport modes:
 * - 'embedded': Running inside UE's CEF browser, uses window.ue.bridge
 * - 'remote': Running on website, uses WebSocket relay to connected instance
 * - 'standalone': No backend available (dev mode), returns mock data
 */
import { createUUID } from '$lib/utils.js';
import { relayCall, onRelayEvent, getRelayState } from './relay.js';
import { createBridgeBindingRegistry } from './bridgeLifecycle.js';

export type Transport = 'embedded' | 'remote' | 'standalone';

let currentTransport: Transport = 'standalone';

export function getTransport(): Transport {
	return currentTransport;
}

export function setTransport(transport: Transport): void {
	currentTransport = transport;
}

/**
 * Detect and set the transport mode.
 * Called during app initialization.
 */
export function detectTransport(): Transport {
	if (getBridge()) {
		currentTransport = 'embedded';
	} else if (getRelayState() === 'connected') {
		currentTransport = 'remote';
	} else {
		currentTransport = 'standalone';
	}
	return currentTransport;
}

export type AgentStatus = 'available' | 'not_installed' | 'missing_key' | 'unknown';

export type AgentInfo = {
	id: string;
	name: string;
	status: AgentStatus;
	statusMessage: string;
	isBuiltIn: boolean;
	isConnected: boolean;
	registryId?: string;
	iconUrl?: string;
	description?: string;
};

export type SessionInfo = {
	sessionId: string;
	agentName: string;
	/** ACP registry agent id when configured (e.g. claude-acp); empty for bundled-only rows */
	registryId?: string;
	/** Server-computed: embedded terminal can generate a CLI resume line for this agent */
	terminalResumeSupported?: boolean;
	title: string;
	messageCount?: number;
	createdAt?: string;
	lastModifiedAt: string;
	isConnected: boolean;
	isActive?: boolean;
	/** True when the user has explicitly renamed this session — title survives remote sync */
	hasCustomTitle?: boolean;
};

export type ExportSessionResult = {
	success: boolean;
	canceled?: boolean;
	savedPath?: string;
	error?: string;
};

export type ToolResultImage = {
	base64: string;
	mimeType: string;
	width: number;
	height: number;
};

export type ContentBlock = {
	type: 'text' | 'thought' | 'tool_call' | 'tool_result' | 'image' | 'error' | 'system';
	text: string;
	isStreaming: boolean;
	toolCallId?: string;
	toolName?: string;
	toolArguments?: string;
	toolResult?: string;
	toolSuccess?: boolean;
	imageCount?: number;
	images?: ToolResultImage[];
	locations?: ToolCallLocation[];
	/** If this tool call was made inside a subagent (Task), the parent Task's toolCallId */
	parentToolCallId?: string;
	/** For system status blocks (e.g. "compacting", "compacted") */
	systemStatus?: string;
};

export type ToolCallLocation = {
	path: string;
	line?: number;
};

export type ChatMessage = {
	messageId: string;
	role: 'user' | 'assistant' | 'system';
	isStreaming: boolean;
	timestamp: string;
	contentBlocks: ContentBlock[];
};

export type ModelUsageEntry = {
	modelName: string;
	inputTokens: number;
	outputTokens: number;
	cacheReadTokens: number;
	cacheCreationTokens: number;
	costUSD: number;
	contextWindow: number;
	maxOutputTokens: number;
};

export type StreamingUpdate = {
	agentName: string;
	/** Correlates an asynchronous terminal error with the accepted prompt. */
	requestId?: string;
	type:
		| 'text_chunk'
		| 'thought_chunk'
		| 'tool_call'
		| 'tool_result'
		| 'error'
		| 'usage'
		| 'plan'
		| 'user_message_chunk'
		| 'history_replay_started'
		| 'history_replay_finished'
		| 'unknown';
	text: string;
	systemStatus?: string;
	toolCallId?: string;
	toolName?: string;
	toolArguments?: string;
	toolResult?: string;
	toolSuccess?: boolean;
	images?: ToolResultImage[];
	locations?: ToolCallLocation[];
	/** If this tool call was made inside a subagent (Task), the parent Task's toolCallId */
	parentToolCallId?: string;
	errorMessage?: string;
	errorCode?: number;
	// Usage fields (present when type === 'usage')
	inputTokens?: number;
	outputTokens?: number;
	totalTokens?: number;
	cacheReadTokens?: number;
	cacheCreationTokens?: number;
	reasoningTokens?: number;
	costAmount?: number;
	costCurrency?: string;
	turnCostUSD?: number;
	contextUsed?: number;
	contextSize?: number;
	numTurns?: number;
	durationMs?: number;
	modelUsage?: ModelUsageEntry[];
	replayMessageCount?: number;
	replayEmpty?: boolean;
	replayPreserveCached?: boolean;
};

// Check if we're running inside UE's embedded browser
function getBridge(): any | null {
	if (typeof window !== 'undefined' && (window as any).ue?.bridge) {
		return (window as any).ue.bridge;
	}
	return null;
}

const embeddedBridgeBindings = createBridgeBindingRegistry();

// CEF exposes a dynamically generated object whose method surface is defined
// by native UFUNCTIONs, so this one boundary intentionally remains dynamic.
function bindEmbeddedListener(name: string, bind: (bridge: any) => void): void {
	embeddedBridgeBindings.register(name, bind);
	const bridge = getBridge();
	embeddedBridgeBindings.refresh(bridge);
	if (!bridge) warnListenerSkipped(name);
}

/** Observe bridge loss/replacement for the lifetime of the mounted app. */
export function startBridgeLifecycleMonitor(signal?: AbortSignal): () => void {
	if (typeof window === 'undefined' || typeof document === 'undefined') return () => {};

	const refresh = () => embeddedBridgeBindings.refresh(getBridge());
	const interval = setInterval(refresh, 500);
	document.addEventListener('ue:ready', refresh);
	refresh();

	const stop = () => {
		clearInterval(interval);
		document.removeEventListener('ue:ready', refresh);
		signal?.removeEventListener('abort', stop);
	};
	signal?.addEventListener('abort', stop, { once: true });
	return stop;
}

export function onBridgeAvailabilityChanged(
	callback: (available: boolean, generation: number) => void
): () => void {
	return embeddedBridgeBindings.subscribe(callback);
}

const EMBEDDED_BRIDGE_QUERY_PARAM = 'neostackEmbedded';

/** Where we are in the wait for the UE bridge to bind. */
export type BridgeWaitState = 'waiting' | 'available' | 'timed_out';

let bridgeWaitState: BridgeWaitState = 'waiting';

/** Current state of the bridge wait: 'waiting' until the bridge appears,
 *  'available' once it has, 'timed_out' if it never did (standalone dev). */
export function getBridgeWaitState(): BridgeWaitState {
	if (getBridge()) bridgeWaitState = 'available';
	return bridgeWaitState;
}

/**
 * Whether this page was opened by the Unreal plugin and must wait for the
 * native bridge. Standalone development deliberately has no marker, so it can
 * initialize mock data immediately instead of guessing from a timeout.
 */
export function expectsEmbeddedBridge(): boolean {
	if (getBridge()) return true;
	if (typeof window === 'undefined') return false;
	return new URLSearchParams(window.location.search).get(EMBEDDED_BRIDGE_QUERY_PARAM) === '1';
}

/**
 * Wait for the UE bridge to become available.
 * The CEF browser starts loading the page before BindUObject() completes, so
 * window.ue.bridge may not exist when onMount fires. When binding finishes the
 * engine dispatches a `ue:ready` CustomEvent on `document`
 * (CEFWebBrowserWindow.cpp) — but on fast startups that can fire before this
 * listener attaches, so a slow poll runs as a belt-and-braces fallback.
 * Resolves true as soon as the bridge appears, no matter how late the editor
 * binds it. The default has no timeout because embedded pages are marked
 * explicitly; callers may still provide a timeout for diagnostics/tests.
 * Resolves false when an optional timeout expires or `signal` is aborted.
 */
export async function waitForBridge(maxWaitMs?: number, signal?: AbortSignal): Promise<boolean> {
	// Already available — no wait needed
	if (getBridge()) {
		bridgeWaitState = 'available';
		return true;
	}
	// Not in a browser environment (SSR)
	if (typeof window === 'undefined' || typeof document === 'undefined' || signal?.aborted) {
		return false;
	}

	bridgeWaitState = 'waiting';
	return new Promise<boolean>((resolve) => {
		let pollHandle: ReturnType<typeof setInterval> | null = null;
		let timeoutHandle: ReturnType<typeof setTimeout> | null = null;
		let settled = false;

		const finish = (found: boolean) => {
			if (settled) return;
			settled = true;
			document.removeEventListener('ue:ready', onUeReady);
			signal?.removeEventListener('abort', onAbort);
			if (pollHandle !== null) clearInterval(pollHandle);
			if (timeoutHandle !== null) clearTimeout(timeoutHandle);
			bridgeWaitState = found ? 'available' : 'timed_out';
			if (!found && maxWaitMs !== undefined) {
				console.warn('Bridge not available after', maxWaitMs, 'ms — running in standalone mode');
			}
			resolve(found);
		};

		// Engine fires this when BindUObject() completes (CEFWebBrowserWindow.cpp:1968)
		const onUeReady = () => {
			if (getBridge()) finish(true);
		};
		const onAbort = () => finish(false);
		document.addEventListener('ue:ready', onUeReady);
		signal?.addEventListener('abort', onAbort, { once: true });

		// Fallback: the event may already have fired before the listener attached
		// (fast startup), or may never fire (standalone dev) — poll slowly too.
		pollHandle = setInterval(() => {
			if (getBridge()) finish(true);
		}, 250);

		if (maxWaitMs !== undefined) {
			timeoutHandle = setTimeout(() => finish(false), maxWaitMs);
		}
	});
}

/** Log when an event-listener registration is dropped because the bridge is
 *  missing. A silent no-op here is how late-bridge bugs hide: the caller's
 *  bind guard latches while nothing was actually registered, and push events
 *  (streaming, permissions, session lists) never arrive. */
function warnListenerSkipped(name: string): void {
	console.warn(`[bridge] ${name}: window.ue.bridge not available — listener NOT registered`);
}

/** Safely parse a bridge result - UE wraps returns in { ReturnValue: "json string" } */
function parseResult<T>(value: unknown): T {
	// UE bridge wraps UFUNCTION returns in { ReturnValue: ... }
	const raw =
		value && typeof value === 'object' && 'ReturnValue' in (value as any)
			? (value as any).ReturnValue
			: value;
	if (typeof raw === 'string') {
		return JSON.parse(raw);
	}
	return raw as T;
}

export function isInUnreal(): boolean {
	return getBridge() !== null || currentTransport === 'remote';
}

/** Export bounded WebUI performance records to native telemetry. Native
 * aggregates allow-listed numeric fields and discards record details. */
export async function capturePerformanceSnapshot(records: unknown[]): Promise<void> {
	if (currentTransport === 'remote' || records.length === 0) return;
	const bridge = getBridge();
	if (!bridge) return;
	const safeRecords = records.flatMap((record) => {
		if (!record || typeof record !== 'object') return [];
		const value = record as Record<string, unknown>;
		return [
			{
				name: value.name,
				value: value.value,
				unit: value.unit,
				budget: value.budget,
				exceeded: value.exceeded
			}
		];
	});
	try {
		await bridge.captureperformancesnapshot(JSON.stringify(safeRecords));
	} catch {
		// Telemetry must never affect the embedded UI lifecycle.
	}
}

/** Get the last used agent name (persisted across editor sessions) */
export async function getLastUsedAgent(): Promise<string> {
	if (currentTransport === 'remote') return relayCall<string>('getLastUsedAgent');
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getlastusedagent();
		const raw =
			result && typeof result === 'object' && 'ReturnValue' in result ? result.ReturnValue : result;
		return (raw as string) || '';
	}
	return '';
}

// ── Onboarding ──────────────────────────────────────────────────────

/** Check if the onboarding wizard has been completed or skipped */
export async function getOnboardingCompleted(): Promise<boolean> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getonboardingcompleted();
		const raw =
			result && typeof result === 'object' && 'ReturnValue' in result ? result.ReturnValue : result;
		return !!raw;
	}
	return true; // In dev mode (no UE), skip wizard
}

/** Mark onboarding as completed. Persists across editor sessions. */
export async function setOnboardingCompleted(): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setonboardingcompleted();
	}
}

/** Record a persisted onboarding outcome using fixed, metadata-only fields. */
export async function captureOnboardingOutcome(
	outcome: 'completed' | 'skipped',
	agentSelected: boolean
): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		try {
			await bridge.captureonboardingoutcome(outcome, agentSelected);
		} catch {
			// Onboarding persistence already succeeded; telemetry is best-effort.
		}
	}
}

/** OS-level user language tag (e.g. "en-US", "fr-FR", "pt-BR"). Empty in standalone mode. */
export async function getDefaultLanguage(): Promise<string> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getdefaultlanguage();
		const raw =
			result && typeof result === 'object' && 'ReturnValue' in result
				? (result as any).ReturnValue
				: result;
		return (raw as string) || '';
	}
	return '';
}

export type SystemFontInfo = {
	family: string;
	isMonospace?: boolean;
};

export type SystemFontsResult = {
	fonts: SystemFontInfo[];
	platform?: 'mac' | 'windows' | 'linux' | 'unknown';
};

/** Installed OS fonts as seen by the embedded UE bridge. Empty in standalone mode. */
export async function listSystemFonts(): Promise<SystemFontsResult> {
	const bridge = getBridge();
	if (bridge?.listsystemfonts) {
		const result = await bridge.listsystemfonts();
		const parsed = parseResult<Partial<SystemFontsResult>>(result);
		return {
			fonts: Array.isArray(parsed?.fonts) ? parsed.fonts : [],
			platform: parsed?.platform
		};
	}
	return { fonts: [], platform: 'unknown' };
}

/** Whether the user has confirmed a UI language. Independent of onboarding. */
export async function getLanguageOnboardingCompleted(): Promise<boolean> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getlanguageonboardingcompleted();
		const raw =
			result && typeof result === 'object' && 'ReturnValue' in result
				? (result as any).ReturnValue
				: result;
		return !!raw;
	}
	return true; // Skip in dev mode
}

/** Mark the language step as done. Persists across editor sessions. */
export async function setLanguageOnboardingCompleted(): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setlanguageonboardingcompleted();
	}
}

// ── Entitlement ─────────────────────────────────────────────────────

export interface EntitlementStatus {
	entitled: boolean;
	status: 'lifetime' | 'subscription' | 'none' | 'network' | 'unknown';
	isBinaryBuild: boolean;
}

/** Snapshot of the latest entitlement check from the C++ side. Polled by
 *  the upgrade banner so it disappears once the StartupModule check lands. */
export async function getEntitlementStatus(): Promise<EntitlementStatus> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getentitlementstatus();
		return parseResult(result);
	}
	// Outside UE (browser dev), assume entitled so we don't block the dev loop.
	return { entitled: true, status: 'lifetime', isBinaryBuild: false };
}

// ── NeoStack Cloud account (auth state + entitlement payload) ─────────

export type CloudConnectionState = 'disconnected' | 'loading' | 'connected' | 'offline';

export type CloudAccountUser = {
	name: string | null;
	email: string | null;
	image: string | null;
};

export type CloudAccountOrganization = {
	id: string;
	name?: string | null;
	slug?: string | null;
	logo?: string | null;
};

export type CloudAccountCredits = {
	subscriptionBalanceUsd: number;
	permanentBalanceUsd: number;
	total: number;
};

export type CloudAccountQuota = {
	period: { percent: number };
	burst: { percent: number } | null;
};

export type CloudUsageSummary = {
	tier: 'free' | 'trial' | 'pro' | 'comp';
	period: 'weekly';
	usedPercent: number;
	remainingPercent: number;
	exhausted: boolean;
	resetsAt: string;
};

export type CloudAccountStatus = {
	signedIn: boolean;
	entitled: boolean;
	isBinaryBuild: boolean;
	checkPending: boolean;
	clientStatus: string;
	connectionState: CloudConnectionState;
	connected: boolean;
	// ideEntitlement payload (present once the signed-in plan check has run).
	reason?: string | null;
	plan?: string | null;
	planName?: string | null;
	features?: string[];
	featureFlags?: string[];
	user?: CloudAccountUser;
	organization?: CloudAccountOrganization;
	// Legacy credit/quota payloads remain optional for compatibility.
	credits?: CloudAccountCredits;
	quota?: CloudAccountQuota | null;
	usage?: CloudUsageSummary;
};

export async function getNeoStackAccountStatus(): Promise<CloudAccountStatus> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getneostackaccountstatus();
		return parseResult<CloudAccountStatus>(result);
	}
	return {
		signedIn: false,
		entitled: true,
		isBinaryBuild: false,
		checkPending: false,
		clientStatus: 'lifetime',
		connectionState: 'disconnected',
		connected: false
	};
}

export function bindNeoStackAccountChanged(callback: (status: CloudAccountStatus) => void): void {
	bindEmbeddedListener('bindNeoStackAccountChanged', (bridge) => {
		bridge.bindonneostackaccountchanged((statusJson: string) => {
			try {
				callback(JSON.parse(statusJson) as CloudAccountStatus);
			} catch {
				console.warn('NeoStack account status payload was malformed');
			}
		});
	});
}

// ── Provider Settings ───────────────────────────────────────────────

export type CustomProviderModel = {
	id: string;
	name: string;
	description: string;
};

export type ProviderConfig = {
	id: string;
	name: string;
	description: string;
	requiresApiKey: boolean;
	hasApiKey: boolean;
	apiKeyMasked: string;
	baseUrl: string;
	defaultBaseUrl: string;
	defaultModel: string;
	supportsModelDiscovery: boolean;
	configured: boolean;
	inPriorityList: boolean;
	isUserDefined: boolean;
	enableModelDiscovery: boolean;
	models?: CustomProviderModel[];
};

export type ProviderSettings = {
	priority: string[];
	providers: ProviderConfig[];
};

export type IntegrationRuntimeState =
	| 'disabled'
	| 'registered'
	| 'active'
	| 'unavailable'
	| 'incompatible'
	| 'failed'
	| 'unknown';

export type IntegrationDependency = {
	name: string;
	optional: boolean;
	enabled: boolean;
	installed: boolean;
};

export type IntegrationInfo = {
	legacyPluginName: string;
	integrationId: string;
	displayName: string;
	description: string;
	version: string;
	vendor: string;
	category: string;
	statusMessage: string;
	baseDir: string;
	runtimeState: IntegrationRuntimeState;
	enabledInProject: boolean;
	hasExplicitProjectEntry: boolean;
	loadedInSession: boolean;
	mountedInSession: boolean;
	activeInSession: boolean;
	restartRequired: boolean;
	canToggle: boolean;
	isProjectPlugin: boolean;
	isInstalledOnEngine: boolean;
	explicitlyLoaded: boolean;
	enabledByDefault: boolean;
	isBetaVersion: boolean;
	isExperimentalVersion: boolean;
	isBuiltIn: boolean;
	isThirdParty: boolean;
	hasRuntimeDescriptor: boolean;
	hasUIMetadata: boolean;
	domain: string;
	domainLabel: string;
	sortOrder: number;
	agentSummary: string;
	enablesAgentTo: string[];
	whenToEnable: string;
	isRecommended: boolean;
	dependencies: IntegrationDependency[];
};

export type IntegrationSettingsState = {
	coreApiVersion: number;
	projectFile: string;
	restartRequired: boolean;
	integrations: IntegrationInfo[];
};

export type IntegrationOverrideResult = {
	success: boolean;
	integrationId: string;
	disabled: boolean;
	restartRequired: boolean;
	error?: string;
};

export async function getProviderSettings(): Promise<ProviderSettings> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getprovidersettings();
		return parseResult(result);
	}
	return { priority: [], providers: [] };
}

export async function setProviderPriority(priority: string[]): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setproviderpriority(JSON.stringify(priority));
	}
}

export async function addProvider(providerId: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.addprovider(providerId);
	}
}

export async function removeProvider(providerId: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.removeprovider(providerId);
	}
}

export async function setProviderApiKey(providerId: string, apiKey: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setproviderapikey(providerId, apiKey);
	}
}

export async function setProviderBaseUrl(providerId: string, baseUrl: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setproviderbaseurl(providerId, baseUrl);
	}
}

export async function refreshProviderModels(): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.refreshprovidermodels();
	}
}

// ── Custom Providers ────────────────────────────────────────────────

export async function createCustomProvider(
	displayName: string,
	baseUrl: string
): Promise<{ providerId: string }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.createcustomprovider(displayName, baseUrl);
		return parseResult(result);
	}
	return { providerId: '' };
}

export async function deleteCustomProvider(providerId: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.deletecustomprovider(providerId);
	}
}

export async function updateCustomProvider(
	providerId: string,
	displayName: string,
	baseUrl: string
): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.updatecustomprovider(providerId, displayName, baseUrl);
	}
}

export async function addCustomProviderModel(
	providerId: string,
	modelId: string,
	displayName: string,
	description: string
): Promise<{ success: boolean }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.addcustomprovidermodel(
			providerId,
			modelId,
			displayName,
			description
		);
		return parseResult(result);
	}
	return { success: false };
}

export async function removeCustomProviderModel(
	providerId: string,
	modelId: string
): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.removecustomprovidermodel(providerId, modelId);
	}
}

export async function importCustomProviderModels(
	providerId: string,
	modelsJson: string
): Promise<{ imported: number; errors: string[] }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.importcustomprovidermodels(providerId, modelsJson);
		return parseResult(result);
	}
	return { imported: 0, errors: ['Bridge not available'] };
}

export async function setCustomProviderModelDiscovery(
	providerId: string,
	enabled: boolean
): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setcustomprovidermodeldiscovery(providerId, enabled);
	}
}

export async function setCustomProviderRequiresApiKey(
	providerId: string,
	requiresApiKey: boolean
): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setcustomproviderrequiresapikey(providerId, requiresApiKey);
	}
}

export type EnabledModelsState = {
	enabledModels: string[];
	hasCustomSelection: boolean;
};

export async function getEnabledModels(): Promise<EnabledModelsState> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getenabledmodels();
		return parseResult(result);
	}
	return { enabledModels: [], hasCustomSelection: false };
}

export async function setModelEnabled(modelId: string, enabled: boolean): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setmodelenabled(modelId, enabled);
	}
}

export async function setEnabledModels(modelIds: string[]): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setenabledmodels(JSON.stringify(modelIds));
	}
}

// ── Folded Integrations ─────────────────────────────────────────────

export async function getIntegrationSettings(): Promise<IntegrationSettingsState> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getintegrationsettings();
		return parseResult(result);
	}
	return { coreApiVersion: 0, projectFile: '', restartRequired: false, integrations: [] };
}

export async function setIntegrationOverride(
	integrationId: string,
	disabled: boolean
): Promise<IntegrationOverrideResult> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.setintegrationoverride(integrationId, disabled);
		return parseResult(result);
	}
	return {
		success: false,
		integrationId,
		disabled,
		restartRequired: false,
		error: 'Bridge not available'
	};
}

export type IntegrationPluginsToggleResult = {
	success: boolean;
	count: number;
	restartRequired: boolean;
	error?: string;
};

// Flip every backing plugin declared by an integration in one .uproject save.
export async function setIntegrationPluginsEnabled(
	integrationId: string,
	enabled: boolean
): Promise<IntegrationPluginsToggleResult> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.setintegrationpluginsenabled(integrationId, enabled);
		return parseResult(result);
	}
	return {
		success: false,
		count: 0,
		restartRequired: false,
		error: 'Bridge not available'
	};
}

// ── Agent Skills ────────────────────────────────────────────────

export type SkillStatus = {
	name: string;
	description: string;
	sourceId: string;
	sourceDisplayName: string;
	sourceVersion: string;
	tags: string[];
	installedPaths: string[];
	userEdited: boolean;
	conflictPending: boolean;
	conflictNewPath: string;
};

export type ProjectSkillStatus = {
	name: string;
	folderName: string;
	description: string;
	tags: string[];
	paths: string[];
	parseError: string;
};

export type SkillsState = {
	projectDir: string;
	manifestPath: string;
	skills: SkillStatus[];
	projectSkills: ProjectSkillStatus[];
};

export type SkillBody = {
	success: boolean;
	name: string;
	body?: string;
	error?: string;
};

export type SkillSyncReport = {
	installed: number;
	updated: number;
	noOp: number;
	userEditsKept: number;
	conflicts: number;
	orphansRemoved: number;
	orphansKept: number;
	errors: string[];
};

export type SkillConflictMode = 'keep-user' | 'take-new';

const EMPTY_SKILLS: SkillsState = {
	projectDir: '',
	manifestPath: '',
	skills: [],
	projectSkills: []
};

export async function getSkills(): Promise<SkillsState> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getskills();
		const parsed = parseResult(result) as SkillsState;
		if (!parsed.projectSkills) {
			parsed.projectSkills = [];
		}
		return parsed;
	}
	return EMPTY_SKILLS;
}

export async function getSkillBody(name: string): Promise<SkillBody> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getskillbody(name);
		return parseResult(result);
	}
	return { success: false, name, error: 'Bridge not available' };
}

export async function getSkillConflictBody(name: string): Promise<SkillBody> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getskillconflictbody(name);
		return parseResult(result);
	}
	return { success: false, name, error: 'Bridge not available' };
}

export async function resolveSkillConflict(
	name: string,
	mode: SkillConflictMode
): Promise<{ success: boolean; error?: string }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.resolveskillconflict(name, mode);
		return parseResult(result);
	}
	return { success: false, error: 'Bridge not available' };
}

export async function rescanSkills(): Promise<SkillSyncReport> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.rescanskills();
		return parseResult(result);
	}
	return {
		installed: 0,
		updated: 0,
		noOp: 0,
		userEditsKept: 0,
		conflicts: 0,
		orphansRemoved: 0,
		orphansKept: 0,
		errors: []
	};
}

export async function openSkillFile(name: string, upstream: boolean): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.openskillfile(name, upstream);
	}
}

// ── Notification Settings ──────────────────────────────────────

export type NotificationSettings = {
	onlyWhenUnfocused: boolean;
	notifyOnComplete: boolean;
	flashTaskbar: boolean;
	playSound: boolean;
	soundVolume: number;
	completionSound: string;
	errorSound: string;
	playPermissionSound: boolean;
	permissionSoundVolume: number;
	permissionRequestSound: string;
};

const defaultNotificationSettings: NotificationSettings = {
	onlyWhenUnfocused: false,
	notifyOnComplete: true,
	flashTaskbar: true,
	playSound: true,
	soundVolume: 1.0,
	completionSound: '',
	errorSound: '',
	playPermissionSound: false,
	permissionSoundVolume: 1.0,
	permissionRequestSound: ''
};

export async function getNotificationSettings(): Promise<NotificationSettings> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getnotificationsettings();
		const parsed = parseResult<Partial<NotificationSettings>>(result);
		return { ...defaultNotificationSettings, ...parsed };
	}
	return { ...defaultNotificationSettings };
}

export async function setNotificationSetting(key: string, value: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setnotificationsetting(key, value);
	}
}

export type SoundAsset = {
	/** FSoftObjectPath string, e.g. "/Game/Sounds/MySound.MySound" */
	path: string;
	/** Bare asset name, e.g. "MySound" */
	name: string;
	/** Package path (folder), e.g. "/Game/Sounds" */
	folder: string;
	/** Class name, e.g. "SoundWave" or "SoundCue" */
	className: string;
};

export async function listSoundAssets(query: string = ''): Promise<SoundAsset[]> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.listsoundassets(query);
		const parsed = parseResult<{ sounds?: SoundAsset[] }>(result);
		return parsed?.sounds ?? [];
	}
	return [];
}

export async function previewNotificationSound(
	soundPath: string,
	volume: number = 1.0
): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.previewnotificationsound(soundPath, volume);
	}
}

export async function soundAssetExists(soundPath: string): Promise<boolean> {
	if (!soundPath) return false;
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.soundassetexists(soundPath);
		const raw =
			result && typeof result === 'object' && 'ReturnValue' in result ? result.ReturnValue : result;
		return !!raw;
	}
	return true; // dev mode (no UE) — assume valid so picker doesn't show false-positive "missing"
}

// ── Agent Execution Settings ────────────────────────────────────────

export type AgentExecutionSettings = {
	systemPromptAppend: string;
	toolTimeout: number;
	agentResponseTimeout: number;
};

export async function getAgentExecutionSettings(): Promise<AgentExecutionSettings> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getagentexecutionsettings();
		const parsed = parseResult<AgentExecutionSettings>(result);
		return {
			systemPromptAppend: parsed?.systemPromptAppend ?? '',
			toolTimeout: parsed?.toolTimeout ?? 60,
			agentResponseTimeout: parsed?.agentResponseTimeout ?? 0
		};
	}
	return { systemPromptAppend: '', toolTimeout: 60, agentResponseTimeout: 0 };
}

export async function setAgentExecutionSetting(
	key: 'systemPromptAppend' | 'toolTimeout' | 'agentResponseTimeout',
	value: string
): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setagentexecutionsetting(key, value);
	}
}

// ── Issue Report Settings ───────────────────────────────────────────

export type IssueReportSettings = {
	disabled: boolean;
};

export async function getIssueReportSettings(): Promise<IssueReportSettings> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getissuereportsettings();
		const parsed = parseResult<IssueReportSettings>(result);
		return parsed ?? { disabled: false };
	}
	return { disabled: false };
}

export async function setIssueReportDisabled(disabled: boolean): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setissuereportdisabled(disabled);
	}
}

// ── Agent Discovery ─────────────────────────────────────────────────

/** Get list of available agents from the backend */
export async function getAgents(): Promise<AgentInfo[]> {
	if (currentTransport === 'remote') return relayCall<AgentInfo[]>('getAgents');
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getagents();
		return parseResult<AgentInfo[]>(result);
	}
	return [];
}

/** Create a new chat session */
export async function createSession(
	agentName: string
): Promise<{ sessionId: string; agentName: string }> {
	if (currentTransport === 'remote') return relayCall('createSession', agentName);
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.createsession(agentName);
		return parseResult(result);
	}
	return { sessionId: createUUID(), agentName };
}

/** Get all sessions (saved + active) */
export async function getSessions(): Promise<SessionInfo[]> {
	if (currentTransport === 'remote') return relayCall<SessionInfo[]>('getSessions');
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getsessions();
		return parseResult(result);
	}
	return [];
}

/** Resume a saved session — loads from disk, connects agent, resumes external session */
export async function resumeSession(
	sessionId: string
): Promise<{ success: boolean; agentName?: string; error?: string }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.resumesession(sessionId);
		return parseResult(result);
	}
	return { success: false, error: 'Not in UE' };
}

export type SessionTerminalResumeResult = {
	supported: boolean;
	command?: string;
	agentName?: string;
	registryId?: string;
	error?: string;
};

/** Shell command to resume this chat in the embedded terminal (Claude Code, Gemini, Copilot, Codex). */
export async function getSessionTerminalResumeCommand(
	sessionId: string
): Promise<SessionTerminalResumeResult> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getsessionterminalresumecommand(sessionId);
		return parseResult(result);
	}
	return { supported: false, error: 'Not in UE' };
}

/** Get messages for a session */
export async function getSessionMessages(sessionId: string): Promise<ChatMessage[]> {
	if (currentTransport === 'remote')
		return relayCall<ChatMessage[]>('getSessionMessages', sessionId);
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getsessionmessages(sessionId);
		return parseResult(result);
	}
	return [];
}

/** Rename a session (sets custom title that survives remote sync) */
export async function renameSession(
	sessionId: string,
	newTitle: string
): Promise<{ success: boolean }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.renamesession(sessionId, newTitle);
		return parseResult(result);
	}
	return { success: false };
}

/** Delete a session */
export async function deleteSession(sessionId: string): Promise<{ success: boolean }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.deletesession(sessionId);
		return parseResult(result);
	}
	return { success: false };
}

/** Export a loaded session to a Markdown file via native save dialog */
export async function exportSessionToMarkdown(sessionId: string): Promise<ExportSessionResult> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.exportsessiontomarkdown(sessionId);
		return parseResult(result);
	}
	return { success: false, error: 'Not in UE' };
}

export type PromptActionResult = {
	accepted: boolean;
	requestId: string;
	errorCode?: string;
	message?: string;
};

function parsePromptActionResult(value: unknown, expectedRequestId: string): PromptActionResult {
	const raw =
		value && typeof value === 'object' && 'ReturnValue' in value
			? (value as { ReturnValue: unknown }).ReturnValue
			: value;

	// Compatibility for one rolling upgrade window. New native builds always
	// return the object contract, but an already-open older editor may say "ok".
	if (raw === 'ok' || raw === '"ok"') {
		return { accepted: true, requestId: expectedRequestId };
	}

	let parsed = raw;
	if (typeof raw === 'string') {
		try {
			parsed = JSON.parse(raw);
		} catch {
			return {
				accepted: false,
				requestId: expectedRequestId,
				errorCode: 'invalid_response',
				message: 'The editor returned an invalid prompt response.'
			};
		}
	}

	if (
		parsed &&
		typeof parsed === 'object' &&
		typeof (parsed as Record<string, unknown>).accepted === 'boolean'
	) {
		const result = parsed as Partial<PromptActionResult>;
		return {
			accepted: result.accepted === true,
			requestId: result.requestId || expectedRequestId,
			errorCode: result.errorCode,
			message: result.message
		};
	}

	return {
		accepted: false,
		requestId: expectedRequestId,
		errorCode: 'missing_response',
		message: 'The editor did not acknowledge the prompt request.'
	};
}

/** Send a prompt to a session and wait for native acceptance. */
export async function sendPrompt(
	sessionId: string,
	text: string,
	requestId = createUUID()
): Promise<PromptActionResult> {
	if (currentTransport === 'remote') {
		const result = await relayCall('sendPrompt', sessionId, text, requestId);
		return parsePromptActionResult(result, requestId);
	}
	const bridge = getBridge();
	if (!bridge) {
		throw new Error('UE bridge unavailable');
	}
	const result = await bridge.sendprompt(sessionId, text, requestId);
	return parsePromptActionResult(result, requestId);
}

/** Cancel current prompt and wait for native acceptance. */
export async function cancelPrompt(
	sessionId: string,
	requestId = createUUID()
): Promise<PromptActionResult> {
	if (currentTransport === 'remote') {
		const result = await relayCall('cancelPrompt', sessionId, requestId);
		return parsePromptActionResult(result, requestId);
	}
	const bridge = getBridge();
	if (!bridge) {
		throw new Error('UE bridge unavailable');
	}
	const result = await bridge.cancelprompt(sessionId, requestId);
	return parsePromptActionResult(result, requestId);
}

// ── Agent Setup ─────────────────────────────────────────────────────

export type AgentInstallInfo = {
	agentName: string;
	baseExecutableName: string;
	installCommand: string;
	installUrl: string;
	requiresAdapter: boolean;
	requiresBaseCLI: boolean;
};

/** Get install info for an agent (install command, download URL, requirements) */
export async function getAgentInstallInfo(agentName: string): Promise<AgentInstallInfo> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getagentinstallinfo(agentName);
		return parseResult(result);
	}
	return {
		agentName,
		baseExecutableName: '',
		installCommand: '',
		installUrl: '',
		requiresAdapter: false,
		requiresBaseCLI: false
	};
}

/** Start async agent installation. Listen for progress via onInstallProgress/onInstallComplete. */
export async function installAgent(agentName: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.installagent(agentName);
	}
}

/** Register callback for install progress updates */
export function onInstallProgress(callback: (agentName: string, message: string) => void): void {
	bindEmbeddedListener('onInstallProgress', (bridge) => {
		bridge.bindoninstallprogress(callback);
	});
}

/** Register callback for install completion */
export function onInstallComplete(
	callback: (agentName: string, success: boolean, errorMessage: string) => void
): void {
	bindEmbeddedListener('onInstallComplete', (bridge) => {
		bridge.bindoninstallcomplete(callback);
	});
}

/** Refresh an agent's status (invalidates cache, re-checks). Returns updated status. */
export async function refreshAgentStatus(
	agentName: string
): Promise<{ status: AgentStatus; statusMessage: string }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.refreshagentstatus(agentName);
		return parseResult(result);
	}
	return { status: 'unknown', statusMessage: '' };
}

// ── ACP Registry ────────────────────────────────────────────────────

export type RegistryAgent = {
	id: string;
	name: string;
	version: string;
	description: string;
	license: string;
	icon: string; // SVG markup (pre-fetched by C++ backend, supports currentColor)
	repository: string;
	authors: string[];
	hasBinary: boolean;
	hasNpx: boolean;
	hasUvx: boolean;
	npxPackage?: string;
	uvxPackage?: string;
	// Install status
	isInstalled: boolean;
	installedVersion?: string;
	latestVersion?: string;
	updateAvailable?: boolean;
	installMethod: string; // "binary" | "npx" | "uvx" | ""
};

/** Get all agents from the ACP registry (cached, platform-filtered) */
export async function getRegistryAgents(): Promise<RegistryAgent[]> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getregistryagents();
		return parseResult<RegistryAgent[]>(result);
	}
	return [];
}

/** Force refresh the ACP registry from the CDN */
export async function refreshRegistry(): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.refreshregistry();
	}
}

/** Install a registry agent. Method: "binary" | "npx" | "uvx" | "auto" */
export async function installRegistryAgent(
	agentId: string,
	method: string = 'auto'
): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.installregistryagent(agentId, method);
	}
}

/** Uninstall a registry agent (removes downloaded binaries) */
export async function uninstallRegistryAgent(agentId: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.uninstallregistryagent(agentId);
	}
}

/** Agent update info */
export type AgentUpdateInfo = {
	agentId: string;
	agentName: string;
	installedVersion: string;
	latestVersion: string;
	isNpx: boolean;
};

/** Get list of installed agents that have updates available */
export async function getAgentUpdates(): Promise<AgentUpdateInfo[]> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getagentupdates();
		return parseResult<AgentUpdateInfo[]>(result);
	}
	return [];
}

/** Trigger update for a binary agent (removes old version, downloads new on next use) */
export async function updateRegistryAgent(agentId: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.updateregistryagent(agentId);
	}
}

// ── Prerequisites ───────────────────────────────────────────────────

export type PrerequisiteTool = {
	found: boolean;
	path: string;
	version?: string;
};

export type PrerequisiteStatus = {
	node: PrerequisiteTool;
	npm: PrerequisiteTool;
	npx: PrerequisiteTool;
	git: PrerequisiteTool;
	uv: PrerequisiteTool;
	uvx: PrerequisiteTool;
	bun: PrerequisiteTool;
};

/** Check which prerequisite tools are installed on the system */
export async function getPrerequisiteStatus(): Promise<PrerequisiteStatus> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getprerequisitestatus();
		return parseResult<PrerequisiteStatus>(result);
	}
	const empty: PrerequisiteTool = { found: false, path: '' };
	return { node: empty, npm: empty, npx: empty, git: empty, uv: empty, uvx: empty, bun: empty };
}

export type McpConnectionInfo = {
	serverName: string;
	port: number;
	isRunning: boolean;
	recommendedUrl: string;
	localhostUrl: string;
	legacySseUrl: string;
	legacyMessageUrl: string;
	transport: 'streamable_http' | string;
};

/** Get the live MCP server endpoints for local client configuration. */
export async function getMcpConnectionInfo(): Promise<McpConnectionInfo> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getmcpconnectioninfo();
		return parseResult<McpConnectionInfo>(result);
	}
	return {
		serverName: 'unreal-editor',
		port: 9315,
		isRunning: false,
		recommendedUrl: 'http://127.0.0.1:9315/mcp',
		localhostUrl: 'http://localhost:9315/mcp',
		legacySseUrl: 'http://127.0.0.1:9315/sse',
		legacyMessageUrl: 'http://127.0.0.1:9315/message',
		transport: 'streamable_http'
	};
}

/** Copy text to system clipboard */
export async function copyToClipboard(text: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.copytoclipboard(text);
	}
}

/** Read text from system clipboard */
export async function getClipboardText(): Promise<string> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getclipboardtext();
		const raw =
			result && typeof result === 'object' && 'ReturnValue' in result ? result.ReturnValue : result;
		return (raw as string) || '';
	}
	return '';
}

/** Open URL in system browser */
export async function openUrl(url: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.openurl(url);
	}
}

/** Open an asset or source file in UE. Handles /Game/ paths, filesystem paths, file:line format. */
export async function openPath(path: string, line: number = 0): Promise<void> {
	const bridge = getBridge();
	if (!bridge) {
		console.warn('[AIK] openPath: bridge not available');
		return;
	}
	if (typeof bridge.openpath !== 'function') {
		console.warn(
			'[AIK] openPath: bridge.openpath is not a function, available methods:',
			Object.keys(bridge)
		);
		return;
	}
	try {
		await bridge.openpath(path, line);
	} catch (e) {
		console.error('[AIK] openPath failed:', e);
	}
}

/** Open the plugin settings panel in UE Project Settings */
export async function openPluginSettings(): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.openpluginsettings();
	}
}

/** Restart Unreal Editor (prompts to save unsaved work) */
export async function restartEditor(): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.restarteditor();
	}
}

/** Trigger an async plugin update check in UE */
export async function checkForPluginUpdate(): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.checkforpluginupdate();
	}
}

export type PluginUpdateStatus = {
	/** Installed version, straight off the .uplugin descriptor. */
	currentVersion: string;
	state:
		| 'none'
		| 'checking'
		| 'updateAvailable'
		| 'downloading'
		| 'downloaded'
		| 'installing'
		| 'failed';
	checked: boolean;
	updateAvailable: boolean;
	downloadAvailable: boolean;
	downloadProgress: number;
	/** Empty when the server has no live build for this engine + platform.
	 *  Equal to currentVersion means "you are on the latest". */
	latestVersion: string;
	changelog: string;
	error: string;
};

/** Result of the last update check. Poll after checkForPluginUpdate — the
 *  UE side is fire-and-forget and pushes nothing back. */
export async function getPluginUpdateStatus(): Promise<PluginUpdateStatus | null> {
	const bridge = getBridge();
	if (!bridge) return null;
	const result = await bridge.getpluginupdatestatus();
	return parseResult<PluginUpdateStatus>(result);
}

// ── Model & Reasoning ───────────────────────────────────────────────

export type ModelInfo = {
	id: string;
	name: string;
	description: string;
	supportsReasoning: boolean;
	provider?: string;
	providerDisplayName?: string;
};

export type ModelState = {
	models: ModelInfo[];
	currentModelId: string;
};

export type ConfigSelectValue = {
	value: string;
	name: string;
	description?: string;
};

export type ConfigSelectGroup = {
	group: string;
	name: string;
	options: ConfigSelectValue[];
};

export type SessionSelectConfigOption = {
	type: 'select';
	id: string;
	name: string;
	description?: string;
	category?: string;
	currentValue: string;
	options: ConfigSelectValue[] | ConfigSelectGroup[];
};

export type SessionBooleanConfigOption = {
	type: 'boolean';
	id: string;
	name: string;
	description?: string;
	category?: string;
	currentValue: boolean;
};

export type SessionConfigOption = SessionSelectConfigOption | SessionBooleanConfigOption;

export type ConfigOptionActionResult = {
	accepted: boolean;
	errorCode?: string;
	message?: string;
};

/** Get available models for an agent */
export async function getModels(agentName: string): Promise<ModelState> {
	if (currentTransport === 'remote') return relayCall<ModelState>('getModels', agentName);
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getmodels(agentName);
		return parseResult(result);
	}
	return { models: [], currentModelId: '' };
}

/** Get full model list for an agent when the backend supports it. */
export async function getAllModels(agentName: string): Promise<ModelState> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getallmodels(agentName);
		return parseResult(result);
	}
	return { models: [], currentModelId: '' };
}

/** Set the active model for an agent */
export async function setModel(agentName: string, modelId: string): Promise<void> {
	if (currentTransport === 'remote') {
		await relayCall('setModel', agentName, modelId);
		return;
	}
	const bridge = getBridge();
	if (bridge) {
		await bridge.setmodel(agentName, modelId);
	}
}

/** Get current reasoning effort level for an agent */
export async function getReasoningLevel(agentName: string): Promise<string> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getreasoninglevel(agentName);
		// ReturnValue is a plain string, not JSON
		const raw =
			result && typeof result === 'object' && 'ReturnValue' in result ? result.ReturnValue : result;
		return (raw as string) || 'medium';
	}
	return '';
}

/** Set reasoning effort level for an agent */
export async function setReasoningLevel(agentName: string, level: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setreasoninglevel(agentName, level);
	}
}

// Remote-mode relay listeners: the embedded bridge's bind* calls REPLACE the
// previous callback on the C++ side, but onRelayEvent ADDS a subscriber and the
// wrappers below discard its unsubscribe function. Mirror the replace semantics
// here so binding the same event twice doesn't stack duplicate callbacks.
const relayListenerUnsubs = new Map<string, () => void>();
function bindRelayEvent(event: string, cb: Parameters<typeof onRelayEvent>[1]): void {
	relayListenerUnsubs.get(event)?.();
	relayListenerUnsubs.set(event, onRelayEvent(event, cb));
}

/** Register callback for streaming message updates */
export function onMessage(callback: (sessionId: string, update: StreamingUpdate) => void): void {
	if (currentTransport === 'remote') {
		bindRelayEvent('onMessage', (data: any) => {
			callback(data.sessionId, data.update);
		});
		return;
	}
	bindEmbeddedListener('onMessage', (bridge) => {
		bridge.bindonmessage((sessionId: string, updateJson: string) => {
			const update: StreamingUpdate = JSON.parse(updateJson);
			callback(sessionId, update);
		});
	});
}

/** Register callback for agent state changes */
export function onStateChanged(
	callback: (sessionId: string, agentName: string, state: string, message: string) => void
): void {
	if (currentTransport === 'remote') {
		bindRelayEvent('onStateChanged', (data: any) => {
			callback(data.sessionId, data.agentName, String(data.state), data.message);
		});
		return;
	}
	bindEmbeddedListener('onStateChanged', (bridge) => {
		bridge.bindonstatechanged(callback);
	});
}

/** Register callback for MCP tool readiness status: "waiting" | "ready" | "timeout" */
export function onMcpStatus(callback: (sessionId: string, status: string) => void): void {
	bindEmbeddedListener('onMcpStatus', (bridge) => {
		bridge.bindonmcpstatus(callback);
	});
}

/** Register callback for session list updates from agents */
export function onSessionListUpdated(
	callback: (agentName: string, sessions: SessionInfo[]) => void
): void {
	bindEmbeddedListener('onSessionListUpdated', (bridge) => {
		bridge.bindonsessionlistupdated((agentName: string, sessionsJson: string) => {
			const sessions: SessionInfo[] = JSON.parse(sessionsJson).map((s: any) => ({
				...s,
				agentName,
				isConnected: false
			}));
			callback(agentName, sessions);
		});
	});
}

/** Register callback fired when the LOCAL chat list changes outside the page
 *  (the session mirror adopts a remotely-assigned chat, a native panel opens
 *  one). Payload-free ping — refetch the list on it. */
export function onSessionsChanged(callback: () => void): void {
	bindEmbeddedListener('onSessionsChanged', (bridge) => {
		bridge.bindonsessionschanged(callback);
	});
}

/** Manually refresh session lists from all agents. Returns how many agents are being connected. */
export async function refreshSessionList(): Promise<{ connectingCount: number }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.refreshsessionlist();
		return parseResult(result);
	}
	return { connectingCount: 0 };
}

// ── Permissions ─────────────────────────────────────────────────────

export type PermissionOption = {
	optionId: string;
	name: string;
	kind: 'allow_always' | 'allow_once' | 'reject_once';
};

export type PermissionToolCall = {
	toolCallId: string;
	title: string;
	rawInput: string;
};

export type QuestionOption = {
	label: string;
	description: string;
};

export type Question = {
	question: string;
	header: string;
	options: QuestionOption[];
	multiSelect: boolean;
};

export type PermissionRequest = {
	agentName: string;
	// JSON-RPC id from the agent — string round-tripped to preserve UUID-style ids.
	// (Was `number` historically; coercion lost non-numeric ids → response id:0 → agent dropped reply.)
	requestId: string;
	options: PermissionOption[];
	toolCall: PermissionToolCall;
	isAskUserQuestion: boolean;
	questions: Question[];
};

/** Register callback for permission/consent requests */
export function onPermissionRequest(
	callback: (sessionId: string, request: PermissionRequest) => void
): void {
	if (currentTransport === 'remote') {
		bindRelayEvent('onPermissionRequest', (data: any) => {
			callback(data.sessionId, data);
		});
		return;
	}
	bindEmbeddedListener('onPermissionRequest', (bridge) => {
		bridge.bindonpermissionrequest((sessionId: string, requestJson: string) => {
			const request: PermissionRequest = JSON.parse(requestJson);
			callback(sessionId, request);
		});
	});
}

/** Respond to a permission request */
export async function respondToPermission(
	sessionId: string,
	agentName: string,
	requestId: string,
	optionId: string,
	outcomeMeta?: Record<string, unknown>
): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		const metaJson = outcomeMeta ? JSON.stringify(outcomeMeta) : '';
		if (bridge.respondtopermissionforsession && sessionId) {
			await bridge.respondtopermissionforsession(
				sessionId,
				agentName,
				requestId,
				optionId,
				metaJson
			);
		} else {
			await bridge.respondtopermission(agentName, requestId, optionId, metaJson);
		}
	}
}

// ── Modes ───────────────────────────────────────────────────────────

export type ModeInfo = {
	id: string;
	name: string;
	description: string;
};

export type ModeState = {
	modes: ModeInfo[];
	currentModeId: string;
};

/** Get available modes for an agent */
export async function getModes(agentName: string): Promise<ModeState> {
	if (currentTransport === 'remote') return relayCall<ModeState>('getModes', agentName);
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getmodes(agentName);
		return parseResult(result);
	}
	return { modes: [], currentModeId: '' };
}

/** Set the active mode for an agent */
export async function setMode(agentName: string, modeId: string): Promise<void> {
	if (currentTransport === 'remote') {
		await relayCall('setMode', agentName, modeId);
		return;
	}
	const bridge = getBridge();
	if (bridge) {
		await bridge.setmode(agentName, modeId);
	}
}

/** Get every generic ACP config option for a live session. */
export async function getSessionConfigOptions(sessionId: string): Promise<SessionConfigOption[]> {
	if (currentTransport === 'remote') {
		return relayCall<SessionConfigOption[]>('getSessionConfigOptions', sessionId);
	}
	const bridge = getBridge();
	if (!bridge) return [];
	return parseResult(await bridge.getsessionconfigoptions(sessionId));
}

/** Set a generic select or boolean ACP config option. */
export async function setSessionConfigOption(
	sessionId: string,
	configId: string,
	value: string | boolean
): Promise<void> {
	const valueJson = JSON.stringify(value);
	const bridge = currentTransport === 'remote' ? null : getBridge();
	if (currentTransport !== 'remote' && !bridge) {
		throw new Error('Editor bridge is not available.');
	}
	const result =
		currentTransport === 'remote'
			? await relayCall<ConfigOptionActionResult>(
					'setSessionConfigOption',
					sessionId,
					configId,
					valueJson
				)
			: parseResult<ConfigOptionActionResult>(
					await bridge!.setsessionconfigoption(sessionId, configId, valueJson)
				);
	if (!result?.accepted) {
		throw new Error(result?.message || 'Could not change this session setting.');
	}
}

/** Register for complete generic ACP config option updates. */
export function onConfigOptionsAvailable(
	callback: (sessionId: string, agentName: string, options: SessionConfigOption[]) => void
): void {
	if (currentTransport === 'remote') {
		bindRelayEvent('onConfigOptionsAvailable', (data: any) => {
			callback(data.sessionId, data.agentName, JSON.parse(data.configOptionsJson || '[]'));
		});
		return;
	}
	bindEmbeddedListener('onConfigOptionsAvailable', (bridge) => {
		bridge.bindonconfigoptionsavailable(
			(sessionId: string, agentName: string, optionsJson: string) => {
				callback(sessionId, agentName, JSON.parse(optionsJson || '[]'));
			}
		);
	});
}

/** Register callback for mode availability updates */
export function onModesAvailable(
	callback: (agentName: string, modeState: ModeState) => void
): void {
	if (currentTransport === 'remote') {
		bindRelayEvent('onModesAvailable', (data: any) => {
			callback(data.agentName, data);
		});
		return;
	}
	bindEmbeddedListener('onModesAvailable', (bridge) => {
		bridge.bindonmodesavailable((agentName: string, modesJson: string) => {
			const modeState: ModeState = JSON.parse(modesJson);
			callback(agentName, modeState);
		});
	});
}

/** Register callback for mode change notifications */
export function onModeChanged(callback: (agentName: string, modeId: string) => void): void {
	bindEmbeddedListener('onModeChanged', (bridge) => {
		bridge.bindonmodechanged(callback);
	});
}

/** Register callback for model availability updates (async push from agents like Codex) */
export function onModelsAvailable(
	callback: (agentName: string, modelState: ModelState) => void
): void {
	if (currentTransport === 'remote') {
		bindRelayEvent('onModelsAvailable', (data: any) => {
			callback(data.agentName, data);
		});
		return;
	}
	bindEmbeddedListener('onModelsAvailable', (bridge) => {
		bridge.bindonmodelsavailable((agentName: string, modelsJson: string) => {
			const modelState: ModelState = JSON.parse(modelsJson);
			callback(agentName, modelState);
		});
	});
}

// ── Slash Commands ──────────────────────────────────────────────────

export type SlashCommand = {
	name: string;
	description: string;
	inputHint: string;
};

/** Register callback for slash commands availability updates */
export function onCommandsAvailable(
	callback: (sessionId: string, commands: SlashCommand[]) => void
): void {
	bindEmbeddedListener('onCommandsAvailable', (bridge) => {
		bridge.bindoncommandsavailable((sessionId: string, commandsJson: string) => {
			const commands: SlashCommand[] = JSON.parse(commandsJson);
			callback(sessionId, commands);
		});
	});
}

// ── Plan/Todo ───────────────────────────────────────────────────────

export type PlanEntry = {
	content: string;
	activeForm: string;
	priority: 'high' | 'medium' | 'low';
	status: 'pending' | 'in_progress' | 'completed';
};

export type PlanUpdate = {
	entries: PlanEntry[];
	completedCount: number;
	totalCount: number;
};

/** Register callback for plan/todo updates */
export function onPlanUpdate(callback: (sessionId: string, plan: PlanUpdate) => void): void {
	if (currentTransport === 'remote') {
		bindRelayEvent('onPlanUpdate', (data: any) => {
			callback(data.sessionId, data);
		});
		return;
	}
	bindEmbeddedListener('onPlanUpdate', (bridge) => {
		bridge.bindonplanupdate((sessionId: string, planJson: string) => {
			const plan: PlanUpdate = JSON.parse(planJson);
			callback(sessionId, plan);
		});
	});
}

// ── Attachments ─────────────────────────────────────────────────────

export type AttachmentInfo = {
	id: string;
	type: 'blueprint_node' | 'blueprint' | 'image' | 'file' | 'actor' | 'object';
	displayName: string;
	mimeType?: string;
	width?: number;
	height?: number;
	sizeBytes?: number;
	hasExtractedText?: boolean;
	thumbnail?: string;
};

/** Paste image from system clipboard into attachments */
export async function pasteClipboardImage(
	sessionId: string
): Promise<{ success: boolean; error?: string }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.pasteclipboardimage(sessionId);
		return parseResult(result);
	}
	return { success: false, error: 'Not in UE' };
}

/** Open native file picker for attachments (images + common docs) */
export async function openImagePicker(
	sessionId: string
): Promise<{ success: boolean; count: number; error?: string }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.openimagepicker(sessionId);
		return parseResult(result);
	}
	return { success: false, count: 0 };
}

/** Remove an attachment by its GUID */
export async function removeAttachment(sessionId: string, id: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.removeattachment(sessionId, id);
	}
}

/** Get current attachments (metadata only) */
export async function getAttachments(sessionId: string): Promise<AttachmentInfo[]> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getattachments(sessionId);
		return parseResult(result);
	}
	return [];
}

/** Register callback for attachment list changes */
export function onAttachmentsChanged(
	callback: (sessionId: string, attachments: AttachmentInfo[]) => void
): void {
	bindEmbeddedListener('onAttachmentsChanged', (bridge) => {
		bridge.bindonattachmentschanged((sessionId: string, attachmentsJson: string) => {
			const attachments: AttachmentInfo[] = JSON.parse(attachmentsJson);
			callback(sessionId, attachments);
		});
	});
}

/** Register callback for worker-thread/native attachment ingestion failures. */
export function onAttachmentError(callback: (sessionId: string, message: string) => void): void {
	bindEmbeddedListener('onAttachmentError', (bridge) => {
		bridge.bindonattachmenterror(callback);
	});
}

// ── Context Mentions ────────────────────────────────────────────────

export type ContextItem = {
	name: string;
	path: string;
	category: string;
	type: string;
	icon?: string; // Raw SVG string from engine (Starship class icons)
};

/** Search for assets/files to attach via @ mention */
export async function searchContextItems(query: string): Promise<ContextItem[]> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.searchcontextitems(query);
		return parseResult(result);
	}
	return [];
}

// ── Agent Authentication ────────────────────────────────────────────

export type AuthMethod = {
	id: string;
	name: string;
	description: string;
	isTerminalAuth: boolean;
};

/** Get available auth methods for an agent */
export async function getAuthMethods(agentName: string): Promise<AuthMethod[]> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getauthmethods(agentName);
		return parseResult(result);
	}
	return [];
}

/** Start agent login with a specific auth method */
export async function startAgentLogin(agentName: string, methodId: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.startagentlogin(agentName, methodId);
	}
}

/** Register callback for login completion */
export function onLoginComplete(
	callback: (agentName: string, success: boolean, errorMessage: string) => void
): void {
	bindEmbeddedListener('onLoginComplete', (bridge) => {
		bridge.bindonlogincomplete(callback);
	});
}

// ── Agent Usage / Rate Limits ──────────────────────────────────────

export type RateLimitWindow = {
	usedPercent: number;
	resetsAt: string;
	windowDurationMinutes: number;
	hasData: boolean;
};

export type ExtraUsage = {
	isEnabled: boolean;
	usedAmount: number;
	limitAmount: number;
	currencyCode: string;
	hasData: boolean;
};

export type AgentRateLimitData = {
	hasData: boolean;
	isLoading: boolean;
	errorMessage: string;
	agentName: string;
	planType: string;
	lastUpdated: string;
	primary: RateLimitWindow;
	secondary: RateLimitWindow;
	modelSpecific: RateLimitWindow;
	modelSpecificLabel: string;
	extraUsage: ExtraUsage;
};

/** Get cached rate limit data for an agent (triggers background fetch if needed) */
export async function getAgentUsage(agentName: string): Promise<AgentRateLimitData> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getagentusage(agentName);
		return parseResult(result);
	}
	return {
		hasData: false,
		isLoading: false,
		errorMessage: '',
		agentName,
		planType: '',
		lastUpdated: '',
		primary: { usedPercent: 0, resetsAt: '', windowDurationMinutes: 0, hasData: false },
		secondary: { usedPercent: 0, resetsAt: '', windowDurationMinutes: 0, hasData: false },
		modelSpecific: { usedPercent: 0, resetsAt: '', windowDurationMinutes: 0, hasData: false },
		modelSpecificLabel: '',
		extraUsage: {
			isEnabled: false,
			usedAmount: 0,
			limitAmount: 0,
			currencyCode: '',
			hasData: false
		}
	};
}

/** Force-refresh usage data for an agent */
export async function refreshAgentUsage(agentName: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.refreshagentusage(agentName);
	}
}

/** Register callback for agent usage/rate-limit updates */
export function onUsageUpdated(
	callback: (agentName: string, data: AgentRateLimitData) => void
): void {
	bindEmbeddedListener('onUsageUpdated', (bridge) => {
		bridge.bindonusageupdated((agentName: string, usageJson: string) => {
			const data: AgentRateLimitData = JSON.parse(usageJson);
			callback(agentName, data);
		});
	});
}

// ── Project Indexing ────────────────────────────────────────────────

export type IndexingScopeBreakdown = {
	blueprints: number;
	cppFiles: number;
	assets: number;
	levels: number;
	config: number;
	documents: number;
};

export type IndexingSettings = {
	provider: 'openrouter' | 'custom';
	endpointUrl: string;
	apiKey: string;
	model: string;
	dimensions: number;
	autoIndex: boolean;
	scope: {
		blueprints: boolean;
		cppFiles: boolean;
		assets: boolean;
		levels: boolean;
		config: boolean;
		documents: boolean;
	};
	hasOpenRouterKey: boolean;
};

export type IndexingStatus = {
	state: 'idle' | 'indexing' | 'ready' | 'error';
	totalChunks: number;
	indexedChunks: number;
	lastIndexedAt: string;
	indexSizeBytes: number;
	errorMessage: string;
	breakdown: IndexingScopeBreakdown;
	embeddingModel: string;
	embeddingDimensions: number;
};

export async function getIndexingSettings(): Promise<IndexingSettings> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getindexingsettings();
		return parseResult(result);
	}
	return {
		provider: 'openrouter',
		endpointUrl: '',
		apiKey: '',
		model: 'google/gemini-embedding-001',
		dimensions: 768,
		autoIndex: false,
		scope: {
			blueprints: true,
			cppFiles: true,
			assets: true,
			levels: true,
			config: false,
			documents: true
		},
		hasOpenRouterKey: false
	};
}

export async function getIndexingStatus(): Promise<IndexingStatus> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getindexingstatus();
		return parseResult(result);
	}
	return {
		state: 'idle',
		totalChunks: 0,
		indexedChunks: 0,
		lastIndexedAt: '',
		indexSizeBytes: 0,
		errorMessage: '',
		breakdown: { blueprints: 0, cppFiles: 0, assets: 0, levels: 0, config: 0, documents: 0 },
		embeddingModel: '',
		embeddingDimensions: 0
	};
}

export async function setIndexingProvider(provider: 'openrouter' | 'custom'): Promise<void> {
	const bridge = getBridge();
	if (bridge) await bridge.setindexingprovider(provider);
}

export async function setIndexingEndpointUrl(url: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) await bridge.setindexingendpointurl(url);
}

export async function setIndexingApiKey(key: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) await bridge.setindexingapikey(key);
}

export async function setIndexingModel(model: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) await bridge.setindexingmodel(model);
}

export async function setIndexingDimensions(dims: number): Promise<void> {
	const bridge = getBridge();
	if (bridge) await bridge.setindexingdimensions(dims);
}

export async function setAutoIndex(enabled: boolean): Promise<void> {
	const bridge = getBridge();
	if (bridge) await bridge.setautoindex(enabled);
}

export async function setIndexingScopeEnabled(scope: string, enabled: boolean): Promise<void> {
	const bridge = getBridge();
	if (bridge) await bridge.setindexingscopeenabled(scope, enabled);
}

export async function startIndexing(): Promise<void> {
	const bridge = getBridge();
	if (bridge) await bridge.startindexing();
}

export async function clearIndex(): Promise<void> {
	const bridge = getBridge();
	if (bridge) await bridge.clearindex();
}

// ── Source Control ──────────────────────────────────────────────────

export type SourceControlStatus = {
	enabled: boolean;
	provider: string;
	branch: string;
	changesCount: number;
	connected: boolean;
};

/** Get current source control status (branch, changes, provider) */
export async function getSourceControlStatus(): Promise<SourceControlStatus> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getsourcecontrolstatus();
		return parseResult(result);
	}
	return { enabled: false, provider: '', branch: '', changesCount: -1, connected: false };
}

/** Open the UE source control changelists tab */
export async function openSourceControlChangelist(): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.opensourcecontrolchangelist();
	}
}

/** Open the UE check-in/submit dialog */
export async function openSourceControlSubmit(): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.opensourcecontrolsubmit();
	}
}

// ── Terminal ────────────────────────────────────────────────────────

/** Start a new terminal session. Returns the terminal ID. */
export async function startTerminal(
	workingDir: string = '',
	shell: string = ''
): Promise<{ terminalId?: string; error?: string }> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.startterminal(workingDir, shell);
		return parseResult(result);
	}
	return { error: 'Not in UE' };
}

/** Write input data to a terminal (raw string from xterm.js onData) */
export async function writeTerminal(terminalId: string, data: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.writeterminal(terminalId, data);
	}
}

/** Resize terminal PTY */
export async function resizeTerminal(
	terminalId: string,
	cols: number,
	rows: number
): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.resizeterminal(terminalId, cols, rows);
	}
}

/** Close a terminal session */
export async function closeTerminal(terminalId: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.closeterminal(terminalId);
	}
}

const terminalOutputListeners = new Set<(terminalId: string, base64Data: string) => void>();
const terminalExitListeners = new Set<(terminalId: string, exitCode: number) => void>();

function dispatchTerminalOutput(terminalId: string, base64Data: string): void {
	for (const listener of terminalOutputListeners) {
		try {
			listener(terminalId, base64Data);
		} catch (e) {
			console.warn('subscribeTerminalOutput listener error:', e);
		}
	}
}

function dispatchTerminalExit(terminalId: string, exitCode: number): void {
	for (const listener of terminalExitListeners) {
		try {
			listener(terminalId, exitCode);
		} catch (e) {
			console.warn('subscribeTerminalExit listener error:', e);
		}
	}
}

/**
 * Subscribe to PTY output for all terminal sessions. Multiple xterm instances must each subscribe —
 * UE only allows one bridge callback; this multicasts.
 * @returns Unsubscribe (call on component destroy).
 */
export function subscribeTerminalOutput(
	callback: (terminalId: string, base64Data: string) => void
): () => void {
	terminalOutputListeners.add(callback);
	bindEmbeddedListener('onTerminalOutput', (bridge) => {
		bridge.bindonterminaloutput(dispatchTerminalOutput);
	});
	return () => {
		terminalOutputListeners.delete(callback);
	};
}

/** @returns Unsubscribe (call on component destroy). */
export function subscribeTerminalExit(
	callback: (terminalId: string, exitCode: number) => void
): () => void {
	terminalExitListeners.add(callback);
	bindEmbeddedListener('onTerminalExit', (bridge) => {
		bridge.bindonterminalexit(dispatchTerminalExit);
	});
	return () => {
		terminalExitListeners.delete(callback);
	};
}

// ── Studio / durable NeoStack Cloud media jobs ─────────────────────

export type MediaField = {
	name: string;
	type: 'string' | 'number' | 'integer' | 'boolean' | 'string_array';
	description: string;
	required?: boolean;
	enum?: string[];
	default?: string | number | boolean;
	minimum?: number;
	maximum?: number;
	multiline?: boolean;
};

export type MediaModel = {
	id: string;
	name: string;
	description: string;
	provider: string;
	kind: 'image' | '3d' | 'audio';
	action: string;
	capabilities: {
		input: string[];
		output: string[];
		progress: boolean;
		cancellation: boolean;
	};
	required: string[];
	fields: MediaField[];
};

export type MediaJob = {
	id: string;
	model: string;
	action: string;
	status: 'submitting' | 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
	stage: string;
	progress: number | null;
	queue_position: number | null;
	logs: { message: string; timestamp?: string }[];
	result: unknown;
	error: string | null;
	created_at: string;
	updated_at: string;
	completed_at: string | null;
};

type MediaError = { error?: string | { message?: string } };

function mediaError(value: MediaError): string | null {
	if (typeof value.error === 'string') return value.error;
	return value.error?.message ?? null;
}

export async function getMediaModels(): Promise<{ models: MediaModel[]; error: string | null }> {
	const bridge = getBridge();
	if (!bridge) return { models: [], error: 'Bridge not available' };
	const parsed = parseResult<{ data?: MediaModel[] } & MediaError>(await bridge.getmediamodels());
	return { models: parsed.data ?? [], error: mediaError(parsed) };
}

export async function listMediaJobs(): Promise<{ jobs: MediaJob[]; error: string | null }> {
	const bridge = getBridge();
	if (!bridge) return { jobs: [], error: 'Bridge not available' };
	const parsed = parseResult<{ jobs?: MediaJob[] } & MediaError>(await bridge.listmediajobs());
	return { jobs: parsed.jobs ?? [], error: mediaError(parsed) };
}

export async function submitMediaJob(
	model: string,
	input: Record<string, unknown>
): Promise<{ job?: MediaJob; error: string | null }> {
	const bridge = getBridge();
	if (!bridge) return { error: 'Bridge not available' };
	const parsed = parseResult<{ job?: MediaJob } & MediaError>(
		await bridge.submitmediajob(model, JSON.stringify(input))
	);
	return { job: parsed.job, error: mediaError(parsed) };
}

export async function getMediaJob(
	jobId: string
): Promise<{ job?: MediaJob; error: string | null }> {
	const bridge = getBridge();
	if (!bridge) return { error: 'Bridge not available' };
	const parsed = parseResult<{ job?: MediaJob } & MediaError>(await bridge.getmediajob(jobId));
	return { job: parsed.job, error: mediaError(parsed) };
}

export async function cancelMediaJob(
	jobId: string
): Promise<{ job?: MediaJob; error: string | null }> {
	const bridge = getBridge();
	if (!bridge) return { error: 'Bridge not available' };
	const parsed = parseResult<{ job?: MediaJob } & MediaError>(await bridge.cancelmediajob(jobId));
	return { job: parsed.job, error: mediaError(parsed) };
}

// ── Crash Reporting ─────────────────────────────────────────────────

export type CrashRecord = {
	crashId: string;
	timestamp: string;
	errorMessage: string;
	crashType: string;
	callstackSummary: string;
	basicReported: boolean;
	fullLogSent: boolean;
	fullLogDeclined: boolean;
	manuallyReported: boolean;
};

/** Get crash history from local crash_history.json */
export async function getCrashHistory(): Promise<CrashRecord[]> {
	if (currentTransport === 'remote') return relayCall<CrashRecord[]>('getCrashHistory');
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getcrashhistory();
		return parseResult<CrashRecord[]>(result);
	}
	return [];
}

/** Manually send a crash report for a previously declined crash */
export async function reportCrash(crashId: string): Promise<{ success: boolean }> {
	if (currentTransport === 'remote') return relayCall<{ success: boolean }>('reportCrash', crashId);
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.reportcrash(crashId);
		return parseResult<{ success: boolean }>(result);
	}
	return { success: false };
}

// ── NeoStack Sign-in (Clerk loopback PKCE) ──────────────────────────

export type NeoStackAuthStatus = 'signedOut' | 'signingIn' | 'signedIn';

export interface NeoStackAuthUser {
	id: string;
	email: string;
	name: string;
	pictureUrl: string;
}

export interface NeoStackEntitlement {
	entitled: boolean;
	reason?: string;
	plan?: string;
	planName?: string;
	features?: string[];
	featureFlags?: string[];
}

export interface NeoStackAuthState {
	status: NeoStackAuthStatus;
	user?: NeoStackAuthUser;
	/** The token's own org claim (whatever was active at sign-in). */
	organizationId?: string;
	/** The org requests actually act in (user override, else the claim) —
	 *  display THIS one; acting in the wrong org silently is the failure mode
	 *  org switching exists to kill. */
	activeOrgId?: string;
	entitlement?: NeoStackEntitlement;
	error?: string;
	/** `status` is 'signedOut' ONLY because NeoStack couldn't be reached — the
	 *  credential is still on disk and the plugin is still retrying. Never
	 *  render a sign-in form for this; the user has nothing to fix. */
	unreachable?: boolean;
}

export interface NeoStackOrg {
	id: string;
	slug: string;
	name: string;
	role: string;
}

export interface NeoStackOrgsResult {
	orgs?: NeoStackOrg[];
	activeOrgId?: string;
	error?: string;
}

/** Begin the browser sign-in flow (opens the system browser, loopback PKCE).
 *  No-op while a flow is already in flight. Progress updates arrive on the
 *  callback registered via onNeoStackAuthChanged. */
export async function startNeoStackSignIn(): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.startneostacksignin();
	}
}

/** Best-effort server-side revoke, then clear the local credential. */
export async function signOutNeoStack(): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.signoutneostack();
	}
}

/** Snapshot of the current auth state. */
export async function getNeoStackAuthState(): Promise<NeoStackAuthState> {
	const bridge = getBridge();
	if (bridge) {
		const result = await bridge.getneostackauthstate();
		return parseResult<NeoStackAuthState>(result);
	}
	// Outside UE (browser dev), pretend signed out so the UI is exercisable.
	return { status: 'signedOut' };
}

/** Orgs the signed-in user belongs to. One-shot fetch through the gateway. */
export function fetchNeoStackOrgs(): Promise<NeoStackOrgsResult> {
	const bridge = getBridge();
	if (!bridge) {
		// Browser dev: an empty picker, not a crash.
		return Promise.resolve({ orgs: [] });
	}
	return new Promise((resolve) => {
		bridge.fetchneostackorgs((json: string) => {
			try {
				resolve(JSON.parse(json) as NeoStackOrgsResult);
			} catch {
				resolve({ error: 'Malformed organizations payload' });
			}
		});
	});
}

/** Switch the org every gateway request acts in ('' = follow the token).
 *  The updated state arrives via onNeoStackAuthChanged. */
export async function setNeoStackActiveOrg(orgId: string): Promise<void> {
	const bridge = getBridge();
	if (bridge) {
		await bridge.setneostackactiveorg(orgId);
	}
}

export interface NeoStackProject {
	id: string;
	slug: string;
	name: string;
}

export interface NeoStackProjectsResult {
	projects?: NeoStackProject[];
	/** '' = unlinked. */
	currentProjectId?: string;
	/** False until the device announce has registered this UE project as a
	 *  workspace — linking needs the row to exist. */
	workspaceRegistered?: boolean;
	error?: string;
}

/** The active org's linkable projects + this UE project's current link. */
export function fetchNeoStackProjects(): Promise<NeoStackProjectsResult> {
	const bridge = getBridge();
	if (!bridge) {
		return Promise.resolve({ projects: [] });
	}
	return new Promise((resolve) => {
		bridge.fetchneostackprojects((json: string) => {
			try {
				resolve(JSON.parse(json) as NeoStackProjectsResult);
			} catch {
				resolve({ error: 'Malformed projects payload' });
			}
		});
	});
}

/** Link the open UE project to a web project ('' = unlink). The link is by
 *  ids — the local folder name and the project name are unrelated. */
export function linkNeoStackProject(
	projectId: string
): Promise<{ linked?: boolean; error?: string }> {
	const bridge = getBridge();
	if (!bridge) {
		return Promise.resolve({ error: 'Not running inside Unreal' });
	}
	return new Promise((resolve) => {
		bridge.linkneostackproject(projectId, (json: string) => {
			try {
				resolve(JSON.parse(json) as { linked?: boolean; error?: string });
			} catch {
				resolve({ error: 'Malformed link result' });
			}
		});
	});
}

/** Register a listener for auth-state updates. */
export function onNeoStackAuthChanged(callback: (state: NeoStackAuthState) => void): void {
	bindEmbeddedListener('onNeoStackAuthChanged', (bridge) => {
		bridge.bindonneostackauthchanged((stateJson: string) => {
			try {
				callback(JSON.parse(stateJson) as NeoStackAuthState);
			} catch {
				console.warn('NeoStack auth state payload was malformed');
			}
		});
	});
}
