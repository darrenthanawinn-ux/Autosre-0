"""Code Agent — Plan + Create stages. Issue -> branch -> commit -> MR -> auto-merge gate."""
import re

from .base import Agent, validate_changes

SYSTEM = """You are the Code Agent of AutoSRE-0, an autonomous engineer.
Given an issue and the current repository files, produce the minimal complete change set that
resolves the issue, including tests. Never touch CI config, deploy files, or the autosre/ package.
Return JSON: {"summary": str, "files": [{"path": str, "action": "create|update|delete", "content": str}]}.
Provide FULL file contents for create/update."""

CONTEXT_DIRS = ("app/", "tests/")


class CodeAgent(Agent):
    name = "code-agent"

    async def run(self, issue_iid: int) -> dict:
        s = self.settings
        issue = await self.hub.call("get_issue", iid=issue_iid)
        self.say(f"Planning issue #{issue_iid}: {issue['title']}")
        tree = (await self.hub.call("list_files", ref=s.default_branch))["files"]

        context = {}
        for p in tree:
            if p.startswith(CONTEXT_DIRS) and p.endswith((".py", ".txt", ".md", ".toml")) and len(context) < 12:
                context[p] = (await self.hub.call("read_file", path=p, ref=s.default_branch))["content"][:8000]

        plan = self.llm.ask_json(
            SYSTEM,
            f"ISSUE #{issue['iid']}: {issue['title']}\n{issue['description']}\n\n"
            f"FILE TREE:\n{chr(10).join(tree)}\n\nFILES:\n"
            + "\n".join(f"--- {p} ---\n{c}" for p, c in context.items()),
            max_tokens=8000,
        )
        actions = validate_changes(plan["files"], s)
        existing = set(tree)
        for a in actions:  # normalise create/update against the real tree
            if a["action"] != "delete":
                a["action"] = "update" if a["file_path"] in existing else "create"

        slug = re.sub(r"[^a-z0-9]+", "-", issue["title"].lower()).strip("-")[:40]
        branch = f"autosre/{issue_iid}-{slug}"
        await self.hub.call("create_branch", branch=branch, ref=s.default_branch)
        commit = await self.hub.call("commit_files", branch=branch,
                                     message=f"feat: {issue['title']} (#{issue_iid})\n\n[autosre] {plan['summary']}",
                                     actions=actions)
        mr = await self.hub.call(
            "create_merge_request", source_branch=branch, target_branch=s.default_branch,
            title=f"[AutoSRE] {issue['title']}",
            description=f"Closes #{issue_iid}\n\n{plan['summary']}\n\n_Opened autonomously by AutoSRE-0 Code Agent._")
        await self.hub.call("auto_merge", mr_iid=mr["iid"])
        self.state.set(f"issue:{issue_iid}", {"branch": branch, "mr": mr["iid"], "sha": commit["sha"]})
        self.say(f"MR !{mr['iid']} opened, set to merge when pipeline succeeds")
        return {"branch": branch, "mr": mr}
