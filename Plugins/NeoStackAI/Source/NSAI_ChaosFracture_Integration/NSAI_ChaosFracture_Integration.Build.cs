using UnrealBuildTool;
using System.IO;

public class NSAI_ChaosFracture_Integration : ModuleRules
{
    public NSAI_ChaosFracture_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI13_CF";
        string[] RequiredPlugins = new string[] { "Fracture", "Dataflow" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_CHAOSFRACTURE_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "FractureEngine",
            "GeometryCollectionEngine",
            "ChaosSolverEngine",
            "Chaos",
            "DataflowCore",
            "DataflowEngine",
            "DataflowEditor",
        });
    }
}
