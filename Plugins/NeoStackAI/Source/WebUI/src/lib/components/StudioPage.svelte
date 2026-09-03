<script lang="ts">
	import { onMount } from 'svelte';
	import Icon from '$lib/components/Icon.svelte';
	import {
		ArrowRight01Icon,
		Cancel01Icon,
		CubeIcon,
		Image02Icon,
		Loading03Icon,
		MusicNote01Icon
	} from '@hugeicons/core-free-icons';
	import {
		cancelJob,
		initializeStudio,
		jobs,
		loading,
		models,
		studioError,
		submitJob
	} from '$lib/stores/studio.js';
	import type { MediaField, MediaJob, MediaModel } from '$lib/bridge.js';

	let selected: MediaModel | null = $state(null);
	let filter = $state<'all' | MediaModel['kind']>('all');
	let values: Record<string, unknown> = $state({});
	let submitting = $state(false);
	let formError = $state('');

	let visibleModels = $derived(
		$models.filter((model) => filter === 'all' || model.kind === filter)
	);
	let activeCount = $derived(
		$jobs.filter((job) => ['submitting', 'queued', 'running'].includes(job.status)).length
	);

	onMount(() => {
		void initializeStudio();
	});

	function openModel(model: MediaModel) {
		selected = model;
		values = Object.fromEntries(
			model.fields
				.filter((field) => field.default !== undefined)
				.map((field) => [field.name, field.default])
		);
		formError = '';
	}

	function closeModel() {
		selected = null;
		values = {};
		formError = '';
	}

	function fieldValue(field: MediaField): string | number | boolean {
		return (values[field.name] as string | number | boolean | undefined) ?? field.default ?? '';
	}

	function setTextField(field: MediaField, raw: string) {
		if (field.type === 'string_array') {
			values[field.name] = raw
				.split('\n')
				.map((value) => value.trim())
				.filter(Boolean);
		} else {
			values[field.name] = raw;
		}
	}

	function textFieldValue(field: MediaField): string {
		const value = values[field.name] ?? field.default ?? '';
		return Array.isArray(value) ? value.join('\n') : String(value);
	}

	async function generate() {
		if (!selected || submitting) return;
		for (const field of selected.fields.filter((item) => item.required)) {
			const value = values[field.name];
			if (value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) {
				formError = `${field.name.replace(/_/g, ' ')} is required.`;
				return;
			}
		}
		submitting = true;
		formError = '';
		try {
			const error = await submitJob(selected.id, { ...values });
			if (error) formError = error;
			else closeModel();
		} finally {
			submitting = false;
		}
	}

	async function cancel(job: MediaJob) {
		const error = await cancelJob(job.id);
		if (error) studioError.set(error);
	}

	function iconFor(kind: MediaModel['kind']) {
		if (kind === 'image') return Image02Icon;
		if (kind === 'audio') return MusicNote01Icon;
		return CubeIcon;
	}

	function colorFor(kind: MediaModel['kind']): string {
		if (kind === 'image') return '#f59e0b';
		if (kind === 'audio') return '#ec4899';
		return '#8b5cf6';
	}

	function statusLabel(job: MediaJob): string {
		if (job.queue_position != null && job.status === 'queued') {
			return `${job.stage} · #${job.queue_position}`;
		}
		return job.stage || job.status;
	}

	function statusColor(status: MediaJob['status']): string {
		if (status === 'succeeded') return 'bg-emerald-400';
		if (status === 'failed') return 'bg-red-400';
		if (status === 'cancelled') return 'bg-muted-foreground/30';
		if (status === 'running') return 'bg-blue-400 animate-pulse';
		return 'bg-amber-400 animate-pulse';
	}

	function resultUrls(value: unknown): string[] {
		const urls = new Set<string>();
		function visit(item: unknown) {
			if (typeof item === 'string' && /^https?:\/\//.test(item)) urls.add(item);
			else if (Array.isArray(item)) item.forEach(visit);
			else if (item && typeof item === 'object') Object.values(item).forEach(visit);
		}
		visit(value);
		return [...urls];
	}

	function timeAgo(timestamp: string): string {
		const minutes = Math.floor((Date.now() - new Date(timestamp).getTime()) / 60000);
		if (minutes < 1) return 'just now';
		if (minutes < 60) return `${minutes}m ago`;
		if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
		return `${Math.floor(minutes / 1440)}d ago`;
	}
</script>

<div class="flex h-full w-full flex-col overflow-hidden bg-background">
	<header
		class="flex h-10 shrink-0 items-center justify-between border-b border-border bg-surface-bar px-4"
	>
		<div class="flex items-center gap-3">
			<h1 class="text-[13px] font-medium text-foreground">Studio</h1>
			<div class="bg-border/60 h-4 w-px"></div>
			{#each [{ id: 'all', label: 'All' }, { id: 'image', label: 'Images' }, { id: '3d', label: '3D' }, { id: 'audio', label: 'Audio' }] as item (item.id)}
				<button
					class="rounded-md px-2 py-1 text-[11px] font-medium {filter === item.id
						? 'bg-accent text-foreground'
						: 'text-muted-foreground hover:text-foreground'}"
					onclick={() => (filter = item.id as typeof filter)}>{item.label}</button
				>
			{/each}
		</div>
		<span class="text-muted-foreground/60 text-[11px]"
			>{activeCount} active · {$jobs.length} jobs</span
		>
	</header>

	<div class="min-h-0 flex-1 overflow-y-auto px-6 py-5">
		{#if $studioError}
			<div
				class="mx-auto mb-4 max-w-4xl rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-[12px] text-red-400"
			>
				{$studioError}
			</div>
		{/if}

		{#if $loading && $models.length === 0}
			<div
				class="text-muted-foreground/60 flex items-center justify-center gap-2 py-20 text-[13px]"
			>
				<Icon icon={Loading03Icon} size={16} class="animate-spin" /> Loading NeoStack Cloud…
			</div>
		{:else if selected}
			<div class="mx-auto max-w-2xl">
				<button
					class="text-muted-foreground/60 mb-5 flex items-center gap-1.5 text-[12px] hover:text-foreground"
					onclick={closeModel}
				>
					<span class="rotate-180"><Icon icon={ArrowRight01Icon} size={12} /></span> Back
				</button>
				<div class="border-border/60 bg-card/40 rounded-xl border p-6">
					<div class="mb-6 flex items-start gap-4">
						<div
							class="flex h-11 w-11 items-center justify-center rounded-xl"
							style="background-color: {colorFor(selected.kind)}15; color: {colorFor(
								selected.kind
							)}"
						>
							<Icon icon={iconFor(selected.kind)} size={22} />
						</div>
						<div>
							<h2 class="text-[16px] font-medium text-foreground">{selected.name}</h2>
							<p class="text-muted-foreground/60 text-[12px]">{selected.description}</p>
						</div>
					</div>

					{#each selected.fields as field (field.name)}
						<div class="mb-4">
							<div
								id={`studio-${field.name}`}
								class="text-muted-foreground/60 mb-1.5 text-[11px] font-medium uppercase tracking-wider"
							>
								{field.name.replace(/_/g, ' ')}{#if field.required}<span
										class="text-[var(--ue-accent)]"
									>
										*</span
									>{/if}
							</div>
							<p class="text-muted-foreground/40 mb-1.5 text-[10px]">{field.description}</p>
							{#if field.enum}
								<div
									class="flex flex-wrap gap-2"
									role="group"
									aria-labelledby={`studio-${field.name}`}
								>
									{#each field.enum as option (option)}
										<button
											class="rounded-lg border px-3 py-1.5 text-[11px] {fieldValue(field) === option
												? 'border-[var(--ue-accent)]/40 bg-[var(--ue-accent)]/10 text-foreground'
												: 'border-border/60 text-muted-foreground'}"
											onclick={() => (values[field.name] = option)}>{option}</button
										>
									{/each}
								</div>
							{:else if field.type === 'boolean'}
								<button
									class="rounded-lg border px-3 py-1.5 text-[11px] {fieldValue(field)
										? 'border-[var(--ue-accent)]/40 bg-[var(--ue-accent)]/10 text-foreground'
										: 'border-border/60 text-muted-foreground'}"
									onclick={() => (values[field.name] = !fieldValue(field))}
									>{fieldValue(field) ? 'Enabled' : 'Disabled'}</button
								>
							{:else if field.type === 'number' || field.type === 'integer'}
								<input
									aria-labelledby={`studio-${field.name}`}
									type="number"
									min={field.minimum}
									max={field.maximum}
									step={field.type === 'integer' ? 1 : 'any'}
									value={fieldValue(field)}
									oninput={(event) =>
										(values[field.name] = Number((event.currentTarget as HTMLInputElement).value))}
									class="border-border/60 w-full rounded-lg border bg-input px-3 py-2 text-[13px] text-foreground focus:outline-none"
								/>
							{:else if field.multiline || field.type === 'string_array'}
								<textarea
									aria-labelledby={`studio-${field.name}`}
									rows={field.type === 'string_array' ? 4 : 3}
									value={textFieldValue(field)}
									placeholder={field.type === 'string_array'
										? 'One URL per line'
										: 'Describe what you want to create…'}
									oninput={(event) =>
										setTextField(field, (event.currentTarget as HTMLTextAreaElement).value)}
									class="border-border/60 w-full resize-none rounded-lg border bg-input px-3 py-2.5 text-[13px] text-foreground focus:outline-none"
								></textarea>
							{:else}
								<input
									aria-labelledby={`studio-${field.name}`}
									value={textFieldValue(field)}
									oninput={(event) =>
										setTextField(field, (event.currentTarget as HTMLInputElement).value)}
									class="border-border/60 w-full rounded-lg border bg-input px-3 py-2 text-[13px] text-foreground focus:outline-none"
								/>
							{/if}
						</div>
					{/each}

					{#if formError}<p
							class="mb-3 rounded-lg bg-red-500/10 px-3 py-2 text-[12px] text-red-400"
						>
							{formError}
						</p>{/if}
					<button
						class="w-full rounded-lg bg-[var(--ue-accent)] px-4 py-2.5 text-[13px] font-medium text-white disabled:opacity-40"
						disabled={submitting}
						onclick={generate}
					>
						{#if submitting}<span class="flex items-center justify-center gap-2"
								><Icon icon={Loading03Icon} size={14} class="animate-spin" /> Submitting…</span
							>{:else}Generate{/if}
					</button>
				</div>
			</div>
		{:else}
			<div class="mx-auto max-w-4xl">
				<div class="mb-3 flex items-center gap-2">
					<span class="text-muted-foreground/50 text-[11px] font-semibold uppercase tracking-widest"
						>Models</span
					>
					<div class="bg-border/30 h-px flex-1"></div>
				</div>
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
					{#each visibleModels as model (model.id)}
						<button
							class="border-border/60 bg-card/40 hover:bg-card/80 group flex flex-col rounded-xl border p-4 text-left"
							onclick={() => openModel(model)}
						>
							<div class="mb-2.5 flex items-start justify-between">
								<div
									class="flex h-9 w-9 items-center justify-center rounded-lg"
									style="background-color: {colorFor(model.kind)}15; color: {colorFor(model.kind)}"
								>
									<Icon icon={iconFor(model.kind)} size={18} />
								</div>
								<Icon icon={ArrowRight01Icon} size={14} class="text-muted-foreground/40" />
							</div>
							<h3 class="mb-1 text-[13px] font-medium text-foreground">{model.name}</h3>
							<p class="text-muted-foreground/70 mb-3 line-clamp-2 text-[11px] leading-relaxed">
								{model.description}
							</p>
							<span class="text-muted-foreground/40 mt-auto text-[9px] uppercase tracking-wide"
								>{model.kind} · {model.action.replace(/_/g, ' ')}</span
							>
						</button>
					{/each}
				</div>

				{#if $jobs.length > 0}
					<div class="mb-3 mt-8 flex items-center gap-2">
						<span
							class="text-muted-foreground/50 text-[11px] font-semibold uppercase tracking-widest"
							>Background jobs</span
						>
						<div class="bg-border/30 h-px flex-1"></div>
					</div>
					<div class="space-y-2">
						{#each $jobs as job (job.id)}
							<div class="border-border/40 bg-card/30 rounded-lg border px-4 py-3">
								<div class="flex items-center gap-3">
									<span class="h-2 w-2 shrink-0 rounded-full {statusColor(job.status)}"></span>
									<div class="min-w-0 flex-1">
										<div class="truncate text-[12px] font-medium text-foreground">
											{$models.find((model) => model.id === job.model)?.name ?? job.model}
										</div>
										<div class="text-muted-foreground/55 truncate text-[10px]">
											{statusLabel(job)} · {timeAgo(job.created_at)}
										</div>
									</div>
									{#if job.progress != null && ['submitting', 'queued', 'running'].includes(job.status)}
										<div class="flex items-center gap-2">
											<div class="bg-secondary/60 h-1 w-20 overflow-hidden rounded-full">
												<div class="h-full bg-blue-400" style="width: {job.progress}%"></div>
											</div>
											<span class="text-[10px] text-blue-400">{job.progress}%</span>
										</div>
									{:else if ['submitting', 'queued', 'running'].includes(job.status)}
										<Icon icon={Loading03Icon} size={14} class="animate-spin text-blue-400" />
									{/if}
									{#if ['submitting', 'queued', 'running'].includes(job.status)}
										<button
											title="Cancel job"
											class="text-muted-foreground/50 rounded p-1 hover:text-red-400"
											onclick={() => cancel(job)}><Icon icon={Cancel01Icon} size={14} /></button
										>
									{/if}
								</div>
								{#if job.error}<p class="mt-2 text-[11px] text-red-400">{job.error}</p>{/if}
								{#if job.logs.at(-1)?.message}<p
										class="text-muted-foreground/45 mt-2 truncate text-[10px]"
									>
										{job.logs.at(-1)?.message}
									</p>{/if}
								{#if job.status === 'succeeded' && resultUrls(job.result).length > 0}
									<div class="mt-2 flex flex-wrap gap-2">
										{#each resultUrls(job.result) as url, index (url)}
											<a
												class="bg-[var(--ue-accent)]/10 rounded px-2 py-1 text-[10px] text-[var(--ue-accent)] hover:underline"
												href={url}
												target="_blank"
												rel="noreferrer">Result {index + 1}</a
											>
										{/each}
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>
