"""Quality evaluator — deterministic pre-evaluation + Copilot judge agents.

Evaluation strategy
-------------------
- **Phase 1** (``run_collect``): responses are collected from target models and
  scored deterministically where possible (JSON validity, Python syntax).
  Undecidable responses are saved as pending judgments.
- **Phase 2** (Copilot agents): a judge agent (@judge-anthropic, @judge-openai
  or @judge-google) reads the pending file and writes scored results.
- **Phase 3** (``MergePipeline``): deterministic + Copilot scores are merged
  with pricing and security data and exported.

The LLM-judge-via-OpenRouter path has been removed.  Judging is exclusively
handled by GitHub Copilot agents — zero extra API cost.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.api.openrouter_client import AsyncOpenRouterClient, OpenRouterClient
from src.evaluators.deterministic_eval import CHECKS

logger = logging.getLogger(__name__)

QUALITY_SUITE_VERSION = "generic-screen-v1"

FORMAT_COMPLIANCE_DIMENSION = "output_format_compliance"
"""Dimension carrying strict-output adherence, kept apart from content correctness."""

# ── Pydantic models for structured judge output ────────────────────────────────


class ModelScore(BaseModel):
    """Score for a single model alias as returned by the judge."""

    model_alias: str = Field(description="Alias assigned to the model (e.g. 'A').")
    reasoning: str = Field(description="Brief evidence-based rationale for the assigned score.")
    score: int = Field(ge=1, le=5, description="Quality score from 1 (worst) to 5 (best).")


class JudgeOutput(BaseModel):
    """Complete structured output returned by the judge LLM."""

    scores: list[ModelScore]


class JudgeResult(BaseModel):
    """Final score for one model, with the original model ID restored."""

    model: str
    score: int = Field(ge=1, le=5)
    reasoning: str


_EXACT_ANSWER_CATEGORIES = {"exact_answer", "factual_sanity", "logical_reasoning"}
_ALLOWED_MESSAGE_ROLES = {"system", "user", "assistant"}


def _validate_evaluation_contract(category: str, accepted_answers: list[str], judge_criteria: list[str]) -> None:
    """Require objective references or explicit judge criteria for a category.

    Kept independent of :class:`QualityPrompt` so the business rule can be
    unit-tested and reused (e.g. by a prompt-authoring CLI) without
    constructing a full Pydantic model.

    Raises:
        ValueError: If the category requires accepted answers or judge
            criteria and none were supplied.
    """
    if category in _EXACT_ANSWER_CATEGORIES and not accepted_answers:
        raise ValueError(f"Category '{category}' requires non-empty accepted_answers.")
    if category not in CHECKS and not judge_criteria:
        raise ValueError(f"Unmapped category '{category}' requires non-empty judge_criteria for blind evaluation.")


class QualityMessage(BaseModel):
    """One message in a provider-neutral quality scenario."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    content: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_role(self) -> QualityMessage:
        """Restrict scenario roles to OpenRouter chat-completion roles."""
        if self.role not in _ALLOWED_MESSAGE_ROLES:
            raise ValueError(f"Unsupported message role '{self.role}'.")
        return self


class QualityPrompt(BaseModel):
    """Validated definition of one provider-neutral quality-screen prompt."""

    model_config = ConfigDict(extra="forbid")

    prompt: str | None = Field(default=None, min_length=1)
    messages: list[QualityMessage] | None = None
    category: str = Field(min_length=1)
    quality_dimension: str = Field(default="general", min_length=1)
    responses: dict[str, str] = Field(default_factory=dict)
    accepted_answers: list[str] = Field(default_factory=list)
    expected_json: object | None = None
    strict_output: bool = False
    required_function: str | None = None
    required_parameters: list[str] = Field(default_factory=list)
    judge_criteria: list[str] = Field(default_factory=list)
    reference_answer: str | None = None
    weight: float = Field(default=1.0, gt=0.0)

    @model_validator(mode="after")
    def validate_evaluation_contract(self) -> QualityPrompt:
        """Require exactly one input format and a valid evaluation contract."""
        if (self.prompt is None) == (self.messages is None):
            raise ValueError("Provide exactly one of 'prompt' or 'messages'.")
        _validate_evaluation_contract(self.category, self.accepted_answers, self.judge_criteria)
        return self

    @property
    def request_messages(self) -> list[dict[str, str]]:
        """Return the complete conversation to send in one API call."""
        if self.messages is not None:
            return [message.model_dump() for message in self.messages]
        return [{"role": "user", "content": self.prompt or ""}]

    @property
    def display_prompt(self) -> str:
        """Return a durable transcript for deterministic evidence and judging."""
        if self.messages is None:
            return self.prompt or ""
        return "\n".join(f"{message.role}: {message.content}" for message in self.messages)

    @property
    def evaluation_context(self) -> dict[str, object]:
        """Return the deterministic-check metadata for this prompt."""
        return {
            "accepted_answers": self.accepted_answers,
            "expected_json": self.expected_json,
            "strict_output": self.strict_output,
            "required_function": self.required_function,
            "required_parameters": self.required_parameters,
        }


