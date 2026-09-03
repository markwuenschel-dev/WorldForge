using UnrealBuildTool;
using System.IO;

public class NSAI_ControlRig_Integration : ModuleRules
{
    public NSAI_ControlRig_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI17_CR";
        string[] RequiredPlugins = new string[] { "ControlRig", "RigVM" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_CONTROLRIG_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "Projects", "NeoStackAI" });
        if (!bWithIntegration)
        {
            return;
        }
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        // Lua and sol2 are exposed by the NeoStack AI core module as public includes.
        PrivateDefinitions.Add("NSAI_CONTROLRIG_MODULE=1");
        PrivateDefinitions.Add("LUA_BUILD_AS_DLL=1");
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
        PrivateDependencyModuleNames.AddRange(new string[] {
            "NeoStackAI",
            "UnrealEd",
            "ControlRig",
            "ControlRigDeveloper",
            "LevelSequence",
            "MovieScene",
            "MovieSceneTracks",
            "RigVM",
            "RigVMDeveloper",
            "Kismet",
            "BlueprintGraph",
        });
    }
}
