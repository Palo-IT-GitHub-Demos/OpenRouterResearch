"""LLM-as-a-Judge quality evaluator.

Bias mitigations applied
------------------------
- **Position bias**: model responses are shuffled into random aliases (A, B, C …)
  before being shown to the judge.  Aliases are remapped back to real model IDs
  after scoring so results are always traceable.
- **Verbosity bias**: the judge rubric explicitly instructs the model *not* to
  favour longer answers and to score only accuracy and instruction-following.
- **Structured output**: the judge must return a JSON object validated by the
  ``JudgeOutput`` Pydantic model, preventing free-form hallucination of scores.
- **Chain-of-Thought**: the judge is required to reason through its evaluation
  in 3-5 sentences before assigning a score, reducing evaluation hallucinations.

V2 additions
------------
- :class:`AsyncQualityJudge` — fully async, parallelises across prompts.
- Deterministic pre-evaluation: JSON/code responses are checked with
  :mod:`src.evaluators.deterministic_eval` before calling the LLM judge.
- ``run_dataset`` collects model responses at runtime (no pre-filled fixture).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from src.api.openrouter_client import AsyncOpenRouterClient, OpenRouterClient
from src.evaluators.deterministic_eval import CHECKS

logger = logging.getLogger(__name__)

# ── Pydantic models for structured judge output ────────────────────────────────


class ModelScore(BaseModel):
    """Score for a single model alias as returned by the judge."""

    model_alias: str = Field(description="Alias assigned to the model (e.g. 'A').")
    reasoning: str = Field(description="3-5 sentence chain-of-thought analysis before the score.")
    score: int = Field(ge=1, le=5, description="Quality score from 1 (worst) to 5 (best).")


class JudgeOutput(BaseModel):
    """Complete structured output returned by the judge LLM."""

    scores: list[ModelScore]


class JudgeResult(BaseModel):
    """Final score for one model, with the original model ID restored."""

    model: str
    score: int = Field(ge=1, le=5)
    reasoning: str


@dataclass
class CollectResult:
    """Output of :meth:`AsyncQualityJudge.run_collect`.

    Contains scores from deterministic checks (no LLM call) and the set of
    prompt/response pairs that are undecidable and require a judge.
    """

    deterministic_rows: list[dict[str, object]] = field(default_factory=list)
    pending_judgments: list[dict[str, object]] = field(default_factory=list)
    # pending_judgments schema:
    # [{
    #   "prompt_id": int,
    #   "prompt": str,
    #   "prompt_preview": str,
    #   "category": str | None,
    #   "alias_map": {"A": "model/id", ...},   ← aliases for position-bias mitigation
    #   "responses": {"A": "text", ...}
    # }]


# ── Prompt templates ───────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an impartial AI quality evaluator. Your task is to score multiple model \
responses to a given prompt on a scale from 1 to 5.

Scoring rubric:
  5 — Fully correct, follows all instructions precisely.
  4 — Mostly correct with minor issues.
  3 — Partially correct; some instructions missed or minor factual errors.
  2 — Mostly incorrect or ignores key instructions.
  1 — Completely wrong or harmful.

Critical anti-bias rules (you MUST follow these):
  - Do NOT favour longer or more verbose responses. Brevity that is correct \
scores the same as a long correct answer.
  - Do NOT favour the first response you read. Treat each response independently.
  - Score based ONLY on accuracy, instruction-following, and absence of errors.

Chain-of-Thought requirement:
  - Before assigning any score, reason through your evaluation in 3-5 sentences.
  - Explain WHY each response deserves its score, referencing specific issues.
  - Your reasoning MUST appear in the JSON "reasoning" field BEFORE the "score" field.

You MUST respond with a valid JSON object matching exactly this schema:
{
  "scores": [
    {
      "model_alias": "<alias letter, e.g. A>",
      "reasoning": "<3-5 sentence chain-of-thought analysis>",
      "score": <1-5>
    },
    ...
  ]
}
The "model_alias" field must be EXACTLY the single letter shown in [MODEL X] headers (e.g. "A", "B", "C").
Do not include any text outside the JSON object."""

