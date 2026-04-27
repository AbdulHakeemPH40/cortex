import os
from pathlib import Path


def get_cortex_temp_dir() -> str:
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir:
        return tmpdir
    return str(Path.home() / ".cortex" / "tmp")


def get_cortex_temp_dir_name() -> str:
    return "tmp"


__all__ = [
    "get_cortex_temp_dir",
    "get_cortex_temp_dir_name",
]
