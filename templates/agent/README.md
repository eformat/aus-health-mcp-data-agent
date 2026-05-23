# Agent Template

These files are **overlays**, not a standalone project. The agent
framework (`BaseAgent`, `StepResult`, the OpenAI-compatible HTTP server,
the Helm chart, and the tool/prompt/skill discovery system) is provided
by the fips-agents scaffold. You must scaffold first, then copy these
files in.

## Steps

### 1. Scaffold the agent

```bash
fips-agents create agent my-agent --local
cd my-agent
make install
```

This gives you a complete project with `src/agent.py`, `agent.yaml`,
`prompts/system.md`, `chart/`, `Containerfile`, `Makefile`, tests, and
all framework dependencies installed.

### 2. Replace the scaffolded files with these templates

```bash
# System prompt — replace the generic scaffold prompt with the
# 6-step reasoning protocol. Edit the {DOMAIN}, tool names, and
# topic lists to match your domain.
cp /path/to/templates/agent/prompts/system.md prompts/system.md

# Agent code — adds the tool-call insistor, the two-call reasoning
# rubric injector, and the programmatic confidence card. Review and
# adjust the tool names in _TOOL_INSIST_MSG.
cp /path/to/templates/agent/src/agent.py src/agent.py

# Agent config — update the model endpoint, model name, and MCP
# server URL to match your deployment.
cp /path/to/templates/agent/agent.yaml agent.yaml
```

### 3. Customize

- **`prompts/system.md`**: Replace `{DOMAIN}` placeholders with your
  domain. Update the tool descriptions and available-topics list to
  match your MCP server's tools. Adjust the 6-step reasoning protocol
  if some considerations don't apply to your domain.

- **`src/agent.py`**: Update the tool names in `_TOOL_INSIST_MSG` to
  match your MCP server's tool names. The `ReasoningRubric` Pydantic
  model, the rubric injector, the confidence card builder, and the
  insistor are domain-neutral and work as-is.

- **`agent.yaml`**: Set your model endpoint and MCP server URL. The
  `${VAR:-default}` substitution pattern lets you override via
  environment variables at deploy time without changing the file.

### 4. Test locally

```bash
make run-local
# In another terminal:
curl localhost:8080/healthz
curl localhost:8080/v1/agent-info | python -m json.tool
```

### 5. Deploy

```bash
make deploy PROJECT=my-namespace
```

See the fips-agents [agent template documentation](https://github.com/fips-agents/agent-template)
for the full deployment workflow, including container builds, Helm
charts, and OpenShift deployment.

## What these files add beyond the scaffold

| File | What it adds |
|------|-------------|
| `prompts/system.md` | The 6-step reasoning protocol, structured output format (reasoning block + confidence card + data freshness), and chart rendering instructions |
| `src/agent.py` | Tool-call insistor (rejects answers without tool use), two-call reasoning rubric injection, and programmatic confidence card computed from the tool trace |
| `agent.yaml` | MCP server connection config and parameterized model endpoint |

## Model-specific workarounds

Some models require additional workarounds in `src/agent.py`:

- **vLLM streaming harmony bug** (gpt-oss models): Override
  `call_model_stream_raw` to use non-streaming calls. See the
  fips-agents docs for the pattern.
- **Implicit-open `<think>` tags** (Nemotron models): Override
  `self._reasoning_parser` in `setup()` with a parser that starts
  in the thinking state. See fips-agents/agent-template#177.

These are not included in the template because they are
model-specific, not domain-specific.
