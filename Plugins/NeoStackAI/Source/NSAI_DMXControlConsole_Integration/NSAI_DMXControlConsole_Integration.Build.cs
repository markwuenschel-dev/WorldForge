using UnrealBuildTool;

public class NSAI_DMXControlConsole_Integration : ModuleRules
{
    public NSAI_DMXControlConsole_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI21_DMXCC";
        string[] RequiredPlugins = new string[] { "DMXControlConsole" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_DMXCONTROLCONSOLE_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "DMXControlConsole",
            "DMXRuntime",
            "DMXProtocol",
            "DMXGDTF"
        });

        PrivateIncludePaths.AddRange(new string[]
        {
            System.IO.Path.Combine(EngineDirectory, "Plugins/VirtualProduction/DMX/DMXControlConsole/Source/DMXControlConsole/Internal"),
            System.IO.Path.Combine(EngineDirectory, "Plugins/VirtualProduction/DMX/DMXControlConsole/Source/DMXControlConsole/Private")
        });

        PublicDefinitions.Add("LUA_BUILD_AS_DLL=1");
    }
}
