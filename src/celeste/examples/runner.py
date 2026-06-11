"""Shared example runner module for Celeste verification scenarios.

Provides helpers to:
- Start/stop docker compose services
- Load seed data into databases
- Run a scenario in local/remote/embedded mode
- Collect verification reports
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from celeste.core.opa_loop import WorkflowResult

logger = logging.getLogger(__name__)


@dataclass
class ExampleResult:
    """Result of running an example scenario."""

    mode: str  # "local", "remote", "embedded"
    workflow_result: WorkflowResult | None = None
    report: dict[str, Any] = field(default_factory=dict)
    services_started: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.workflow_result is not None and self.workflow_result.status in (
            "completed",
            "paused",
        )


class ExampleRunner:
    """Orchestrate a Celeste example scenario."""

    def __init__(self, example_dir: Path | str) -> None:
        self._example_dir = Path(example_dir)
        self._compose_file = self._example_dir / "docker-compose.yml"

    # ------------------------------------------------------------------
    # Docker Compose helpers
    # ------------------------------------------------------------------

    async def start_services(self, services: list[str] | None = None) -> list[str]:
        """Start docker compose services and return the list started."""
        if not self._compose_file.exists():
            logger.info("No docker-compose.yml found at %s; skipping services", self._compose_file)
            return []

        cmd = ["docker", "compose", "-f", str(self._compose_file), "up", "-d"]
        if services:
            cmd.extend(services)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"docker compose up failed: {stderr.decode().strip()}"
            )

        started = stdout.decode().strip().splitlines()
        logger.info("Started services: %s", started)
        return started

    async def stop_services(self) -> None:
        """Stop and remove docker compose services."""
        if not self._compose_file.exists():
            return

        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", str(self._compose_file), "down",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        logger.info("Stopped services")

    async def service_healthy(self, service_name: str, timeout: float = 60.0) -> bool:
        """Wait for a docker compose service to be healthy."""
        start = asyncio.get_event_loop().time()
        while True:
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "-f", str(self._compose_file),
                "ps", "-q", service_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if stdout.strip():
                # Container exists; optional: check health status
                return True

            if asyncio.get_event_loop().time() - start > timeout:
                return False

            await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # Seed data loading
    # ------------------------------------------------------------------

    async def load_seed_data(self, db_url: str | None = None) -> None:
        """Run the example's seed_data/load.py script."""
        load_script = self._example_dir / "seed_data" / "load.py"
        if not load_script.exists():
            logger.info("No seed data loader at %s; skipping", load_script)
            return

        env = {"PYTHONPATH": str(self._example_dir.parent.parent / "src")}
        if db_url:
            env["DATABASE_URL"] = db_url

        proc = await asyncio.create_subprocess_exec(
            "python", str(load_script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**dict(__import__("os").environ), **env},
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"Seed data load failed: {stderr.decode().strip()}"
            )
        logger.info("Seed data loaded")

    # ------------------------------------------------------------------
    # Scenario execution
    # ------------------------------------------------------------------

    async def run_local(
        self,
        goal: str,
        agent: Any,
        planner: Any,
        evaluator: Any,
    ) -> ExampleResult:
        """Run the scenario in local mode (in-process)."""
        from celeste.core.engine import Engine

        engine = Engine()
        await engine.start()
        try:
            result = await engine.run(
                goal=goal,
                agent=agent,
                planner=planner,
                evaluator=evaluator,
            )
            return ExampleResult(mode="local", workflow_result=result)
        finally:
            await engine.stop()

    async def run_remote(
        self,
        goal: str,
        agent_url: str,
    ) -> ExampleResult:
        """Run the scenario in remote mode (WebSocket agent)."""
        # Remote mode requires a running agent server.
        # This is a stub for the runner interface.
        return ExampleResult(
            mode="remote",
            errors=["Remote mode not yet implemented in ExampleRunner"],
        )

    async def run_embedded(
        self,
        goal: str,
        app: Any,
    ) -> ExampleResult:
        """Run the scenario in embedded mode (FastAPI app)."""
        # Embedded mode requires an ASGI test client.
        # This is a stub for the runner interface.
        return ExampleResult(
            mode="embedded",
            errors=["Embedded mode not yet implemented in ExampleRunner"],
        )

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    async def verify(
        self,
        workflow_id: str,
        mode: str = "local",
    ) -> dict[str, Any]:
        """Run verification for the given workflow and mode."""
        from celeste.evaluation import Evaluator

        evaluator = Evaluator(workflow_id=workflow_id)
        report = await evaluator.evaluate()
        return report.model_dump() if hasattr(report, "model_dump") else report
