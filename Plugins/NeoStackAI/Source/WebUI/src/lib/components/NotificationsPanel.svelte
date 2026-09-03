<script lang="ts">
	import {
		getNotificationSettings,
		setNotificationSetting,
		type NotificationSettings
	} from '$lib/bridge.js';
	import { t } from '$lib/i18n.js';
	import { toast } from 'svelte-sonner';
	import SoundPicker from '$lib/components/SoundPicker.svelte';

	// ── State ──────────────────────────────────────────────────────────
	let settings = $state<NotificationSettings>({
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
	});
	let isLoading = $state(false);

	export async function load() {
		if (isLoading) return;
		isLoading = true;
		try {
			settings = await getNotificationSettings();
		} catch (e) {
			console.warn('Failed to load notification settings:', e);
		} finally {
			isLoading = false;
		}
	}

	type BooleanSettingKey =
		| 'onlyWhenUnfocused'
		| 'notifyOnComplete'
		| 'flashTaskbar'
		| 'playSound'
		| 'playPermissionSound';
	type VolumeSettingKey = 'soundVolume' | 'permissionSoundVolume';
	type SoundSettingKey = 'completionSound' | 'errorSound' | 'permissionRequestSound';

	function saveErrorToast(e: unknown) {
		toast.error($t('failed_to_save'), {
			description: e instanceof Error ? e.message : String(e)
		});
	}

	async function toggle(key: BooleanSettingKey, value: boolean) {
		const prev = settings[key];
		settings[key] = value;
		try {
			await setNotificationSetting(key, String(value));
		} catch (e) {
			console.warn('Failed to save notification setting:', e);
			settings[key] = prev;
			saveErrorToast(e);
		}
	}

	async function setVolume(key: VolumeSettingKey, value: number) {
		const prev = settings[key];
		settings[key] = value;
		try {
			await setNotificationSetting(key, String(value));
		} catch (e) {
			console.warn('Failed to save sound volume:', e);
			settings[key] = prev;
			saveErrorToast(e);
		}
	}

	async function setSound(key: SoundSettingKey, value: string) {
		const prev = settings[key];
		settings[key] = value;
		try {
			await setNotificationSetting(key, value);
		} catch (e) {
			console.warn('Failed to save sound:', e);
			settings[key] = prev;
			saveErrorToast(e);
		}
	}

	let volumePercent = $derived(Math.round(settings.soundVolume * 100));
	let permissionVolumePercent = $derived(Math.round(settings.permissionSoundVolume * 100));
</script>

<div class="mb-6">
	<h2 class="mb-1 text-[18px] font-medium text-foreground">{$t('tab_notifications')}</h2>
	<p class="text-muted-foreground/60 text-[13px]">{$t('notif_desc')}</p>
	<p class="text-muted-foreground/45 mt-1 text-[12px]">{$t('notif_permission_gate_note')}</p>
</div>

