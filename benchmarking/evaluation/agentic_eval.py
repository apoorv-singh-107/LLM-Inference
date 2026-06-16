"""
Agentic Correctness Evaluation Module
======================================
Scores each response on whether the model used the correct tool routing:

RULES:
  1. OOKB questions (weather, live prices, future predictions):
       - web_search OR direct refusal = CORRECT
       - Looping through querifai/docufai without escalating = BAD

  2. Financial/KPI questions (structured data):
       - querifai FIRST (via retrieval_augmented_generation → get_tables/execute_mysql_query)
       - If querifai fails → docufai
       - If docufai fails → web_search
       - web_search BEFORE exhausting querifai = VIOLATION

  3. Document/text questions (narrative, policy, names, strategic text):
       - docufai first OR querifai then docufai
       - web_search before both fail = VIOLATION

  4. Multi-Source questions (High/Medium Multi-Source, High/Medium Inferred/MS):
       - MUST use BOTH querifai AND docufai
       - Using only one source = INCOMPLETE

  5. Chart generation:
       - chart_generator called but response is empty/very short: suspicious
       - Chart HTML in response but chart_generator NOT called: inconsistent
       - chart_generator called for simple text-only questions (name/award/CEO): unnecessary

  6. No tool used for non-OOKB questions: MISSING LOOKUP
"""

import pandas as pd


# ─────────────────────────────────────────────
# QUESTION CLASSIFICATION HELPERS
# ─────────────────────────────────────────────

OOKB_COMPLEXITIES = {"High (OOKB)"}

MULTI_SOURCE_COMPLEXITIES = {
    "High (Multi-Source)",
    "High (Inferred/MS)",
    "Medium (Multi-Source)",
    "Medium (Inferred/MS)",
}

# OOKB questions where web_search is the right first step
OOKB_WEB_SEARCH_EXPECTED = [
    "weather",
    "forecast",
    "temperature",
    "stock price",
    "share price",
    "NYSE",
    "today",
    "current price",
]

# Questions where charts are appropriate (data-heavy)
CHART_APPROPRIATE_KEYWORDS = [
    "trend",
    "growth",
    "decline",
    "compare",
    "ratio",
    "margin",
    "revenue",
    "profit",
    "ebitda",
    "performance",
    "over the years",
    "since 2020",
    "between",
    "vs",
    "breakdown",
    "how did",
    "change",
]

# Questions where charts are NOT appropriate
CHART_INAPPROPRIATE_KEYWORDS = [
    "who is",
    "what is the name",
    "where is",
    "which month",
    "what award",
    "does the company",
    "what is the",
    "chairman",
    "ceo",
    "headquartered",
    "ascend",
    "smart factory",
    "sap",
    "linkedin following",
]


def parse_tools(brain_tool_calls_str, sub_agent_tool_calls_str, agentic_steps_str):
    """Parse tool call strings into structured flags."""
    brain = str(brain_tool_calls_str).lower() if pd.notna(brain_tool_calls_str) else ""
    sub = (
        str(sub_agent_tool_calls_str).lower()
        if pd.notna(sub_agent_tool_calls_str)
        else ""
    )
    steps = str(agentic_steps_str).lower() if pd.notna(agentic_steps_str) else ""

    used_rag = "retrieval_augmented_generation" in brain
    used_chart = "chart_generator" in brain
    used_web_search = "web_search" in brain
    used_querifai = "querifai" in sub
    used_docufai = "docufai" in sub
    no_tools = brain.strip() in ["", "nan", "(none)"] and sub.strip() in [
        "",
        "nan",
        "(none)",
    ]

    # Check ordering from the steps trace
    web_search_before_rag = False
    if used_web_search and used_rag:
        web_idx = steps.find("web_search")
        rag_idx = steps.find("retrieval_augmented_generation")
        if web_idx < rag_idx and rag_idx != -1:
            web_search_before_rag = True

    # Count how many times chart_generator is called
    chart_count = brain.count("chart_generator")

    return {
        "used_rag": used_rag,
        "used_chart": used_chart,
        "chart_count": chart_count,
        "used_web_search": used_web_search,
        "used_querifai": used_querifai,
        "used_docufai": used_docufai,
        "no_tools": no_tools,
        "web_search_before_rag": web_search_before_rag,
    }


