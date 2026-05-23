"""KFP components for the NNDSS capability evaluation pipeline.

Handles non-LLM stages: data loading, triage, gold standard merging,
summary aggregation, and MLflow logging.
"""

from kfp import dsl


@dsl.component(base_image="python:3.11-slim", packages_to_install=["pandas>=2.0"])
def load_questions(
    output_data: dsl.Output[dsl.Dataset],
    input_path: str = "/mnt/eval-data/input/questions.jsonl",
    limit: int = 0,
):
    """Load evaluation questions from JSONL and prepare for the pipeline."""
    import pandas as pd

    df = pd.read_json(input_path, lines=True)
    if limit > 0:
        df = df.head(limit)

    if "eval_question" not in df.columns:
        df["eval_question"] = df["question"]

    for col in [
        "id",
        "question_type",
        "can_server_answer",
        "evaluation_criteria",
        "good_answer",
        "relevant_capabilities",
    ]:
        if col not in df.columns:
            df[col] = ""

    df.to_json(output_data.path, orient="records", lines=True, force_ascii=False)
    print(f"Loaded {len(df)} questions (limit={limit})")


@dsl.component(base_image="python:3.11-slim", packages_to_install=["pandas>=2.0"])
def triage(
    input_data: dsl.Input[dsl.Dataset],
    output_data: dsl.Output[dsl.Dataset],
):
    """Extract agent answer, reasoning, and tool interactions from traces."""
    import json
    import re

    import pandas as pd

    df = pd.read_json(input_data.path, lines=True)

    agent_answers = []
    agent_reasonings = []
    tool_interactions_list = []
    n_tool_calls_list = []

    for _, row in df.iterrows():
        trace = row.get("agent_trace")
        if not trace or (isinstance(trace, str) and trace.strip() == ""):
            agent_answers.append("")
            agent_reasonings.append("")
            tool_interactions_list.append("")
            n_tool_calls_list.append(0)
            continue

        if isinstance(trace, str):
            try:
                trace = json.loads(trace)
            except json.JSONDecodeError:
                agent_answers.append("")
                agent_reasonings.append("")
                tool_interactions_list.append("")
                n_tool_calls_list.append(0)
                continue

        messages = trace.get("messages", [])

        assistant_texts = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("content"):
                assistant_texts.append(msg["content"])
        final_answer = assistant_texts[-1] if assistant_texts else ""
        if not final_answer and len(assistant_texts) > 1:
            final_answer = "\n\n".join(assistant_texts)
        agent_answers.append(final_answer)

        reasoning = ""
        full_text = "\n".join(assistant_texts)
        match = re.search(r"<reasoning>(.*?)</reasoning>", full_text, re.DOTALL)
        if match:
            reasoning = match.group(1).strip()
        agent_reasonings.append(reasoning)

        tool_calls = []
        tool_responses = []
        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    tool_calls.append({
                        "name": fn.get("name", "unknown"),
                        "arguments": fn.get("arguments", "{}"),
                    })
            elif msg.get("role") == "tool":
                tool_responses.append(msg.get("content", ""))

        n_tool_calls_list.append(len(tool_calls))

        if not tool_calls:
            tool_interactions_list.append("")
        else:
            parts = []
            for i, tc in enumerate(tool_calls, 1):
                args_str = tc["arguments"]
                if isinstance(args_str, dict):
                    args_str = json.dumps(args_str)
                resp = (
                    tool_responses[i - 1]
                    if i - 1 < len(tool_responses)
                    else "(no response)"
                )
                resp_preview = resp[:500] if resp else "(empty)"
                parts.append(
                    f"[{i}] CALL: {tc['name']}({args_str})\n"
                    f"    RESPONSE: {resp_preview}"
                )
            tool_interactions_list.append("\n".join(parts))

    df["agent_answer"] = agent_answers
    df["agent_reasoning"] = agent_reasonings
    df["tool_interactions"] = tool_interactions_list
    df["n_tool_calls"] = n_tool_calls_list

    df.to_json(output_data.path, orient="records", lines=True, force_ascii=False)

    n_total = len(df)
    n_with_tools = sum(1 for n in n_tool_calls_list if n > 0)
    n_with_reasoning = sum(1 for r in agent_reasonings if r)
    print(
        f"Triaged {n_total} questions: "
        f"{n_with_tools} with tool calls, "
        f"{n_with_reasoning} with reasoning blocks"
    )


