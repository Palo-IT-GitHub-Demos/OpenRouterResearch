"""Tests for pure model-selection helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.model_selector import (
    ModelCatalogEntry,
    catalog_entries,
    estimate_cost_usd,
    estimate_requests,
    load_selection,
    save_selection,
    select_models,
)


def _entries() -> list[ModelCatalogEntry]:
    return [
        ModelCatalogEntry("vendor/free:free", 0.0, 0.0, 32_000),
        ModelCatalogEntry("vendor/cheap", 0.0000002, 0.0000006, 32_000),
        ModelCatalogEntry("vendor/large", 0.000001, 0.000003, 128_000),
    ]


def test_catalog_entries_reads_openrouter_pricing() -> None:
    entries = catalog_entries(
        [{"id": "vendor/model", "pricing": {"prompt": "0.000001", "completion": "0.000002"}, "context_length": 8192}]
    )

    assert entries[0].model_id == "vendor/model"
    assert entries[0].context_length == 8192


def test_select_models_filters_paid_price_and_context() -> None:
    selected = select_models(_entries(), paid_only=True, max_output_price_per_million=1.0, min_context_length=32_000)

    assert [entry.model_id for entry in selected] == ["vendor/cheap"]


def test_estimates_requests_and_cost() -> None:
    assert estimate_requests(2, 16, 5) == 42
    assert estimate_cost_usd(
        _entries()[1:2], daily_requests=1, avg_prompt_tokens=1_000_000, avg_completion_tokens=0, working_days=1
    ) == pytest.approx(0.2)


def test_paid_and_free_filters_cannot_be_combined() -> None:
    with pytest.raises(ValueError, match="both"):
        select_models(_entries(), paid_only=True, free_only=True)


def test_zero_priced_catalog_route_is_treated_as_free() -> None:
    route = ModelCatalogEntry("openrouter/free", 0.0, 0.0, 200_000)

    assert route.is_free


def test_paid_filter_excludes_zero_priced_catalog_route() -> None:
    selected = select_models(_entries() + [ModelCatalogEntry("openrouter/free", 0.0, 0.0, 200_000)], paid_only=True)

    assert all(not entry.is_free for entry in selected)


def test_selection_can_be_saved_and_loaded(tmp_path: Path) -> None:
    path = tmp_path / "selection.json"

    save_selection(["vendor/cheap"], path)

    assert load_selection(path) == ["vendor/cheap"]