_USER_TEMPLATE = """\
## Prompt given to models
{prompt}

## Responses to evaluate
{responses_block}

Each response is labelled [MODEL A], [MODEL B], etc. Use ONLY the single letter \
(A, B, C…) as the "model_alias" in your JSON. Think carefully and reason through \
your evaluation before giving a score. Return only the JSON object."""


# ── Synchronous judge (V1 compat) ──────────────────────────────────────────────


class QualityJudge:
    """Evaluate model responses using a judge LLM with bias mitigations."""

    def __init__(self, client: OpenRouterClient, judge_model: str) -> None:
        self._client = client
        self._judge_model = judge_model

    def evaluate(
        self,
        prompt: str,
        responses: dict[str, str],
    ) -> dict[str, JudgeResult]:
        """Score each model's response using the judge LLM."""
        if not responses:
            return {}

        model_ids = list(responses.keys())
        random.shuffle(model_ids)
        alias_map: dict[str, str] = {
            _alias(i): model_id for i, model_id in enumerate(model_ids)
        }
        reverse_map: dict[str, str] = {v: k for k, v in alias_map.items()}

        responses_block = "\n\n".join(
            f"[MODEL {reverse_map[model_id]}]\n{responses[model_id]}"
            for model_id in model_ids
        )
        user_message = _USER_TEMPLATE.format(
            prompt=prompt, responses_block=responses_block
        )

        completion = self._client.chat_completion(
            model=self._judge_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
        )

        raw_content = (completion.choices[0].message.content or "").strip()
        judge_output = _parse_judge_output(raw_content)

        results: dict[str, JudgeResult] = {}
        for model_score in judge_output.scores:
            model_id = alias_map.get(model_score.model_alias)
            if model_id is None:
                logger.warning(
                    "Judge returned unknown alias '%s'; skipping.", model_score.model_alias
                )
                continue
            results[model_id] = JudgeResult(
                model=model_id,
                score=model_score.score,
                reasoning=model_score.reasoning,
            )

        return results

    def run_dataset(self, prompts_path: Path) -> pd.DataFrame:
        """Evaluate all prompts in a JSON fixture file (responses must be pre-filled)."""
        with prompts_path.open() as fh:
            dataset: list[dict[str, Any]] = json.load(fh)

        rows: list[dict[str, object]] = []
        for idx, entry in enumerate(dataset):
            prompt: str = entry["prompt"]
            responses: dict[str, str] = entry.get("responses", {})
            if not responses:
                continue
            logger.info("Evaluating prompt %d/%d …", idx + 1, len(dataset))
            for model_id, result in self.evaluate(prompt=prompt, responses=responses).items():
                rows.append(
                    {
                        "prompt_id": idx,
                        "prompt_preview": prompt[:80],
                        "model": model_id,
                        "score": result.score,
                        "reasoning": result.reasoning,
                    }
                )

        df = pd.DataFrame(rows)
        return (
            df.sort_values(["prompt_id", "score"], ascending=[True, False]).reset_index(drop=True)
            if not df.empty
            else df
        )

    @staticmethod
    def _parse_judge_output(raw: str) -> JudgeOutput:
        return _parse_judge_output(raw)


# ── Asynchronous judge (V2) ────────────────────────────────────────────────────


