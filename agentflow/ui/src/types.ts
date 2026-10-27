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

/** 出处：snapshot() 的 `ledger` —— 台账（第二个独立读数）。`events` 与 `upserts` 同口径（`D21`：它不再是 events.jsonl 的总行数），`commit_markers` 是其中提交标记的行数。 */
export interface LedgerReading {
  path: string;
  events: number | null;
  upserts: number | null;
  commit_markers: number | null;
  tables: number | null;
  note: string;
  tables_note: string;
  events_note: string;
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
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
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
  prompt_cache: CheckpointCacheView | Record<string, never>;
  at: string;
}

/** 出处：检查点的缓存汇总（`promptstability.summarize_prompt_cache` 的 11 格）。 */
export interface CheckpointCacheView {
  calls: number;
  no_request_calls: number;
  hit: number;
  miss: number;
  unknown_calls: number;
  tokens_in: number;
  hit_rate: number | null;
  mismatched_calls: number;
  saved_usd: number | null;
  saved_unknown_calls: number;
  why: string;
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
  checkpoint_role: string;
  checkpoint_spend_usd: number | null;
  same_run_spend_usd: number | null;
  same_run_unknown_usd: number;
  same_run_start_index: number | null;
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
  experiment_spots: ExperimentSpot[];
  experiment_spots_tri: Tri;
  experiment_spots_reason: string;
  code_exp: CodeExpFile[];
  tasks: TaskRow[];
  tasks_tri: Tri;
}

/** 出处：artifacts_face() 的 experiment_spots[] —— 实验产物的一个落点（`out/experiments/<号>/design.md` / `exhaustion.md` / `.log`；`kind` 是 design / exhaustion / log）。 */
export interface ExperimentSpot {
  kind: string;
  path: string;
  exists: boolean;
  bytes: number | null;
  tri: Tri;
  reason?: string;
}

/** 出处：artifacts_face() 的 code_exp[] —— `code/exp/` 下的一个脚本（相对工作区的路径）。 */
export interface CodeExpFile {
  path: string;
  bytes: number | null;
}

/** 出处：acceptance_face() —— 内容级验收（键名逐字来自 reviewaccept.CRITERIA 与 AUXILIARY_SIGNALS）。 */
export interface AcceptanceView {
  tri: Tri;
  reason: string;
  criteria: Record<string, string>;
  details: Record<string, string>;
  rows: AcceptanceRow[];
  auxiliary: Record<string, string>;
  failed: string[];
  auxiliary_note: string;
}

/** 出处：acceptance_face() 的 rows[] —— 一条验收判据一行（键名来自 reviewaccept.CRITERIA；编号那一格恒为 not_applicable：判据是现算的、不落任何台账行）。 */
export interface AcceptanceRow {
  key: string;
  title: string;
  value: string;
  detail: string;
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
}

/** 出处：machine_face() 的 `settings` —— 设置文件的各段（key 只给掩码后的那一份）。 */
export interface SettingsReading {
  path: string;
  exists: boolean;
  toolchain: Record<string, string>;
  model: { vendor: string; api_key: string; base_url: string; name: string; reasoning_effort: string; key_source: string; configured: boolean };
  models: Record<string, { api_key: string; base_url: string; name: string; vendor: string; reasoning_effort: string; key_source: string; configured: boolean; source: string }>;
  secretary: { api_key: string; base_url: string; name: string; vendor: string; reasoning_effort: string; key_source: string; configured: boolean; source: string; own_slot?: Record<string, string> };
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
  running: LiveLoopRow[];
  live: LivePidRow[];
  unreadable_sessions: string[];
  switch: Record<string, unknown>;
  switch_present: boolean;
  history: Array<Record<string, unknown>>;
  interrupts: Array<Record<string, unknown>>;
}

/** 出处：stopctl.running_loops() 的 running[] —— 还在盘上跑的一趟循环（会话面）。 */
export interface LiveLoopRow {
  role: string;
  sid: string;
  since: string;
}

