# agentflow

**agentflow is an autonomous multi-agent framework for mathematical research: a conductor plans, specialist agents search, compute, formalize, write, and audit, and every claim ends up on a ledger you can re-derive.**

Its core capability is to turn one sentence of research intent into a traceable research record. Instead of letting a single model answer in one pass, agentflow splits the work across fixed roles with disjoint authority — retrieval, statement registration, conjecture generation, experiment execution, formal verification, manuscript writing, review, and a conductor that dispatches — and makes each step land in an append-only ledger with evidence, cost, and an audit trail.

agentflow can also run a single role as a normal chat-like loop, but its main strength is research mode: a persistent project workspace where many roles work across many turns and sessions while keeping a re-derivable record of what was claimed, what was checked, and what was refused.

## Highlights

- Fixed roles with disjoint authority: A retrieval, B statement ledger, C relation analysis, D conjectures and attack plans, E experiments, F attack steps, G manuscripts, H review, V verification, M conductor.
- Seven explicit layers: data, declaration, tool, role, loop, wiring, quality — each with its own judge.
- Append-only ledger: JSON snapshots plus `events.jsonl`, re-derivable with `rebuild`.
- Evidence grading: `proof` / `proof_review` / `cross_check` / `heuristic`, with a five-bit evidence model (`numeric` / `proof` / `reviewed` / `formal` / `audited`).
- Formal verification bridge to Lean, with a controlled refusal when the toolchain is absent (`lean_disabled` / `no_backend` / `tool_crashed` / `import_unavailable`).
- Quote verification that compares a claim against source text word by word.
- Conjecture-driven research: conjectures, attack plans, refutations, and counterexample search are first-class records.
- Closing gate with a fixed set of acceptance cells, computed from the ledger rather than typed by hand.
- Per-run budget with hard cap, per-call cost accounting, and a usage ledger.
- Two independent switches for formal work (a CLI flag for the topic pipeline, a setting for agent loops), and a documented no-Lean mode.
- Graceful stop and force stop with process-tree termination; checkpoint-based session continuation.
- Offline demo that never touches the network.

## Latest Updates

### 2026-10

- Fixed a scoping defect in the tool call path: any call carrying a `why` argument raised `UnboundLocalError` when call logging was off (the production default). One fix explained three separate machine-reported crashes.
- Rate limiting no longer sleeps through a long `Retry-After`; the provider is put on a short cooldown instead, and later queries stop hammering it.
- `--wall-clock-sec` now means what it says: omitted means no limit, and an explicit value means exactly that value.
- Session continuation now rebuilds from the session transcript when no checkpoint exists, so a killed run can actually be resumed.
- Stale `running` task rows are swept when a new top-level run opens.
- `table.schema` accepts a single-table filter, cutting its payload from about 47 KB to 8 KB.
- `created_by` records the real writing actor instead of a per-table default.
- Added an audit check that a statement claiming `proof` must be backed by a formal experiment.

### 2026-09

- Introduced the role spec layer: per-role action tables derived into capabilities, edges, and write sets.
- Added the closing gate and its acceptance-cell vocabulary.
- Added the review tool family (review document, findings, report, fix verification).
- Added formal experiment execution with verifier output and exit code recorded on the experiment row.

## Contents

