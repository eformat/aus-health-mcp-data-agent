"""Capability Evaluation Pipeline (KFP).

Runs an agent against a question corpus, judges responses on 7 capability
dimensions, and produces a per-capability scorecard.

Pipeline stages:
  1. Load questions (from PVC)
  2. Run agent (MCP server via MCPAgentBlock)
  3. Triage (extract reasoning, answer, tool interactions)
  4. Merge with gold standards (inject expected reasoning + criteria)
  5. Capability judge (7 dimensions)
  6. Summary (per-capability scores)

Usage:
    python pipeline.py
"""

from kfp import dsl, compiler
from kfp.kubernetes import (
    use_config_map_as_volume,
    use_secret_as_env,
    mount_pvc,
)

from components import load_questions, triage, merge_gold_standards, summary


# -- Replace these with your actual endpoints -------------------------------- #

# YOUR_MCP_SERVER_URL: The MCP server URL your agent connects to.
# YOUR_MODEL_ENDPOINT: The OpenAI-compatible model endpoint (e.g., vLLM).
# These are defaults; override via pipeline parameters at submission time.

DEFAULT_MCP_SERVER_URL = "YOUR_MCP_SERVER_URL"
DEFAULT_MODEL_ENDPOINT = "YOUR_MODEL_ENDPOINT"


# -- Reusable SDG Hub flow runner -------------------------------------------- #

@dsl.component(
    base_image="python:3.11-slim",
    packages_to_install=["sdg-hub>=0.7.0,<1.0", "pandas>=2.0"],
)
def sdg_flow(
    output_artifact: dsl.Output[dsl.Dataset],
    input_artifact: dsl.Input[dsl.Dataset],
    flow_yaml_path: str = "",
    model: str = "",
    max_concurrency: int = 4,
    checkpoint_pvc_path: str = "",
    save_freq: int = 50,
    runtime_params: dict = None,
):
    """Run an SDG Hub flow as a KFP component."""
    import os
    import time

    import pandas as pd
    from sdg_hub.core.flow import Flow

    api_key_val = os.environ.get("LLM_API_KEY", "")
    if api_key_val and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = api_key_val

    df = pd.read_json(input_artifact.path, lines=True)
    print(f"Input: {len(df)} rows")

    if len(df) == 0:
        print("Empty input -- writing empty output and skipping flow execution")
        df.to_json(
            output_artifact.path, orient="records", lines=True, force_ascii=False
        )
        return

    flow = Flow.from_yaml(flow_yaml_path)

    api_key = os.environ.get("LLM_API_KEY", "")
    api_base = os.environ.get("LLM_API_BASE", "")

    if flow.is_model_config_required() and model:
        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base
        flow.set_model_config(model=model, **kwargs)

    if runtime_params:
        from pydantic import SecretStr
        for block_name, params in runtime_params.items():
            if api_key and "api_key" not in params:
                params["api_key"] = SecretStr(api_key)
            if api_base and "api_base" not in params:
                params["api_base"] = api_base

    generate_kwargs = {"max_concurrency": max_concurrency}
    if checkpoint_pvc_path:
        generate_kwargs["checkpoint_dir"] = checkpoint_pvc_path
        generate_kwargs["save_freq"] = save_freq
    if runtime_params:
        generate_kwargs["runtime_params"] = runtime_params

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            result = flow.generate(df, **generate_kwargs)
            break
        except Exception as e:
            err = str(e).lower()
            transient = (
                "connection" in err
                or "timeout" in err
                or "502" in err
                or "503" in err
                or "504" in err
            )
            if transient and attempt < max_retries:
                wait = 30 * (2 ** (attempt - 1))
                print(f"Transient error on attempt {attempt}/{max_retries}: {e}")
                print(f"Retrying in {wait}s (checkpoints preserved)...")
                time.sleep(wait)
                flow = Flow.from_yaml(flow_yaml_path)
                if flow.is_model_config_required() and model:
                    kwargs = {}
                    if api_key:
                        kwargs["api_key"] = api_key
                    if api_base:
                        kwargs["api_base"] = api_base
                    flow.set_model_config(model=model, **kwargs)
            else:
                raise

    result.to_json(
        output_artifact.path, orient="records", lines=True, force_ascii=False
    )
    print(f"Output: {len(result)} rows, {len(result.columns)} columns")


# -- Pipeline ---------------------------------------------------------------- #

