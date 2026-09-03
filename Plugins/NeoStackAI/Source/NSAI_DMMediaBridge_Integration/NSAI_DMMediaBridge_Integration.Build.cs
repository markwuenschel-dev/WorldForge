using UnrealBuildTool;

public class NSAI_DMMediaBridge_Integration : ModuleRules
{
    public NSAI_DMMediaBridge_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI20_DMMB";
        string[] RequiredPlugins = new string[] { "DynamicMaterial", "MediaStream", "DynamicMaterialMediaStreamBridge" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_DMMEDIABRIDGE_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "Json",
            "DynamicMaterial",
            "DynamicMaterialEditor",
            "MediaAssets",
            "MediaStream",
            "DynamicMaterialMediaStreamBridge"
        });
    }
}
