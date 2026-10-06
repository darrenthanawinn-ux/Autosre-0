# AutoSRE-0 — System Architecture

## Swarm topology

```
 Issue labelled `autosre`
        │  (webhook / trigger API)
        ▼
┌───────────────┐  MR (auto-merge on green)  ┌──────────────────┐
│  Code Agent   │ ─────────────────────────▶ │   GitLab CI/CD    │
│ Plan + Create │                            │ verify → secure → │
└───────────────┘                            │ package → release │
        ▲                                    │ → configure →     │
        │ fix commits                        │ monitor           │
┌───────────────┐  on_failure                └─────────┬────────┘
│ Healing Agent │ ◀────────────────────────────────────┤
│    Verify     │                                      │
└───────────────┘          ┌───────────────┐           │
                           │Security & Gov │ ◀─────────┤ secure stage
                           │    Agent      │  patch    │
                           └───────────────┘           │
                           ┌───────────────┐           │
                           │ Cloud SRE     │ ◀─────────┘ main branch
                           │ Agent         │──▶ Cloud Run canary → promote → watch → rollback
                           └───────────────┘
```

All side effects flow through two **MCP servers** (`autosre-gitlab`, `autosre-gcp`) via a single `McpHub`. Agents contain only reasoning and policy; every action is an auditable MCP tool call.

## Lifecycle coverage (8 stages)

| Stage | Where | Agent / mechanism |
|---|---|---|
| Plan | `plan:issue-to-mr` | Code Agent reads the issue, repo tree, drafts the change set |
| Create | Code Agent | Branch, atomic commit with tests, MR, merge-when-pipeline-succeeds |
| Verify | `verify:test`, `heal` | pytest; Healing Agent diagnoses failures and pushes fixes (max 3 attempts, then incident issue) |
| Secure | `secure:agent` + GitLab SAST/Secret Detection | Security Agent: bandit + pip-audit, deterministic dependency bumps, LLM-patched code findings, HIGH-severity policy gate |
| Package | `package:image` | Docker build, push to Artifact Registry |
| Release | `release:tag` | Tagged GitLab release per main pipeline |
| Configure | `configure:deploy` | envsubst-rendered Cloud Run manifest, no-traffic canary deploy, health probe, promote |
| Monitor | `monitor:slo` | SRE Agent polls health + Cloud Logging errors; auto-rollback and incident issue on breach |

## State and handoffs

- **Durable state** lives in GitLab itself (issues, MRs, commits, labels). Nothing the swarm needs is kept only in memory.
- `StateStore` (JSON) holds per-branch counters (heal attempts) and the issue→MR mapping within a runner or orchestrator.
- Handoffs are event-driven: an agent's commit triggers a new pipeline, which triggers the next agent. There is no central loop to crash.

## Governance and safety

1. **Protected paths**: agents cannot modify `.gitlab-ci.yml`, `autosre/`, `deploy/`, `policy.yaml`, `LICENSE`, and path traversal is rejected (`validate_changes`).
2. **Deterministic where possible**: dependency fixes come from `pip-audit` fix versions, not from model output.
3. **Bounded autonomy**: heal budget, canary-before-promote, SLO-triggered rollback.
4. **Merge gate**: auto-merge only after the full pipeline (tests + security) is green.
5. **Escalation without humans in the loop**: exhausted budgets and incidents become labelled issues, which are themselves machine-readable inputs.

## Known limits

- Agents are implemented with the GitLab REST API, MCP, and the Anthropic API. The `agents/*.yaml` manifests are declarative contracts that must be mapped to the current GitLab Duo Agent Platform schema when registering in your project.
- GitLab "merge when pipeline succeeds" may require project merge settings (pipelines must succeed) and token scopes (`api`).
