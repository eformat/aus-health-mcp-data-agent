# Evaluation Methodology

This framework evaluates agent quality through a 7-dimension capability judge powered by an LLM-as-judge. Unlike traditional NLP benchmarks that check answer correctness, this evaluation judges **reasoning quality** -- whether the agent applied the right methodology awareness, respected scope boundaries, and demonstrated the epistemological discipline that makes a data agent trustworthy.

A correct final answer with poor reasoning scores lower than a thoughtful response that shows proper methodology consideration and honest scope acknowledgment.

## The Seven Dimensions

Each dimension is scored on a 1-5 scale. Dimensions that do not apply to a particular question receive "N/A" -- never a 1 (which means the dimension applied and the agent failed) and never a free 5.

### 1. Cross-Dataset Reasoning (1-5 or N/A)

Did the agent correctly determine which dataset(s) to use and why?

| Score | Criteria |
|-------|----------|
| 1 | Used wrong dataset without considering alternatives |
| 2 | Used a dataset that works but didn't consider whether a better one exists |
| 3 | Considered multiple datasets but made an incorrect or incomplete comparison |
| 4 | Correctly identified the right dataset(s) and articulated the key trade-offs |
| 5 | Demonstrated deep understanding of dataset differences (methodology, geographic level, temporal coverage) and recommended the optimal approach with clear reasoning |

### 2. Methodology Awareness (1-5 or N/A)

Did the agent demonstrate understanding of how the data was collected?

| Score | Criteria |
|-------|----------|
| 1 | Data was retrieved but the agent made no mention of methodology |
| 2 | Named the data source but showed no understanding of methodology |
| 3 | Mentioned methodology basics (e.g., "sensor data") without specifics |
| 4 | Described the collection design and connected it to interpretation |
| 5 | Retrieved and applied per-indicator methodology; demonstrated understanding of specific nuances like calibration, population coverage, or temporal comparability |

### 3. Scope Adherence (1-5)

Did the agent stay within what the data can answer?

| Score | Criteria |
|-------|----------|
| 1 | Made claims the data cannot support (health recommendations, predictions, causal claims from monitoring data) |
| 2 | Mostly stayed within scope but supplemented with unsourced knowledge without disclaiming it |
| 3 | Stayed within scope but failed to explicitly note what the data cannot answer |
| 4 | Correctly identified scope boundaries and stated what the data can and cannot answer |
| 5 | Proactively identified that the question is outside scope, explained why, and redirected to appropriate resources |

### 4. Causal Inference Boundaries (1-5 or N/A)

Did the agent correctly handle causal claims or implications?

| Score | Criteria |
|-------|----------|
| 1 | Made or agreed to causal claims from observational data |
| 2 | Hedged but still implied causation |
| 3 | Noted correlation is not causation but didn't explain what study design would be needed |
| 4 | Clearly stated the data shows associations not causation, named the kind of study needed |
| 5 | Explicitly identified the observational design as the reason causal claims aren't supportable, and offered to show what the data CAN tell you |

### 5. Geographic Resolution Knowledge (1-5 or N/A)

Did the agent correctly handle geographic scope?

| Score | Criteria |
|-------|----------|
| 1 | Presented data at wrong geographic level or claimed data exists at a level it doesn't |
| 2 | Got the geographic level right but didn't explain limitations |
| 3 | Noted geographic limitations but didn't explain why (sensor placement, sampling design) |
| 4 | Correctly explained geographic scope, why it's limited, and offered alternatives at other levels |
| 5 | Demonstrated deep understanding of resolution differences across datasets and why they can't be compared directly |

### 6. Terminology Fluency (1-5 or N/A)

Did the agent correctly map lay terms to domain-specific terminology?

| Score | Criteria |
|-------|----------|
| 1 | Used wrong term or failed to find data because of a terminology mismatch |
| 2 | Found data but didn't bridge between the user's language and technical terminology |
| 3 | Mapped terms correctly but didn't clarify for the user what the term means |
| 4 | Correctly mapped lay terms to domain indicators and explained the mapping |
| 5 | Mapped terms, explained the mapping, noted scope implications, and gently corrected imprecise language |

### 7. Confidence Calibration (1-5, never N/A)

