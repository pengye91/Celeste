"""Environment Agent module.

Exports the EnvironmentAgent, drivers, transports, and the stdio transport
for the Celeste-DAG Environment Agent Protocol.
"""

from celeste.core.agent.agent import EnvironmentAgent
from celeste.core.agent.driver import BaseDriver, ShellDriver, FilesystemDriver
from celeste.core.agent.transport import BaseTransport, InProcessTransport
from celeste.core.agent.transport_stdio import StdioTransport
from celeste.core.agent.transport_ws import WebSocketTransport, WebSocketServer

__all__ = [
    "EnvironmentAgent",
    "BaseDriver",
    "ShellDriver",
    "FilesystemDriver",
    "BaseTransport",
    "InProcessTransport",
    "StdioTransport",
    "WebSocketTransport",
    "WebSocketServer",
]
