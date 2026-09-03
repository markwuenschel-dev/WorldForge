using UnrealBuildTool;

public class NSAI_SceneStateDataLink_Integration : ModuleRules
{
    public NSAI_SceneStateDataLink_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI52_SSDL";
        string[] RequiredPlugins = new string[] { "SceneState", "AvalancheSceneState", "DataLink", "SceneStateDataLink" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_SCENESTATEDATALINK_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "Projects", "NeoStackAI" });
        if (!bWithIntegration)
        {
            return;
        }
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PrivateDefinitions.Add("LUA_BUILD_AS_DLL=1");

        PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
        PrivateDependencyModuleNames.AddRange(new string[] {
            "NeoStackAI",
            "UnrealEd",
            "AvalancheSceneState",
            "AvalancheSceneStateBlueprint",
            "DataLink",
            "SceneState",
            "SceneStateBinding",
            "SceneStateBlueprint",
            "SceneStateDataLink",
            "SceneStateMachineGraph",
            "SceneStateTasks"
        });
    }
}