@dsl.component(
    base_image="python:3.11-slim",
    packages_to_install=["pandas>=2.0", "pyyaml>=6.0"],
)
def merge_gold_standards(
    triaged_data: dsl.Input[dsl.Dataset],
    output_data: dsl.Output[dsl.Dataset],
    gold_standards_dir: str = "/mnt/eval-gold-standards",
):
    """Merge gold standard YAML files into triaged data for judge input."""
    import json
    import os

    import pandas as pd
    import yaml

    df = pd.read_json(triaged_data.path, lines=True)

    gold = {}
    if os.path.isdir(gold_standards_dir):
        for fname in sorted(os.listdir(gold_standards_dir)):
            if not fname.endswith(".yaml") and not fname.endswith(".yml"):
                continue
            fpath = os.path.join(gold_standards_dir, fname)
            with open(fpath, "r") as f:
                doc = yaml.safe_load(f)
            if doc and "id" in doc:
                gold[doc["id"]] = doc

    print(f"Loaded {len(gold)} gold standard files from {gold_standards_dir}")

    good_answers = []
    gold_reasonings = []
    relevant_caps = []
    eval_criteria = []
    matched = 0

    for _, row in df.iterrows():
        qid = row.get("id", "")
        gs = gold.get(qid)

        if gs is None:
            good_answers.append(row.get("good_answer", ""))
            gold_reasonings.append("")
            relevant_caps.append(row.get("relevant_capabilities", ""))
            eval_criteria.append(row.get("evaluation_criteria", ""))
            continue

        matched += 1

        good_answers.append(
            gs.get("gold_standard_answer", gs.get("good_answer", ""))
        )

        steps = gs.get("gold_standard_reasoning", [])
        if steps and isinstance(steps, list):
            lines = []
            for s in steps:
                step_num = s.get("step", "?")
                consideration = s.get("consideration", "")
                thought = s.get("thought", "").strip()
                lines.append(f"Step {step_num} ({consideration}): {thought}")
            gold_reasonings.append("\n".join(lines))
        else:
            gold_reasonings.append("")

        caps = gs.get("relevant_capabilities", {})
        if isinstance(caps, dict):
            relevant_caps.append(json.dumps(caps))
        else:
            relevant_caps.append(json.dumps(caps) if caps else "")

        criteria = gs.get("evaluation_criteria", [])
        if isinstance(criteria, list):
            eval_criteria.append(", ".join(str(c) for c in criteria))
        else:
            eval_criteria.append(str(criteria) if criteria else "")

    df["good_answer"] = good_answers
    df["gold_standard_reasoning"] = gold_reasonings
    df["relevant_capabilities"] = relevant_caps
    df["evaluation_criteria"] = eval_criteria

    df.to_json(output_data.path, orient="records", lines=True, force_ascii=False)
    print(f"Merged gold standards: {matched}/{len(df)} questions matched")


@dsl.component(base_image="python:3.11-slim", packages_to_install=["pandas>=2.0"])
def summary(
    judged_data: dsl.Input[dsl.Dataset],
    triaged_data: dsl.Input[dsl.Dataset],
    output_data: dsl.Output[dsl.Dataset],
    output_metrics: dsl.Output[dsl.Metrics],
    run_name: str = "eval-run",
):
    """Aggregate capability scores and produce evaluation summary."""
    import pandas as pd

    judged = pd.read_json(judged_data.path, lines=True)
    triaged = pd.read_json(triaged_data.path, lines=True)

    capabilities = [
        "cross_dataset_reasoning",
        "methodology_awareness",
        "scope_adherence",
        "causal_inference_boundaries",
        "geographic_resolution_knowledge",
        "terminology_fluency",
        "confidence_calibration",
    ]

    cap_means = {}
    cap_counts = {}
    all_scores = []

    for cap in capabilities:
        if cap not in judged.columns:
            cap_means[cap] = float("nan")
            cap_counts[cap] = 0
            continue

        series = judged[cap].copy()
        numeric = pd.to_numeric(
            series.where(series.astype(str).str.strip() != "N/A"),
            errors="coerce",
        )
        valid = numeric.dropna()
        cap_means[cap] = valid.mean() if len(valid) > 0 else float("nan")
        cap_counts[cap] = len(valid)
        all_scores.extend(valid.tolist())

    overall_mean = (
        sum(all_scores) / len(all_scores) if all_scores else float("nan")
    )

    n_total = len(triaged)
    if "n_tool_calls" in triaged.columns:
        n_with_tools = int((triaged["n_tool_calls"] > 0).sum())
    else:
        n_with_tools = 0

    output_metrics.log_metric("n_questions", n_total)
    output_metrics.log_metric("n_with_tools", n_with_tools)
    output_metrics.log_metric(
        "tool_call_rate",
        round(n_with_tools / n_total, 3) if n_total > 0 else 0.0,
    )
    output_metrics.log_metric(
        "overall_capability_mean",
        round(float(overall_mean), 3) if pd.notna(overall_mean) else 0.0,
    )
    for cap in capabilities:
        val = cap_means[cap]
        output_metrics.log_metric(
            f"mean_{cap}",
            round(float(val), 3) if pd.notna(val) else 0.0,
        )
        output_metrics.log_metric(f"n_{cap}", cap_counts[cap])

    def fmt(val):
        return f"{val:.2f}" if pd.notna(val) else "N/A"

    print()
    print(f"CAPABILITY EVALUATION -- {run_name}")
    print("=" * 60)
    print(f"Questions: {n_total}")
    print(f"Tool call rate: {n_with_tools}/{n_total}")
    print()
    print("Per-Capability Scores (1-5, excluding N/A):")
    for cap in capabilities:
        label = f"  {cap}:"
        score_str = fmt(cap_means[cap])
        count_str = f"(n={cap_counts[cap]})"
        print(f"{label:<43} {score_str:>5} {count_str}")
    print()
    print(f"Overall capability mean: {fmt(overall_mean)}")
    print("=" * 60)

    judged.to_json(
        output_data.path, orient="records", lines=True, force_ascii=False
    )


