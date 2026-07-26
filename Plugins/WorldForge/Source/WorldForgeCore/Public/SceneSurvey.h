// Copyright Epic Games, Inc. All Rights Reserved.
//
// WorldForge v2.6 SceneSurveyForge — read-only spatial survey primitives.
//
// These reflected UFUNCTIONs are the C++ half of the scene survey: the geometry-
// heavy work (actor/component enumeration with bounds + collision state, downward-
// trace 6-class support classification, and trace-only temporary-marker clearance)
// that a far-side in-editor python script calls into after opening a target map.
// Each emits WF_SURVEY_* marker lines the near-side parses into a SurveyReport.
//
// This lives in WorldForgeCore (the game-agnostic, dependency-light plugin module)
// on purpose: only the WorldForge PLUGIN ships into an external target like
// Gloamstead, so the survey primitives must be here to cross the repo boundary — a
// project-module class would be invisible in the target editor.
//
// Read-only: nothing here saves the map or authors a permanent actor. Camera capture
// is deliberately NOT here — it needs an RHI and is done far-side in python via the
// editor screenshot API, keeping this module free of render deps.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "SceneSurvey.generated.h"

/** Static survey primitives, reflected so a far-side editor python script can call
 *  them (e.g. unreal.SceneSurveyStatics.sample_survey_support(world, ctr, r, step)). */
UCLASS()
class USceneSurveyStatics : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()
public:
	/** Enumerate actors within RadiusCm of Center and their primitive components;
	 *  emit one WF_SURVEY_ACTOR line per actor (class, name, location, bounds) and
	 *  one WF_SURVEY_COMPONENT line per primitive (class, collision state, bounds),
	 *  then a WF_SURVEY_ENUM summary. Returns the actor count. */
	UFUNCTION(BlueprintCallable, Category = "WorldForge|SceneSurvey",
		meta = (WorldContext = "WorldContextObject"))
	static int32 EnumerateSurveyActors(const UObject* WorldContextObject, FVector Center, float RadiusCm);

	/** Downward-trace 6-class support sampling over a grid around Center (step
	 *  StepCm, half-extent RadiusCm): each cell -> valid_support / unsupported /
	 *  edge / blocked / trace_error / unknown (unknown is the fail-closed default;
	 *  unsupported = clean miss; edge = valid cell bordering an invalid neighbour or
	 *  a step discontinuity). Emits a WF_SURVEY_SUPPORT summary; returns the total
	 *  sample count. Collision/geometry evidence only — never navmesh. */
	UFUNCTION(BlueprintCallable, Category = "WorldForge|SceneSurvey",
		meta = (WorldContext = "WorldContextObject"))
	static int32 SampleSurveySupport(const UObject* WorldContextObject, FVector Center, float RadiusCm, float StepCm);

	/** Trace-test a temporary-marker candidate at Location: ground contact, 4-corner
	 *  footprint support, and a capsule overlap against static + dynamic geometry.
	 *  Emits WF_SURVEY_MARKER; returns true only when grounded AND footprint-supported
	 *  AND clear (never guesses a placement). Does not spawn — pure query. */
	UFUNCTION(BlueprintCallable, Category = "WorldForge|SceneSurvey",
		meta = (WorldContext = "WorldContextObject"))
	static bool ProbeTempMarker(const UObject* WorldContextObject, FVector Location,
		float CapsuleRadius, float CapsuleHalfHeight);
};
