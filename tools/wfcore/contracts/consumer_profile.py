#!/usr/bin/env python3
"""wfcore.contracts.consumer_profile -- WHO is calling, and what holds every time.

A profile is the importing game's IDENTITY plus its STANDING preferences: the
facts that are true of every request it will ever make. It is deliberately not a
request. Splitting the two is what lets a consumer make a hundred asks without
restating its capsule dimensions, and -- more importantly -- what stops a
per-request value from silently redefining the consumer.

WHY METRICS AND NOT ADJECTIVES
------------------------------
"Make it feel traversable" is unfalsifiable. ``max_step_height_cm`` is not. Every
downstream decision Core makes about terrain, clearance, and navigation resolves
against numbers the consumer supplied, so the profile carries the numbers rather
than the adjectives -- and where a number is not known, it carries the literal
``unknown`` instead of a zero (see ``contracts.check_measure`` for why that
distinction is load-bearing rather than pedantic).

WHY STANDING CONSTRAINTS ARE VALIDATED PER MEMBER, NOT AS A SET
---------------------------------------------------------------
``constraints.validate_constraint_set`` requires at least one acceptance-load-
bearing member, because a SET with none folds to vacuous SATISFIED and would
accept any world at all. That rail is correct for the thing being accepted -- a
world_request, an acceptance_criteria -- and wrong here: a profile is never
folded into an acceptance verdict, and a consumer whose standing preferences are
all soft is stating something perfectly coherent. So each standing constraint is
validated individually through the same taxonomy, and the set-level rail is
deliberately not applied. The alternative would force every consumer to invent a
hard invariant it does not have, which is how declarations become decorative.
"""

from typing import Any, Dict, List

from .. import constraints as K
from .. import tri
from ..failure import FailureCode as C
from . import (Check, UNKNOWN, check_enum, check_is_object, check_measure,
               check_no_unknown, check_object_field, check_required,
               check_schema_version, check_str, check_str_list, prefixed,
               require_caller_owned)

RT_CONSUMER_PROFILE = "wf.core.consumer_profile.v1"

# The Core contract generations this build can speak. A consumer pinning anything
# else is rejected (WF1212) rather than best-effort parsed: a profile written
# against a different generation may use the same field names for different
# meanings, and "mostly parsed" is the worst of the three possible outcomes.
SUPPORTED_CONTRACT_VERSIONS = ("wf.core.contract.v1",)

# --------------------------------------------------------------------------- #
# closed vocabularies. Each is a SHAPE of game, never a game: these words must
# stay generic enough that two unrelated consumers can both find themselves here.
# --------------------------------------------------------------------------- #
GAME_TYPES = (
    "open_world",
    "zoned_world",
    "linear_level_sequence",
    "arena",
    "sandbox",
    "simulation",
    "strategy_overview",
    "narrative_exploration",
)

VISUAL_LANGUAGES = (
    "photoreal",
    "stylized",
    "painterly",
    "graphic_flat",
    "blockout_greybox",
    "abstract",
)

CAMERA_MODES = (
    "first_person",
    "third_person_close",
    "third_person_far",
    "isometric",
    "top_down",
    "orbital",
    "fixed",
)

# The locomotion modes a consumer's player may have. Core reads these to decide
# which clearances matter -- a consumer that cannot climb does not need climbable
# geometry, and generating it anyway is wasted work the consumer never asked for.
#
# ``jump`` was added after the FIRST REAL CALLER exposed its absence: that game's
# character binds ACharacter::Jump, and the closed vocabulary had no member for
# it, so the profile could only UNDERSTATE the player's real mobility. That is a
# live defect and not a cosmetic one -- vertical reach is exactly the kind of
# clearance Core decides generation from, and a consumer silently described as
# unable to jump would have geometry authored for a shorter reach than its player
# actually has.
#
# The consumer worked around it honestly (declaring the shortfall in notes rather
# than smuggling an out-of-vocabulary string past the enum), which is what made
# the gap visible instead of silently absorbed. Fixed generically here, in Core,
# because jumping is a property of players in general and not of any one game --
# fixing it in that consumer's adapter would have left the next caller to
# rediscover it.
LOCOMOTION_MODES = (
    "walk", "jump", "sprint", "crouch", "climb", "swim", "fly", "vehicle",
    "teleport",
)

PLAYER_METRIC_FIELDS = (
    "capsule_height_cm",
    "capsule_radius_cm",
    "eye_height_cm",
    "max_step_height_cm",
    "max_walk_slope_deg",
    "max_jump_height_cm",
)

CAMERA_METRIC_FIELDS = (
    "camera_mode",
    "horizontal_fov_deg",
    "near_clip_cm",
    "far_clip_cm",
)

