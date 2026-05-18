# Deep Research

Parallel multi-agent deep research with Claude. Decomposes a topic into five orthogonal sub-topics, runs five parallel research agents (server-side web search + web fetch), then produces a consolidated report with a cross-agent contradiction table, confidence matrix, and research gaps list.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env  # then put your key in .env
export $(grep -v '^#' .env | xargs)
```

## Usage

```bash
python -m deep_research "How is AI changing software engineering hiring?"
```

Or with a different model:

```bash
python -m deep_research --model claude-sonnet-4-6 "your topic here"
```

Reports are written to `reports/<timestamp>-<slug>.md` (gitignored).

## Cost

The default model is `claude-opus-4-7`. A single run makes 7+ Opus calls: one coordinator, five parallel agents (each looping over multiple web searches), one synthesizer. Expect roughly **$2–$8 per run** depending on topic depth and how aggressively the agents fan out. Use `--model claude-sonnet-4-6` for a substantially cheaper run.

## Architecture

- **Coordinator** (`decompose`) — uses structured outputs (`output_format=Decomposition`) to split the topic into five orthogonal sub-topics with primary research questions and scopes.
- **Research agents** (`run_research_agent`) — five concurrent `messages.stream()` calls with `web_search_20260209` + `web_fetch_20260209`. Each loop handles `pause_turn` (server-side tool iteration limit) by re-sending without an extra user message, so long search trails resume cleanly.
- **Synthesizer** (`synthesize`) — single call that ingests all five agent reports and produces consolidated findings, a contradiction table, a confidence matrix, and a research-gaps list.
- Parallelism via `asyncio.gather` on the `AsyncAnthropic` client with the `aiohttp` backend.

System prompts live in `deep_research/prompts.py`. Tune them in place.
