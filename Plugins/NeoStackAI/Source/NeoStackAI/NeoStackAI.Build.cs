// Copyright 2025-2026 Betide Studio. All Rights Reserved.

using System;
using System.Collections.Generic;
using System.IO;
using EpicGames.Core;
using UnrealBuildTool;

public class NeoStackAI : ModuleRules
{
	public NeoStackAI(ReadOnlyTargetRules Target) : base(Target)
	{
		bUsePrecompiled = true;
		// Optional integrations still linked by core (no extension module for these yet)
		bool bWithCommonUI = IsOptionalPluginAvailable(Target, "CommonUI");

		// All other optional plugin dependencies have been moved to NSAI_* extension modules.
		// They are loaded at runtime when the backing plugin is available. The WITH_* defines
		// are kept as =0 so that #if guards in shared headers compile correctly in core.

		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		// Lua 5.4.7: public headers for consumers, src path for internal #includes in LuaAll.c
		string LuaIncludePath = Path.Combine(PluginDirectory, "Source", "ThirdParty", "Lua", "include");
		string LuaSrcPath = Path.Combine(PluginDirectory, "Source", "ThirdParty", "Lua", "src");
		PublicIncludePaths.Add(LuaIncludePath);
		PrivateIncludePaths.Add(LuaSrcPath);

		// sol2 v3.3.0: header-only C++ binding library
		string Sol2IncludePath = Path.Combine(PluginDirectory, "Source", "ThirdParty", "sol2", "include");
		PublicIncludePaths.Add(Sol2IncludePath);

		PublicDefinitions.Add("SOL_ALL_SAFETIES_ON=1");
		PublicDefinitions.Add("SOL_USING_CXX_LUA=0");
		PublicDefinitions.Add("SOL_PRINT_ERRORS=0");

		// Suppress C5321 (UTF-8 escape in sol2) — not available as a UBT property,
		// so we disable it via pragma in the sol2 wrapper header instead.

		// Lua symbol export: LUA_BUILD_AS_DLL is defined in LuaLib.c (not here) so it only
		// applies to the C translation unit that compiles Lua, not to C++ files in this module.
		// Extension modules define LUA_BUILD_AS_DLL in their Build.cs to get the import path.

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"Slate",
			"SlateCore",
			"InputCore",
			"Json",
			"JsonUtilities",
			"SQLiteCore",
			"HTTP",
			"HTTPServer",
			"RenderCore",
			"RHI",
			"Renderer"
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"UnrealEd",
			"EditorStyle",
			"ToolMenus",
			"WorkspaceMenuStructure",
			"Projects",
			"DeveloperSettings",
			"ApplicationCore",
			"EditorFramework",
			"EditorSubsystem",
			"GameProjectGeneration",
			// Blueprint tools dependencies
			"AssetTools",
			"AssetRegistry",
			"Kismet",
			"KismetCompiler",
			"BlueprintGraph",
			"UMG",
			"UMGEditor",
			// Core AI/Animation (always present — part of engine)
			"AIModule",
			"AIGraph",
			"AnimGraph",
			"AnimGraphRuntime",
			"MaterialEditor",
			"GraphEditor",
			"PhysicsCore",
			"PhysicsUtilities",
			// Context attachment dependencies
			"ContentBrowser",
			"DesktopPlatform",
			// Settings detail customization
			"PropertyEditor",
			// Actor detail panel extension (OnExtendActorDetails delegate)
			"DetailCustomizations",
			"ImageWrapper",
			"ImageCore",
			// WebBrowser for embedded web UI
			"WebBrowser",
			// WebSockets for relay client (remote editor access)
			"WebSockets",
			// Level Editor tab management (viewport activation)
			"LevelEditor",
			// Logging and diagnostics
			"MessageLog",
			// Behavior Tree editor graph support (BT runtime headers are in AIModule)
			"BehaviorTreeEditor",
			// SoundCue graph editor support
			"AudioEditor",
			// Level Sequence / Cinematics support
			"LevelSequence",
			"MovieScene",
			"MovieSceneTracks",
			"MovieSceneTextTrack",
			// FMovieSceneSequenceEditor — needed for director blueprint get/set
			"Sequencer",
			"AssetDefinition",
			// Asset management (UEditorAssetLibrary)
			"EditorScriptingUtilities",
			// Editor utility support (EditorUtilityBlueprint/Widget)
			"Blutility",
			// Clothing system (UClothingAssetBase for skeletal mesh clothing data)
			"ClothingSystemRuntimeInterface",
			// Level Design: Landscape + Foliage + Navigation
			"Landscape",
			"LandscapeEditor",
			"Foliage",
			"NavigationSystem",
			// Procedural noise (FractalBrownianMotionNoise for landscape generation)
			"GeometryCore",
			// Asset Collections support
			"CollectionManager",
			// Actor Merging / Proxy Mesh support
			"MeshMergeUtilities",
			// SkeletalMesh editor scripting surface (USkeletalMeshEditorSubsystem)
			"SkeletalMeshEditor",
			"SkeletalMeshUtilitiesCommon",
			// Settings discovery & plugin management
			"Settings",
			"StatusBar",
			// Localization workflow support
			"Localization",
			"LocalizationCommandletExecution",
			// Level Instance / Packed Level Actor editor support
			"LevelInstanceEditor",
			// Automation Testing support
			"AutomationController",
			"AutomationTest",
			"FunctionalTesting",
			// Replay System file management support
			"NetworkReplayStreaming",
			"LocalFileNetworkReplayStreaming",
			// GameplayTags (always present — core engine module)
			"GameplayTags",
			// Project indexing: file-change watcher for auto-index
			"DirectoryWatcher",
			// Asset drop target widget (SAssetDropTarget) for Content Browser drag-drop
			"EditorWidgets",
			// Loopback listener for the Clerk PKCE sign-in flow (NeoStackAuth)
			"Sockets",
		});

		// Niagara: moved to NSAI_Niagara extension module
		PublicDefinitions.Add("WITH_NIAGARA=0");

		// ControlRig: moved to NSAI_ControlRig extension module
		PublicDefinitions.Add("WITH_CONTROLRIG=0");

		// IKRig: moved to NSAI_IKRig extension module
		PublicDefinitions.Add("WITH_IKRIG=0");

		// MetaSound: moved to NSAI_MetaSound extension module
		PublicDefinitions.Add("WITH_METASOUND=0");

		// StateTree: moved to NSAI_StateTree extension module
		PublicDefinitions.Add("WITH_STATE_TREE=0");

		// Paper2D: moved to NSAI_Paper2D extension module
		PublicDefinitions.Add("WITH_PAPER2D=0");

		// EnhancedInput: moved to NSAI_EnhancedInput extension module
		PublicDefinitions.Add("WITH_ENHANCED_INPUT=0");

		// GameplayAbilities: moved to NSAI_GameplayAbilities extension module
		PublicDefinitions.Add("WITH_GAMEPLAY_ABILITIES=0");

		// SmartObjects: moved to NSAI_SmartObjects extension module
		PublicDefinitions.Add("WITH_SMART_OBJECTS=0");

		// Chooser: moved to NSAI_Chooser extension module
		PublicDefinitions.Add("WITH_CHOOSER=0");

		// Python: moved to NSAI_Python_Integration.
		PublicDefinitions.Add("WITH_PYTHON=0");

		// ChaosFracture: moved to NSAI_ChaosFracture extension module
		PublicDefinitions.Add("WITH_CHAOS_FRACTURE=0");

		// Interchange: moved to NSAI_Interchange extension module
		PublicDefinitions.Add("WITH_INTERCHANGE=0");

		// PCG: moved to NSAI_PCG extension module
		PublicDefinitions.Add("WITH_PCG=0");

		// EQS: moved to NSAI_EQS extension module
		PublicDefinitions.Add("WITH_EQS=0");

		// PoseSearch: moved to NSAI_PoseSearch extension module (loaded at runtime if PoseSearch is available)
		// WITH_POSE_SEARCH define kept for backward compat but always 0 in core module
		PublicDefinitions.Add("WITH_POSE_SEARCH=0");

		// Optional: CommonUI (set bWithCommonUI = false if unavailable)
		if (bWithCommonUI)
		{
			PrivateDependencyModuleNames.Add("CommonUI");
		}
		PublicDefinitions.Add("WITH_COMMON_UI=" + (bWithCommonUI ? "1" : "0"));

		// Water: moved to NSAI_Water extension module
		PublicDefinitions.Add("WITH_WATER=0");

		// Geometry Scripting: moved to NSAI_GeometryScripting extension module
		PublicDefinitions.Add("WITH_GEOMETRY_SCRIPTING=0");

		// nDisplay: moved to NSAI_NDisplay extension module
		PublicDefinitions.Add("WITH_NDISPLAY=0");

		// Dataflow: moved to NSAI_Dataflow extension module
		PublicDefinitions.Add("WITH_DATAFLOW=0");

		// MovieRenderPipeline: moved to NSAI_MovieRenderPipeline extension module
		PublicDefinitions.Add("WITH_MOVIE_RENDER_PIPELINE=0");

		// LiveLink: moved to NSAI_LiveLink extension module
		PublicDefinitions.Add("WITH_LIVE_LINK=0");

		// MetaHuman: moved to NSAI_MetaHuman extension module
		PublicDefinitions.Add("WITH_METAHUMAN=0");

		// MassAI: moved to NSAI_MassAI extension module
		PublicDefinitions.Add("WITH_MASS_AI=0");

		// Clothing system editor (clothing asset factory for creating/binding cloth from mesh sections)
		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"ClothingSystemRuntimeCommon",
			"ClothingSystemEditor"
		});

		// HLOD generation support (World Partition + Legacy)
		// WorldPartitionHLODUtilities is an editor plugin that may be absent on UE 5.5 or custom builds.
		// The HLOD binding only uses Engine-level headers (HLODBuilder.h, HLODActor.h, HLODLayer.h etc.)
		// so no C++ #if guard is needed — the plugin dependency just ensures builder classes are registered.
		bool bWithHLODUtilities = IsOptionalPluginAvailable(Target, "WorldPartitionHLODUtilities");
		if (bWithHLODUtilities)
		{
			PrivateDependencyModuleNames.Add("WorldPartitionHLODUtilities");
		}
		PublicDefinitions.Add("WITH_HLOD_UTILITIES=" + (bWithHLODUtilities ? "1" : "0"));

		// UE 5.8's ToolsetRegistry is Experimental + NoRedist. A direct module
		// dependency is stripped from Rocket/Fab packages, so the bridge uses
		// reflected Blueprint APIs at runtime and never links or redistributes it.
		bool bWithUEToolsetRegistry =
			Target.Version.MajorVersion > 5 ||
			(Target.Version.MajorVersion == 5 && Target.Version.MinorVersion >= 8);
		PublicDefinitions.Add("WITH_UE_TOOLSET_REGISTRY=" + (bWithUEToolsetRegistry ? "1" : "0"));

		// WorldPartitionEditor — needed for UWorldPartitionHLODEditorSubsystem (hlod_write_stats).
		PrivateDependencyModuleNames.Add("WorldPartitionEditor");

		// Source control integration (branch info, changelists UI)
		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"SourceControl",
			"SourceControlWindows"
		});

		// PKCE primitives (SHA-256 challenge + crypto-quality randomness) for
		// the Clerk sign-in flow (NeoStackAuth).
		AddEngineThirdPartyPrivateStaticDependencies(Target, "OpenSSL");

		// Live Coding support (Windows only)
		if (Target.Platform == UnrealTargetPlatform.Win64)
		{
			PrivateDependencyModuleNames.Add("LiveCoding");
			// DPAPI credential-at-rest encryption (CryptProtectData).
			PublicSystemLibraries.Add("Crypt32.lib");
		}

		// AppKit framework for clipboard image reading (macOS)
		if (Target.Platform == UnrealTargetPlatform.Mac)
		{
			PublicFrameworks.Add("AppKit");
			PublicFrameworks.Add("CoreText");
		}

		// libutil for forkpty() — PTY support for integrated terminal (macOS/Linux)
		if (Target.Platform == UnrealTargetPlatform.Mac || Target.Platform == UnrealTargetPlatform.Linux)
		{
			PublicSystemLibraries.Add("util");
		}

	}

	private bool IsOptionalPluginAvailable(ReadOnlyTargetRules Target, string PluginName)
	{
		return NeoStackIntegrationRules.ArePluginsAvailable(Target, new string[] { PluginName }, EngineDirectory);
	}

	private static bool IsPluginExplicitlyDisabled(ReadOnlyTargetRules Target, string PluginName)
	{
		foreach (string DisabledPlugin in Target.DisablePlugins)
		{
			if (DisabledPlugin.Equals(PluginName, StringComparison.OrdinalIgnoreCase))
			{
				return true;
			}
		}
		return false;
	}

	private bool IsPluginDescriptorAvailable(ReadOnlyTargetRules Target, string PluginName)
	{
		foreach (string CandidatePath in GetLikelyPluginDescriptorPaths(Target, PluginName))
		{
			if (File.Exists(CandidatePath))
			{
				return true;
			}
		}

		// Fallback for custom engine/plugin layouts.
		string EnginePluginsDir = Path.Combine(EngineDirectory, "Plugins");
		if (ContainsPluginDescriptorRecursive(EnginePluginsDir, PluginName))
		{
			return true;
		}

		if (Target.ProjectFile != null)
		{
			string ProjectDir = Path.GetDirectoryName(Target.ProjectFile.FullName);
			if (!string.IsNullOrEmpty(ProjectDir))
			{
				string ProjectPluginsDir = Path.Combine(ProjectDir, "Plugins");
				if (ContainsPluginDescriptorRecursive(ProjectPluginsDir, PluginName))
				{
					return true;
				}
			}
		}

		return false;
	}

	private IEnumerable<string> GetLikelyPluginDescriptorPaths(ReadOnlyTargetRules Target, string PluginName)
	{
		// Known engine plugin locations for optional dependencies we gate in this module.
		// Fast path — avoids recursive directory scan for common plugins.
		var KnownPaths = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
		{
			{ "PoseSearch",        Path.Combine("Animation", "PoseSearch", "PoseSearch.uplugin") },
			{ "CommonUI",          Path.Combine("Runtime", "CommonUI", "CommonUI.uplugin") },
			{ "nDisplay",          Path.Combine("Runtime", "nDisplay", "nDisplay.uplugin") },
			{ "Dataflow",          Path.Combine("Experimental", "Dataflow", "Dataflow.uplugin") },
			{ "ChaosOutfitAsset",  Path.Combine("Experimental", "ChaosOutfitAsset", "ChaosOutfitAsset.uplugin") },
			{ "Niagara",           Path.Combine("FX", "Niagara", "Niagara.uplugin") },
			{ "ControlRig",        Path.Combine("Animation", "ControlRig", "ControlRig.uplugin") },
			{ "IKRig",             Path.Combine("Animation", "IKRig", "IKRig.uplugin") },
			{ "Metasound",         Path.Combine("Runtime", "Metasound", "Metasound.uplugin") },
			{ "StateTree",         Path.Combine("Runtime", "StateTree", "StateTree.uplugin") },
			{ "Paper2D",           Path.Combine("2D", "Paper2D", "Paper2D.uplugin") },
			{ "EnhancedInput",     Path.Combine("EnhancedInput", "EnhancedInput.uplugin") },
			{ "GameplayAbilities", Path.Combine("Runtime", "GameplayAbilities", "GameplayAbilities.uplugin") },
			{ "SmartObjects",      Path.Combine("Runtime", "SmartObjects", "SmartObjects.uplugin") },
			{ "Chooser",           Path.Combine("Chooser", "Chooser.uplugin") },
			{ "PythonScriptPlugin", Path.Combine("Scripting", "PythonScriptPlugin", "PythonScriptPlugin.uplugin") },
			{ "Fracture",          Path.Combine("Experimental", "ChaosEditor", "Fracture.uplugin") },
			{ "Interchange",       Path.Combine("Interchange", "Runtime", "Interchange.uplugin") },
			{ "PCG",               Path.Combine("PCG", "PCG.uplugin") },
			{ "MovieRenderPipeline", Path.Combine("MovieScene", "MovieRenderPipeline", "MovieRenderPipeline.uplugin") },
			{ "LiveLink",          Path.Combine("Animation", "LiveLink", "LiveLink.uplugin") },
			{ "Water",             Path.Combine("Water", "Water.uplugin") },
			{ "MassGameplay",      Path.Combine("Runtime", "MassGameplay", "MassGameplay.uplugin") },
			{ "MassAI",            Path.Combine("AI", "MassAI", "MassAI.uplugin") },
			{ "MassCrowd",         Path.Combine("AI", "MassCrowd", "MassCrowd.uplugin") },
			{ "ZoneGraph",         Path.Combine("Runtime", "ZoneGraph", "ZoneGraph.uplugin") },
			{ "ToolsetRegistry",   Path.Combine("Experimental", "ToolsetRegistry", "ToolsetRegistry.uplugin") },
			// GeometryScripting moved to NSAI_GeometryScripting extension module
			{ "WorldPartitionHLODUtilities", Path.Combine("Editor", "WorldPartitionHLODUtilities", "WorldPartitionHLODUtilities.uplugin") },
		};

		if (KnownPaths.TryGetValue(PluginName, out string RelativePath))
		{
			yield return Path.Combine(EngineDirectory, "Plugins", RelativePath);
		}

		if (Target.ProjectFile != null)
		{
			string ProjectDir = Path.GetDirectoryName(Target.ProjectFile.FullName);
			if (!string.IsNullOrEmpty(ProjectDir))
			{
				yield return Path.Combine(ProjectDir, "Plugins", PluginName, $"{PluginName}.uplugin");
			}
		}
	}

	private static bool ContainsPluginDescriptorRecursive(string RootDir, string PluginName)
	{
		if (!Directory.Exists(RootDir))
		{
			return false;
		}

		try
		{
			string TargetFile = $"{PluginName}.uplugin";
			foreach (string _ in Directory.EnumerateFiles(RootDir, TargetFile, SearchOption.AllDirectories))
			{
				return true;
			}
		}
		catch (Exception)
		{
			return false;
		}

		return false;
	}

	private bool IsPluginModuleCompiled(ReadOnlyTargetRules Target, string ModuleName)
	{
		// Check if the module's generated headers exist (meaning the plugin was actually compiled/enabled).
		// Without this, we'd try to include headers that reference .generated.h files that don't exist.
		string[] PlatformDirs = { "Mac", "Win64", "Linux" };
		string[] ConfigDirs = { "UnrealEditor", "UnrealGame" };
		string EngineIntermediatePath = Path.Combine(EngineDirectory, "..", "Intermediate", "Build");
		foreach (string Platform in PlatformDirs)
		{
			foreach (string Config in ConfigDirs)
			{
				string GeneratedDir = Path.Combine(EngineIntermediatePath, Platform, Config, "Inc", ModuleName);
				if (Directory.Exists(GeneratedDir))
				{
					return true;
				}
			}
		}

		// Also check under the plugin's own Intermediate directory
		string PluginIntermediateBase = Path.Combine(EngineDirectory, "Plugins");
		try
		{
			string GeneratedHeader = $"{ModuleName}.init.gen.cpp";
			foreach (string _ in Directory.EnumerateFiles(PluginIntermediateBase, GeneratedHeader, SearchOption.AllDirectories))
			{
				return true;
			}
		}
		catch (Exception) { }

		return false;
	}
}

