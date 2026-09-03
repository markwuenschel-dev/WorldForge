<script lang="ts">
	import Icon from '$lib/components/Icon.svelte';
	import { UserIcon, Login01Icon, AlertCircleIcon, ReloadIcon } from '@hugeicons/core-free-icons';
	import {
		cloudAccount,
		cloudAccountLoadState,
		cloudAccountError,
		formatTierLabel,
		userInitials,
		maskEmail,
		refreshCloudAccount
	} from '$lib/stores/cloudAccount.js';
	import { openSettings, hideEmail } from '$lib/stores/settings.js';
	import { neostackAuth, signOut, startSignIn, switchOrganization } from '$lib/stores/neostackAuth.js';
	import {
		fetchNeoStackOrgs,
		fetchNeoStackProjects,
		linkNeoStackProject,
		type NeoStackOrg,
		type NeoStackProject
	} from '$lib/bridge.js';
	import CustomSelect from '$lib/components/ui/custom-select/CustomSelect.svelte';

	let {
		variant = 'sidebar'
	}: {
		variant?: 'sidebar' | 'settings';
	} = $props();

	const isCompact = $derived(variant === 'sidebar');
	const account = $derived($cloudAccount);
	const connection = $derived(account?.connectionState ?? 'disconnected');
	// Entitlement tier (Lifetime / Subscription) — only meaningful when the
	// plan check landed on an entitled verdict.
	const tierLabel = $derived(
		account?.clientStatus === 'lifetime' || account?.clientStatus === 'subscription'
			? formatTierLabel(account.clientStatus)
			: ''
	);
	// Prefer the plan's display name from the entitlement payload.
	const planLabel = $derived(account?.planName || tierLabel || 'Free');
	const visibleEmail = $derived(
		account?.user?.email ? ($hideEmail ? maskEmail(account.user.email) : account.user.email) : ''
	);
	const displayName = $derived(account?.user?.name || visibleEmail || 'NeoStack account');
	const workspaceName = $derived(account?.organization?.name || account?.organization?.slug || '');
	const isConnected = $derived(
		connection === 'connected' ||
			(connection === 'offline' && (account?.user?.name || account?.user?.email))
	);

	// ── Acting organization ─────────────────────────────────────────────
	// The org every gateway request acts in. Displayed prominently because the
	// token silently pins whichever org was active at sign-in — acting in the
	// wrong org with no indication is the failure mode org switching exists
	// to kill (apps/gateway/docs/org-switching.md).
	let orgs = $state<NeoStackOrg[]>([]);
	let orgsError = $state('');
	let orgSwitching = $state(false);
	const activeOrgId = $derived($neostackAuth.activeOrgId ?? $neostackAuth.organizationId ?? '');
	const activeOrgName = $derived(
		orgs.find((o) => o.id === activeOrgId)?.name || workspaceName || activeOrgId
	);
	const orgOptions = $derived(orgs.map((o) => ({ value: o.id, label: o.name || o.slug })));

	$effect(() => {
		// Settings panel only, once signed in; re-runs after a switch lands so
		// the list stays fresh (cheap — one catalog read).
		if (variant !== 'settings' || $neostackAuth.status !== 'signedIn') return;
		fetchNeoStackOrgs().then((result) => {
			if (result.error) {
				orgsError = result.error;
			} else {
				orgsError = '';
				orgs = result.orgs ?? [];
			}
		});
	});

	async function handleOrgChange(orgId: string) {
		if (orgSwitching || !orgId || orgId === activeOrgId) return;
		orgSwitching = true;
		try {
			// C++ persists the choice, reconnects the gateway sockets, and
			// re-announces the device; running mirrored chats are released and
			// keep working locally as forks. State lands via the auth push.
			await switchOrganization(orgId);
		} finally {
			orgSwitching = false;
			// Projects are org-scoped — reload the link picker for the new org.
			void loadProjects();
		}
	}

	// ── Project link ────────────────────────────────────────────────────
	// The open UE project's workspace links to ONE web project by id — the
	// local folder name and the project name are unrelated, so a folder named
	// anything can link to any project in the active org. Linking retro-files
	// past sessions server-side.
	let projects = $state<NeoStackProject[]>([]);
	let currentProjectId = $state('');
	let workspaceRegistered = $state(true);
	let projectsError = $state('');
	let projectLinking = $state(false);
	const projectOptions = $derived([
		{ value: '', label: 'No project (group by folder name)' },
		...projects.map((p) => ({ value: p.id, label: p.name || p.slug }))
	]);

	async function loadProjects() {
		const result = await fetchNeoStackProjects();
		if (result.error) {
			projectsError = result.error;
			return;
		}
		projectsError = '';
		projects = result.projects ?? [];
		currentProjectId = result.currentProjectId ?? '';
		workspaceRegistered = result.workspaceRegistered ?? false;
	}

	$effect(() => {
		if (variant !== 'settings' || $neostackAuth.status !== 'signedIn') return;
		void loadProjects();
	});

	async function handleProjectChange(projectId: string) {
		if (projectLinking || projectId === currentProjectId) return;
		projectLinking = true;
		try {
			const result = await linkNeoStackProject(projectId);
			if (result.error) {
				projectsError = result.error;
			} else {
				projectsError = '';
				currentProjectId = projectId;
			}
		} finally {
			projectLinking = false;
		}
	}

	async function handleSignIn() {
		// Route through the shared store so every sign-in entry point shares
		// one flow, then refresh the account card once the session lands.
		const terminal = await startSignIn();
		if (terminal.status === 'signedIn') {
			await refreshCloudAccount();
		}
	}

	async function handleSignOut() {
		await signOut();
		await refreshCloudAccount();
	}
