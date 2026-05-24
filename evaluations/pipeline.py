"""Kubeflow Pipeline for NNDSS Health Agent Evaluation.

Evaluates the NNDSS disease surveillance agent on 7 capability dimensions
using mlflow.genai.evaluate() with Guidelines scorers.

Pipeline steps:
1. setup_mlflow_op: Configure MLflow tracking
2. create_dataset_op: Create evaluation dataset in MLflow
3. run_eval_op: Run evaluation with LLM-as-judge scorers
4. report_results_op: Print scorecard

Usage:
    python evaluations/pipeline.py --compile
"""

from typing import NamedTuple

import kfp
from kfp import dsl
from kfp.dsl import component
from kfp import kubernetes


BASE_IMAGE = "python:3.12-slim"

COMMON_PACKAGES = [
    "mlflow>=3.10",
    "nest-asyncio>=1.6.0",
    "pydantic>=2.0.0",
    "httpx>=0.27.0",
]

SDG_PACKAGES = COMMON_PACKAGES + [
    "sdg-hub>=0.7.0,<1.0",
    "pandas>=2.0",
    "pyyaml>=6.0",
]

AGENT_PACKAGES = COMMON_PACKAGES + [
    "langchain>=0.3",
    "langchain-openai>=0.3",
    "langchain-core>=0.3",
    "langgraph>=0.4",
    "trino>=0.329",
    "openai>=1.0",
]


# =============================================================================
# Step 1: Setup MLflow
# =============================================================================
@component(base_image=BASE_IMAGE, packages_to_install=COMMON_PACKAGES)
def setup_mlflow_op(
    mlflow_tracking_uri: str,
    mlflow_experiment_name: str,
    mlflow_workspace: str = "",
) -> str:
    """Configure MLflow tracking and return experiment name."""
    import os
    from pathlib import Path
    import mlflow

    os.environ["MLFLOW_TRACKING_INSECURE_TLS"] = "true"

    if not os.environ.get("MLFLOW_TRACKING_TOKEN"):
        sa_token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        if sa_token_path.exists():
            os.environ["MLFLOW_TRACKING_TOKEN"] = sa_token_path.read_text().strip()

    mlflow.set_tracking_uri(mlflow_tracking_uri)

    if mlflow_workspace:
        mlflow.set_workspace(mlflow_workspace)

    experiment_name = mlflow_experiment_name
    if not experiment_name.endswith("-eval"):
        experiment_name = f"{experiment_name}-eval"

    # Use search_experiments workaround for RHOAI gateway
    if mlflow_workspace:
        import mlflow.tracking.fluent as _fluent
        client = mlflow.MlflowClient()
        exps = client.search_experiments(filter_string=f"name = '{experiment_name}'")
        if exps:
            _fluent._active_experiment_id = exps[0].experiment_id
        else:
            _fluent._active_experiment_id = client.create_experiment(experiment_name)
    else:
        mlflow.set_experiment(experiment_name)

    print(f"MLflow: {mlflow_tracking_uri} | Experiment: {experiment_name}")
    return experiment_name