/// Shared availability gate used by every folded integration module. This is a
/// build-time source-availability check only; runtime enablement is handled by
/// FNeoStackIntegrationManager through IPluginManager::FindEnabledPlugin.
// Keep this internal. UE 5.5 compiles plugin rules once into the plugin rules
// assembly and again while composing HostProjectModuleRules; a public helper is
// then visible from both assemblies and produces CS0436 for every integration.
internal static class NeoStackIntegrationRules
{
	private static readonly Dictionary<string, bool> DescriptorCache =
		new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);

	public static bool ArePluginsAvailable(
		ReadOnlyTargetRules Target,
		IEnumerable<string> RequiredPlugins,
		string EngineDirectory)
	{
		foreach (string PluginName in RequiredPlugins)
		{
			if (IsExplicitlyDisabled(Target, PluginName)
				|| !IsDescriptorAvailable(Target, PluginName, EngineDirectory))
			{
				return false;
			}
		}
		return true;
	}

	private static bool IsExplicitlyDisabled(ReadOnlyTargetRules Target, string PluginName)
	{
		foreach (string DisabledPlugin in Target.DisablePlugins)
		{
			if (DisabledPlugin.Equals(PluginName, StringComparison.OrdinalIgnoreCase))
			{
				return true;
			}
		}
		return false;
	}

	private static bool IsDescriptorAvailable(ReadOnlyTargetRules Target, string PluginName, string EngineDirectory)
	{
		string ProjectDirectory = Target.ProjectFile == null
			? string.Empty
			: Path.GetDirectoryName(Target.ProjectFile.FullName);
		// Platform is part of the answer now (a descriptor can exist while every
		// module in it is disallowed on this platform), so it keys the cache too.
		string CacheKey = EngineDirectory + "|" + ProjectDirectory + "|" + PluginName + "|" + Target.Platform;
		lock (DescriptorCache)
		{
			if (DescriptorCache.TryGetValue(CacheKey, out bool CachedResult))
			{
				return CachedResult;
			}
		}

		string DescriptorPath = FindDescriptorBounded(
			Path.Combine(EngineDirectory, "Plugins"),
			PluginName + ".uplugin",
			8);
		if (DescriptorPath == null && !string.IsNullOrEmpty(ProjectDirectory))
		{
			DescriptorPath = FindDescriptorBounded(
				Path.Combine(ProjectDirectory, "Plugins"),
				PluginName + ".uplugin",
				6);
		}

		// Present AND usable: a plugin whose modules all exclude this platform
		// never produced generated headers or binaries here (e.g. MIDIDevice is
		// Win64/Mac only — including its headers on Linux is a guaranteed
		// compile error in installed builds).
		bool bAvailable = DescriptorPath != null
			&& DescriptorSupportsPlatform(DescriptorPath, Target.Platform.ToString());

		lock (DescriptorCache)
		{
			DescriptorCache[CacheKey] = bAvailable;
		}
		return bAvailable;
	}

	/** True when at least one module in the descriptor may build for `Platform`
	 *  (no Modules array counts as supported — content-only plugins). A module
	 *  counts when its PlatformAllowList (if any) contains the platform and its
	 *  PlatformDenyList (if any) does not. Unreadable descriptors fail open to
	 *  preserve the old exists-only behavior for exotic layouts. */
	private static bool DescriptorSupportsPlatform(string DescriptorPath, string Platform)
	{
		try
		{
			JsonObject Descriptor = JsonObject.Read(new FileReference(DescriptorPath));
			if (!Descriptor.TryGetObjectArrayField("Modules", out JsonObject[] Modules) || Modules.Length == 0)
			{
				return true;
			}
			foreach (JsonObject Module in Modules)
			{
				if (Module.TryGetStringArrayField("PlatformAllowList", out string[] AllowList)
					&& AllowList.Length > 0
					&& Array.FindIndex(AllowList, P => P.Equals(Platform, StringComparison.OrdinalIgnoreCase)) < 0)
				{
					continue;
				}
				if (Module.TryGetStringArrayField("PlatformDenyList", out string[] DenyList)
					&& Array.FindIndex(DenyList, P => P.Equals(Platform, StringComparison.OrdinalIgnoreCase)) >= 0)
				{
					continue;
				}
				return true;
			}
			return false;
		}
		catch (Exception)
		{
			return true;
		}
	}

	private static string FindDescriptorBounded(string Root, string DescriptorFileName, int MaxDepth)
	{
		if (!Directory.Exists(Root))
		{
			return null;
		}
		var Pending = new Stack<KeyValuePair<string, int>>();
		Pending.Push(new KeyValuePair<string, int>(Root, 0));
		while (Pending.Count > 0)
		{
			KeyValuePair<string, int> Current = Pending.Pop();
			try
			{
				string Candidate = Path.Combine(Current.Key, DescriptorFileName);
				if (File.Exists(Candidate))
				{
					return Candidate;
				}
				if (Current.Value >= MaxDepth)
				{
					continue;
				}
				foreach (string Child in Directory.EnumerateDirectories(Current.Key))
				{
					Pending.Push(new KeyValuePair<string, int>(Child, Current.Value + 1));
				}
			}
			catch (Exception)
			{
				// Inaccessible plugin roots are treated as unavailable.
			}
		}
		return null;
	}
}
