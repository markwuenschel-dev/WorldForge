using UnrealBuildTool;
using System.IO;

public class NSAI_MovieRenderPipeline_Integration : ModuleRules
{
    public NSAI_MovieRenderPipeline_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI39_MRP";
        string[] RequiredPlugins = new string[] { "MovieRenderPipeline" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_MOVIERENDERPIPELINE_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "MovieRenderPipelineCore",
            "MovieRenderPipelineSettings",
            "MovieRenderPipelineRenderPasses",
            "MovieRenderPipelineEditor",
            "LevelSequence",
            "MovieScene",
        });

        if (Target.Version.MajorVersion > 5 || (Target.Version.MajorVersion == 5 && Target.Version.MinorVersion >= 6))
        {
            PrivateDependencyModuleNames.Add("MovieRenderPipelineMP4Encoder");
        }
    }
}
