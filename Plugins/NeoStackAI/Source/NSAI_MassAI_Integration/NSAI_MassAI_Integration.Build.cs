using UnrealBuildTool;
using System.IO;

public class NSAI_MassAI_Integration : ModuleRules
{
    public NSAI_MassAI_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI36_MAI";
        string[] RequiredPlugins = new string[] { "ZoneGraph", "MassGameplay", "MassCrowd" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_MASSAI_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "Projects", "NeoStackAI" });
        if (!bWithIntegration)
        {
            return;
        }
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        // Lua and sol2 are exposed by the NeoStack AI core module as public includes.
        PrivateDefinitions.Add("LUA_BUILD_AS_DLL=1");
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
        PrivateDependencyModuleNames.AddRange(new string[] {
            "NeoStackAI",
            "UnrealEd",
            "ZoneGraph",
            "MassEntity",
            "MassSpawner",
            "MassSimulation",
            "MassCommon",
            "MassCrowd",
            "AIModule",
        });

        // StructUtils merged into CoreUObject in 5.6+, only needed as separate dep for 5.4/5.5
        if (Target.Version.MajorVersion == 5 && Target.Version.MinorVersion <= 5)
        {
            PrivateDependencyModuleNames.Add("StructUtils");
        }
    }
}
