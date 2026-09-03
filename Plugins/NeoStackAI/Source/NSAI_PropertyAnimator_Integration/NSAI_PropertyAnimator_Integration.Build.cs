using UnrealBuildTool;

public class NSAI_PropertyAnimator_Integration : ModuleRules
{
    public NSAI_PropertyAnimator_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI45_PA";
        string[] RequiredPlugins = new string[] { "PropertyAnimator", "PropertyAnimatorCore", "AudioSynesthesia" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_PROPERTYANIMATOR_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "PropertyAnimatorCore",
            "PropertyAnimator",
            "AudioAnalyzer",
            "AudioSynesthesia"
        });
    }
}
