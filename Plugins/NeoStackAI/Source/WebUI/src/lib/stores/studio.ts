import { get, writable } from 'svelte/store';
import {
	cancelMediaJob,
	getMediaJob,
	getMediaModels,
	listMediaJobs,
	submitMediaJob,
	type MediaJob,
	type MediaModel
} from '$lib/bridge.js';

export const models = writable<MediaModel[]>([]);
export const jobs = writable<MediaJob[]>([]);
export const loading = writable(false);
export const studioError = writable('');

const pollers = new Map<string, ReturnType<typeof setInterval>>();
const failures = new Map<string, number>();
const ACTIVE = new Set<MediaJob['status']>(['submitting', 'queued', 'running']);

function upsert(job: MediaJob): void {
	jobs.update((current) => [job, ...current.filter((item) => item.id !== job.id)]);
}

function stopPolling(jobId: string): void {
	const timer = pollers.get(jobId);
	if (timer) clearInterval(timer);
	pollers.delete(jobId);
	failures.delete(jobId);
}

function startPolling(job: MediaJob): void {
	if (!ACTIVE.has(job.status) || pollers.has(job.id)) return;
	const timer = setInterval(async () => {
		const result = await getMediaJob(job.id);
		if (!result.job) {
			const count = (failures.get(job.id) ?? 0) + 1;
			failures.set(job.id, count);
			if (count >= 5) {
				stopPolling(job.id);
				studioError.set(result.error ?? 'Could not refresh a generation job.');
			}
			return;
		}
		failures.delete(job.id);
		upsert(result.job);
		if (!ACTIVE.has(result.job.status)) stopPolling(result.job.id);
	}, 3000);
	pollers.set(job.id, timer);
}

export async function initializeStudio(): Promise<void> {
	if (get(loading)) return;
	loading.set(true);
	studioError.set('');
	try {
		const [modelResult, jobResult] = await Promise.all([getMediaModels(), listMediaJobs()]);
		models.set(modelResult.models);
		jobs.set(jobResult.jobs);
		const error = modelResult.error ?? jobResult.error;
		if (error) studioError.set(error);
		for (const job of jobResult.jobs) startPolling(job);
	} finally {
		loading.set(false);
	}
}

export async function submitJob(
	model: string,
	input: Record<string, unknown>
): Promise<string | null> {
	const result = await submitMediaJob(model, input);
	if (!result.job) return result.error ?? 'Could not submit the generation job.';
	upsert(result.job);
	startPolling(result.job);
	return null;
}

export async function cancelJob(jobId: string): Promise<string | null> {
	const result = await cancelMediaJob(jobId);
	if (!result.job) return result.error ?? 'Could not cancel the generation job.';
	upsert(result.job);
	stopPolling(jobId);
	return null;
}

export function resumeActivePolling(): void {
	for (const job of get(jobs)) startPolling(job);
}

export function stopAllPolling(): void {
	for (const jobId of [...pollers.keys()]) stopPolling(jobId);
}
