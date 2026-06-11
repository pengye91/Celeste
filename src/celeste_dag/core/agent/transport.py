"""Transport layer for Celeste-DAG Environment Agent Protocol.

Provides BaseTransport ABC and InProcessTransport for direct method calls.
"""

from abc import ABC, abstractmethod


class BaseTransport(ABC):
    """Abstract base class for all transport implementations.

    Transports are responsible for sending JSON-RPC-style requests to an
    Environment Agent and returning the response. The protocol shape is:

        request  -> {"method": str, "params": dict}
        response -> dict (the JSON-RPC result object)
    """

    @abstractmethod
    async def send_request(self, method: str, params: dict) -> dict:
        """Send a request and await the response.

        Args:
            method: The JSON-RPC method name (e.g. ``"call_tool"``,
                ``"list_tools"``).
            params: Method-specific parameters.

        Returns:
            The parsed response payload (the ``result`` field of a JSON-RPC
            response).

        Raises:
            RuntimeError: If the transport receives a JSON-RPC error object.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the transport and release any resources."""
        ...


class InProcessTransport(BaseTransport):
    """Transport that invokes an agent instance directly in the same process.

    No serialization or network overhead.  Useful for local development and
    embedded SDK usage.
    """

    def __init__(self, agent_instance: object) -> None:
        self._agent = agent_instance

    async def send_request(self, method: str, params: dict) -> dict:
        """Dispatch to the agent's internal handler methods.

        * ``call_tool``  -> ``agent._handle_call_tool(params)``
        * ``list_tools`` -> ``agent._handle_list_tools()``
        """
        if method == "call_tool":
            return await self._agent._handle_call_tool(params)
        if method == "list_tools":
            return await self._agent._handle_list_tools()
        raise RuntimeError(f"Unknown method: {method}")

    async def close(self) -> None:
        """No-op — the agent lifecycle is managed externally."""
        return None
