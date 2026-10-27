# Incubator

**Incubator is a research project; its working system is `agentflow`, an autonomous multi-agent framework for mathematical research:** a conductor plans, specialist agents retrieve, compute, formalize, write, and review, and every claim lands on a ledger you can re-derive.**

`agentflow` (this repository's `agentflow/` package, run as `python -m agentflow.cli`) turns one sentence of research intent into a traceable research record. Rather than letting a single model answer in one pass, agentflow assigns the work to fixed roles with disjoint authority — retrieval, statement registration, relation analysis, conjecture generation, experiments, attack steps, manuscripts, review, verification, and a conductor that dispatches — and makes each step land on an append-only ledger with evidence, cost, and an audit trail.

It can also drive a single role as a chat-like loop, but its main strength is research mode: a persistent workspace where many roles work across many turns and sessions while keeping a record of what was claimed, what was checked, what was refused, and what it cost.

## Highlights

- Eleven roles: ten summonable specialists with disjoint authority — A retrieval, B statement ledger, C relation analysis, D research loop (conjectures and attack plans), E experiments, F attack steps, G manuscripts, H review, V proof-step verification, L Lean formalization — plus M, the conductor.
- Sixty-five declared actions across those roles, derived from one declaration into capabilities, edges, and write sets.
- Eight explicit layers — data, declaration, tool, role, loop, wiring, quality, and the web/user-facing layer — each with its own judges.
- Seventeen ledger tables (statements, conjectures, attack plans, experiments, documents, review findings, research questions, dependencies, tasks, usage, candidates, and more) plus an append-only event log that can rebuild every snapshot.
- Evidence grading with a five-bit model: `numeric`, `proof`, `reviewed`, `formal`, `audited`. A row that says "proved" must be readable in the table that owns proofs.
- A formal verification bridge to Lean, with controlled refusals (`lean_disabled`, `no_backend`, `tool_crashed`, `import_unavailable`) instead of confident silence.
- Word-by-word quote verification against extracted source text.
- Conjecture-driven research: conjectures, attack plans, refutations, and counterexample search are first-class records, not chat asides.
- A closing gate whose acceptance cells are computed from the ledger, never typed by hand.
- A hard per-run budget with per-call accounting and a usage ledger.
- Graceful stop, force stop with process-tree termination, and transcript-based continuation.
- An offline demo that never touches the network.

## Latest Updates

### 2026-10

- Fixed a scoping defect on the tool call path: any call carrying a `why` argument raised `UnboundLocalError` when call logging was off, which is the production default. One fix explained three separately reported crashes.
- Rate limiting no longer sleeps through a long `Retry-After`; the provider goes on a short cooldown and later queries stop retrying it.
- The wall-clock limit now means what it says: omitted means no limit, and an explicit value means exactly that value.
- Continuation rebuilds from the session transcript when no checkpoint exists, so a killed run can actually be resumed.
- Stale `running` task rows are swept when a new top-level run opens (matched by topology, not by caller).
- `table.schema` accepts a single-table filter, cutting its payload from about 47 KB to 8 KB.
- `created_by` records the writing actor instead of a per-table default.
- An audit check now requires that a statement claiming `proof` be backed by a formal experiment.
- A review report and a ledger verdict are documented as two deliberately separate records.

### 2026-09

- Introduced the role spec layer: per-role action tables derived into capabilities, edges, and write sets.
- Added the closing gate and its acceptance-cell vocabulary.
- Added the review tool family (review document, findings, report, fix verification).
- Added formal experiment execution recording verifier output and exit code on the experiment row.

## Contents

- [Latest Updates](#latest-updates)
- [Requirements](#requirements)
- [From Install to First Run](#from-install-to-first-run)
- [Workspace Home](#workspace-home)
- [Provider Setup](#provider-setup)
- [Daily Use After Setup](#daily-use-after-setup)
- [One Entry Point: `start`](#one-entry-point-start)
- [Agent Loop Mode](#agent-loop-mode)
- [Research Mode](#research-mode)
- [Sessions and Continuation](#sessions-and-continuation)
- [Ledger and Retrieval](#ledger-and-retrieval)
- [Roles, Skills, and Tools](#roles-skills-and-tools)
- [Experiments and Python Tools](#experiments-and-python-tools)
- [Verification and Evidence](#verification-and-evidence)
- [Lean Modes](#lean-modes)
- [Budget and Stop Control](#budget-and-stop-control)
- [Files and Paths](#files-and-paths)
- [Runtime Layout](#runtime-layout)
- [Command Line](#command-line)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Status](#status)
- [Repository facts](#repository-facts读数判据在守)

## Requirements

- Python 3.11 or newer. The code uses `X | None` annotations and dataclass features that require it.
- A terminal environment.
- An LLM provider for live model calls. The offline demo and a large part of the test suite need none.
- Optional: a Lean toolchain for formal verification.

Runtime dependencies are deliberately few — file locking, YAML presets, PDF text extraction, JSON-schema checks, and two optional HTTP clients. There is no web framework and no database server; the ledger is JSON plus an append-only event log.

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
```

## From Install to First Run

This is the shortest path from a fresh checkout to a working run.

### 1. Install

```bash
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
```

Alternatively run from the source tree with `PYTHONPATH=src` and skip the editable install.

### 2. Initialize a workspace

A workspace is any directory. The ledger lives under `<workspace>/data/`.

```bash
python -m agentflow.cli --root workspace init
```

### 3. Run the offline demo

This exercises the whole record path without touching the network.

```bash
python -m agentflow.cli --root workspace demo
```

> `cli demo` is the **old path**（旧路径）: the **offline smoke test**, kept reachable, needs no model
> key, and never touches the network. The main path is the one entry point documented in §One Entry
> Point; the demo stays as the end-to-end check that the record path works with no provider at all.

### 4. Start a research run

The workspace is selected by a global argument that goes before the subcommand
(see `agentflow.cli --help`). It is not inferred from the current directory: omitted, it falls back
to the package's own default workspace, so pass it explicitly.

```bash
python -m agentflow.cli run-agent M \
  --task "研究这个问题：<your research question>。交付研究手稿与说明。" \
  --budget-usd 5 \
  --provider crossref,doaj,europepmc,openalex
```

That is the one-role-loop spelling. The same run through the unified entry point (one command that
answers what to do / where / how much / Lean on or off) is documented in
[One Entry Point: `start`](#one-entry-point-start); the four older commands remain aliases of the
same execution body (`cli._run_spec`) with their flags, defaults, and `--help` text unchanged.

### 5. Read the record

```bash
python -m agentflow.cli --root workspace status
python -m agentflow.cli --root workspace verify       # exit 1 on an error-level finding
python -m agentflow.cli --root workspace closing      # acceptance gate, exit 0 / 1 / 2
```

## Workspace Home

A workspace is self-describing. `init` creates `data/` with one JSON snapshot per table plus `events.jsonl`; nothing else is required to start, and every optional directory is created by whoever needs it.

Because a workspace is a plain directory, it is also a unit of isolation: two workspaces share no ids, no budget, and no session, so a run in one cannot corrupt the record of another.

## Provider Setup

Retrieval providers are selected per run with `--provider` (comma separated: `crossref`, `doaj`, `europepmc`, `openalex`, `fixture`). Omitted, the configured default is used.

Provider behaviour is honest by construction:

- A provider that reports "all query paths failed" raises a distinct error instead of returning zero candidates, so "nothing was found" and "nothing was checked" stay different readings.
- HTTP 429 with a long `Retry-After` is not slept through; the provider goes on a short cooldown so subsequent queries move on.
- `--provider fixture` runs the whole retrieval path offline against local fixtures.

Model providers are configured in `settings.json` or the environment. With no model configured, only the offline paths run.

## Daily Use After Setup

The common loop is:

1. `start --task "..."` with a budget (or `run-agent M --task "..."`, the alias).
2. Watch it dispatch roles; each dispatch returns a preview of what that role produced.
3. `status` to read the tables, `verify` to check invariants, `closing` to see which acceptance cells can be computed.
4. `inbox` for questions waiting on a human, `answer` to answer one.
5. `stop` if it goes the wrong way; `--resume` afterwards to continue where it stopped.

## One Entry Point: `start`

`start` answers four questions — what to do, where, how much, Lean on or off. Every other entry is a
sub-mode of it, and the four older commands (`run`, `run-agent`, `project run`, `web`) are aliases
of the same execution body (`cli._run_spec`): the parser and the flags are untouched, so existing
scripts keep working.

```bash
# preview only: prints what would happen — creates no directory, writes no byte, calls no model
python -m agentflow.cli --root workspace start --task "<one sentence>" --dry-run

# run it (the workspace is initialized on the way if it does not exist yet)
python -m agentflow.cli --root workspace start --task "<one sentence>" --budget-usd 5

# supervise while it runs: prints URL / workspace / sid / current round, and stops the server
# when the run finishes (use `web` or another `start --watch` if you want to keep looking)
python -m agentflow.cli --root workspace start --task "<one sentence>" --watch --port 52060 --open

# web only (the server stays up until Ctrl-C)
python -m agentflow.cli --root workspace start --watch --port 52060 --open
```

- `--mode` defaults to `auto`, which infers from the directory: no task plus `--watch` ⇒ web only;
  a missing or empty project folder ⇒ cold start; a workspace whose `data/tasks.jsonl` already has
  rows ⇒ the ten-role research loop (role defaults to M); an initialized workspace without a ledger
  ⇒ the warm project path. Pin it with `--mode research|role|topic|project|cold|warm`.
- `--mode role` requires `--role <A..H|V|L|M>`; `--mode research` takes no role.
- `--budget-usd` is written to `<workspace>/budget.json` when given explicitly, and the run prints
  the transition (`old → new`); the previous entry stays in the append-only `added[]` history.
  Omitted, each mode uses its own default (topic 1.0 / project 0.5 / role unlimited) and nothing is
  written.
- `--lean on|off|auto` (a bare `--lean` means `on`). `auto` runs one real self-check first and only
  enables Lean when it is `usable`; otherwise the run proceeds and every formal conclusion is
  recorded as `unknown` with the reason named in the reading.
- `--allow-foreign-entries` is the way into a directory that already holds your own material (a
  paper, some notes). Initialization refuses such a directory by default, because building the full
  `data/` and `library/` inside someone else's folder is irreversible; the flag first drops
  `.agentflow-workspace` (the allow-listed marker `store` recognizes) and then initializes without
  deleting or modifying your files. Project workspaces (`--mode project`) do not need it: a
  non-empty `projects/<name>` is adopted and its entries are recorded in the project card.
- `--json` for `--dry-run` carries exactly `mode` / `task` / `workspace` / `project` / `model` /
  `budget` / `lean` / `summons` / `writes` / `spend` (`cli.START_PLAN_KEYS`); for `--watch` without
  a task it is `{url, root, sid, round}`.

The four aliases exist for scripts and for the flags only they expose: `run` (topic pipeline,
`--out` / `--fulltext`), `run-agent <ROLE>` (one role loop, `--drive` / `--rounds`),
`project run` (project workspace; it reads `--projects-dir`, never `--root`), and `web` (the server
alone, with `--allow-writes` / `--no-settings-write`). A `start` with `--root` but without
`--projects-dir` resolves `--project` under `<root>/projects` — that one rule lives only in `start`.

## Agent Loop Mode

`run-agent <ROLE>` drives one role's loop with the model. The shape is the same for every role: a system prompt assembled from the role's declaration, a tool surface filtered to that role's authority, a step loop, and a final message.

Useful flags:

- `--task` — the work item (required).
- `--budget-usd` — hard cap for this run; given explicitly it is also written to the budget register.
- `--max-steps` — a step-accounting reporting threshold; it does not force a finish.
- `--wall-clock-sec` — omitted means no limit; an explicit value bounds the run.
- `--resume` — continue a previous run, from checkpoint or from the session transcript.
- `--sid` — session id, so separate runs stay separate.
- `--stop-file` — the stop switch this run watches.

Exit codes are part of the contract — six of them, from one table (`cli.EXIT_CODE_BY_STOP`):

| Code | Meaning |
|---|---|
| `0` | finished with a `final` |
| `1` | abnormal behaviour (not wired / key not recognized / no reply / unreachable / output capped / bad JSON or bad args over the limit / no notify), and any unregistered `stop_reason` |
| `2` | the run never started (checkpoint unreadable, task fingerprint mismatch, previous run already closed, step not reconstructable), or a usage error |
| `3` | paused waiting for a user answer (`waiting_for_user`); answer it, then `--resume` |
| `4` | stopped normally mid-way: user stop, parent stop, or budget exhausted |
| `5` | stopped normally without a `final` (no progress / escalated to the caller) |

## Research Mode

A research run is a loop driven by the conductor. Each dispatched role returns a payload preview, a summary, and its own readings; the conductor reads them, updates the ledger, and dispatches again.

What lands on the ledger is what downstream judges read:

| Table | Holds |
|---|---|
| `literature` | retrieved documents with provenance and extraction status |
| `statements` | registered claims with evidence kind, quote verification, and five-bit evidence |
| `conjectures` | testable conjectures with explicit criteria |
| `attack_plans` | attack plans and their step history |
| `experiments` | runs with method, result, verifier output, and exit code |
| `documents` | manuscripts with claims and citations |
| `review_findings` | review findings with level and target |
| `research_questions` | the questions the run is actually pursuing |
| `dependencies` | what depends on what, including refutations |
| `relations`, `analysis_reports` | the relation layer produced by role C |
| `search_requests`, `reprocess_requests` | request queues with terminal states |
| `lit_candidates` | the pending-literature list: candidates admitted into, or rejected from, the library |
| `tasks`, `usage_ledger`, `eval_results` | who did what, what it cost, and how it was scored |

A run that produces experiments and conjectures but no manuscript is a normal intermediate state: manuscripts are written when there is something to write.

## Sessions and Continuation

Every step is an event in `sessions/<sid>.jsonl`. Two things follow:

- A run can be **continued** from its checkpoint; when no checkpoint was written (a killed run), the framework rebuilds from the transcript rather than replaying from step one.
- A run can be **inspected** after the fact: which role did what, with which arguments, and what came back.

A user can interject mid-run. Interjections are delivered to the conductor at the next step boundary, are recorded as events, and are marked as seen with the step number, so "was it received" is a readable fact rather than a guess.

## Ledger and Retrieval

Every table is a JSON snapshot; every write is also appended to `events.jsonl`. `rebuild` replays the event log into the snapshots, which is why a damaged snapshot is recoverable and an audit can be re-run.

Reads are cheap and writes are transactional: writes take a per-table file lock, so concurrent roles cannot interleave a partial row.

`table.schema` reflects the live schema rather than a hand-written document, and it accepts a single table name so a caller can ask for exactly the one it needs.

## Roles, Skills, and Tools

A role is declared once: its actions, its edges, its write sets, and its local notes. The tool surface, the call-time authority check, and the capability table are all derived from that declaration, so "who may write what" has one definition.

Read-only roles (C analysis, H review, V verification) receive no write tools structurally; the few ledger-writing proxies they do have are registered one by one, each with a written reason (`tools/base.py`'s `READONLY_CALL_EXCEPTIONS`).

Skills are per-role documents under `skills/`; they are materialised from a catalogue and refreshed when the catalogue changes. They teach method, not authority.

## Experiments and Python Tools

Role E runs experiments through one entry point with four methods: `numeric`, `symbolic`, `exhaustive_search`, and `formal`.

- Every run records its method, its result (`supports` / `refutes` / `inconclusive`), its evidence kind, and its observations.
- A `formal` run requires a Lean source file, records the checker's own output and its real exit code, and can only claim `proof` when the checker says so.
- A refutation is a first-class result: `refutes` rows are what stop a line of research.
- Experiment scripts live under `code/`, and their paths are recorded on the experiment row, so a result can be re-run.

## Verification and Evidence

Strength is a grade, not a slogan:

| Evidence kind | Meaning |
|---|---|
| `proof` | a checker ran and its verbatim output is recorded |
| `proof_review` | a proof was reviewed line by line |
| `cross_check` | another method corroborated it |
| `heuristic` | plausible, no independent backing |

Rules that are enforced rather than suggested:

- `proof` requires the checker's output, a matching subject key, and a non-empty proof text.
- The five-bit evidence model says a true `proof` bit must be findable in the table that owns proofs; otherwise it is an error.
- A statement claiming `proof` without a formal experiment behind it is reported by the audit.
- A review report and a ledger verdict are separate records on purpose: the report is the reviewer's written opinion, the ledger is the mechanical verdict. Both are readable, and neither silently overwrites the other.

`verify` checks invariants across tables — dangling references, claims resting on unusable claims, unverified literature claims, cost attribution, request closure — and exits non-zero on an error-level finding.

## Lean Modes

Formal work has two independent switches:

- `--lean on|off|auto` on `start`, `run`, and `project` (a bare `--lean` means `on`). It normalizes
  to `AGENTFLOW_LEAN_ENABLED=1` / `=0` for the length of that run, so on `start` it reaches the
  agent loops too (role and research modes). Not passing it touches nothing: "this command never
  mentions Lean" and "this command wants Lean off" are two different things.
- `AGENTFLOW_LEAN_ENABLED` / `toolchain.lean_enabled`. It gates formal tools, experiments, wording
  ceilings, and prompt rewriting.

`--lean auto` runs one real self-check first (`refresh=True`, never a stale cache) and enables Lean
only when the result is `usable`. Otherwise the run proceeds as a no-Lean run: every formal
conclusion is recorded as `unknown` and the reason is named in the reading — that is the guard
against a fake Lean environment, where a five-line echo binary prints a version and always exits 0.

When Lean is unavailable or disabled, formal experiments are refused in a controlled way and no row can claim `proof`. The refusal distinguishes "the user turned it off" (`lean_disabled`) from "this machine has no backend" (`no_backend`), because the two fixes are different.

### Setting up a Lean toolchain

The toolchain is **not** shipped in this repository. Install it once and point the
settings at it; nothing else in the framework needs it.

**1. Get Lean 4.7.0 — the version this repo was measured against.** (The self-check
requires major version 4; a different 4.x is accepted but untested.) Either the
official Windows/Linux release archive, or `elan`:

```bash
elan toolchain install leanprover/lean4:v4.7.0
```

A convention that keeps the workspace tidy (this directory is git-ignored):

```
<repo>/_env/lean470/lean-4.7.0-windows/bin/lean.exe
<repo>/_env/mathlib-pinned2/mathlib4-4.7.0/          # optional, for Mathlib imports
```

**2. Point the settings at it.** Paths are resolved relative to the repository
root, not to `agentflow/`:

```json
{
  "toolchain": {
    "lean_enabled": false,
    "lean_bin": "_env/lean470/lean-4.7.0-windows/bin",
    "mathlib_root": "_env/mathlib-pinned2/mathlib4-4.7.0"
  }
}
```

`lean_enabled` stays `false` until you want formal work: leaving it off is the
default and is what a no-Lean run looks like.

**3. Check the reading before trusting it.**

```bash
python -c "import sys; sys.path.insert(0, 'agentflow/src');
from agentflow import toolchain as TC; r = TC.toolchain_report();
print(r['lean_ready'], r['lean_path'], r['lean_version'])"
```

`lean_ready=True` and a real `lean_version` string mean the bridge found a
working binary. `lean_path=''` means it did not — and then every formal call
refuses with `no_backend`, which is a different message from `lean_disabled`.

**4. Turn formal work on**: the gate is `AGENTFLOW_LEAN_ENABLED=1` (or
`toolchain.lean_enabled: true`), and `--lean on` / `auto` sets it for the length
of one run on `start`, `run`, and `project`. `can_do_formal` is the combined
reading: the gate is on **and** the self-check came back `usable` (version,
sha256, a positive sample accepted, a false statement rejected) — a binary that
merely prints a version is `unusable`, not "ready".

`Mathlib` is only needed when the formalized statement imports it. A
self-contained lemma (for example `theorem t : (1 : Nat) + 1 = 2 := rfl`) proves
without it, which is enough to exercise the whole bridge end to end.

`docs/LEAN-MODES.md` carries the full matrix: what each role may do in each mode, which actions are refused, what the evidence ceiling is, and what each closing cell checks.

## Budget and Stop Control

- `--budget-usd` caps a run; every model call is charged to the usage ledger with its task attribution.
- `budget` shows the pool, sets it, or adds to it.
- `stop` stops gracefully: the running loop finishes its current step, sub-processes are terminated, and the stop is recorded with its reason and consumer.
- `stop --force` terminates the registered process tree.
- `stop --status` reports whether the switch exists, which processes are still alive, and which runs consumed a stop.
- `stop --clear` removes a leftover switch; while one exists, a new run refuses to start.

## Files and Paths

Paths inside a workspace are relative to the workspace root. The framework does not write outside it, and a path that escapes is rejected rather than resolved.

The distinction that matters in practice:

- `source/` is **input**: anything you drop there is treated as given and is never modified.
- `out/` is **output**: manuscripts, PDFs, acceptance tables, review reports, the roster tree.
- `data/` is the **record**: snapshots plus events.
- `sessions/` is the **trace**: one append-only event log per session (`sessions/<sid>.jsonl`),
  which is also where a run is resumed from when no checkpoint was written.
- `runs/` is the **control plane**: pid registrations (`<role>-<sid>.pid`), the stop switch, the
  stop/interrupt history, and per-child interrupt signals. It holds no transcripts.

## Runtime Layout

```
<workspace>/
  data/                  ledger snapshots (one JSON per table) + events.jsonl
  source/                inputs (papers, drafts) — read only
  code/                  experiment scripts produced by the agents
  library/               extracted text of retrieved documents
  manuscripts/           handoff records between roles
  notes/                 per-role notes
  out/paper/             manuscripts, PDFs, acceptance tables
  out/review/            review reports and status reports
  out/roster/            roster files (one <parent-id>.jsonl per parent) + index files
  runs/                  pid registrations, stop switch, stop/interrupt history
  sessions/              append-only session event logs
  skills/                per-role skill documents
  verifications/         verification receipts
  budget.json            the budget register (only after a budget was set once)
```

## Command Line

The parser currently exposes 28 subcommands: `build_parser()` is the source of truth. The top-level
`--help` now prints four verb groups (`incubate` / `inspect` / `run` / `serve`, table:
`cli.COMMAND_GROUPS`) plus a short "the old names still work" note; the full 28-row mapping is
`agentflow --help-legacy` (and `docs/USER-GUIDE.md` §7.2).

```text
incubate   init start stop status answer inbox submit
inspect    status-report stats evidence artifacts analyze tools cache budget doctor verify
run        topic(=old run) pipeline run-a run-b run-agent repair rebuild project closing
serve      web demo
```

The group names are not subcommands: `cli.canonical_argv` folds `agentflow inspect stats` back to
`agentflow stats` before parsing, so every old name keeps its flags, defaults, output, and exit
codes byte for byte (the count stays 28). `agentflow run` (no member) is still the old topic run;
its group page is `agentflow run --help`.

The legacy names, grouped the way they were before this change (kept here as an index:

```
研究（跑一次研究）
  start        one entry point: what to do / where / how much / Lean on or off
  run          end-to-end topic run (retrieval -> answer -> quote verify -> ledger -> artifacts)
  run-agent    run one role loop (model driven); exit codes 0-5
  run-a        run agent A
  run-b        run agent B
  submit       submit a search request
  analyze      relation analysis (role C)
  pipeline     orchestrate C -> D -> (A -> B -> D) rounds
  closing      run the closing gate (8 cells; exit 0 / 1 / 2)

项目（工作区与产物）
  project      project workspaces: list / plan / run / create
  evidence     evidence surface: verify / store / migrate
  artifacts    artifact ownership: record / list / verify / owners / unowned / report
  status-report  project status report (read-only; lands out/review/STATUS-<ts>.{md,json})
  answer       answer a question on the user's behalf
  inbox        questions waiting for a user answer

诊断（看清这台机器与这一趟）
  status       table statistics
  verify       global invariant check (exit 1 on error)
  tools        list the tool surface per role
  doctor       machine check (no model calls; 0 complete / 1 something missing / 2 could not check);
               `doctor --selfcheck` compiles every file in the package instead; every failing
               item carries a `fix_hint` (a command you can copy and run)
  budget       show / set / add to the run budget
  stop         stop a running run-agent (graceful by default)
  cache        two-tier prompt cache: `status` (read-only: landed / fresh / covered / missing,
               plus the key-change reminder) and `warm --lean on|off|both [--dry-run]`
               (real warm-up spends money; `--dry-run` spends 0)
  stats        four read-only readings (`errors` wrong actions per role, `flow` actions / blocked /
               relayed per role, `cost` money and tokens per role and per stage, `gates` the eight
               closing-gate cells) plus `all`; three-state (`checked` / `unknown`) so "nothing
               happened" and "could not read" never share a value; `inspect stats … --json` returns
               the four-key envelope (see `docs/CLI-CONTRACT.md`)

运维（数据维护与界面）
  init         initialize data directories and empty tables
  rebuild      rebuild snapshots from events.jsonl
  repair       recompute derived fields
  demo         offline end-to-end demo
  web          start the user-facing web server
```

`repair`, `rebuild`, `demo`, and `evidence migrate` are staging tools: their implementation now
lives in `tools/legacy_cli/` and the CLI keeps a one-line forward (byte-identical output; the next
version deletes them).

Four of them are aliases of the `start` execution body (`cli._run_spec`) and keep their old flags,
defaults, and `--help` output verbatim: `run`, `run-agent`, `project run`, and `web`.

> 旧流水线教学段（`project plan` / `project run` 那一套）**已退场**：子命令本身保留可达，
> 但"怎么跑那套旧流水线"的整段教学已删除。逐字留痕与理由见 `draft/65a` §A-2。

## Testing

```bash
python -m pytest -q
```

The full suite collects 6401 tests (2026-10-23 reading); 28 of them are marked `network` and
deselected by `pyproject.toml`, so a default run is 6373. Re-measure with
`python -m pytest --collect-only -q` (about 20 seconds); a full run takes tens of minutes. Much of
it is judge-style: it asserts what the framework refuses, not only what it produces. Single files
run in seconds:

```bash
python -m pytest -q tests/test_user_quickstart.py
python -m pytest -q tests/test_lean_modes_matrix.py
```

## Troubleshooting

- **`lean_disabled` on a machine that has Lean** — the setting is separate from the CLI flag. Set `toolchain.lean_enabled` or `AGENTFLOW_LEAN_ENABLED=1`.
- **A run exits at once** — check `stop --status`; a leftover stop switch makes every new run finish at step zero.
- **`--resume` cannot find a checkpoint** — it falls back to the session transcript; if that is empty too, the run never produced a step.
- **`verify` exits non-zero** — the message names the table and the row. Most findings are dangling references or a claim whose evidence kind is stronger than its backing.
- **A run ends without a manuscript** — check `documents` and `out/`; the closing gate reports which acceptance cells could not be computed.
- **A role cannot call a tool it "should" have** — the call-time authority check is authoritative, and `tools --role <R>` prints the surface that role actually receives.

## Status

Feature-complete for the research loop, with a judge-backed test suite and a real-machine record on two task shapes: a review-and-revise paper package, and a from-scratch research question. Known limits are documented rather than hidden — a no-Lean run cannot produce `proof`-grade evidence, graceful stop stops the run that consumes the switch, and a tool that never observes its deadline is recorded as `deadline_passed_unobserved` instead of being force-killed.

## License

See the repository root for license information.

## Repository facts（读数，判据在守）

这一节是**机器会核对的读数**——每个数字都有判据盯着，改它必须同时改判据认的那个来源。

```
agentflow/.noai-paths            禁改区清单（**46** 条 glob / **43** 条唯一路径，**7** 个分组）
agentflow/src/agentflow/tools/   **19** 个 `*_tools.py`（工具层按角色装配，见 `python -m agentflow.cli tools`）
```

两个工具面读数，口径不同、不许互换：**95** 是 Lean 关着时各角色面的并集（`python -m agentflow.cli tools` 那一档，
`formal.*` 三件与 L 不在面里）；**98** 是全库声明的工具件数（Lean 开着，判据 `tests/test_tools_returns_declaration.py`
的 `TOOL_COUNT` 钉的是这一格）。

三个带 `--json` 出口的脚本（`scripts/lint_rules.py`、`tools/release_all.py`、`tools/run_each_test_file.py`）
一律 `open(..., newline="")` 写文件，**不经过 `Path.write_text`** ⇒ 当次产物的行尾是
**CR=0**（纯 LF），与他平台无关。

lint 规则范围 **R001–R012**（规则 12 条；`R004`/`R006` 已退休并登记去向，见 `scripts/lint_rules.py` 的 `RETIRED_RULES`）。
