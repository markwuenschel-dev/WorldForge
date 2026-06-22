// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class WorldForgeCore : ModuleRules
{
	public WorldForgeCore(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		// Runtime contracts only. Keep this module game-agnostic and dependency-light
		// so it ships cleanly into any packaged game.
		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine"
		});

		PrivateDependencyModuleNames.AddRange(new string[] { });
	}
}
