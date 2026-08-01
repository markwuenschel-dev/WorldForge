// Copyright Epic Games, Inc. All Rights Reserved.

#include "SceneSurvey.h"

#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Actor.h"
#include "Components/PrimitiveComponent.h"
#include "CollisionQueryParams.h"

DEFINE_LOG_CATEGORY_STATIC(LogWFSurvey, Display, All);

namespace
{
	// Support-class codes (fail-closed: unknown is the default before classification).
	enum : int32 { CLS_VALID = 0, CLS_UNSUPPORTED = 1, CLS_EDGE = 2, CLS_BLOCKED = 3,
	               CLS_TRACE_ERROR = 4, CLS_UNKNOWN = 5 };

	UWorld* ResolveWorld(const UObject* WorldContextObject)
	{
		return GEngine ? GEngine->GetWorldFromContextObject(
			WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
	}

	// Grid key with a +2000 bias so negative indices stay non-negative and distinct.
	FORCEINLINE int64 GridKey(int32 ix, int32 iy)
	{
		return (int64)(ix + 2000) * 100000 + (int64)(iy + 2000);
	}
}

int32 USceneSurveyStatics::EnumerateSurveyActors(const UObject* WorldContextObject,
	FVector Center, float RadiusCm)
{
	UWorld* W = ResolveWorld(WorldContextObject);
	if (!W)
	{
		UE_LOG(LogWFSurvey, Warning, TEXT("WF_SURVEY_ENUM_ERROR reason=no_world"));
		return 0;
	}
	const float R2 = RadiusCm * RadiusCm;
	int32 ActorCount = 0, CompCount = 0;
	for (TActorIterator<AActor> It(W); It; ++It)
	{
		AActor* A = *It;
		if (!A) { continue; }
		const FVector Loc = A->GetActorLocation();
		if ((float)FVector::DistSquared(Loc, Center) > R2) { continue; }

		FVector Origin, Extent;
		A->GetActorBounds(false, Origin, Extent);
		++ActorCount;
		UE_LOG(LogWFSurvey, Display,
			TEXT("WF_SURVEY_ACTOR class=%s name=%s loc=%.1f,%.1f,%.1f ext=%.1f,%.1f,%.1f"),
			*A->GetClass()->GetName(), *A->GetName(),
			Loc.X, Loc.Y, Loc.Z, Extent.X, Extent.Y, Extent.Z);

		TArray<UPrimitiveComponent*> Prims;
		A->GetComponents(Prims);
		for (UPrimitiveComponent* P : Prims)
		{
			if (!P) { continue; }
			++CompCount;
			const FBoxSphereBounds B = P->Bounds;
			UE_LOG(LogWFSurvey, Display,
				TEXT("WF_SURVEY_COMPONENT actor=%s comp=%s class=%s collision=%d ")
				TEXT("bext=%.1f,%.1f,%.1f"),
				*A->GetName(), *P->GetName(), *P->GetClass()->GetName(),
				(int32)P->GetCollisionEnabled(),
				B.BoxExtent.X, B.BoxExtent.Y, B.BoxExtent.Z);
		}
	}
	UE_LOG(LogWFSurvey, Display,
		TEXT("WF_SURVEY_ENUM actors=%d components=%d radius=%.1f"),
		ActorCount, CompCount, RadiusCm);
	return ActorCount;
}

int32 USceneSurveyStatics::SampleSurveySupport(const UObject* WorldContextObject,
	FVector Center, float RadiusCm, float StepCm)
{
	UWorld* W = ResolveWorld(WorldContextObject);
	if (!W || StepCm <= 0.f || RadiusCm <= 0.f)
	{
		UE_LOG(LogWFSurvey, Warning, TEXT("WF_SURVEY_SUPPORT_ERROR reason=bad_params"));
		return 0;
	}
	// Tolerances are CONTRACT VALUES — docs/contracts/v2_6_support_grid_contract.md §3.
	const float MaxSlope = 44.f, MaxStepH = 45.f;

	// Grid extent. sample_region_shape = AXIS_ALIGNED_SQUARE; RadiusCm is its HALF-EXTENT.
	//     k = floor(R / s),  i,j in [-k, k],  p_ij = (a.x + i*s, a.y + j*s),  N = (2k+1)^2
	// Consequence, and the point of the change: R < s yields k = 0 -> exactly ONE centre
	// sample. The previous max(1, floor(R/s)) sampled a 3x3 block reaching +/-s, i.e.
	// OUTSIDE the half-extent it was handed. A collector must not sample beyond its
	// requested region.
	// A radial region is a SEPARATE, SEPARATELY-DECLARED mode (i*i + j*j <= (R/s)^2).
	// Never substitute disk semantics for square semantics silently — the two modes must
	// stay distinguishable by name at every layer.
	// RadiusCm > 0 and StepCm > 0 are guaranteed by the guard above, so the quotient is
	// positive and FloorToInt is a true floor.
	const int32 K = FMath::FloorToInt(RadiusCm / StepCm);
	FCollisionQueryParams Q;
	Q.bTraceComplex = true;

	TMap<int64, int32> Cls;
	TMap<int64, float> GridZ;

	// Pass 1 — classify each cell from a downward complex trace + head clearance.
	for (int32 ix = -K; ix <= K; ++ix)
	{
		for (int32 iy = -K; iy <= K; ++iy)
		{
			const float X = Center.X + ix * StepCm;
			const float Y = Center.Y + iy * StepCm;
			const FVector S(X, Y, Center.Z + 1000.f), E(X, Y, Center.Z - 3000.f);
			FHitResult H;
			const bool bHit = W->LineTraceSingleByChannel(H, S, E, ECC_Visibility, Q);
			int32 c = CLS_UNKNOWN;  // fail-closed default, before any classification
			if (!bHit)
			{
				c = CLS_UNSUPPORTED;  // a clean miss = no floor beneath this cell
			}
			else if (H.ImpactPoint.ContainsNaN() || H.ImpactNormal.ContainsNaN()
				|| H.ImpactNormal.IsNearlyZero())
			{
				// A blocking hit carrying no usable geometry is a FAILED MEASUREMENT,
				// not an observation that there is no floor here. Fail-closed: it is
				// trace_error, never unsupported, and never counted valid. This is the
				// only assignment of CLS_TRACE_ERROR; without it the class is
				// structurally unreachable and every "valid excludes trace_error" rail
				// downstream is vacuous.
				c = CLS_TRACE_ERROR;
			}
			else
			{
				const float Slope = FMath::RadiansToDegrees(
					FMath::Acos(FMath::Clamp((float)H.ImpactNormal.Z, -1.f, 1.f)));
				GridZ.Add(GridKey(ix, iy), (float)H.ImpactPoint.Z);
				if (Slope > MaxSlope)
				{
					c = CLS_BLOCKED;  // too steep to stand on
				}
				else
				{
					const FVector HS(X, Y, (float)H.ImpactPoint.Z + MaxStepH + 5.f);
					const FVector HE(X, Y, (float)H.ImpactPoint.Z + 176.f);
					FHitResult HC;
					const bool bHeadBlocked =
						W->LineTraceSingleByChannel(HC, HS, HE, ECC_Visibility, Q);
					c = bHeadBlocked ? CLS_BLOCKED : CLS_VALID;
				}
			}
			Cls.Add(GridKey(ix, iy), c);
		}
	}

	// Pass 2 — DIAGNOSTIC edge marking. This is NOT the authoritative edge result.
	//
	// Authoritative predicate (contract §5):
	//     E_ij = S_ij AND exists q in N(i,j):  !S_q
	//                                       OR |z_ij - z_q| > tau_h
	//                                       OR angle(n_ij, n_q) > tau_n
	// The tau_n (normal-discontinuity) term is ABSENT below, and tau_n has no declared
	// value anywhere yet, so this flag systematically UNDER-reports: a ridge crest with
	// a sharp normal change but no height step stays `valid` on both sides.
	//
	// Therefore CLS_EDGE here is a diagnostic hint only. It MUST NOT satisfy the
	// authoritative edge result; that is derived independently by the WorldForge
	// evidence layer from raw observations (tools/pipeline/support_grid_canonical.py).
	// Keeping the engine side to raw observation + diagnostics is what stops the C++
	// and the validator from agreeing merely by duplicated convention.
	static const int32 DX[4] = { 1, -1, 0, 0 };
	static const int32 DY[4] = { 0, 0, 1, -1 };
	for (int32 ix = -K; ix <= K; ++ix)
	{
		for (int32 iy = -K; iy <= K; ++iy)
		{
			int32* Cp = Cls.Find(GridKey(ix, iy));
			if (!Cp || *Cp != CLS_VALID) { continue; }
			const float* Z = GridZ.Find(GridKey(ix, iy));
			bool bEdge = false;
			for (int32 d = 0; d < 4 && !bEdge; ++d)
			{
				const int32 nx = ix + DX[d], ny = iy + DY[d];
				const int32* Nc = Cls.Find(GridKey(nx, ny));
				if (!Nc) { continue; }  // off-grid neighbour: not evidence of an edge
				if (*Nc == CLS_UNSUPPORTED || *Nc == CLS_TRACE_ERROR || *Nc == CLS_UNKNOWN)
				{
					bEdge = true;
					break;
				}
				const float* Nz = GridZ.Find(GridKey(nx, ny));
				if (Z && Nz && FMath::Abs(*Z - *Nz) > MaxStepH * 2.f)
				{
					bEdge = true;
					break;
				}
			}
			if (bEdge) { *Cp = CLS_EDGE; }
		}
	}

	int32 Total = 0, Valid = 0, Unsupported = 0, Edge = 0, Blocked = 0, TraceErr = 0, Unknown = 0;
	for (const TPair<int64, int32>& It : Cls)
	{
		++Total;
		switch (It.Value)
		{
		case CLS_VALID:       ++Valid; break;
		case CLS_UNSUPPORTED: ++Unsupported; break;
		case CLS_EDGE:        ++Edge; break;
		case CLS_BLOCKED:     ++Blocked; break;
		case CLS_TRACE_ERROR: ++TraceErr; break;
		default:              ++Unknown; break;
		}
	}
	// Field order up to unknown= is load-bearing: tools/pipeline/run_scene_survey_probe.py:136
	// parses this prefix as a DIAGNOSTIC channel. New fields are appended after it only.
	// edge_authority=diagnostic says out loud that edge= lacks the tau_n term (see pass 2).
	UE_LOG(LogWFSurvey, Display,
		TEXT("WF_SURVEY_SUPPORT total=%d valid=%d unsupported=%d edge=%d blocked=%d ")
		TEXT("trace_error=%d unknown=%d radius=%.1f step=%.1f navmesh=0 ")
		TEXT("shape=axis_aligned_square k=%d edge_authority=diagnostic"),
		Total, Valid, Unsupported, Edge, Blocked, TraceErr, Unknown, RadiusCm, StepCm, K);
	return Total;
}

bool USceneSurveyStatics::ProbeTempMarker(const UObject* WorldContextObject, FVector Location,
	float CapsuleRadius, float CapsuleHalfHeight)
{
	UWorld* W = ResolveWorld(WorldContextObject);
	if (!W)
	{
		UE_LOG(LogWFSurvey, Warning, TEXT("WF_SURVEY_MARKER_ERROR reason=no_world"));
		return false;
	}
	FCollisionQueryParams Q;
	Q.bTraceComplex = true;

	// Ground contact directly below the candidate. The reach matches the support
	// sampler (Z-3000) so an elevated anchor (e.g. a PlayerStart floating above the
	// courtyard floor) still finds real ground rather than falsely reading ungrounded.
	const FVector S(Location.X, Location.Y, Location.Z + 100.f);
	const FVector E(Location.X, Location.Y, Location.Z - 3000.f);
	FHitResult G;
	const bool bGrounded = W->LineTraceSingleByChannel(G, S, E, ECC_Visibility, Q);
	const float GroundZ = bGrounded ? (float)G.ImpactPoint.Z : (float)Location.Z;

	// Footprint support: four corner traces at the capsule radius must all hit.
	const float RR = FMath::Max(1.f, CapsuleRadius);
	static const float OX[4] = { 1.f, -1.f, 0.f, 0.f };
	static const float OY[4] = { 0.f, 0.f, 1.f, -1.f };
	bool bFootprint = bGrounded;
	for (int32 i = 0; i < 4 && bFootprint; ++i)
	{
		const FVector FS(Location.X + OX[i] * RR, Location.Y + OY[i] * RR, GroundZ + 100.f);
		const FVector FE(Location.X + OX[i] * RR, Location.Y + OY[i] * RR, GroundZ - 200.f);
		FHitResult F;
		if (!W->LineTraceSingleByChannel(F, FS, FE, ECC_Visibility, Q)) { bFootprint = false; }
	}

	// Capsule clearance: a blocking overlap against static or dynamic geometry rejects.
	const FVector CapCtr(Location.X, Location.Y, GroundZ + CapsuleHalfHeight + 2.f);
	const FCollisionShape Cap = FCollisionShape::MakeCapsule(CapsuleRadius, CapsuleHalfHeight);
	const bool bOverlap =
		W->OverlapBlockingTestByChannel(CapCtr, FQuat::Identity, ECC_WorldStatic, Cap, Q) ||
		W->OverlapBlockingTestByChannel(CapCtr, FQuat::Identity, ECC_WorldDynamic, Cap, Q);
	const bool bClearance = !bOverlap;
	const bool bAccepted = bGrounded && bFootprint && bClearance;

	UE_LOG(LogWFSurvey, Display,
		TEXT("WF_SURVEY_MARKER loc=%.1f,%.1f,%.1f groundZ=%.1f grounded=%d footprint=%d ")
		TEXT("overlap=%d clearance=%d accepted=%d"),
		Location.X, Location.Y, Location.Z, GroundZ,
		bGrounded ? 1 : 0, bFootprint ? 1 : 0, bOverlap ? 1 : 0, bClearance ? 1 : 0,
		bAccepted ? 1 : 0);
	return bAccepted;
}
