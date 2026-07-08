#!/usr/bin/env python3
"""runtime_bridge.py — WorldForge v1.6 UE/NeoStack live-bridge detection.

Single source of truth for "is a live Unreal editor available to run runtime
scenarios right now?". The NeoStack plugin writes Saved/NeoStackAI/runtime.json
when the editor is open with the plugin enabled; its absence means live runtime
execution is impossible, and every live-run gate must fail CLOSED
(RUNTIME_LIVE_RUN_PENDING) rather than fake a completion. Stdlib only.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

NEOSTACK_RUNTIME_REL = "Saved/NeoStackAI/runtime.json"


def bridge_runtime_path():
    return REPO_ROOT / NEOSTACK_RUNTIME_REL


def ue_bridge_live():
    """True iff the NeoStack runtime handshake file exists (editor is open)."""
    return bridge_runtime_path().is_file()


def bridge_status_detail():
    if ue_bridge_live():
        return "UE/NeoStack bridge LIVE ({})".format(NEOSTACK_RUNTIME_REL)
    return ("UE/NeoStack bridge OFFLINE — no {} (open the editor with the "
            "NeoStackAI plugin to run live scenarios)".format(NEOSTACK_RUNTIME_REL))


if __name__ == "__main__":
    print(bridge_status_detail())
