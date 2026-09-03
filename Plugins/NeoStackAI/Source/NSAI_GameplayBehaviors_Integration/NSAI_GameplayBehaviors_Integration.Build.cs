using UnrealBuildTool;

public class NSAI_GameplayBehaviors_Integration : ModuleRules
{
    public NSAI_GameplayBehaviors_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI29_GB";
        string[] RequiredPlugins = new string[] { "GameplayBehaviors", "GameplayAbilities" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_GAMEPLAYBEHAVIORS_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "Engine",
        });

        PrivateDependencyModuleNames.AddRange(new string[] {
            "NeoStackAI",
            "GameplayBehaviorsModule",
            "GameplayAbilities",
            "AIModule",
        });
    }
}