def is_ookb(complexity):
    return complexity in OOKB_COMPLEXITIES


def is_multi_source(complexity):
    return complexity in MULTI_SOURCE_COMPLEXITIES


def question_needs_chart(question_text):
    q = question_text.lower()
    appropriate = any(kw in q for kw in CHART_APPROPRIATE_KEYWORDS)
    inappropriate = any(kw in q for kw in CHART_INAPPROPRIATE_KEYWORDS)
    return appropriate and not inappropriate


def is_text_only_question(question_text):
    """Questions that are clearly document/text, not KPI/numeric."""
    q = question_text.lower()
    return any(
        kw in q
        for kw in [
            "who is",
            "what is the name",
            "where is",
            "which month",
            "what award",
            "does the company use",
            "ascend",
            "smart factory",
            "sap",
            "linkedin",
            "terracotta",
            "recycled product",
            "headquarters",
            "chairman",
            "ceo",
            "group ceo",
            "kludi",
            "cookingrak",
        ]
    )


# ─────────────────────────────────────────────
# VIOLATION DETECTION
# ─────────────────────────────────────────────


def detect_violations(row, tools):
    """
    Returns a list of (violation_code, description) tuples for this row.
    """
    violations = []
    complexity = str(row.get("Complexity", ""))
    question = str(row.get("Question", "")).lower()
    response_chars = row.get("Response Char Count", 0) or 0
    response = str(row.get("Final Response", "")).lower()

    # ── OOKB checks ────────────────────────────────────────
    if is_ookb(complexity):
        # OOKB: model should NOT loop querifai repeatedly without escalating
        if (
            tools["used_querifai"]
            and not tools["used_web_search"]
            and not tools["no_tools"]
        ):
            violations.append(
                (
                    "OOKB_RAG_LOOP",
                    "Used querifai for OOKB question without escalating to web_search",
                )
            )
        # OOKB: going to web_search directly is correct
        # OOKB: direct answer (no tools) is acceptable for "can't predict" questions
        # Flag if chart_generator used on OOKB — unnecessary
        if tools["used_chart"]:
            violations.append(
                ("OOKB_UNNECESSARY_CHART", "chart_generator called for OOKB question")
            )
        return violations  # No further checks for OOKB

    # ── Non-OOKB checks ─────────────────────────────────────

    # Missing lookup: no tools used for a question that needs data
    if tools["no_tools"]:
        violations.append(
            (
                "NO_TOOL_USED",
                "No tools used for a non-OOKB question requiring data lookup",
            )
        )
        return violations  # No point checking further

    # Web search triggered prematurely (before querifai/docufai exhausted)
    if tools["used_web_search"] and tools["web_search_before_rag"]:
        violations.append(
            (
                "WEB_SEARCH_BEFORE_RAG",
                "web_search called before trying retrieval_augmented_generation",
            )
        )

    if (
        tools["used_web_search"]
        and not tools["used_querifai"]
        and not tools["used_docufai"]
    ):
        violations.append(
            (
                "WEB_SEARCH_ONLY",
                "Only used web_search for a non-OOKB question, skipped RAG entirely",
            )
        )

    # If web_search triggered without querifai being used — check if it should have been
    if (
        tools["used_web_search"]
        and not tools["used_querifai"]
        and not is_text_only_question(question)
    ):
        violations.append(
            (
                "WEB_SEARCH_WITHOUT_QUERIFAI",
                "web_search used but querifai was never queried first",
            )
        )

    # Multi-source: must use BOTH querifai AND docufai
    if is_multi_source(complexity):
        if not tools["used_querifai"]:
            violations.append(
                (
                    "MULTI_SOURCE_MISSING_QUERIFAI",
                    "Multi-source question did not query querifai",
                )
            )
        if not tools["used_docufai"]:
            violations.append(
                (
                    "MULTI_SOURCE_MISSING_DOCUFAI",
                    "Multi-source question did not query docufai",
                )
            )

    # Chart generator checks
    if tools["used_chart"]:
        # Chart called but response is very short (chart likely failed/empty)
        if response_chars < 200 and tools["chart_count"] > 0:
            violations.append(
                (
                    "CHART_NO_OUTPUT",
                    f"chart_generator called {tools['chart_count']}x but response is very short ({response_chars} chars)",
                )
            )
        # Chart called for text-only question (unnecessary)
        if is_text_only_question(question):
            violations.append(
                (
                    "CHART_UNNECESSARY",
                    "chart_generator called for a text/name-only question",
                )
            )
        # Excessive chart calls (>3 for a single question)
        if tools["chart_count"] > 3:
            violations.append(
                (
                    "CHART_EXCESSIVE",
                    f"chart_generator called {tools['chart_count']} times (excessive)",
                )
            )
    else:
        # No chart but response contains Chart.js/canvas (chart created outside chart_generator)
        if "<canvas" in response or "chart.js" in response or "new chart(" in response:
            violations.append(
                (
                    "CHART_WITHOUT_AGENT",
                    "Response contains chart HTML but chart_generator tool was never called",
                )
            )

    return violations


