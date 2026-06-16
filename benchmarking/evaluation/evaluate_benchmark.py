"""
Model Evaluation Script
Evaluates 4 models across:
  - Layer 1: Deterministic metrics (speed, reliability, token efficiency)
  - Layer 2: LLM-as-a-Judge via Gemini API (accuracy, completeness, relevance, hallucination)

Usage:
    pip install pandas openpyxl google-generativeai tqdm
    export GEMINI_API_KEY="your_key_here"
    python evaluate_models.py
"""

import os
from dotenv import load_dotenv
import time
import json
import json_repair
import pandas as pd
from google import genai
from tqdm import tqdm
from agentic_eval import evaluate_agentic_correctness, agentic_summary

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
load_dotenv()
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
RATE_LIMIT_DELAY = 1.5  # seconds between Gemini calls (adjust for your quota)
MAX_RESPONSE_CHARS = 2000  # truncate long model responses before sending to judge

MODEL_FILES = {
    "Ministral-3B": "/home/apoorvsingh/Documents/experiements/slm_exploration/ministral3-3b-inst/ministral3-3b-inst_benchmark_results.xlsx",
    "Ministral-8B": "/home/apoorvsingh/Documents/experiements/slm_exploration/ministral3-8b-inst/ministral3-8b-inst_benchmark_results.xlsx",
    "Nemotron-4B": "/home/apoorvsingh/Documents/experiements/slm_exploration/nemotro3-nano-4b/nemotro3-nano-4b_benchmark_results.xlsx",
    "Qwen3.5-9B": "/home/apoorvsingh/Documents/experiements/slm_exploration/qwen35-9b/qwen35-9b_benchmark_results.xlsx",
    "Qwen3.5-4B": "/home/apoorvsingh/Documents/experiements/slm_exploration/qwen35-4b/qwen35-4b_benchmark_results.xlsx",
    "Qwen3.5-2B": "/home/apoorvsingh/Documents/experiements/slm_exploration/qwen35-2b/qwen35-2b_benchmark_results.xlsx",
    "Qwen3.5-0.8B": "/home/apoorvsingh/Documents/experiements/slm_exploration/qwen35-08b/qwen35-08b_benchmark_results.xlsx",
    "Gemma-4-E2B-it": "/home/apoorvsingh/Documents/experiements/slm_exploration/gemma4-e2b-it/gemma4-e2b-it_benchmark_results.xlsx",
    "Gemma-4-E4B-it": "/home/apoorvsingh/Documents/experiements/slm_exploration/gemma4-e4b-it/gemma4-e4b-it_benchmark_results.xlsx",
}

# Scoring weights for final composite score
WEIGHTS = {
    "judge_score": 0.40,  # Gemini quality scores
    "agentic_score": 0.25,  # Tool routing correctness
    "reliability": 0.15,  # Clean streams %
    "speed_norm": 0.10,  # Response time
    "token_efficiency": 0.10,  # Quality per token
}

OOKB_COMPLEXITIES = {
    "High (OOKB)"
}  # questions where correct behavior is to say "I don't know"

# ─────────────────────────────────────────────
# JUDGE PROMPT
# ─────────────────────────────────────────────
JUDGE_PROMPT_STANDARD = """You are an expert evaluator for AI assistant responses. 
A user asked a question and the AI produced a response. A reference answer (ground truth) is also provided.

**Question:** {question}

**Complexity:** {complexity}

**Ground Truth Answer:** {ground_truth}

**Model Response (truncated if long):**
{model_response}

Score the model response on these 4 criteria (each 1-5):

1. **Accuracy** (1-5): Does the response contain correct factual information compared to the ground truth?
   - 5: Fully accurate, no errors
   - 3: Mostly accurate, minor errors or omissions
   - 1: Incorrect or contradicts ground truth

2. **Completeness** (1-5): Does the response cover all key aspects of what was asked?
   - 5: Fully complete
   - 3: Partially complete, missing some important points
   - 1: Very incomplete or off-topic

3. **Relevance** (1-5): Is the response focused on answering the actual question?
   - 5: Highly relevant, directly answers the question
   - 3: Partially relevant, includes tangential content
   - 1: Mostly irrelevant

4. **Hallucination-Free** (1-5): Does the response avoid making up facts not in the ground truth?
   - 5: No hallucinations detected
   - 3: Some unsupported claims but not critically wrong
   - 1: Significant fabrications

Respond ONLY with a JSON object like this (no markdown, no explanation):
{{"accuracy": 4, "completeness": 3, "relevance": 5, "hallucination_free": 4, "reasoning": "brief one-line reason"}}
"""

