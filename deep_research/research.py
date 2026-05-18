import asyncio
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic, DefaultAioHttpClient
from pydantic import BaseModel, Field

from .prompts import COORDINATOR_SYSTEM, RESEARCH_AGENT_SYSTEM, SYNTHESIZER_SYSTEM


DEFAULT_MODEL = "claude-opus-4-7"
REPORTS_DIR = Path("reports")


class SubTopic(BaseModel):
    agent_number: int = Field(ge=1, le=5)
    title: str
    primary_research_question: str
    scope: str


class Decomposition(BaseModel):
    topic_confirmation: str
    sub_topics: list[SubTopic] = Field(min_length=5, max_length=5)


def _format_agent_instruction(sub_topic: SubTopic) -> str:
    return (
        f"AGENT {sub_topic.agent_number} — {sub_topic.title}\n\n"
        f"Primary research question:\n{sub_topic.primary_research_question}\n\n"
        f"Scope:\n{sub_topic.scope}\n\n"
        "Begin research now. Use web_search and web_fetch as needed, then return "
        "your report under the exact section headings specified in your system prompt."
    )


async def decompose(client: AsyncAnthropic, topic: str, model: str) -> Decomposition:
    response = await client.messages.parse(
        model=model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=COORDINATOR_SYSTEM,
        messages=[{"role": "user", "content": f"Research topic:\n\n{topic}"}],
        output_format=Decomposition,
    )
    if response.parsed_output is None:
        raise RuntimeError(
            f"Coordinator failed to produce a valid decomposition "
            f"(stop_reason={response.stop_reason})."
        )
    return response.parsed_output


async def run_research_agent(
    client: AsyncAnthropic, instruction: str, model: str
) -> str:
    messages: list[dict[str, Any]] = [{"role": "user", "content": instruction}]

    while True:
        async with client.messages.stream(
            model=model,
            max_tokens=64000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=RESEARCH_AGENT_SYSTEM,
            tools=[
                {"type": "web_search_20260209", "name": "web_search"},
                {"type": "web_fetch_20260209", "name": "web_fetch"},
            ],
            messages=messages,
        ) as stream:
            response = await stream.get_final_message()

        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        break

    text = "\n".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        text = f"[Agent produced no text output. stop_reason={response.stop_reason}]"
    return text


async def synthesize(
    client: AsyncAnthropic,
    topic: str,
    agent_reports: list[str],
    model: str,
) -> str:
    parts = [f"<topic>\n{topic}\n</topic>"]
    for i, report in enumerate(agent_reports, start=1):
        parts.append(f"<agent_{i}_report>\n{report}\n</agent_{i}_report>")
    user_content = "\n\n".join(parts)

    async with client.messages.stream(
        model=model,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=SYNTHESIZER_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        response = await stream.get_final_message()

    return "\n".join(b.text for b in response.content if b.type == "text").strip()


def _slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:max_len].rstrip("-") or "research"


def _render_report(
    topic: str,
    decomposition: Decomposition,
    agent_reports: list[str],
    synthesis: str,
    model: str,
    generated_at: datetime,
) -> str:
    lines: list[str] = [
        f"# Research report: {topic}",
        "",
        f"- Generated: {generated_at.isoformat(timespec='seconds')}",
        f"- Model: `{model}`",
        f"- Topic confirmation: {decomposition.topic_confirmation}",
        "",
        "## Synthesis",
        "",
        synthesis,
        "",
        "## Sub-topic decomposition",
        "",
    ]
    for st in decomposition.sub_topics:
        lines += [
            f"### Agent {st.agent_number}: {st.title}",
            "",
            f"**Question:** {st.primary_research_question}",
            "",
            f"**Scope:** {st.scope}",
            "",
        ]
    lines += ["## Raw agent reports", ""]
    for st, report in zip(decomposition.sub_topics, agent_reports):
        lines += [
            f"### Agent {st.agent_number}: {st.title}",
            "",
            report,
            "",
        ]
    return "\n".join(lines)


def _write_report(topic: str, body: str, generated_at: datetime) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = generated_at.strftime("%Y%m%d-%H%M%S")
    path = REPORTS_DIR / f"{stamp}-{_slugify(topic)}.md"
    path.write_text(body, encoding="utf-8")
    return path


async def run(topic: str, model: str = DEFAULT_MODEL) -> Path:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")

    generated_at = datetime.now()

    async with AsyncAnthropic(http_client=DefaultAioHttpClient()) as client:
        print(f"[1/3] Decomposing topic with {model}...", file=sys.stderr)
        decomposition = await decompose(client, topic, model)
        print(
            f"      -> {len(decomposition.sub_topics)} sub-topics ready",
            file=sys.stderr,
        )

        print("[2/3] Running 5 research agents in parallel...", file=sys.stderr)
        instructions = [
            _format_agent_instruction(st) for st in decomposition.sub_topics
        ]
        agent_reports = await asyncio.gather(
            *(run_research_agent(client, instr, model) for instr in instructions)
        )
        print("      -> all agent reports received", file=sys.stderr)

        print("[3/3] Synthesizing final report...", file=sys.stderr)
        synthesis = await synthesize(client, topic, agent_reports, model)

    body = _render_report(
        topic=topic,
        decomposition=decomposition,
        agent_reports=agent_reports,
        synthesis=synthesis,
        model=model,
        generated_at=generated_at,
    )
    return _write_report(topic, body, generated_at)
