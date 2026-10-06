"""Security & Governance Agent — Secure stage. Scan, auto-patch, enforce policy."""
import json
import re
import subprocess
from pathlib import Path

from .base import Agent, PolicyViolation, validate_changes

SYSTEM = """You are the Security Agent of AutoSRE-0. Fix the reported code vulnerability with the smallest safe change.
Return JSON: {"summary": str, "files": [{"path": str, "action": "update", "content": str}]} with FULL file contents."""


def run_scanners(app_dir: str = "app", req: str = "app/requirements.txt") -> dict:
    """Run SAST (bandit) and SCA (pip-audit); returns normalised findings."""
    findings = {"deps": [], "code": []}
    b = subprocess.run(["bandit", "-r", app_dir, "-f", "json", "-q"], capture_output=True, text=True)
    try:
        for r in json.loads(b.stdout or "{}").get("results", []):
            findings["code"].append({"file": r["filename"], "line": r["line_number"], "severity": r["issue_severity"],
                                     "test": r["test_id"], "text": r["issue_text"]})
    except json.JSONDecodeError:
        pass
    a = subprocess.run(["pip-audit", "-r", req, "-f", "json", "--progress-spinner", "off"], capture_output=True, text=True)
    try:
        for d in json.loads(a.stdout or "{}").get("dependencies", []):
            for v in d.get("vulns", []):
                if v.get("fix_versions"):
                    findings["deps"].append({"name": d["name"], "version": d["version"], "fix": v["fix_versions"][-1], "id": v["id"]})
    except json.JSONDecodeError:
        pass
    return findings


def bump_requirements(text: str, deps: list[dict]) -> str:
    """Deterministic dependency patching (no LLM needed, no hallucinated versions)."""
    for d in deps:
        text = re.sub(rf"(?im)^({re.escape(d['name'])})\s*(==|>=|~=)\s*[\w.\-]+", rf"\1=={d['fix']}", text)
    return text


class SecurityAgent(Agent):
    name = "security-agent"

    async def run(self, branch: str, findings: dict | None = None) -> dict:
        findings = findings if findings is not None else run_scanners()
        s = self.settings
        actions, notes = [], []

        if findings["deps"]:
            path = Path("app/requirements.txt")
            old = path.read_text()
            new = bump_requirements(old, findings["deps"])
            if new != old:
                actions.append({"action": "update", "file_path": "app/requirements.txt", "content": new})
                notes.append("bumped " + ", ".join(f"{d['name']}→{d['fix']}" for d in findings["deps"]))

        for f in [f for f in findings["code"] if f["severity"] in ("HIGH", "MEDIUM")][:3]:
            src = Path(f["file"]).read_text()
            plan = self.llm.ask_json(SYSTEM, f"Finding: {f}\n\nFILE {f['file']}:\n{src}")
            for c in validate_changes(plan["files"], s):
                actions = [a for a in actions if a["file_path"] != c["file_path"]] + [c | {"action": "update"}]
            notes.append(plan["summary"])

        if actions:
            await self.hub.call("commit_files", branch=branch,
                                message="fix(security): autonomous patch\n\n[autosre] " + "; ".join(notes), actions=actions)
            self.say(f"Committed security patch: {'; '.join(notes)}")
        else:
            self.say("No patchable findings")

        # Governance gate: unresolved HIGH findings fail the pipeline even after patching.
        remaining_high = [f for f in findings["code"] if f["severity"] == "HIGH"] if not actions else []
        if remaining_high:
            raise PolicyViolation(f"{len(remaining_high)} unresolved HIGH findings")
        return {"patched": bool(actions), "notes": notes}