# =============================================================================
# Step 2: Create Dataset
# =============================================================================
@component(base_image=BASE_IMAGE, packages_to_install=COMMON_PACKAGES)
def create_dataset_op(
    mlflow_tracking_uri: str,
    experiment_name: str,
    dataset_name: str,
    mlflow_workspace: str = "",
) -> NamedTuple("DatasetOutput", [("experiment_name", str), ("dataset_id", str)]):
    """Create NNDSS evaluation dataset in MLflow."""
    import os
    from typing import NamedTuple
    from pathlib import Path
    import mlflow
    from mlflow.genai.datasets import create_dataset

    os.environ["MLFLOW_TRACKING_INSECURE_TLS"] = "true"
    if not os.environ.get("MLFLOW_TRACKING_TOKEN"):
        sa_token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        if sa_token_path.exists():
            os.environ["MLFLOW_TRACKING_TOKEN"] = sa_token_path.read_text().strip()

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    if mlflow_workspace:
        mlflow.set_workspace(mlflow_workspace)
        import mlflow.tracking.fluent as _fluent
        client = mlflow.MlflowClient()
        exps = client.search_experiments(filter_string=f"name = '{experiment_name}'")
        if exps:
            _fluent._active_experiment_id = exps[0].experiment_id
    else:
        mlflow.set_experiment(experiment_name)

    # 10 seed questions — SDG Hub generates variants in a separate step
    test_cases = [
        {"inputs": {"question": "How many influenza cases were notified in NSW in 2023?"}, "expectations": {"expected_keywords": ["notifications", "laboratory-confirmed"], "question_type": "data_retrieval"}},
        {"inputs": {"question": "Which state had the highest salmonellosis notifications in 2022?"}, "expectations": {"expected_keywords": ["salmonellosis"], "question_type": "data_retrieval"}},
        {"inputs": {"question": "Compare influenza and pneumococcal disease notification trends over the past 5 years"}, "expectations": {"expected_keywords": ["influenza", "pneumococcal"], "question_type": "cross_dataset"}},
        {"inputs": {"question": "What is the meningococcal disease rate per 100,000 in Victoria?"}, "expectations": {"expected_keywords": ["per 100,000", "population"], "question_type": "scope_boundary"}},
        {"inputs": {"question": "Does vaccination cause the decline in pertussis notifications?"}, "expectations": {"expected_keywords": ["cannot", "causal"], "question_type": "scope_boundary", "forbidden_content": ["yes, vaccination causes"]}},
        {"inputs": {"question": "What are the influenza notifications in the Sydney LGA?"}, "expectations": {"expected_keywords": ["state", "territory"], "question_type": "geographic_resolution"}},
        {"inputs": {"question": "How does NNDSS collect influenza data compared to sentinel surveillance?"}, "expectations": {"expected_keywords": ["passive", "surveillance"], "question_type": "methodology_comparison"}},
        {"inputs": {"question": "What food poisoning cases were reported in Queensland last year?"}, "expectations": {"expected_keywords": ["salmonellosis"], "question_type": "data_retrieval"}},
        {"inputs": {"question": "Should I get vaccinated against meningococcal disease based on the notification data?"}, "expectations": {"expected_keywords": ["cannot", "health advice"], "question_type": "scope_boundary", "forbidden_content": ["you should get vaccinated"]}},
        {"inputs": {"question": "Are influenza notifications increasing because of climate change?"}, "expectations": {"expected_keywords": ["cannot", "causal"], "question_type": "scope_boundary", "forbidden_content": ["climate change causes"]}},
    ]

    # Each run gets its own dataset — no mutation across runs
    from datetime import datetime
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dataset_name = f"{dataset_name}_{run_ts}"

    dataset = create_dataset(
        name=run_dataset_name,
        tags={"stage": "validation", "seeds": str(len(test_cases)), "agent": "nndss-data-agent"},
    )
    dataset = dataset.merge_records(test_cases)
    print(f"Dataset: {run_dataset_name} | {len(test_cases)} seeds | ID: {dataset.dataset_id}", flush=True)

    DatasetOutput = NamedTuple("DatasetOutput", [("experiment_name", str), ("dataset_id", str)])
    return DatasetOutput(experiment_name=experiment_name, dataset_id=dataset.dataset_id)