/** 出处：stopctl.live_pids() 的一行 —— 登记在盘上且真的还活着的一个进程（`path` 是那一份登记文件的落点，`live_pids` 会给）。 */
export interface LivePidRow {
  pid: number;
  role: string;
  sid: string;
  started_at: string;
  path: string;
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

/** 出处：chat_face() —— 一条对话线（`who` 只有 user / conductor / team 三档，见 CHAT_WHO）。`task_id` 是说话那一方的绝对编号，`task_id_source` 只说这个编号从哪来：event（事件里真有）/ inherited（老事件没记，同一岗在本段唯一那一趟的 agent_run_start 有编号 ⇒ 回填）/ missing（拿不准或确实没记，页面显示「（未记录编号）」，绝不编一个假编号）。`role` 是说话那一方的角色，`role_source` 同一条纪律：event（事件自带）/ from（`agent_message` 只记了 `from`，读侧用它补齐，页面括注「承自发件人」）/ missing（两格都没有，页面显示「（未记录角色）」）。 */
export interface ChatLine {
  index: number;
  who: string;
  role: string;
  kind: string;
  ts: string;
  title: string;
  text: string;
  role_source: string;
  task_id: string;
  task_id_source: string;
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
  bits: Record<string, unknown>;
  status: string;
  derived_from: string;
  doc_id: string;
  line_range: string;
  created_at: string;
  created_by: string;
  quote_state: string;
  nontriviality: number | null;
  nontriviality_label: string;
  nontriviality_meaning: string;
  nontriviality_tri: string;
  nontriviality_word: string;
  nontriviality_matched_by: string;
  formal_paths: FormalPath[];
  bit_numeric: string;
  bit_proof: string;
  bit_reviewed: string;
  bit_audited: string;
  reviewed_paths: ReviewedPath[];
  grade: string;
  grade_label: string;
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
}

/** 出处：evidencebits.formal_by_proof() 的一行 —— 五元位第 4 位的一条路径（`proof_no` 是证明号，`state` 取 `evidencebits.FORMAL_PATH_STATES` 的五档：pending / na / failed / verified / stale）。折成一条汇总就等于让 `#p2` 借 `#p1` 的光。 */
export interface FormalPath {
  proof_no: number;
  state: string;
}

/** 出处：evidencebits.reviewed_by_proof() 的一行 —— 五元位第 3 位按证明逐条（`proof_no` 是证明号，`reviewed` 是「这一份签过没有」；签的是不是现在这一份正文由 `VerificationRow.proof_sha_consistency` 回答。只签了 `#p1` 而定理还有`#p2` 时 `#p2` 是 false —— 折成一句「审过」就等于让它借 `#p1` 的光）。 */
export interface ReviewedPath {
  proof_no: number;
  reviewed: boolean;
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
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
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
  quote_state: string;
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
}

/** 出处：verifications.list_verifications()（裁定 K2：无真机样本 ⇒ 夹具造一行）。 */
export interface VerificationRow {
  verification_id: string;
  statement_id: string;
  stmt_id: string;
  proof_no: number;
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
  proof_sha_consistency: string;
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  citation_checks: { stmt_id: string; verdict: string; quote_verbatim: boolean; note: string; in_material: boolean }[];
  by_task_id_tri: string;
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
  sha_consistency: string;
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
}

/** 出处：artifacts.verify_entries() 的行 —— 台账钉的 sha 与盘上现在这一版是不是同一版（`sha_consistency` 把 `status` 的五档折成 match / mismatch / unknown）。 */
export interface LedgerVerifyRow {
  path: string;
  sha256: string;
  producer: string;
  at: string;
  sha256_now: string;
  status: string;
  sha_consistency: string;
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
}

/** 出处：manuscripts.read_rows() 的行（`manuscripts.write` 写的 14 个必填键；`revises`/`kind`/`ref_problems`/`to_task_id`/`to_task_ids` 是「有就带上」的几栏）。 */
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
  to_task_id: string;
  to_task_ids: string[];
  sender_label: string;
  to_label: string;
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
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
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
}

