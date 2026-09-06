"""Unit tests for dashboard/security_viz.py."""

from __future__ import annotations

import math

import pandas as pd

from dashboard.security_viz import build_owasp_heatmap


def test_owasp_heatmap_displays_missing_security_data_as_na() -> None:
    security_df = pd.DataFrame(
        {
            "model": ["model-a", "model-b"],
            "category_id": ["LLM01", "LLM01"],
            "vulnerability_rate": [0.0, float("nan")],
        }
    )

    figure = build_owasp_heatmap(security_df)

    assert figure.data[0].text[0][0] == "0%"
    assert figure.data[0].text[1][0] == "N/A"
    assert math.isnan(figure.data[0].z[1][0])