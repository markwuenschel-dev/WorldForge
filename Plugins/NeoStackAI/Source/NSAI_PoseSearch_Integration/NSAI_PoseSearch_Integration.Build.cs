// Copyright 2025-2026 Betide Studio. All Rights Reserved.

using UnrealBuildTool;
using System.IO;

public class NSAI_PoseSearch_Integration : ModuleRules
{
	public NSAI_PoseSearch_Integration(ReadOnlyTargetRules Target) : base(Target)
	{
		bUsePrecompiled = true;
        ShortName = "NSI44_PS";
        string[] RequiredPlugins = new string[] { "PoseSearch" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_POSESEARCH_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "Projects", "NeoStackAI" });
        if (!bWithIntegration)
        {
            return;
        }
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		// Lua and sol2 are exposed by the NeoStack AI core module as public includes.
		PrivateDefinitions.Add("LUA_BUILD_AS_DLL=1");

		// Core engine
		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core",
			"CoreUObject",
			"Engine"
		});

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			// Core AIK module (for FLuaBindingRegistry, FLuaSessionData, Lua lib symbols)
			"NeoStackAI",

			// Editor (FScopedTransaction, etc.)
			"UnrealEd",

			// PoseSearch
			"PoseSearch",
			"PoseSearchEditor",

			// Animation types used by PoseSearch binding
			"AnimGraphRuntime"
		});
	}
}
