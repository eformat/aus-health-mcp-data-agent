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

## Documentation

- [Reasoning Protocol](docs/reasoning-protocol.md) -- How to apply the 6-step protocol to your domain
- [Evaluation Methodology](docs/evaluation-methodology.md) -- The 7-dimension capability judge explained
- [Architecture](docs/architecture.md) -- Component diagram and deployment overview

## License

Apache 2.0. See [LICENSE](LICENSE).
