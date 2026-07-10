"""Load the hyphenated NoneBot plugin as an importable package for tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_send_package() -> None:
    name = "amia_plugin_send"
    if name in sys.modules:
        return
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        name,
        root / "__init__.py",
        submodule_search_locations=[str(root)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Amia-plugin-send")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