class AsyncQualityJudge:
    """Async LLM-as-a-Judge with deterministic pre-evaluation and CoT prompting.

    Evaluation flow per prompt:
    1. Run deterministic checks (JSON validity, Python syntax, …) on each response.
    2. If ALL responses have a definitive score → skip the LLM call (cost saving).
    3. For undecidable responses → call the judge LLM with CoT prompt.
    4. Collect responses from target models at runtime (no pre-filled fixture).
    """

    def __init__(self, client: AsyncOpenRouterClient, judge_model: str) -> None:
        self._client = client
        self._judge_model = judge_model

    # ── Public API ─────────────────────────────────────────────────────────────

    async def evaluate(
        self,
        prompt: str,
        responses: dict[str, str],
        category: str | None = None,
    ) -> dict[str, JudgeResult]:
        """Score each model's response, applying deterministic checks first.

        Args:
            prompt: The original prompt sent to the models.
            responses: Mapping of ``{model_id: response_text}``.
            category: Prompt category key (e.g. ``"json_output"``); used to
                select the appropriate deterministic check.

        Returns:
            Mapping of ``{model_id: JudgeResult}`` with scores 1–5.
        """
        if not responses:
            return {}

        results: dict[str, JudgeResult] = {}
        undecidable: dict[str, str] = {}

        # 1. Deterministic pre-evaluation.
        if category:
            check = CHECKS.get(category)
            if check is not None:
                for model_id, response in responses.items():
                    cr = check.run(prompt, response)
                    if cr.score is not None:
                        results[model_id] = JudgeResult(
                            model=model_id,
                            score=cr.score,
                            reasoning=cr.reason,
                        )
                    else:
                        undecidable[model_id] = response
            else:
                undecidable = dict(responses)
        else:
            undecidable = dict(responses)

        if not undecidable:
            return results

        # 2. LLM judge for undecidable responses.
        llm_results = await self._llm_evaluate(prompt, undecidable)
        results.update(llm_results)
        return results

    async def run_dataset(
        self,
        prompts_path: Path,
        models: list[str],
    ) -> pd.DataFrame:
        """Collect model responses and evaluate all prompts in a fixture file.

        Args:
            prompts_path: Path to a JSON file with a list of ``{prompt, category}``
                objects.
            models: List of OpenRouter model IDs to benchmark.

        Returns:
            DataFrame with columns: ``prompt_id``, ``prompt_preview``, ``model``,
            ``score``, ``reasoning``.
        """
        with prompts_path.open() as fh:
            dataset: list[dict[str, Any]] = json.load(fh)

        async def _process(idx: int, entry: dict[str, Any]) -> list[dict[str, object]]:
            prompt: str = entry["prompt"]
            category: str | None = entry.get("category")
            logger.info("Collecting responses for prompt %d/%d …", idx + 1, len(dataset))
            responses = await self._collect_responses(prompt, models)
            eval_results = await self.evaluate(
                prompt=prompt, responses=responses, category=category
            )
            return [
                {
                    "prompt_id": idx,
                    "prompt_preview": prompt[:80],
                    "model": model_id,
                    "score": r.score,
                    "reasoning": r.reasoning,
                }
                for model_id, r in eval_results.items()
            ]

        batches = await asyncio.gather(*[_process(i, e) for i, e in enumerate(dataset)])
        rows = [row for batch in batches for row in batch]
        df = pd.DataFrame(rows)
        return (
            df.sort_values(["prompt_id", "score"], ascending=[True, False]).reset_index(drop=True)
            if not df.empty
            else df
        )

    # ── Collect-only (split pipeline) ─────────────────────────────────────────

    async def run_collect(
        self,
        prompts_path: Path,
        models: list[str],
    ) -> CollectResult:
        """Collect model responses + run deterministic checks.  No LLM calls.

        Returns a :class:`CollectResult` separating:
        - **deterministic_rows** — prompts with a clear pass/fail (json, code syntax).
        - **pending_judgments** — undecidable responses that require a judge.

        Aliased responses in ``pending_judgments`` preserve position-bias
        mitigation: the ``alias_map`` is needed by :class:`MergePipeline` to
        remap Copilot's scores back to model IDs.
        """
        with prompts_path.open() as fh:
            dataset: list[dict[str, Any]] = json.load(fh)

        deterministic_rows: list[dict[str, object]] = []
        pending_judgments: list[dict[str, object]] = []

        async def _process(idx: int, entry: dict[str, Any]) -> None:
            prompt: str = entry["prompt"]
            category: str | None = entry.get("category")
            logger.info("Collecting responses for prompt %d/%d …", idx + 1, len(dataset))
            responses = await self._collect_responses(prompt, models)

            check = CHECKS.get(category or "") if category else None
            undecidable: dict[str, str] = {}

            if check is not None:
                for model_id, response in responses.items():
                    cr = check.run(prompt, response)
                    if cr.score is not None:
                        deterministic_rows.append({
                            "prompt_id": idx,
                            "prompt_preview": prompt[:80],
                            "model": model_id,
                            "score": cr.score,
                            "reasoning": cr.reason,
                            "source": "deterministic",
                        })
                    else:
                        undecidable[model_id] = response
            else:
                undecidable = dict(responses)

            if undecidable:
                model_ids = list(undecidable.keys())
                random.shuffle(model_ids)
                alias_map = {_alias(i): mid for i, mid in enumerate(model_ids)}
                pending_judgments.append({
                    "prompt_id": idx,
                    "prompt": prompt,
                    "prompt_preview": prompt[:80],
                    "category": category,
                    "alias_map": alias_map,
                    "responses": {alias: undecidable[mid] for alias, mid in alias_map.items()},
                })

        await asyncio.gather(*[_process(i, e) for i, e in enumerate(dataset)])

        return CollectResult(
            deterministic_rows=sorted(deterministic_rows, key=lambda r: int(str(r["prompt_id"]))),
            pending_judgments=sorted(pending_judgments, key=lambda p: int(str(p["prompt_id"]))),
        )

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _collect_responses(
        self, prompt: str, models: list[str]
    ) -> dict[str, str]:
        """Send *prompt* to all *models* in parallel and return responses."""

        async def _get(model: str) -> tuple[str, str]:
            try:
                completion = await self._client.chat_completion(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                )
                content = (
                    completion.choices[0].message.content
                    if completion.choices
                    else None
                )
                return model, content or ""
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to get response from '%s': %s", model, exc)
                return model, ""

        pairs = await asyncio.gather(*[_get(m) for m in models])
        return dict(pairs)

    async def _llm_evaluate(
        self, prompt: str, responses: dict[str, str]
    ) -> dict[str, JudgeResult]:
        """Call the judge LLM with position-shuffled aliases."""
        model_ids = list(responses.keys())
        random.shuffle(model_ids)
        alias_map = {_alias(i): mid for i, mid in enumerate(model_ids)}
        reverse_map = {v: k for k, v in alias_map.items()}

        responses_block = "\n\n".join(
            f"[MODEL {reverse_map[mid]}]\n{responses[mid]}" for mid in model_ids
        )
        user_message = _USER_TEMPLATE.format(
            prompt=prompt, responses_block=responses_block
        )

        completion = await self._client.chat_completion(
            model=self._judge_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
        )

        raw = (completion.choices[0].message.content or "").strip()
        judge_output = _parse_judge_output(raw)

        results: dict[str, JudgeResult] = {}
        for ms in judge_output.scores:
            model_id = alias_map.get(ms.model_alias)
            if model_id is None:
                logger.warning("Judge returned unknown alias '%s'; skipping.", ms.model_alias)
                continue
            results[model_id] = JudgeResult(
                model=model_id, score=ms.score, reasoning=ms.reasoning
            )
        return results


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _parse_judge_output(raw: str) -> JudgeOutput:
    """Extract and validate the JSON block from the judge's response."""
    content = raw
    if "```" in content:
        start = content.find("{")
        end = content.rfind("}") + 1
        content = content[start:end]

    try:
        data = json.loads(content)
        return JudgeOutput.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Judge returned malformed JSON. Raw output:\n{raw}") from exc


def _alias(index: int) -> str:
    """Convert a zero-based index to a letter alias (0 → 'A', 1 → 'B', …)."""
    return chr(ord("A") + index)
