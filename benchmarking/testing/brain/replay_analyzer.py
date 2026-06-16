"""
Offline SSE Replay Analyzer
Parse and analyze saved SSE response files (like response_sse_example)
without hitting the live endpoint. Useful for debugging and validating
the parser before a live benchmark run.

Usage:
    python replay_analyzer.py <path_to_sse_file> [question_text]
"""

import json
import sys
from collections import defaultdict


def parse_sse_file(filepath: str):
    """Parse a raw SSE file and return structured event list."""
    events = []
    current_event = None
    current_data = None

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")

            if line.startswith("event:"):
                current_event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                current_data = line[len("data:") :].strip()
            elif line == "":
                if current_event and current_data:
                    try:
                        parsed = json.loads(current_data)
                    except json.JSONDecodeError:
                        parsed = {"_raw": current_data}
                    events.append((current_event, parsed))
                current_event = None
                current_data = None

    return events


def analyze_events(events: list, question: str = "(unknown)"):
    print(f"\n{'=' * 70}")
    print("  OFFLINE SSE ANALYSIS")
    print(f"  Question: {question[:80]}")
    print(f"  Total SSE events: {len(events)}")
    print(f"{'=' * 70}\n")

    # Count by event type
    type_counts = defaultdict(int)
    for etype, _ in events:
        type_counts[etype] += 1

    print("Event Type Distribution:")
    for etype, count in sorted(type_counts.items()):
        print(f"  {etype:<40} {count:>6} events")

    print()

    # ── brain/body analysis ──
    brain_bodies = [(i, d) for i, (e, d) in enumerate(events) if e == "brain/body"]
    print(f"brain/body events ({len(brain_bodies)} total):")
    for pos, d in brain_bodies:
        usage = d.get("metadata", {}).get("usage", {}) or {}
        resp = d.get("response")
        fc = d.get("function_call") or {}
        tools = [ti.get("name") for ti in fc.get("tool_invoke_args", [])]
        print(
            f"  [event #{pos}]  tools={tools}  "
            f"completion_tokens={usage.get('completion_tokens', '?')}  "
            f"response={'<present>' if resp else 'null'}  "
            f"resp_len={len(resp) if resp else 0}"
        )

    print()

    # ── Function call trace ──
    print("Agentic Step Trace:")
    step_count = 0
    seen_steps = set()
    for etype, data in events:
        # Brain dispatches a tool
        if etype == "brain/body":
            fc = data.get("function_call") or {}
            for ti in fc.get("tool_invoke_args", []):
                name = ti.get("name", "?")
                key = f"brain:{name}"
                if key not in seen_steps:
                    step_count += 1
                    print(f"  {step_count:>3}. [brain] → {name}")
                    seen_steps.add(key)

        # Sub-agent tool calls
        elif "/" in etype and etype not in ("brain/text",):
            parts = etype.split("/")
            sub_agent = parts[1] if len(parts) > 1 else "?"
            content = data.get("content", {})
            if isinstance(content, dict):
                for part in content.get("parts", []):
                    if "function_call" in part:
                        tool_name = part["function_call"].get("name", "?")
                        key = f"{sub_agent}:{tool_name}"
                        if key not in seen_steps:
                            step_count += 1
                            print(f"  {step_count:>3}. [{sub_agent}] → {tool_name}")
                            seen_steps.add(key)
                    elif "function_response" in part:
                        tool_name = part["function_response"].get("name", "?")
                        key = f"{sub_agent}:result:{tool_name}"
                        if key not in seen_steps:
                            step_count += 1
                            print(
                                f"  {step_count:>3}. [{sub_agent}] ← result from {tool_name}"
                            )
                            seen_steps.add(key)

    print()

    # ── Brain text token stats ──
    brain_texts = [(e, d) for e, d in events if e == "brain/text"]
    total_brain_text = "".join(
        part.get("text", "")
        for _, d in brain_texts
        for part in d.get("content", {}).get("parts", [])
    )
    print("Brain text tokens (stream):")
    print(f"  Events: {len(brain_texts)}")
    print(f"  Total chars assembled: {len(total_brain_text)}")

    print()

    # ── Final response ──
    final_resp = next(
        (d.get("response") for _, d in reversed(brain_bodies) if d.get("response")),
        None,
    )
    if final_resp:
        print("Final Response (from brain/body):")
        print(f"  Length: {len(final_resp)} chars")
        print(f"  Preview: {final_resp[:300]}...")
    else:
        print(
            "⚠️  No final brain/body response found — stream may have ended prematurely."
        )
        if total_brain_text:
            print(f"  Partial brain/text assembled ({len(total_brain_text)} chars):")
            print(f"  {total_brain_text[:200]}...")

    print()

    # ── Token summary ──
    final_body = next((d for _, d in reversed(brain_bodies) if d.get("response")), None)
    if final_body:
        usage = final_body.get("metadata", {}).get("usage", {}) or {}
        print("Token Usage (final brain/body):")
        print(f"  Prompt tokens:     {usage.get('prompt_tokens', '?')}")
        print(f"  Completion tokens: {usage.get('completion_tokens', '?')}")
        print(f"  Total tokens:      {usage.get('total_tokens', '?')}")

    # ── Stream health ──
    clean = final_resp is not None
    print(f"\nStream Health: {'✅ CLEAN' if clean else '❌ PREMATURE BREAK'}")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python replay_analyzer.py <sse_file> [question]")
        sys.exit(1)

    filepath = sys.argv[1]
    question = sys.argv[2] if len(sys.argv) > 2 else "(not provided)"

    events = parse_sse_file(filepath)
    analyze_events(events, question)
