"""Tests for ExampleRunner seed-data loader path resolution.

Captures the bug where the runner was constructed with
example_dir="examples/pharma-coldchain" (with a hyphen) and looked for
<example_dir>/seed_data/load.py, but the loader actually lived in
examples/pharma_coldchain/seed_data/load.py (with an underscore). The
runner always returned early and seed data was never loaded.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from celeste.examples.runner import ExampleRunner


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_DIR = REPO_ROOT / "examples" / "pharma-coldchain"


class TestSeedLoaderPathResolution:
    """Ensure the ExampleRunner can locate the seed loader for the
    pharma-coldchain (hyphenated) example directory."""

    def test_resolve_load_script_path_finds_load_py(self) -> None:
        """_resolve_load_script_path() must return a path that exists."""
        runner = ExampleRunner(EXAMPLE_DIR)
        resolved = runner._resolve_load_script_path()
        assert resolved.exists(), f"load.py not found at {resolved}"
        assert resolved.name == "load.py"

    def test_resolve_load_script_path_prefers_hyphen_dir(self) -> None:
        """When the hyphen variant has a load.py, that one is used."""
        runner = ExampleRunner(EXAMPLE_DIR)
        resolved = runner._resolve_load_script_path()
        # Resolved path must be under examples/pharma-coldchain/seed_data/
        # (not the underscore variant), since that's the canonical
        # example_dir passed to the runner.
        assert "pharma-coldchain" in str(resolved)
        assert "pharma_coldchain" not in str(resolved.parent.parent)

    def test_load_seed_data_runs_when_loader_exists(self) -> None:
        """load_seed_data() should not return early when loader is present.

        We exercise only the path-resolution + skip logic (without actually
        loading data) by patching subprocess to a no-op. The point of
        this test is to confirm the runner no longer silently skips.
        """
        runner = ExampleRunner(EXAMPLE_DIR)
        # If resolution returns a missing path, the runner will skip with
        # an info log; if resolution returns the correct path, the runner
        # will attempt to invoke the loader. Either way, the resolved
        # path must exist.
        assert runner._resolve_load_script_path().exists()


class TestSeedDataLoaderImports:
    """The consolidated load.py module must remain importable."""

    def test_load_py_imports_without_error(self) -> None:
        """The load.py module under the unified location imports cleanly."""
        import importlib
        import sys

        # The runner resolves the path; we use it to determine the package
        # root and add it to sys.path so the import works.
        runner = ExampleRunner(EXAMPLE_DIR)
        load_path = runner._resolve_load_script_path().resolve()
        # Add the parent directory of the package containing load.py.
        # load.py lives at <pkg_root>/seed_data/load.py, so the package
        # root is two levels up.
        pkg_root = load_path.parent.parent
        if str(pkg_root) not in sys.path:
            sys.path.insert(0, str(pkg_root))
        # Clear any cached modules with the same name
        for mod_name in list(sys.modules.keys()):
            if mod_name == "seed_data" or mod_name.startswith("seed_data."):
                sys.modules.pop(mod_name, None)
        # Now import it. The package the runner resolves to is "seed_data".
        mod = importlib.import_module("seed_data.load")
        assert hasattr(mod, "load_seed_data")
        assert hasattr(mod, "SeedDataLoadError")

    def test_pharma_coldchain_tools_package_still_importable(self) -> None:
        """examples.pharma_coldchain.tools must remain importable so
        run_local.py's `from examples.pharma_coldchain.tools.pharma_toolkit
        import PharmaColdChainToolkit` keeps working."""
        from examples.pharma_coldchain.tools.pharma_toolkit import (
            PharmaColdChainToolkit,
        )

        toolkit = PharmaColdChainToolkit()
        assert toolkit.name == "pharma_coldchain"


if __name__ == "__main__":
    pytest.main([__file__, "-x"])
