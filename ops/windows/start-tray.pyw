"""Start the project's tray worker from the base interpreter's GUI executable."""

import os
import subprocess
import sys
from pathlib import Path


if __name__ == "__main__":
    project = Path(__file__).resolve().parents[2]
    # Use the base GUI binary with the same environment hint as CPython's venv
    # redirector. uv's pythonw shim can start a console python.exe internally.
    venv_executable = project / ".venv/Scripts/pythonw.exe"
    subprocess.Popen(
        [str(Path(sys.base_prefix) / "pythonw.exe"), "-B", "-m", "stockinsight.launcher",
         "--background", *sys.argv[1:]],
        cwd=project, env={**os.environ, "__PYVENV_LAUNCHER__": str(venv_executable)},
        creationflags=subprocess.DETACHED_PROCESS,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
