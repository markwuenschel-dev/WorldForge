export const PERFORMANCE_BUDGETS = Object.freeze({
	composer_input: 50,
	session_switch_visible: 100,
	session_resume_bridge: 500,
	attachment_mutation: 250,
	prompt_to_first_visible_update: 10_000,
	long_task: 50,
	dom_nodes: 2_500,
	heap_growth: 64 * 1024 * 1024
});

/** @typedef {keyof typeof PERFORMANCE_BUDGETS} MetricName */
/** @typedef {{ id: number, name: MetricName, startedAt: number, details: Record<string, unknown> }} ActiveSpan */
/** @typedef {{ sequence: number, name: MetricName, value: number, unit: string, budget: number, exceeded: boolean, at: string, details: Record<string, unknown> }} PerformanceRecord */

const MAX_RECORDS = 200;
/** @type {Map<number, ActiveSpan>} */
const activeSpans = new Map();
/** @type {Map<string, number>} */
const keyedSpans = new Map();
/** @type {PerformanceRecord[]} */
const records = [];
let nextSpanId = 1;
let nextRecordSequence = 1;
let lastExportedSequence = 0;
let monitorCount = 0;
let baselineHeap = null;

const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

/** @param {PerformanceRecord} record */
function appendRecord(record) {
	records.push(record);
	if (records.length > MAX_RECORDS) records.splice(0, records.length - MAX_RECORDS);
	if (record.exceeded) console.warn('[NeoStackPerf]', JSON.stringify(record));
	return record;
}

/**
 * @param {MetricName} name
 * @param {number} value
 * @param {Record<string, unknown>} [details]
 */
function recordMetric(name, value, details = {}) {
	const budget = PERFORMANCE_BUDGETS[name];
	return appendRecord({
		sequence: nextRecordSequence++,
		name,
		value: Math.round(value * 100) / 100,
		unit: name === 'dom_nodes' ? 'count' : name === 'heap_growth' ? 'bytes' : 'ms',
		budget,
		exceeded: typeof budget === 'number' && value > budget,
		at: new Date().toISOString(),
		details
	});
}

/**
 * @param {MetricName} name
 * @param {Record<string, unknown>} [details]
 */
export function beginPerformanceSpan(name, details = {}) {
	const span = { id: nextSpanId++, name, startedAt: now(), details };
	activeSpans.set(span.id, span);
	try {
		performance.mark(`neostack:${name}:${span.id}:start`);
	} catch {
		// Performance marks are optional in older embedded Chromium builds.
	}
	return span.id;
}

/**
 * @param {number} spanId
 * @param {Record<string, unknown>} [details]
 */
export function endPerformanceSpan(spanId, details = {}) {
	const span = activeSpans.get(spanId);
	if (!span) return null;
	activeSpans.delete(spanId);
	const duration = Math.max(0, now() - span.startedAt);
	try {
		const start = `neostack:${span.name}:${span.id}:start`;
		const end = `neostack:${span.name}:${span.id}:end`;
		performance.mark(end);
		performance.measure(`neostack:${span.name}`, start, end);
		performance.clearMarks(start);
		performance.clearMarks(end);
	} catch {
		// Keep the bounded in-memory record even if User Timing is unavailable.
	}
	return recordMetric(span.name, duration, { ...span.details, ...details });
}

/**
 * @param {MetricName} name
 * @param {string} key
 * @param {Record<string, unknown>} [details]
 */
export function beginKeyedPerformanceSpan(name, key, details = {}) {
	const compoundKey = `${name}:${key}`;
	const previous = keyedSpans.get(compoundKey);
	if (previous) endPerformanceSpan(previous, { superseded: true });
	const spanId = beginPerformanceSpan(name, { ...details, key });
	keyedSpans.set(compoundKey, spanId);
	return spanId;
}

/**
 * @param {MetricName} name
 * @param {string} key
 * @param {Record<string, unknown>} [details]
 */
