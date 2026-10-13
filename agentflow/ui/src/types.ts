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

/** 出处：趟次索引里的一场会话（`sessions.compute_run_index` 的 `sessions[sid]`）。 */
export interface RunIndexSession {
  runs: RunRow[];
  last_end_index: number | null;
  digest: string;
}

/** 出处：`GET /api/run-index` 的 `index` 那一栏 —— 趟次索引本体（裁定 O2；`sessions.compute_run_index` / `rebuild_run_index` 落的盘上那一份）。 */
export interface RunIndex {
  version: string;
  generated_at: string;
  sessions: Record<string, RunIndexSession>;
}

/** 出处：`GET /api/run-index` 的返回值 —— `sessions.run_index_report(root)` 逐字：索引可用性与它与事件现算结果的对账结论（`tri != "computed"` ⇒ 显红）。 */
export interface RunIndexDrift {
  usable: boolean;
  tri: Tri;
  reason: string;
  drift: string[];
  sessions: string[];
  index: RunIndex | null;
}

/** 出处：run_products() —— 六件产物里的一件（`runflow.ARTIFACTS` 那六个名字）。 */
export interface RunProduct {
  name: string;
  path: string;
  exists: boolean;
  bytes: number | null;
  lines: number | null;
  sha256: string;
  tri: Tri;
}

/** 出处：检查点的花销子树（`llmseam.SeamSpend.to_dict()`：calls/tokens_in/tokens_out/usd/unknown_usd_calls）。 */
export interface CheckpointSpendView {
  calls: number;
  tokens_in: number;
  tokens_out: number;
  usd: number | null;
  unknown_usd_calls: number;
}

/** 出处：检查点文件 `runs/agent-<角色>-<sid>.json`（`agent_loop.save_run_checkpoint`）。 */
export interface CheckpointView {
  role: string;
  sid: string;
  task: string;
  fingerprint: string;
  step: number;
  stop_reason: string;
  waiting_for: string;
  spend: CheckpointSpendView | Record<string, never>;
  at: string;
}

/** 出处：run_view() 的 `report` —— 交付说明 `out/review/REPORT.md` 的读数。 */
export interface ReportReadingView {
  status: ReportTri;
  text: string;
}

/** 出处：run_view() —— 一趟详情（`Run` + `report` + `checkpoint`）。 */
export interface RunView {
  tri: Tri;
  reason: string;
  sid: string;
  runs: RunRow[];
  report: ReportReadingView;
  checkpoint: CheckpointView | null;
  checkpoint_reason: string;
  path: string;
}

/** 出处：run_events() 的一行 —— 会话里的一条事件（`index` 与 `RunRow.start_index`/`end_index` 同一套编号：解析成功后的事件列表下标，0 起）。 */
export interface EventRow {
  index: number;
  kind: string;
  ts: string;
  role: string;
  shape?: string;
  ok?: boolean;
  usd?: number | null;
  tokens_in?: number;
  tokens_out?: number;
  payload?: Record<string, unknown>;
  result?: Record<string, unknown>;
  text?: string;
  stopped?: boolean;
}

/** 出处：run_events() —— 一趟的逐条事件（游标分页：`from_index` 闭、`to_index` 开，`to_index` 直接可当下一次的 `since_index`）。 */
export interface RunEventsView {
  tri: Tri;
  reason: string;
  sid: string;
  total: number | null;
  from_index: number | null;
  to_index: number | null;
  truncated: boolean;
  events: EventRow[];
}

/** 出处：evidence_chain() —— 证据链七栏（各栏另带 `<栏>_tri`）。 */
export interface EvidenceView {
  tri: Tri;
  reason: string;
  store_problems: string[];
  statements: StatementRow[];
  statements_tri: Tri;
  conjectures: ConjectureRow[];
  conjectures_tri: Tri;
  experiments: ExperimentRow[];
  experiments_tri: Tri;
  review_findings: ReviewFindingRow[];
  review_findings_tri: Tri;
  relations: RelationRow[];
  relations_tri: Tri;
  verifications: VerificationRow[];
  verifications_tri: Tri;
  secretary: SecretaryDecision[];
  secretary_tri: Tri;
}

