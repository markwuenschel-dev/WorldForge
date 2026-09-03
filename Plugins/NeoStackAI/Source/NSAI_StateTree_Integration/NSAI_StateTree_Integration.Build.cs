using UnrealBuildTool;
using System.IO;

public class NSAI_StateTree_Integration : ModuleRules
{
    public NSAI_StateTree_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI57_ST";
        string[] RequiredPlugins = new string[] { "StateTree", "PropertyBindingUtils", "GameplayStateTree", "GameplayTagsEditor" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_STATETREE_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "StateTreeModule",
            "StateTreeEditorModule",
            "GameplayStateTreeModule",
            "PropertyBindingUtils",
            "GameplayTags",
            "GameplayTagsEditor",
        });
    }
}
