// Copyright Epic Games, Inc. All Rights Reserved.
//
// WorldForge v2.6 — native runtime identity surface.
//
// PURPOSE
// -------
// Answer, from inside the running editor, one question that nothing else can
// answer honestly: *is the WorldForge plugin actually loaded, and which build of
// it?* A python-side `hasattr(unreal, "SceneSurveyStatics")` proves a class is
// reflected; it cannot distinguish a freshly-compiled module from a stale DLL
// left over from a previous build. That distinction is the whole point here.
//
// This surface is deliberately PLUGIN-OWNED (WorldForgeCore, not the project
// module) for the same reason SceneSurvey.h is: only the plugin crosses into an
// external target like Gloamstead, so identity must be provable there too.
//
// REFLECTION CONTRACT — do not "tidy" the specifiers
// --------------------------------------------------
// Every field is `UPROPERTY(BlueprintReadOnly)` and the struct is `BlueprintType`
// ON PURPOSE. A bare `UPROPERTY()` is NOT exposed to python: the PythonScriptPlugin
// only wraps properties carrying CPF_BlueprintVisible. This project has already
// paid for that lesson once — FHitResult's fields are unreachable from python for
// exactly this reason, which is why `break_hit_result` has to exist. Dropping
// `BlueprintReadOnly` from any field below silently removes it from
// `unreal.WorldForgeRuntimeIdentity` and the far-side smoke will report it missing.
//
// HONESTY CONTRACT
// ----------------
// A field the engine cannot answer is emitted EMPTY, never guessed. An empty
// string here is a real signal that travels: the far-side validator in
// tools/pipeline/run_v2_6_fixture_smoke.py requires every field to be a non-empty
// string, so an unavailable field turns the identity probe RED rather than
// letting a plausible-looking placeholder through. That is intended fail-closed
// behaviour, not a bug.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "WorldForgeRuntimeIdentity.generated.h"

/**
 * Version of the NATIVE identity contract. Bump this whenever the shape or the
 * meaning of FWorldForgeRuntimeIdentity changes. The python side pins the value
 * it expects in tools/build/wf_build_proof.py (EXPECTED_CONTRACT_VERSION); a
 * mismatch means the loaded DLL and the python contract are out of step, which
 * is precisely the stale-binary condition this surface exists to detect.
 */
#define WF_RUNTIME_IDENTITY_CONTRACT_VERSION 1

/**
 * Identity of the WorldForgeCore binary that is actually loaded in this process.
 *
 * Python-visible as `unreal.WorldForgeRuntimeIdentity` with snake_case fields
 * (module_name, plugin_name, plugin_version, contract_version, build_identity,
 * loaded_module_path).
 */
USTRUCT(BlueprintType)
struct WORLDFORGECORE_API FWorldForgeRuntimeIdentity
{
	GENERATED_BODY()

	/** Module the identity was resolved for, as the module manager knows it
	 *  (FModuleStatus::Name). Empty if the module manager does not know it — which
	 *  would be self-contradictory here, since this code lives in that module. */
	UPROPERTY(BlueprintReadOnly, Category = "WorldForge|Identity")
	FString ModuleName;

	/** Owning plugin's name, taken from the plugin whose descriptor declares this
	 *  module. Empty if no discovered plugin claims it. Never hard-coded. */
	UPROPERTY(BlueprintReadOnly, Category = "WorldForge|Identity")
	FString PluginName;

	/** Owning plugin's FPluginDescriptor::VersionName (the front-facing version
	 *  string from WorldForge.uplugin). Empty if the descriptor is unavailable. */
	UPROPERTY(BlueprintReadOnly, Category = "WorldForge|Identity")
	FString PluginVersion;

	/** WF_RUNTIME_IDENTITY_CONTRACT_VERSION as compiled into this binary. Zero is
	 *  never a valid contract version and means the struct was default-constructed
	 *  without going through GetWorldForgeRuntimeIdentity(). */
	UPROPERTY(BlueprintReadOnly, Category = "WorldForge|Identity")
	int32 ContractVersion = 0;

	/** Compile stamp of THIS translation unit (__DATE__ " " __TIME__), so a stale
	 *  binary is detectable: it changes every time this .cpp is genuinely
	 *  recompiled and does not change when a cached object file is reused. */
	UPROPERTY(BlueprintReadOnly, Category = "WorldForge|Identity")
	FString BuildIdentity;

	/** Absolute path of the loaded binary, from FModuleStatus::FilePath. Empty in
	 *  monolithic builds, where the engine genuinely does not record it — see
	 *  ModuleManager.cpp:456-458. Empty therefore means "unsupported here", not
	 *  "not loaded". */
	UPROPERTY(BlueprintReadOnly, Category = "WorldForge|Identity")
	FString LoadedModulePath;

	/** True when the module manager reports the module as currently loaded. This
	 *  is a bool rather than a string because it is a fact the engine always
	 *  knows; it has no unavailable state. */
	UPROPERTY(BlueprintReadOnly, Category = "WorldForge|Identity")
	bool bIsModuleLoaded = false;
};

/**
 * Plugin-owned identity accessor.
 *
 * Python: `unreal.WorldForgeIdentityStatics.get_world_forge_runtime_identity()`.
 *
 * The mere fact that this call SUCCEEDS is half the evidence: the function is
 * compiled into UnrealEditor-WorldForgeCore.dll, so a successful invocation
 * proves that specific plugin binary is loaded and reflected. The returned
 * struct is the other half — it says *which* binary.
 */
UCLASS()
class WORLDFORGECORE_API UWorldForgeIdentityStatics : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/** Resolve the identity of the loaded WorldForgeCore binary. Pure query: no
	 *  side effects, safe to call at any time from any thread the reflection
	 *  system allows. Fields the engine cannot supply come back empty. */
	UFUNCTION(BlueprintCallable, Category = "WorldForge")
	static FWorldForgeRuntimeIdentity GetWorldForgeRuntimeIdentity();
};
