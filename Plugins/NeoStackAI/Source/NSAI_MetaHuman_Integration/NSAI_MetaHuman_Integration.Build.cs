using UnrealBuildTool;
using System;
using System.IO;

public class NSAI_MetaHuman_Integration : ModuleRules
{
    public NSAI_MetaHuman_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI37_MH";
        string[] RequiredPlugins = new string[] { "MetaHumanCharacter", "MetaHumanSDK", "MetaHuman", "MetaHumanCoreTech" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_METAHUMAN_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "Projects", "NeoStackAI" });
        if (!bWithIntegration)
        {
            return;
        }
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDefinitions.Add("SOL_ALL_SAFETIES_ON=1");
        PublicDefinitions.Add("SOL_USING_CXX_LUA=0");
        PublicDefinitions.Add("SOL_PRINT_ERRORS=0");
        PrivateDefinitions.Add("LUA_BUILD_AS_DLL=1");
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
        PrivateDependencyModuleNames.AddRange(new string[] {
            "NeoStackAI",
            "UnrealEd",
        });

        // Lua and sol2 are exposed by the NeoStack AI core module as public includes.

        // MetaHumanCharacter has EnabledByDefault=false. Detect modules by
        // descriptor + source Build.cs files, not generated Intermediate
        // headers that may not exist before the engine/plugin has been built.
        string MetaHumanPluginDir = Path.Combine(EngineDirectory, "Plugins", "MetaHuman", "MetaHumanCharacter");
        string MetaHumanSDKDir = Path.Combine(EngineDirectory, "Plugins", "MetaHuman", "MetaHumanSDK");
        string CoreTechDir = Path.Combine(EngineDirectory, "Plugins", "MetaHuman", "MetaHumanCoreTechLib");
        string AnimatorDir = Path.Combine(EngineDirectory, "Plugins", "MetaHuman", "MetaHumanAnimator");
        bool bHasMetaHumanCharacter =
            File.Exists(Path.Combine(MetaHumanPluginDir, "MetaHumanCharacter.uplugin")) &&
            HasPluginModuleSource(MetaHumanPluginDir, "MetaHumanCharacter") &&
            HasPluginModuleSource(MetaHumanPluginDir, "MetaHumanCharacterEditor") &&
            HasPluginModuleSource(MetaHumanPluginDir, "MetaHumanCharacterPalette") &&
            HasPluginModuleSource(MetaHumanPluginDir, "MetaHumanCharacterPaletteEditor") &&
            HasPluginModuleSource(MetaHumanSDKDir, "MetaHumanSDKRuntime") &&
            HasPluginModuleSource(MetaHumanSDKDir, "MetaHumanSDKEditor") &&
            HasPluginModuleSource(CoreTechDir, "MetaHumanCoreTechLib");

        if (bHasMetaHumanCharacter)
        {
            PrivateDependencyModuleNames.AddRange(new string[] {
                "MetaHumanCharacter",
                "MetaHumanSDKRuntime",
                "MetaHumanSDKEditor",
                "MetaHumanCharacterEditor",
                "MetaHumanCharacterPalette",
                "MetaHumanCharacterPaletteEditor",
                "MetaHumanCoreTechLib",
            });

            // MetaHumanIdentity (under MetaHumanAnimator plugin) for ImportFromIdentity
            if (HasPluginModuleSource(AnimatorDir, "MetaHumanIdentity"))
            {
                PrivateDependencyModuleNames.Add("MetaHumanIdentity");
            }
        }
        else
        {
            PrivateDefinitions.Add("NSAI_METAHUMAN_DISABLED=1");
        }
    }

    private static bool HasPluginModuleSource(string PluginDir, string ModuleName)
    {
        return File.Exists(Path.Combine(PluginDir, "Source", ModuleName, ModuleName + ".Build.cs"));
    }
}
