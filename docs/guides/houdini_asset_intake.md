# Houdini Generated-Asset Intake (v0.8 sidecar)

> Register **one** baked Houdini-generated rock StaticMesh as a WorldForge-owned
> generated asset and make it eligible for desert PCG placement.

This is the narrow asset-intake lane. It is **not MeshForge**, not a procedural
mesh framework, and not HDA authoring. Definition of done:

```
one baked Houdini StaticMesh
  → WorldForge-owned folder
  → registry / provenance
  → desert asset catalog
  → PCG eligibility
  → validation
```

Then stop. Houdini work caps after this one asset validates.

## Allowed vs forbidden paths

| | Path |
|---|---|
| ✅ Allowed final path | `/Game/WorldForge/Generated/Houdini/Rocks/...` |
| ❌ Forbidden final path | `/Game/HoudiniEngine/Temp` |
| ❌ Forbidden final path | `/Game/HoudiniEngine/Bake` |

`register-generated-asset` **refuses** to register a forbidden path, and
`validate-generated-asset` **fails** if a registered asset resolves to one
(Risk 2 mitigation). A baked asset must be relocated into the WorldForge-owned
tree before registration.

## Workflow

### 1. (UE-side) Relocate the bake into WorldForge ownership

The proof bake lives at
`/Game/HoudiniEngine/Bake/rock_generator_3_6_0_main_geo_C3C435B6`. Relocate it to
`/Game/WorldForge/Generated/Houdini/Rocks/SM_RockGenerator_Desert_01`:

```bash
# run inside the UE editor python (reads descriptor.json; src/dst come from it)
make relocate-houdini-asset ASSET=rock_generator_desert_01
```

This duplicates the bake to the owned path, asserts the result is a `StaticMesh`,
and writes `ue_generated_asset_report.json`. (Register first — step 2 — so the
descriptor exists; or relocate by hand in-editor and skip to step 2.)

### 2. Register the asset (authoring-side, pure Python)

Edit `procedural/definitions/generated_assets/rock_generator_desert_01.yaml` to
describe the asset, then:

```bash
make register-generated-asset ASSET=rock_generator_desert_01
```

This writes a descriptor + a registry entry in
`procedural/generated/worldforge_generated_asset_registry.json`. When
`pcg_allowed: true`, it also asserts the asset is listed in its catalog category
(`desert_asset_catalog.generated_rocks`) so a placement preset can scatter it.

### 3. Validate the intake

```bash
make validate-generated-asset ASSET=rock_generator_desert_01
make validate-generated-asset ASSET=rock_generator_desert_01 STRICT=1   # v0.9 final gate
```

`STRICT=1` (v0.9) escalates soft `WARN` checks to blocking; the gated UE check below
stays non-blocking in both modes. See
[`production_hardening_v0_9.md`](production_hardening_v0_9.md) for the strict-mode
and six-verdict vocabulary.

## Asset definition fields

`procedural/definitions/generated_assets/<asset_id>.yaml`:

| Field | Meaning |
|-------|---------|
| `asset_id`, `display_name` | Identity (`rock_generator_desert_01`). |
| `unreal_path` | Final WorldForge-owned path (must be under the allowed root). |
| `source`, `hda_name`, `source_bake_path` | Provenance of the generated mesh. |
| `asset_type` | `static_mesh`. |
| `role`, `biome` | Classification + biome compatibility (machine-readable). |
| `pcg_allowed` | PCG eligibility flag. |
| `placement_category`, `asset_catalog` | Where the path must be catalog-listed. |
| `generated_owned`, `temporary` | Ownership flags (`true` / `false`). |

## Catalog membership = PCG eligibility

The asset path is listed under `generated_rocks` in
`procedural/definitions/assets/desert_asset_catalog.yaml`. A desert placement
preset that references the `generated_rocks` category will then scatter the
Houdini rock. Add the path to the catalog **before** registering (the registrar
verifies it; `make validate-asset-catalog CATALOG=desert_asset_catalog` confirms
the catalog stays well-formed).

## What validate-generated-asset proves

descriptor + registry ownership · `asset_type == static_mesh` · `source ==
houdini` + `hda_name` present · path under `/Game/WorldForge/Generated/Houdini/
Rocks` · **not** a Houdini Temp/Bake path · `generated_owned == true`,
`temporary == false` · `pcg_allowed == true` · `desert` in `biome` · catalog
membership · provenance present.

### v0.9 — strict validation and the gated UE check

Under v0.9 the UE StaticMesh presence check is reclassified from `warn_only` to
**`GATED_HUMAN_EDITOR`** (D7): `asset_exists_in_ue_as_static_mesh` is gated until
`make relocate-houdini-asset` has produced a passing `ue_generated_asset_report.json`.
It never blocks — in normal **or** strict mode — and clears to `PASS` once the editor
step runs. If the asset is materialized but is the wrong type, the gated check carries
`WF081_UE_ASSET_NOT_STATIC_MESH`; otherwise `WF080_UE_MATERIALIZATION_PENDING`. So the
data-layer intake validates cleanly (even under `STRICT=1`) without an editor, and the
UE presence check lights up once `relocate-houdini-asset` runs.

The data-layer guarantees stay **hard `FAIL`s** in both modes: forbidden Houdini
Temp/Bake path (`WF040`), path not under the owned tree (`WF041`), missing
`generated_owned` flag (`WF051`), missing catalog membership (`WF042`), missing
provenance (`WF020`).

### v0.9 — audit and package-check coverage

This intake asset is swept by two repo-wide v0.9 commands (both read-only):

- **`make audit-generated-content`** includes the `generated_assets` surface: it
  asserts the registry entry exists, the descriptor resolves, `generated_owned` is
  explicit, `temporary` is false, the `source_bake_path` is provenance-only (never the
  final path), the final path is owned and not a Temp/Bake path, and catalog
  membership holds.
- **`make package-check PACK=…`** rejects any world pack whose final dependency set
  reaches a forbidden Houdini Temp/Bake path (`WF090_PACKAGE_FORBIDDEN_DEPENDENCY`)
  and verifies that generated-owned references resolve to a registry entry — so a
  relocated, registered rock packages cleanly while an un-relocated bake path is
  rejected.

## Output locations

```
procedural/generated/generated_assets/<asset_id>/descriptor.json
procedural/generated/worldforge_generated_asset_registry.json
procedural/reports/generated_assets/<asset_id>/validate_generated_asset_report.json
procedural/reports/generated_assets/<asset_id>/ue_generated_asset_report.json
```