</script>

{#if isConnected}
	{#if isCompact}
		<button
			type="button"
			class="hover:bg-sidebar-accent/40 flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left transition-colors"
			title="Open account settings"
			onclick={() => openSettings('agents')}
		>
			{#if account?.user?.image}
				<img src={account.user.image} alt="" class="h-7 w-7 shrink-0 rounded-full object-cover" />
			{:else}
				<div
					class="bg-[var(--ue-accent)]/15 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold text-[var(--ue-accent)]"
				>
					{userInitials(account?.user?.name, account?.user?.email)}
				</div>
			{/if}
			<div class="min-w-0 flex-1 leading-tight">
				<p class="truncate text-[12px] font-medium text-foreground">{displayName}</p>
				<p class="text-muted-foreground/60 truncate text-[10.5px]">{planLabel}</p>
			</div>
			{#if connection === 'offline'}
				<span
					class="shrink-0 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-medium text-amber-400"
					title="Offline — showing last known account">offline</span
				>
			{/if}
		</button>
	{:else}
		<div class="border-border/60 bg-card/40 mb-4 rounded-lg border p-4">
			<div class="flex items-start gap-3">
				{#if account?.user?.image}
					<img
						src={account.user.image}
						alt=""
						class="h-10 w-10 shrink-0 rounded-full object-cover"
					/>
				{:else}
					<div
						class="bg-[var(--ue-accent)]/15 flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold text-[var(--ue-accent)]"
					>
						{userInitials(account?.user?.name, account?.user?.email)}
					</div>
				{/if}
				<div class="min-w-0 flex-1">
					<div class="flex items-start justify-between gap-2">
						<div class="min-w-0">
							<div class="flex items-center gap-1.5">
								<p class="truncate text-[14px] font-medium text-foreground">{displayName}</p>
								{#if connection === 'offline'}
									<span
										class="shrink-0 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-medium text-amber-400"
										title="Offline — showing last known account">offline</span
									>
								{/if}
							</div>
							{#if visibleEmail && visibleEmail !== displayName}
								<p class="text-muted-foreground/55 truncate text-[11.5px]">{visibleEmail}</p>
							{/if}
							{#if activeOrgName}
								<p class="text-muted-foreground/60 truncate text-[11.5px]">{activeOrgName}</p>
							{/if}
						</div>
						<button
							type="button"
							class="text-muted-foreground/40 shrink-0 rounded p-1 transition-colors hover:bg-accent hover:text-foreground"
							title="Refresh account"
							onclick={() => refreshCloudAccount()}
						>
							<Icon icon={ReloadIcon} size={14} strokeWidth={1.5} />
						</button>
					</div>
					<div class="mt-1.5 flex flex-wrap items-center gap-1.5">
						<span
							class="bg-[var(--ue-accent)]/10 rounded-full px-2 py-0.5 text-[10.5px] font-medium text-[var(--ue-accent)]"
							>{planLabel}</span
						>
						{#if tierLabel && tierLabel !== planLabel}
							<span class="text-muted-foreground/55 text-[10.5px]">{tierLabel}</span>
						{/if}
					</div>
					{#if $neostackAuth.status === 'signedIn'}
						<div class="mt-3">
							<p class="text-muted-foreground/50 mb-1 text-[10.5px] font-medium tracking-wide uppercase">
								Project
							</p>
							{#if projectsError}
								<p class="text-[11px] text-amber-400/80">{projectsError}</p>
							{:else if !workspaceRegistered}
								<p class="text-muted-foreground/55 text-[11px] leading-relaxed">
									Registering this Unreal project with NeoStack… linking unlocks in a
									moment.
								</p>
							{:else if projects.length === 0}
								<p class="text-muted-foreground/55 text-[11px] leading-relaxed">
									No projects in this organization yet — create one on the web
									dashboard, then pick it here.
								</p>
							{:else}
								<CustomSelect
									id="neostack-project-select"
									options={projectOptions}
									value={currentProjectId}
									onchange={handleProjectChange}
								/>
								{#if projectLinking}
									<p class="text-muted-foreground/55 mt-1 text-[10.5px]">Linking…</p>
								{:else}
									<p class="text-muted-foreground/45 mt-1 text-[10.5px] leading-relaxed">
										Files this Unreal project's chats under the selected web project —
										past chats included. Folder and project names don't need to match.
									</p>
								{/if}
							{/if}
						</div>
					{/if}
					{#if orgs.length > 1 || orgsError}
						<div class="mt-3">
							<p class="text-muted-foreground/50 mb-1 text-[10.5px] font-medium tracking-wide uppercase">
								Organization
							</p>
							{#if orgsError}
								<p class="text-[11px] text-amber-400/80">{orgsError}</p>
							{:else}
								<CustomSelect
									id="neostack-org-select"
									options={orgOptions}
									value={activeOrgId}
									onchange={handleOrgChange}
								/>
								{#if orgSwitching}
									<p class="text-muted-foreground/55 mt-1 text-[10.5px]">
										Switching — reconnecting to the new organization…
									</p>
								{:else}
									<p class="text-muted-foreground/45 mt-1 text-[10.5px] leading-relaxed">
										Sessions and devices are scoped to this organization. Running chats
										stay in the editor but stop syncing when you switch.
									</p>
								{/if}
							{/if}
						</div>
					{/if}
					<div class="mt-3 flex items-center gap-3 text-[11px]">
						<button
							type="button"
							class="text-muted-foreground/60 underline-offset-2 hover:text-foreground hover:underline"
							onclick={() => openSettings('usage')}>View usage</button
						>
						<button
							type="button"
							class="text-muted-foreground/50 underline-offset-2 hover:text-foreground hover:underline"
							onclick={handleSignOut}>Sign out</button
						>
					</div>
				</div>
			</div>
		</div>
	{/if}
{:else if connection === 'loading' || $cloudAccountLoadState === 'loading'}
	{#if isCompact}
		<div class="text-muted-foreground/60 flex items-center gap-2 px-1.5 py-1.5 text-[11.5px]">
			<div
				class="border-muted-foreground/20 border-t-muted-foreground/70 h-3 w-3 animate-spin rounded-full border-2"
			></div>
			<span>Checking NeoStack…</span>
		</div>
	{:else}
		<div
			class="border-border/60 bg-card/40 text-muted-foreground/60 mb-4 flex items-center gap-2 rounded-lg border px-4 py-3 text-[12px]"
		>
			<div
				class="border-muted-foreground/20 border-t-muted-foreground/70 h-3.5 w-3.5 animate-spin rounded-full border-2"
			></div>
			<span>Checking NeoStack Cloud…</span>
		</div>
	{/if}
{:else if isCompact}
	<button
		type="button"
		class="hover:bg-sidebar-accent/40 flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left transition-colors"
		onclick={handleSignIn}
	>
		<div
			class="bg-muted-foreground/10 text-muted-foreground/60 flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
		>
			<Icon icon={UserIcon} size={14} strokeWidth={1.5} />
		</div>
		<div class="min-w-0 flex-1 leading-tight">
			<p class="truncate text-[12px] font-medium text-foreground">
				{#if account?.isBinaryBuild}
					Sign in with NeoStack
				{:else}
					NeoStack Cloud
				{/if}
			</p>
			<p class="text-muted-foreground/55 truncate text-[10.5px]">
				{#if connection === 'offline'}
					Offline — tap to retry
				{:else}
					Not signed in
				{/if}
			</p>
		</div>
	</button>
{:else}
	<div class="border-border/60 bg-card/40 mb-4 flex flex-col gap-2 rounded-lg border p-4">
		<div class="flex items-start gap-2.5">
			<Icon
				icon={UserIcon}
				size={20}
				strokeWidth={1.5}
				class="text-muted-foreground/45 mt-0.5 shrink-0"
			/>
			<div class="min-w-0">
				<p class="text-[13px] font-medium text-foreground">
					{#if connection === 'offline'}
						Can't reach NeoStack Cloud
					{:else if account?.isBinaryBuild}
						Sign in with NeoStack
					{:else}
						NeoStack Cloud
					{/if}
				</p>
				<p class="text-muted-foreground/60 mt-0.5 text-[11.5px] leading-relaxed">
					{#if connection === 'offline'}
						Check your connection.
					{:else if account?.isBinaryBuild}
						Already bought NeoStack on Fab? Sign in so we can verify your lifetime access and enable
						cloud features.
					{:else}
						Sign in to track your plan and credits (optional for source builds).
					{/if}
				</p>
				{#if $cloudAccountError}
					<p class="mt-1 flex items-center gap-1 text-[11px] text-amber-400/80">
						<Icon icon={AlertCircleIcon} size={12} strokeWidth={1.5} />
						{$cloudAccountError}
					</p>
				{/if}
			</div>
		</div>
		<div class="flex flex-col gap-1.5">
			<button
				type="button"
				class="flex w-full items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors {account?.isBinaryBuild
					? 'bg-amber-500/15 text-amber-200 hover:bg-amber-500/25'
					: 'bg-[var(--ue-accent)] text-white hover:opacity-90'}"
				onclick={handleSignIn}
			>
				<Icon icon={Login01Icon} size={14} strokeWidth={2} />
				Sign in with NeoStack
			</button>
			{#if connection === 'offline' || account?.clientStatus === 'network'}
				<button
					type="button"
					class="text-muted-foreground/55 text-[11px] underline-offset-2 hover:text-foreground hover:underline"
					onclick={() => refreshCloudAccount()}>Retry</button
				>
			{/if}
		</div>
	</div>
{/if}
