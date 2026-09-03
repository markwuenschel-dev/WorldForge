using UnrealBuildTool;
using System.IO;

public class NSAI_PCG_Integration : ModuleRules
{
    public NSAI_PCG_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI43_PCG";
        string[] RequiredPlugins = new string[] { "PCG" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_PCG_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "PCG",
            "PCGEditor",
            "AssetDefinition",
        });

        // StructUtils: PropertyBag symbols not exported in 5.4, only needed for 5.5+
        if (Target.Version.MajorVersion == 5 && Target.Version.MinorVersion <= 5)
        {
            PrivateDependencyModuleNames.Add("StructUtils");
        }
    }
}