/** 出处：artifacts_face() —— 产物面（各栏另带 `<栏>_tri`）。 */
export interface ArtifactsView {
  tri: Tri;
  reason: string;
  ledger: ArtifactRow[];
  ledger_tri: Tri;
  ledger_verify: LedgerVerifyRow[];
  ledger_verify_tri: Tri;
  handoffs: HandoffRow[];
  handoffs_tri: Tri;
  checks: AcceptanceCheck[];
  checks_tri: Tri;
  style: ReportStyle;
  style_tri: Tri;
  secretary: SecretaryDecision[];
  secretary_tri: Tri;
  products: RunProduct[];
  products_tri: Tri;
  run_dir: string;
  products_reason: string;
  tasks: TaskRow[];
  tasks_tri: Tri;
}

/** 出处：acceptance_face() —— 内容级验收（键名逐字来自 reviewaccept.CRITERIA 与 AUXILIARY_SIGNALS）。 */
export interface AcceptanceView {
  tri: Tri;
  reason: string;
  criteria: Record<string, string>;
  details: Record<string, string>;
  auxiliary: Record<string, string>;
  failed: string[];
  auxiliary_note: string;
}

/** 出处：machine_face() 的 `settings` —— 设置文件三段（key 只给掩码后的那一份）。 */
export interface SettingsReading {
  path: string;
  exists: boolean;
  toolchain: Record<string, string>;
  model: { api_key: string; base_url: string; name: string; reasoning_effort: string; key_source: string; configured: boolean };
  workspace: Record<string, string>;
  raw_keys: string[];
}

/** 出处：machine_face() —— toolchain.toolchain_report() 的键 + 设置三段。 */
export interface MachineView {
  tri: Tri;
  reason: string;
  model: Record<string, unknown>;
  provers: Record<string, unknown>;
  lean_enabled: boolean;
  lean_enabled_source: string;
  formal_mode: string;
  lean_ready: boolean | null;
  lean_path: string;
  lean_version: string;
  mathlib: Record<string, unknown>;
  can_do_formal: boolean | null;
  settings: SettingsReading;
  settings_tri: Tri;
  settings_reason: string;
}

/** 出处：budget.reading() 的 `added[]` 一行（`budget._write` 写进寄存器的那一笔）。 */
export interface BudgetEntry {
  kind: string;
  usd: number;
  by: string;
  at: string;
  note: string;
}

/** 出处：budget_face() —— 总额度（寄存器）+ 已花（`usage_ledger`）与两个归口。 */
export interface BudgetView {
  tri: Tri;
  reason: string;
  path: string;
  exists: boolean;
  source: string;
  total_usd: number | null;
  spent_usd: number | null;
  remaining_usd: number | null;
  exceeded: boolean;
  added: BudgetEntry[];
  problem: string;
  spent_tri: Tri;
  spent_reason: string;
  entries: number | null;
  tokens: number | null;
  attempts: number | null;
  added_count: number;
  by_role: Record<string, UsageBucket>;
  by_scope: Record<string, UsageBucket>;
}

/** 出处：tokenmeter.by_role() / by_scope() 的一格（`{tokens, usd, entries, attempts[, roles]}`）。 */
export interface UsageBucket {
  tokens: number;
  usd: number;
  entries: number;
  attempts: number;
  roles?: Record<string, number>;
}

/** 出处：live_face() —— 在飞的循环 / 活进程 / 停机开关与历史（行逐字来自 stopctl）。 */
export interface LiveView {
  tri: Tri;
  reason: string;
  root: string;
  answer: string;
  running: Array<Record<string, unknown>>;
  live: Array<Record<string, unknown>>;
  unreadable_sessions: string[];
  switch: Record<string, unknown>;
  switch_present: boolean;
  history: Array<Record<string, unknown>>;
  interrupts: Array<Record<string, unknown>>;
}

/** 出处：usage_face() —— usage_ledger 的汇总（总计 + 两个归口 + 重试开销 + 最近几笔）。 */
export interface UsageView {
  tri: Tri;
  reason: string;
  path: string;
  entries: number | null;
  spent: Record<string, unknown>;
  by_role: Record<string, UsageBucket>;
  by_scope: Record<string, UsageBucket>;
  retry_overhead: Record<string, unknown>;
  recent: Array<Record<string, unknown>>;
}

/** 出处：status_reports_face() 的一行 —— `out/review/STATUS-<ts>.{md,json}` 的一份。 */
export interface StatusReportRow {
  name: string;
  stem: string;
  path: string;
  json_path: string;
  bytes: number | null;
  ts: string;
}

