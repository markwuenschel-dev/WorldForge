using UnrealBuildTool;
using System.IO;

public class NSAI_Dataflow_Integration : ModuleRules
{
    public NSAI_Dataflow_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI18_D";
        string[] RequiredPlugins = new string[] { "Dataflow" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_DATAFLOW_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "DataflowCore",
            "DataflowEngine",
            "DataflowEditor",
        });

        string EngineDir = Path.GetFullPath(Target.RelativeEnginePath);
        string DataflowEditorPrivate = Path.Combine(EngineDir, "Plugins", "Dataflow", "Source", "DataflowEditor", "Private");
        if (Directory.Exists(DataflowEditorPrivate))
        {
            PrivateIncludePaths.Add(DataflowEditorPrivate);
        }
    }
}