JUDGE_PROMPT_OOKB = """You are an expert evaluator for AI assistant responses.
This question is OUT-OF-KNOWLEDGE-BASE (OOKB) — the correct behavior is to clearly state 
that the information is not available in the data sources, WITHOUT making up an answer.
Speculating, hallucinating, or providing invented figures is a serious failure.

**Question:** {question}

**Expected Behavior:** Politely decline, say the data is not available, and optionally redirect.

**Model Response (truncated if long):**
{model_response}

Score the model response on these 4 criteria (each 1-5):

1. **Accuracy** (1-5): Did the model correctly recognize it cannot answer from its knowledge base?
   - 5: Clearly states data unavailable, no hallucination
   - 3: Partially correct, some hedging but also some speculation
   - 1: Confidently provides a wrong/made-up answer

2. **Completeness** (1-5): Did it explain WHY it can't answer and offer alternatives?
   - 5: Explains limitation and provides helpful redirect
   - 3: Just says "I don't know" with no context
   - 1: Ignores the limitation entirely

3. **Relevance** (1-5): Is the response focused on the question being asked?
   - 5: Directly addresses why this specific question cannot be answered
   - 3: Somewhat relevant but vague
   - 1: Completely off-topic

4. **Hallucination-Free** (1-5): Did the model avoid inventing data?
   - 5: No made-up data, sticks to saying "unknown"
   - 3: Some hedged speculation
   - 1: Presents fabricated data as fact

Respond ONLY with a JSON object like this (no markdown, no explanation):
{{"accuracy": 4, "completeness": 3, "relevance": 5, "hallucination_free": 4, "reasoning": "brief one-line reason"}}
"""


# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────
def load_model_data(model_name, filepath):
    """Load ground truth and benchmark results from one xlsx file."""
    xls = pd.ExcelFile(filepath)

    # Ground truth
    gt = pd.read_excel(xls, sheet_name="Sheet1")
    gt = gt[["Question", "Answer", "Source", "Complexity"]].rename(
        columns={"Answer": "GroundTruth"}
    )

    # Benchmark results
    bench = pd.read_excel(xls, sheet_name="Benchmark Results")
    bench = bench[
        [
            "Q#",
            "Question",
            "Complexity",
            "Total Time (s)",
            "Time to First Token (s)",
            "Brain Completion Tokens",
            "Brain Prompt Tokens",
            "Tokens / Sec",
            "Agents Total Tokens",
            "Stream Ended Cleanly",
            "Premature Break Reason",
            "Response Char Count",
            "Final Response",
        ]
    ]

    # Merge with ground truth
    df = bench.merge(gt[["Question", "GroundTruth"]], on="Question", how="left")
    df["Model"] = model_name
    return df


def load_all_models(model_files, base_dir=""):
    dfs = []
    for model_name, filename in model_files.items():
        path = os.path.join(base_dir, filename)
        print(f"Loading {model_name} from {path}...")
        df = load_model_data(model_name, path)
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


# ─────────────────────────────────────────────
# LAYER 1: DETERMINISTIC METRICS
# ─────────────────────────────────────────────
def compute_deterministic_metrics(df):
    """Compute per-model summary of speed, reliability, and efficiency metrics."""
    results = []
    for model, group in df.groupby("Model"):
        total_q = len(group)
        clean = (group["Stream Ended Cleanly"].astype(str).str.upper() == "YES").sum()
        reliability_pct = clean / total_q * 100

        avg_total_time = group["Total Time (s)"].mean()
        avg_ttft = group["Time to First Token (s)"].mean()
        avg_tok_per_sec = group["Tokens / Sec"].mean()
        avg_brain_tokens = group["Brain Completion Tokens"].mean()
        avg_agent_tokens = group["Agents Total Tokens"].mean()
        avg_resp_chars = group["Response Char Count"].mean()

        results.append(
            {
                "Model": model,
                "Total Questions": total_q,
                "Clean Streams (%)": round(reliability_pct, 1),
                "Avg Total Time (s)": round(avg_total_time, 2),
                "Avg TTFT (s)": round(avg_ttft, 2),
                "Avg Tokens/Sec": round(avg_tok_per_sec, 2),
                "Avg Brain Tokens": round(avg_brain_tokens, 1),
                "Avg Agent Tokens": round(avg_agent_tokens, 1),
                "Avg Response Chars": round(avg_resp_chars, 1),
            }
        )

    return pd.DataFrame(results)


