/*
 * 证据链（`draft/74 §3.3` 逐行落）。
 *
 * 输入：`api.getEvidence()` → `EvidenceView`（B 线的 `readers.evidence_chain`）。
 * SSE：`state`。
 *
 * 七栏各自带一个 `<栏>_tri`（B 线的口径：整面一个词会吞掉"哪一栏没读成"），
 * 所以这里每一栏都渲染自己那个三态，不拿整面的词顶替：
 *
 * 1. 命题台账 `statements`（真机 0 行 ⇒ 空态写"0 条"，那是"读到了，里面是 0 行"）；
 * 2. 猜想与反例 `conjectures`（`status=refuted` 时要显 `experiment_ids` 与
 *    `counterexample_experiment_id`）；
 * 3. 实验 `experiments`；
 * 4. 审校发现 `review_findings`；
 * 5. 引文回验：`relations` 的 `quote_state` 五档（逐字 / 语义 / 不一致 / 未查 /
 *    没有可复核的区间）—— 不是"通过"的那几档必须把 `quote_reason` 一起显出来，
 *    否则读的人不知道为什么；
 * 6. 证明级 `verifications`（裁定 K2：盘上无真机样本 ⇒ 夹具造一行；页面标明）；
 * 7. 秘书决策 `secretary`。
 *
 * ## 每一栏各说各的
 *
 * - sha 原文一律不上屏：证明那一栏只印"一致 / 不一致 / unknown（没得比）"
 *   （比的是 V 签的那一份 vs 命题现在这一份，见那一栏的副标题）；
 * - 命题多两格：非平凡度（`T0`–`T4` 或"未判"）与形式化第 4 位的逐路径读数
 *   （`{证明号: 状态}` 是二维的，折成一条汇总就等于让 `#p2` 借 `#p1` 的光）；
 * - reviewed 按证明逐条显示：逐份证明的号与"签没签"在命题台账那一栏
 *   （`reviewed_paths`）；验证台账那一栏按验证号 / 命题号读，与 `VerificationRow` 现值对齐。
 *
 * ## 列集按 origin / kind 分（2026-11-20，业主 lp-ball-13 现场）
 *
 * 命题台账不再是一套列全行通用（判据见 `tests/test_webui_ledger_columns.py`，
 * 列 id 与条件在 `statementLedger.ts`）：
 * - 判读格优先：档位 / 是否优化 / 类别 / 出处 / 现行性排在最前；
 * - 引文回验只对文献行（且不是概念行）出现，理由进 tooltip；自产行不摆这一列；
 * - 自产结果多两列「稿 / V 签」（文献命题写「不适用」）；
 * - provenance（谁写的、台账编号、哪篇文献哪一页）不占列：挂在命题号的 tooltip
 *   与「详情」里；
 * - 现行性列：active 是补集兜底名，写 `—`；只有被取代 / 被证否 / 被放弃时才写
 *   具体原因与所指编号。
 *
 * ## 五元位与「优化」
 *
 * - 五元位每一位一格：第 1 位 numeric、第 2 位 proof、第 3 位 reviewed、
 *   第 4 位 formal（按路径那一格）、第 5 位 audited 各占一列；
 * - 第 3 位与第 4 位同一个样式：一份证明一格（`#p1 已签 ｜ #p2 未签`）；
 * - 命题台账补一列「优化」，与第 3 位 reviewed 并排：读后端逐份的 `optimized_paths`
 *   （`[{proof_no, state}]`，三态由 `evidencebits.optimized_state` 给）；
 * - 三档词逐字是「已优化 / 未优化 / 未记录」：缺格（`not_recorded`）不许折成
 *   「未优化」—— 那一格在存量行上根本不存在，折平会让整库一次全变「未优化」；
 * - 一行证明一格（`#p1 已优化 ｜ #p2 未优化`），`#p2` 不借 `#p1` 的光；
 *   这一条没有逐证明记录时写「未记录（…说不出是哪一份）」，不写「未优化」；
 * - 实验表补「报告」一列：`out/experiments/<号>/exhaustion.md`（②③ 的唯一落点）。
 *   链接指向产物页那张实验落点卡（报告不在 web 服务的静态路由下，直接链文件是死链），
 *   没有报告写「无」而不是留空。
 */
import { api } from "../api";
import { useState } from "preact/hooks";

import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { Consistency } from "../components/Consistency";
import { Nontriviality } from "../components/Nontriviality";
import { formatUsd } from "../components/Money";
import { PagedTable } from "../components/PagedTable";
import { cell } from "../components/Table";
import type { Column } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace } from "../live";
import {
  currentnessText,
  gradeText,
  kindText,
  ledgerFields,
  manuscriptText,
  originText,
  provenanceText,
  vsignText,
} from "../statementLedger";
import type { LedgerField } from "../statementLedger";
import type { EvidenceView, ExperimentRow, RelationRow, StatementRow } from "../types";

/** 这一栏**真实**有多少行（AUDIT F12 的分页读数：`rows_total[栏]`；全量档与数组等长）。 */
function totalOf(ev: EvidenceView, key: string, shown: number): number {
  const raw = ev.rows_total[key];
  return typeof raw === "number" ? raw : shown;
}

