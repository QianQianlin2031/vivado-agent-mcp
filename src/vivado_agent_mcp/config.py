"""Vivado executable discovery and runtime configuration."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def discover_vivado(explicit_path: str | None = None) -> Path | None:
    """Find Vivado without starting it.

    Discovery order is deliberately deterministic so an Agent can explain which
    installation it selected.
    """

    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path).expanduser())

    env_path = os.getenv("VIVADO_PATH")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    on_path = shutil.which("vivado") or shutil.which("vivado.bat")
    if on_path:
        candidates.append(Path(on_path))

    if os.name == "nt":
        xilinx_root = Path("C:/Xilinx/Vivado")
        if xilinx_root.exists():
            candidates.extend(sorted(xilinx_root.glob("*/bin/vivado.bat"), reverse=True))
    else:
        xilinx_root = Path("/tools/Xilinx/Vivado")
        if xilinx_root.exists():
            candidates.extend(sorted(xilinx_root.glob("*/bin/vivado"), reverse=True))

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    return None
