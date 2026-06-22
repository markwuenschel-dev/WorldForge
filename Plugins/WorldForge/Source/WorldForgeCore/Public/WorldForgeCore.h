// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

/**
 * WorldForgeCore - runtime contracts shared between the tooling layer and any game.
 *
 * Keep this module game-agnostic: only adaptive world-state contracts and
 * generation-rule primitives belong here, never game-specific lore, factions,
 * quests, or content.
 */
class FWorldForgeCoreModule : public IModuleInterface
{
};
