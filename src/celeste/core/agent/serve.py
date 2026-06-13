"""Generic server runner for the Celeste-DAG Environment Agent Protocol.

Exposes a :func:`serve` coroutine that builds an :class:`EnvironmentAgent`
in *serve* mode (a standalone WebSocket server owning drivers and toolkits)
and runs it until cancelled, plus a ``main()`` CLI entry point that loads
toolkits dynamically from ``module.path:Attr`` specs.

This module is intentionally GENERIC and lives in the core package: it MUST
NOT import anything from ``examples/`` (core cannot depend on examples).
Pharma-specific wiring belongs in the examples directory and reaches this
module via dependency injection (the ``toolkits`` parameter).

Run directly::

    python -m celeste.core.agent.serve \\
        --host 0.0.0.0 --port 8900 \\
        --toolkits celeste.toolkits.system_data:SystemDataToolkit
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
from typing import Any

from celeste.core.agent.agent import EnvironmentAgent
from celeste.toolkits.base import BaseToolkit

logger = logging.getLogger(__name__)


async def serve(
    host: str,
    port: int,
    workdir: str,
    toolkits: list[BaseToolkit] | None,
    auth_token: str | None = None,
) -> None:
    """Start an EnvironmentAgent server and run until cancelled.

    Builds the agent in *serve* mode (a WebSocket server that owns the
    drivers and registered toolkits), starts it, and then blocks forever.
    Cancellation (``asyncio.CancelledError``) or ``KeyboardInterrupt``
    triggers a graceful ``agent.stop()`` before returning.

    Args:
        host: Bind address (e.g. ``"0.0.0.0"``).
        port: Bind port. ``0`` lets the OS pick a free port.
        workdir: Working directory for the server's filesystem/shell drivers.
        toolkits: Toolkits to register on the server agent. ``None`` means
            only the built-in tools are available.
        auth_token: Optional bearer token clients must present.

    Raises:
        Nothing on graceful shutdown; any startup error propagates.
    """
    agent = EnvironmentAgent.serve(
        host=host,
        port=port,
        workdir=workdir,
        toolkits=toolkits,
        auth_token=auth_token,
    )
    await agent.start()
    logger.info(
        "Celeste agent server listening on %s:%d (workdir=%s, toolkits=%d)",
        host,
        port,
        workdir,
        len(toolkits) if toolkits else 0,
    )
    try:
        # Run until cancelled. ``suspend_forever`` yields control to the
        # event loop without busy-waiting; the WebSocketServer handles
        # inbound connections concurrently.
        await asyncio.Event().wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Shutting down Celeste agent server...")
    finally:
        await agent.stop()
        logger.info("Celeste agent server stopped")


def _load_toolkit_specs(specs: list[str]) -> list[BaseToolkit]:
    """Load toolkit instances from ``module.path:AttributeName`` specs.

    Each spec is ``"package.module:ClassName"``. The class is instantiated
    with no arguments. Unknown attributes or import errors raise
    ``ValueError`` with a helpful message.

    Args:
        specs: Dotted-path specs, e.g.
            ``["celeste.toolkits.system_data:SystemDataToolkit"]``.

    Returns:
        A list of instantiated toolkits.
    """
    toolkits: list[BaseToolkit] = []
    for spec in specs:
        if ":" not in spec:
            raise ValueError(
                f"Invalid toolkit spec {spec!r}: expected 'module.path:Attr'"
            )
        module_path, attr_name = spec.split(":", 1)
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            raise ValueError(
                f"Could not import module {module_path!r} for toolkit spec "
                f"{spec!r}: {exc}"
            ) from exc
        try:
            cls = getattr(module, attr_name)
        except AttributeError as exc:
            raise ValueError(
                f"Module {module_path!r} has no attribute {attr_name!r}"
            ) from exc
        try:
            instance = cls()
        except Exception as exc:
            raise ValueError(
                f"Could not instantiate {module_path}:{attr_name}: {exc}"
            ) from exc
        toolkits.append(instance)
        logger.info("Loaded toolkit %s from %s", attr_name, spec)
    return toolkits


def main() -> None:
    """CLI entry point: parse args and run the server until interrupted."""
    parser = argparse.ArgumentParser(
        prog="celeste.core.agent.serve",
        description=(
            "Run a Celeste-DAG Environment Agent as a standalone WebSocket "
            "server. Toolkits are loaded from 'module.path:Attr' specs."
        ),
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8900,
        help="Bind port (default: 8900; 0 picks a free port).",
    )
    parser.add_argument(
        "--workdir",
        default=".",
        help="Working directory for filesystem/shell drivers (default: '.').",
    )
    parser.add_argument(
        "--auth-token",
        default=None,
        help="Optional bearer token clients must present.",
    )
    parser.add_argument(
        "--toolkits",
        nargs="+",
        default=[],
        metavar="MODULE:ATTR",
        help=(
            "Toolkit specs as 'module.path:ClassName', instantiated with no "
            "args. May be repeated."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    toolkits = _load_toolkit_specs(args.toolkits) if args.toolkits else None

    try:
        asyncio.run(
            serve(
                host=args.host,
                port=args.port,
                workdir=args.workdir,
                toolkits=toolkits,
                auth_token=args.auth_token,
            )
        )
    except KeyboardInterrupt:
        # asyncio.run already drained the cancel path; just exit cleanly.
        pass


if __name__ == "__main__":
    main()
