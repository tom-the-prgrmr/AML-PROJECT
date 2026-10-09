"""TxnGenParams.from_settings reads the active profile, thresholds and DQ settings."""

from __future__ import annotations

from datetime import date

from aml.common.config import load_settings
from aml.datagen.activity import TxnGenParams


def test_from_settings_maps_config() -> None:
    settings = load_settings(environ={"AML__DATA__PROFILE": "dense"})
    params = TxnGenParams.from_settings(settings)
    assert params.n_transactions == settings.data.active.transactions
    assert params.months == 6
    assert params.counterparties == (50, 100)
    assert params.start_date == date(2026, 1, 1)
    assert params.large_cash_vnd == 400_000_000
    assert params.structuring_band_pct == 0.10
    assert params.duplicate_rate == settings.data.dq_defect_rate
    assert params.injection_memos == 30
    assert set(params.typology_counts) == {
        "structuring",
        "rapid_movement",
        "mule_ring",
        "round_tripping",
        "benign_payroll",
        "benign_merchant",
    }
    scale = settings.data.active.typology_scale
    assert params.typology_counts == {k: v * scale for k, v in settings.data.typologies.items()}
