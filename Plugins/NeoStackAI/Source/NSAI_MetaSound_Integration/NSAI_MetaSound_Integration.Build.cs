using UnrealBuildTool;

public class NSAI_MetaSound_Integration : ModuleRules
{
    public NSAI_MetaSound_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI38_MS";
        string[] RequiredPlugins = new string[] { "Metasound" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_METASOUND_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "UnrealEd",
            "AssetRegistry",
            "MetasoundEngine",
            "MetasoundFrontend",
            "MetasoundGenerator",
            "MetasoundGraphCore",
            "MetasoundStandardNodes",
            "MetasoundEditor"
        });
    }
}
