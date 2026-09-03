using UnrealBuildTool;

public class NSAI_AvalancheSequence_Integration : ModuleRules
{
    public NSAI_AvalancheSequence_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI11_AS";
        string[] RequiredPlugins = new string[] { "Avalanche" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_AVALANCHESEQUENCE_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "AssetTools",
            "Avalanche",
            "AvalancheSequence",
            "AvalancheSequencer",
            "AvalancheTag",
            "LevelSequence",
            "MovieScene"
        });
    }
}
