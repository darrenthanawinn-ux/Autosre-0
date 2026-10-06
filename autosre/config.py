"""Central configuration, read from environment (GitLab CI variables in production)."""
import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    gitlab_url: str = field(default_factory=lambda: _env("GITLAB_URL", _env("CI_SERVER_URL", "https://gitlab.com")))
    gitlab_token: str = field(default_factory=lambda: _env("AUTOSRE_GITLAB_TOKEN"))
    project_id: str = field(default_factory=lambda: _env("CI_PROJECT_ID", _env("GITLAB_PROJECT_ID")))
    default_branch: str = field(default_factory=lambda: _env("CI_DEFAULT_BRANCH", "main"))

    anthropic_model: str = field(default_factory=lambda: _env("AUTOSRE_MODEL", "claude-sonnet-5-5"))
    anthropic_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))

    gcp_project: str = field(default_factory=lambda: _env("GCP_PROJECT_ID"))
    gcp_region: str = field(default_factory=lambda: _env("GCP_REGION", "us-central1"))
    cloud_run_service: str = field(default_factory=lambda: _env("CLOUD_RUN_SERVICE", "autosre-demo"))

    max_heal_attempts: int = field(default_factory=lambda: int(_env("AUTOSRE_MAX_HEAL_ATTEMPTS", "3")))
    monitor_seconds: int = field(default_factory=lambda: int(_env("AUTOSRE_MONITOR_SECONDS", "120")))
    monitor_interval: int = field(default_factory=lambda: int(_env("AUTOSRE_MONITOR_INTERVAL", "15")))
    max_error_rate: float = field(default_factory=lambda: float(_env("AUTOSRE_MAX_ERRORS", "5")))
    trigger_label: str = field(default_factory=lambda: _env("AUTOSRE_LABEL", "autosre"))
    state_path: str = field(default_factory=lambda: _env("AUTOSRE_STATE", ".autosre_state.json"))

    # Governance: paths agents may never modify (prevents self-privilege-escalation).
    protected_paths: tuple = (".gitlab-ci.yml", "autosre/", "deploy/", "LICENSE", "policy.yaml")


def get_settings() -> Settings:
    return Settings()
