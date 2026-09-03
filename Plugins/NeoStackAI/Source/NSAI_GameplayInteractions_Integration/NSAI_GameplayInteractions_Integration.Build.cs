using UnrealBuildTool;

public class NSAI_GameplayInteractions_Integration : ModuleRules
{
    public NSAI_GameplayInteractions_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI31_GI";
        string[] RequiredPlugins = new string[] { "GameplayInteractions" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_GAMEPLAYINTERACTIONS_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "GameplayInteractionsModule",
            "SmartObjectsModule",
            "StateTreeModule",
            "GameplayStateTreeModule",
        });
    }
}
