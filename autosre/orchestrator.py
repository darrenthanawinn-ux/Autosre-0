"""CLI + webhook orchestrator.

CI jobs call:   python -m autosre.orchestrator <plan|secure|heal|deploy|monitor> [...]
Webhook mode:   python -m autosre.orchestrator serve     (GitLab issue events -> Code Agent)
"""
import argparse
import asyncio
import hmac
import os
import sys

from .agents.base import PolicyViolation
from .agents.code_agent import CodeAgent
from .agents.healing_agent import HealingAgent
from .agents.sre_agent import SREAgent
from .agents.security_agent import SecurityAgent
from .config import get_settings
from .hub import McpHub
from .llm import ClaudeLLM
from .state import StateStore


async def run_command(args: argparse.Namespace) -> int:
    s = get_settings()
    llm, state = ClaudeLLM(), StateStore(s.state_path)
    async with McpHub() as hub:
        kw = dict(hub=hub, llm=llm, state=state, settings=s)
        if args.cmd == "plan":
            await CodeAgent(**kw).run(int(args.issue))
        elif args.cmd == "secure":
            try:
                await SecurityAgent(**kw).run(branch=args.branch)
            except PolicyViolation as e:
                print(f"[governance] BLOCKED: {e}", file=sys.stderr)
                return 1
        elif args.cmd == "heal":
            await HealingAgent(**kw).run(pipeline_id=int(args.pipeline), branch=args.branch)
        elif args.cmd == "deploy":
            r = await SREAgent(**kw).deploy(args.image)
            return 0 if r["promoted"] else 1
        elif args.cmd == "monitor":
            r = await SREAgent(**kw).monitor()
            return 0 if r["healthy"] else 1
    return 0


def serve() -> None:
    """Webhook receiver: label an issue `autosre` and the swarm takes over."""
    import uvicorn
    from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

    app = FastAPI(title="AutoSRE-0 orchestrator")
    secret = os.environ.get("AUTOSRE_WEBHOOK_SECRET", "")

    async def _plan(iid: int) -> None:
        await run_command(argparse.Namespace(cmd="plan", issue=iid))

    @app.post("/webhook/gitlab")
    async def hook(req: Request, bg: BackgroundTasks, x_gitlab_token: str = Header(default="")):
        if not secret or not hmac.compare_digest(x_gitlab_token, secret):
            raise HTTPException(401, "bad token")
        body = await req.json()
        if body.get("object_kind") == "issue":
            labels = [l["title"] for l in body.get("labels", [])]
            if get_settings().trigger_label in labels and body["object_attributes"]["action"] in ("open", "update"):
                bg.add_task(_plan, body["object_attributes"]["iid"])
                return {"accepted": True}
        return {"accepted": False}

    @app.get("/healthz")
    def health():
        return {"ok": True}

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))


def main() -> None:
    p = argparse.ArgumentParser(prog="autosre")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    sub.add_parser("plan").add_argument("--issue", required=True)
    sub.add_parser("secure").add_argument("--branch", required=True)
    h = sub.add_parser("heal")
    h.add_argument("--pipeline", required=True)
    h.add_argument("--branch", required=True)
    sub.add_parser("deploy").add_argument("--image", required=True)
    sub.add_parser("monitor")
    args = p.parse_args()
    if args.cmd == "serve":
        serve()
    else:
        sys.exit(asyncio.run(run_command(args)))


if __name__ == "__main__":
    main()
