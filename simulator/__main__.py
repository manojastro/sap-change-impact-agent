"""python -m simulator : seed the simulated landscape into the configured DB."""
from __future__ import annotations

import sys
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "backend")):
    if _p not in sys.path:
        sys.path.append(_p)

from backend.app.db import get_session_factory, init_db  # noqa: E402
from simulator.generate_landscape import SIMULATION_LABEL, seed_landscape  # noqa: E402


def main() -> None:
    init_db()
    session = get_session_factory()()
    counts = seed_landscape(session)
    print(SIMULATION_LABEL)
    print("Seeded:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
