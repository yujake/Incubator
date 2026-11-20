/*
 * 命题台账的渲染口径（LEDGERUI，2026-11-20 业主四点现场）。
 *
 * 这里是页面那一层唯一的"哪一格上主表"与"那一格印什么词"的判据面：
 * 它不 import preact、不碰 DOM，所以 `tests/test_webui_ledger_columns.py` 能把
 * `ui/node_modules/typescript` 转出来的 ESM 直接喂给 node 真跑（与
 * `rosterTree.ts` 同一条路）。Evidence.tsx 只负责把这里给的列 id 摆成表。
 *
 * ## 列集按 origin / kind 决定（不是一套列全行通用）
 *
 * - `quote`（引文回验）只对"从文献摘来的、且不是概念行"出现：自产结果结构上
 *   没有逐字引文，概念 / 定义行也没有逐字摘录 —— 对它们摆一列"未查 / 不适用"
 *   只是占列位（业主原话：「引文这个状态在自产定理里肯定没有，不该作为展示格」）；
 * - `manuscript` / `vsign`（稿 / 稿上有无 V 签）只对自产结果出现 —— 文献命题
 *   没有"我们写的稿"这件事。
 *
 * 两类行混在一张表里时取并集（HTML 表没有"按行换列"这回事），不适用的那一格
 * 写「不适用（…）」，与"读不到"分开。
 *
 * ## 判读格优先、provenance 退到详情
 *
 * 主表前几列是判读格：档位（grade）/ 是否优化（optimized）/ 类别（kind）/
 * 出处（origin）/ 现行性（current）。谁写的（created_by → by_role）、台账编号、
 * 是哪篇文献、哪一页，都不占列 —— 由 `provenanceText()` 合成一句，页面挂在
 * 命题号的 tooltip 与「详情」那一格里。
 *
 * ## 现行性：active 是补集兜底名，不印
 *
 * `status=active` 是"没被取代、没被证否、没被放弃"的兜底档；十三行全是它时，
 * 那一列等于没有信息（业主原话：「都登记上了什么叫活跃」）。所以 active 行
 * 印 `—`；只有非 active 才印具体原因与所指编号（`已取代（被 …）` /
 * `已证否（反例 …）` / `已放弃（…）`）。词由后端按 lifecycle 三态与作废载荷
 * 算好（`current_word`），页面不另拼一份。
 */
import type { StatementRow } from "./types";

/** 主表能出现的那几格（顺序就是页面上的列序）。 */
export type LedgerField =
  | "stmt_id"
  | "grade"
  | "optimized"
  | "kind"
  | "origin"
  | "current"
  | "nontriviality"
  | "label"
  | "bit_numeric"
  | "bit_proof"
  | "reviewed_paths"
  | "formal_paths"
  | "bit_audited"
  | "body"
  | "quote"
  | "manuscript"
  | "vsign";

/** 每一行都要有的判读格（与 origin / kind 无关）。 */
export const BASE_FIELDS: readonly LedgerField[] = [
  "stmt_id",
  "grade",
  "optimized",
  "kind",
  "origin",
  "current",
  "nontriviality",
  "label",
  "bit_numeric",
  "bit_proof",
  "reviewed_paths",
  "formal_paths",
  "bit_audited",
  "body",
];

/** 这一行是从文献里摘来的吗。 */
export function isExternalLit(row: StatementRow): boolean {
  return row.origin === "external_lit";
}

/** 这一行是本台账自己的结果吗。 */
export function isOwnResult(row: StatementRow): boolean {
  return row.origin === "own_result";
}

/**
 * 主表列集：按这一批行的 origin / kind 算，不是一张固定的清单。
 *
 * 两处条件各有一个"为什么"：
 * - `quote` 要求"文献行 + 不是概念行"：概念行在盘上结构性地没有 `proof_text`
 *   （见 `schema.Statement` 的 docstring 与真机 000004 的读数），给它一列
 *   "不适用"只是噪声；
 * - `manuscript` / `vsign` 要求"自产行"：文献命题没有我们自己的稿。
 */
export function ledgerFields(rows: StatementRow[]): LedgerField[] {
  const fields: LedgerField[] = [...BASE_FIELDS];
  if (rows.some((r) => isExternalLit(r) && r.kind !== "concept")) {
    fields.push("quote");
  }
  if (rows.some(isOwnResult)) {
    fields.push("manuscript", "vsign");
  }
  return fields;
}

/** 现行性那一格：active 写 `—`（兜底名不印），其余用后端算好的那句话。 */
export function currentnessText(row: StatementRow): string {
  return row.current_word === "" ? "—" : row.current_word;
}

