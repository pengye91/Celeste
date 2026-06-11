"""Firecracker MicroVM workspace — KVM-based isolation.

Stub implementation: setup/teardown define the VM config structure,
but execute raises NotImplementedError since Firecracker requires Linux KVM.

Requirements:
    - Linux host with KVM enabled
    - AWS .metal instances or equivalent bare-metal hosts
    - Firecracker binary installed
    - Root filesystem image and kernel image

See: https://firecracker-microvm.github.io/
"""

from __future__ import annotations

from typing import AsyncIterator

from celeste.core.workspaces.base import BaseWorkspace, WorkspaceEvent


class FirecrackerWorkspace(BaseWorkspace):
    """Workspace backed by a Firecracker MicroVM for KVM-based isolation.

    This is a stub implementation. Setup defines the VM configuration
    structure. Execute raises NotImplementedError pending Linux KVM
    support in the deployment environment.
    """

    def __init__(
        self,
        kernel_path: str = "/path/to/kernel",
        rootfs_path: str | None = None,
        vcpu_count: int = 1,
        mem_size_mb: int = 128,
    ) -> None:
        self._kernel_path = kernel_path
        self._rootfs_path = rootfs_path
        self._vcpu_count = vcpu_count
        self._mem_size_mb = mem_size_mb
        self._active: bool = False
        self.vm_config: dict | None = None

    @property
    def is_active(self) -> bool:
        return self._active

    async def setup(self) -> None:
        """Define MicroVM configuration structure."""
        self.vm_config = {
            "kernel_path": self._kernel_path,
            "rootfs_path": self._rootfs_path,
            "vcpu_count": self._vcpu_count,
            "mem_size_mb": self._mem_size_mb,
            "boot_timeout_seconds": 30,
            "network": None,
        }
        self._active = True

    async def execute(
        self,
        command: str,
        arguments: dict | None = None,
        env: dict | None = None,
    ) -> AsyncIterator[WorkspaceEvent]:
        """Execute a command inside the Firecracker MicroVM.

        Raises:
            NotImplementedError: Firecracker execution requires Linux KVM.
        """
        raise NotImplementedError(
            "Firecracker workspace execution is not yet implemented. "
            "Requires Linux host with KVM enabled (e.g., AWS .metal instances)."
        )
        yield  # pragma: no cover — makes this an async generator

    async def teardown(self) -> None:
        """Clean up VM configuration."""
        self._active = False
        self.vm_config = None

    async def get_workspace_path(self) -> str:
        """Return the workspace path inside the MicroVM."""
        return "/workspace"