@dsl.component(
    base_image="python:3.11-slim",
    packages_to_install=["mlflow>=3.10.1", "pandas>=2.0"],
)
def log_to_mlflow(
    judged_data: dsl.Input[dsl.Dataset],
    questions_data: dsl.Input[dsl.Dataset],
    run_name: str = "eval-run",
    experiment_name: str = "nndss-data-agent-evals",
):
    """Log evaluation dataset and results to MLflow."""
    import os

    import pandas as pd

    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    if not mlflow_uri:
        print("[mlflow] No MLFLOW_TRACKING_URI set, skipping MLflow logging")
        return

    import mlflow

    token_file = os.environ.get("MLFLOW_TRACKING_TOKEN_FILE", "").strip()
    if token_file and os.path.isfile(token_file):
        with open(token_file) as f:
            os.environ["MLFLOW_TRACKING_TOKEN"] = f.read().strip()

    mlflow.set_tracking_uri(mlflow_uri)

    workspace = os.environ.get("MLFLOW_WORKSPACE", "").strip()
    if workspace:
        mlflow.set_workspace(workspace)

    import mlflow.tracking.fluent as _fluent

    client = mlflow.MlflowClient()

    if workspace:
        exps = client.search_experiments(
            filter_string=f"name = '{experiment_name}'"
        )
        if exps:
            _fluent._active_experiment_id = exps[0].experiment_id
        else:
            exp_id = client.create_experiment(experiment_name)
            _fluent._active_experiment_id = exp_id
    else:
        mlflow.set_experiment(experiment_name)

    judged = pd.read_json(judged_data.path, lines=True)
    questions = pd.read_json(questions_data.path, lines=True)

    capabilities = [
        "cross_dataset_reasoning",
        "methodology_awareness",
        "scope_adherence",
        "causal_inference_boundaries",
        "geographic_resolution_knowledge",
        "terminology_fluency",
        "confidence_calibration",
    ]

    # Create MLflow evaluation dataset
    try:
        eval_dataset = mlflow.genai.datasets.create_dataset(
            name=f"nndss-eval-{run_name}",
        )
        records = []
        for _, row in questions.iterrows():
            records.append({
                "inputs": {"question": row.get("eval_question", "")},
                "expectations": {
                    "good_answer": str(row.get("good_answer", "")),
                    "question_type": str(row.get("question_type", "")),
                },
            })
        eval_dataset.merge_records(records)
        print(
            f"[mlflow] Created eval dataset 'nndss-eval-{run_name}' "
            f"with {len(records)} records"
        )
    except Exception as exc:
        print(f"[mlflow] Dataset creation failed (continuing): {exc}")

    # Log eval run with metrics
    with mlflow.start_run(run_name=run_name):
        for cap in capabilities:
            if cap in judged.columns:
                numeric = pd.to_numeric(
                    judged[cap].where(
                        judged[cap].astype(str).str.strip() != "N/A"
                    ),
                    errors="coerce",
                )
                valid = numeric.dropna()
                if len(valid) > 0:
                    mlflow.log_metric(f"mean_{cap}", round(valid.mean(), 3))
                    mlflow.log_metric(f"n_{cap}", len(valid))

        all_scores = []
        for cap in capabilities:
            if cap in judged.columns:
                numeric = pd.to_numeric(
                    judged[cap].where(
                        judged[cap].astype(str).str.strip() != "N/A"
                    ),
                    errors="coerce",
                )
                all_scores.extend(numeric.dropna().tolist())
        if all_scores:
            mlflow.log_metric(
                "overall_capability_mean",
                round(sum(all_scores) / len(all_scores), 3),
            )

        if "n_tool_calls" in judged.columns:
            n_with_tools = int((judged["n_tool_calls"] > 0).sum())
            mlflow.log_metric(
                "tool_call_rate",
                round(n_with_tools / len(judged), 3),
            )

        judged.to_json(
            "/tmp/eval_results.jsonl",
            orient="records",
            lines=True,
            force_ascii=False,
        )
        mlflow.log_artifact("/tmp/eval_results.jsonl", "eval-results")

        questions.to_json(
            "/tmp/eval_questions.jsonl",
            orient="records",
            lines=True,
            force_ascii=False,
        )
        mlflow.log_artifact("/tmp/eval_questions.jsonl", "eval-datasets")

        try:
            prompt = mlflow.genai.load_prompt(
                "prompts:/nndss-agent.system@production",
                allow_missing=True,
                cache_ttl_seconds=60,
            )
            if prompt:
                mlflow.log_param("system_prompt_version", prompt.version)
        except Exception:
            pass

        print(
            f"[mlflow] Logged eval run '{run_name}' "
            f"with {len(judged)} judged responses"
        )
