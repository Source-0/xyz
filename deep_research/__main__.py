import argparse
import asyncio
import sys

from .research import DEFAULT_MODEL, run


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="deep-research",
        description="Parallel multi-agent deep research with Claude.",
    )
    parser.add_argument("topic", help="The research topic.")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Claude model ID (default: {DEFAULT_MODEL}).",
    )
    args = parser.parse_args()

    try:
        path = asyncio.run(run(topic=args.topic, model=args.model))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Report written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