# Engine + project identity. Both name things in the CONSUMER's world, which is
# why the whole object is caller-owned and has no default.
ENGINE_IDENTITY_FIELDS = ("engine_version", "project_identifier")

CONSUMER_PROFILE_REQUIRED = (
    "consumer_id",
    "contract_version",
    "game_type",
    "visual_language",
    "locomotion_modes",
    "player_metrics",
    "camera_metrics",
    "engine_identity",
    "declared_capabilities",
    "schema_version",
)

CONSUMER_PROFILE_ALLOWED = CONSUMER_PROFILE_REQUIRED + (
    "standing_constraints",
    "unknown_resolution_owner",
    "display_name",
    "created_by",
    "created_at",
    "report_type",
    "meta",
    "notes",
)

# Fields Core must never invent. ``consumer_id`` and ``engine_identity`` name the
# caller's project; ``declared_capabilities`` states what the caller is willing to
# accept, and a Core-chosen default there would be Core deciding what the game can
# live with.
CALLER_OWNED_FIELDS = ("consumer_id", "engine_identity", "declared_capabilities")

_P = "cp::"


def validate_consumer_profile(obj: Any, strict: bool = False) -> List[Check]:
    """Validate a consumer profile. Cross-field rails carry the honesty."""
    code = C.CORE_CONSUMER_PROFILE_INVALID
    ch = check_is_object(obj, code, _P, "consumer_profile")
    if ch:
        return ch

    ch += check_required(obj, CONSUMER_PROFILE_REQUIRED, code, _P)
    ch += check_no_unknown(obj, CONSUMER_PROFILE_ALLOWED, code, _P, strict)
    ch += check_str(obj, "consumer_id", code, _P)
    ch += check_enum(obj, "game_type", GAME_TYPES, code, _P)
    ch += check_enum(obj, "visual_language", VISUAL_LANGUAGES, code, _P)
    ch += check_schema_version(obj, RT_CONSUMER_PROFILE, code, _P)

    # --- contract version: unsupported is a hard stop, not a best effort ------
    cv = obj.get("contract_version")
    ok = cv in SUPPORTED_CONTRACT_VERSIONS
    ch.append((_P + "contract_version_supported", ok,
               "contract_version={!r} must be one of {}; a profile written "
               "against another generation may reuse these field names with "
               "different meanings".format(cv, SUPPORTED_CONTRACT_VERSIONS),
               None if ok else C.CORE_CONTRACT_VERSION_UNSUPPORTED))

    # --- locomotion + capabilities -------------------------------------------
    ch += check_str_list(obj, "locomotion_modes", code, _P, min_len=1)
    modes = obj.get("locomotion_modes")
    if isinstance(modes, (list, tuple)):
        unknown_modes = sorted({m for m in modes if m not in LOCOMOTION_MODES})
        ok = not unknown_modes
        ch.append((_P + "locomotion_modes_in_vocabulary", ok,
                   "locomotion mode(s) {} are outside {}".format(
                       unknown_modes, LOCOMOTION_MODES) if unknown_modes
                   else "all locomotion modes known", None if ok else code))

    # Capability NAMES are not bounded here on purpose. The capability registry is
    # a different authority (provider selection); a second closed vocabulary in
    # this module would drift from it and start rejecting capabilities that
    # actually exist. Structure is this contract's business; resolution is not.
    ch += check_str_list(obj, "declared_capabilities", code, _P, min_len=1)

    # --- identity of the caller's project ------------------------------------
    ch += check_object_field(obj, "engine_identity", ENGINE_IDENTITY_FIELDS,
                             code, _P)
    eng = obj.get("engine_identity")
    if isinstance(eng, dict):
        for fld in ENGINE_IDENTITY_FIELDS:
            ch += check_str(eng, fld, code, _P + "engine_identity.")

    # --- metrics: positive numbers or an explicit unknown ---------------------
    ch += check_object_field(obj, "player_metrics", PLAYER_METRIC_FIELDS,
                             code, _P)
    pm = obj.get("player_metrics")
    if isinstance(pm, dict):
        for fld in PLAYER_METRIC_FIELDS:
            ch += check_measure(pm, fld, code, _P + "player_metrics.")

    ch += check_object_field(obj, "camera_metrics", CAMERA_METRIC_FIELDS,
                             code, _P)
    cm = obj.get("camera_metrics")
    if isinstance(cm, dict):
        ch += check_enum(cm, "camera_mode", CAMERA_MODES, code,
                         _P + "camera_metrics.")
        for fld in ("horizontal_fov_deg", "near_clip_cm", "far_clip_cm"):
            ch += check_measure(cm, fld, code, _P + "camera_metrics.")

    ch += _rail_metric_coherence(obj, code)
    ch += _rail_unknown_has_owner(obj, code)
    ch += _rail_standing_constraints(obj, strict, code)
    return ch


