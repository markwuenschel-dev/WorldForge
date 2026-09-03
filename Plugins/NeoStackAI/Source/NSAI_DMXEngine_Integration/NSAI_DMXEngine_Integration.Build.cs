using UnrealBuildTool;

public class NSAI_DMXEngine_Integration : ModuleRules
{
    public NSAI_DMXEngine_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI22_DMXE";
        string[] RequiredPlugins = new string[] { "DMXEngine", "DMXProtocol" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_DMXENGINE_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "DMXRuntime",
            "DMXProtocol"
        });

        PublicDefinitions.Add("LUA_BUILD_AS_DLL=1");
    }
}
