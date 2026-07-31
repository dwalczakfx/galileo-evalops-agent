# Galileo EvalOps Agent

A standalone, cost-bounded operator that uses Galileo APIs to investigate one
selected project and Log Stream, manage evaluation workflows, curate regression
datasets, evaluate release readiness, and propose governed remediations.

The application does **not** perform organization-wide trace or metric scans.
The configured project and Log Stream are suggestions that the user confirms
before analysis. Environment comparison is the only two-project operation: it
reads capped metadata from one exact target project and never copies trace data.

## Data flow

```text
Selected project and source Log Stream
        |
        | aggregate metrics first
        v
Bounded trace search (default: 20)
        |
        | selected trace IDs only
        v
Detailed inspection (default: 5)
        |
        | explicit approval
        v
Regression dataset -> bounded experiment
```

The EvalOps Agent writes its own traces to a separate `evalops-agent` Log Stream
inside the selected project. This prevents its activity from contaminating the
source data it analyzes.

## Environment

Configuration is self-contained. By default, the app loads `.env` from this
directory. Create it from the deployment template:

```bash
cp .env.example .env
```

Fill every value marked `REQUIRED`. In particular, choose an
`EVALOPS_MODEL` supported by the endpoint configured through
`OPENAI_BASE_URL`; leave `OPENAI_BASE_URL` blank only when using the standard
OpenAI endpoint.

`.env` is ignored by Git and Docker. Never put credentials in `.env.example`.
Process environment variables take precedence over the file. To use another
file:

```bash
python3 -m evalops_agent --env-file /run/secrets/evalops.env chat
```

`AGENT_CONTROL_URL` is required. Without Agent Control initialization,
decorated functions would otherwise run without protection, which is not an
acceptable deployment mode for this application.

## Install

From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m pip install --no-deps -e .
```

`requirements.txt` pins the direct dependency versions tested with this
release. `pyproject.toml` also applies major-version upper bounds.

## Start safely

Create the dedicated telemetry Log Stream after reviewing the write preview:

```bash
python3 -m evalops_agent setup
```

Then run the read-only deployment check. It verifies the exact Galileo scope,
dedicated telemetry stream, local environment path, and Agent Control
authentication without scanning organization traces:

```bash
python3 -m evalops_agent doctor
```

Start the guided conversational agent:

```bash
python3 -m evalops_agent chat
```

Before showing the menu, the CLI explains the agent’s purpose, available
capabilities, selected source and telemetry streams, cost boundaries, and write
approval behavior. It then asks what the user wants to accomplish:

1. Investigate a quality drop
2. Find and explain low-quality traces
3. Build a regression dataset
4. Review or compare experiments
5. Get an EvalOps project briefing
6. Prepare a bounded experiment
7. Run Galileo Project Doctor
8. Find production-to-dataset coverage gaps
9. Evaluate release readiness
10. Optimize evaluation cost and budget
11. Build and simulate an Agent Control
12. Compare or bootstrap Galileo environments
13. Investigate a Galileo Signal
0. Ask a custom question

Each workflow discovers valid Galileo metrics and resources before asking the
user to choose. The user does not need to know metric, trace, dataset, prompt,
or experiment IDs.

Open the presenter-ready demo menu:

```bash
python3 -m evalops_agent demo
```

The presentation menu includes:

- Why did quality drop?
- Turn production failures into regression tests
- EvalOps project briefing
- Governed agent and prompt-injection resistance
- Galileo Project Doctor
- Advanced Galileo management tour

Each option includes an audience takeaway, cost/write profile, speaker notes,
and guided prompts that can be run one step at a time.

List or preview scenarios without running model calls:

```bash
python3 -m evalops_agent demo --list
python3 -m evalops_agent demo \
  --scenario management-tour \
  --print-only
