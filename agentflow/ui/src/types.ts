// 生成物，勿手改；改 `agentflow/web/emit_types.py` 再重跑：
//   python -m agentflow.web.emit_types
//
// 唯一类型来源（`draft/75 §1` 的 C3 契约）：字段名逐字对应后端它自己的键，
// 不许在这里改名，也不许把后端一定会给的键写成可选。对齐由两条判据守着：
//   - 名字层：`tests/test_webui_contracts.py` 的 C 条（生成物键集合 vs 后端真读数）；
//   - 类型层：`pnpm typecheck`（`tsc --noEmit`，配 `strict` + `noUncheckedIndexedAccess`）。
//
// 手改本文件的任何一处都会让 C 条与新鲜度判据变红 —— 那是刻意的。

/** 三态（reviewaccept 词表）：算出来了 / 没查成 / 用不着。 */
export type Tri = "computed" | "unreadable" | "not_applicable";

/** 交付说明那一格专用的三态（`webui/state.py` 的 `_read_report`）。 */
export type ReportTri = "ok" | "missing" | "unknown";

/** 出处：option_view() —— 一个选项的渲染视图（注意：快照里的 `options` 是这一族对象，不是裸字符串；`draft/75 §1.3` 那里写的 `string[]` 与盘上读数不一致，以这里为准）。 */
export interface OptionRow {
  label: string;
  description: string;
  multi: boolean;
}

/** 出处：orphan_summary() 的 `groups[]` 元素 —— 按会话分组的「轮次之外的零散事件」。 */
export interface OrphanGroup {
  sid: string;
  count: number;
  kinds: string[];
  first_ts: string;
  last_ts: string;
  first_index: number;
  last_index: number;
}

/** 出处：orphan_summary() —— 「轮次之外的零散事件」的汇总读数。 */
export interface OrphanSummary {
  count: number;
  groups: OrphanGroup[];
}

/** 出处：snapshot() —— 工作区盘上事实的只读投影（返回键逐字见它的 docstring）。 */
export interface StateSnapshot {
  root: string;
  generated_at: string;
  sessions: SessionRow[];
  pending_questions: PendingQuestion[];
  runs: RunRow[];
  orphans: OrphanRow[];
  orphan_summary: OrphanSummary;
  last_run: RunRow | null;
  ledger: LedgerReading;
  problems: string[];
}

/** 出处：snapshot() 的 `sessions[]` —— 一段会话的读盘读数。 */
export interface SessionRow {
  sid: string;
  path: string;
  events_seen: number;
  events_listed: number | null;
  bad_lines: number;
  first_ts: string;
  last_ts: string;
  last_kind: string;
  last_seq: number;
  pending: number;
  runs: number;
  orphans: number;
}

/** 出处：snapshot() 的 `pending_questions[]` —— 一条待答问题（全局，不按会话过滤）。 */
export interface PendingQuestion {
  qid: string;
  sid: string;
  role: string;
  ts: string;
  timeout_sec: number | null;
  text: string;
  options: OptionRow[];
  multi: boolean;
  index: number;
}

/** 出处：snapshot() 的 `runs[]` —— 一趟运行（一条 agent_run_start 到它之后的 agent_run_end）。 */
export interface RunRow {
  sid: string;
  role: string;
  task: string;
  start_index: number;
  start_ts: string;
  steps: number;
  llm_calls: number;
  usd: number | null;
  unknown_usd: number;
  stop_reason: string;
  final_chars: number | null;
  summons: number | null;
  messages: number | null;
  elapsed_sec: number | null;
  last_shape: string;
  end_index: number | null;
  end_ts: string;
  waiting_on: string[];
  waiting: boolean;
  events_in_run: number;
}

/** 出处：snapshot() 的 `orphans[]` —— 轮次之外的一条零散事件（不许折成一趟运行）。 */
export interface OrphanRow {
  sid: string;
  index: number;
  kind: string;
  ts: string;
  role: string;
}

/** 出处：snapshot() 的 `ledger` —— 台账（第二个独立读数）。 */
export interface LedgerReading {
  path: string;
  events: number | null;
  tables: number | null;
  note: string;
  tables_note: string;
}

/** 出处：_read_report() —— 交付说明 `out/review/REPORT.md` 的读数（二元组 status/text 的字典口径）。 */
export interface ReportReading {
  status: ReportTri;
  text: string;
}

/** 出处：检查点里的花销子树（`agent_loop` 写的 `runs/agent-<角色>-<sid>.json`）。 */
export interface CheckpointSpend {
  calls: number;
  tokens_in: number;
  tokens_out: number;
  usd: number | null;
  unknown_usd_calls: number;
}

/** 出处：一趟的检查点文件（`runs/agent-<角色>-<sid>.json`；本批没有 reader ⇒ 判据 C 不覆盖它）。 */
export interface Checkpoint {
  role: string;
  sid: string;
  task: string;
  fingerprint: string;
  step: number;
  stop_reason: string;
  waiting_for: string[];
  spend: CheckpointSpend;
  at: string;
}

/** 出处：写面端点的统一回执（W3/W4 才有生产者 ⇒ 判据 C 不覆盖它；`id`/`extra` 只是「有就带上」的两栏，所以写成可选）。 */
export interface WriteResult {
  ok: boolean;
  tri: Tri;
  reason: string;
  id?: string;
  extra?: Record<string, unknown>;
}

// --------------------------------------------------------------------------
// 欠账清单：这些接口本批不生成（没有真读数就没有类型）。
// 每一条都写明缺哪一个 reader —— 补上读数之后，把那一行从对应模块的
// `MISSING_TYPES` 里删掉，并把接口加进那个模块的 `type_decls()`。
// --------------------------------------------------------------------------
// TODO RunView：缺本模块的「一趟详情」适配器（W1）；本批 ROUTES 里没有 `GET /api/run/{sid}`，所以它没有生产者。
// TODO EvidenceView：缺 `readers.evidence_chain(store)`（W1）：`store.rows("statements"/"conjectures"/"experiments"/"review_findings")` 的适配器。
// TODO ArtifactsView：缺 `readers.artifact_ledger` / `readers.handoffs` / `readers.run_products`（W1）：`artifacts.read_ledger` · `manuscripts.rows` · 六件产物那一路。
// TODO AcceptanceView：缺 `readers.acceptance(root, ...)`（W1）：`reviewaccept.check_review` 的逐条读数。
// TODO MachineView：缺 `readers.machine_readings(root)`（W1）：`toolchain.toolchain_report()` 与 `settings.load_settings()`（key 走 `ModelSpec.redacted()`）。
// TODO TaskRow：缺 `store.rows("tasks")` 的适配器（W1 的 readers 那一面）。
// TODO SearchRequestRow：缺 `store.rows("search_requests")` 的适配器（W1）。
// TODO ConjectureRow：缺 `store.rows("conjectures")` 的适配器（W1）。
// TODO ExperimentRow：缺 `store.rows("experiments")` 的适配器（W1）。
// TODO ArtifactRow：缺 `artifacts.read_ledger` 的行适配器（W1）。
// TODO HandoffRow：缺 `manuscripts.rows` 的行适配器（W1）。
// TODO SecretaryDecision：缺 `secretary.decisions_path` 的读法（W1）。
// TODO AcceptanceCheck：缺 `closing.py` 的 ACCEPTANCE-CHECKS 读者（W1）。
// TODO ReportStyle：缺 `out/review/REPORT-STYLE.json` 的读者（W1）。
// TODO UsageRow：缺 `store.rows("usage_ledger")` 的适配器（W1）。
