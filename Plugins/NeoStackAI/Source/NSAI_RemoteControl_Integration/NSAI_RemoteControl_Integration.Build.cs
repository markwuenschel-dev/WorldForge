using UnrealBuildTool;

public class NSAI_RemoteControl_Integration : ModuleRules
{
    public NSAI_RemoteControl_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI47_RC";
        string[] RequiredPlugins = new string[] { "RemoteControl", "StructUtils" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_REMOTECONTROL_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "RemoteControl",
            "RemoteControlCommon",
            "RemoteControlLogic",
            "StructUtils"
        });

        PublicDefinitions.Add("LUA_BUILD_AS_DLL=1");
    }
}