# =============================================================================
# Step 2b: Generate Question Variants via SDG Hub
# =============================================================================
@component(base_image=BASE_IMAGE, packages_to_install=SDG_PACKAGES)
def generate_variants_op(
    mlflow_tracking_uri: str,
    experiment_name: str,
    dataset_id: str,
    llm_base_url: str,
    gen_model: str,
    variants_per_seed: int = 3,
    mlflow_workspace: str = "",
) -> NamedTuple("GenOutput", [("experiment_name", str), ("dataset_id", str)]):
    """Generate question variants from seeds using SDG Hub."""
    import os
    import sys
    import json
    import tempfile
    from typing import NamedTuple
    from pathlib import Path

    os.environ["PYTHONUNBUFFERED"] = "1"
    sys.stdout.reconfigure(line_buffering=True)
    os.environ["MLFLOW_TRACKING_INSECURE_TLS"] = "true"

    if not os.environ.get("MLFLOW_TRACKING_TOKEN"):
        sa_token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        if sa_token_path.exists():
            os.environ["MLFLOW_TRACKING_TOKEN"] = sa_token_path.read_text().strip()

    import mlflow
    from mlflow.genai.datasets import get_dataset

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    if mlflow_workspace:
        mlflow.set_workspace(mlflow_workspace)
        import mlflow.tracking.fluent as _fluent
        client = mlflow.MlflowClient()
        exps = client.search_experiments(filter_string=f"name = '{experiment_name}'")
        if exps:
            _fluent._active_experiment_id = exps[0].experiment_id
    else:
        mlflow.set_experiment(experiment_name)

    dataset = get_dataset(dataset_id=dataset_id)
    df = dataset.to_df()
    seed_count = len(df)
    print(f"Dataset: {dataset.name} | {seed_count} seeds", flush=True)

    import pandas as pd
    seeds = []
    for _, row in df.iterrows():
        inputs = row.get("inputs", {})
        expectations = row.get("expectations", {})
        if isinstance(inputs, str):
            inputs = json.loads(inputs)
        if isinstance(expectations, str):
            expectations = json.loads(expectations)
        seeds.append({
            "question": inputs.get("question", ""),
            "question_type": expectations.get("question_type", "data_retrieval"),
            "expected_keywords": json.dumps(expectations.get("expected_keywords", [])),
        })
    seed_df = pd.DataFrame(seeds)

    # api_base must include /v1 for litellm (used by SDG Hub)
    gen_base = llm_base_url.rstrip("/")
    if not gen_base.endswith("/v1"):
        gen_base = gen_base + "/v1"
    api_key = os.environ.get("OPENAI_API_KEY", "")

    # Create SDG Hub flow and prompt files in temp directory
    work_dir = Path(tempfile.mkdtemp())
    prompts_dir = work_dir / "prompts"
    prompts_dir.mkdir()

    prompt_yaml = prompts_dir / "question_gen.yaml"
    import yaml as _yaml
    prompt_config = [
        {
            "role": "system",
            "content": (
                "You are an expert in Australian disease surveillance data. Generate evaluation "
                "questions for testing an NNDSS data agent.\n\n"
                "Available diseases: Influenza (laboratory confirmed), Invasive meningococcal "
                "disease, Invasive pneumococcal disease, Salmonellosis.\n"
                "States: ACT, NSW, NT, QLD, SA, TAS, VIC, WA.\n"
                "Data years: 2008-2025 (annual), 2024-2026 (fortnightly).\n\n"
                "Question types: data_retrieval, cross_dataset, scope_boundary, "
                "geographic_resolution, methodology_comparison."
            ),
        },
        {
            "role": "user",
            "content": (
                "{{ question_type }} question variant generation.\n\n"
                "Seed: {{ question }}\n"
                "Expected keywords: {{ expected_keywords }}\n\n"
                "Generate exactly 3 variant questions testing the same capability "
                "but with different disease, state, or year. For scope_boundary "
                "questions, create new out-of-scope questions.\n\n"
                'Respond with a JSON object containing a "variants" array. '
                'Each variant needs: "question" (string), "question_type" (string), '
                '"expected_keywords" (array of strings). No markdown, only valid JSON.'
            ),
        },
    ]
    with open(prompt_yaml, "w") as f:
        _yaml.dump(prompt_config, f, default_flow_style=False)

    flow_def = {
        "metadata": {
            "name": "NNDSS Question Variant Generator",
            "version": "1.0.0",
            "dataset_requirements": {
                "required_columns": ["question", "question_type", "expected_keywords"]
            },
        },
        "blocks": [
            {
                "block_type": "PromptBuilderBlock",
                "block_config": {
                    "block_name": "build_prompt",
                    "input_cols": {
                        "question": "question",
                        "question_type": "question_type",
                        "expected_keywords": "expected_keywords",
                    },
                    "output_cols": "gen_messages",
                    "prompt_config_path": str(prompt_yaml),
                },
            },
            {
                "block_type": "LLMChatBlock",
                "block_config": {
                    "block_name": "generate",
                    "input_cols": "gen_messages",
                    "output_cols": "gen_response",
                    "async_mode": True,
                    "temperature": 0.7,
                    "max_tokens": 1024,
                },
            },
            {
                "block_type": "LLMResponseExtractorBlock",
                "block_config": {
                    "block_name": "extract",
                    "input_cols": "gen_response",
                    "field_prefix": "gen_",
                    "extract_content": True,
                },
            },
        ],
    }
    flow_yaml_path = work_dir / "question_gen_flow.yaml"
    with open(flow_yaml_path, "w") as f:
        _yaml.dump(flow_def, f)

    all_variants = []

    try:
        from sdg_hub.core.flow import Flow
        from pydantic import SecretStr

        flow = Flow.from_yaml(str(flow_yaml_path))

        flow.set_model_config(
            model=f"openai/{gen_model}",
            api_key=SecretStr(api_key),
            api_base=gen_base,
        )

        print(f"Running SDG Hub flow with model {gen_model} via {gen_base}...", flush=True)
        result_df = flow.generate(
            seed_df,
            runtime_params={
                "generate": {
                    "api_key": SecretStr(api_key),
                    "api_base": gen_base,
                    "model": f"openai/{gen_model}",
                }
            },
            max_concurrency=2,
        )
        print(f"SDG Hub output: {len(result_df)} rows, columns: {list(result_df.columns)}", flush=True)

        content_col = None
        for col in result_df.columns:
            if "content" in col.lower():
                content_col = col
                break

        if content_col:
            for _, row in result_df.iterrows():
                try:
                    raw = row[content_col]
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                    for v in parsed.get("variants", [])[:variants_per_seed]:
                        q = v.get("question", "")
                        if q:
                            all_variants.append({
                                "inputs": {"question": q},
                                "expectations": {
                                    "expected_keywords": v.get("expected_keywords", []),
                                    "question_type": v.get("question_type", "data_retrieval"),
                                    "forbidden_content": v.get("forbidden_content", []),
                                },
                            })
                except Exception as e:
                    print(f"  Parse error: {e}", flush=True)

        print(f"Generated {len(all_variants)} variant questions via SDG Hub", flush=True)

    except Exception as e:
        print(f"SDG Hub error: {e}", flush=True)
        print("Falling back to direct HTTP generation...", flush=True)
        import httpx
        url = f"{gen_base}/chat/completions"
        for seed in seeds:
            prompt = (
                f"Generate {variants_per_seed} variant evaluation questions for an Australian disease surveillance agent.\n\n"
                f"Seed: {seed['question']}\nType: {seed['question_type']}\n\n"
                f"Change the disease, state, or year while keeping the same question type.\n\n"
                f"Respond with a JSON object containing a \"variants\" array. "
                f"Each variant needs: \"question\", \"question_type\", \"expected_keywords\". No markdown."
            )
            try:
                r = httpx.post(url, json={
                    "model": gen_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7, "max_tokens": 1024,
                }, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, timeout=30)
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                clean = content.strip()
                if clean.startswith("```"):
                    lines = clean.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    clean = "\n".join(lines)
                parsed = json.loads(clean)
                for v in parsed.get("variants", [])[:variants_per_seed]:
                    q = v.get("question", "")
                    if q:
                        all_variants.append({
                            "inputs": {"question": q},
                            "expectations": {
                                "expected_keywords": v.get("expected_keywords", []),
                                "question_type": v.get("question_type", seed["question_type"]),
                            },
                        })
            except Exception as ex:
                print(f"  HTTP error for '{seed['question'][:40]}': {ex}", flush=True)
        print(f"Generated {len(all_variants)} variant questions via HTTP fallback", flush=True)

    if all_variants:
        dataset = dataset.merge_records(all_variants)
        total = len(dataset.to_df())
        print(f"Dataset: {seed_count} seeds + {len(all_variants)} variants = {total} total", flush=True)
    else:
        print("No variants generated, using seeds only", flush=True)

    GenOutput = NamedTuple("GenOutput", [("experiment_name", str), ("dataset_id", str)])
    return GenOutput(experiment_name=experiment_name, dataset_id=dataset.dataset_id)


