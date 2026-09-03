using UnrealBuildTool;

public class NSAI_DynamicMaterial_Integration : ModuleRules
{
    public NSAI_DynamicMaterial_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI25_DM";
        string[] RequiredPlugins = new string[] { "DynamicMaterial" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_DYNAMICMATERIAL_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "DynamicMaterial",
            "DynamicMaterialEditor",
            "DynamicMaterialTextureSet",
            "DynamicMaterialTextureSetEditor",
            "Json",
            "JsonUtilities",
            "SlateCore",
            "UMG"
        });
    }
}