/** 这一栏被首屏摘要切过时那一句（不许把"首屏画了 N 行"读成"一共 N 行"）。
 *
 * 空串 = 没切过（这一栏给全了）。判据 `${shown} < ${total}` 而不是看 `rows_mode`：
 * 全量档里也可能某一栏本来就只有几行，那种情况一个字都不该多说。
 */
function rowsNote(ev: EvidenceView, key: string, shown: number): string {
  const total = totalOf(ev, key, shown);
  if (total <= shown) {
    return "";
  }
  return `这一栏共 ${total} 行，首屏只画了前 ${shown} 行（摘要档）—— 点这张卡上面的「取全部」拉整表。`;
}

/** `rowsNote` 那一句的渲染（空串 ⇒ 什么都不画）。 */
function PartialRows(props: { note: string }) {
  return props.note === "" ? null : <div class="readings tri-reason">{props.note}</div>;
}

/** 状态那一格：人话（`status_word`）上屏，原始 token 进 tooltip；命题面另报三态。
 *
 * 为什么不再直接印 `status`：真机上这一列是 `refuted` / `supported_not_proved` /
 * `voided` / `needs_evidence` 这些原始 token 并排（`draft/187` P1-4）—— 读的人得自己
 * 翻译，而 `supported_not_proved` 与 `refuted` 在屏幕上长得一样"都是英文"。
 *
 * 三态只在命题面上有（`lifecycle.state_of_statement`，唯一入口）：
 * `lifecycle_checked === false` ⇒ 这一格判不了（`unknown`），**不折成"活跃"**；
 * 其余几张表没有 lifecycle 入口，`lifecycle_state` 是空串 —— 那不是"判成活跃"。
 */
export function statusCell(r: {
  status: string;
  status_word?: string;
  lifecycle_state?: string;
  lifecycle_checked?: boolean | null;
}) {
  const word = (r.status_word ?? "") === "" ? cell(r.status) : (r.status_word as string);
  const tip = `盘上的原始 status=${r.status === "" ? "（空串）" : r.status}`;
  if (r.lifecycle_checked === false) {
    return (
      <span class="tri-reason" title={tip}>
        {word}（三态判不了：status 不在词表里，不折成活跃）
      </span>
    );
  }
  return (
    <span class="mono" title={tip}>
      {word}
    </span>
  );
}

/** 引文状态的五档（后端 `evidencebits.QUOTE_STATES`；词表外的值原样印，不折成"通过"）。 */
const QUOTE_WORDS: Record<string, { text: string; kind: string }> = {
  verbatim: { text: "逐字通过", kind: "badge-pass" },
  semantic: { text: "语义通过", kind: "badge-pass" },
  mismatch: { text: "不一致", kind: "badge-fail" },
  unchecked: { text: "未查", kind: "badge-na" },
  no_evidence: { text: "没有可复核的区间", kind: "badge-unknown" },
};

/** 五元位第 4 位逐路径的五档（后端 `evidencebits.FORMAL_PATH_STATES`）。 */
const FORMAL_WORDS: Record<string, string> = {
  verified: "verified",
  failed: "failed",
  pending: "pending",
  na: "na（不适用）",
  stale: "stale（验过、过期了）",
};

/** 五元位那四位标量位的状态词（后端 `evidencebits.BIT_STATES` 的四档）。
 *
 * 词表外的值原样印：把认不出的状态折成 `pending`（"还没做"）与折成 `verified`
 * 一样危险 —— 一个是把做过的事说成没做，一个是把没做的事说成做了。
 */
const BIT_WORDS: Record<string, string> = {
  verified: "verified（已做）",
  failed: "failed（没通过）",
  na: "na（不适用）",
  pending: "pending（未做）",
};

/** 一个标量位的词（空串 = 这一位没读出来 ⇒ `unknown`，不冒充 `pending`）。 */
function bitWord(state: string): string {
  if (state === "") {
    return "unknown（这一位没读出来）";
  }
  return BIT_WORDS[state] ?? state;
}

/** 第 1 / 2 / 5 位那一格：一位一个词（读不到写 `unknown`，不写「未做」）。 */
function bitCell(state: string) {
  return state === "" ? (
    <span class="tri-reason">{bitWord(state)}</span>
  ) : (
    <span class="mono">{bitWord(state)}</span>
  );
}

/** 第 3 位那一格：按证明逐条签（`#p1 已签 ｜ #p2 未签`）。
 *
 * 与第 4 位同一个样式（一份证明一行）：这一位在盘上是"证明号 ⇒ 签没签过"那张表，
 * 折成一句"审过"就等于让 `#p2` 借 `#p1` 的光。没有逐条记录时退回汇总位那个词，
 * 但明写"说不出是哪一份签的"—— 那与"没签"不是同一句话。
 */
function reviewedCell(r: StatementRow) {
  if (r.reviewed_paths.length === 0) {
    return (
      <span class="tri-reason">
        汇总位 {bitWord(r.bit_reviewed)}（这一条没有逐证明的签名记录，说不出是哪一份签的）
      </span>
    );
  }
  return (
    <span
      class="mono"
      title="第 3 位是按证明签的：一份证明一格，任一条签过即算过；签的是不是现在这一份正文，看「证明级」那一卡的证明一致"
    >
      {r.reviewed_paths.map((p) => `#p${p.proof_no} ${p.reviewed ? "已签" : "未签"}`).join(" ｜ ")}
    </span>
  );
}

