// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class WorldForgeEd : ModuleRules
{
	public WorldForgeEd(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		// Editor-only tooling. Nothing here ships in a packaged game.
		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"WorldForgeCore"
		});

		PrivateDependencyModuleNames.AddRange(new string[] {
			"Slate",
			"SlateCore",
			"UnrealEd",
			"AssetTools",
			"AssetRegistry"
		});
	}
}
