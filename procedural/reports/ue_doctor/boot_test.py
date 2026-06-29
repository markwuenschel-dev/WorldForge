import json, os, unreal
root = os.path.normpath(unreal.Paths.project_dir())
out = os.path.join(root, "procedural", "reports", "ue_doctor", "boot_test_report.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    json.dump({"boot": True, "python_ok": True}, f)
unreal.log("[ue-doctor] boot ok")