- [Latest Updates](#latest-updates)
- [Requirements](#requirements)
- [From Install to First Run](#from-install-to-first-run)
- [Runtime Layout](#runtime-layout)
- [Roles](#roles)
- [Research Mode](#research-mode)
- [Evidence and Verification](#evidence-and-verification)
- [Budget and Stop Control](#budget-and-stop-control)
- [Command Line](#command-line)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

## Requirements

- Python 3.11+ (the code base uses `X | None` annotations and dataclass features that need it)
- A terminal environment
- An LLM provider for live model calls (offline demo and most judges need none)
- Optional: a Lean toolchain for formal verification

Install the Python dependencies with `pip install -r requirements.txt` (or `pip install -e .` for the package itself).

The framework is otherwise standard-library first. The runtime dependencies are file locking, YAML presets, PDF text extraction, and the Lean bridge; there is no web framework and no database server.

## From Install to First Run

This is the recommended path from a fresh checkout to a working agentflow run.

### 1. Install

Run this from the `agentflow/` directory:

```bash
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
```

### 2. Initialize a workspace

A workspace is any directory. The ledger lives under `<workspace>/data/`.

```bash
python -m agentflow.cli --root workspace init
```

Add `PYTHONPATH=src` (or install the package) so `agentflow.cli` is importable.

### 3. Run the offline demo

This never touches the network and exercises the whole record path:

```bash
python -m agentflow.cli --root workspace demo
```

### 4. Start a research run

```bash
python -m agentflow.cli --root workspace run-agent M \
  --task "研究这个问题：<your research question>。交付研究手稿与说明。" \
  --budget-usd 5 \
  --provider crossref,doaj,europepmc,openalex
```

`--budget-usd` is the hard cap for the run. Omit `--wall-clock-sec` for no time limit; pass a value to bound it.

### 5. Check the record

```bash
python -m agentflow.cli --root workspace status
python -m agentflow.cli --root workspace verify     # exit 1 on error
python -m agentflow.cli --root workspace closing    # acceptance gate, exit 0/1/2
```

## Runtime Layout

```
<workspace>/
  data/                  ledger snapshots (one JSON per table) + events.jsonl
  source/                inputs you drop in (papers, drafts)
  code/                  experiment scripts produced by the agents
  library/               extracted text of retrieved documents
  manuscripts/           handoff records between roles
  notes/                 per-role notes
  out/paper/             manuscripts, PDFs, acceptance tables
  out/review/            review reports
  runs/                  per-run transcripts, checkpoints, pid files
  sessions/              append-only session event logs
  skills/                per-role skill documents
  verifications/         verification receipts
```

Everything under `data/` is re-derivable: `rebuild` replays `events.jsonl` into the snapshots.

## Roles

| Role | Responsibility |
|---|---|
| A | Retrieval: turn a search request into registered literature rows, and report every failure |
| B | Statement ledger: register claims, quote-verify them word by word |
| C | Relation analysis: concepts, gaps, contradictions |
| D | Conjectures and attack plans |
| E | Experiments: numeric, symbolic, exhaustive search, formal |
| F | Attack steps and counterexample search |
| G | Manuscripts |
| H | Review: findings, verdicts, fix verification (read-only) |
| V | Verification of proof steps (read-only) |
| M | Conductor: decides what happens next and dispatches |

Authority is not advisory: a role table, a tool surface, and a call-time check are all derived from the same declaration, and a write by a read-only role is refused structurally.

## Research Mode

A research run is a loop driven by the conductor. Each dispatched role returns a `payload_preview`, a summary, and its own readings; the conductor reads them, updates the ledger, and dispatches again.

What lands on the ledger is what downstream judges read:

- `literature` — retrieved documents with provenance
- `statements` — registered claims with evidence kind and quote verification
- `conjectures` — testable conjectures with criteria
- `attack_plans` — attack plans and their history
- `experiments` — runs with method, result, verifier output, exit code
- `documents` — manuscripts with claims and citations
- `review_findings` — findings from review, with level and target
- `research_questions`, `relations`, `concepts`, `dependencies`

The closing gate reads those tables and emits acceptance cells; a cell that cannot be computed from the ledger is reported as unknown rather than guessed.

## Evidence and Verification

A claim's strength is a grade, not a slogan:

| Evidence kind | Meaning |
|---|---|
| `proof` | A verifier ran and its own output is recorded |
| `proof_review` | A human-style proof was reviewed line by line |
| `cross_check` | Another method corroborated it |
| `heuristic` | Plausible, no independent backing |

`evidence_kind="proof"` requires a checker's verbatim output, its exit code, and a subject key that matches the claim. Statement rows carry a five-bit evidence model; the `proof` bit being true while the proof text is empty is an error, not a rounding difference.

Formal work has two switches:

- `--lean` on the topic pipeline (`run`, `project`)
- `AGENTFLOW_LEAN_ENABLED` / `toolchain.lean_enabled` for agent loops and tools

They are independent. When Lean is not available or not enabled, the framework refuses formal experiments in a controlled way (`lean_disabled`) instead of pretending; with the switch off no row can claim `proof`. See `docs/LEAN-MODES.md` for the full matrix.

## Budget and Stop Control

- `--budget-usd` caps a run; every model call is charged to the usage ledger.
- `python -m agentflow.cli --root <ws> budget` shows and adjusts the pool.
- `python -m agentflow.cli --root <ws> stop` stops gracefully: the running loop finishes its current step and exits; sub-processes are terminated.
- `--force` terminates the process tree by registration.
- `--resume` continues a run from its checkpoint, or from the session transcript when no checkpoint was written.

## Command Line

```
init         initialize data directories and empty tables
submit       submit a search request
run-a        run agent A
run-b        run agent B
status       table statistics
verify       global invariant check (exit 1 on error)
rebuild      rebuild snapshots from events.jsonl
repair       recompute derived fields
demo         offline end-to-end demo
tools        list the tool surface per role
analyze      relation analysis (role C)
pipeline     orchestrate C -> D -> (A -> B -> D) rounds
run          end-to-end topic run (retrieval -> answer -> quote verify -> ledger -> artifacts)
project      project workspaces: list / plan / run
evidence     evidence surface: verify / store / migrate
artifacts    artifact ownership: record / list / verify / owners
run-agent    run one role loop (model driven)
budget       show / set / add to the run budget
stop         stop a running run-agent (graceful by default)
inbox        questions waiting for a user answer
answer       answer a question on the user's behalf
closing      run the closing gate
```

## Testing

```bash
python -m pytest -q
```

The full suite is roughly 5.4k tests and takes about 25 minutes on a laptop. A large part of it is judge-style: it asserts what the framework refuses, not only what it produces.

## Troubleshooting

- **`lean_disabled` on a machine that has Lean**: the setting is separate from the CLI flag. Set `toolchain.lean_enabled` or `AGENTFLOW_LEAN_ENABLED=1`.
- **A run that stops early with no error**: check `stop --status`; a stop switch may have been left behind, and a run refuses to start while it exists. `stop --clear` removes it.
- **`verify` exits 1**: the message names the table and row; most failures are dangling references or a claim whose evidence kind is stronger than its backing.
- **A run ends without a manuscript**: check `documents` and the `out/` tree; the closing gate reports which acceptance cells could not be computed.

## License

See the repository root for license information.
