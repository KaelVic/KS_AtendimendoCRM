from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
AWS = ROOT / "deploy" / "aws"


def _bash_command() -> str | None:
    candidates = ["bash"]
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            "bash",
        ]
    for candidate in candidates:
        command = candidate if Path(candidate).is_file() else shutil.which(candidate)
        if command:
            result = subprocess.run([command, "--version"], capture_output=True, check=False)
            if result.returncode == 0 and b"GNU bash" in result.stdout:
                return command
    return None


def _compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_aws_overlay_removes_public_ports_from_internal_services() -> None:
    base = _compose(ROOT / "docker-compose.yml")["services"]
    overlay = _compose(AWS / "docker-compose.aws.yml")["services"]

    for name in ("postgres", "redis", "api", "scrapegraph", "web"):
        assert overlay[name]["ports"] == [], name
        if name != "scrapegraph":
            assert base[name].get("ports"), f"fixture must prove overlay removes {name} ports"

    assert overlay["caddy"]["ports"] == ["80:80", "443:443"]
    assert "ports" not in overlay["openwa"]


def test_openwa_is_fixed_and_not_latest() -> None:
    service = _compose(AWS / "docker-compose.aws.yml")["services"]["openwa"]
    image = service["image"]
    assert ":0.23.3@sha256:" in image
    assert "latest" not in image.lower()
    assert "OPENWA_IMAGE" in image

    compose_text = (AWS / "docker-compose.aws.yml").read_text(encoding="utf-8")
    assert "network_mode: host" not in compose_text


def test_openwa_operations_are_opt_in_and_digest_pinned() -> None:
    helper = (AWS / "scripts" / "compose-env.sh").read_text(encoding="utf-8")
    service = (AWS / "ks-atendimento.service").read_text(encoding="utf-8")
    assert "ENABLE_OPENWA:-0" in helper
    assert "@sha256:[0-9a-fA-F]{64}" in helper
    assert "--profile openwa" not in service


def test_user_data_installs_docker_before_assigning_docker_group() -> None:
    user_data = (AWS / "user-data.yaml").read_text(encoding="utf-8")
    assert "groups: [docker]" not in user_data
    assert user_data.index("dnf install -y docker") < user_data.index("usermod -aG docker ksapp")


def test_caddy_has_no_openwa_route_and_blocks_api_docs() -> None:
    caddy = (AWS / "Caddyfile").read_text(encoding="utf-8")
    assert "reverse_proxy openwa" not in caddy
    assert "handle /docs*" in caddy
    assert "handle /openapi.json" in caddy
    assert "reverse_proxy web:3000" in caddy


def test_env_example_does_not_contain_secret_values() -> None:
    text = (AWS / ".env.aws.example").read_text(encoding="utf-8")
    forbidden = ("sk-", "AIza", "ghp_", "BEGIN PRIVATE KEY", "password123")
    assert not any(value.lower() in text.lower() for value in forbidden)
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if match and match.group(1) in {
            "POSTGRES_PASSWORD",
            "JWT_SECRET_KEY",
            "OWNER_AUTH_TOKEN",
            "OPENWA_API_KEY",
            "OPENWA_API_KEY_PEPPER",
            "OPENWA_API_MASTER_KEY",
            "OPENWA_WEBHOOK_SECRET",
            "GEMINI_API_KEY",
            "SCRAPEGRAPH_SERVICE_TOKEN",
            "BUDGET_ALERT_EMAIL",
        }:
            assert match.group(2) == ""


@pytest.mark.skipif(
    _bash_command() is None,
    reason="GNU Bash não disponível (launcher WSL pode estar bloqueado no Windows)",
)
def test_deploy_scripts_parse_with_bash() -> None:
    for script in sorted((AWS / "scripts").glob("*.sh")):
        result = subprocess.run(
            [_bash_command(), "-n", script.relative_to(ROOT).as_posix()],
            capture_output=True,
            text=True,
            check=False,
            cwd=ROOT,
        )
        assert result.returncode == 0, f"{script}: {result.stderr}"


def test_aws_docs_require_approval_for_remote_mutations() -> None:
    runbook = (AWS / "README.md").read_text(encoding="utf-8")
    assert re.search(r"nenhum comando AWS abaixo deve ser\s+executado sem aprovação", runbook)
    assert "[MUTAÇÃO AWS]" in runbook
    assert "CONFIRM_AWS_MUTATION=I_APPROVE_AWS_BUDGET" in runbook


def test_budget_uses_aws_tag_key_value_syntax() -> None:
    script = (AWS / "scripts" / "create-budget.sh").read_text(encoding="utf-8")
    assert 'TAG_FILTER="user:Project\\$${PROJECT_TAG}"' in script


def test_local_postgres_is_opt_in_for_external_supabase_mode() -> None:
    base = _compose(ROOT / "docker-compose.yml")["services"]

    assert base["postgres"]["profiles"] == ["local-db"]
    assert "postgres" not in base["api"]["depends_on"]
    assert "postgres" not in base["worker"]["depends_on"]


def test_neon_deploy_example_uses_external_database_without_secrets() -> None:
    text = (AWS / ".env.aws.example").read_text(encoding="utf-8")

    assert "DATABASE_BACKEND=neon" in text
    assert "DATABASE_SSL_MODE=auto" in text
    assert "COMPOSE_PROFILES=" in text
    for key in ("DATABASE_URL", "POSTGRES_PASSWORD", "JWT_SECRET_KEY"):
        assert re.search(rf"^{key}=$", text, re.MULTILINE)


def test_external_migration_script_is_fail_closed_and_uses_alembic() -> None:
    script = (AWS / "scripts" / "migrate.sh").read_text(encoding="utf-8")

    assert 'DATABASE_BACKEND="${DATABASE_BACKEND:-local}"' in script
    assert "neon|supabase|external" in script
    assert "DATABASE_URL:?DATABASE_URL" in script
    assert "alembic upgrade head" in script
    assert "--no-deps" in script