@dataclass(frozen=True)
class CollectedResponse:
    """One model response or collection failure for a prompt attempt."""

    model: str
    attempt: int
    content: str
    error: str | None = None
    generation_id: str | None = None
    resolved_model: str | None = None
    request_sha256: str = ""


def _request_sha256(messages: list[dict[str, str]]) -> str:
    """Return a stable fingerprint of the exact local request messages."""
    payload = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class CollectResult:
    """Output of :meth:`AsyncQualityJudge.run_collect`.

    Contains scores from deterministic checks (no LLM call) and the set of
    prompt/response pairs that are undecidable and require a judge.
    """

    deterministic_rows: list[dict[str, object]] = field(default_factory=list)
    pending_judgments: list[dict[str, object]] = field(default_factory=list)
    collection_errors: list[dict[str, object]] = field(default_factory=list)
    prompt_count: int = 0
    dimension_count: int = 0
    repetitions: int = 1
    quality_suite_id: str = ""
    # pending_judgments schema:
    # [{
    #   "prompt_id": int,
    #   "prompt": str,
    #   "prompt_preview": str,
    #   "category": str | None,
    #   "alias_map": {"A": "model/id", ...},   ← aliases for position-bias mitigation
    #   "responses": {"A": "text", ...},       ← raw text, kept for evidence (never rewritten)
    #   "responses_for_judging": {"A": "text", ...},  ← same text with self-identification
    #                                                    scrubbed; this is what a judge sees
    # }]


# ── Self-identification scrubbing (best effort) ────────────────────────────────────────
#
# Alias-based blind evaluation hides which model produced a response, but a
# response that names its own vendor ("As an AI developed by Anthropic...")
# defeats that blindness in front of a judge that happens to be from the same
# vendor. This targets the literal self-referential phrasing observed in real
# runs; it is NOT a guarantee of blindness — a paraphrased or indirect
# disclosure is not caught. See docs/quality-methodology.md "Judge blindness
# and self-preference bias".
_VENDOR_MODEL_NAMES = (
    "anthropic",
    "claude",
    "openai",
    "chatgpt",
    "gpt-4o",
    "gpt-4",
    "gpt-3.5",
    "gpt-5",
    "google",
    "gemini",
    "gemma",
    "meta ai",
    "llama",
    "cohere",
    "nvidia",
    "nemotron",
    "mistral",
    "qwen",
    "deepseek",
    "grok",
    "xai",
)
_SELF_REFERENCE_CUE = (
    r"(?:i(?:'m|\s+am)"  # I'm / I am
    r"|as(?:\s+an?)?"  # as / as a / as an
    r"|my name is"
    r"|i was (?:developed|created|built|trained|made)"
    r"|(?:developed|created|built|trained|made)\s+by"  # "made by X" (an appositive, not just after "I'm")
    r")"
)
_SELF_IDENTIFICATION_RE = re.compile(
    rf"(?P<cue>\b{_SELF_REFERENCE_CUE}\b[^.!?\n]{{0,40}}?)\b(?P<vendor>"
    + "|".join(re.escape(name) for name in _VENDOR_MODEL_NAMES)
    + r")\b",
    re.IGNORECASE,
)


def _scrub_self_identification(text: str) -> str:
    """Best-effort redaction of a self-disclosed vendor/model name for judges.

    Only used for the judge-facing copy of a response; the raw text kept for
    evidence is never modified by this function.
    """
    return _SELF_IDENTIFICATION_RE.sub(lambda m: f"{m.group('cue')}[assistant]", text)


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
    - Score based ONLY on the supplied evaluation criteria, accuracy,
        instruction-following, and absence of errors.
    - Use the reference answer as a grading aid, not as wording that must be
        copied verbatim unless a criterion explicitly requires exact wording.

Rationale requirement:
    - Provide a concise, evidence-based rationale for each score.
    - Reference the relevant criterion or concrete response evidence.

You MUST respond with a valid JSON object matching exactly this schema:
{
  "scores": [
    {
      "model_alias": "<alias letter, e.g. A>",
    "reasoning": "<concise evidence-based rationale>",
      "score": <1-5>
    },
    ...
  ]
}
The "model_alias" field must be EXACTLY the single letter shown in [MODEL X] \
headers (e.g. "A", "B", "C").
Do not include any text outside the JSON object."""

_USER_TEMPLATE = """\
## Prompt given to models
{prompt}

