"""Entry point.

Responsibility: launch the Streamlit UI as a subprocess via the ``agent-crew`` console script.
Must not: contain any application logic — keep this file a thin launcher.
Next: streamlit_app.py (UI layer), or graph.py (pipeline entry points run_plan / stream_build).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    app = Path(__file__).resolve().parents[2] / "streamlit_app.py"
    raise SystemExit(
        subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)])  # noqa: S603
    )