/** 「优化」那一格的三档词（后端 `evidencebits.OPTIMIZED_STATES`：true / false / not_recorded）。
 *
 * 后端给 token、词只在这一处映射（与 `QUOTE_WORDS` / `FORMAL_WORDS` 同一条纪律）。
 * `not_recorded` 的页面词逐字是「未记录」而不是「未优化」：缺格（存量行还没有这一格）
 * 与"这一份确实还没洗"是两件事 —— 折平会让整库一次全变「未优化」，读的人会去洗
 * 3000+ 条本来没欠账的证明。
 */
const OPTIMIZED_WORDS: Record<string, string> = {
  true: "已优化",
  false: "未优化",
  not_recorded: "未记录",
};

/** 「优化」那一格：按证明逐份（`#p1 已优化 ｜ #p2 未优化`），与第 3 位并排。
 *
 * 这一条没有逐证明记录时（连证明号都读不出来）写「未记录（说不出是哪一份）」：
 * 那是"没有这一格"，不是"没优化"—— 页面不替它编一个「未优化」。
 */
function optimizedCell(r: StatementRow) {
  if (r.optimized_paths.length === 0) {
    return (
      <span class="tri-reason">
        未记录（这一条没有逐证明的记录，说不出是哪一份 —— 与「未优化」是两件事）
      </span>
    );
  }
  return (
    <span
      class="mono"
      title="是否优化是按证明记的：一份证明一格（已优化 / 未优化 / 未记录）；未记录 = 这一行还没有那一格，不是未优化"
    >
      {r.optimized_paths
        .map((p) => `#p${p.proof_no} ${OPTIMIZED_WORDS[p.state] ?? p.state}`)
        .join(" ｜ ")}
    </span>
  );
}

/** 「报告」那一格指向产物页那张实验落点卡（`Artifacts.tsx` 给那张卡挂了这个 id）。
 *
 * 为什么不直接链到文件：web 服务只发 `/static/` 与页面（`routes.ROUTES`），
 * 仓库相对路径当 `href` 点下去只会回到应用 —— 那是死链。链接指向"这一处在盘上
 * 有没有、多大"那张卡，链接文字仍是业主点名的那份报告的仓库相对路径。
 */
const REPORT_SPOT_HREF = "/artifacts#experiment-spots";

/** 实验表的「报告」那一格：`out/experiments/<号>/exhaustion.md`（②③ 的唯一落点）。
 *
 * 三档各说各的：有 ⇒ 链接；没有 ⇒ 写「无」（不是空白）；读不出来 ⇒ 写"没查成"
 * （不许把"没读到"与"没有报告"折成同一个「无」）。
 */
/** 实验表的「代码一致」那一格：四档（一致 / 已撤销 / 不一致 / unknown）。
 *
 * 第四档「已撤销」不是红 —— 它说的是"这件事已经处置过：老登记作废、新登记接上"，
 * 而「不一致」说的是"脚本改过却没重新登记"，是异常。折平之后读者看见一片红，
 * 分不清哪一条要动手。「已撤销」还要印出从哪一份换到哪一份（两个 sha 前 16 位与
 * 撤销理由）—— 只写「已撤销」三个字，读者仍然不知道它换成了哪一份脚本。
 */
function codeCell(r: ExperimentRow) {
  if (r.code_sha_consistency === "revoked") {
    const detail = r.void_reason !== "" ? r.void_reason : `${r.code_sha_from} → ${r.code_sha_to}`;
    return (
      <span class="consistency" title={`已撤销：${detail}（这一行不再算作该结论的证据）`}>
        <Badge kind="badge-unknown" text={`已撤销（脚本已改：${detail}）`} />
      </span>
    );
  }
  return (
    <Consistency
      value={r.code_sha_consistency}
      note="台账钉住的代码 sha 与盘上现在这一份脚本（脚本不在盘上或那一行没记 sha ⇒ 没得比）"
    />
  );
}

function reportCell(r: ExperimentRow) {
  if (r.exhaustion_tri === "unreadable") {
    return <span class="tri-reason">没查成（这一份报告读不出来，不是「无」）</span>;
  }
  if (r.exhaustion_tri !== "computed" || r.exhaustion_path === "") {
    const why =
      r.exhaustion_path === ""
        ? "台账里的实验号不成形，判不出落点"
        : `${r.exhaustion_path} 还没落盘`;
    return <span class="tri-reason">无（{why}）</span>;
  }
  return (
    <a class="mono" href={REPORT_SPOT_HREF} title={`${r.exhaustion_path} —— 与产物页「实验产物的落点」那张卡是同一处`}>
      {r.exhaustion_path}
    </a>
  );
}

/** 一行的引文状态：新后端给 `quote_state`，老后端没有这一格就按布尔读（三态不折平）。 */
function quoteStateOf(r: StatementRow | RelationRow): string {
  if (r.quote_state !== "") {
    return r.quote_state;
  }
  if (r.quote_verified === true) {
    return "verbatim";
  }
  return r.quote_verified === false ? "mismatch" : "unchecked";
}