## Evaluation context
{evaluation_context}

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
        judge_criteria: list[str] | None = None,
        reference_answer: str | None = None,
    ) -> dict[str, JudgeResult]:
        """Score each model response using blind aliases and explicit criteria."""
        if not responses:
            return {}

        alias_map = _blind_alias_map(
            responses.keys(),
            seed_material=f"sync|{prompt}|{'|'.join(sorted(responses))}",
        )
        model_ids = list(alias_map.values())
        reverse_map: dict[str, str] = {v: k for k, v in alias_map.items()}

        responses_block = "\n\n".join(
            f"[MODEL {reverse_map[model_id]}]\n{responses[model_id]}" for model_id in model_ids
        )
        user_message = _USER_TEMPLATE.format(
            prompt=prompt,
            evaluation_context=_format_judge_context(judge_criteria, reference_answer),
            responses_block=responses_block,
        )

        completion = self._client.chat_completion(
            model=self._judge_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            usage_context="quality_judge",
            temperature=0,
        )

        raw_content = (completion.choices[0].message.content or "").strip()
        judge_output = _parse_judge_output(raw_content)

        results: dict[str, JudgeResult] = {}
        for model_score in judge_output.scores:
            model_id = alias_map.get(model_score.model_alias)
            if model_id is None:
                logger.warning(
                    "Judge returned unknown alias '%s'; skipping.",
                    model_score.model_alias,
                )
                continue
            results[model_id] = JudgeResult(
                model=model_id,
                score=model_score.score,
                reasoning=model_score.reasoning,
            )

        return results

    def run_dataset(self, prompts_path: Path) -> pd.DataFrame:
        """Evaluate all prompts in a fixture file (responses must be pre-filled)."""
        dataset = load_quality_prompts(prompts_path)

        rows: list[dict[str, object]] = []
        for idx, entry in enumerate(dataset):
            prompt = entry.display_prompt
            responses = entry.responses
            if not responses:
                continue
            logger.info("Evaluating prompt %d/%d …", idx + 1, len(dataset))
            for model_id, result in self.evaluate(
                prompt=prompt,
                responses=responses,
                judge_criteria=entry.judge_criteria,
                reference_answer=entry.reference_answer,
            ).items():
                rows.append(
                    {
                        "prompt_id": idx,
                        "prompt_preview": prompt[:80],
                        "model": model_id,
                        "score": result.score,
                        "reasoning": result.reasoning,
                        "category": entry.category,
                        "quality_dimension": entry.quality_dimension,
                        "weight": entry.weight,
                        "attempt": 0,
                        "source": "sync-judge",
                    }
                )

        df = pd.DataFrame(rows)
        return (
            df.sort_values(["prompt_id", "attempt", "score"], ascending=[True, True, False]).reset_index(drop=True)
            if not df.empty
            else df
        )

    @staticmethod
    def _parse_judge_output(raw: str) -> JudgeOutput:
        return _parse_judge_output(raw)


# ── Asynchronous judge (V2) ────────────────────────────────────────────────────


