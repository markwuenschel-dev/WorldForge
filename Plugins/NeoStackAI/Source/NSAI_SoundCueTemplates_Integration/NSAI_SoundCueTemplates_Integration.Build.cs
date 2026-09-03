using UnrealBuildTool;

public class NSAI_SoundCueTemplates_Integration : ModuleRules
{
    public NSAI_SoundCueTemplates_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI54_SCT";
        string[] RequiredPlugins = new string[] { "SoundCueTemplates" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_SOUNDCUETEMPLATES_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "Projects", "NeoStackAI" });
        if (!bWithIntegration)
        {
            return;
        }
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PrivateDefinitions.Add("LUA_BUILD_AS_DLL=1");

        PublicDependencyModuleNames.AddRange(new string[] {
            "Core",
            "CoreUObject",
            "Engine"
        });

        PrivateDependencyModuleNames.AddRange(new string[] {
            "NeoStackAI",
            "AssetRegistry",
            "GameProjectGeneration",
            "UnrealEd",
            "SoundCueTemplates",
            "SoundCueTemplatesEditor"
        });
    }
}
