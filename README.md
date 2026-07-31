# Galileo EvalOps Agent

[![CI](https://github.com/dwalczakfx/galileo-evalops-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/dwalczakfx/galileo-evalops-agent/actions/workflows/ci.yml)

Galileo EvalOps Agent is an interactive command-line assistant for teams that
operate, evaluate, and improve AI applications in Galileo. It connects
production insights with practical EvalOps workflows: investigating quality
changes, reviewing traces, building regression datasets, comparing experiments,
planning evaluation cost, and managing Agent Control guardrails.

The agent starts in the Galileo project and Log Stream configured in `.env`,
shows that working context clearly, and guides users through its metrics,
datasets, prompts, and experiments. You can switch scope explicitly and work
with familiar names instead of looking up resource IDs.

## Capabilities

| Area | What the agent helps you accomplish |
| --- | --- |
| Production quality | Investigate metric changes and inspect representative low-quality traces. |
| Regression testing | Convert reviewed production failures into reusable Galileo datasets and identify coverage gaps. |
| Experiments | Discover, compare, prepare, and run bounded evaluation experiments. |
| Release decisions | Apply explicit quality and cost criteria to produce a repeatable `GO` or `HOLD` recommendation. |
| Project health | Review Log Stream activity, metrics, datasets, prompts, experiments, sessions, and governance coverage. |
| Cost planning | Estimate generation and evaluator calls before an evaluation is launched. |
| Agent Control | Install a starter safety policy, inspect coverage, and build or simulate additional controls. |
| Environment management | Compare two selected Galileo projects and optionally create missing Log Streams. |
| Signals workflow | Use a Galileo Signal name or link as the starting context for a focused investigation. |

Management changes—such as creating datasets, experiments, controls, or Log
Streams—are shown as a preview and require approval. Read and evaluation
budgets are configurable, making the agent suitable for both demos and regular
project operations.

## Quick start

### 1. Requirements

- Python 3.12, 3.13, or 3.14
- A Galileo account and API key
- A Galileo project with a source Log Stream
- Access to an OpenAI-compatible model endpoint
- A Galileo Agent Control endpoint

### 2. Install

```bash
git clone https://github.com/dwalczakfx/galileo-evalops-agent.git
cd galileo-evalops-agent

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m pip install --no-deps -e .
```

After activation, the `evalops` command is available in the virtual
environment. On Windows PowerShell, activate with
`.venv\Scripts\Activate.ps1`.

### 3. Configure

Create a private environment file from the included template:

```bash
cp .env.example .env
```

Open `.env` and review these core settings:

| Setting | Purpose |
| --- | --- |
| `GALILEO_API_URL` | Galileo API endpoint. |
| `GALILEO_CONSOLE_URL` | Optional Galileo Console address used for navigation. |
| `GALILEO_API_KEY` | API key used by Galileo and Agent Control. |
| `GALILEO_PROJECT` | Project used automatically when the agent starts. |
| `GALILEO_LOG_STREAM` | Source Log Stream used automatically for investigations. |
| `OPENAI_API_KEY` | Key for the configured model endpoint. |
| `OPENAI_BASE_URL` | Optional OpenAI-compatible endpoint; leave blank for the standard OpenAI API. |
| `EVALOPS_MODEL` | Model name supported by the configured endpoint. |
| `AGENT_CONTROL_URL` | Galileo Agent Control service endpoint. |

The template also includes defaults for the telemetry Log Stream, agent name,
query limits, and evaluation budgets. `.env` is excluded from Git and Docker;
do not place credentials in `.env.example`.

To use a centrally managed environment file instead:

```bash
evalops --env-file /run/secrets/evalops.env chat
```

### 4. Initialize Galileo integration

Run the guided setup:

```bash
evalops setup --with-agent-control
```

Setup creates the dedicated EvalOps telemetry Log Stream when needed,
registers the agent, and offers to install the versioned starter Agent Control
policy. Every change is displayed before approval. Setup does not call an LLM
or run evaluators.

To preview setup without making changes:

```bash
evalops --dry-run setup --with-agent-control
```

### 5. Verify the installation

```bash
evalops doctor
```

The doctor checks configuration, project connectivity, source and telemetry
Log Streams, exact model access, Agent Control registration, effective control
coverage, and the runtime evaluation endpoint. The model check reads metadata
and makes no generation calls.

### 6. Start the agent

```bash
evalops chat
```

The CLI presents guided workflows and also accepts free-form EvalOps requests.
It opens directly in the configured project and source Log Stream and prints
the active context before the menu. To choose another scope interactively, run:

```bash
evalops chat --select-scope
```

## Guided workflows

The chat starts with four clear choices instead of displaying every capability
at once:

1. Get a recommended first check.
2. Investigate production quality.
3. Improve evaluations and releases.
4. Govern and manage Galileo.

Selecting a topic opens a smaller menu with the relevant workflows. For
example, **Investigate production quality** includes quality changes,
low-quality trace triage, proactive Signal candidates, and handoff from a known
Signal. Type `menu` at any time to return to the topics.

The recommended start profiles one bounded recent trace page in the selected
Log Stream. It separates configured metrics from metrics that actually have
numeric values in the requested window before proposing a check. If the window
contains no traces or a metric has no values, the agent explains that instead of
suggesting arbitrary threshold changes. You do not need to bring an example,
metric, threshold, or Signal name.

Once a workflow starts, short answers such as `yes`, `1h`, `0.5`, or `20` are
passed to the conversation instead of being interpreted as menu selections.
The agent asks for one decision at a time, offers an explanation and a default,
and lets you accept or change it. Exact workflow titles and keys are also
accepted.

## Demo mode

Open the presenter-ready scenario menu:

```bash
evalops demo
```

Available scenarios include:

- Why did quality drop?
- Turn production failures into regression tests.
- EvalOps project briefing.
- Governed agent and prompt-injection resistance.
- Galileo Project Doctor.
- Advanced Galileo management tour.

List or preview the scenarios without launching model calls:

```bash
evalops demo --list
evalops demo --scenario management-tour --print-only
```

For a predictable demo environment, create the included sample traffic:

```bash
evalops demo-seed
```

This produces 12 deterministic traces with a locally calculated
`demo_quality` metric and does not use an LLM or external evaluator.

## Agent Control integration

The recommended setup installs
`<EVALOPS_AGENT_NAME>-starter-safety-v1`. The policy contains four controls:

- Deny explicit requests to reveal credentials or system prompts.
- Deny responses that resemble credential disclosure.
- Deny destructive requests targeting Galileo resources.
- Observe prompt-injection language found in inspected traces.

The setup is safe to rerun. Matching controls and policy associations are
reused, while an unexpected control with the same name is left unchanged and
reported for review.

The interactive **Build and simulate an Agent Control** workflow can validate
new regex controls, preview their behavior against inspected traces, and
publish them after approval.

## Scope and cost management

Each conversation works within one project and source Log Stream. By default,
the agent uses `GALILEO_PROJECT` and `GALILEO_LOG_STREAM` without asking you to
confirm them on every launch. The active scope and query limits are printed
before the workflow menu.

Override the defaults for one run with exact names:

```bash
evalops --project my-project --log-stream production chat
```

Or ask the CLI to list project and Log Stream names for interactive selection:

```bash
evalops chat --select-scope
```

If configured resources are invalid, an interactive terminal offers the same
picker. Automated runs fail with a clear configuration error instead of
waiting for input. Cross-environment comparison is initiated only when a user
selects a second project.

Default operating limits include:

| Limit | Default |
| --- | ---: |
| Metric and trace lookback | 7 days |
| Traces returned per search | 20 |
| Detailed traces per conversation | 5 |
| Dataset or experiment rows | 20 |
| Experiment metrics | 3 |
| Generation calls | 50 |
| Evaluator calls | 100 |

Limits can be adjusted in `.env`. The agent estimates generation and evaluator
usage before an experiment and asks for approval before executing it.

## Galileo observability

The agent records its own activity in the dedicated Log Stream configured by
`EVALOPS_LOG_STREAM` (default: `evalops-agent`). Galileo receives:

- Conversation sessions and agent traces.
- OpenAI-compatible LLM spans.
- Galileo API tool spans.
- Agent Control evaluations and decisions.
- Latency and token usage captured by the Galileo integrations.

Telemetry is flushed after each completed turn, and upload failures are shown
in the CLI. The telemetry Log Stream must be different from the source Log
Stream being investigated.

## Command reference

| Command | Description |
| --- | --- |
| `evalops setup` | Create or verify the dedicated telemetry Log Stream. |
| `evalops setup --with-agent-control` | Register the agent and install the starter control policy. |
| `evalops doctor` | Run read-only configuration and connectivity checks. |
| `evalops chat` | Start the interactive EvalOps assistant. |
| `evalops demo` | Run a presenter-ready guided scenario. |
| `evalops demo-seed` | Create deterministic sample traces for demonstrations. |

`--select-scope` may be placed before or after a command. It only changes the
working context; it does not approve writes. The `--yes` option approves remote
write previews and should be used only in trusted automation.

Except for `--select-scope`, global options must appear before the command:

```bash
evalops --project my-project --log-stream production chat
evalops chat --select-scope
evalops --dry-run setup --with-agent-control
evalops --yes --project my-project demo-seed
```

## Docker

```bash
docker build -t galileo-evalops-agent:0.5.0 .
docker run --rm -it --env-file .env \
  galileo-evalops-agent:0.5.0 chat
```

The image runs as an unprivileged user and does not include `.env`, tests, Git
metadata, or local caches.

## Operational notes

- The application is a single-user CLI; start one process per conversation.
- User requests and inspected trace content are sent to the configured model
  and recorded in the dedicated telemetry Log Stream.
- The current Galileo SDK does not expose a Signals API. The Signals workflow
  starts from a Signal name, link, metric, threshold, and time window supplied
  by the user.
- Environment bootstrap can create selected missing Log Streams after approval;
  it does not copy trace data or delete resources.

## Development

Run the verification suite:

```bash
python3 -m pip check
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
python3 -m build
```

Tests use mocked Galileo services and do not contact external systems. GitHub
Actions tests Python 3.12–3.14 and builds both the Python package and container
image.