Does the confidence card accurately reflect the context actually retrieved? This is the one dimension that is always scored -- every response must include a confidence card, including refusals.

| Score | Criteria |
|-------|----------|
| 1 | No confidence card at all, or claims HIGH confidence with no methodology retrieved |
| 2 | Confidence level doesn't match what was actually retrieved |
| 3 | Confidence level is roughly right but the basis statement is vague |
| 4 | Confidence level matches context, basis statement is specific |
| 5 | Confidence level precisely reflects what was retrieved and what's missing; gaps are accurately identified |

## Gold Standards

Gold standards define the expected reasoning for each evaluation question. They aren't answer templates -- the agent doesn't need to match them word-for-word. They establish what key considerations must be present.

A gold standard file contains:

- **id**: Unique identifier for the question
- **question**: The evaluation question text
- **evaluation_criteria**: What the question tests (e.g., "Cross-dataset comparison", "Methodology awareness")
- **relevant_capabilities**: Which of the 7 dimensions apply to this question and what reasoning is expected for each
- **gold_standard_reasoning**: A step-by-step reasoning chain showing the expected thought process
- **gold_standard_answer**: A reference answer showing the expected substance

See `templates/eval-pipeline/gold-standards/example-seed.yaml` for a fully annotated example.

## Writing Seed Questions

Good seed questions target specific reasoning capabilities. Each question should primarily test 2-3 dimensions while touching others tangentially. Categories:

- **Data retrieval**: Straightforward data lookups that test methodology awareness and terminology fluency
- **Cross-dataset comparison**: Questions requiring the agent to choose between or compare data sources
- **Scope boundary**: Questions that push against what the data can answer, testing scope adherence and causal inference boundaries
- **Geographic resolution**: Questions about specific locations that test geographic knowledge
- **Methodology comparison**: Questions requiring understanding of how different datasets collect data differently

For scaling, each seed question can generate variants by changing the geographic focus, time period, specific indicator, or comparison axis. See `templates/eval-pipeline/questions/seed-template.yaml`.

## The KFP Pipeline

The evaluation pipeline runs in six stages:

1. **Load questions**: Reads the evaluation corpus (JSONL) and prepares it for the agent
2. **Run agent**: Sends each question to the agent via the MCP agent block, collecting full tool traces
3. **Triage**: Extracts the agent's reasoning block, final answer, and tool interactions from the trace
4. **Merge gold standards**: Joins the triaged responses with gold standard YAML files to provide the judge with expected reasoning
5. **Capability judge**: An LLM scores each response on 7 dimensions, grounding every evaluation in specific evidence from the agent's output
6. **Summary**: Aggregates per-capability scores, computes means, and reports tool call rates

The judge model should be kept pinned across A/B comparisons. When comparing two agent models, both must be judged by the same judge checkpoint so scores remain comparable. The agent model is parameterized; the judge model is intentionally not.

## Worked Example: Environmental Monitoring

Suppose you're building an air quality monitoring agent. Here's how you'd write a seed question targeting cross-dataset reasoning and geographic resolution:

**Question**: "What is the current PM2.5 level near downtown Portland, Oregon?"

**Why this tests what it tests**: The agent must choose between AQS fixed monitors (point measurements, regulatory-grade), PurpleAir sensors (denser coverage, lower accuracy), and satellite-derived estimates (complete coverage, daily resolution). Portland has both AQS and PurpleAir coverage, so the agent must reason about which is most appropriate for a "current level" question (AQS for regulatory-grade, PurpleAir for hyperlocal).

**Gold standard reasoning steps**:
1. Cross-dataset: Consider AQS vs PurpleAir vs satellite. "Current level" implies real-time, which favors AQS and PurpleAir over satellite (daily averages).
2. Methodology: AQS uses FEM/FRM instruments, PurpleAir uses laser particle counters with EPA correction factors applied.
3. Geographic: "Near downtown" -- check which AQS monitors serve that area. PurpleAir may offer closer coverage.
4. Terminology: "PM2.5 level" maps to AQI category and raw concentration (ug/m3).

This seed can be scaled by varying the city (rural areas may only have satellite coverage), pollutant (O3 vs PM2.5 vs NO2), and temporal specificity ("last month's average" shifts the dataset preference toward satellite).