# ─────────────────────────────────────────────
# SCORING
# ─────────────────────────────────────────────

# Violation severity → score penalty (out of 5)
VIOLATION_PENALTIES = {
    "NO_TOOL_USED": 4.0,  # Severe: answered without any lookup
    "WEB_SEARCH_BEFORE_RAG": 2.5,  # Severe: wrong order
    "WEB_SEARCH_ONLY": 3.0,  # Severe: skipped RAG entirely
    "WEB_SEARCH_WITHOUT_QUERIFAI": 2.0,  # Moderate
    "OOKB_RAG_LOOP": 2.5,  # Looped on OOKB
    "OOKB_UNNECESSARY_CHART": 1.0,  # Minor
    "MULTI_SOURCE_MISSING_DOCUFAI": 2.0,  # Missed a required source
    "MULTI_SOURCE_MISSING_QUERIFAI": 2.0,  # Missed a required source
    "CHART_NO_OUTPUT": 1.5,  # Chart called but empty
    "CHART_UNNECESSARY": 0.5,  # Minor: charts for text questions
    "CHART_EXCESSIVE": 1.0,  # Minor: too many chart calls
    "CHART_WITHOUT_AGENT": 1.5,  # Inconsistency
}


def compute_agentic_score(violations):
    """
    Base score = 5.0
    Subtract penalties for each violation (capped at 0).
    """
    base = 5.0
    total_penalty = sum(
        VIOLATION_PENALTIES.get(v_code, 1.0) for v_code, _ in violations
    )
    return max(0.0, base - total_penalty)


# ─────────────────────────────────────────────
# MAIN EVALUATION FUNCTION
# ─────────────────────────────────────────────


def evaluate_agentic_correctness(df):
    """
    Takes the combined dataframe (all models) and returns it enriched with:
      - agentic_score (0-5)
      - agentic_violations (list of violation codes as string)
      - agentic_violation_details (human-readable)
    """
    scores = []
    violation_codes = []
    violation_details = []

    for _, row in df.iterrows():
        tools = parse_tools(
            row.get("Brain Tool Calls"),
            row.get("Sub-Agent Tool Calls"),
            row.get("Agentic Steps", ""),
        )
        violations = detect_violations(row, tools)
        score = compute_agentic_score(violations)

        scores.append(score)
        violation_codes.append(
            "|".join(v[0] for v in violations) if violations else "OK"
        )
        violation_details.append(
            "; ".join(v[1] for v in violations) if violations else ""
        )

    result = df.copy()
    result["agentic_score"] = scores
    result["agentic_violations"] = violation_codes
    result["agentic_violation_details"] = violation_details
    return result


