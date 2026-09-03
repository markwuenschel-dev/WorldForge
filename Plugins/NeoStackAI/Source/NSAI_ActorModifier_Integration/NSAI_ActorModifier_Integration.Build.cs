using UnrealBuildTool;

public class NSAI_ActorModifier_Integration : ModuleRules
{
    public NSAI_ActorModifier_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI01_AM";
        string[] RequiredPlugins = new string[] { "ActorModifierCore", "ActorModifier" };
        // 5.7 gate: the plugins exist in 5.6 but the ActorModifierLayout/
        // ActorModifierRendering MODULES only split out in 5.7 — a descriptor
        // check alone passes there and then dies at rules resolution.
        bool bEngineHasModifierModules =
            Target.Version.MajorVersion > 5 || Target.Version.MinorVersion >= 7;
        bool bWithIntegration = bEngineHasModifierModules
            && NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_ACTORMODIFIER_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "ActorModifierCore",
            "ActorModifier",
            "ActorModifierLayout",
            "ActorModifierRendering",
        });
    }
}
