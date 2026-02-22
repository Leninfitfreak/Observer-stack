from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATES = [HERE / "src", HERE.parent / "src"]
for candidate in CANDIDATES:
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from ai_observer.api.app import create_app

app = create_app()
