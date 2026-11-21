"""Unit tests: test-selection weighting and risk-score boundaries (all bands)."""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.app.tools.sap_tools import (
    SELECTION_THRESHOLD, band_for_score, compute_risk, score_test_candidate,
)


# ---------------------------------------------------------------- selection weighting

def test_score_perfect_focus_critical_interface():
    score, parts = score_test_candidate(
        covered_impacted=2, total_validated=2, criticality="CRITICAL",
        defect_rate=0.12, covers_interface=True)
    assert score == 0.45 + 0.25 + 0.15 + 0.15
    assert parts["coverage_focus"] == 0.45


def test_score_low_relevance_test_stays_below_threshold():
    score, _ = score_test_candidate(
        covered_impacted=1, total_validated=4, criticality="LOW",
        defect_rate=0.0, covers_interface=False)
    expected = 0.45 * 0.25 + 0.25 * 0.25 + 0.0
    assert abs(score - round(expected, 4)) < 1e-6
    assert score < SELECTION_THRESHOLD


def test_score_monotonic_in_each_component():
    base = dict(covered_impacted=1, total_validated=2, criticality="MEDIUM",
                defect_rate=0.02, covers_interface=False)
    s_base, _ = score_test_candidate(**base)
    s_more_cov, _ = score_test_candidate(**{**base, "covered_impacted": 2})
    s_crit, _ = score_test_candidate(**{**base, "criticality": "CRITICAL"})
    s_hist, _ = score_test_candidate(**{**base, "defect_rate": 0.10})
    s_iface, _ = score_test_candidate(**{**base, "covers_interface": True})
    for s in (s_more_cov, s_crit, s_hist, s_iface):
        assert s > s_base


# ---------------------------------------------------------------- risk bands

def test_band_boundaries_exact():
    assert band_for_score(0) == "LOW"
    assert band_for_score(29.99) == "LOW"
    assert band_for_score(30) == "MEDIUM"
    assert band_for_score(49.99) == "MEDIUM"
    assert band_for_score(50) == "HIGH"
    assert band_for_score(79.99) == "HIGH"
    assert band_for_score(80) == "CRITICAL"
    assert band_for_score(100) == "CRITICAL"


def test_risk_low_profile():
    r = compute_risk(
        impacted_processes=[("IM", "MEDIUM")], custom_code_count=1,
        interface_count=0, selected_defect_rates=[0.01],
        coverage_gap_ratio=0.0, size_bucket="SMALL")
    assert r["band"] == "LOW"
    assert 20 <= r["score"] < 30


def test_risk_medium_single_process_no_interface():
    r = compute_risk(
        impacted_processes=[("R2R", "HIGH")], custom_code_count=2,
        interface_count=0, selected_defect_rates=[0.06],
        coverage_gap_ratio=0.0, size_bucket="MEDIUM")
    assert r["band"] in ("MEDIUM", "HIGH")
    assert r["factor_breakdown"]["interfaces"]["raw"] == 0.0


def test_risk_high_canonical_shape():
    r = compute_risk(
        impacted_processes=[("O2C", "CRITICAL"), ("R2R", "HIGH")],
        custom_code_count=3, interface_count=1,
        selected_defect_rates=[0.10], coverage_gap_ratio=0.0,
        size_bucket="MEDIUM")
    assert r["band"] == "HIGH"
    assert r["score"] >= 50


def test_risk_critical_requires_extreme_combination():
    r = compute_risk(
        impacted_processes=[("A", "CRITICAL"), ("B", "CRITICAL"),
                            ("C", "HIGH"), ("D", "MEDIUM")],
        custom_code_count=4, interface_count=3,
        selected_defect_rates=[0.15], coverage_gap_ratio=0.5,
        size_bucket="LARGE")
    assert r["band"] == "CRITICAL"


def test_weights_sum_to_one():
    from backend.app.tools.sap_tools import RISK_WEIGHTS

    assert abs(sum(RISK_WEIGHTS.values()) - 1.0) < 1e-9
