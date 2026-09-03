from __future__ import annotations

import re
import json
import logging
from pathlib import Path

import yaml
from src.core.logging import StructuredJsonFormatter


ROOT = Path(__file__).resolve().parents[1]


def _compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_openwa_is_internal_only_and_hardened() -> None:
    compose = _compose(ROOT / "docker-compose.yml")
    services = compose["services"]
    gateway = services["openwa"]

    assert gateway["image"] == "ghcr.io/rmyndharis/openwa:0.23.3@sha256:c00b5b589446ce7dd6177f1b871789284bcfbe3612189ba109465025eb0ad4ec"
    assert "latest" not in gateway["image"].lower()
    assert "ports" not in gateway
    assert "expose" not in gateway
    assert gateway["networks"] == ["ks-openwa"]
    assert services["api"]["networks"] == ["ks-internal", "ks-openwa"]
    assert compose["networks"]["ks-openwa"]["internal"] is True
    assert compose["networks"]["ks-openwa"]["ipam"]["config"] == [
        {"subnet": "172.30.0.0/24"}
    ]

    assert gateway["read_only"] is True
    assert gateway["security_opt"] == ["no-new-privileges:true"]
    assert gateway["cap_drop"] == ["ALL"]
    assert gateway["cap_add"] == ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"]
    assert gateway["pids_limit"] == 512
    assert gateway["mem_limit"] == "1g"
    assert gateway["shm_size"] == "128m"
    assert gateway["tmpfs"] == ["/tmp:size=128m,noexec,nosuid,nodev"]
    assert gateway["logging"]["options"] == {"max-size": "10m", "max-file": "5"}

    env = gateway["environment"]
    assert env["API_KEY"].endswith("OPENWA_API_KEY:-}")
    assert env["API_MASTER_KEY"].endswith("OPENWA_API_MASTER_KEY:-}")
    assert env["API_KEY_PEPPER"].endswith("OPENWA_API_KEY_PEPPER:-}")
    assert env["API_KEY_ROLE"].endswith("OPENWA_API_KEY_ROLE:-operator}")
    assert env["SESSION_ID"].endswith("OPENWA_SESSION_ID:-kaelsolutions_pilot}")
    assert env["ALLOWED_SESSIONS"].endswith("OPENWA_ALLOWED_SESSIONS:-kaelsolutions_pilot}")
    assert env["ALLOWED_IPS"].endswith("OPENWA_ALLOWED_IPS:-172.30.0.0/24}")
    assert env["WEBHOOK_SECRET"].endswith("OPENWA_WEBHOOK_SECRET:-}")
    assert env["ENABLE_SWAGGER"] == "false"
    assert env["SERVE_DASHBOARD"] == "false"
    assert env["AUTO_RESPONSES_ENABLED"] == "false"
    assert env["LOG_LEVEL"].endswith("OPENWA_LOG_LEVEL:-error}")
    assert env["ALLOW_UNSIGNED_INGRESS"] == "false"
    assert env["MCP_ENABLED"] == "false"
    assert env["PLUGINS_ENABLED"] == "false"
    assert env["PLUGINS_DIR"] == "/tmp/openwa-plugins"
    assert env["PLUGIN_INSTALL_REQUIRE_PIN"] == "true"
    assert env["PLUGIN_DOWNLOAD_ALLOW_INSECURE_REDIRECTS"] == "false"
    assert env["BODY_SIZE_LIMIT"].endswith("25mb}")
    assert env["WEBHOOK_MAX_PAYLOAD_BYTES"].endswith("1048576}")
    assert env["WEBHOOK_MAX_PER_SESSION"].endswith("16}")
    assert env["RATE_LIMIT_SHORT_LIMIT"].endswith("10}")
    assert env["WS_MAX_SOCKETS_PER_KEY"].endswith("16}")
    assert not any("docker.sock" in str(value) or str(value).startswith("DOCKER_HOST") for value in env.values())
    assert not any(key.startswith(("POSTGRES", "DATABASE", "REDIS")) for key in env)


def test_session_volume_is_exclusive_and_public_proxy_has_no_openwa_route() -> None:
    compose = _compose(ROOT / "docker-compose.yml")
    users = []
    for name, service in compose["services"].items():
        for volume in service.get("volumes", []):
            if str(volume).split(":", 1)[0] == "openwa_sessions":
                users.append(name)
    assert users == ["openwa"]
    assert compose["volumes"]["openwa_sessions"]["name"] == "ks_openwa_sessions"

    caddy = (ROOT / "deploy" / "aws" / "Caddyfile").read_text(encoding="utf-8")
    assert "reverse_proxy openwa" not in caddy
    assert "handle /docs*" in caddy
    assert "handle /openapi.json" in caddy


def test_openwa_admin_paths_are_not_publicly_routed() -> None:
    caddy = (ROOT / "deploy" / "aws" / "Caddyfile").read_text(encoding="utf-8")

    assert "reverse_proxy openwa" not in caddy
    assert "reverse_proxy openwa" not in caddy
    assert "handle /api/docs*" in caddy
    assert "handle /api/openapi.json" in caddy
    assert "handle /dashboard*" in caddy


def test_secret_examples_are_empty_and_scope_contract_is_non_public() -> None:
    values: dict[str, str] = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*)", line)
        if match:
            values[match.group(1)] = match.group(2)

    for key in (
        "OPENWA_API_KEY",
        "OPENWA_API_KEY_PEPPER",
        "OPENWA_API_MASTER_KEY",
        "OPENWA_WEBHOOK_SECRET",
    ):
        assert values[key] == ""
    assert values["OPENWA_API_KEY_ROLE"] == "operator"
    assert values["OPENWA_ALLOWED_SESSIONS"] == "kaelsolutions_pilot"
    assert values["OPENWA_ALLOWED_IPS"] == "172.30.0.0/24"


def test_aws_activation_fails_closed_before_openwa_profile_start() -> None:
    helper = (ROOT / "deploy" / "aws" / "scripts" / "compose-env.sh").read_text(encoding="utf-8")
    for variable in (
        "OPENWA_API_KEY",
        "OPENWA_API_MASTER_KEY",
        "OPENWA_API_KEY_PEPPER",
        "OPENWA_WEBHOOK_SECRET",
        "OPENWA_SESSION_ID",
        "OPENWA_ALLOWED_SESSIONS",
        "OPENWA_ALLOWED_IPS",
    ):
        assert f'"${{{variable}:?' in helper
    assert 'OPENWA_API_KEY_ROLE:-}" != "operator"' in helper
    assert "allowed sessions must contain only the configured session" in helper
    assert "OPENWA_API_MASTER_KEY} < 32" in helper
    assert "OPENWA_API_KEY_PEPPER} < 32" in helper
    assert "OPENWA_API_KEY} < 32" in helper
    assert "@sha256:[0-9a-fA-F]{64}" in helper
    assert "validate_openwa_gate.py" in helper
    assert "gate manifest is not approved" in helper
    assert "evidence_sha256,," in helper


def test_backend_logs_redact_openwa_secrets_identifiers_and_phone() -> None:
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "API_MASTER_KEY=super-secret session_id=pilot qr_code=secret-qr "
        '"sessionId":"camel-session" "qrCode":"camel-qr" phone=5511999999999',
        (),
        None,
    )
    output = json.loads(StructuredJsonFormatter().format(record))
    assert "super-secret" not in output["message"]
    assert "pilot" not in output["message"]
    assert "secret-qr" not in output["message"]
    assert "camel-session" not in output["message"]
    assert "camel-qr" not in output["message"]
    assert "5511999999999" not in output["message"]
