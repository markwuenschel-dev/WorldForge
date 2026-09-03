using UnrealBuildTool;

public class NSAI_AvalancheSceneState_Integration : ModuleRules
{
    public NSAI_AvalancheSceneState_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI10_ASS";
        string[] RequiredPlugins = new string[] { "Avalanche", "SceneState", "AvalancheSceneState" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_AVALANCHESCENESTATE_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "Avalanche",
            "AvalancheSceneState",
            "AvalancheSceneStateBlueprint",
            "BlueprintGraph",
            "PropertyBindingUtils",
            "SceneState",
            "SceneStateBinding",
            "SceneStateBlueprint",
            "SceneStateBlueprintEditor",
            "SceneStateEvent",
            "SceneStateGameplay",
            "SceneStateMachineGraph",
            "SceneStateTransitionGraph",
            "SceneStateTasks"
        });
    }
}
