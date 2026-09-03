using UnrealBuildTool;

public class NSAI_DMXFixtures_Integration : ModuleRules
{
    public NSAI_DMXFixtures_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI23_DMXF";
        string[] RequiredPlugins = new string[] { "DMXFixtures" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_DMXFIXTURES_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "Projects", "NeoStackAI" });
        if (!bWithIntegration)
        {
            return;
        }
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "CoreUObject",
            "Engine",
            "NeoStackAI"
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "UnrealEd",
            "DMXFixtures",
            "DMXRuntime",
            "DMXProtocol",
            "ProceduralMeshComponent"
        });

        PublicDefinitions.Add("LUA_BUILD_AS_DLL=1");
    }
}
