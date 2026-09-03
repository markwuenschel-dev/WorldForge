<script lang="ts">
	import { onMount } from 'svelte';
	import Icon from '$lib/components/Icon.svelte';
	import NeoStackSignInButton from '$lib/components/NeoStackSignInButton.svelte';
	import SetupChecklist from '$lib/components/SetupChecklist.svelte';
	import {
		SparklesIcon,
		Settings02Icon,
		ArrowRight01Icon,
		Globe02Icon,
		CheckmarkCircle02Icon,
		MessageMultiple01Icon
	} from '@hugeicons/core-free-icons';
	import {
		skipOnboarding,
		completeOnboarding,
		completeLanguageStep,
		goNext,
		goBack,
		onboardingStep,
		selectedSubscriptions,
		recommendedAgentId,
		alternativeAgentIds,
		subscriptionOptions,
		toggleSubscription,
		isLanguageOnlyFlow
	} from '$lib/stores/onboarding.js';
	import {
		locale,
		locales,
		localeNames,
		setLocale,
		matchOsLanguageToLocale,
		type Locale
	} from '$lib/i18n.js';
	import { getDefaultLanguage } from '$lib/bridge.js';

	// ── Language step state ─────────────────────────────────────────
	let detectedLocale: Locale | null = $state(null);
	let pickedLocale: Locale = $state($locale);

	onMount(async () => {
		const osLang = await getDefaultLanguage();
		const matched = matchOsLanguageToLocale(osLang);
		if (matched) {
			detectedLocale = matched;
			// Pre-select the detected locale (but don't apply yet — user must Continue)
			pickedLocale = matched;
		}
	});

	function handleLocaleClick(loc: Locale) {
		pickedLocale = loc;
	}

	async function handleLanguageContinue() {
		setLocale(pickedLocale);
		await completeLanguageStep();
	}

	// ── Recommendation display ──────────────────────────────────────
	const agentDisplayNames: Record<string, string> = {
		'claude-acp': 'Claude Code',
		'codex-acp': 'OpenAI Codex',
		gemini: 'Gemini',
		'github-copilot-cli': 'GitHub Copilot CLI',
		cursor: 'Cursor Agent'
	};

	function displayName(registryId: string): string {
		return agentDisplayNames[registryId] || registryId;
	}

	let installing = $state(false);

	async function handleGetStarted() {
		if (installing) return;
		const id = $recommendedAgentId;
		if (!id) return;
		installing = true;
		try {
			await completeOnboarding(id);
		} finally {
			installing = false;
		}
	}

	// ── Progress indicator ──────────────────────────────────────────
	// Steps shown in dots: language, welcome, subs, reco. Hidden in language-only flow.
	const stepOrder = ['language', 'welcome', 'subscriptions', 'recommendation'] as const;
	const currentStepIndex = $derived(stepOrder.indexOf($onboardingStep));
</script>

