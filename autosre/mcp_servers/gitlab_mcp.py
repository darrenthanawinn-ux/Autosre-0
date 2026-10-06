"""MCP server: GitLab tools (Plan, Create, Verify, Release stages).

Run standalone:  python -m autosre.mcp_servers.gitlab_mcp   (stdio transport)
"""
import base64
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

from ..config import get_settings

mcp = FastMCP("autosre-gitlab")


def _api(method: str, path: str, **kw) -> Any:
    s = get_settings()
    url = f"{s.gitlab_url}/api/v4/projects/{s.project_id}{path}"
    r = httpx.request(method, url, headers={"PRIVATE-TOKEN": s.gitlab_token}, timeout=60, **kw)
    r.raise_for_status()
    if "application/json" in r.headers.get("content-type", ""):
        return r.json()
    return {"text": r.text}


@mcp.tool()
def get_issue(iid: int) -> dict:
    """Fetch an issue (title, description, labels)."""
    i = _api("GET", f"/issues/{iid}")
    return {"iid": i["iid"], "title": i["title"], "description": i.get("description") or "", "labels": i["labels"]}


@mcp.tool()
def list_files(ref: str = "main") -> dict:
    """List all file paths in the repository at ref."""
    files, page = [], 1
    while True:
        items = _api("GET", "/repository/tree", params={"ref": ref, "recursive": True, "per_page": 100, "page": page})
        if not items:
            break
        files += [i["path"] for i in items if i["type"] == "blob"]
        page += 1
        if page > 20:
            break
    return {"files": files}


@mcp.tool()
def read_file(path: str, ref: str = "main") -> dict:
    """Read a UTF-8 file from the repository."""
    f = _api("GET", f"/repository/files/{quote(path, safe='')}", params={"ref": ref})
    return {"path": path, "content": base64.b64decode(f["content"]).decode("utf-8", "replace")}


@mcp.tool()
def create_branch(branch: str, ref: str = "main") -> dict:
    """Create a branch from ref (idempotent)."""
    try:
        _api("POST", "/repository/branches", params={"branch": branch, "ref": ref})
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 400:  # 400 = already exists
            raise
    return {"branch": branch}


@mcp.tool()
def commit_files(branch: str, message: str, actions: list[dict]) -> dict:
    """Atomic commit. actions: [{action: create|update|delete, file_path, content}]"""
    c = _api("POST", "/repository/commits", json={"branch": branch, "commit_message": message, "actions": actions})
    return {"sha": c["id"], "web_url": c.get("web_url")}


@mcp.tool()
def create_merge_request(source_branch: str, title: str, description: str, target_branch: str = "main") -> dict:
    """Open a merge request."""
    mr = _api("POST", "/merge_requests", json={
        "source_branch": source_branch, "target_branch": target_branch, "title": title,
        "description": description, "remove_source_branch": True, "squash": True})
    return {"iid": mr["iid"], "web_url": mr["web_url"]}


@mcp.tool()
def auto_merge(mr_iid: int) -> dict:
    """Merge when the pipeline succeeds (hands-off release gate: security + tests must pass)."""
    _api("PUT", f"/merge_requests/{mr_iid}/merge", json={"merge_when_pipeline_succeeds": True, "squash": True})
    return {"mr_iid": mr_iid, "auto_merge": True}


@mcp.tool()
def get_failed_jobs(pipeline_id: int) -> dict:
    """Failed jobs of a pipeline with the tail of each job trace."""
    jobs = _api("GET", f"/pipelines/{pipeline_id}/jobs", params={"scope": "failed", "per_page": 50})
    out = []
    for j in jobs:
        trace = _api("GET", f"/jobs/{j['id']}/trace").get("text", "")
        out.append({"id": j["id"], "name": j["name"], "stage": j["stage"], "trace_tail": trace[-6000:]})
    return {"jobs": out}


@mcp.tool()
def retry_job(job_id: int) -> dict:
    """Retry a job (used for flaky/infra failures)."""
    _api("POST", f"/jobs/{job_id}/retry")
    return {"retried": job_id}


@mcp.tool()
def create_issue(title: str, description: str, labels: str = "autosre") -> dict:
    """Open an issue (incident reports, escalations)."""
    i = _api("POST", "/issues", json={"title": title, "description": description, "labels": labels})
    return {"iid": i["iid"], "web_url": i["web_url"]}


@mcp.tool()
def comment_issue(iid: int, body: str) -> dict:
    """Comment on an issue."""
    _api("POST", f"/issues/{iid}/notes", json={"body": body})
    return {"ok": True}


if __name__ == "__main__":
    mcp.run()
