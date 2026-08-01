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

		// "Projects" supplies IPluginManager / FPluginDescriptor, used by
		// WorldForgeRuntimeIdentity.cpp to read this plugin's real descriptor
		// instead of hard-coding its name and version.
		//
		// It must be listed explicitly: Engine and CoreUObject both depend on
		// Projects PRIVATELY (Engine.Build.cs:160, CoreUObject.Build.cs:42) and
		// Core does not reference it at all, so it is NOT inherited transitively.
		// Omitting it still compiles - the headers are reachable on the include
		// path - and then fails at link with unresolved PROJECTS_API symbols.
		//
		// Private, not Public: IPluginManager.h is included only from the .cpp, so
		// this keeps the module's public surface as dependency-light as before.
		// Projects is a Runtime module present in packaged games, so this does not
		// compromise shipping WorldForgeCore into an external target.
		PrivateDependencyModuleNames.AddRange(new string[] {
			"Projects"
		});
	}
}