def agentic_summary(df_with_scores):
    """Per-model and per-complexity summary of agentic scores and violation rates."""

    per_model = (
        df_with_scores.groupby("Model")["agentic_score"]
        .agg(["mean", "min", "std", "count"])
        .round(3)
        .rename(
            columns={
                "mean": "avg_agentic_score",
                "min": "worst_score",
                "std": "score_std",
                "count": "n",
            }
        )
    )

    # Violation frequency per model
    all_violations = []
    for _, row in df_with_scores.iterrows():
        for v in row["agentic_violations"].split("|"):
            if v and v != "OK":
                all_violations.append({"Model": row["Model"], "violation": v})

    if all_violations:
        viol_df = pd.DataFrame(all_violations)
        viol_counts = (
            viol_df.groupby(["Model", "violation"]).size().unstack(fill_value=0)
        )
    else:
        viol_counts = pd.DataFrame()

    per_complexity = (
        df_with_scores.groupby(["Model", "Complexity"])["agentic_score"]
        .mean()
        .round(3)
        .unstack("Complexity")
        .reset_index()
    )

    return per_model, viol_counts, per_complexity


# ─────────────────────────────────────────────
# INTEGRATION INTO evaluate_models.py
# ─────────────────────────────────────────────
# Add this to the main() function in evaluate_models.py:
#
#   from agentic_eval import evaluate_agentic_correctness, agentic_summary
#
#   # After loading df:
#   df = evaluate_agentic_correctness(df)
#   agent_per_model, agent_violations, agent_per_complexity = agentic_summary(df)
#
#   # In compute_final_ranking(), add agentic_score to weights:
#   WEIGHTS = {
#       "judge_score":      0.40,
#       "agentic_score":    0.25,   # NEW
#       "reliability":      0.15,
#       "speed_norm":       0.10,
#       "token_efficiency": 0.10,
#   }
#   # And include agentic_norm in ranking:
#   merged["agentic_norm"] = df.groupby("Model")["agentic_score"].mean() / 5.0
#
#   # In export_results(), add sheets:
#   agent_per_model.to_excel(writer, sheet_name="Agentic Per Model")
#   agent_violations.to_excel(writer, sheet_name="Violation Counts")
#   agent_per_complexity.to_excel(writer, sheet_name="Agentic By Complexity", index=False)
# ─────────────────────────────────────────────


if __name__ == "__main__":
    import os
    import pandas as pd

    base_dir = "/mnt/user-data/uploads"
    MODEL_FILES = {
        "Ministral-3B": "ministral3-3b-inst_benchmark_results.xlsx",
        "Ministral-8B": "ministral3-8b-inst_benchmark_results.xlsx",
        "Nemotron-4B": "nemotro3-nano-4b_benchmark_results.xlsx",
        "Qwen3.5-9B": "qwen35-9b_benchmark_results.xlsx",
    }
    NEEDED = [
        "Q#",
        "Question",
        "Complexity",
        "Brain Tool Calls",
        "Sub-Agent Tool Calls",
        "Agentic Steps",
        "Response Char Count",
        "Final Response",
    ]
    dfs = []
    for model_name, filename in MODEL_FILES.items():
        bench = pd.read_excel(
            os.path.join(base_dir, filename), sheet_name="Benchmark Results"
        )
        bench = bench[[c for c in NEEDED if c in bench.columns]].copy()
        bench["Model"] = model_name
        dfs.append(bench)
    df = pd.concat(dfs, ignore_index=True)
    df_scored = evaluate_agentic_correctness(df)
    per_model, violations, per_complexity = agentic_summary(df_scored)

    print("\n" + "=" * 70)
    print("AGENTIC CORRECTNESS SCORES (0-5)")
    print("=" * 70)
    print(per_model.to_string())

    print("\n" + "=" * 70)
    print("VIOLATION COUNTS PER MODEL")
    print("=" * 70)
    if not violations.empty:
        print(violations.to_string())
    else:
        print("No violations found.")

    print("\n" + "=" * 70)
    print("AGENTIC SCORE BY COMPLEXITY")
    print("=" * 70)
    print(per_complexity.to_string(index=False))

    # Show worst offenders
    print("\n" + "=" * 70)
    print("WORST OFFENDERS (agentic_score < 3)")
    print("=" * 70)
    bad = df_scored[df_scored["agentic_score"] < 3][
        [
            "Model",
            "Q#",
            "Question",
            "Complexity",
            "agentic_score",
            "agentic_violations",
            "agentic_violation_details",
        ]
    ].copy()
    bad["Question"] = bad["Question"].str[:60]
    print(bad.sort_values("agentic_score").to_string(index=False))
