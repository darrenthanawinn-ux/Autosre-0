# AutoSRE-0 — The Autonomous Self-Healing Enterprise Pipeline

> Set the intent. Walk away. A swarm of agents plans, builds, secures, ships, and operates it — and fixes itself when it breaks.

**Life After Code: GitLab Transcend Hackathon** · Autonomy level: **hands-off** · Lifecycle stages: **8/9** · Cloud: **Google Cloud Run**

## The problem

Writing code is no longer the bottleneck. Everything after the commit — failing pipelines, CVEs, flaky deploys, 2 a.m. rollbacks — still eats engineering time. AutoSRE-0 automates that whole post-code lifecycle.

## What happens when you label an issue `autosre`

1. **Plan/Create** — the **Code Agent** reads the issue and repo, commits an implementation with tests, opens an MR and arms merge-when-green.
2. **Verify** — CI runs tests. If anything fails, the **Healing Agent** reads the logs, classifies the failure (code / flaky / infra), pushes a fix or retries, within a bounded budget.
3. **Secure** — the **Security & Governance Agent** runs SAST and dependency audit, patches what it can (dependency bumps deterministically, code fixes via Claude), and blocks merge on unresolved HIGH findings.
4. **Package/Release** — container image to Artifact Registry, tagged GitLab release.
5. **Configure** — the **Cloud SRE Agent** deploys a zero-traffic canary to Cloud Run, health-checks it, promotes it.
6. **Monitor** — it watches live health and error logs; on SLO breach it rolls back to the last good revision and files an incident report.

No human touches anything between the issue and production.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). In short:

- **4 agents** (`autosre/agents/`): Code, Security/Governance, Healing, Cloud SRE
- **2 MCP servers** (`autosre/mcp_servers/`): GitLab and Google Cloud; agents act only through MCP tool calls via `McpHub`
- **Claude** for reasoning, with strict JSON outputs and a policy layer that validates every proposed change
- **GitLab CI/CD** as the nervous system: each agent's commit triggers the next stage

## Repo layout

```
autosre/            agents, MCP servers, orchestrator, hub, policy guardrails
agents/*.yaml       declarative agent manifests
app/                demo FastAPI service the swarm evolves and deploys
deploy/             Cloud Run manifest + GCP bootstrap script
tests/              unit tests (agents run against fake hub/LLM)
.gitlab-ci.yml      the 8-stage pipeline
Dockerfile          app image   |   Dockerfile.agents  orchestrator image
policy.yaml         governance policy
```

## Setup (about 15 minutes)

1. **GitLab project**: push this repo. Enable *Settings → Merge requests → Pipelines must succeed*.
2. **CI/CD variables** (Settings → CI/CD → Variables):
   | Variable | Notes |
   |---|---|
   | `AUTOSRE_GITLAB_TOKEN` | Project access token, `api` scope, Maintainer role (masked) |
   | `ANTHROPIC_API_KEY` | masked |
   | `GCP_PROJECT_ID`, `GCP_REGION` | e.g. `us-central1` |
   | `GCP_SA_KEY` | **File** type; produced by the bootstrap script |
   | `CLOUD_RUN_SERVICE` | optional, default `autosre-demo` |
3. **Google Cloud**: `GCP_PROJECT_ID=<id> ./deploy/bootstrap_gcp.sh`
4. **Trigger path** (pick one):
   - *Webhook*: deploy `Dockerfile.agents` to Cloud Run (`python -m autosre.orchestrator serve`), set `AUTOSRE_WEBHOOK_SECRET`, add a GitLab Issues webhook to `/webhook/gitlab` with the same secret token.
   - *Trigger API*: start a pipeline with variable `AUTOSRE_ISSUE_IID=<n>`; the `plan:issue-to-mr` job runs the Code Agent.
5. Create an issue, add the label `autosre`, and walk away.

## Local development

```bash
pip install -r requirements.txt
pytest -q          # agents are tested against fake MCP hub + fake LLM
```

## Safety design

- Protected paths: agents cannot rewrite CI config, deploy files, policy or the agent code itself.
- Dependency fixes are deterministic (from `pip-audit`), never invented by the model.
- Heal budget of 3, then an incident issue rather than an infinite loop.
- Canary-before-promote and automatic rollback on SLO breach.
- Full pipeline must be green before auto-merge.

## Honest scope notes

- The agents use the GitLab REST API, MCP, and the Anthropic API. `agents/*.yaml` are declarative manifests; map them to your GitLab Duo Agent Platform's current custom-agent/flow schema when registering.
- The 9th stage (Govern/Manage beyond policy-as-code) is intentionally out of scope.
- Production hardening to consider: Workload Identity Federation instead of a service account key, per-agent least-privilege tokens, approval gates for high-risk repos.

## License

MIT — see [LICENSE](LICENSE).