@dsl.pipeline(
    name="capability-eval",
    description=(
        "Capability evaluation pipeline. Runs agent against an MCP server, "
        "judges on 7 capability dimensions, and reports per-capability scores."
    ),
)
def eval_pipeline(
    limit: int = 0,
    run_name: str = "eval-run",
    input_file: str = "questions.jsonl",
    agent_model: str = "openai/your-model-id",
    agent_api_base: str = "",
    agent_max_concurrency: int = 1,
    judge_max_concurrency: int = 2,
):
    # --- Stage 1: Load questions ---
    load_task = load_questions(
        input_path=f"/mnt/eval-data/input/{input_file}",
        limit=limit,
    )
    load_task.set_caching_options(False)
    mount_pvc(load_task, pvc_name="eval-data", mount_path="/mnt/eval-data")

    # --- Stage 2: Run agent ---
    agent_task = sdg_flow(
        input_artifact=load_task.outputs["output_data"],
        flow_yaml_path="/mnt/eval-flows/agent_flow.yaml",
        model="",
        max_concurrency=agent_max_concurrency,
        checkpoint_pvc_path="/mnt/eval-data/checkpoints/agent",
        save_freq=5,
        runtime_params={
            "data_agent": {
                "model": agent_model,
                "api_base": agent_api_base or DEFAULT_MODEL_ENDPOINT,
                "mcp_server_url": DEFAULT_MCP_SERVER_URL,
            }
        },
    )
    use_config_map_as_volume(
        agent_task, config_map_name="eval-flows", mount_path="/mnt/eval-flows"
    )
    use_config_map_as_volume(
        agent_task,
        config_map_name="eval-prompts",
        mount_path="/mnt/eval-flows/prompts",
    )
    mount_pvc(agent_task, pvc_name="eval-data", mount_path="/mnt/eval-data")
    use_secret_as_env(
        agent_task,
        secret_name="llm-credentials",
        secret_key_to_env={
            "api_key": "LLM_API_KEY",
            "api_base": "LLM_API_BASE",
            "mcp_server_url": "MCP_SERVER_URL",
        },
    )
    agent_task.set_retry(
        num_retries=3, backoff_duration="30s", backoff_factor=2.0
    )
    agent_task.set_caching_options(False)

    # --- Stage 3: Triage ---
    triage_task = triage(input_data=agent_task.outputs["output_artifact"])
    triage_task.set_caching_options(False)

    # --- Stage 4: Merge with gold standards ---
    merge_task = merge_gold_standards(
        triaged_data=triage_task.outputs["output_data"],
        gold_standards_dir="/mnt/eval-gold-standards",
    )
    use_config_map_as_volume(
        merge_task,
        config_map_name="eval-gold-standards",
        mount_path="/mnt/eval-gold-standards",
    )
    merge_task.set_caching_options(False)

    # --- Stage 5: Capability judge ---
    # NOTE: The judge model is intentionally NOT parameterised. Keep it
    # pinned to the same checkpoint across A/B runs so scores remain
    # comparable. Only the agent model should vary between runs.
    judge_task = sdg_flow(
        input_artifact=merge_task.outputs["output_data"],
        flow_yaml_path="/mnt/eval-flows/capability_judge_flow.yaml",
        model="openai/your-judge-model-id",
        max_concurrency=judge_max_concurrency,
        checkpoint_pvc_path="",
        save_freq=50,
    )
    use_config_map_as_volume(
        judge_task, config_map_name="eval-flows", mount_path="/mnt/eval-flows"
    )
    use_config_map_as_volume(
        judge_task,
        config_map_name="eval-prompts",
        mount_path="/mnt/eval-flows/prompts",
    )
    use_secret_as_env(
        judge_task,
        secret_name="llm-credentials",
        secret_key_to_env={
            "api_key": "LLM_API_KEY",
            "api_base": "LLM_API_BASE",
        },
    )
    judge_task.set_retry(
        num_retries=3, backoff_duration="30s", backoff_factor=2.0
    )
    judge_task.set_caching_options(False)

    # --- Stage 6: Summary ---
    summary_task = summary(  # noqa: F841
        judged_data=judge_task.outputs["output_artifact"],
        triaged_data=triage_task.outputs["output_data"],
        run_name=run_name,
    )
    summary_task.set_caching_options(False)


if __name__ == "__main__":
    from pathlib import Path

    output = Path(__file__).parent / "eval_pipeline.yaml"
    compiler.Compiler().compile(eval_pipeline, str(output))
    print(f"Compiled to {output}")
