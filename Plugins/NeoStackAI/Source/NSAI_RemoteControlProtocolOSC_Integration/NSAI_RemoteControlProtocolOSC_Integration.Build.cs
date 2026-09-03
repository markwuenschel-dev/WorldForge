using UnrealBuildTool;

public class NSAI_RemoteControlProtocolOSC_Integration : ModuleRules
{
    public NSAI_RemoteControlProtocolOSC_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI51_RCPOSC";
        string[] RequiredPlugins = new string[] { "RemoteControl", "RemoteControlProtocolOSC", "OSC" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_REMOTECONTROLPROTOCOLOSC_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "RemoteControlProtocolOSC",
            "OSC"
        });
    }
}