/** 出处：out/paper/ACCEPTANCE-CHECKS.json 的一行（真机 8 行 C1–C8；`closing.ACCEPTANCE_CHECKS_NAME`）。 */
export interface AcceptanceCheck {
  id: string;
  kind: string;
  min: number;
  name: string;
  note: string;
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
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
  settled_at_parent_exit: boolean;
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
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
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
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
  code_sha_consistency: string;
  code_sha_from: string;
  code_sha_to: string;
  void_reason: string;
  exhaustion_path: string;
  exhaustion_tri: Tri;
  by_role: string;
  by_role_source: string;
  by_task_id: string;
  by_task_id_tri: string;
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

/** 出处：roster_face() —— 当前工作区整棵名册树（`out/roster/<父编号>.jsonl` 与 `<父编号>-index.jsonl` 折叠出不落盘的名册项 + `data/tasks.json` 的状态/收件箱读数）。 */
export interface RosterView {
  answer: string;
  tri: Tri;
  reason: string;
  root: string;
  dir: string;
  nodes: RosterNode[];
  roots: string[];
  children_of: Record<string, string[]>;
  count: number | null;
  max_depth: number | null;
  files: string[];
  diagnostics: string[];
  coverage: RosterCoverage;
  tasks_tri: Tri;
  tasks_reason: string;
  truncated: boolean;
  states: { checked: boolean; reason: string; flying: number | null; standby: number | null; silent: number | null; unknown: number | null; active: number | null; total: number | null; labels: Record<string, string> };
  unplaced: RosterUnplaced[];
}

/** 出处：roster_face() 的一个节点 —— 一个常驻子代理（名册里那一项；`depth` 是名册链上的相对深度，根 = 1）。`task_id` 只是页面用的节点键（建项那件活的编号），身份是`owner` + `name`；它接过哪些活见 `tasks`。 */
export interface RosterNode {
  task_id: string;
  name: string;
  role: string;
  depth: number;
  parent_task_id: string;
  parent_name: string;
  children: RosterChild[];
  retired: boolean;
  retired_branch: string;
  brief: string;
  brief_source: string;
  surface: string;
  status: string;
  task_found: boolean;
  state: string;
  state_reason: string;
  stalled: boolean;
  stalled_sec: number | null;
  stalled_reason: string;
  in_flight: number | null;
  inbox: RosterInbox;
  tasks: RosterTask[];
  child_count: number | null;
  roster_child_count: number;
  unrostered_children: RosterUnrostered[];
}

/** 出处：roster_face() 的 nodes[].unrostered_children[] 一项 —— 台账里有父、名册正文与对照表里都没有任何名册项接过的那一行（它同时仍进页面底部的 `unplaced`，两处是同一处判据的两个落位）。 */
export interface RosterUnrostered {
  task_id: string;
  role: string;
  status: string;
  started_at: string;
  ended_at: string;
  why: string;
}

/** 出处：roster_face() 的 nodes[].tasks[] 一项 —— 这个子代理接过的一件活：编号来自`<父>-index.jsonl` 的调用记录，状态与起止时间来自 `data/tasks.json`。 */
export interface RosterTask {
  task_id: string;
  role: string;
  status: string;
  started_at: string;
  ended_at: string;
  task_found: boolean;
  brief: string;
  detail: string;
}

/** 出处：roster_face() 的 unplaced[] 一项 —— 台账里有父、却没有任何名册项接过的那一行（平铺并点名，不抬成树根）。 */
export interface RosterUnplaced {
  task_id: string;
  parent_task_id: string;
  role: string;
  status: string;
  started_at: string;
  ended_at: string;
  why: string;
}

/** 出处：roster_face() 的 nodes[].children[] 一项 —— 名册里的一个子（绝对编号 + 名册名）。 */
export interface RosterChild {
  task_id: string;
  name: string;
  role: string;
  retired: boolean;
}

/** 出处：roster_face() 的 nodes[].inbox —— 收件箱（板项：`kind` 非空、`parent_task_id` = 收件人、`item_state != "done"` 的那些行）；`unread` 是还没被读进任何一步的（queued/claimed），`seen_not_acked` 是读了但还缺 ack 的，`open_total` 是 `len(rows)` = `unread` + `seen_not_acked` + `other`（`other` 是状态读不出来的那些：`item_state` 是空串或词表外的行）。 */
export interface RosterInbox {
  tri: Tri;
  unread: number | null;
  seen_not_acked: number | null;
  open_total: number | null;
  other: number | null;
  by_state: Record<string, number>;
  by_kind: Record<string, number>;
  items: RosterInboxItem[];
  more: number;
  reason: string;
}

/** 出处：roster_face() 的 nodes[].inbox.items[] 一项 —— 一条还没消的消息/通知。 */
export interface RosterInboxItem {
  task_id: string;
  kind: string;
  state: string;
  called_by: string;
  detail: string;
}

/** 出处：roster_face() 的 coverage —— 台账里的代理行与名册节点的对账（读不到就是 null）。 */
export interface RosterCoverage {
  tasks_agents: number | null;
  roster_nodes: number | null;
  unrostered: number | null;
}

/** 出处：library_face() —— 文献库那一面：只算「正式入库」的文献 + 每篇被哪些命题／哪一份证明用过（`state` 只有 computed / unknown 两档；`unknown` 有两支 ——台账没读成、以及「没有候选台账 ⇒ 入库判不出」，两支的 `data.count` 都是 null，不是 0）。 */
export interface LibraryView {
  checked: boolean;
  state: string;
  reason: string;
  data: LibraryData;
  problems: LibraryProblem[];
}

/** 出处：library_face() 的 data —— 入库文献那几栏与判据的来源（`rows_total` 是台账里一共几行，`count` 是显示几条；两者之和不必相等：待入库与判不出的都不显示。`admission_source` 只有一个取值：那一格是唯一判据）。 */
export interface LibraryData {
  works: LibraryWork[];
  count: number | null;
  table: string;
  table_state: string;
  rows_total: number | null;
  admission_source: string;
  admission_tri: Tri;
  undecidable: number | null;
  uses_tri: Tri;
  uses_reason: string;
}

/** 出处：library_face() 的 data.works[] —— 一条「正式入库」的文献（`admitted` 恒为 true：判不出的不进这个数组，而判据只有 `lit_candidates.status=admitted` 那一格）。`download_state` 是 download 那一格与盘上文件核对的三态（present / absent / unreadable），`uses` 是反查出来的「被谁用过」。 */
export interface LibraryWork {
  lit_id: string;
  title: string;
  authors: string[];
  doi: string;
  dedup_key: string;
  pages: string;
  matched: string;
  claimed_by: string;
  mine_attempts: number;
  last_mine_error: string;
  download_status: string;
  download_path: string;
  download_state: string;
  download_bytes: number | null;
  download_reason: string;
  admitted: boolean;
  admission_basis: string;
  uses: LibraryUse[];
  uses_count: number;
}

/** 出处：library_face() 的 data.works[].uses[] —— 「这一篇被谁用过」的一条（`via` 只有 statement / dependency 两档：语句自己的 `source_lit_id`，与依赖的 `source_lit_id`；`proof_no` 是证明号，`#pN` 由 `proofloc` 拆）。 */
export interface LibraryUse {
  stmt_id: string;
  proof_no: number;
  label: string;
  used_by: string;
  via: string;
}

/** 出处：library_face() 的 problems[] —— 一条不拦门但要留痕的读数问题（`code` 是受控的几个码，`admission_undecidable` 就是「判不出入库/待入库」那一条：A 侧的实现问题，不显示但记一笔）。 */
export interface LibraryProblem {
  code: string;
  detail: string;
}

/** 出处：cachectl.tier_reading() 的 per_target[目标] —— 一个预热目标落地/新鲜的四格。 */
export interface CacheTargetCell {
  state: string;
  fresh: boolean | null;
  recorded_sha256: string;
  now_sha256: string;
  absent_reason: string;
}

/** 出处：cachectl.tier_reading() 的 key —— 这一档的 key 换没换（`same` / `stale` / `unknown`）。 */
export interface CacheKeyCell {
  tri: string;
  reason: string;
  changed: string[];
  affected: string[];
  affected_why: string;
  text: string;
  recorded: { fingerprint: string; model: string; base_url: string };
}

/** 出处：cachectl.tier_reading() —— 一档的四格读数（落地 / 新鲜 / 覆盖几个 / 缺谁）。 */
export interface CacheTier {
  tier: string;
  label: string;
  lean_enabled: boolean;
  tri: string;
  reason: string;
  warmed: boolean;
  fresh: boolean | null;
  fresh_reason: string;
  not_fresh: string[];
  version_mismatch: boolean;
  covered: number;
  covered_fresh: number;
  total: number;
  missing: string[];
  absent: string[];
  absent_reason: Record<string, string>;
  at: string;
  prompt_version: string;
  readings_prompt_version: string;
  spent_usd: number | null;
  model: string;
  per_target: Record<string, CacheTargetCell>;
  key: CacheKeyCell;
}

/** 出处：cachectl.key_reading() —— 当前这把 key 的读数（值永不上屏：只有指纹与长度）。 */
export interface CacheKeyReading {
  configured: boolean;
  source: string;
  model: string;
  base_url: string;
  key_chars: number;
  fingerprint: string;
}

/** 出处：cachectl.active_reading() —— 当前这一趟会用哪一档（三层来源各自自报）。 */
export interface CacheActive {
  tier: string;
  label: string;
  lean: boolean | null;
  source: string;
  source_text: string;
  source_note: string;
  record_sid: string;
  record_at: string;
  record_state: string;
  strategy: string;
  run_at: string;
  prompt_version: string;
  readings_prompt_version: string;
  covered: string;
  covered_count: number;
  total: number;
  missing: string[];
  absent: string[];
  fresh: boolean;
  tri: string;
  why: string;
  text: string;
}

/** 出处：cachectl.status() 的 reminder —— 换 key 那条提醒（网页顶部横幅与命令行同一句）。 */
export interface CacheReminder {
  active: boolean;
  tri: string;
  tiers: string[];
  text: string;
  affected: string[];
  dismiss_key: string;
}

/** 出处：cacheface.warm_job() —— 最近一趟网页预热的三态（`running` / `done` / `failed` / `unknown`）。 */
export interface CacheWarmJob {
  recorded: boolean;
  state: string;
  reason: string;
  log: string;
  log_path: string;
  pid: number;
  tier: string;
  at: string;
  last_line: string;
  tail: string[];
}

/** 出处：GET /api/cache 的整份读数（`cachectl.status()` + 写权限读数 + 预热三态）。 */
export interface CacheView {
  schema: number;
  at: string;
  readings: string;
  lean_now: boolean;
  prompt_version: string;
  key: CacheKeyReading;
  tiers: Record<string, CacheTier>;
  workspace: string;
  active: CacheActive;
  reminder: CacheReminder;
  writes_allowed: boolean;
  writes_reason: string;
  warm: CacheWarmJob;
  verdict: { tri: string; unknown_tiers: string[]; stale_tiers: string[]; key_unknown_tiers: string[] };
}

/** 出处：errors_readout() 的 problems[] —— 一条「读到了、但人该看见」的异常（与 `LibraryProblem` 同形：两族各是各的读数，合并不省事）。 */
export interface ReadoutProblem {
  code: string;
  detail: string;
}

/** 出处：errors_readout() 的 data.sources[源] —— 逐源读数（三种源的键不完全相同，所以每一格都是可选的：缺格 = 这一源没有这一栏，不是 0）。 */
export interface ErrorStatsSource {
  checked?: boolean;
  events?: number;
  files?: number;
  records?: number;
  bad_lines?: number;
  unreadable_files?: string[];
  unclassified?: number;
  table?: string;
  reason?: string;
}

/** 出处：errors_readout() 的 data —— 角色 × 类目的计数（只记出现过的格，缺格就是 0）。 */
export interface ErrorStatsData {
  by_role: Record<string, Record<string, number>>;
  role_total: Record<string, number>;
  total: number;
  categories: Record<string, number>;
  sources: Record<string, ErrorStatsSource>;
}

/** 出处：GET /api/errors 的整份读数（`readouts.errors_readout()` 逐字）。 */
export interface RoleErrorsView {
  checked: boolean;
  state: string;
  reason: string;
  data: ErrorStatsData;
  problems: ReadoutProblem[];
}

/** 出处：errorstats.ERROR_CATEGORIES 的一行 —— 类目与它那一句含义。 */
export interface ErrorCategoryMeaning {
  name: string;
  meaning: string;
}

/** 出处：GET /api/errors/categories 的整份读数（一张常量表，无三态）。 */
export interface ErrorCategoryGlossary {
  categories: ErrorCategoryMeaning[];
  source: string;
}

/** 出处：写面端点的统一回执（W3/W4 才有生产者 ⇒ 判据 C 不覆盖它；`id`/`extra` 只是「有就带上」的两栏，所以写成可选）。 */
export interface WriteResult {
  ok: boolean;
  tri: Tri;
  reason: string;
  id?: string;
  state?: string;
  extra?: Record<string, unknown>;
}

// --------------------------------------------------------------------------
// 欠账清单：这些接口本批不生成（没有真读数就没有类型）。
// 每一条都写明缺哪一个 reader —— 补上读数之后，把那一行从对应模块的
// `MISSING_TYPES` 里删掉，并把接口加进那个模块的 `type_decls()`。
// --------------------------------------------------------------------------
