# MCP for Public Health

A framework for building evaluated, methodology-aware public health data agents using MCP (Model Context Protocol) servers. This project provides templates and patterns for creating agents that don't just retrieve data, but reason about its methodology, scope, and limitations before answering.

## The Three Layers

**1. MCP Server** -- A tool server that enriches every data response with methodology context, geographic scope, cross-dataset comparisons, and supported/unsupported conclusions alongside the raw data. Templates in `templates/mcp-server/`.

**2. Agent with Reasoning Protocol** -- An agent that uses a structured 6-step reasoning protocol before answering any data question: cross-dataset reasoning, methodology awareness, scope adherence, causal inference boundaries, geographic resolution knowledge, and terminology fluency. Templates in `templates/agent/`.

**3. Evaluation Pipeline** -- A KFP (Kubeflow Pipelines) evaluation pipeline that scores agent responses on 7 capability dimensions using an LLM-as-judge, with gold standard comparisons. Templates in `templates/eval-pipeline/`.

## Prerequisites

- [fips-agents CLI](https://github.com/fips-agents/agent-template) for scaffolding agents
- An OpenShift cluster with OpenShift AI (or any Kubernetes cluster with KFP)
- A vLLM-served model (or any OpenAI-compatible endpoint)
- Python 3.11+

## Quick Start

1. **Scaffold your MCP server**: `fips-agents create mcp-server your-domain-server`. Add tools following the enrichment pattern in `templates/mcp-server/example-tool.py`.

2. **Customize the agent prompt**: Copy `templates/agent/prompts/system.md`, replace `{DOMAIN}` with your domain, and update the tool descriptions and reasoning examples.

3. **Write seed questions and gold standards**: Use `templates/eval-pipeline/questions/seed-template.yaml` and `templates/eval-pipeline/gold-standards/example-seed.yaml` as starting points.

4. **Run the eval pipeline**: Adapt `templates/eval-pipeline/pipeline.py` with your model endpoint and MCP server URL, compile with `python pipeline.py`, and submit to your KFP instance.

## NNDSS Health Agent

A deployed implementation targeting Australian NNDSS disease surveillance data. LangChain/LangGraph agent with Chainlit UI, Trino Iceberg lakehouse, MLflow tracing, and automated evaluation.

### Make Targets

```bash
make help                # Show all targets
```

**Build & Push**

```bash
make build               # Build agent container image
make push                # Push to quay.io/eformat
```

**Prompts**

```bash
make register-prompt PROMPT_MSG="v4: changes"   # Register system_prompt.md in MLflow, set @production alias
```

**Deployment**

```bash
make deploy-all          # Full deployment: MinIO -> Trino -> Agent -> DSPA -> Eval
make set-model AGENT_MODEL=kimi-k2-6   # Switch agent model
```

After switching models, redeploy:

```bash
oc apply -k agents/nndss-agent/deploy -n nndss-agent
```

**SpiceDB (Authorization)**

```bash
make spicedb-schema                                          # Write schema to SpiceDB
make spicedb-seed                                            # Seed test users and relationships
make spicedb-check USER=admin PERM=query DATASET=notifications  # Check a permission
```

**Evaluation**

```bash
make eval-compile        # Compile KFP pipeline to YAML
make eval-submit         # Compile + upload + submit pipeline run
make eval-status         # Check latest pipeline run statuses
```

The eval pipeline:
1. Creates a timestamped MLflow dataset (20 seed questions)
2. Generates ~60 variant questions via SDG Hub
3. Runs the agent against all ~80 questions
4. Scores responses with 11 scorers (4 deterministic + 7 LLM-as-judge)
5. Logs results to MLflow with linked prompt version

### Project Structure

```
agents/nndss-agent/          # LangChain + Chainlit agent
  app.py                     # Main application
  tools.py                   # query_trino, describe_datasets, get_methodology, check_dataset_permission
  system_prompt.md           # Versioned prompt (registered in MLflow)
  spicedb/                   # SpiceDB schema and relationship seeder
  deploy/                    # OpenShift deployment manifests

agents/nndss-mcp-server/     # MCP server with NNDSS data

evaluations/
  pipeline.py                # KFP pipeline definition
  flows/                     # SDG Hub question generation flow
  prompts/                   # SDG Hub prompt templates

deploy/                      # Infrastructure (MinIO, Trino, DSPA, RBAC)
scripts/                     # Deployment and evaluation scripts
```

## Documentation

- [Reasoning Protocol](docs/reasoning-protocol.md) -- How to apply the 6-step protocol to your domain
- [Evaluation Methodology](docs/evaluation-methodology.md) -- The 7-dimension capability judge explained
- [Architecture](docs/architecture.md) -- Component diagram and deployment overview

## License

Apache 2.0. See [LICENSE](LICENSE).
