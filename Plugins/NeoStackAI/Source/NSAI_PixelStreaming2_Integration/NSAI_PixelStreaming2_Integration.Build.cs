using UnrealBuildTool;
using System.IO;

public class NSAI_PixelStreaming2_Integration : ModuleRules
{
    public NSAI_PixelStreaming2_Integration(ReadOnlyTargetRules Target) : base(Target)
    {
		bUsePrecompiled = true;
        ShortName = "NSI64_PS2";
        string[] RequiredPlugins = new string[] { "PixelStreaming2" };
        bool bWithIntegration = NeoStackIntegrationRules.ArePluginsAvailable(Target, RequiredPlugins, EngineDirectory);
        // Per-client-window capture rides 5.8's FVideoProducerViewportBase.
        // Older minors compile the module but answer supported=false; the
        // desktop falls back to the single-stream flow there. 5.7 support
        // slots in behind this define later.
        bool bMultiStream = bWithIntegration
            && (Target.Version.MajorVersion > 5 || Target.Version.MinorVersion >= 8);
        PublicDefinitions.Add("WITH_NSAI_PIXELSTREAMING2_INTEGRATION=" + (bWithIntegration ? "1" : "0"));
        PublicDefinitions.Add("NSAI_PS2_MULTISTREAM=" + (bMultiStream ? "1" : "0"));
        PublicDependencyModuleNames.AddRange(new string[] { "Core", "Projects", "NeoStackAI" });
        if (!bWithIntegration)
        {
            return;
        }
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        // Lua and sol2 are exposed by the NeoStack AI core module as public includes.
        PrivateDefinitions.Add("LUA_BUILD_AS_DLL=1");
        PrivateDependencyModuleNames.AddRange(new string[] {
            "CoreUObject",
            "Engine",
            "UnrealEd",
            "Slate",
            "SlateCore",
            "InputCore",
            "Json",
            "PixelStreaming2",
            "PixelStreaming2Input",
        });
        if (Target.Version.MajorVersion > 5 || Target.Version.MinorVersion >= 6)
        {
            // IPixelStreaming2Streamer moved here in 5.6.
            PrivateDependencyModuleNames.Add("PixelStreaming2Core");
        }
        if (bMultiStream)
        {
            // The producer base's header pulls RDG/RHI and capture types;
            // LevelEditor for the spawn-at-camera viewport lookup.
            PrivateDependencyModuleNames.AddRange(new string[] {
                "RenderCore", "RHI", "MediaIOCore", "PixelCapture", "LevelEditor",
            });
            // FVideoProducerViewportBase lives in the engine plugin's
            // Internal/ folder, which UBT hides from project-scope modules.
            // Reach in explicitly rather than flipping bTreatAsEngineModule
            // (which would change this module's whole build semantics).
            string PS2Source = Path.Combine(EngineDirectory, "Plugins", "Media", "PixelStreaming2", "Source");
            PrivateIncludePaths.Add(Path.Combine(PS2Source, "PixelStreaming2", "Internal"));
        }
    }
}
