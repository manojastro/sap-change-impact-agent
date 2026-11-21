"""Pytest configuration: isolated test DB + shared helpers."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / "data" / "test_sap_change_impact.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
# must be set before backend.app.db is imported anywhere
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ.setdefault("LLM_MODE", "mock")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    if TEST_DB.exists():
        TEST_DB.unlink()
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def seeded(client):
    resp = client.post("/api/v1/simulator/seed")
    assert resp.status_code == 200, resp.text
    return client


def gt_entry(key: str) -> dict:
    data = json.loads((ROOT / "evaluation" / "ground_truth.json").read_text(encoding="utf-8"))
    return next(e for e in data["transports"] if e["key"] == key)


def import_transport(seeded, key: str) -> dict:
    entry = gt_entry(key)
    resp = seeded.post("/api/v1/transports", json=entry["transport"])
    assert resp.status_code == 201, resp.text
    return resp.json()


def import_and_analyze(seeded, key: str) -> tuple[dict, dict]:
    tr = import_transport(seeded, key)
    resp = seeded.post("/api/v1/analyses",
                       json={"transport_id_ref": tr["id"], "wait": True})
    assert resp.status_code == 202, resp.text
    analysis = resp.json()
    assert analysis["status"] == "COMPLETED", analysis
    return tr, analysis


def wait_for_analysis(seeded, analysis_id: int, timeout_s: float = 30.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        a = seeded.get(f"/api/v1/analyses/{analysis_id}").json()
        if a["status"] in ("COMPLETED", "FAILED"):
            return a
        time.sleep(0.25)
    raise TimeoutError(f"analysis {analysis_id} did not finish in {timeout_s}s")
