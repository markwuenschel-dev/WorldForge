using UnrealBuildTool;

public class NSAI_Avalanche_Integration : ModuleRules
{
    public NSAI_Avalanche_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI08_A";
        string[] RequiredPlugins = new string[] { "Avalanche", "RemoteControl", "StructUtils" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_AVALANCHE_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "AssetRegistry",
            "UnrealEd",
            "Avalanche",
            "AvalancheAttribute",
            "AvalancheCamera",
            "AvalancheComponentVisualizers",
            "AvalancheMask",
            "AvalancheMedia",
            "AvalancheOutliner",
            "AvalancheRemoteControl",
            "AvalancheSceneTree",
            "AvalancheSceneRig",
            "AvalancheSceneRigEditor",
            "AvalancheSequence",
            "AvalancheSequencer",
            "AvalancheViewport",
            "AvalancheShapes",
            "AvalancheText",
            "AvalancheTag",
            "AvalancheTransition",
            "ActorModifierCore",
            "DynamicMesh",
            "GeometryCore",
            "GeometryMask",
            "GeometryFramework",
            "InputCore",
            "LevelSequence",
            "MediaIOCore",
            "MovieScene",
            "RemoteControl",
            "RemoteControlLogic",
            "Slate",
            "StructUtils",
            "Text3D"
        });
    }
}
