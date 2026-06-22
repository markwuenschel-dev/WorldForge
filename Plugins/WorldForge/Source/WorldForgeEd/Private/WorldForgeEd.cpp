// Copyright Epic Games, Inc. All Rights Reserved.

#include "WorldForgeEd.h"

#define LOCTEXT_NAMESPACE "FWorldForgeEdModule"

void FWorldForgeEdModule::StartupModule()
{
	// Register procedural-material / manifest / import tooling here.
}

void FWorldForgeEdModule::ShutdownModule()
{
	// Tear down anything registered in StartupModule().
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FWorldForgeEdModule, WorldForgeEd);
