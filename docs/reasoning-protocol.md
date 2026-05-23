# Reasoning Protocol: Applying Structured Reasoning to Your Domain

Public health data is only useful if consumers understand what it can and cannot say. Raw numbers stripped of methodology, scope, and geographic context are dangerous -- they invite misinterpretation. This reasoning protocol ensures that every agent response demonstrates the epistemological discipline required to interpret public health data responsibly.

The protocol consists of six considerations. Not every consideration applies to every question, but the agent must demonstrate reasoning for every one that does. The key insight: **a thoughtful response that honestly acknowledges limitations is more valuable than a confident answer built on unexamined assumptions.**

## The Six Considerations

### 1. Cross-Dataset Reasoning

**What it checks**: Which dataset(s) the agent selected and why, including what alternatives were considered and rejected.

**Why it matters**: Public health domains typically have multiple overlapping data sources -- national surveys, state-level administrative data, county-level modeled estimates. Each covers different populations, uses different methodologies, and measures slightly different things. Choosing the wrong source silently corrupts the answer.

**How to customize**: Enumerate your domain's data sources and their key differentiators. For an environmental monitoring agent, this might be: "EPA AQS provides hourly readings from fixed monitoring stations (regulatory-grade, sparse coverage), PurpleAir provides real-time PM2.5 from consumer sensors (dense coverage, lower accuracy), and satellite-derived AOD provides complete spatial coverage but requires model calibration and has coarser temporal resolution."

**This consideration is never N/A.** Every data query involves a dataset choice, even when the choice seems obvious. Stating the choice and the reasoning makes the decision auditable.

### 2. Methodology Awareness

**What it checks**: Whether the agent understands how the data was collected and how that affects interpretation.

**Why it matters**: Self-reported survey data, direct measurements, and modeled estimates all have different error profiles. An agent that presents modeled county estimates as equivalent to direct measurements misleads users about the data's reliability.

**How to customize**: For each data source, document: sampling design (probability sample vs. convenience sample), collection mode (telephone, in-person, sensor, satellite), population coverage (who is included and excluded), and known biases. Your MCP server should return methodology metadata alongside the data; the agent prompt should require the agent to review it before answering. Example: "AQS monitors are sited according to EPA criteria -- they over-represent populated areas and may miss pollution hotspots in industrial zones."

### 3. Scope Adherence

**What it checks**: Whether the agent stays within what the data can actually answer, and explicitly declines questions that require evidence the data cannot provide.

**Why it matters**: Monitoring data can show levels and trends. It cannot establish health effects, predict future conditions, or make policy recommendations. An agent that answers "is the air safe to breathe?" from AQI readings alone is overstepping -- that question requires exposure duration, population vulnerability, and health threshold context that monitoring data alone doesn't provide.

**How to customize**: Define your domain's scope boundaries clearly. What CAN the data show? (Levels, trends, spatial patterns, temporal patterns, exceedances.) What can't it show? (Causation, health effects, predictions, policy recommendations.) Include these boundaries in your system prompt and have the agent acknowledge them when a question approaches the edge.

### 4. Causal Inference Boundaries

**What it checks**: Whether the agent correctly handles questions that imply causation.

**Why it matters**: Observational data shows correlations and co-occurrences, not causes. An environmental monitoring agent asked "does the factory cause the high PM2.5 readings?" cannot answer from monitoring data alone -- that requires source apportionment studies, dispersion modeling, or controlled experiments.

**How to customize**: Identify the study designs your data sources represent (observational monitoring, cross-sectional surveys, longitudinal studies) and their causal inference limits. Include examples of causal questions users commonly ask and the correct redirections. Example: "Monitoring data can show that PM2.5 is elevated downwind of the facility. It cannot establish that the facility caused the elevation. Source apportionment analysis or dispersion modeling would be needed for that."

### 5. Geographic Resolution Knowledge

**What it checks**: Whether the agent correctly handles requests at different geographic levels and explains why certain resolutions are or aren't available.

**Why it matters**: A national average tells you nothing about your neighborhood. A single monitoring station tells you nothing about the next county. Different data sources provide data at different spatial resolutions, and the resolution is a function of the measurement design -- it's not an arbitrary choice.

**How to customize**: Map your data sources to their native geographic resolutions and explain why. Example: "AQS provides point measurements at specific monitor locations. The EPA's AirNow system interpolates these into regional AQI maps, but interpolated values between monitors are model estimates, not measurements. Satellite-derived estimates provide county-level or grid-cell coverage but at coarser temporal resolution (daily averages vs. hourly readings)."

### 6. Terminology Fluency

**What it checks**: Whether the agent correctly maps between the user's natural language and the domain's technical vocabulary, and makes the mapping transparent.

**Why it matters**: Users say "air pollution"; datasets use "PM2.5", "PM10", "O3", "NO2", "SO2", "CO". Users say "safe"; EPA uses "Good", "Moderate", "Unhealthy for Sensitive Groups". Terminology mismatches cause the agent to return wrong data or miss relevant data entirely.

**How to customize**: Document common lay-to-technical term mappings for your domain. Your MCP server should include a `terminology_note` in tool responses that shows how the user's query was mapped. The agent prompt should instruct the model to echo this mapping back to the user. Example: "'air quality' was matched to PM2.5 (particulate matter 2.5 micrometers and smaller). Other pollutants monitored at this station include O3 (ozone) and NO2 (nitrogen dioxide), which are not included in this query."

## Implementing the Protocol

### In the System Prompt

Include the six considerations as explicit sections the agent must work through. Use a structured output format (like a `<reasoning>` block) so the reasoning is visible and auditable. See `templates/agent/prompts/system.md` for the full template.

### In the MCP Server

Each tool response should include metadata fields that feed the reasoning protocol: `methodology`, `geographic_context`, `cross_dataset_context`, `supported_conclusions`, `unsupported_conclusions`, `terminology_note`, and `data_freshness`. See `templates/mcp-server/example-tool.py` for the enrichment pattern.

### In the Evaluation Pipeline

The capability judge scores the agent's reasoning on 7 dimensions -- the 6 considerations above plus confidence calibration (whether the agent's stated confidence matches the evidence actually retrieved). See `docs/evaluation-methodology.md` for the scoring rubric.

## The Key Principle

**Grounding over speculation.** Every claim the agent makes must trace back to retrieved data and its documented methodology. When the data cannot answer a question, the agent should say so honestly rather than filling gaps with plausible-sounding but unverifiable information. A LOW-confidence answer with honest gaps is always preferable to a HIGH-confidence answer built on fabricated context.
