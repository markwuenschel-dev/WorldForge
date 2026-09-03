using UnrealBuildTool;
using System.IO;

public class NSAI_AvalancheDataLink_Integration : ModuleRules
{
    public NSAI_AvalancheDataLink_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI09_ADL";
        string[] RequiredPlugins = new string[] { "Avalanche", "DataLink", "AvalancheDataLink" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_AVALANCHEDATALINK_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "Avalanche",
            "AvalancheDataLink",
            "AvalancheRemoteControl",
            "DataLink",
            "DataLinkEdGraph",
            "RemoteControl",
            "RemoteControlLogic"
        });

        if (Target.Version.MajorVersion == 5 && Target.Version.MinorVersion == 6)
        {
            PrivateIncludePaths.Add(Path.Combine(
                EngineDirectory,
                "Plugins/Experimental/AvalancheDataLink/Source/AvalancheDataLink/Private"
            ));
        }
    }
}
