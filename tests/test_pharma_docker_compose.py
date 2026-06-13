"""Regression tests for DX-006, PHARMA-1, PHARMA-14: broken docker-compose services.

The audit found that docker-compose.yml in examples/pharma-coldchain/ defines
three services whose commands cannot work:

  1. iot-telemetry-server — runs `python server.py` but no server.py is mounted.
  2. customs-api          — same as above.
  3. celeste-agent        — runs `pip install celeste && python -m celeste.core.agent.serve`
                            but the celeste PyPI package is unrelated to the
                            in-tree `src/celeste`, and `serve.py` does not exist.

The fixed-state we require: each broken service is either removed or replaced
with a stub that doesn't try to execute missing files / modules. The
celeste-agent service must not `pip install celeste` (which would shadow the
in-tree module).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PHARMA_COMPOSE = REPO_ROOT / "examples" / "pharma-coldchain" / "docker-compose.yml"


def test_pharma_compose_file_loads_as_valid_yaml() -> None:
    """The docker-compose file must parse as YAML."""
    with open(PHARMA_COMPOSE) as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), "docker-compose.yml must parse as a mapping"
    assert "services" in data, "docker-compose.yml must define services"


def test_pharma_compose_does_not_run_missing_server_py() -> None:
    """Services must not invoke `python server.py` without a server.py mount.

    PHARMA-1: the iot-telemetry-server and customs-api services run
    `python server.py` but no server.py is mounted in the volume block,
    so docker compose reports success (depends_on only checks healthy
    services) while the containers exit with "No such file".
    """
    with open(PHARMA_COMPOSE) as f:
        data = yaml.safe_load(f)
    services = data.get("services", {})

    bad_services: list[str] = []
    for name, cfg in services.items():
        cmd = cfg.get("command", "")
        if isinstance(cmd, str) and "python server.py" in cmd:
            # Must mount a server.py somewhere reachable.
            volumes = cfg.get("volumes", []) or []
            has_server_mount = any(
                isinstance(v, str) and "server.py" in v for v in volumes
            )
            if not has_server_mount:
                bad_services.append(name)

    assert not bad_services, (
        f"These services run `python server.py` without mounting a "
        f"server.py file (PHARMA-1): {bad_services}. Either provide a "
        "server.py or remove/comment out the service."
    )


def test_pharma_compose_does_not_pip_install_celeste() -> None:
    """The celeste-agent service must not `pip install celeste`.

    PHARMA-14: pip install celeste pulls the unrelated public PyPI package,
    not the in-tree `src/celeste`. This shadows the engine and breaks
    `python -m celeste.core.agent.serve` (which also doesn't exist).
    """
    with open(PHARMA_COMPOSE) as f:
        data = yaml.safe_load(f)
    services = data.get("services", {})

    bad_services: list[str] = []
    for name, cfg in services.items():
        cmd = cfg.get("command", "")
        if isinstance(cmd, str) and "pip install celeste" in cmd:
            # Must either use -e / src/ mount, or be removed.
            volumes = cfg.get("volumes", []) or []
            has_src_mount = any(
                isinstance(v, str) and "src" in v.lower() for v in volumes
            )
            editable_install = "-e " in cmd or "--editable" in cmd
            if not (has_src_mount or editable_install):
                bad_services.append(name)

    assert not bad_services, (
        f"These services try to `pip install celeste` from PyPI, "
        f"shadowing the in-tree engine (PHARMA-14): {bad_services}. "
        "Either mount the in-tree src/ and editable-install, or remove "
        "the service."
    )


def test_pharma_compose_celeste_agent_does_not_invoke_missing_module() -> None:
    """The celeste-agent service must not invoke `celeste.core.agent.serve`.

    DX-006: there is no serve.py submodule. Any reference to this entry
    point must be removed or replaced with a real one.
    """
    with open(PHARMA_COMPOSE) as f:
        data = yaml.safe_load(f)
    services = data.get("services", {})

    bad_services: list[str] = []
    for name, cfg in services.items():
        cmd = cfg.get("command", "")
        if isinstance(cmd, str) and "celeste.core.agent.serve" in cmd:
            bad_services.append(name)

    assert not bad_services, (
        f"These services invoke `python -m celeste.core.agent.serve` "
        f"which is not a real module (DX-006): {bad_services}. Either "
        "create the module or remove the service."
    )


def test_pharma_compose_postgres_has_no_initdb_schema_mount() -> None:
    """The postgres-hub service must NOT mount schema.sql into initdb.

    Fix B (load-bearing for ``docker compose up``): the schema.sql file
    starts with ``PRAGMA foreign_keys = ON;`` which is a SQLite extension
    and is invalid PostgreSQL. Mounting it as a
    ``docker-entrypoint-initdb.d/*.sql`` file makes postgres initdb error
    with ``syntax error`` and the container fails to initialise.

    serve_agent.py already creates the schema itself via SQLAlchemy
    (``_apply_schema`` uses ``CREATE TABLE IF NOT EXISTS`` and skips PRAGMA
    for non-sqlite dialects), so the initdb mount is both redundant AND
    broken. The schema source of truth is serve_agent.py, not initdb.
    """
    with open(PHARMA_COMPOSE) as f:
        data = yaml.safe_load(f)
    services = data.get("services", {})

    bad_volumes: list[str] = []
    for name, cfg in services.items():
        volumes = cfg.get("volumes", []) or []
        for vol in volumes:
            if not isinstance(vol, str):
                continue
            if "docker-entrypoint-initdb.d" in vol and "schema.sql" in vol:
                bad_volumes.append(f"{name}: {vol}")

    assert not bad_volumes, (
        "postgres-hub must not mount schema.sql into "
        "docker-entrypoint-initdb.d/ — schema.sql begins with PRAGMA which is "
        "invalid PostgreSQL and breaks initdb (Fix B). serve_agent.py is the "
        f"real schema source. Offending mounts: {bad_volumes}"
    )