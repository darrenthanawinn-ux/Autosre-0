"""MCP server: Google Cloud tools (Configure + Monitor stages) built on the gcloud CLI.

Run standalone:  python -m autosre.mcp_servers.gcp_mcp   (stdio transport)
"""
import json
import subprocess
import time

import httpx
from mcp.server.fastmcp import FastMCP

from ..config import get_settings

mcp = FastMCP("autosre-gcp")


def _gcloud(*args: str) -> str:
    r = subprocess.run(["gcloud", *args, "--quiet"], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-2000:])
    return r.stdout


@mcp.tool()
def deploy_cloud_run(image: str, tag: str = "") -> dict:
    """Deploy an image to Cloud Run. With tag, deploys with no traffic so it can be verified first."""
    s = get_settings()
    args = ["run", "deploy", s.cloud_run_service, "--image", image, "--region", s.gcp_region,
            "--project", s.gcp_project, "--allow-unauthenticated", "--format", "json"]
    if tag:
        args += ["--no-traffic", "--tag", tag]
    out = json.loads(_gcloud(*args) or "{}")
    return {"revision": out.get("status", {}).get("latestCreatedRevisionName"), "url": out.get("status", {}).get("url")}


@mcp.tool()
def service_url() -> dict:
    """Public URL of the Cloud Run service."""
    s = get_settings()
    url = _gcloud("run", "services", "describe", s.cloud_run_service, "--region", s.gcp_region,
                  "--project", s.gcp_project, "--format", "value(status.url)").strip()
    return {"url": url}


@mcp.tool()
def health_check(url: str, path: str = "/healthz", attempts: int = 5) -> dict:
    """Probe the service; returns ok + average latency in ms."""
    lat, ok = [], 0
    for _ in range(attempts):
        t = time.time()
        try:
            r = httpx.get(url.rstrip("/") + path, timeout=10)
            ok += r.status_code == 200
        except httpx.HTTPError:
            pass
        lat.append((time.time() - t) * 1000)
        time.sleep(1)
    return {"ok": ok == attempts, "success": ok, "attempts": attempts, "avg_latency_ms": round(sum(lat) / len(lat), 1)}


@mcp.tool()
def error_count(minutes: int = 5) -> dict:
    """Count Cloud Logging entries with severity>=ERROR for the service in the last N minutes."""
    s = get_settings()
    flt = (f'resource.type="cloud_run_revision" AND resource.labels.service_name="{s.cloud_run_service}" '
           f'AND severity>=ERROR AND timestamp>="-PT{minutes}M"')
    out = _gcloud("logging", "read", flt, "--project", s.gcp_project, "--limit", "200", "--format", "json",
                  "--freshness", f"{minutes}m")
    return {"errors": len(json.loads(out or "[]"))}


@mcp.tool()
def previous_revision() -> dict:
    """Name of the last-known-good (second most recent) revision."""
    s = get_settings()
    out = _gcloud("run", "revisions", "list", "--service", s.cloud_run_service, "--region", s.gcp_region,
                  "--project", s.gcp_project, "--format", "json", "--limit", "2")
    revs = json.loads(out or "[]")
    return {"revision": revs[1]["metadata"]["name"] if len(revs) > 1 else None}


@mcp.tool()
def rollback(revision: str) -> dict:
    """Route 100% of traffic to a known-good revision."""
    s = get_settings()
    _gcloud("run", "services", "update-traffic", s.cloud_run_service, "--region", s.gcp_region,
            "--project", s.gcp_project, "--to-revisions", f"{revision}=100")
    return {"rolled_back_to": revision}


@mcp.tool()
def promote(revision: str) -> dict:
    """Route 100% of traffic to a (verified) revision."""
    s = get_settings()
    _gcloud("run", "services", "update-traffic", s.cloud_run_service, "--region", s.gcp_region,
            "--project", s.gcp_project, "--to-revisions", f"{revision}=100")
    return {"promoted": revision}


if __name__ == "__main__":
    mcp.run()
