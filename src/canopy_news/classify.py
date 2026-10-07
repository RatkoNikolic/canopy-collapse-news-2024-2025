"""Relevance stage 3: the codebook classifier (PROTOCOL.md §5.4).

The prompt is the frozen codebook (CODEBOOK.md) as the system message
and the article as the coders see it on the labelling page: title, date, lead and
numbered body paragraphs, never the outlet or the URL. The answer is the codebook's
output object, enforced by a JSON schema. Arms are named model settings so a run
manifest records the exact model id and thinking setting of every decision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from canopy_news.labels import CODEBOOK, codebook_sha256

INSTRUCTION = (
    "You classify Serbian news articles for a research corpus. Apply the codebook below "
    "exactly as written: it is the same text human coders use. The article follows in "
    "the user message (title, date, lead, numbered body paragraphs). Answer only with "
    "the codebook's output object; `evidence` is a paragraph number such as \"p3\", or "
    "\"headline\".\n\n"
)

SCHEMA = {
    "type": "object",
    "properties": {
        "in_scope": {"type": "boolean"},
        "clauses": {"type": "array", "items": {"type": "integer", "enum": [1, 2, 3, 4]}},
        "evidence": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["in_scope", "clauses", "evidence", "confidence"],
    "additionalProperties": False,
}

# $/1M tokens, standard (batch = half): input, output (Anthropic table 2026-09-25)
PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-5-5": (2.0, 10.0)}
CACHE_READ, CACHE_WRITE = 0.10, 1.25


@dataclass(frozen=True)
class Arm:
    name: str
    model: str
    params: dict = field(default_factory=dict)


ARMS = {
    "haiku": Arm("haiku", "claude-haiku-4-5", {"temperature": 0}),
    # Sonnet 5.5 rejects non-default sampling parameters; `between_tools` is its no-thinking setting
    "sonnet": Arm("sonnet", "claude-sonnet-5-5", {"thinking": {"type": "between_tools"}}),
    "sonnet-think-low": Arm("sonnet-think-low", "claude-sonnet-5-5",
                            {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}),
}


def system_prompt() -> str:
    return INSTRUCTION + CODEBOOK.read_text(encoding="utf-8")


def article_text(doc: dict) -> str:
    body = doc["body"] or ""
    paras = [body[a:b].strip() for a, b in (doc["para_offsets"] or [[0, len(body)]])]
    lines = [f"Title: {doc['title'] or ''}", f"Date: {doc['day']}", f"Lead: {doc['lead'] or ''}", ""]
    lines += [f"[p{i}] {p}" for i, p in enumerate((p for p in paras if p), 1)]
    return "\n".join(lines)


def request(arm: Arm, doc: dict) -> dict:
    """Messages API parameters for one article (also the `params` of a batch request)."""
    output_config = {"format": {"type": "json_schema", "schema": SCHEMA},
                     **arm.params.get("output_config", {})}
    extra = {k: v for k, v in arm.params.items() if k != "output_config"}
    return {"model": arm.model, "max_tokens": 4000,
            "system": [{"type": "text", "text": system_prompt(),
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": article_text(doc)}],
            "output_config": output_config, **extra}


def parse(message) -> dict:
    text = next(b.text for b in message.content if b.type == "text")
    return json.loads(text)


def cost(model: str, usage) -> float:
    pin, pout = PRICES[model]
    return (usage.input_tokens * pin
            + (usage.cache_read_input_tokens or 0) * pin * CACHE_READ
            + (usage.cache_creation_input_tokens or 0) * pin * CACHE_WRITE
            + usage.output_tokens * pout) / 1e6


def manifest(arms: list[Arm]) -> dict:
    return {"codebook_sha256": codebook_sha256(), "schema": SCHEMA,
            "arms": {a.name: {"model": a.model, **a.params} for a in arms}}