/** 出处：status_reports_face() —— 状态报告最近几份（`statusreport` 写了没人读的那个缺口）。 */
export interface StatusReportsView {
  tri: Tri;
  reason: string;
  dir: string;
  count: number | null;
  reports: StatusReportRow[];
}

/** 出处：chat_face() 的 options[] 一项（`userio.option_view` 渲染视图里的两栏）。 */
export interface ChatOption {
  label: string;
  description: string;
}

/** 出处：chat_face() —— 一条对话线（`who` 只有 user / conductor / team 三档，见 CHAT_WHO）。 */
export interface ChatLine {
  index: number;
  who: string;
  role: string;
  kind: string;
  ts: string;
  title: string;
  text: string;
  clipped: boolean;
  qid?: string;
  options?: ChatOption[];
}

/** 出处：chat_face() 的 sessions[] —— 供对话页挑会话（`sessions.list_sessions` 的四栏）。 */
export interface ChatSession {
  sid: string;
  last_ts: string;
  events: number;
  bad_lines: number;
}

/** 出处：chat_face() —— 一段会话的对话读数（有界：只给最近的 lines_max 条，截断逐条标明）。 */
export interface ChatView {
  tri: Tri;
  reason: string;
  sid: string;
  lines: ChatLine[];
  total: number;
  shown: number;
  clipped: boolean;
  sessions: ChatSession[];
}

/** 出处：store.rows("statements")（无真机样本 ⇒ 权威来源是 `schema.Statement`）。 */
export interface StatementRow {
  stmt_id: string;
  origin: string;
  kind: string;
  label: string;
  statement_text: string;
  statement_full: string;
  proof_text: string;
  source_lit_id: string;
  page_range: string;
  quote_verified: boolean | null;
  quote_reason: string;
  evidence_kind: string;
  bits: number;
  status: string;
  derived_from: string;
  doc_id: string;
  line_range: string;
  created_at: string;
  created_by: string;
}

/** 出处：store.rows("review_findings")（无真机样本 ⇒ 权威来源是 `schema.ReviewFinding`）。 */
export interface ReviewFindingRow {
  finding_id: string;
  doc_id: string;
  kind: string;
  level: string;
  target: string;
  evidence: string;
  message: string;
  round: number;
  suggestion: string;
  status: string;
  resolution_note: string;
  created_at: string;
  created_by: string;
  axis: string;
  line: number | null;
  verbatim_quote: string;
  maths: string;
  line_unavailable_reason: string;
}

/** 出处：store.rows("relations")（无真机样本 ⇒ 权威来源是 `schema.Relation`）。 */
export interface RelationRow {
  relation_id: string;
  concept_ids: string[];
  description: string;
  lit_id: string;
  page_range: string;
  quote: string;
  quote_normalized: string;
  quote_verified: boolean | null;
  statement: string;
  concept_group_key: string;
  dedup_key: string;
  status: string;
  duplicate_of: string;
  created_at: string;
  supporting_lit_ids: string[];
}

/** 出处：verifications.list_verifications()（裁定 K2：无真机样本 ⇒ 夹具造一行）。 */
export interface VerificationRow {
  verification_id: string;
  statement_id: string;
  verifier: string;
  verdict: string;
  defect_step: string;
  quote: string;
  why: string;
  findings: Record<string, unknown>[];
  unresolved_errors: number;
  proof_sha256: string;
  proof_chars: number;
  round: number;
  used_faces: string[];
  submission_id: string;
  at: string;
}

/** 出处：artifacts.read_ledger() 的行（`artifacts.FIELDS` 九个键，真机 ARTIFACTS.jsonl 同形）。 */
export interface ArtifactRow {
  at: string;
  path: string;
  sha256: string;
  bytes: number;
  producer: string;
  kind: string;
  task_id: string;
  exit_code: number | null;
  note: string;
}

/** 出处：artifacts.verify_entries() 的行 —— 台账钉的 sha 与盘上现在这一版是不是同一版。 */
export interface LedgerVerifyRow {
  path: string;
  sha256: string;
  producer: string;
  at: string;
  sha256_now: string;
  status: string;
}

/** 出处：manuscripts.read_rows() 的行（`manuscripts.write` 写的 14 个键；`revises`/`kind`/`ref_problems` 是「有就带上」的三栏）。 */
export interface HandoffRow {
  id: string;
  to: string;
  sender: string;
  summary: string;
  body: string;
  refs: string[];
  sha256: string;
  sid: string;
  task_id: string;
  format: string;
  bytes: number;
  path: string;
  note: string;
  created_at: string;
  revises?: string;
  kind?: string;
  ref_problems?: Record<string, string>;
}