<div class="flex flex-1 flex-col items-center justify-center px-6">
	<!-- Progress dots (hidden in language-only flow) -->
	{#if !$isLanguageOnlyFlow}
		<div class="mb-8 flex items-center gap-1.5">
			{#each stepOrder as step, idx (step)}
				{@const state =
					idx === currentStepIndex ? 'current' : idx < currentStepIndex ? 'done' : 'pending'}
				<div
					class="h-1.5 rounded-full transition-all duration-300 {state === 'current'
						? 'bg-foreground/80 w-6'
						: state === 'done'
							? 'bg-foreground/40 w-1.5'
							: 'w-1.5 bg-border'}"
				></div>
			{/each}
		</div>
	{/if}

	{#if $onboardingStep === 'language'}
		<!-- ─────────────────── Step 1: Language ─────────────────── -->
		<div class="flex w-full max-w-2xl flex-col items-center gap-8">
			<div class="relative flex items-center justify-center">
				<div
					class="from-sky-500/8 to-violet-500/8 absolute h-24 w-24 rounded-full bg-gradient-to-br blur-xl"
				></div>
				<div
					class="border-border/30 bg-card/40 relative flex h-20 w-20 items-center justify-center rounded-2xl border shadow-lg shadow-black/20 backdrop-blur-sm"
				>
					<Icon icon={Globe02Icon} size={36} strokeWidth={1.2} class="text-foreground/50" />
				</div>
			</div>

			<div class="flex flex-col items-center gap-3 text-center">
				<h1 class="text-foreground/90 text-[22px] font-semibold tracking-tight">
					Choose your language
				</h1>
				<p class="text-muted-foreground/60 max-w-md text-[13.5px] leading-relaxed">
					{#if detectedLocale}
						We detected your system language. You can change it any time in Settings.
					{:else}
						Pick the language you'd like NeoStack AI to use.
					{/if}
				</p>
			</div>

			<!-- Locale grid -->
			<div class="grid w-full grid-cols-2 gap-2 sm:grid-cols-3">
				{#each locales as loc (loc)}
					{@const isPicked = pickedLocale === loc}
					{@const isDetected = detectedLocale === loc}
					<button
						type="button"
						onclick={() => handleLocaleClick(loc)}
						class="bg-card/40 text-foreground/80 group relative flex items-center justify-between rounded-xl border px-4 py-3 text-left text-[13.5px] transition-all {isPicked
							? 'border-[var(--ue-accent)] bg-card text-foreground'
							: 'hover:bg-card/70 border-border hover:border-[var(--ue-accent-muted)]'}"
					>
						<span class="font-medium">{localeNames[loc]}</span>
						{#if isPicked}
							<Icon
								icon={CheckmarkCircle02Icon}
								size={16}
								strokeWidth={2}
								class="text-[var(--ue-accent)]"
							/>
						{:else if isDetected}
							<span
								class="bg-[var(--ue-accent)]/15 rounded-md px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--ue-accent)]"
							>
								Detected
							</span>
						{/if}
					</button>
				{/each}
			</div>

			<div class="flex flex-col items-center gap-3">
				<button
					class="group flex items-center gap-2 rounded-xl bg-[var(--ue-accent)] px-7 py-2.5 text-[14px] font-medium text-white transition-all hover:opacity-90"
					onclick={handleLanguageContinue}
				>
					Continue
					<Icon
						icon={ArrowRight01Icon}
						size={16}
						strokeWidth={2}
						class="transition-transform group-hover:translate-x-0.5"
					/>
				</button>
				{#if $isLanguageOnlyFlow}
					<button
						class="text-muted-foreground/40 hover:text-muted-foreground/70 text-[12px] transition-colors"
						onclick={skipOnboarding}
					>
						Skip
					</button>
				{/if}
			</div>
		</div>
	{:else if $onboardingStep === 'welcome'}
		<!-- ─────────────────── Step 2: Welcome ─────────────────── -->
		<div class="flex w-full max-w-3xl flex-col items-center gap-8">
			<div class="relative flex items-center justify-center">
				<div
					class="from-violet-500/8 to-amber-500/8 absolute h-24 w-24 rounded-full bg-gradient-to-br blur-xl"
				></div>
				<div
					class="border-border/30 bg-card/40 relative flex h-20 w-20 items-center justify-center rounded-2xl border shadow-lg shadow-black/20 backdrop-blur-sm"
				>
					<Icon icon={SparklesIcon} size={36} strokeWidth={1.2} class="text-foreground/50" />
				</div>
			</div>

			<div class="flex flex-col items-center gap-3 text-center">
				<h1 class="text-foreground/90 text-[22px] font-semibold tracking-tight">
					Welcome to NeoStack AI
				</h1>
				<p class="text-muted-foreground/60 max-w-xs text-[13.5px] leading-relaxed">
					Connect AI coding agents to Unreal Engine. We'll guide you through the few checks needed
					for a first successful chat.
				</p>
			</div>

			<div class="w-full">
				<SetupChecklist />
			</div>

			<div class="flex flex-col items-center gap-3">
				<button
					class="group flex items-center gap-2 rounded-xl bg-[var(--ue-accent)] px-7 py-2.5 text-[14px] font-medium text-white transition-all hover:opacity-90"
					onclick={goNext}
				>
					<Icon icon={Settings02Icon} size={16} strokeWidth={1.5} />
					Get Started
					<Icon
						icon={ArrowRight01Icon}
						size={16}
						strokeWidth={2}
						class="transition-transform group-hover:translate-x-0.5"
					/>
				</button>
				<button
					class="text-muted-foreground/40 hover:text-muted-foreground/70 text-[12px] transition-colors"
					onclick={skipOnboarding}
				>
					Skip for now
				</button>
			</div>
		</div>
	{:else if $onboardingStep === 'subscriptions'}
		<!-- ─────────────── Step 3: Subscriptions ─────────────── -->
		<div class="flex w-full max-w-2xl flex-col items-center gap-8">
			<div class="relative flex items-center justify-center">
				<div
					class="from-emerald-500/8 to-sky-500/8 absolute h-24 w-24 rounded-full bg-gradient-to-br blur-xl"
				></div>
				<div
					class="border-border/30 bg-card/40 relative flex h-20 w-20 items-center justify-center rounded-2xl border shadow-lg shadow-black/20 backdrop-blur-sm"
				>
					<Icon
						icon={MessageMultiple01Icon}
						size={36}
						strokeWidth={1.2}
						class="text-foreground/50"
					/>
				</div>
			</div>

			<div class="flex flex-col items-center gap-3 text-center">
				<h1 class="text-foreground/90 text-[22px] font-semibold tracking-tight">
					What AI services do you have?
				</h1>
				<p class="text-muted-foreground/60 max-w-md text-[13.5px] leading-relaxed">
					Select all that apply. We'll recommend the agent that fits best — you can always add more
					later.
				</p>
			</div>

			<!-- Quickest path: sign in with NeoStack in the browser. -->
			<div
				class="border-border/40 bg-card/30 flex w-full flex-col items-center gap-3 rounded-2xl border p-5"
			>
				<div class="flex flex-col items-center gap-1 text-center">
					<span class="text-foreground/90 text-[13.5px] font-medium">
						Quickest start: sign in with NeoStack
					</span>
					<span class="text-muted-foreground/70 text-[12px]">
						One click — sign in with your browser and the editor connects to your account. You can
						still pick services below or skip ahead.
					</span>
				</div>
				<NeoStackSignInButton label="Sign in with NeoStack" variant="primary" onsuccess={goNext} />
			</div>

			<div class="grid w-full grid-cols-1 gap-2 sm:grid-cols-2">
				{#each subscriptionOptions as opt (opt.id)}
					{@const isSelected = $selectedSubscriptions.has(opt.id)}
					<button
						type="button"
						onclick={() => toggleSubscription(opt.id)}
						class="bg-card/40 group flex items-start justify-between gap-3 rounded-xl border px-4 py-3 text-left transition-all {isSelected
							? 'border-[var(--ue-accent)] bg-card'
							: 'hover:bg-card/70 border-border hover:border-[var(--ue-accent-muted)]'}"
					>
						<div class="flex flex-col gap-0.5">
							<span class="text-[13.5px] font-medium text-foreground">{opt.label}</span>
							<span class="text-muted-foreground/60 text-[12px]">{opt.sublabel}</span>
						</div>
						{#if isSelected}
							<Icon
								icon={CheckmarkCircle02Icon}
								size={18}
								strokeWidth={2}
								class="mt-0.5 shrink-0 text-[var(--ue-accent)]"
							/>
						{/if}
					</button>
				{/each}
			</div>

			<div class="flex items-center gap-3">
				<button
					class="text-muted-foreground/60 text-[13px] transition-colors hover:text-foreground"
					onclick={goBack}
				>
					Back
				</button>
				<button
					class="group flex items-center gap-2 rounded-xl bg-[var(--ue-accent)] px-7 py-2.5 text-[14px] font-medium text-white transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
					disabled={$selectedSubscriptions.size === 0}
					onclick={goNext}
				>
					Continue
					<Icon
						icon={ArrowRight01Icon}
						size={16}
						strokeWidth={2}
						class="transition-transform group-hover:translate-x-0.5"
					/>
				</button>
			</div>
		</div>
	{:else if $onboardingStep === 'recommendation'}
		<!-- ────────────── Step 4: Recommendation ────────────── -->
		<div class="flex w-full max-w-md flex-col items-center gap-8">
			<div class="relative flex items-center justify-center">
				<div
					class="from-amber-500/8 to-emerald-500/8 absolute h-24 w-24 rounded-full bg-gradient-to-br blur-xl"
				></div>
				<div
					class="border-border/30 bg-card/40 relative flex h-20 w-20 items-center justify-center rounded-2xl border shadow-lg shadow-black/20 backdrop-blur-sm"
				>
					<Icon
						icon={CheckmarkCircle02Icon}
						size={36}
						strokeWidth={1.2}
						class="text-foreground/50"
					/>
				</div>
			</div>

			<div class="flex flex-col items-center gap-3 text-center">
				<p class="text-muted-foreground/50 text-[12px] uppercase tracking-wider">We recommend</p>
				<h1 class="text-[26px] font-semibold tracking-tight text-foreground">
					{displayName($recommendedAgentId)}
				</h1>
				<p class="text-muted-foreground/60 max-w-xs text-[13.5px] leading-relaxed">
					{#if $alternativeAgentIds.length > 0}
						We'll also install {$alternativeAgentIds.map(displayName).join(', ')} so you can switch any
						time.
					{:else}
						Best fit for what you've selected. You can install more agents later from Settings.
					{/if}
				</p>
			</div>

			<div class="flex items-center gap-3">
				<button
					class="text-muted-foreground/60 text-[13px] transition-colors hover:text-foreground"
					onclick={goBack}
				>
					Back
				</button>
				<button
					class="group flex items-center gap-2 rounded-xl bg-[var(--ue-accent)] px-7 py-2.5 text-[14px] font-medium text-white transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
					disabled={installing}
					onclick={handleGetStarted}
				>
					{installing ? 'Installing…' : 'Install & Get Started'}
					<Icon
						icon={ArrowRight01Icon}
						size={16}
						strokeWidth={2}
						class="transition-transform group-hover:translate-x-0.5"
					/>
				</button>
			</div>
		</div>
	{/if}
</div>
