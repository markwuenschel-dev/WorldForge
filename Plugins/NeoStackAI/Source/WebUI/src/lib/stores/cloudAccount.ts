import { writable, get } from 'svelte/store';
import {
	bindNeoStackAccountChanged,
	getNeoStackAccountStatus,
	type CloudAccountStatus
} from '$lib/bridge.js';

export type CloudAccountLoadState = 'idle' | 'loading' | 'ready' | 'error';

export const cloudAccount = writable<CloudAccountStatus | null>(null);
export const cloudAccountLoadState = writable<CloudAccountLoadState>('idle');
export const cloudAccountError = writable('');

let listenerBound = false;

export function formatTierLabel(status?: string): string {
	if (!status || status === 'none') return 'Free';
	return status
		.split('+')
		.map((part) =>
			part
				.split('-')
				.map((word) => word.charAt(0).toUpperCase() + word.slice(1))
				.join(' ')
		)
		.join(' + ');
}

/** Mask an email like `devesh@neostack.dev` → `de••••h@n••••k.dev`.
 *  Used when the user has enabled Hide Email Address in Appearance. */
export function maskEmail(email?: string | null): string {
	if (!email) return '';
	const at = email.indexOf('@');
	if (at < 0) return email;
	const local = email.slice(0, at);
	const domain = email.slice(at + 1);
	const dot = domain.lastIndexOf('.');
	const domainName = dot > 0 ? domain.slice(0, dot) : domain;
	const tld = dot > 0 ? domain.slice(dot) : '';
	const maskPart = (s: string): string => {
		if (s.length <= 2) return '••';
		return `${s[0]}••••${s[s.length - 1]}`;
	};
	return `${maskPart(local)}@${maskPart(domainName)}${tld}`;
}

export function userInitials(name?: string | null, email?: string | null): string {
	const source = (name || email || '').trim();
	if (!source) return '?';
	const parts = source.split(/\s+/).filter(Boolean);
	if (parts.length >= 2) {
		return (parts[0][0] + parts[1][0]).toUpperCase();
	}
	return source.slice(0, 2).toUpperCase();
}

export function usageColor(pct: number): string {
	if (pct < 60) return '#22c55e';
	if (pct < 85) return '#eab308';
	return '#ef4444';
}

export function peakQuotaPercent(quota?: CloudAccountStatus['quota']): number {
	if (!quota) return 0;
	const burst = quota.burst?.percent ?? 0;
	const period = quota.period?.percent ?? 0;
	return Math.round(Math.max(burst, period));
}

export async function refreshCloudAccount(): Promise<void> {
	cloudAccountLoadState.set('loading');
	cloudAccountError.set('');
	try {
		const status = await getNeoStackAccountStatus();
		cloudAccount.set(status);
		cloudAccountLoadState.set('ready');
	} catch (e) {
		console.warn('Failed to load NeoStack account status:', e);
		cloudAccountError.set(e instanceof Error ? e.message : 'Could not load account status.');
		cloudAccountLoadState.set('error');
	}
}

export function bindCloudAccountListener(): void {
	if (listenerBound) return;
	listenerBound = true;
	bindNeoStackAccountChanged((status) => {
		cloudAccount.set(status);
		cloudAccountLoadState.set('ready');
		cloudAccountError.set('');
	});
}

export function getCloudAccountSnapshot(): CloudAccountStatus | null {
	return get(cloudAccount);
}
