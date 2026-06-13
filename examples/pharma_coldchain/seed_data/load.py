"""Re-export shim for the pharma cold-chain seed data loader.

The canonical loader lives at ``examples/pharma-coldchain/seed_data/load.py``
(under the hyphenated directory name that matches the example's
``example_dir``). It is re-exported from this location so that
``from examples.pharma_coldchain.seed_data.load import load_seed_data``
keeps working — Python forbids hyphens in package names, so the
underscored ``pharma_coldchain`` package cannot directly import the
hyphenated module without help.

This file loads the real module by file path and re-exports its
public API.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REAL_LOADER = (
    _HERE.parent.parent  # examples/
    / "pharma-coldchain"  # hyphenated sibling
    / "seed_data"
    / "load.py"
)


def _load_real_module():
    spec = importlib.util.spec_from_file_location(
        "examples.pharma_coldchain.seed_data._real_load",
        _REAL_LOADER,
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(
            f"Could not load real seed_data/load.py from {_REAL_LOADER}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_real = _load_real_module()

# Re-export public API
load_seed_data = _real.load_seed_data
SeedDataLoadError = _real.SeedDataLoadError

__all__ = ["load_seed_data", "SeedDataLoadError"]


def _cli() -> None:  # pragma: no cover - thin shim
    _real._cli()


if __name__ == "__main__":
    _cli()