/** 引文那一格：五档各有自己的词（`no_evidence` 与"未查"欠的东西不同，不许合并）。
 *
 * 自产结果结构上没有逐字引文（业主 2026-11-20 ③：「引文这个状态在自产定理里
 * 肯定没有，不该作为展示格」）：混排表里它写「不适用」，词表外的值原样印。
 * 回验理由不再单独占一列，挂在徽标的 tooltip 上。
 */
function quoteCell(r: StatementRow) {
  if (r.origin === "own_result") {
    return <span class="tri-reason">不适用（自产结果没有引文）</span>;
  }
  if (r.proof_text === "" && quoteStateOf(r) === "unchecked") {
    return <span class="tri-reason">不适用（这一行没有逐字摘录）</span>;
  }
  const state = quoteStateOf(r);
  const got = QUOTE_WORDS[state];
  return got === undefined ? (
    <span class="tri-reason" title={r.quote_reason}>{state === "" ? "unknown" : state}</span>
  ) : (
    <span title={r.quote_reason}>
      <Badge kind={got.kind} text={got.text} />
    </span>
  );
}

/** 正文那一格：短版优先、缺席退回全文（R93：盘上短版常为空，整列 `unknown` 像没读到）。 */
function bodyCell(r: StatementRow) {
  if (r.statement_text !== "") {
    return r.statement_text;
  }
  if (r.statement_full !== "") {
    return (
      <>
        {r.statement_full}
        <span class="tri-reason">（短版没写；这是含假设的全文）</span>
      </>
    );
  }
  return <span class="tri-reason">（这一行没写正文）</span>;
}

/** 第 4 位那一格：按路径逐条印（`形式化：路径1 verified ｜ 路径2 pending`）。 */
function formalCell(r: StatementRow) {
  if (r.formal_paths.length === 0) {
    return <span class="tri-reason">不适用（这一条还没有形式化的路径读数）</span>;
  }
  const text = r.formal_paths
    .map((p) => `路径${p.proof_no} ${FORMAL_WORDS[p.state] ?? p.state}`)
    .join(" ｜ ");
  return (
    <span class="mono" title="第 4 位是二维的（一份证明一行）：任一路径通过即算过，而验的是哪一条逐条可读">
      形式化：{text}
    </span>
  );
}

/** 引文回验的五档计数（读不到的那一档一律算"未查"）＋ 不是「逐字 / 语义」通过的那些行。
 *
 * 两件事本来各扫一遍（`quoteTally` 一趟 + `filter` 一趟，每行各算一次
 * `quoteStateOf`）。合到一趟里：`quoteStateOf` 每行只算一次，`notClean` 的
 * 行序仍是 `relations` 的行序，五个计数仍是那五档各自的条数 —— 读数一个都不变。
 */
function quoteScan(rows: RelationRow[]): {
  tally: Record<string, number>;
  notClean: RelationRow[];
} {
  const tally: Record<string, number> = {
    verbatim: 0,
    semantic: 0,
    mismatch: 0,
    unchecked: 0,
    no_evidence: 0,
  };
  const notClean: RelationRow[] = [];
  for (const r of rows) {
    const state = quoteStateOf(r);
    tally[state] = (tally[state] ?? 0) + 1;
    if (state !== "verbatim" && state !== "semantic") {
      notClean.push(r);
    }
  }
  return { tally, notClean };
}

/** 命题台账的列定义表：列 id 与顺序由 `statementLedger.ledgerFields()` 给。
 *
 * 判读格在前（档位 / 优化 / 类别 / 出处 / 现行性）；provenance（谁写的、台账编号、
 * 哪篇文献哪一页）不占列 —— 挂在命题号的 tooltip 与「详情」里（业主 2026-11-20 ②③④）。
 * 引文那一列只在有文献行（且不是概念行）时出现；稿 / V 签只在自产行在场时出现。
 */