def _numeric(container: Any, field: str):
    """Return the value only when it is a real number (not unknown, not a bool)."""
    if not isinstance(container, dict):
        return None
    v = container.get(field)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    return None


def _rail_metric_coherence(obj: Dict[str, Any], code: str) -> List[Check]:
    """Metrics that contradict each other describe no character that can exist.

    Each of these passes every per-field check -- they are all positive numbers --
    and each produces a world built for a body the consumer does not have. Only a
    cross-field rail catches them, which is exactly why they live in the validator
    rather than in a paragraph of documentation nobody reads at authoring time.
    """
    out: List[Check] = []
    pm = obj.get("player_metrics")
    height = _numeric(pm, "capsule_height_cm")
    radius = _numeric(pm, "capsule_radius_cm")
    step = _numeric(pm, "max_step_height_cm")
    eye = _numeric(pm, "eye_height_cm")
    slope = _numeric(pm, "max_walk_slope_deg")

    if height is not None and radius is not None:
        ok = (radius * 2) <= height
        out.append((_P + "capsule_is_a_capsule", ok,
                    "capsule_radius_cm={} implies a diameter of {} which exceeds "
                    "capsule_height_cm={}; that is a sphere, and clearance "
                    "generated for it fits nothing".format(radius, radius * 2, height),
                    None if ok else code))

    if height is not None and step is not None:
        ok = step < height
        out.append((_P + "step_height_below_capsule_height", ok,
                    "max_step_height_cm={} is not below capsule_height_cm={}; a "
                    "step taller than the character is not a step, and terrain "
                    "authored to it is impassable".format(step, height),
                    None if ok else code))

    if height is not None and eye is not None:
        ok = eye <= height
        out.append((_P + "eye_height_within_capsule", ok,
                    "eye_height_cm={} exceeds capsule_height_cm={}; the camera "
                    "would sit outside the body it belongs to".format(eye, height),
                    None if ok else code))

    if slope is not None:
        ok = 0 < slope < 90
        out.append((_P + "walk_slope_is_walkable", ok,
                    "max_walk_slope_deg={} must be in (0, 90); 90 degrees or more "
                    "is a wall, and terrain generated against it would be graded "
                    "as walkable when it is not".format(slope),
                    None if ok else code))

    cm = obj.get("camera_metrics")
    near = _numeric(cm, "near_clip_cm")
    far = _numeric(cm, "far_clip_cm")
    if near is not None and far is not None:
        ok = near < far
        out.append((_P + "clip_planes_ordered", ok,
                    "near_clip_cm={} must be less than far_clip_cm={}; an "
                    "inverted pair renders nothing while every field check "
                    "passes".format(near, far), None if ok else code))
    return out


def _rail_unknown_has_owner(obj: Dict[str, Any], code: str) -> List[Check]:
    """An unknown metric must name who resolves it.

    ``unknown`` is the honest answer, and it is allowed. What is not allowed is an
    unknown with nobody attached: it blocks acceptance forever, and a permanent
    blocker with no owner is indistinguishable from a bug in Core. This mirrors
    ``DECLARED_UNKNOWN.resolution_owner`` in the constraint taxonomy -- the same
    rule, applied to metrics instead of constraints.
    """
    unknown_fields: List[str] = []
    for group, fields in (("player_metrics", PLAYER_METRIC_FIELDS),
                          ("camera_metrics", CAMERA_METRIC_FIELDS)):
        container = obj.get(group)
        if not isinstance(container, dict):
            continue
        for fld in fields:
            if container.get(fld) == UNKNOWN:
                unknown_fields.append("{}.{}".format(group, fld))

    if not unknown_fields:
        return [(_P + "unknown_metric_names_resolution_owner", True,
                 "no metric is declared unknown", None)]

    owner = obj.get("unknown_resolution_owner")
    ok = isinstance(owner, str) and bool(owner.strip())
    return [(_P + "unknown_metric_names_resolution_owner", ok,
             "metric(s) {} are declared {!r} but unknown_resolution_owner={!r}; "
             "an unknown blocks acceptance until measured, so it must name the "
             "consumer-side owner who will measure it".format(
                 unknown_fields, UNKNOWN, owner),
             None if ok else code)]


