// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

/**
 * WorldForgeEd - editor-only tooling home for:
 *   - procedural material authoring
 *   - the manifest pipeline
 *   - UE import automation
 *
 * Nothing in this module is included in a packaged (non-editor) build.
 */
class FWorldForgeEdModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};