# ─────────────────────────────────────────────
# LAYER 2: LLM-AS-A-JUDGE (GEMINI)
# ─────────────────────────────────────────────
def call_gemini_judge(
    client: genai.Client, question, complexity, ground_truth, model_response
):
    """Call Gemini to score a single response. Returns dict with scores."""
    is_ookb = complexity in OOKB_COMPLEXITIES

    # Truncate response
    response_trunc = (
        str(model_response)[:MAX_RESPONSE_CHARS]
        if model_response
        else "(empty response)"
    )

    if is_ookb:
        prompt = JUDGE_PROMPT_OOKB.format(
            question=question,
            model_response=response_trunc,
        )
    else:
        prompt = JUDGE_PROMPT_STANDARD.format(
            question=question,
            complexity=complexity,
            ground_truth=str(ground_truth)[:500],
            model_response=response_trunc,
        )

    try:
        response = client.models.generate_content(
            model="gemini-3-flash-preview", contents=prompt
        )
        text = response.text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        scores = json_repair.loads(text)
        return scores
    except Exception as e:
        print(f"  Gemini error: {e} | raw: {getattr(response, 'text', 'N/A')[:200]}")
        return {
            "accuracy": 0,
            "completeness": 0,
            "relevance": 0,
            "hallucination_free": 0,
            "reasoning": f"error: {e}",
        }


def run_llm_judge(df, gemini_api_key, rate_limit_delay=1.5):
    """Run Gemini judge on all rows. Returns df with score columns added."""
    client = genai.Client(api_key=gemini_api_key)

    judge_results = []
    total = len(df)

    print(f"\nRunning LLM-as-a-Judge on {total} rows...")
    for idx, row in tqdm(df.iterrows(), total=total):
        scores = call_gemini_judge(
            client,
            question=row["Question"],
            complexity=row["Complexity"],
            ground_truth=row.get("GroundTruth", ""),
            model_response=row["Final Response"],
        )
        scores["idx"] = idx
        judge_results.append(scores)
        time.sleep(rate_limit_delay)

    judge_df = pd.DataFrame(judge_results).set_index("idx")
    result = df.join(
        judge_df[
            ["accuracy", "completeness", "relevance", "hallucination_free", "reasoning"]
        ]
    )
    result["judge_avg"] = result[
        ["accuracy", "completeness", "relevance", "hallucination_free"]
    ].mean(axis=1)
    return result


# ─────────────────────────────────────────────
# LAYER 2 (OPTIONAL): BATCH WITH CACHING
# ─────────────────────────────────────────────
def run_llm_judge_with_cache(
    df, gemini_api_key, cache_path="judge_cache.json", rate_limit_delay=1.5
):
    """Same as run_llm_judge but caches results so reruns are free."""
    # Load cache
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            cache = json.load(f)
        print(f"Loaded {len(cache)} cached judgments from {cache_path}")

    client = genai.Client(api_key=gemini_api_key)

    judge_results = []
    total = len(df)

    print(f"\nRunning LLM-as-a-Judge on {total} rows (with caching)...")
    for idx, row in tqdm(df.iterrows(), total=total):
        cache_key = f"{row['Model']}|{row['Q#']}|{row['Question'][:80]}"

        if cache_key in cache:
            scores = cache[cache_key]
        else:
            scores = call_gemini_judge(
                client,
                question=row["Question"],
                complexity=row["Complexity"],
                ground_truth=row.get("GroundTruth", ""),
                model_response=row["Final Response"],
            )
            cache[cache_key] = scores
            # Save cache incrementally
            with open(cache_path, "w") as f:
                json.dump(cache, f, indent=2)
            time.sleep(rate_limit_delay)

        scores["idx"] = idx
        judge_results.append(scores)

    judge_df = pd.DataFrame(judge_results).set_index("idx")
    result = df.join(
        judge_df[
            ["accuracy", "completeness", "relevance", "hallucination_free", "reasoning"]
        ]
    )
    result["judge_avg"] = result[
        ["accuracy", "completeness", "relevance", "hallucination_free"]
    ].mean(axis=1)
    return result


# ─────────────────────────────────────────────
# AGGREGATE & RANK
# ─────────────────────────────────────────────
def compute_complexity_breakdown(judged_df):
    """Judge scores broken down by complexity type per model."""
    return (
        judged_df.groupby(["Model", "Complexity"])["judge_avg"]
        .mean()
        .round(2)
        .unstack("Complexity")
        .reset_index()
    )


