// Copyright Epic Games, Inc. All Rights Reserved.
//
// See WorldForgeRuntimeIdentity.h for why this surface exists.
//
// Every value below is READ FROM THE ENGINE. Nothing is a literal describing what
// we believe to be true:
//   - ModuleName / LoadedModulePath  <- FModuleManager::QueryModule
//   - PluginName / PluginVersion     <- the plugin descriptor that actually
//                                       declares this module (discovered, not
//                                       hard-coded to "WorldForge")
//   - BuildIdentity                  <- this translation unit's compile stamp
//   - ContractVersion                <- a constant, which is the one thing that
//                                       SHOULD be a literal: it is the contract.
// A value the engine cannot supply stays empty.

#include "WorldForgeRuntimeIdentity.h"

#include "Modules/ModuleManager.h"
#include "Interfaces/IPluginManager.h"

namespace
{
	/** The module this file is compiled into. Kept as a single definition so the
	 *  identity always describes the binary that is actually executing this code,
	 *  not whatever module a caller might guess at. */
	const TCHAR* const GWorldForgeIdentityModuleName = TEXT("WorldForgeCore");

	/** Compile stamp of THIS translation unit.
	 *
	 *  __DATE__ and __TIME__ are adjacent string literals, so the preprocessor
	 *  concatenates them before ANSI_TO_TCHAR sees a single literal. Deliberately
	 *  NOT written as TEXT(__DATE__): UE's TEXT() pastes an `L` onto its argument,
	 *  and although the two-stage expansion happens to work, the intent is clearer
	 *  and the behaviour is unambiguous this way.
	 *
	 *  This value changes only when this .cpp is genuinely recompiled. That is the
	 *  property we want: if the editor reports a BuildIdentity older than the
	 *  build you just ran, the DLL was linked from a cached object file and your
	 *  source change never reached the binary. */
	FString MakeBuildIdentity()
	{
		return FString(ANSI_TO_TCHAR(__DATE__ " " __TIME__));
	}

	/**
	 * Find the plugin whose descriptor declares InModuleName.
	 *
	 * Deliberately NOT IPluginManager::GetModuleOwnerPlugin(): that method is
	 * inside `#if WITH_EDITOR` (IPluginManager.h:465-475), so it would compile out
	 * of a packaged game — and this plugin is meant to ship into one. Scanning the
	 * discovered plugins' descriptors works in every configuration and derives the
	 * answer from real descriptor data rather than assuming the plugin is called
	 * "WorldForge".
	 *
	 * Returns nullptr when no discovered plugin claims the module.
	 */
	TSharedPtr<IPlugin> FindOwningPlugin(const FName InModuleName)
	{
		IPluginManager& PluginManager = IPluginManager::Get();

		for (const TSharedRef<IPlugin>& Plugin : PluginManager.GetDiscoveredPlugins())
		{
			for (const FModuleDescriptor& ModuleDesc : Plugin->GetDescriptor().Modules)
			{
				if (ModuleDesc.Name == InModuleName)
				{
					return Plugin;
				}
			}
		}

		return nullptr;
	}
}

FWorldForgeRuntimeIdentity UWorldForgeIdentityStatics::GetWorldForgeRuntimeIdentity()
{
	FWorldForgeRuntimeIdentity Identity;

	// The contract version is compiled in; that is the whole point of it.
	Identity.ContractVersion = WF_RUNTIME_IDENTITY_CONTRACT_VERSION;
	Identity.BuildIdentity = MakeBuildIdentity();

	const FName ModuleName(GWorldForgeIdentityModuleName);

	// ---- module identity, straight from the module manager -------------------
	// QueryModule rather than GetModuleFilename: GetModuleFilename is compiled out
	// in monolithic builds (ModuleManager.h:508) and asserts on an unknown module,
	// whereas QueryModule always exists, returns false instead of crashing, and
	// hands back a path already run through ConvertRelativePathToFull
	// (ModuleManager.cpp:1700).
	FModuleStatus ModuleStatus;
	if (FModuleManager::Get().QueryModule(ModuleName, ModuleStatus))
	{
		Identity.ModuleName = ModuleStatus.Name;
		Identity.bIsModuleLoaded = ModuleStatus.bIsLoaded;

		// Empty in monolithic builds, where the engine never records a filename
		// (ModuleManager.cpp:456-458). Left empty rather than substituted, so the
		// far side can classify it as unsupported instead of trusting a guess.
		Identity.LoadedModulePath = ModuleStatus.FilePath;
	}
	else
	{
		// Self-contradictory in practice — this code IS that module — but reported
		// honestly rather than papered over with the name we "know" it has.
		Identity.ModuleName.Empty();
		Identity.bIsModuleLoaded = false;
		Identity.LoadedModulePath.Empty();
	}

	// ---- plugin identity, from the descriptor that declares the module -------
	if (const TSharedPtr<IPlugin> OwningPlugin = FindOwningPlugin(ModuleName))
	{
		Identity.PluginName = OwningPlugin->GetName();
		Identity.PluginVersion = OwningPlugin->GetDescriptor().VersionName;
	}
	else
	{
		Identity.PluginName.Empty();
		Identity.PluginVersion.Empty();
	}

	return Identity;
}
