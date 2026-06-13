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

    def _resolve_load_script_path(self) -> Path:
        """Return the path to the example's seed_data/load.py, if any.

        The example_dir typically uses a hyphenated name (e.g.
        ``examples/pharma-coldchain``), but the loader module is
        importable as ``examples.pharma_coldchain`` (Python forbids
        hyphens in package names). For that reason the loader sometimes
        lives one directory up under the underscore variant; check both.
        """
        candidates = [
            self._example_dir / "seed_data" / "load.py",
            self._example_dir.with_name(
                self._example_dir.name.replace("-", "_")
            )
            / "seed_data"
            / "load.py",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        # Return the first (canonical) candidate even if missing so callers
        # can produce a useful log message.
        return candidates[0]

    async def load_seed_data(self, db_url: str | None = None) -> None:
        """Run the example's seed_data/load.py script."""
        load_script = self._resolve_load_script_path()
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
        agent: Any,
        planner: Any,
        evaluator: Any,
        *,
        server_toolkits: list[Any] | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        auth_token: str | None = None,
        agent_url: str | None = None,
    ) -> ExampleResult:
        """Run the scenario in remote mode (WebSocket agent).

        Self-contained and testable: spins up an in-process
        :class:`WebSocketServer` (owning the drivers + ``server_toolkits``)
        as a background task, connects a remote client agent, and drives the
        OPA loop. Every ``agent.call_tool`` / ``agent.list_tools`` call
        crosses a real WebSocket to the server.

        Args:
            goal: The workflow goal text.
            agent: The CLIENT agent to drive (must be a remote agent built
                via ``EnvironmentAgent.remote``). If ``agent_url`` is given
                the caller is responsible for that agent's lifecycle; if a
                server is spun up in-process a fresh client is built.
            planner: Injected planner (no LLM needed in tests).
            evaluator: Injected evaluator.
            server_toolkits: Toolkits to register on the SERVER agent. The
                server owns execution; the client only forwards requests.
            host: Bind host for the in-process server.
            port: Bind port for the in-process server (0 = OS-chosen).
            auth_token: Optional bearer token for the in-process server.
            agent_url: If provided, connect to this external server instead
                of spinning up an in-process one. In that case ``agent`` is
                ignored and a fresh client is built.

        Returns:
            An :class:`ExampleResult` with ``mode="remote"``.
        """
        from celeste.core.agent.agent import EnvironmentAgent
        from celeste.core.agent.transport_ws import WebSocketServer
        from celeste.core.engine import Engine

        server: WebSocketServer | None = None
        server_agent: EnvironmentAgent | None = None
        client_agent: EnvironmentAgent | None = None
        client_started = False

        try:
            if agent_url is None:
                # Spin up an in-process server that owns the toolkits.
                server_agent = EnvironmentAgent.in_process(
                    workdir=".",
                    toolkits=server_toolkits or [],
                )
                server = WebSocketServer(
                    host=host, port=port, agent=server_agent, auth_token=auth_token
                )
                await server.start()
                addr = server._server.sockets[0].getsockname()
                agent_url = f"ws://{addr[0]}:{addr[1]}"
                logger.info("In-process agent server started at %s", agent_url)

            # Decide which client agent drives the OPA loop. If we spun up
            # our own in-process server (server is not None) or the caller
            # passed no agent, build a fresh remote client connected to it.
            # Otherwise reuse the caller-provided agent (already connected
            # to an external server at agent_url).
            if server is not None or agent is None:
                client_agent = EnvironmentAgent.remote(
                    url=agent_url, auth_token=auth_token
                )
                await client_agent.start()
                client_started = True
                effective_agent = client_agent
            else:
                effective_agent = agent

            engine = Engine()
            await engine.start()
            try:
                result = await engine.run(
                    goal=goal,
                    agent=effective_agent,
                    planner=planner,
                    evaluator=evaluator,
                )
                return ExampleResult(mode="remote", workflow_result=result)
            finally:
                await engine.stop()
        except Exception as exc:  # pragma: no cover - surface as ExampleResult error
            logger.exception("Remote run failed")
            return ExampleResult(mode="remote", errors=[str(exc)])
        finally:
            if client_started and client_agent is not None:
                try:
                    await client_agent.stop()
                except Exception:  # pragma: no cover
                    pass
            if server is not None:
                try:
                    await server.stop()
                except Exception:  # pragma: no cover
                    pass

    async def run_embedded(
        self,
        goal: str,
        app: Any,
        *,
        max_cycles: int | None = None,
        max_llm_tokens: int | None = None,
        poll_timeout: float = 120.0,
    ) -> ExampleResult:
        """Run the scenario in embedded mode (engine inside a FastAPI app).

        Drives the OPA loop via the FastAPI ``POST /api/runs`` endpoint over
        an in-process ASGI transport (no real network socket), polling until
        a terminal status. The app must already be built with
        :func:`celeste.api.app.create_app` (toolkits + planner/evaluator
        factories wired by the caller); this method only orchestrates the
        HTTP drive + result collection.

        Because the OPA loop persists Workflow/TaskEvent rows as it runs,
        the run is observable through the app's existing monitoring
        endpoints.

        Args:
            goal: The workflow goal text.
            app: A FastAPI app built via ``create_app`` with the desired
                toolkits + cognitive-stack factories injected.
            max_cycles: Optional OPA-cycle cap forwarded to the run.
            max_llm_tokens: Optional token cap forwarded to the run.
            poll_timeout: Max seconds to wait for a terminal status.

        Returns:
            An :class:`ExampleResult` with ``mode="embedded"`` and the
            :class:`WorkflowResult` reconstructed from the run status (when
            available). On error the ``errors`` list is populated.
        """
        import httpx

        from celeste.core.opa_loop import WorkflowResult

        _TERMINAL = {"completed", "paused", "failed", "escalated", "cancelled"}

        # Drive the lifespan so the engine starts/stops cleanly.
        lifespan_cm = app.router.lifespan_context(app)
        await lifespan_cm.__aenter__()
        try:
            payload: dict[str, Any] = {"goal": goal}
            if max_cycles is not None:
                payload["max_cycles"] = max_cycles
            if max_llm_tokens is not None:
                payload["max_llm_tokens"] = max_llm_tokens

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://embedded"
            ) as client:
                resp = await client.post("/api/runs", json=payload)
                resp.raise_for_status()
                run_id = resp.json()["run_id"]

                deadline = asyncio.get_event_loop().time() + poll_timeout
                status_payload: dict[str, Any] = {"status": "unknown"}
                while asyncio.get_event_loop().time() < deadline:
                    r = await client.get(f"/api/runs/{run_id}")
                    r.raise_for_status()
                    status_payload = r.json()
                    if status_payload.get("status") in _TERMINAL:
                        break
                    await asyncio.sleep(0.1)

            workflow_result: WorkflowResult | None = None
            wf_id_str = status_payload.get("workflow_id")
            if wf_id_str:
                import uuid as _uuid

                workflow_result = WorkflowResult(
                    status=status_payload.get("status", "unknown"),
                    cycle_count=0,
                    llm_tokens_accumulated=0,
                    workflow_id=_uuid.UUID(wf_id_str),
                )

            errors: list[str] = []
            if status_payload.get("status") == "failed":
                errors.append(status_payload.get("error") or "run failed")
            elif status_payload.get("status") not in {"completed", "paused"}:
                errors.append(
                    f"embedded run ended in non-terminal status "
                    f"{status_payload.get('status')!r}"
                )

            return ExampleResult(
                mode="embedded",
                workflow_result=workflow_result,
                errors=errors,
            )
        except Exception as exc:  # pragma: no cover - surface as ExampleResult error
            logger.exception("Embedded run failed")
            return ExampleResult(mode="embedded", errors=[str(exc)])
        finally:
            # Cancel any lingering background run tasks before teardown.
            if hasattr(app.state, "running_run_tasks"):
                for rid, task in list(app.state.running_run_tasks.items()):
                    if not task.done():
                        task.cancel()
                for rid, task in list(app.state.running_run_tasks.items()):
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                app.state.running_run_tasks.clear()
            await lifespan_cm.__aexit__(None, None, None)

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
