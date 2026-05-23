"""NNDSS Australian Disease Surveillance data agent.

Extends BaseAgent with two post-processing layers:

1. A tool-call insistor that retries when the model produces an answer
   without calling any tools (query_notifications, describe_datasets,
   get_methodology). The system prompt requires grounding in NNDSS data.

2. A reasoning rubric injector that makes a second structured-output call
   to produce the 6-step reasoning block after the tool-calling loop.

The confidence card is built programmatically from the tool trace.
"""

from __future__ import annotations

import logging
import os
from typing import Any, AsyncIterator

try:
    import mlflow
    _HAS_MLFLOW = bool(os.environ.get("MLFLOW_TRACKING_URI", "").strip())
except ImportError:
    _HAS_MLFLOW = False

from pydantic import BaseModel, Field

from fipsagents.baseagent import BaseAgent, StepResult
from fipsagents.baseagent.events import (
    ContentDelta,
    StreamComplete,
    StreamEvent,
    ToolResultEvent,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured reasoning rubric
# ---------------------------------------------------------------------------

class ReasoningRubric(BaseModel):
    """The 6-consideration reasoning rubric.

    Each field is a brief sentence or two. ``cross_dataset`` is never
    "N/A" per the protocol rules; the others may be "N/A" when the
    consideration doesn't apply to the user's question.
    """

    cross_dataset: str = Field(
        ...,
        description=(
            "Which dataset(s) you used and why, including which alternatives "
            "were considered and rejected. NEVER 'N/A'."
        ),
    )
    methodology: str = Field(
        ...,
        description=(
            "What methodology you retrieved and how it informed your answer, "
            "or 'N/A' if not applicable."
        ),
    )
    scope: str = Field(
        ...,
        description=(
            "Whether the question is within the data's scope, "
            "or 'N/A' if not applicable."
        ),
    )
    causal_inference: str = Field(
        ...,
        description=(
            "Whether causal claims are appropriate given the data, "
            "or 'N/A' if the question doesn't imply causation."
        ),
    )
    geographic: str = Field(
        ...,
        description=(
            "Geographic resolution analysis (level, why, alternatives), "
            "or 'N/A' if the question isn't geographic."
        ),
    )
    terminology: str = Field(
        ...,
        description=(
            "Any term mapping needed between the user's wording and the "
            "indicator name, or 'N/A' if no mapping was needed."
        ),
    )


_RUBRIC_REQUEST = (
    "Now produce ONLY the structured reasoning rubric for the answer you just "
    "gave above, as JSON matching the provided schema. Each value should be a "
    "brief sentence or two -- not a paragraph. Use 'N/A' for considerations "
    "that don't apply, EXCEPT cross_dataset which is never 'N/A' (every data "
    "query involves a dataset choice, even when obvious)."
)


def _format_rubric_block(rubric: ReasoningRubric) -> str:
    """Render the rubric as the ``<reasoning>...</reasoning>`` block.

    The chat UI can parse these tags into labeled cards.
    """
    return (
        "<reasoning>\n"
        f"cross_dataset: {rubric.cross_dataset}\n"
        f"methodology: {rubric.methodology}\n"
        f"scope: {rubric.scope}\n"
        f"causal_inference: {rubric.causal_inference}\n"
        f"geographic: {rubric.geographic}\n"
        f"terminology: {rubric.terminology}\n"
        "</reasoning>"
    )


# ---------------------------------------------------------------------------
# Programmatic confidence card
# ---------------------------------------------------------------------------

def _build_confidence_card(
    used_tools: bool,
    tool_results: list[str],
    rubric: ReasoningRubric | None = None,
) -> str:
    """Compute a Data Confidence + Data Freshness card from the tool trace.

    Deterministic -- no LLM call. The confidence level is based on what
    actually happened during the turn, not the model's self-assessment.
    If a rubric is provided, scope assessment can downgrade confidence
    when the question is out of scope for the available data.
    """
    import json as _json
    from datetime import datetime, timezone

    level = "LOW"
    basis = "No tools were called; the answer may not be grounded in data."
    source_name = ""
    source_url = ""
    data_year = ""
    dataset_updated = ""

    if used_tools and tool_results:
        has_data = False
        has_methodology = False

        for result_text in tool_results:
            try:
                result = _json.loads(result_text)
            except (ValueError, TypeError):
                continue

            results_list = result.get("results") or result.get("availability")
            if results_list:
                has_data = True

            if result.get("methodology") or result.get("methodology_structured"):
                has_methodology = True

            freshness = result.get("data_freshness", {})
            if freshness:
                source_name = freshness.get("dataset_name", source_name)
                source_url = freshness.get("dataset_url", source_url)
                dataset_updated = freshness.get("dataset_updated", dataset_updated)

            citation = result.get("citation", {})
            if citation and not source_name:
                source_name = citation.get("source", "")

            if isinstance(results_list, list):
                for row in results_list:
                    if isinstance(row, dict) and row.get("year"):
                        data_year = str(row["year"])
                        break

        if has_data and has_methodology:
            level = "HIGH"
            basis = (
                "Retrieved data with methodology context. Scope and "
                "geographic resolution verified via tool response metadata."
            )
        elif has_data:
            level = "MODERATE"
            basis = (
                "Retrieved data but methodology context was partial or "
                "not explicitly retrieved. The answer is data-grounded "
                "but interpretation gaps may exist."
            )
        else:
            level = "LOW"
            basis = (
                "Tools were called but did not return the requested data. "
                "The answer may rely on partial information."
            )

    # Scope override: if the rubric's scope field signals the question
    # is outside what the data can support, downgrade to LOW regardless
    # of whether tools returned data.
    rubric_text_to_check = ""
    if rubric:
        for field in [rubric.scope, rubric.causal_inference]:
            if field and field.strip().upper() != "N/A":
                rubric_text_to_check += " " + field
    if rubric_text_to_check:
        scope_lower = rubric_text_to_check.lower()
        out_of_scope_signals = [
            "out of scope", "outside the scope", "outside scope",
            "beyond the scope", "not within scope",
            "cannot support", "cannot answer", "cannot be answered",
            "does not cover", "not supported", "not designed to answer",
            "cannot determine", "cannot measure",
            "do not establish causal", "does not establish causal",
            "cannot establish causal", "causal relationship",
            "causal claim", "not establish causal",
            "long-term effect", "long-term health",
            "individual risk", "treatment outcome",
        ]
        if any(signal in scope_lower for signal in out_of_scope_signals):
            level = "LOW"
            basis = (
                "The question asks about something the available data "
                "cannot support (e.g., causal claims, predictions, "
                "health effects). Data was retrieved but does not answer "
                "the user's actual question."
            )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        "---",
        "**Data Confidence: %s**" % level,
        basis,
    ]
    if source_name:
        if source_url:
            lines.append(
                "\n**Data Freshness**\n"
                "**Source:** [%s](%s)" % (source_name, source_url)
            )
        else:
            lines.append("\n**Data Freshness**\n**Source:** %s" % source_name)
        year_part = "**Data Year:** %s" % data_year if data_year else ""
        updated_part = (
            "**Updated:** %s" % dataset_updated if dataset_updated else ""
        )
        retrieved_part = "**Retrieved:** %s" % now
        parts = [p for p in [year_part, updated_part, retrieved_part] if p]
        if parts:
            lines.append(" | ".join(parts))
    lines.append("---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class NNDSSDataAgent(BaseAgent):
    """Australian disease surveillance agent with structured reasoning.

    Uses Qwen's enable_thinking toggle: disabled during tool-calling
    rounds (fast SQL generation), enabled for final answer formulation.
    """

    _thinking_enabled: bool = False

    async def setup(self) -> None:
        await super().setup()

    async def call_model(self, **kwargs: Any):
        """Override to inject enable_thinking via chat_template_kwargs."""
        extra_body = kwargs.pop("extra_body", {}) or {}
        extra_body.setdefault("chat_template_kwargs", {})
        extra_body["chat_template_kwargs"]["enable_thinking"] = self._thinking_enabled
        return await super().call_model(extra_body=extra_body, **kwargs)

    async def step(self) -> StepResult:
        """Non-streaming entry point with MLflow parent trace."""
        if _HAS_MLFLOW:
            # Create parent trace — autolog LLM calls will nest under it
            with mlflow.start_span(name="nndss_agent_request") as span:
                _question = ""
                for m in reversed(self.messages):
                    if m.get("role") == "user":
                        _question = m.get("content", "")
                        break
                span.set_inputs({"question": _question[:500]})

                # Load prompt inside trace for auto-linking
                try:
                    mlflow.genai.load_prompt(
                        "prompts:/nndss-agent.system@production",
                        allow_missing=True,
                        cache_ttl_seconds=60,
                    )
                except Exception:
                    pass

                result = await self._step_impl()
                span.set_outputs({"answer_length": len(result.result or "")})
                return result
        return await self._step_impl()

    async def _step_impl(self) -> StepResult:
        """Full pipeline with two-phase tool calling."""
        _question = ""
        for m in reversed(self.messages):
            if m.get("role") == "user":
                _question = m.get("content", "")
                break

        # Phase 1: Tool calling with thinking disabled
        self._thinking_enabled = False
        logger.info("Tool-calling phase: thinking disabled")
        response = await self.call_model()
        used_tools = bool(response.tool_calls)

        if response.tool_calls:
            response = await self.run_tool_calls(response)

        if not used_tools:
            # Insist once
            self.messages.append({"role": "user", "content": self._TOOL_INSIST_MSG})
            response = await self.call_model()
            if response.tool_calls:
                response = await self.run_tool_calls(response)
                used_tools = True

        answer = response.content or ""

        if used_tools:
            # Phase 2: Final answer with thinking enabled
            logger.info("Final answer phase: thinking enabled")
            self._thinking_enabled = True
            self.messages.append({"role": "user", "content": (
                "Now provide a well-structured answer to the "
                "original question based on the data retrieved "
                "above. Include your reasoning."
            )})
            response = await self.call_model()
            answer = response.content or ""

            # Rubric injection
            rubric = await self._build_rubric()
            if rubric and "<reasoning>" not in answer:
                answer = _format_rubric_block(rubric) + "\n\n" + answer

        # Confidence card
        if "Data Confidence" not in answer:
            card = _build_confidence_card(used_tools, [], rubric if used_tools else None)
            answer = answer + "\n\n" + card

        # MLflow trace with prompt link
        self._log_to_mlflow(_question, answer, [], used_tools)

        return StepResult.done(answer)

    _TOOL_INSIST_MSG = (
        "Your answer did not include any tool calls. The system prompt "
        "requires you to call at least one tool (query_trino, "
        "describe_datasets, or get_methodology) to "
        "retrieve real NNDSS data before answering. For questions spanning "
        "multiple diseases or states, prefer query_trino with SQL. "
        "Please call the appropriate tool now -- do not answer from memory."
    )

    async def astep_stream(self, **kwargs: Any) -> AsyncIterator[StreamEvent]:
        """Streaming entry point with two post-processing layers.

        1. Tool-calling phase: enable_thinking=False for fast SQL generation
        2. Final answer phase: enable_thinking=True for reasoned responses
        3. Tool-call insistor: retries once if model skips tools
        4. Reasoning rubric injection + deterministic confidence card
        """
        max_insist_retries = 1
        _question = ""
        for m in reversed(self.messages):
            if m.get("role") == "user":
                _question = m.get("content", "")
                break

        # Start a parent MLflow span so autolog LLM calls nest under it
        _parent_span = None
        if _HAS_MLFLOW:
            try:
                _parent_span = mlflow.start_span(name="agent_request")
                _parent_span.set_inputs({"question": _question[:500]})
            except Exception:
                _parent_span = None

        # Phase 1: Tool calling with thinking disabled (fast)
        self._thinking_enabled = False
        logger.info("Tool-calling phase: thinking disabled")

        for attempt in range(1 + max_insist_retries):
            content_buffer: list[str] = []
            used_tools = False
            tool_results: list[str] = []

            async for event in super().astep_stream(**kwargs):
                if isinstance(event, ContentDelta):
                    content_buffer.append(event.content)
                    continue
                if isinstance(event, ToolResultEvent):
                    used_tools = True
                    tool_results.append(event.content or "")
                    yield event
                    continue
                if isinstance(event, StreamComplete):
                    if not used_tools and attempt < max_insist_retries:
                        logger.warning(
                            "Model produced an answer without tool "
                            "calls (attempt %d); insisting.",
                            attempt + 1,
                        )
                        self.messages.append(
                            {"role": "user", "content": self._TOOL_INSIST_MSG}
                        )
                        break  # re-enter outer for-loop

                    if used_tools:
                        # Phase 2: Final answer with thinking enabled.
                        # Discard the no-think content (likely terse),
                        # re-call the model with thinking enabled for
                        # a well-reasoned final response.
                        logger.info("Final answer phase: thinking enabled")
                        self._thinking_enabled = True
                        self.messages.append(
                            {"role": "user", "content": (
                                "Now provide a well-structured answer to the "
                                "original question based on the data retrieved "
                                "above. Include your reasoning."
                            )}
                        )
                        final_buffer: list[str] = []
                        async for final_event in super().astep_stream(**kwargs):
                            if isinstance(final_event, ContentDelta):
                                final_buffer.append(final_event.content)
                                yield final_event
                                continue
                            if isinstance(final_event, ToolResultEvent):
                                tool_results.append(final_event.content or "")
                                yield final_event
                                continue
                            if isinstance(final_event, StreamComplete):
                                full = "".join(final_buffer)
                                rubric = None
                                if full.strip() and "<reasoning>" not in full:
                                    self._thinking_enabled = False
                                    rubric = await self._build_rubric()
                                    if rubric:
                                        yield ContentDelta(
                                            content=_format_rubric_block(rubric) + "\n\n"
                                        )
                                if "Data Confidence" not in full:
                                    card = _build_confidence_card(
                                        True, tool_results, rubric
                                    )
                                    yield ContentDelta(content="\n\n" + card)
                                yield final_event
                                if _parent_span:
                                    try:
                                        _parent_span.set_outputs({"answer_length": len(full), "tool_calls": len(tool_results)})
                                        _parent_span.end()
                                    except Exception:
                                        pass
                                self._log_to_mlflow(_question, full, tool_results, True)
                                return
                            yield final_event
                        if _parent_span:
                            try:
                                _parent_span.end()
                            except Exception:
                                pass
                        self._log_to_mlflow(_question, "", tool_results, True)
                        return
                    else:
                        # No tools used even after retries
                        full = "".join(content_buffer)
                        if content_buffer:
                            yield ContentDelta(content=full)
                        if "Data Confidence" not in full:
                            card = _build_confidence_card(False, [], None)
                            yield ContentDelta(content="\n\n" + card)
                        yield event
                        if _parent_span:
                            try:
                                _parent_span.set_outputs({"answer_length": len(full), "used_tools": False})
                                _parent_span.end()
                            except Exception:
                                pass
                        self._log_to_mlflow(_question, full, [], False)
                        return
                yield event

    def _log_to_mlflow(
        self,
        question: str,
        answer: str,
        tool_results: list[str],
        used_tools: bool,
    ) -> None:
        """Log a trace to MLflow with prompt linkage."""
        if not _HAS_MLFLOW:
            return
        try:
            @mlflow.trace(name="nndss_agent_query")
            def _traced(q, a):
                # Load prompt inside trace — auto-links to this trace
                mlflow.genai.load_prompt(
                    "prompts:/nndss-agent.system@production",
                    allow_missing=True,
                    cache_ttl_seconds=60,
                )
                return a[:2000]

            _traced(question[:500], answer)
            logger.info("MLflow trace logged with prompt link")
        except Exception as exc:
            logger.warning("MLflow trace failed: %s", exc)

    async def _build_rubric(self) -> ReasoningRubric | None:
        """Run a structured-output call for the rubric (thinking disabled)."""
        self._thinking_enabled = False
        try:
            rubric = await self.call_model_json(
                ReasoningRubric,
                messages=self.messages
                + [{"role": "user", "content": _RUBRIC_REQUEST}],
            )
        except Exception as exc:
            logger.warning(
                "Rubric call failed (%s: %s); returning unstructured answer.",
                type(exc).__name__,
                exc,
            )
            return None
        logger.info("Rubric call succeeded.")
        return rubric



if __name__ == "__main__":
    from fipsagents.baseagent import load_config
    from fipsagents.server import OpenAIChatServer

    from src.mlflow_init import init_mlflow
    init_mlflow()

    config = load_config("agent.yaml")
    server = OpenAIChatServer(
        agent_class=NNDSSDataAgent,
        config_path="agent.yaml",
        title=config.agent.name,
        version=config.agent.version,
    )
    server.run(host=config.server.host, port=config.server.port)
