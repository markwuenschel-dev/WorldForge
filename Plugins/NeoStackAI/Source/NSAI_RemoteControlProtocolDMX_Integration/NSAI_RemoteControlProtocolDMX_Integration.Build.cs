using UnrealBuildTool;

public class NSAI_RemoteControlProtocolDMX_Integration : ModuleRules
{
    public NSAI_RemoteControlProtocolDMX_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI49_RCPDMX";
        string[] RequiredPlugins = new string[] { "RemoteControl", "RemoteControlProtocolDMX", "DMXProtocol", "DMXEngine" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_REMOTECONTROLPROTOCOLDMX_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "RemoteControl",
            "RemoteControlProtocol",
            "RemoteControlProtocolDMX",
            "DMXProtocol",
            "DMXRuntime"
        });

        PrivateIncludePaths.AddRange(new string[] {
            System.IO.Path.Combine(EngineDirectory, "Plugins/VirtualProduction/RemoteControlProtocolDMX/Source/RemoteControlProtocolDMX/Internal")
        });
    }
}
