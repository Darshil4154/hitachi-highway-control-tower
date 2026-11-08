"""Copy demo-writable state; restore after recording; verify scored hashes."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .numbers import HANDBOOK, RUN_LOG, ROOT, sha256

BACKUP = ROOT / "video" / ".demo_backup"


def snapshot() -> dict:
    BACKUP.mkdir(parents=True, exist_ok=True)
    hitl = ROOT / "ui" / "hitl_decisions.json"
    if hitl.exists():
        shutil.copy2(hitl, BACKUP / "hitl_decisions.json")
    else:
        (BACKUP / "hitl_decisions.json").write_text("{}", encoding="utf-8")
    for name in ("desk.json", "history.jsonl"):
        src = ROOT / "config" / "policies" / name
        if src.exists():
            shutil.copy2(src, BACKUP / name)
    audit = ROOT / "traces" / "policy_audit.jsonl"
    if audit.exists():
        shutil.copy2(audit, BACKUP / "policy_audit.jsonl")
    # remember non-handbook policy files
    pols = sorted((ROOT / "config" / "policies").glob("*_v*.yaml"))
    (BACKUP / "policy_files.json").write_text(
        json.dumps([p.name for p in pols if p.name != "handbook_v1.yaml"]), encoding="utf-8")
    return {"handbook": sha256(HANDBOOK), "action_log": sha256(RUN_LOG)}


def restore(before: dict) -> dict:
    hitl_bak = BACKUP / "hitl_decisions.json"
    hitl = ROOT / "ui" / "hitl_decisions.json"
    if hitl_bak.exists():
        shutil.copy2(hitl_bak, hitl)
    for name in ("desk.json", "history.jsonl"):
        bak = BACKUP / name
        dst = ROOT / "config" / "policies" / name
        if bak.exists():
            shutil.copy2(bak, dst)
        elif dst.exists():
            dst.unlink()
    audit_bak = BACKUP / "policy_audit.jsonl"
    audit = ROOT / "traces" / "policy_audit.jsonl"
    if audit_bak.exists():
        shutil.copy2(audit_bak, audit)
    elif audit.exists():
        audit.unlink()
    # remove any demo-published profiles created during recording
    known = set(json.loads((BACKUP / "policy_files.json").read_text(encoding="utf-8")))
    for p in (ROOT / "config" / "policies").glob("*_v*.yaml"):
        if p.name != "handbook_v1.yaml" and p.name not in known:
            p.unlink()
    after = {"handbook": sha256(HANDBOOK), "action_log": sha256(RUN_LOG)}
    ok = after == before
    print("scored-run hash check:", "PASS" if ok else "FAIL")
    print("  handbook_v1", after["handbook"][:16], "unchanged" if after["handbook"] == before["handbook"] else "CHANGED")
    print("  action_log ", after["action_log"][:16], "unchanged" if after["action_log"] == before["action_log"] else "CHANGED")
    if not ok:
        raise SystemExit("scored artifacts changed - abort")
    return after
