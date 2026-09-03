using UnrealBuildTool;
using System;
using System.IO;

public class NSAI_NDisplay_Integration : ModuleRules
{
    public NSAI_NDisplay_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI40_ND";
        string[] RequiredPlugins = new string[] { "nDisplay" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_NDISPLAY_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "Projects", "NeoStackAI" });
        if (!bWithIntegration)
        {
            return;
        }
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        // Lua and sol2 are exposed by the NeoStack AI core module as public includes.
        PrivateDefinitions.Add("LUA_BUILD_AS_DLL=1");
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
        PrivateDependencyModuleNames.AddRange(new string[] {
            "NeoStackAI",
            "UnrealEd",
        });

        // nDisplay has EnabledByDefault=false and is not supported on every
        // target platform. Detect the engine plugin by descriptor + module
        // source, not generated Intermediate headers that may not exist in a
        // clean source-engine install.
        string NDisplayPluginDir = Path.Combine(EngineDirectory, "Plugins", "Runtime", "nDisplay");
        if (IsNDisplaySupportedTarget(Target) &&
            File.Exists(Path.Combine(NDisplayPluginDir, "nDisplay.uplugin")) &&
            HasPluginModuleSource(NDisplayPluginDir, "DisplayCluster") &&
            HasPluginModuleSource(NDisplayPluginDir, "DisplayClusterConfiguration") &&
            HasPluginModuleSource(NDisplayPluginDir, "DisplayClusterConfigurator"))
        {
            PrivateDependencyModuleNames.Add("DisplayCluster");
            PrivateDependencyModuleNames.Add("DisplayClusterConfiguration");
            PrivateDependencyModuleNames.Add("DisplayClusterConfigurator");
        }
        else
        {
            PrivateDefinitions.Add("NSAI_NDISPLAY_DISABLED=1");
        }
    }

    private static bool IsNDisplaySupportedTarget(ReadOnlyTargetRules Target)
    {
        return Target.Platform == UnrealTargetPlatform.Win64 ||
            Target.Platform == UnrealTargetPlatform.Linux;
    }

    private static bool HasPluginModuleSource(string PluginDir, string ModuleName)
    {
        return File.Exists(Path.Combine(PluginDir, "Source", ModuleName, ModuleName + ".Build.cs"));
    }
}
