using UnrealBuildTool;
using System.IO;

public class NSAI_LiveLink_Integration : ModuleRules
{
    public NSAI_LiveLink_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI35_LL";
        string[] RequiredPlugins =
            Target.Version.MajorVersion == 5 && Target.Version.MinorVersion == 6
                ? new string[] { "LiveLink", "PerformanceCaptureWorkflow" }
                : new string[] { "LiveLink" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_LIVELINK_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "LiveLinkInterface",
            "LiveLink",
        });

        if (Target.Version.MajorVersion == 5 && Target.Version.MinorVersion == 6)
        {
            PrivateDependencyModuleNames.Add("PerformanceCaptureWorkflow");
            PrivateIncludePaths.Add(Path.Combine(
                EngineDirectory,
                "Plugins/VirtualProduction/PerformanceCaptureWorkflow/Source/PerformanceCaptureWorkflow/Private"
            ));
        }
    }
}