```

Seed the deterministic demo after reviewing its write preview:

```bash
python3 -m evalops_agent demo-seed
```

This writes 12 traces and computes `demo_quality` locally. It makes no LLM or
external evaluator calls. The output gives the exact command for analyzing the
new `evalops-demo-source` stream.

Use `--dry-run` to guarantee that no writes execute. Use `--project` and
`--log-stream` for exact, non-discovery targeting:

```bash
python3 -m evalops_agent \
  --project dwalczak-demo \
  --log-stream guardrails \
  --dry-run \
  chat
```

## Advanced management capabilities

- **Project Doctor** audits capped stream activity, empty sessions, enabled
  metrics, datasets, prompts, experiments, and Agent Control coverage. Findings
  are deterministic and evidence-linked; there is deliberately no opaque health
  score.
- **Production coverage analyst** compares already inspected failures with one
  small regression dataset. It uses lexical similarity as a triage signal, not
  as proof of semantic coverage.
- **Release gate** compares two exact experiments against thresholds supplied by
  the user. The result is `GO` only when every criterion passes; otherwise it is
  `HOLD`.
- **Evaluation cost advisor** forecasts sampled rows, generation calls, and
  evaluator calls before work is run. It shows the formula and never invents
  currency pricing.
- **Agent Control builder** constructs a regex control, validates it with Agent
  Control, and simulates it locally only against traces inspected in the current
  session. Creation and attachment are separately approval-gated.
- **Environment drift and bootstrap** compares capped resource metadata for the
  selected project and one exact target. The only automated remediation is
  approval-gated creation of explicitly selected missing Log Streams. It never
  copies traces, datasets, prompts, collaborators, or deletes resources.
- **Signals handoff** accepts a Signal name or link, metric, threshold, and
  window supplied by the user, validates the metric in the selected Log Stream,
  and starts the bounded incident workflow. The installed Galileo SDK currently
  exposes no Signals endpoint, so the agent explicitly reports that it did not
  query a Signals API.

## Built-in examples

The chat UI always offers starter requests:

1. List friendly metric names available on the selected Log Stream.
2. Summarize quality metrics for the last 24 hours.
3. Find up to 10 traces below a selected metric threshold.
4. Inspect the three most relevant failures from the previous search.
5. List datasets in the selected project.
6. List prompts in the selected project.
7. List experiments and summarize available results.
8. Compare two experiments numerically.
9. Prepare a regression dataset from previously returned trace IDs.
10. For the demo stream, find traces with `demo_quality` below 0.6.
11. Run Galileo Project Doctor with a 30-day stale-resource threshold.
12. Estimate calls for 20 rows, two metrics, one run, and a 50% sample.
13. Compare this project with one exact target without copying trace data.
14. Turn user-provided Galileo Signal context into a bounded investigation.

No Galileo IDs need to be typed by the user.

## Cost controls

- Aggregate metric query before raw trace retrieval
- Trace and metric operations restricted to one selected project and Log Stream
- No automatic pagination
- Maximum seven-day lookback by default
- Maximum 20 traces per search
- At most 50 recent candidate traces examined for client-side metric filtering
- Maximum five detailed traces
- Maximum 20 dataset and experiment rows
- Maximum three experiment metrics
- Maximum 10 streams and 20 resources per type in management audits
- Maximum five recent sessions sampled per audited stream
- Maximum 30 dataset rows in lexical coverage analysis
- Configurable ceilings of 50 generation and 100 evaluator calls
- Deterministic Python for sorting and numeric comparisons
- Session-level caching for repeated metric requests
- Write preview with estimated generation and evaluator calls
- Explicit approval for every write

Querying existing metric results is read-only. Enabling metrics, recomputing
metrics, and running experiments can invoke evaluators and are never performed
automatically.

The hosted trace-search endpoint can reject metric filters for some streams.
The app therefore reads at most `EVALOPS_MAX_TRACE_CANDIDATES` recent traces
(default 50) from the selected stream and filters them locally. Results are
clearly labeled as a bounded recent sample, not an exhaustive project-wide
ranking.

The management limits can be changed with
`EVALOPS_MAX_MANAGEMENT_STREAMS`, `EVALOPS_MAX_MANAGEMENT_RESOURCES`,
`EVALOPS_MAX_SESSION_SAMPLE`, `EVALOPS_MAX_COVERAGE_ROWS`,
`EVALOPS_MAX_GENERATION_CALLS`, and `EVALOPS_MAX_EVALUATOR_CALLS`.

## Galileo instrumentation

- One lazily created Galileo session per CLI conversation that runs a request
- A controlled request trace plus an agent execution trace per user turn
- Tool and OpenAI LLM spans nested under the agent execution trace
- `@log(span_type="tool")` on every Galileo management operation
- OpenAI calls captured by Galileo's OpenAI integration
- Immediate flush after every completed user turn, with visible upload status
- Visible telemetry errors instead of silently empty sessions
- Agent Control bridge registered against the dedicated telemetry Log Stream
- `@control()` on user requests, detailed trace inspection, dataset writes, and
  experiment execution, plus advanced environment and Agent Control writes
- Explicit handling of DENY and bounded STEER decisions
- Agent Control policy refresh and observability resources shut down on exit
- Final Galileo flush, session cleanup, and auth-environment restoration on exit
- Opening and quitting the CLI without a request does not create an empty session

The source and telemetry Log Streams must differ. The application refuses to
start if they are the same, preventing recursive self-analysis and telemetry
contamination.

## Agent Control policies

The decorators define decision boundaries; policies remain centrally managed.
For the demo, bind controls to the `evalops-agent` Log Stream and use the exact
step names:

- `evalops_user_request`
- `inspect_production_trace`
- `analyze_regression_coverage`
- `write_regression_dataset`
- `write_prompt_version`
- `run_bounded_experiment`
- `bootstrap_galileo_environment`
- `write_agent_control_policy`

Suggested policies:

- DENY requests to expose credentials or system prompts.
- DENY destructive Galileo operations.
- STEER write requests that do not identify the selected project and resource.
- OBSERVE when trace content appears to contain prompt-injection instructions.

## Deployment

This repository is designed as a single-session CLI process. Run one interactive
conversation per process; it is not a multi-user HTTP service.

Local deployment:

```bash
python3 -m evalops_agent doctor
python3 -m evalops_agent chat
```

Container deployment:

```bash
docker build -t galileo-evalops-agent:0.3.0 .
docker run --rm -it --env-file .env \
  galileo-evalops-agent:0.3.0 chat
