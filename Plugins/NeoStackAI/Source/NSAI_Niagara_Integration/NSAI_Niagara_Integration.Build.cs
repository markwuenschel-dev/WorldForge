using UnrealBuildTool;
using System.IO;

public class NSAI_Niagara_Integration : ModuleRules
{
    public NSAI_Niagara_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI41_N";
        string[] RequiredPlugins = new string[] { "Niagara" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        PublicDefinitions.Add("WITH_NSAI_NIAGARA_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
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
            "Niagara",
            "NiagaraEditor",
            "AnimGraphRuntime",
            "Sequencer",
        });

        string NiagaraInternalDir = Path.Combine(
            EngineDirectory,
            "Plugins",
            "FX",
            "Niagara",
            "Source",
            "Niagara",
            "Internal");
        bool bHasStatelessInternal =
            File.Exists(Path.Combine(NiagaraInternalDir, "Stateless", "NiagaraStatelessEmitter.h")) &&
            File.Exists(Path.Combine(NiagaraInternalDir, "Stateless", "NiagaraStatelessModule.h")) &&
            File.Exists(Path.Combine(NiagaraInternalDir, "Stateless", "NiagaraStatelessSimulationShader.h"));
        if (bHasStatelessInternal)
        {
            PrivateIncludePaths.Add(NiagaraInternalDir);
        }
        PrivateDefinitions.Add("NSAI_NIAGARA_HAS_STATELESS_INTERNAL=" + (bHasStatelessInternal ? "1" : "0"));

        string ExternalEditUtilitiesHeader = Path.Combine(
            EngineDirectory,
            "Plugins",
            "FX",
            "Niagara",
            "Source",
            "NiagaraEditor",
            "Public",
            "NiagaraExternalSystemEditorUtilities.h");
        PrivateDefinitions.Add("NSAI_NIAGARA_HAS_EXTERNAL_EDIT_UTILITIES=" + (File.Exists(ExternalEditUtilitiesHeader) ? "1" : "0"));
    }
}
