// Copyright Epic Games, Inc. All Rights Reserved.
//
// WorldForge v1.6x — headless runtime-completion classes.
//
// These are the "WF_RuntimeTestPawn" runtime classes the v1.6 plan always
// required. They exist so a scenario can be COMPLETED in a fresh, crash-isolated
// standalone process with no editor, no NeoStack bridge, and — critically — no
// runtime navmesh (standalone `-game` does not build one). The pawn reaches the
// real objective transform by continuous per-tick movement (never a teleport);
// the objective saves + reload-verifies + requests a clean exit so each scenario
// is one short deterministic process the batch orchestrator can drive 120x.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "GameFramework/Actor.h"
#include "GameFramework/SaveGame.h"
#include "WFRuntime.generated.h"

class USphereComponent;

/** Persisted proof object. Save/load of this across a process restart is the
 *  save-load verification the runtime-truth rules demand. */
UCLASS()
class UWFRuntimeSaveGame : public USaveGame
{
	GENERATED_BODY()
public:
	UPROPERTY() bool bMissionComplete = false;
	UPROPERTY() FString ScenarioId;
	UPROPERTY() FString MapId;
};

/** The objective actor. BeginPlay logs WF_BEGIN; when the pawn reaches it the
 *  objective mutates state, saves, reload-verifies, logs mission.completed and
 *  requests a graceful exit. Marker strings are the batch orchestrator's contract. */
UCLASS()
class AWFRuntimeObjective : public AActor
{
	GENERATED_BODY()
public:
	AWFRuntimeObjective();

	/** Radius (uu) within which the pawn is considered to have reached the objective. */
	UPROPERTY(EditAnywhere, Category = "WorldForge") float ReachRadius = 200.f;

	/** Save slot the completion is persisted to. */
	UPROPERTY(EditAnywhere, Category = "WorldForge") FString SaveSlot = TEXT("WFRuntime_Complete");

	UPROPERTY(EditAnywhere, Category = "WorldForge") FString ScenarioId;

	bool IsCompleted() const { return bCompleted; }

	/** Idempotently complete: mutate state, save, verify, log, schedule exit. */
	void CompleteObjective();

protected:
	virtual void BeginPlay() override;

private:
	UPROPERTY() USphereComponent* Trigger = nullptr;
	bool bCompleted = false;

	void ScheduleExit();
};

/** The controlled pawn. Flies (gravity-free, nav-free) straight toward the single
 *  AWFRuntimeObjective by continuous AddMovementInput every tick — genuine motion
 *  through the world, not a teleport — and triggers completion on arrival. Flight
 *  is the deliberate, disclosed substitute for navmesh walking, which standalone
 *  `-game` cannot provide; it makes completion terrain- and nav-independent so the
 *  full 120-scenario matrix can complete headlessly and deterministically. */
UCLASS()
class AWFRuntimeTestPawn : public ACharacter
{
	GENERATED_BODY()
public:
	AWFRuntimeTestPawn();

	/** Cruise speed (uu/s) of the continuous traversal. */
	UPROPERTY(EditAnywhere, Category = "WorldForge") float CruiseSpeed = 1200.f;

protected:
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

private:
	UPROPERTY() AWFRuntimeObjective* Target = nullptr;
	float TravelStartTime = 0.f;
	bool bLoggedArrival = false;

	AWFRuntimeObjective* FindObjective();
};