```

The container runs as an unprivileged user and does not contain `.env`, tests,
Git metadata, or local caches.

GitHub Actions runs the test suite and compilation checks on Python 3.12–3.14
and separately builds both the Python distribution and container image. Before
publishing:

```bash
python3 -m pip check
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
python3 -m build
```

No license is included; choose a license before publishing the repository for
reuse outside your organization.

## Security and operational boundaries

- Every remote write requires an in-process preview and approval. `--dry-run`
  prevents writes even when `--yes` is supplied.
- Trace details can only be fetched after a bounded search. Dataset writes and
  control simulations require traces inspected in the current session.
- Agent Control publication requires successful server validation and an exact
  agent returned by a same-session Agent Control listing.
- Locally simulated regex controls use a restricted pattern subset to avoid
  unbounded regex execution.
- Secrets are redacted from tool errors and structured outputs. Token-count
  metrics remain visible because they are not credentials.
- User prompts and inspected trace content are intentionally sent to the
  configured model and logged to the dedicated Galileo telemetry stream. Apply
  your organization’s data-retention and access policies.
- The app does not automatically delete resources, copy traces between
  projects, enable metrics, or recompute evaluations.

## Tests

Tests use mocked services and do not contact Galileo:

```bash
python3 -m unittest discover -s tests -v
```