/** 出处：out/secretary/<角色>.jsonl（老文件）与 out/secretary/<角色>-<实例号>.jsonl（S1m 起的分片）的行（`secretary.Secretary.note_decision` 写的；`decision`/`reason`/`basis` 等是「有就带上」的几栏）。`task_id` 是 S1m 补的那一格：分片之后「这一行是哪一个实例写的」必须读得出来。 */
export interface SecretaryDecision {
  role: string;
  seq: number;
  at: string;
  kind: string;
  duty: number;
  from: string;
  fail_open: boolean;
  task_id?: string;
  decision?: string;
  judge?: Record<string, unknown>;
  reason?: string;
  basis?: string[];
  before?: string;
  target?: string;
}

/** 出处：out/paper/ACCEPTANCE-CHECKS.json 的一行（真机 8 行 C1–C8；`closing.ACCEPTANCE_CHECKS_NAME`）。 */
export interface AcceptanceCheck {
  id: string;
  kind: string;
  min: number;
  name: string;
  note: string;
}

/** 出处：out/review/REPORT-STYLE.json 的 `sections`（真机四节名字）。 */
export interface ReportStyle {
  sections: string[];
}

/** 出处：store.rows("tasks")（真机 p9b/data/tasks.json 19 键 + 工作项板那 7 格；板那 7 格是 S0/S1b 扩列之后补进来的 —— 真机上它们今天全是空值（`draft/94` §4：2276 行里 `kind` 非空 0 行），但列**在**，所以类型必须跟上）。 */
export interface TaskRow {
  task_id: string;
  role: string;
  action: string;
  called_by: string;
  parent_task_id: string | null;
  depth: number;
  input_key: string;
  status: string;
  outcome: string;
  refusal_reason: string;
  detail: string;
  error: string;
  started_at: string;
  ended_at: string | null;
  tokens: number | null;
  usd: number | null;
  instance: string;
  artifacts: string[];
  inputs: string[];
  kind: string;
  expects: string;
  item_state: string;
  item_close: string;
  seen_by: string;
  seen_step: number | null;
  keep_alive: boolean;
}

/** 出处：store.rows("conjectures")（真机 p9b/data/conjectures.json；无样本时以 `schema.Conjecture` 为准）。 */
export interface ConjectureRow {
  conjecture_id: string;
  statement: string;
  status: string;
  form: string;
  testable: boolean | null;
  origin: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  experiment_ids: string[];
  counterexample_experiment_id: string | null;
  proof_experiment_id: string | null;
  negation_statement: string;
  known_lit_id: string;
  notes: string;
  promoted_to: string;
  withdraw_reason: string;
  duplicate: boolean | null;
}

/** 出处：store.rows("experiments")（真机 p9b/data/experiments.json；无样本时以 `schema.Experiment` 为准）。 */
export interface ExperimentRow {
  experiment_id: string;
  method: string;
  result: string;
  evidence_kind: string;
  negation_kind: string;
  claim: string;
  claim_key: string;
  certificate: string;
  counterexample: string;
  search_bound: string;
  verifier_output: string;
  verifier_subject_key: string;
  code_path: string;
  code_hash: string;
  exit_code: number | null;
  artifact_paths: string[];
  observations: string;
  params: Record<string, unknown>;
  runtime_sec: number | null;
  notes: string;
  created_at: string;
  created_by: string;
  for_question_id: string;
}

/** 出处：store.rows("usage_ledger")（真机 p9b/data/usage_ledger.json 37 行）。 */
export interface UsageRow {
  usage_id: string;
  at: string;
  role: string;
  scope: string;
  task_id: string;
  idem_key: string;
  tokens_in: number;
  tokens_out: number;
  tokens_total: number;
  usd: number | null;
  attempts: number;
  note: string;
}

/** 出处：store.rows("search_requests")（真机 p9b/data/search_requests.json 17 键）。 */
export interface SearchRequestRow {
  request_id: string;
  topic: string;
  mode: string;
  content_description: string;
  providers: string[];
  done: boolean;
  outcome: string;
  priority: string;
  submitted_by: string;
  submit_note: string;
  for_question_id: string;
  claimed_by: string;
  lease_until: string | null;
  attempts: number;
  last_error: string;
  result_lit_ids: string[];
  timestamp: string;
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