def compute_final_ranking(judged_df, det_df, weights=WEIGHTS):
    """Combine judge scores with deterministic metrics into a final ranking."""
    # Judge scores per model
    judge_agg = (
        judged_df.groupby("Model")[
            ["accuracy", "completeness", "relevance", "hallucination_free", "judge_avg"]
        ]
        .mean()
        .round(3)
    )

    # Merge with deterministic
    merged = det_df.set_index("Model").join(judge_agg)

    # Normalize speed: lower total time = better; scale 0-1 across models
    max_time = merged["Avg Total Time (s)"].max()
    min_time = merged["Avg Total Time (s)"].min()
    merged["speed_norm"] = 1 - (
        (merged["Avg Total Time (s)"] - min_time) / (max_time - min_time + 1e-9)
    )

    # Normalize reliability
    merged["reliability_norm"] = merged["Clean Streams (%)"] / 100.0

    # Normalize judge score
    merged["judge_norm"] = merged["judge_avg"] / 5.0

    merged["agentic_norm"] = judged_df.groupby("Model")["agentic_score"].mean() / 5.0

    # Token efficiency: judge_avg per 1000 agent tokens (higher = more efficient)
    merged["tok_eff_raw"] = (
        merged["judge_avg"]
        / (judged_df.groupby("Model")["Agents Total Tokens"].mean() / 1000)
    ).round(4)
    max_eff = merged["tok_eff_raw"].max()
    min_eff = merged["tok_eff_raw"].min()
    merged["token_efficiency"] = (merged["tok_eff_raw"] - min_eff) / (
        max_eff - min_eff + 1e-9
    )

    # Composite score
    merged["composite_score"] = (
        weights["judge_score"] * merged["judge_norm"]
        + weights["agentic_score"] * merged["agentic_norm"]
        + weights["reliability"] * merged["reliability_norm"]
        + weights["speed_norm"] * merged["speed_norm"]
        + weights["token_efficiency"] * merged["token_efficiency"]
    )

    merged["rank"] = merged["composite_score"].rank(ascending=False).astype(int)
    return merged.sort_values("rank").round(3)


# ─────────────────────────────────────────────
# EXPORT RESULTS
# ─────────────────────────────────────────────
def export_results(
    judged_df,
    det_df,
    ranking_df,
    complexity_df,
    agent_per_model,
    agent_violations,
    agent_per_complexity,
    output_path="evaluation_results.xlsx",
):
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        ranking_df.to_excel(writer, sheet_name="Final Rankings")
        det_df.to_excel(writer, sheet_name="Deterministic Metrics", index=False)
        complexity_df.to_excel(writer, sheet_name="Score by Complexity", index=False)
        agent_per_model.to_excel(writer, sheet_name="Agentic Per Model")
        agent_violations.to_excel(writer, sheet_name="Violation Counts")
        agent_per_complexity.to_excel(
            writer, sheet_name="Agentic By Complexity", index=False
        )
        judged_df[
            [
                "Model",
                "Q#",
                "Question",
                "Complexity",
                "GroundTruth",
                "Final Response",
                "accuracy",
                "completeness",
                "relevance",
                "hallucination_free",
                "judge_avg",
                "reasoning",
                "Total Time (s)",
                "Tokens / Sec",
                "Stream Ended Cleanly",
            ]
        ].to_excel(writer, sheet_name="All Judgments", index=False)

    print(f"\n✅ Results exported to: {output_path}")


# ─────────────────────────────────────────────
# PRINT SUMMARY
# ─────────────────────────────────────────────
def print_summary(ranking_df, complexity_df):
    print("\n" + "=" * 70)
    print("FINAL MODEL RANKINGS")
    print("=" * 70)
    cols = [
        "rank",
        "judge_avg",
        "accuracy",
        "completeness",
        "hallucination_free",
        "Clean Streams (%)",
        "Avg Total Time (s)",
        "Avg Tokens/Sec",
        "composite_score",
    ]
    available = [c for c in cols if c in ranking_df.columns]
    print(ranking_df[available].to_string())

    print("\n" + "=" * 70)
    print("JUDGE SCORES BY COMPLEXITY")
    print("=" * 70)
    print(complexity_df.to_string(index=False))


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    # ── 1. Load data ──────────────────────────
    base_dir = ""  # set to folder with xlsx files if not current dir
    df = load_all_models(MODEL_FILES, base_dir=base_dir)
    df = evaluate_agentic_correctness(df)
    print(f"\nLoaded {len(df)} total rows across {df['Model'].nunique()} models.")

    # ── 2. Deterministic metrics ───────────────
    print("\nComputing deterministic metrics...")
    det_df = compute_deterministic_metrics(df)
    print(det_df.to_string(index=False))

    # ── 3. LLM-as-a-Judge ─────────────────────
    judged_df = run_llm_judge_with_cache(
        df, GEMINI_API_KEY, rate_limit_delay=RATE_LIMIT_DELAY
    )

    # ── 4. Agentic evaluation ─────────────────────
    agent_per_model, agent_violations, agent_per_complexity = agentic_summary(df)

    # ── 5. Aggregate & rank ────────────────────
    ranking_df = compute_final_ranking(judged_df, det_df)
    complexity_df = compute_complexity_breakdown(judged_df)

    # ── 6. Print & export ──────────────────────
    print_summary(ranking_df, complexity_df)
    export_results(
        judged_df,
        det_df,
        ranking_df,
        complexity_df,
        agent_per_model,
        agent_violations,
        agent_per_complexity,
    )


if __name__ == "__main__":
    main()