const STATEMENT_COLUMNS: Record<LedgerField, Column<StatementRow>> = {
  stmt_id: {
    key: "stmt_id",
    title: "命题号",
    render: (r) => (
      <div>
        <span class="mono" title={provenanceText(r)}>{cell(r.stmt_id)}</span>
        <details class="ledger-detail">
          <summary>详情</summary>
          <div class="readings">{provenanceText(r)}</div>
        </details>
      </div>
    ),
  },
  // 档位：空 ⇒ 「未判」（不是空白，也不是 unknown —— unknown 在同页专指"没读到"）。
  grade: {
    key: "grade_label",
    title: "派生等级",
    render: (r) => (
      <span title={`grade=${r.grade === "" ? "（空）" : r.grade}（空档写「未判」）`}>
        {gradeText(r)}
      </span>
    ),
  },
  // 是否优化，与 reviewed 并排、同一条证明一格。
  // 三档词：已优化 / 未优化 / 未记录（缺格不许折成「未优化」）。
  optimized: {
    key: "optimized_paths",
    title: "优化",
    render: (r) => optimizedCell(r),
  },
  // 类别：盘上 `kind` 与读侧投影并列（差异用箭头 +「读侧投影」标出，投影不冒充原值）。
  kind: {
    key: "kind",
    title: "类别",
    render: (r) => (
      <span class="mono" title={r.kind_projection_basis}>
        {kindText(r)}
      </span>
    ),
  },
  // 出处：external_lit / own_result 译成人话，原始 token 进 tooltip。
  origin: {
    key: "origin",
    title: "出处",
    render: (r) => (
      <span class="mono" title={`盘上的原始 origin=${r.origin === "" ? "（空）" : r.origin}`}>
        {originText(r)}
      </span>
    ),
  },
  // 现行性：active 是补集兜底名 ⇒ 页面写 `—`；只有非 active 才印具体原因与所指编号。
  current: {
    key: "current_word",
    title: "现行性",
    render: (r) => (
      <span title={r.current_detail === "" ? r.status_word : r.current_detail}>
        {currentnessText(r)}
      </span>
    ),
  },
  nontriviality: {
    key: "nontriviality_word",
    title: "非平凡度",
    render: (r) => (
      <Nontriviality
        word={r.nontriviality_word}
        label={r.nontriviality_label}
        meaning={r.nontriviality_meaning}
        tri={r.nontriviality_tri}
      />
    ),
  },
  label: { key: "label", title: "标签", render: (r) => cell(r.label) },
  // 五元位每一位一格：第 4 位按路径（二维），第 3 位按证明逐条。
  bit_numeric: {
    key: "bit_numeric",
    title: "第 1 位·numeric（数值实验）",
    render: (r) => bitCell(r.bit_numeric),
  },
  bit_proof: {
    key: "bit_proof",
    title: "第 2 位·proof（有证明）",
    render: (r) => bitCell(r.bit_proof),
  },
  reviewed_paths: {
    key: "reviewed_paths",
    title: "第 3 位·reviewed（按证明）",
    render: (r) => reviewedCell(r),
  },
  formal_paths: {
    key: "formal_paths",
    title: "第 4 位·formal（按路径）",
    render: (r) => formalCell(r),
  },
  bit_audited: {
    key: "bit_audited",
    title: "第 5 位·audited（正式审查）",
    render: (r) => bitCell(r.bit_audited),
  },
  body: {
    key: "statement_text",
    title: "正文",
    render: (r) => bodyCell(r),
  },
  // 引文回验（五档）：只对文献行出现；理由进 tooltip，不再单独占一列。
  quote: {
    key: "quote_state",
    title: "引文回验",
    render: (r) => quoteCell(r),
  },
  // 自产结果才有的两格（文献命题写「不适用」，混排时也一眼看得出）。
  manuscript: {
    key: "manuscript_path",
    title: "稿",
    render: (r) => <span class="mono">{manuscriptText(r)}</span>,
  },
  vsign: {
    key: "vsign_state",
    title: "V 签",
    render: (r) => (
      <span class="mono" title={r.vsign_detail}>{vsignText(r)}</span>
    ),
  },
};

/** 这一批命题行的主表列集（按 origin / kind 算，不是一套列全行通用）。 */
function statementColumns(rows: StatementRow[]): Array<Column<StatementRow>> {
  return ledgerFields(rows).map((field) => STATEMENT_COLUMNS[field]);
}

