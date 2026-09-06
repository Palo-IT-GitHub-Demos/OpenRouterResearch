"""Recheck one k=1 objective quality failure through OpenRouter.

The command measures reproducibility only. It does not attribute a failure to
OpenRouter, an upstream provider, or the model. Rechecks are explicit because
they are billable API calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.data_prep import load_quality_details  # noqa: E402
from src.core.config import Settings, get_settings  # noqa: E402

Verification = Literal["confirmed_failure", "not_reproduced", "unstable", "inconclusive"]


@dataclass(frozen=True)
class RecheckResult:
    """One OpenRouter recheck with non-secret routing evidence."""

    response: str
    passed: bool
    generation_id: str | None
    resolved_model: str | None
    provider_name: str | None = None
    upstream_id: str | None = None
    error: str | None = None


def classify_verification(rechecks: list[RecheckResult]) -> Verification:
    """Classify reproducibility without making a causal attribution."""
    if len(rechecks) < 2 or any(result.error for result in rechecks):
        return "inconclusive"
    passes = [result.passed for result in rechecks]
    if all(passes):
        return "not_reproduced"
    if not any(passes):
        return "confirmed_failure"
    return "unstable"


def _is_expected(response: str, accepted_answers: list[str]) -> bool:
    normalized = response.strip().casefold()
    return normalized in {answer.strip().casefold() for answer in accepted_answers}


def _openrouter_recheck(
    client: httpx.Client,
    settings: Settings,
    model: str,
    prompt: str,
    accepted_answers: list[str],
) -> RecheckResult:
    try:
        response = client.post(
            f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0},
        )
        response.raise_for_status()
        payload = response.json()
        generation_id = payload.get("id")
        content = payload["choices"][0]["message"].get("content") or ""
        provider_name = None
        upstream_id = None
        if isinstance(generation_id, str):
            metadata_response = client.get(
                f"{settings.openrouter_base_url.rstrip('/')}/generation",
                headers={"Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}"},
                params={"id": generation_id},
            )
            if metadata_response.is_success:
                metadata = metadata_response.json().get("data", {})
                provider_name = metadata.get("provider_name")
                upstream_id = metadata.get("upstream_id")
        return RecheckResult(
            response=content,
            passed=_is_expected(content, accepted_answers),
            generation_id=generation_id if isinstance(generation_id, str) else None,
            resolved_model=payload.get("model"),
            provider_name=provider_name,
            upstream_id=upstream_id,
        )
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        return RecheckResult("", False, None, None, error=str(exc))


def _selected_evidence(results_path: Path, model: str, prompt_id: int) -> tuple[pd.Series, int]:
    evidence = load_quality_details(results_path)
    if evidence.empty or "prompt_id" not in evidence.columns:
        raise ValueError(f"No quality evidence with prompt IDs found for {results_path}.")
    prompt_ids = pd.to_numeric(evidence["prompt_id"], errors="coerce")
    selected = evidence.loc[(evidence["model"] == model) & (prompt_ids == prompt_id)]
    if selected.empty:
        raise ValueError(f"No quality evidence for model={model!r}, prompt_id={prompt_id}.")
    attempts = pd.to_numeric(selected.get("attempt", pd.Series(0, index=selected.index)), errors="coerce")
    repetition_count = int(attempts.nunique())
    if repetition_count > 1:
        raise ValueError(
            f"This prompt already has k={repetition_count} attempts in the run. "
            "Use the recorded stability evidence; extra OpenRouter rechecks are not justified."
        )
    row = selected.iloc[0]
    if row.get("verification_status") != "optional_openrouter_recheck":
        raise ValueError(
            "This evidence is not eligible for an OpenRouter recheck. Only failed objective prompts "
            "from a k=1 run with verification_status=optional_openrouter_recheck are accepted."
        )
    return row, repetition_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recheck one k=1 objective failure twice through OpenRouter.")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt-id", type=int, required=True)
    parser.add_argument("--rechecks", type=int, default=2, choices=range(2, 6))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    row, original_repetitions = _selected_evidence(args.results, args.model, args.prompt_id)
    accepted_answers = json.loads(str(row.get("expected_answers_json", "[]")))
    if not isinstance(accepted_answers, list) or not accepted_answers:
        raise ValueError(
            "The selected evidence has no objective accepted answers; it cannot be rechecked automatically."
        )

    prompt = str(row["prompt"])
    settings = get_settings()
    with httpx.Client(timeout=settings.request_timeout) as client:
        rechecks = [
            _openrouter_recheck(client, settings, args.model, prompt, accepted_answers)
            for _ in range(args.rechecks)
        ]

    verification = classify_verification(rechecks)
    report = {
        "source_benchmark": str(args.results),
        "model": args.model,
        "prompt_id": args.prompt_id,
        "original_repetitions": original_repetitions,
        "prompt": prompt,
        "accepted_answers": accepted_answers,
        "verification": verification,
        "interpretation": {
            "confirmed_failure": "The objective failure occurred on every OpenRouter recheck.",
            "not_reproduced": "Every OpenRouter recheck passed; the original failure was not reproduced.",
            "unstable": "OpenRouter rechecks produced both passing and failing answers.",
            "inconclusive": "A recheck failed technically or insufficient evidence was available.",
        }[verification],
        "rechecks": [asdict(result) for result in rechecks],
    }
    output = args.output or (
        args.results.parent
        / "verification"
        / f"{args.results.stem}_{args.model.replace('/', '_')}_prompt_{args.prompt_id}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Verification: {verification}\nWrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())