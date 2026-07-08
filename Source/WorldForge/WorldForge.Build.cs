// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class WorldForge : ModuleRules
{
	public WorldForge(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		// The host shell stays deliberately thin. It depends on the reusable
		// runtime contracts so a future game can consume them, and nothing else.
		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"WorldForgeCore",
			// v1.6y grounded traversal: navmesh probing + AI MoveTo bridge.
			"NavigationSystem",
			"AIModule"
		});

		PrivateDependencyModuleNames.AddRange(new string[] { });
	}
}