def _rail_standing_constraints(obj: Dict[str, Any], strict: bool,
                               code: str) -> List[Check]:
    """Validate standing constraints through the taxonomy, member by member.

    See the module docstring for why the SET-level rail is not applied here.
    """
    out: List[Check] = []
    standing = obj.get("standing_constraints")
    if standing is None:
        return [(_P + "standing_constraints_absent_is_legal", True,
                 "no standing constraints declared; the profile states identity "
                 "only", None)]

    if not isinstance(standing, (list, tuple)):
        return [(_P + "standing_constraints_is_list", False,
                 "standing_constraints must be a list, got {}".format(
                     type(standing).__name__), code)]

    for idx, c in enumerate(standing):
        out += prefixed(K.validate_constraint(c, strict=strict),
                        "{}standing[{}].".format(_P, idx))

    ids = [c.get("constraint_id") for c in standing if isinstance(c, dict)]
    dupes = sorted({i for i in ids if i is not None and ids.count(i) > 1})
    ok = not dupes
    out.append((_P + "standing_constraint_ids_unique", ok,
                "duplicate standing constraint_id(s) {}; a duplicate lets one "
                "standing preference silently shadow another".format(dupes)
                if dupes else "all standing constraint_ids unique",
                None if ok else code))
    return out


def declared_capability_verdict(profile: Dict[str, Any],
                                capability: str) -> str:
    """Tri-verdict for "may Core use this capability for this consumer?".

    SATISFIED when the consumer declared it. VIOLATED when the consumer declared a
    capability list that does not contain it -- a declared list is a closed
    statement, so absence is a refusal, not a gap. UNKNOWN only when there is no
    list to read at all, because then nothing has been stated in either direction
    and inventing a verdict would be Core answering on the consumer's behalf.
    """
    declared = profile.get("declared_capabilities")
    if not isinstance(declared, (list, tuple)):
        return tri.UNKNOWN
    return tri.from_bool(capability in declared, measured=True)


def build_consumer_profile(**over: Any) -> Dict[str, Any]:
    """Build a profile. ``CALLER_OWNED_FIELDS`` are REQUIRED -- no defaults.

    The defaults below describe only what Core legitimately owns: its own schema
    identity and contract generation. Everything that describes the CONSUMER --
    who it is, what engine and project it is, what it can accept -- must be
    supplied, and omitting any of it raises :class:`ContractAuthorityError`.

    Note what is deliberately NOT defaulted beyond the caller-owned set: nothing
    here invents a game_type or a visual_language either. Those carry defaults
    only in the sense that a caller may override them -- see ``_example_*``, which
    is a TEST fixture and says so.
    """
    require_caller_owned(over, CALLER_OWNED_FIELDS, "consumer_profile")
    d: Dict[str, Any] = dict(
        contract_version=SUPPORTED_CONTRACT_VERSIONS[0],
        schema_version=RT_CONSUMER_PROFILE,
        report_type=RT_CONSUMER_PROFILE,
    )
    d.update(over)
    return d


def _example_consumer_profile(**over: Any) -> Dict[str, Any]:
    """Canonical-valid profile. ``**over`` spawns the known-bads.

    Every value naming the caller is a neutral placeholder. Core owns no game's
    vocabulary, and an example is still Core: a plausible-looking name here would
    be the first place a real consumer's identity leaks in, and it would read as
    harmless for exactly as long as it took to matter.
    """
    d: Dict[str, Any] = dict(
        consumer_id="consumer_placeholder",
        engine_identity={
            "engine_version": "0.0.0",
            "project_identifier": "project_placeholder",
        },
        declared_capabilities=[
            "terrain.heightfield",
            "population.scatter",
            "navigation.bake",
        ],
        game_type="open_world",
        visual_language="stylized",
        locomotion_modes=["walk", "sprint", "crouch"],
        player_metrics={
            "capsule_height_cm": 180.0,
            "capsule_radius_cm": 42.0,
            "eye_height_cm": 165.0,
            "max_step_height_cm": 45.0,
            "max_walk_slope_deg": 44.0,
            "max_jump_height_cm": 120.0,
        },
        camera_metrics={
            "camera_mode": "third_person_close",
            "horizontal_fov_deg": 90.0,
            "near_clip_cm": 10.0,
            "far_clip_cm": 200000.0,
        },
        standing_constraints=[
            {
                "constraint_id": "sc_step_clearance",
                "constraint_class": K.HARD_INVARIANT,
                "subject": "navigation.step_height",
                "detail": ("walkable ground must never require a step taller "
                           "than the declared max_step_height_cm"),
            },
            {
                "constraint_id": "sc_silhouette_variety",
                "constraint_class": K.SOFT_PREFERENCE,
                "subject": "composition.silhouette_variety",
                "detail": "prefer varied skyline silhouettes over uniform ones",
                "weight": 0.4,
            },
        ],
    )
    d.update(over)
    return build_consumer_profile(**d)
