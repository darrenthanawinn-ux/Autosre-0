"""Pipeline Healing Agent — Verify stage. Failed job -> diagnose -> patch -> re-run, bounded."""
import re

from .base import Agent, PolicyViolation, validate_changes

SYSTEM = """You are the Pipeline Healing Agent of AutoSRE-0. You receive failed CI job logs and the implicated files.
Classify the failure and fix it.
Return JSON: {"kind": "code|flaky|infra", "diagnosis": str, "summary": str,
"files": [{"path": str, "action": "update|create", "content": str}]}.
Use kind=flaky/infra with empty files when the failure is transient. Never edit CI config or autosre/."""

SELF_JOBS = {"heal", "security:patch"}


class HealingAgent(Agent):
    name = "healing-agent"

    async def run(self, pipeline_id: int, branch: str) -> dict:
        s = self.settings
        failed = [j for j in (await self.hub.call("get_failed_jobs", pipeline_id=pipeline_id))["jobs"]
                  if j["name"] not in SELF_JOBS]
        if not failed:
            self.say("Nothing to heal")
            return {"healed": False, "reason": "no failed jobs"}

        key = f"heal:{branch}"
        attempt = self.state.incr(key)
        if attempt > s.max_heal_attempts:
            issue = await self.hub.call(
                "create_issue", title=f"[AutoSRE] Healing exhausted on {branch}",
                description="Autonomous healing hit its attempt budget.\n\n" +
                            "\n".join(f"- `{j['name']}`" for j in failed))
            self.say(f"Budget exhausted; opened incident issue #{issue['iid']}")
            return {"healed": False, "reason": "budget exhausted", "issue": issue}

        logs = "\n\n".join(f"### {j['name']} ({j['stage']})\n{j['trace_tail']}" for j in failed)
        paths = set(re.findall(r"((?:app|tests)/[\w/\-.]+\.py)", logs))
        files = {}
        for p in sorted(paths)[:6]:
            try:
                files[p] = (await self.hub.call("read_file", path=p, ref=branch))["content"][:8000]
            except Exception:  # noqa: BLE001 — file may not exist on branch
                pass

        plan = self.llm.ask_json(
            SYSTEM, f"ATTEMPT {attempt}/{s.max_heal_attempts}\n\nFAILED JOBS:\n{logs}\n\nFILES:\n" +
            "\n".join(f"--- {p} ---\n{c}" for p, c in files.items()), max_tokens=8000)

        if plan["kind"] in ("flaky", "infra") or not plan["files"]:
            for j in failed:
                await self.hub.call("retry_job", job_id=j["id"])
            self.say(f"Transient failure ({plan['kind']}); retried {len(failed)} job(s)")
            return {"healed": True, "kind": plan["kind"]}

        try:
            actions = validate_changes(plan["files"], s)
        except PolicyViolation as e:
            self.say(f"Governance blocked patch: {e}")
            return {"healed": False, "reason": str(e)}
        await self.hub.call("commit_files", branch=branch,
                            message=f"fix(ci): {plan['summary']}\n\n[autosre] {plan['diagnosis']}", actions=actions)
        self.say(f"Pushed fix (attempt {attempt}): {plan['summary']}")
        return {"healed": True, "kind": "code", "attempt": attempt}