{#if isLoading}
	<div class="text-muted-foreground/50 flex items-center gap-2 py-8">
		<span
			class="border-muted-foreground/30 inline-block h-4 w-4 animate-spin rounded-full border-2 border-t-muted-foreground"
		></span>
		Loading...
	</div>
{:else}
	<!-- When to notify -->
	<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
		<h3 class="mb-3 text-[14px] font-medium text-foreground">{$t('notif_when_heading')}</h3>

		<label
			class="hover:bg-accent/20 flex cursor-pointer items-center justify-between rounded-md px-1 py-2.5 transition-colors"
		>
			<div>
				<span class="text-[13px] text-foreground">{$t('notif_only_unfocused')}</span>
				<p class="text-muted-foreground/50 mt-0.5 text-[11px]">{$t('notif_only_unfocused_desc')}</p>
			</div>
			<input
				type="checkbox"
				checked={settings.onlyWhenUnfocused}
				onchange={(e) => toggle('onlyWhenUnfocused', (e.currentTarget as HTMLInputElement).checked)}
				class="h-4 w-4 shrink-0 rounded border-border accent-[var(--ue-accent)]"
			/>
		</label>
	</div>

	<!-- Notification types -->
	<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
		<h3 class="mb-3 text-[14px] font-medium text-foreground">{$t('notif_types_heading')}</h3>

		<div class="flex flex-col">
			<!-- Editor toast -->
			<label
				class="hover:bg-accent/20 flex cursor-pointer items-center justify-between rounded-md px-1 py-2.5 transition-colors"
			>
				<div>
					<span class="text-[13px] text-foreground">{$t('notif_toast')}</span>
					<p class="text-muted-foreground/50 mt-0.5 text-[11px]">{$t('notif_toast_desc')}</p>
				</div>
				<input
					type="checkbox"
					checked={settings.notifyOnComplete}
					onchange={(e) =>
						toggle('notifyOnComplete', (e.currentTarget as HTMLInputElement).checked)}
					class="h-4 w-4 shrink-0 rounded border-border accent-[var(--ue-accent)]"
				/>
			</label>

			<!-- Taskbar flash -->
			<label
				class="hover:bg-accent/20 flex cursor-pointer items-center justify-between rounded-md px-1 py-2.5 transition-colors"
			>
				<div>
					<span class="text-[13px] text-foreground">{$t('notif_flash')}</span>
					<p class="text-muted-foreground/50 mt-0.5 text-[11px]">{$t('notif_flash_desc')}</p>
				</div>
				<input
					type="checkbox"
					checked={settings.flashTaskbar}
					onchange={(e) => toggle('flashTaskbar', (e.currentTarget as HTMLInputElement).checked)}
					class="h-4 w-4 shrink-0 rounded border-border accent-[var(--ue-accent)]"
				/>
			</label>

			<!-- Sound -->
			<label
				class="hover:bg-accent/20 flex cursor-pointer items-center justify-between rounded-md px-1 py-2.5 transition-colors"
			>
				<div>
					<span class="text-[13px] text-foreground">{$t('notif_sound')}</span>
					<p class="text-muted-foreground/50 mt-0.5 text-[11px]">{$t('notif_sound_desc')}</p>
				</div>
				<input
					type="checkbox"
					checked={settings.playSound}
					onchange={(e) => toggle('playSound', (e.currentTarget as HTMLInputElement).checked)}
					class="h-4 w-4 shrink-0 rounded border-border accent-[var(--ue-accent)]"
				/>
			</label>

			<!-- Permission / Ask User prompt sound -->
			<label
				class="hover:bg-accent/20 flex cursor-pointer items-center justify-between rounded-md px-1 py-2.5 transition-colors"
			>
				<div>
					<span class="text-[13px] text-foreground">{$t('notif_permission_sound')}</span>
					<p class="text-muted-foreground/50 mt-0.5 text-[11px]">
						{$t('notif_permission_sound_desc')}
					</p>
				</div>
				<input
					type="checkbox"
					checked={settings.playPermissionSound}
					onchange={(e) =>
						toggle('playPermissionSound', (e.currentTarget as HTMLInputElement).checked)}
					class="h-4 w-4 shrink-0 rounded border-border accent-[var(--ue-accent)]"
				/>
			</label>
		</div>
	</div>

	<!-- Volume slider (only when sound enabled) -->
	{#if settings.playSound}
		<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
			<h3 class="mb-3 text-[14px] font-medium text-foreground">{$t('notif_volume_heading')}</h3>
			<div class="flex items-center gap-3">
				<input
					type="range"
					min="0"
					max="1"
					step="0.05"
					value={settings.soundVolume}
					onchange={(e) =>
						setVolume('soundVolume', parseFloat((e.currentTarget as HTMLInputElement).value))}
					class="bg-border/60 h-1.5 flex-1 cursor-pointer appearance-none rounded-full accent-[var(--ue-accent)] [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-foreground"
				/>
				<span class="w-10 text-right text-[13px] text-muted-foreground">{volumePercent}%</span>
			</div>

			<div class="border-border/30 mt-4 border-t pt-3">
				<SoundPicker
					label="Completion sound"
					value={settings.completionSound}
					volume={settings.soundVolume}
					onchange={(v) => setSound('completionSound', v)}
				/>
				<SoundPicker
					label="Error sound"
					value={settings.errorSound}
					volume={settings.soundVolume}
					onchange={(v) => setSound('errorSound', v)}
				/>
			</div>
		</div>
	{/if}

	{#if settings.playPermissionSound}
		<div class="border-border/60 mb-4 rounded-lg border bg-card p-4">
			<h3 class="mb-3 text-[14px] font-medium text-foreground">
				{$t('notif_permission_volume_heading')}
			</h3>
			<div class="flex items-center gap-3">
				<input
					type="range"
					min="0"
					max="1"
					step="0.05"
					value={settings.permissionSoundVolume}
					onchange={(e) =>
						setVolume(
							'permissionSoundVolume',
							parseFloat((e.currentTarget as HTMLInputElement).value)
						)}
					class="bg-border/60 h-1.5 flex-1 cursor-pointer appearance-none rounded-full accent-[var(--ue-accent)] [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-foreground"
				/>
				<span class="w-10 text-right text-[13px] text-muted-foreground"
					>{permissionVolumePercent}%</span
				>
			</div>
			<div class="border-border/30 mt-4 border-t pt-3">
				<SoundPicker
					label="Permission request sound"
					value={settings.permissionRequestSound}
					volume={settings.permissionSoundVolume}
					onchange={(v) => setSound('permissionRequestSound', v)}
				/>
			</div>
		</div>
	{/if}
{/if}
