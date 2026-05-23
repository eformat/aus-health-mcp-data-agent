# Architecture

## Component Diagram

```
                                    Eval Pipeline (KFP)
                                    +------------------+
                                    | load_questions   |
                                    | run_agent -------+-----+
                                    | triage           |     |
                                    | merge_gold_stds  |     |
                                    | capability_judge |     |
                                    | summary          |     |
                                    +------------------+     |
                                                             |
  +------+     +--------+     +---------+     +-------+      |
  | User | --> | Chat   | --> | Agent   | --> | MCP   |  <---+
  |      |     | UI     |     | Server  |     | Server|
  +------+     +--------+     +---------+     +-------+
                                  |               |
                                  |  6-step       |  Enriched
                                  |  reasoning    |  tool
                                  |  protocol     |  responses
                                  |               |
                              +---------+     +---------+
                              | vLLM    |     | Domain  |
                              | Model   |     | Data    |
                              | Endpoint|     | Sources |
                              +---------+     +---------+
```

## Components

### MCP Server

The domain data gateway. Each tool enriches its response with methodology context, geographic scope, cross-dataset comparisons, and data freshness metadata. Scaffold with `fips-agents create mcp-server your-server-name`, then add tools following the enrichment pattern in `templates/mcp-server/example-tool.py`.

The MCP server uses streamable-http transport and exposes tools that the agent (or the eval pipeline's MCPAgentBlock) discovers at runtime via the MCP protocol.

### Agent Server

An OpenAI-compatible HTTP server (`/v1/chat/completions`) built on the BaseAgent framework. The agent subclass adds two post-processing layers on top of the base framework:

1. A **tool-call insistor** that retries when the model skips tool calls (ensuring every answer is grounded in retrieved data)
2. A **reasoning rubric injector** that makes a second structured-output call to produce the 6-step `<reasoning>` block, plus a deterministic confidence card

Scaffold with `fips-agents create agent your-agent-name`, then customize `src/agent.py` with the patterns from `templates/agent/src/agent.py`.

### Chat UI

Any OpenAI-compatible chat frontend. The agent exposes `/v1/chat/completions` with streaming support. The `<reasoning>` block and confidence card are emitted as part of the content stream; your UI can parse the `<reasoning>...</reasoning>` tags into collapsible cards if desired.

### vLLM Model Endpoint

Any OpenAI-compatible LLM endpoint. The templates use `${MODEL_ENDPOINT}` and `${MODEL_NAME}` placeholders. vLLM is recommended for self-hosted models because it supports structured output (JSON mode) needed by the rubric injection call.

### Evaluation Pipeline

A Kubeflow Pipelines DAG that runs the agent against a question corpus and scores responses on 7 capability dimensions. The pipeline is a parallel track -- it doesn't modify the production agent, it evaluates it. See `templates/eval-pipeline/pipeline.py` for the full DAG.

## Deployment

The MCP server, agent server, and model endpoint each deploy as separate pods. The evaluation pipeline runs on a KFP instance (OpenShift AI or standalone). All components communicate via HTTP.

For scaffolding, the `fips-agents` CLI generates Helm charts for each component. The typical deployment sequence:

1. Deploy the model endpoint (vLLM `InferenceService` or standalone pod)
2. Deploy the MCP server (`fips-agents create mcp-server` + `make deploy`)
3. Deploy the agent server (`fips-agents create agent` + `make deploy`)
4. Configure the eval pipeline with the agent and model endpoints, compile, and submit to KFP