class AsyncQualityJudge:
    """Async quality evaluator with deterministic pre-evaluation.

    Evaluation flow per prompt:
    1. Collect responses from target models at runtime.
    2. Run deterministic checks (JSON validity, Python syntax, …) on each response.
    3. Responses with a definitive score → recorded directly.
    4. Undecidable responses → saved as pending for a Copilot judge agent (Phase 2).
    """

    def __init__(self, client: AsyncOpenRouterClient) -> None:
        self._client = client

    # ── Public API ─────────────────────────────────────────────────────────────

    async def evaluate(
        self,
        prompt: str,
        responses: dict[str, str],
        category: str | None = None,
        evaluation: dict[str, object] | None = None,
    ) -> dict[str, JudgeResult]:
        """Score each model's response using deterministic checks only.

        Undecidable responses (logical reasoning, free-form instruction
        following) are omitted — they are scored by a Copilot judge agent
        in Phase 2 via ``run_collect`` + ``make merge``.
        """
        if not responses:
            return {}

        results: dict[str, JudgeResult] = {}

        # Deterministic pre-evaluation only.
        if category:
            check = CHECKS.get(category)
            if check is not None:
                for model_id, response in responses.items():
                    cr = check.run(prompt, response, evaluation)
                    if cr.score is not None:
                        results[model_id] = JudgeResult(
                            model=model_id,
                            score=cr.score,
                            reasoning=cr.reason,
                        )
        # Undecidable responses are not scored here — use a Copilot judge agent.
        return results

    async def run_dataset(
        self,
        prompts_path: Path,
        models: list[str],
        repetitions: int = 1,
    ) -> pd.DataFrame:
        """Run deterministic evaluation and return scores as a DataFrame.

        Undecidable responses are not included. Use ``run_collect`` +
        a Copilot judge agent (Phase 2) + ``make merge`` for complete results.
        """
        result = await self.run_collect(prompts_path, models, repetitions=repetitions)
        df = pd.DataFrame(result.deterministic_rows)
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
        repetitions: int = 1,
    ) -> CollectResult:
        """Collect model responses + run deterministic checks.  No LLM calls.

        Returns a :class:`CollectResult` separating deterministic scores,
        blind-judge work, and transport failures. A response failure is never
        silently misclassified as a model-quality failure.

        Aliased responses in ``pending_judgments`` preserve position-bias
        mitigation: the ``alias_map`` is needed by :class:`MergePipeline` to
        remap Copilot's scores back to model IDs.
        """
        if repetitions < 1:
            raise ValueError("repetitions must be greater than or equal to 1.")

        dataset = load_quality_prompts(prompts_path)

        deterministic_rows: list[dict[str, object]] = []
        pending_judgments: list[dict[str, object]] = []
        collection_errors: list[dict[str, object]] = []

        async def _process(idx: int, entry: QualityPrompt) -> None:
            prompt = entry.display_prompt
            logger.info("Collecting responses for prompt %d/%d …", idx + 1, len(dataset))
            collected = await self._collect_responses(entry.request_messages, models, repetitions)

            check = CHECKS.get(entry.category) if entry.messages is None else None
            undecidable_by_attempt: dict[int, dict[str, str]] = {}

            for item in collected:
                row_metadata = {
                    "prompt_id": idx,
                    "attempt": item.attempt,
                    "prompt": prompt,
                    "prompt_preview": prompt[:80],
                    "model": item.model,
                    "response": item.content,
                    "category": entry.category,
                    "quality_dimension": entry.quality_dimension,
                    "weight": entry.weight,
                    "generation_id": item.generation_id,
                    "resolved_model": item.resolved_model,
                    "request_sha256": item.request_sha256,
                    "expected_answers_json": json.dumps(entry.accepted_answers, ensure_ascii=False),
                }
                if item.error is not None:
                    collection_errors.append({**row_metadata, "error": item.error})
                    continue

                if not item.content.strip():
                    deterministic_rows.append(
                        {
                            **row_metadata,
                            "score": 1,
                            "reasoning": "Model returned an empty response.",
                            "source": "deterministic-empty-response",
                        }
                    )
                    continue

                if check is not None:
                    check_result = check.run(prompt, item.content, entry.evaluation_context)
                    if check_result.format_score is not None:
                        deterministic_rows.append(
                            {
                                **row_metadata,
                                "quality_dimension": FORMAT_COMPLIANCE_DIMENSION,
                                "score": check_result.format_score,
                                "reasoning": check_result.format_reason,
                                "source": "deterministic-format",
                                "verification_status": "not_required",
                            }
                        )
                    if check_result.score is not None:
                        deterministic_rows.append(
                            {
                                **row_metadata,
                                "score": check_result.score,
                                "reasoning": check_result.reason,
                                "source": "deterministic",
                                "verification_status": (
                                    "optional_openrouter_recheck"
                                    if entry.category in _EXACT_ANSWER_CATEGORIES
                                    and check_result.score < 5
                                    and repetitions == 1
                                    else (
                                        "run_repetitions_available"
                                        if entry.category in _EXACT_ANSWER_CATEGORIES and check_result.score < 5
                                        else "not_required"
                                    )
                                ),
                            }
                        )
                        continue

                undecidable_by_attempt.setdefault(item.attempt, {})[item.model] = item.content

            for attempt, undecidable in undecidable_by_attempt.items():
                alias_map = _blind_alias_map(
                    undecidable.keys(),
                    seed_material=f"{QUALITY_SUITE_VERSION}|{idx}|{attempt}|{prompt}",
                )
                pending_judgments.append(
                    {
                        "prompt_id": idx,
                        "attempt": attempt,
                        "prompt": prompt,
                        "prompt_preview": prompt[:80],
                        "category": entry.category,
                        "quality_dimension": entry.quality_dimension,
                        "weight": entry.weight,
                        "judge_criteria": entry.judge_criteria,
                        "reference_answer": entry.reference_answer,
                        "alias_map": alias_map,
                        # Raw text — kept for evidence, never rewritten (see AGENTS.md).
                        "responses": {alias: undecidable[mid] for alias, mid in alias_map.items()},
                        # Same text, self-identification scrubbed — this is the copy the
                        # blind judging file exposes to judge agents (see _save_pending).
                        "responses_for_judging": {
                            alias: _scrub_self_identification(undecidable[mid]) for alias, mid in alias_map.items()
                        },
                    }
                )

        await asyncio.gather(*[_process(i, e) for i, e in enumerate(dataset)])

        return CollectResult(
            deterministic_rows=sorted(
                deterministic_rows,
                key=lambda row: (int(str(row["prompt_id"])), int(str(row["attempt"]))),
            ),
            pending_judgments=sorted(
                pending_judgments,
                key=lambda pending: (int(str(pending["prompt_id"])), int(str(pending["attempt"]))),
            ),
            collection_errors=sorted(
                collection_errors,
                key=lambda row: (int(str(row["prompt_id"])), int(str(row["attempt"]))),
            ),
            prompt_count=len(dataset),
            dimension_count=len(
                {entry.quality_dimension for entry in dataset}
                | ({FORMAT_COMPLIANCE_DIMENSION} if any(entry.strict_output for entry in dataset) else set())
            ),
            repetitions=repetitions,
            quality_suite_id=quality_suite_id(prompts_path),
        )

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _collect_responses(
        self,
        messages: list[dict[str, str]],
        models: list[str],
        repetitions: int,
    ) -> list[CollectedResponse]:
        """Send each complete conversation to all models concurrently.

        Failures are represented explicitly to keep transport availability out
        of the model-quality score.
        """

        request_sha256 = _request_sha256(messages)

        async def _get(model: str, attempt: int) -> CollectedResponse:
            try:
                completion = await self._client.chat_completion(
                    model=model,
                    messages=messages,
                    usage_context="quality_screen",
                    temperature=0,
                )
                content = completion.choices[0].message.content if completion.choices else None
                return CollectedResponse(
                    model=model,
                    attempt=attempt,
                    content=content or "",
                    generation_id=completion.id,
                    resolved_model=completion.model,
                    request_sha256=request_sha256,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to get response from '%s' (attempt %d): %s", model, attempt + 1, exc)
                return CollectedResponse(
                    model=model,
                    attempt=attempt,
                    content="",
                    error=str(exc),
                    request_sha256=request_sha256,
                )

        tasks = [_get(model, attempt) for attempt in range(repetitions) for model in models]
        return list(await asyncio.gather(*tasks))


# ── Shared helpers ─────────────────────────────────────────────────────────────


def load_quality_prompts(prompts_path: Path) -> list[QualityPrompt]:
    """Load and validate a generic quality-screen JSON fixture.

    Raises:
        ValueError: If the fixture is missing required fields, has invalid JSON
            or does not contain a non-empty list of prompt objects.
    """
    try:
        raw = json.loads(prompts_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Quality prompts file does not exist: '{prompts_path}'.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Quality prompts file contains invalid JSON: {exc}") from exc

    if not isinstance(raw, list) or not raw:
        raise ValueError(f"Quality prompts file '{prompts_path}' must contain a non-empty JSON list.")

    prompts: list[QualityPrompt] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Quality prompt #{index} must be a JSON object.")
        try:
            prompts.append(QualityPrompt.model_validate(item))
        except ValueError as exc:
            raise ValueError(f"Quality prompt #{index} is invalid: {exc}") from exc
    return prompts


def quality_suite_id(prompts_path: Path) -> str:
    """Return a content-addressed ID that ties results to an exact prompt suite."""
    digest = hashlib.sha256(prompts_path.read_bytes()).hexdigest()[:12]
    return f"{QUALITY_SUITE_VERSION}-{digest}"


def _format_judge_context(judge_criteria: list[str] | None, reference_answer: str | None) -> str:
    """Format stable, model-blind instructions for an external judge."""
    criteria = judge_criteria or []
    criteria_text = "\n".join(f"- {criterion}" for criterion in criteria) or "- Apply the default scoring rubric."
    reference_text = reference_answer or "No reference answer is supplied."
    return f"Criteria:\n{criteria_text}\n\nReference answer:\n{reference_text}"


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


def _blind_alias_map(model_ids: Iterable[str], *, seed_material: str) -> dict[str, str]:
    """Return a reproducibly shuffled alias map without preserving input order."""
    ordered_ids = sorted(str(model_id) for model_id in model_ids)
    seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
    random.Random(seed).shuffle(ordered_ids)
    return {_alias(index): model_id for index, model_id in enumerate(ordered_ids)}