export function endKeyedPerformanceSpan(name, key, details = {}) {
	const compoundKey = `${name}:${key}`;
	const spanId = keyedSpans.get(compoundKey);
	if (!spanId) return null;
	keyedSpans.delete(compoundKey);
	return endPerformanceSpan(spanId, details);
}

/**
 * @param {MetricName} name
 * @param {string} key
 * @param {Record<string, unknown>} [details]
 */
export function endKeyedPerformanceSpanAfterPaint(name, key, details = {}) {
	const finish = () => endKeyedPerformanceSpan(name, key, details);
	if (
		typeof requestAnimationFrame !== 'function' ||
		(typeof document !== 'undefined' && document.hidden)
	) {
		setTimeout(finish, 0);
		return;
	}
	requestAnimationFrame(() => requestAnimationFrame(finish));
}

/**
 * @param {MetricName} name
 * @param {number} eventTimestamp
 * @param {Record<string, unknown>} [details]
 */
export function recordInteractionLatency(name, eventTimestamp, details = {}) {
	if (typeof requestAnimationFrame !== 'function') return;
	const normalizedTimestamp =
		eventTimestamp > 1_000_000_000_000 && typeof performance !== 'undefined'
			? eventTimestamp - performance.timeOrigin
			: eventTimestamp;
	requestAnimationFrame(() => {
		recordMetric(name, Math.max(0, now() - normalizedTimestamp), details);
	});
}

function sampleResourcePressure() {
	if (typeof document !== 'undefined') {
		recordMetric('dom_nodes', document.getElementsByTagName('*').length);
	}
	const memory =
		typeof performance !== 'undefined'
			? /** @type {{ memory?: { usedJSHeapSize?: number } }} */ (performance).memory
			: undefined;
	if (memory?.usedJSHeapSize) {
		baselineHeap ??= memory.usedJSHeapSize;
		recordMetric('heap_growth', Math.max(0, memory.usedJSHeapSize - baselineHeap), {
			usedJSHeapSize: memory.usedJSHeapSize
		});
	}
}

export function getPerformanceSnapshot() {
	return {
		budgets: PERFORMANCE_BUDGETS,
		activeSpanCount: activeSpans.size,
		records: records.slice()
	};
}

/** Return each record at most once for native aggregate export. Details remain
 * in the local diagnostics snapshot but native intentionally discards them. */
export function takePerformanceRecordsForExport() {
	const pending = records.filter((record) => record.sequence > lastExportedSequence);
	if (pending.length > 0) lastExportedSequence = pending[pending.length - 1].sequence;
	return pending.slice();
}

export function startPerformanceMonitoring() {
	monitorCount += 1;
	if (monitorCount > 1) return () => stopPerformanceMonitoring();

	/** @type {PerformanceObserver | undefined} */
	let observer;
	try {
		observer = new PerformanceObserver((list) => {
			for (const entry of list.getEntries()) {
				recordMetric('long_task', entry.duration, { startTime: entry.startTime });
			}
		});
		observer.observe({ type: 'longtask', buffered: true });
	} catch {
		// Long Tasks are not exposed by every CEF build; span and resource data remain available.
	}

	const interval = setInterval(sampleResourcePressure, 5_000);
	sampleResourcePressure();
	/** @type {any} */ (globalThis).__NEOSTACK_PERFORMANCE__ = {
		getSnapshot: getPerformanceSnapshot
	};

	return () => {
		stopPerformanceMonitoring();
		clearInterval(interval);
		observer?.disconnect();
	};
}

function stopPerformanceMonitoring() {
	monitorCount = Math.max(0, monitorCount - 1);
	if (monitorCount === 0) delete (/** @type {any} */ (globalThis).__NEOSTACK_PERFORMANCE__);
}

export function resetPerformanceTelemetryForTests() {
	activeSpans.clear();
	keyedSpans.clear();
	records.length = 0;
	baselineHeap = null;
	nextRecordSequence = 1;
	lastExportedSequence = 0;
}