# =============================================================================
# Step 3: Run Evaluation
# =============================================================================
@component(base_image=BASE_IMAGE, packages_to_install=AGENT_PACKAGES)
def run_eval_op(
    mlflow_tracking_uri: str,
    experiment_name: str,
    dataset_id: str,
    llm_base_url: str,
    agent_model: str,
    judge_model: str,
    trino_host: str = "trino",
    trino_port: int = 8080,
    mlflow_workspace: str = "",
) -> dict:
    """Run NNDSS agent evaluation with 7 capability dimension scorers.

    Uses mlflow.genai.evaluate() with Guidelines scorers for each dimension
    plus deterministic scorers for basic checks.
    """
    import os
    import re
    import sys
    import json
    import warnings
    from pathlib import Path

    os.environ["PYTHONUNBUFFERED"] = "1"
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    warnings.filterwarnings("ignore")
    os.environ["MLFLOW_TRACKING_INSECURE_TLS"] = "true"
    os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = "2"
    os.environ["MLFLOW_GENAI_EVAL_MAX_SCORER_WORKERS"] = "2"
    os.environ["MLFLOW_GENAI_EVAL_MAX_RETRIES"] = "3"
    os.environ["MLFLOW_GENAI_EVAL_SKIP_TRACE_VALIDATION"] = "True"
    os.environ["TRINO_QUERY_HOST"] = trino_host
    os.environ["TRINO_QUERY_PORT"] = str(trino_port)
    # Build judge chat/completions URL from the base URL.
    # llm_base_url includes /v1 (e.g. .../gemma4/v1) — keep it.
    judge_base = llm_base_url.rstrip("/")
    judge_chat_url = judge_base + "/chat/completions"
    print(f"Judge endpoint: {judge_chat_url}")

    if not os.environ.get("MLFLOW_TRACKING_TOKEN"):
        sa_token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        if sa_token_path.exists():
            os.environ["MLFLOW_TRACKING_TOKEN"] = sa_token_path.read_text().strip()

    try:
        import nest_asyncio
        nest_asyncio.apply()
    except ImportError:
        pass

    import mlflow
    from mlflow.genai.scorers import scorer
    from mlflow.genai.datasets import get_dataset

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    if mlflow_workspace:
        mlflow.set_workspace(mlflow_workspace)
        import mlflow.tracking.fluent as _fluent
        client = mlflow.MlflowClient()
        exps = client.search_experiments(filter_string=f"name = '{experiment_name}'")
        if exps:
            _fluent._active_experiment_id = exps[0].experiment_id
    else:
        mlflow.set_experiment(experiment_name)

    # -------------------------------------------------------------------------
    # Deterministic scorers
    # -------------------------------------------------------------------------
    @scorer
    def contains_expected(inputs: dict, outputs: str, expectations: dict) -> bool:
        keywords = expectations.get("expected_keywords", [])
        if not keywords:
            return True
        out = str(outputs).lower()
        return any(kw.lower() in out for kw in keywords)

    @scorer
    def no_forbidden_content(inputs: dict, outputs: str, expectations: dict) -> bool:
        forbidden = expectations.get("forbidden_content", [])
        if not forbidden:
            return True
        out = str(outputs).lower()
        return not any(f.lower() in out for f in forbidden)

    @scorer
    def confidence_card_present(outputs: str) -> bool:
        return "data confidence" in str(outputs).lower()

    @scorer
    def response_adequate_length(outputs: str) -> float:
        return 1.0 if len(str(outputs)) >= 100 else 0.5

    # -------------------------------------------------------------------------
    # LLM-as-Judge scorers (7 capability dimensions)
    # Custom @scorer functions calling the judge LLM via HTTP.
    # Returns bool for numeric metric aggregation.
    # -------------------------------------------------------------------------
    import httpx

    api_key = os.environ.get("OPENAI_API_KEY", "")
    print(f"Judge model: {judge_model} via {judge_chat_url}", flush=True)

    def _call_judge(question: str, response: str, criterion: str) -> bool:
        prompt = (
            f"Question: {question}\nResponse: {response}\n\n"
            f"{criterion}\n\n"
            "Reply with only YES or NO."
        )
        try:
            r = httpx.post(
                judge_chat_url,
                json={
                    "model": judge_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 10,
                    "temperature": 0,
                },
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                timeout=30,
            )
            r.raise_for_status()
            answer = r.json()["choices"][0]["message"]["content"].strip().upper()
            return answer.startswith("YES")
        except Exception as e:
            print(f"  Judge error: {e}", flush=True)
            return False

    @scorer
    def cross_dataset_reasoning(inputs: dict, outputs: str) -> bool:
        return _call_judge(str(inputs), str(outputs),
            "Does the response state which dataset or table was used and why?")

    @scorer
    def methodology_awareness(inputs: dict, outputs: str) -> bool:
        return _call_judge(str(inputs), str(outputs),
            "Does the response describe the data collection methodology "
            "(passive surveillance, laboratory-confirmed notifications, under-reporting)?")

    @scorer
    def scope_adherence(inputs: dict, outputs: str) -> bool:
        return _call_judge(str(inputs), str(outputs),
            "Does the response stay within the scope of notification data "
            "and avoid making causal claims or providing health advice?")

    @scorer
    def causal_inference_boundaries(inputs: dict, outputs: str) -> bool:
        return _call_judge(str(inputs), str(outputs),
            "Does the response correctly avoid causal claims from "
            "observational surveillance data?")

    @scorer
    def geographic_resolution(inputs: dict, outputs: str) -> bool:
        return _call_judge(str(inputs), str(outputs),
            "Does the response correctly state the geographic resolution "
            "(state/territory level) and explain limitations if finer resolution is requested?")

    @scorer
    def terminology_fluency(inputs: dict, outputs: str) -> bool:
        return _call_judge(str(inputs), str(outputs),
            "Are lay terms correctly mapped to NNDSS indicators "
            "(e.g., 'food poisoning' -> Salmonellosis, 'flu' -> Influenza)?")

    @scorer
    def confidence_calibration(inputs: dict, outputs: str) -> bool:
        return _call_judge(str(inputs), str(outputs),
            "Does the response include a Data Confidence level "
            "(HIGH/MODERATE/LOW) that reflects what data was actually retrieved?")

    capability_scorers = [
        cross_dataset_reasoning, methodology_awareness, scope_adherence,
        causal_inference_boundaries, geographic_resolution,
        terminology_fluency, confidence_calibration,
    ]

    all_scorers = [
        contains_expected, no_forbidden_content,
        confidence_card_present, response_adequate_length,
    ] + capability_scorers

    # -------------------------------------------------------------------------
    # Predictor — invokes the LangGraph agent directly
    # -------------------------------------------------------------------------
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent
    from langchain_core.messages import HumanMessage

    # Import tools
    from trino.dbapi import connect as trino_connect

    # Inline tool definitions (simplified for pipeline pod)
    from langchain_core.tools import tool

    BLOCKED_SQL = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE)\b", re.IGNORECASE)

    @tool
    def query_trino(sql: str) -> str:
        """Execute a read-only SQL query against NNDSS Iceberg lakehouse in Trino.
        Tables: lakehouse.nndss.notifications (year, state, disease, notifications),
        lakehouse.nndss.population (year, state, population).
        Only SELECT allowed."""
        if BLOCKED_SQL.search(sql):
            return json.dumps({"error": "Only SELECT queries allowed."})
        try:
            conn = trino_connect(host=trino_host, port=trino_port, user="admin", catalog="lakehouse", schema="nndss")
            cur = conn.cursor()
            cur.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(500)
            conn.close()
            return json.dumps({"results": [dict(zip(columns, r)) for r in rows], "row_count": len(rows)})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @tool
    def describe_datasets(topic: str = "") -> str:
        """List available NNDSS datasets."""
        return json.dumps({"datasets": [
            {"name": "Influenza (laboratory confirmed)", "years": "2008-2025"},
            {"name": "Invasive meningococcal disease", "years": "2009-2024"},
            {"name": "Invasive pneumococcal disease", "years": "2009-2024"},
            {"name": "Salmonellosis", "years": "2009-2025"},
        ]})

    @tool
    def get_methodology(dataset_name: str) -> str:
        """Get methodology for a specific NNDSS dataset."""
        return json.dumps({"surveillance_type": "Passive", "collection_design": "Lab/clinician notifications"})

    # Agent uses its own model endpoint (not the judge endpoint)
    agent_base_url = llm_base_url.replace(f"/{judge_model}", f"/{agent_model}")
    if not agent_base_url.endswith("/v1"):
        agent_base_url = agent_base_url + "/v1"
    print(f"Agent model: {agent_model} via {agent_base_url}")

    agent_llm = ChatOpenAI(
        model=agent_model, base_url=agent_base_url,
        api_key=os.environ.get("OPENAI_API_KEY", "x"),
        temperature=0.3, max_tokens=4096, streaming=False,
        model_kwargs={"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
    )
    # Load prompt from MLflow registry — links eval run to prompt version
    prompt_name = "nndss-agent.system"
    system_prompt = None
    prompt_version = "unknown"
    try:
        prompt_obj = mlflow.genai.load_prompt(
            f"prompts:/{prompt_name}@production",
            allow_missing=True,
        )
        if prompt_obj:
            system_prompt = prompt_obj.template
            prompt_version = str(prompt_obj.version)
            print(f"Loaded prompt: {prompt_name} v{prompt_version} ({len(system_prompt)} chars)", flush=True)
            mlflow.log_param("prompt_name", prompt_name)
            mlflow.log_param("prompt_version", prompt_version)
    except Exception as e:
        print(f"Could not load prompt from MLflow: {e}", flush=True)

    if not system_prompt:
        print("Using fallback prompt (not registered in MLflow)", flush=True)
        system_prompt = (
            "You are an Australian disease surveillance data agent. "
            "Use query_trino to execute SQL against the NNDSS Iceberg lakehouse. "
            "Table: lakehouse.nndss.notifications (year INT, state VARCHAR, disease VARCHAR, notifications INT). "
            "Diseases: 'Influenza (laboratory confirmed)', 'Invasive meningococcal disease', 'Invasive pneumococcal disease', 'Salmonellosis'. "
            "Table: lakehouse.nndss.population (year INT, state VARCHAR, population INT) for per-capita rates. "
            "Always include Data Confidence (HIGH/MODERATE/LOW) and Data Freshness in your response. "
            "Notifications are laboratory-confirmed cases from passive surveillance, not total infections."
        )

    agent = create_react_agent(
        model=agent_llm,
        tools=[query_trino, describe_datasets, get_methodology],
        prompt=system_prompt,
    )

    _q_count = [0]

    def predict_fn(question: str) -> str:
        _q_count[0] += 1
        print(f"[predict {_q_count[0]}] Q: {question[:80]}...", flush=True)
        try:
            with mlflow.start_span(name="nndss_agent_eval") as span:
                span.set_inputs({"question": question[:200]})
                mlflow.genai.load_prompt(
                    f"prompts:/{prompt_name}@production",
                    allow_missing=True,
                    cache_ttl_seconds=300,
                )
                result = agent.invoke({"messages": [HumanMessage(content=question)]})
                for m in reversed(result.get("messages", [])):
                    if hasattr(m, "type") and m.type == "ai" and not getattr(m, "tool_calls", None):
                        answer = m.content or ""
                        span.set_outputs({"answer_length": len(answer)})
                        print(f"[predict {_q_count[0]}] A: {len(answer)} chars", flush=True)
                        return answer
            print(f"[predict {_q_count[0]}] No AI response found", flush=True)
            return "No response"
        except Exception as e:
            print(f"[predict {_q_count[0]}] Error: {e}", flush=True)
            return f"Error: {e}"

    # -------------------------------------------------------------------------
    # Run evaluation
    # -------------------------------------------------------------------------
    dataset = get_dataset(dataset_id=dataset_id)
    print(f"Dataset: {dataset.name} | Records: {len(dataset.to_df())}", flush=True)
    print(f"Scorers: {len(all_scorers)} (4 deterministic + {len(capability_scorers)} LLM judges)", flush=True)

    print("Starting mlflow.genai.evaluate()...", flush=True)
    result = mlflow.genai.evaluate(
        data=dataset,
        predict_fn=predict_fn,
        scorers=all_scorers,
    )
    print("Evaluation complete.", flush=True)

    metrics = {}
    if hasattr(result, "metrics") and result.metrics:
        for k, v in result.metrics.items():
            metrics[k] = round(v, 4) if isinstance(v, float) else v

    print(f"\nResults: {metrics}")
    return metrics


# =============================================================================
# Step 4: Report Results
# =============================================================================
@component(base_image=BASE_IMAGE, packages_to_install=["pydantic>=2.0.0"])
def report_results_op(metrics: dict, mlflow_tracking_uri: str) -> str:
    """Print evaluation scorecard."""
    print("=" * 60)
    print("NNDSS HEALTH AGENT EVALUATION REPORT")
    print("=" * 60)
    for k, v in sorted(metrics.items()):
        if isinstance(v, float):
            print(f"  {k}: {v:.2%}")
        else:
            print(f"  {k}: {v}")
    print(f"\nView in MLflow: {mlflow_tracking_uri}")
    return f"Evaluation complete. {len(metrics)} metrics. View at {mlflow_tracking_uri}"


# =============================================================================
# Pipeline Definition
# =============================================================================
@dsl.pipeline(
    name="NNDSS Health Agent Evaluation",
    description="Evaluate NNDSS agent on 7 capability dimensions using LLM-as-judge"
)
def nndss_eval_pipeline(
    mlflow_tracking_uri: str = "https://mlflow.redhat-ods-applications.svc:8443/mlflow",
    mlflow_workspace: str = "nndss-agent",
    mlflow_experiment_name: str = "nndss-data-agent",
    dataset_name: str = "nndss_health_eval",
    llm_base_url: str = "http://maas.apps.ocp.cloud.rhai-tmm.dev/prelude-maas/gemma4/v1",
    agent_model: str = "qwen36-27b",
    judge_model: str = "gemma4",
    trino_host: str = "trino.nndss-agent.svc.cluster.local",
    trino_port: int = 8080,
    llm_secret_name: str = "nndss-agent-maas-key",
):
    # Step 1
    setup = setup_mlflow_op(
        mlflow_tracking_uri=mlflow_tracking_uri,
        mlflow_experiment_name=mlflow_experiment_name,
        mlflow_workspace=mlflow_workspace,
    )

    # Step 2
    dataset = create_dataset_op(
        mlflow_tracking_uri=mlflow_tracking_uri,
        experiment_name=setup.output,
        dataset_name=dataset_name,
        mlflow_workspace=mlflow_workspace,
    )

    # Step 2b — SDG Hub question variant generation
    sdg_task = generate_variants_op(
        mlflow_tracking_uri=mlflow_tracking_uri,
        experiment_name=dataset.outputs["experiment_name"],
        dataset_id=dataset.outputs["dataset_id"],
        llm_base_url=llm_base_url,
        gen_model=judge_model,
        variants_per_seed=3,
        mlflow_workspace=mlflow_workspace,
    )
    sdg_task.set_caching_options(False)
    kubernetes.use_secret_as_env(
        sdg_task,
        secret_name=llm_secret_name,
        secret_key_to_env={"api-key": "OPENAI_API_KEY"},
    )

    # Step 3 — caching disabled: prompt loads from MLflow at runtime
    eval_task = run_eval_op(
        mlflow_tracking_uri=mlflow_tracking_uri,
        experiment_name=sdg_task.outputs["experiment_name"],
        dataset_id=sdg_task.outputs["dataset_id"],
        llm_base_url=llm_base_url,
        agent_model=agent_model,
        judge_model=judge_model,
        trino_host=trino_host,
        trino_port=trino_port,
        mlflow_workspace=mlflow_workspace,
    )
    eval_task.set_caching_options(False)
    kubernetes.use_secret_as_env(
        eval_task,
        secret_name=llm_secret_name,
        secret_key_to_env={"api-key": "OPENAI_API_KEY"},
    )

    # Step 4
    report_results_op(
        metrics=eval_task.output,
        mlflow_tracking_uri=mlflow_tracking_uri,
    )


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="NNDSS Eval Pipeline")
    parser.add_argument("--compile", action="store_true", help="Compile to YAML")
    parser.add_argument("--output-dir", default="pipelines_gen")
    args = parser.parse_args()

    if args.compile:
        from kfp import compiler

        script_dir = Path(__file__).parent
        output_dir = script_dir / args.output_dir
        output_dir.mkdir(exist_ok=True)

        output_file = output_dir / "nndss-eval-pipeline.yaml"
        compiler.Compiler().compile(
            pipeline_func=nndss_eval_pipeline,
            package_path=str(output_file),
        )
        print(f"Pipeline compiled to: {output_file}")
    else:
        print("Usage: python evaluations/pipeline.py --compile")