/** 档位那一格：空 ⇒ 「未判」（不是空白，也不是 unknown）。 */
export function gradeText(row: StatementRow): string {
  return row.grade_label === "" ? "未判" : row.grade_label;
}

/**
 * 类别那一格：盘上的 `kind` 与读侧投影并列（KINDREAD，2026-11-20）。
 *
 * 历史行是在写侧判据落地之前入库的（真机 lp-ball-13 的 6 行文献定理写着
 * `conjecture`）。读侧只现算一个并列值、不改盘 —— 所以这一格必须把两个词都印出来：
 * 原值在前、投影在后，差异用箭头与「读侧投影」标出。投影与盘上相同（绝大多数行）
 * 时不画箭头、也不加注，免得让每一行都看起来被改过。
 *
 * 不许把 `kind_projected` 单独印出来：那等于拿投影冒充原值，读者再也看不出
 * "盘上还写着旧词"这件事。后端两格都在（`kind` / `kind_projected`），这一格只负责
 * 把差异显示出来。
 */
export function kindText(row: StatementRow): string {
  const disk = row.kind === "" ? "unknown" : row.kind;
  if (!row.kind_projection_changed) {
    return disk;
  }
  return `${disk} → ${row.kind_projected === "" ? "unknown" : row.kind_projected}（读侧投影）`;
}

/** 出处那一格：两个受控词译成人话，词表外的原样印（不折成"文献"）。 */
export function originText(row: StatementRow): string {
  if (row.origin === "external_lit") {
    return "文献";
  }
  if (row.origin === "own_result") {
    return "自产";
  }
  return row.origin === "" ? "unknown" : row.origin;
}

/** 「有没有稿」那一格（只对自产行有意义）。 */
export function manuscriptText(row: StatementRow): string {
  if (row.manuscript_state === "found") {
    return `有稿（${row.manuscript_path}）`;
  }
  if (row.manuscript_state === "missing") {
    return `稿没落盘（${row.manuscript_path}）`;
  }
  if (row.manuscript_state === "none") {
    return "无稿（台账没记稿路径）";
  }
  if (row.manuscript_state === "unknown") {
    return "稿读数没查成";
  }
  return "不适用（文献命题没有自产稿）";
}

/** 「稿上有无 V 签」那一格（只对自产行有意义）。 */
export function vsignText(row: StatementRow): string {
  if (row.vsign_state === "signed") {
    return row.vsign_detail === "" ? "V 已签" : `V 已签（${row.vsign_detail}）`;
  }
  if (row.vsign_state === "unsigned") {
    return "无 V 签";
  }
  if (row.vsign_state === "unknown") {
    return "签表没查成";
  }
  return "不适用（文献命题没有自产稿）";
}

/** 页区间：盘上是 `{start,end}`，老行可能是字符串；读不出来就不写这一截。 */
function pageText(row: StatementRow): string {
  const raw: unknown = row.page_range;
  if (typeof raw === "string") {
    return raw === "" ? "" : ` · ${raw}`;
  }
  if (raw !== null && typeof raw === "object") {
    const got = raw as Record<string, unknown>;
    const start = got["start"];
    const end = got["end"];
    if (typeof start === "number" && typeof end === "number") {
      return ` p${start}–${end}`;
    }
  }
  return "";
}

/** 出处那一行的细节（详情，不上主表）。 */
function originDetail(row: StatementRow): string {
  if (row.origin === "external_lit") {
    const lit = row.source_lit_id === "" ? "（没记文献号）" : row.source_lit_id;
    return `文献 ${lit}${pageText(row)}`;
  }
  if (row.origin === "own_result") {
    return "自产（本台账自己的结果）";
  }
  return row.origin === "" ? "unknown" : row.origin;
}

/**
 * provenance 那一段（详情 / tooltip 的唯一文本）：谁写的、台账编号、收录时间、出处。
 *
 * 为什么是一整句而不是几列：这几格回答的是"这一行从哪来"，不是"这一条命命题
 * 判成什么" —— 它们与 grade / optimized 抢列位时，读的人先看到的是"B 秘书写的"，
 * 而不是"还没判"。合成一句挂在命题号上，要找的人点一下就有。
 */
export function provenanceText(row: StatementRow): string {
  const who = row.by_role === "" ? "—（盘上没记）" : row.by_role;
  const source = row.by_role_source === "" ? "（来源没记）" : `（来源 ${row.by_role_source}）`;
  const task = row.by_task_id === "" ? "—（台账里查不到这一行的任务号）" : row.by_task_id;
  const at = row.created_at === "" ? "unknown" : row.created_at;
  return [
    `写它的实例：${who}${source}`,
    `台账编号：${task}`,
    `收录：${at}`,
    `出处：${originDetail(row)}`,
  ].join(" · ");
}
