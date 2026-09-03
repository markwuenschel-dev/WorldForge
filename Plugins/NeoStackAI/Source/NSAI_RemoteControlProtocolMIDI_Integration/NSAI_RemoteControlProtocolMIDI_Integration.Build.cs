using UnrealBuildTool;

public class NSAI_RemoteControlProtocolMIDI_Integration : ModuleRules
{
    public NSAI_RemoteControlProtocolMIDI_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI50_RCPMIDI";
        string[] RequiredPlugins = new string[] { "RemoteControl", "RemoteControlProtocolMIDI", "MIDIDevice" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_REMOTECONTROLPROTOCOLMIDI_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "RemoteControlProtocolMIDI",
            "MIDIDevice"
        });
    }
}