export function Evidence() {
  // 首屏摘要 vs 整表（AUDIT F12：真机上这一条端点回 2.1 MB / 2.6 s，一进页面就卡）。
  // `false` ⇒ 首屏只要每栏前 `readers.SUMMARY_ROWS` 行（`?summary=1`）；`true` ⇒ 全量。
  // 为什么保留"取全部"：摘要会切掉行，而所有字段与三态一个都没删 —— "要读全"必须是
  // 一次点击就能做到的事，否则这一改就是把"慢"换成"看不全"。
  const [full, setFull] = useState(false);
  const face = useFace(() => api.getEvidence(full ? {} : { summary: true }));

  if (face.data === null) {
    return (
      <Card
        title="证据链"
        tone={face.problem === "" ? "plain" : "problem"}
        right={face.problem === "" ? null : <TriState tri="unreadable" reason={face.problem} label="证据面" />}
      >
        <span class="readings">{face.problem === "" ? "正在读盘……" : face.problem}</span>
      </Card>
    );
  }

  const ev = face.data;
  // 五档计数与「不是逐字 / 语义通过」的那批行由同一趟扫出来（每行只算一次引文状态）。
  const { tally, notClean } = quoteScan(ev.relations);
  // 哪些栏被首屏摘要切过（按真实总行数与数组长度比，不按 `rows_mode` 猜）。
  const cutColumns: string[] = [
    ["命题", ev.statements.length, totalOf(ev, "statements", ev.statements.length)],
    ["猜想", ev.conjectures.length, totalOf(ev, "conjectures", ev.conjectures.length)],
    ["实验", ev.experiments.length, totalOf(ev, "experiments", ev.experiments.length)],
    ["稿件", ev.documents.length, totalOf(ev, "documents", ev.documents.length)],
    ["审校", ev.review_findings.length, totalOf(ev, "review_findings", ev.review_findings.length)],
    ["关系", ev.relations.length, totalOf(ev, "relations", ev.relations.length)],
    ["验证", ev.verifications.length, totalOf(ev, "verifications", ev.verifications.length)],
    ["秘书", ev.secretary.length, totalOf(ev, "secretary", ev.secretary.length)],
  ]
    .filter(([, shown, total]) => Number(total) > Number(shown))
    .map(([name]) => String(name));

  return (
    <>
      <Card
        title="证据链"
        subtitle={`八栏 · 整面 tri=${ev.tri}`}
        tone={isUnreadable(ev.tri) ? "problem" : "plain"}
        right={<TriState tri={ev.tri} label="证据面" reason={ev.reason} />}
      >
        <div class="readings">
          八张表；每一栏各有自己的三态。
        </div>
        {/* 首屏摘要（AUDIT F12）：这一格必须说清"这一份是全量还是摘要、一共多少行"，
            否则"命题台账 40 条"会把真实总数读没。四格读数全部来自后端的
            `rows_mode` / `rows_limit` / `rows_offset` / `rows_total`。 */}
        <div class="readings">
          读数档{" "}
          <span class="mono">{ev.rows_mode}</span>（每栏 {ev.rows_offset} 起，最多{" "}
          <span class="mono">{ev.rows_limit === 0 ? "全部" : ev.rows_limit}</span> 行）·{" "}
          {cutColumns.length === 0 ? (
            <span>这一份是全量：每一栏给全了。</span>
          ) : (
            <span>
              首屏摘要切过这几栏：<span class="mono">{cutColumns.join(" / ")}</span>
              （每栏下面的「共 N 行」是真实总数）
            </span>
          )}{" "}
          {full ? (
            <button
              class="btn"
              type="button"
              onClick={() => {
                setFull(false);
                face.reload();
              }}
            >
              回到首屏摘要（快）
            </button>
          ) : (
            <button
              class="btn"
              type="button"
              onClick={() => {
                setFull(true);
                face.reload();
              }}
            >
              取全部（整表，慢）
            </button>
          )}
        </div>
        {ev.store_problems.length === 0 ? null : (
          <div class="readings">
            读盘问题 <span class="mono">{ev.store_problems.join("；")}</span>
          </div>
        )}
      </Card>

      <Card
        title="命题台账"
        subtitle={`${ev.statements.length} 条 · 共 ${totalOf(ev, "statements", ev.statements.length)} 条`}
        right={<TriState tri={ev.statements_tri} label="statements" />}
      >
        <PartialRows note={rowsNote(ev, "statements", ev.statements.length)} />
        {isUnreadable(ev.statements_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : ev.statements_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这个工作区里这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <div class="ledger-scroll">
            <PagedTable
              rows={ev.statements}
              empty="暂无命题（已读出）。"
              columns={statementColumns(ev.statements)}
            />
          </div>
        )}
      </Card>

      <Card
        title="猜想与反例"
        subtitle={`${ev.conjectures.length} 条`}
        right={<TriState tri={ev.conjectures_tri} label="conjectures" />}
      >
        <PartialRows note={rowsNote(ev, "conjectures", ev.conjectures.length)} />
        {isUnreadable(ev.conjectures_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : ev.conjectures_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这个工作区里这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <PagedTable
            rows={ev.conjectures}
            empty="0 条猜想（读到了，里面是空的）。"
            columns={[
              { key: "conjecture_id", title: "猜想号" },
              { key: "status_word", title: "状态", render: (r) => statusCell(r) },
              { key: "form", title: "形态", render: (r) => cell(r.form) },
              {
                // `testable` 的真身是 dict（`{"params","bounds","why"}`，`schema.Conjecture`）。
                // 改前这里是 `String(r.testable)` ⇒ 真机 13 行全印 `[object Object]`；
                // `cell()` 对对象走 `JSON.stringify`，至少是真的读数、读得懂。
                // 空对象印「—（盘上没写）」—— 那是"这一格没有内容"，不是"没读到"。
                key: "testable",
                title: "可检验",
                render: (r) => {
                  const t: Record<string, unknown> = r.testable ?? {};
                  return Object.keys(t).length === 0 ? "—（盘上没写）" : cell(t);
                },
              },
              { key: "statement", title: "陈述" },
              {
                key: "counterexample_experiment_id",
                title: "反例实验",
                render: (r) =>
                  r.counterexample_experiment_id === null
                    ? "没有（未反驳 / 未记）"
                    : r.counterexample_experiment_id,
              },
              { key: "experiment_ids", title: "相关实验" },
            ]}
          />
        )}
      </Card>

      <Card
        title="实验"
        subtitle={`${ev.experiments.length} 条`}
        right={<TriState tri={ev.experiments_tri} label="experiments" />}
      >
        <PartialRows note={rowsNote(ev, "experiments", ev.experiments.length)} />
        {isUnreadable(ev.experiments_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : ev.experiments_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这个工作区里这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <PagedTable
            rows={ev.experiments}
            empty="0 条实验（读到了，里面是空的）。"
            columns={[
              { key: "experiment_id", title: "实验号" },
              { key: "status_word", title: "状态", render: (r) => statusCell(r) },
              { key: "method", title: "方法", render: (r) => cell(r.method) },
              { key: "result", title: "结论", render: (r) => cell(r.result) },
              { key: "evidence_kind", title: "证据档", render: (r) => cell(r.evidence_kind) },
              { key: "negation_kind", title: "否定档", render: (r) => cell(r.negation_kind) },
              {
                key: "exit_code",
                title: "退出码",
                render: (r) => (r.exit_code === null ? "unknown" : String(r.exit_code)),
              },
              { key: "code_path", title: "代码", render: (r) => cell(r.code_path) },
              {
                // 这一格只说"台账钉的代码 sha 与盘上现在这一份脚本"一致不一致。
                // 三种"没得比"（没记 sha / 脚本不在盘上 / 读不出来）都落 unknown，
                // 不冒充"不一致"。第四档「已撤销」（脚本已改：旧 → 新）不是红。
                key: "code_sha_consistency",
                title: "代码一致",
                render: (r) => codeCell(r),
              },
              {
                // ②③ 的落点是 `out/experiments/<号>/exhaustion.md`
                // （V 会照它判证据档）。这一格把那份报告挂出来，没有就写「无」。
                key: "exhaustion_path",
                title: "报告",
                render: (r) => reportCell(r),
              },
              { key: "artifact_paths", title: "产物" },
            ]}
          />
        )}
      </Card>

      <Card
        title="审校发现"
        subtitle={`${ev.review_findings.length} 条`}
        right={<TriState tri={ev.review_findings_tri} label="review_findings" />}
      >
        <PartialRows note={rowsNote(ev, "review_findings", ev.review_findings.length)} />
        {isUnreadable(ev.review_findings_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : ev.review_findings_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这个工作区里这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <PagedTable
            rows={ev.review_findings}
            empty="0 条审校发现（读到了，里面是空的）。"
            columns={[
              { key: "finding_id", title: "发现号" },
              { key: "round", title: "轮次" },
              { key: "level", title: "档", render: (r) => cell(r.level) },
              { key: "kind", title: "类别", render: (r) => cell(r.kind) },
              { key: "axis", title: "轴", render: (r) => cell(r.axis) },
              {
                key: "line",
                title: "行",
                render: (r) => (r.line === null ? "unknown（没记行号）" : String(r.line)),
              },
              { key: "message", title: "正文" },
              { key: "status_word", title: "状态", render: (r) => statusCell(r) },
            ]}
          />
        )}
      </Card>

      <Card
        title="稿件台账"
        subtitle={`${ev.documents.length} 份`}
        right={<TriState tri={ev.documents_tri} label="documents" />}
      >
        <PartialRows note={rowsNote(ev, "documents", ev.documents.length)} />
        {isUnreadable(ev.documents_tri) ? (
          <span class="empty">这一栏没查成（不是"0 份"）。</span>
        ) : ev.documents_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这个工作区里这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <PagedTable
            rows={ev.documents}
            empty="0 份稿件（读到了，里面是空的）。"
            columns={[
              { key: "doc_id", title: "稿件号", render: (r) => cell(r.doc_id) },
              { key: "kind", title: "种类", render: (r) => cell(r.kind) },
              { key: "title", title: "标题", render: (r) => cell(r.title) },
              { key: "status_word", title: "状态", render: (r) => statusCell(r) },
              { key: "review_rounds", title: "审校轮次" },
              { key: "review_verdict", title: "审校结论", render: (r) => cell(r.review_verdict) },
              { key: "revision", title: "修订号" },
              { key: "updated_at", title: "最后改于", render: (r) => cell(r.updated_at) },
            ]}
          />
        )}
      </Card>

      <Card
        title="引文回验（relations 的五档 quote_state）"
        subtitle={`逐字 ${tally.verbatim} · 语义 ${tally.semantic} · 不一致 ${tally.mismatch} · 未查 ${tally.unchecked} · 没有可复核的区间 ${tally.no_evidence}`}
        right={<TriState tri={ev.relations_tri} label="relations" />}
      >
        <PartialRows note={rowsNote(ev, "relations", ev.relations.length)} />
        {isUnreadable(ev.relations_tri) ? (
          <span class="empty">这一栏没查成 —— 那五个数不是 0，是没读到。</span>
        ) : ev.relations_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这个工作区里这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <>
            <div class="readings">
              <span class="mono">{ev.relations.length}</span> 条关系；不是「逐字 / 语义」通过的那些
              须连同理由阅读。五档里「没有可复核的区间」与「未查」是两件事：前者说通过了、
              却指不出核的是哪一段（欠一次重核），后者是还没人查（欠一次回验）。
            </div>
            {notClean.length === 0 ? (
              <span class="empty">
                没有不是「逐字 / 语义」通过的引文。
              </span>
            ) : (
              <PagedTable
                rows={notClean}
                empty="没有不是「逐字 / 语义」通过的引文。"
                columns={[
                  { key: "relation_id", title: "关系号" },
                  {
                    key: "quote_state",
                    title: "回验",
                    render: (r) => {
                      const state = quoteStateOf(r);
                      const got = QUOTE_WORDS[state];
                      return got === undefined ? (
                        <span class="tri-reason">{state === "" ? "unknown" : state}</span>
                      ) : (
                        <Badge kind={got.kind} text={got.text} />
                      );
                    },
                  },
                  { key: "quote", title: "引文" },
                  { key: "statement", title: "断言" },
                ]}
              />
            )}
          </>
        )}
      </Card>

      <Card
        title="证明级（V 的验证台账）"
        subtitle={`${ev.verifications.length} 条 · reviewed 按证明逐条`}
        right={<TriState tri={ev.verifications_tri} label="verifications" />}
      >
        <PartialRows note={rowsNote(ev, "verifications", ev.verifications.length)} />
        <div class="readings">
          这一栏是 V 的签名行：<span class="mono">verdict</span> 只有「成立」显绿，其余档显黄
          （不假装通过）；<span class="mono">unresolved_errors</span> 与「证明一致」那一格要一起读，
          才知道这一行可不可回验。逐份证明的号与"签没签"在命题台账那一栏
          （<span class="mono">reviewed_paths</span>）；验证台账行按验证号 / 命题号读。
          sha 原文不上屏：那一格只说
          「一致 / 不一致 / unknown（没得比）」，比的是 V 签的那一份与命题现在这一份。
        </div>
        {isUnreadable(ev.verifications_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : ev.verifications_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这个工作区里这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <PagedTable
            rows={ev.verifications}
            empty="暂无验证台账（合法初态）。"
            columns={[
              { key: "verification_id", title: "验证号" },
              { key: "statement_id", title: "命题号" },
              { key: "verifier", title: "签名者" },
              {
                key: "verdict",
                title: "结论",
                render: (r) => (
                  <Badge
                    kind={r.verdict === "成立" ? "badge-pass" : "badge-unknown"}
                    text={cell(r.verdict)}
                  />
                ),
              },
              {
                // 这一格只说两份是不是同一份（sha 原文不上屏）。
                key: "proof_sha_consistency",
                title: "证明一致",
                render: (r) => (
                  <Consistency
                    value={r.proof_sha_consistency}
                    note="V 签的那一份证明与命题现在这一份（同一个证明号；命题正文没读到或那一行没记 sha ⇒ 没得比）"
                  />
                ),
              },
              { key: "unresolved_errors", title: "未解错误数" },
              { key: "at", title: "时间", render: (r) => cell(r.at) },
            ]}
          />
        )}
      </Card>

      <Card
        title="秘书决策"
        subtitle={`${ev.secretary.length} 条`}
        right={<TriState tri={ev.secretary_tri} label="secretary" />}
      >
        <PartialRows note={rowsNote(ev, "secretary", ev.secretary.length)} />
        {isUnreadable(ev.secretary_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : ev.secretary_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这个工作区里这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <PagedTable
            rows={ev.secretary}
            empty="还没有秘书决策台账（合法初态）。"
            columns={[
              { key: "role", title: "角色" },
              { key: "seq", title: "序号" },
              { key: "duty", title: "职责号" },
              { key: "decision", title: "决定", render: (r) => cell(r.decision) },
              {
                // 判据那一栏（R93 体检）：盘上它是一个**整份判定记录**（`basis`/`checked`/
                // `cost`/`decision`/`reason`…），只有"建议不派"那一类才有；"已执笔"这类
                // 不经判据的行它是 `null`。直接 `cell()` 会把对象印成 JSON 一大坨、
                // 把 `null` 印成 `unknown` —— 两种都不是给人看的。这里只读人真正要问的
                // 两件事：这一行经不经判据、判过没有；细节（依据/花销）折在理由那一栏里。
                key: "judge",
                title: "判据",
                render: (r) => {
                  const j = r.judge as Record<string, unknown> | null;
                  if (j === null || j === undefined) {
                    return <span class="tri-reason">不适用（这一行不经判据）</span>;
                  }
                  const checked = j["checked"];
                  const cost = j["cost"] as Record<string, unknown> | undefined;
                  const usd = cost === undefined ? undefined : cost["usd"];
                  return (
                    <>
                      <Badge
                        kind={checked === true ? "badge-pass" : "badge-unknown"}
                        text={checked === true ? "查过" : "没查成"}
                      />
                      {typeof usd === "number" ? (
                        <span class="mono"> {formatUsd(usd)}</span>
                      ) : null}
                    </>
                  );
                },
              },
              { key: "reason", title: "理由", render: (r) => cell(r.reason) },
              { key: "basis", title: "依据" },
              {
                key: "fail_open",
                title: "fail_open",
                // 走 `cell()`，与同页其余列同一个取值器：`out/secretary/` 下那份旁支台账
                // （`nontriviality.jsonl` / `proposition_verdicts.jsonl`）的行**根本没有**
                // `fail_open` 这一栏（真机读数：613 行里 143 行没有），`String()` 会把它们
                // 印成字面量 `undefined`。`undefined` 是"没读到"，不是"false"：这一列的
                // 三态就是 cell() 承诺的那三档。
                render: (r) => cell(r.fail_open),
              },
              { key: "target", title: "对象", render: (r) => cell(r.target) },
              { key: "at", title: "时间", render: (r) => cell(r.at) },
            ]}
          />
        )}
      </Card>
    </>
  );
}
