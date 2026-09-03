using UnrealBuildTool;

public class NSAI_SVGImporter_Integration : ModuleRules
{
    public NSAI_SVGImporter_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI58_SVGI";
        string[] RequiredPlugins = new string[] { "SVGImporter", "Avalanche", "ActorModifierCore", "ActorModifier" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_SVGIMPORTER_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "AssetRegistry",
            "GeometryFramework",
            "SVGImporter",
            "SVGImporterEditor",
            "Avalanche",
            "AvalancheSVGEditor",
            "ActorModifierCore",
            "ActorModifier",
        });
    }
}
