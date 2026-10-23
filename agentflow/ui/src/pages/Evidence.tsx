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
 * ## 2026-10-23（业主：显示格式过时了）
 *
 * - sha 原文一律不上屏：证明那一栏只印"一致 / 不一致 / unknown（没得比）"
 *   （比的是 V 签的那一份 vs 命题现在这一份，见那一栏的副标题）；
 * - 命题多两格：非平凡度（`T0`–`T4` 或"未判"）与形式化第 4 位的逐路径读数
 *   （`{证明号: 状态}` 是二维的，折成一条汇总就等于让 `#p2` 借 `#p1` 的光）；
 * - reviewed 按证明逐条显示：验证行的第一格就是证明号（`proof_no`）。
 *
 * ## 2026-10-23 第二批（业主：五元位只展开了第 4 位 / 实验表没挂报告）
 *
 * - 五元位每一位一格：第 1 位 numeric、第 2 位 proof、第 3 位 reviewed、
 *   第 4 位 formal（仍是按路径那一格）、第 5 位 audited 各占一列 ——
 *   改前只有第 4 位在屏幕上，其余四位要从派生的等级去猜；
 * - 第 3 位与第 4 位同一个样式：一份证明一格（`#p1 已签 ｜ #p2 未签`）；
 * - 实验表补「报告」一列：`out/experiments/<号>/exhaustion.md`（②③ 的唯一落点）。
 *   链接指向产物页那张实验落点卡（报告不在 web 服务的静态路由下，直接链文件是死链），
 *   没有报告写「无」而不是留空。
 */
import { api } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { Consistency } from "../components/Consistency";
import { Nontriviality } from "../components/Nontriviality";
import { Table, cell } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace } from "../live";
import type { ExperimentRow, RelationRow, StatementRow } from "../types";

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

/** 引文那一格：五档各有自己的词（`no_evidence` 与"未查"欠的东西不同，不许合并）。 */
function quoteCell(r: StatementRow) {
  if (r.proof_text === "" && quoteStateOf(r) === "unchecked") {
    return <span class="tri-reason">不适用（这一行没有逐字摘录）</span>;
  }
  const state = quoteStateOf(r);
  const got = QUOTE_WORDS[state];
  return got === undefined ? (
    <span class="tri-reason">{state === "" ? "unknown" : state}</span>
  ) : (
    <Badge kind={got.kind} text={got.text} />
  );
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

/** 引文回验的五档计数（读不到的那一档一律算"未查"）。 */
function quoteTally(rows: RelationRow[]): Record<string, number> {
  const out: Record<string, number> = {
    verbatim: 0,
    semantic: 0,
    mismatch: 0,
    unchecked: 0,
    no_evidence: 0,
  };
  for (const r of rows) {
    const key = quoteStateOf(r);
    out[key] = (out[key] ?? 0) + 1;
  }
  return out;
}

export function Evidence() {
  const face = useFace(() => api.getEvidence());

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
  const tally = quoteTally(ev.relations);
  const notClean = ev.relations.filter((r) => {
    const state = quoteStateOf(r);
    return state !== "verbatim" && state !== "semantic";
  });

  return (
    <>
      <Card
        title="证据链"
        subtitle={`七栏 · 整面 tri=${ev.tri}`}
        tone={isUnreadable(ev.tri) ? "problem" : "plain"}
        right={<TriState tri={ev.tri} label="证据面" reason={ev.reason} />}
      >
        <div class="readings">
          七张表 + 验证台账 + 秘书台账；每一栏各有自己的三态。
        </div>
        {ev.store_problems.length === 0 ? null : (
          <div class="readings">
            读盘问题 <span class="mono">{ev.store_problems.join("；")}</span>
          </div>
        )}
      </Card>

      <Card
        title="命题台账"
        subtitle={`${ev.statements.length} 条`}
        right={<TriState tri={ev.statements_tri} label="statements" />}
      >
        {isUnreadable(ev.statements_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : (
          <Table
            rows={ev.statements}
            empty="暂无命题（已读出）。"
            columns={[
              { key: "stmt_id", title: "命题号" },
              {
                // 2026-10-23（业主：命题要标注非平凡度等级）：一格 `T0`–`T4` 或"未判"，
                // hover 给这一档的语义。未判不是 T0（0 从 2026-10-23 起是一档真的档位）。
                key: "nontriviality_label",
                title: "非平凡度",
                render: (r) => (
                  <Nontriviality
                    label={r.nontriviality_label}
                    meaning={r.nontriviality_meaning}
                    tri={r.nontriviality_tri}
                  />
                ),
              },
              { key: "status", title: "状态", render: (r) => cell(r.status) },
              { key: "kind", title: "类别", render: (r) => cell(r.kind) },
              { key: "label", title: "标签", render: (r) => cell(r.label) },
              {
                // 派生等级（五元位现算：任一路径通过即正式定理）。它不是谁自报的，
                // 所以与下面五格并排读：一个说多不平凡、一个说到没到定理。
                key: "grade",
                title: "派生等级",
                render: (r) =>
                  r.grade_label === "" ? (
                    <span class="tri-reason">unknown（五元位算不出来）</span>
                  ) : (
                    r.grade_label
                  ),
              },
              {
                // 五元位第 1 位（2026-10-23 第二批：每一位一格）。数值实验那一位
                // 是四态（`pending` / `na` / `failed` / `verified`），不是布尔。
                key: "bit_numeric",
                title: "第 1 位·numeric（数值实验）",
                render: (r) => bitCell(r.bit_numeric),
              },
              {
                key: "bit_proof",
                title: "第 2 位·proof（有证明）",
                render: (r) => bitCell(r.bit_proof),
              },
              {
                // 第 3 位按证明逐条签：一份证明一格（与第 4 位同一个样式）。
                key: "reviewed_paths",
                title: "第 3 位·reviewed（按证明）",
                render: (r) => reviewedCell(r),
              },
              {
                // 五元位第 4 位（2026-10-22 起是二维的）：一份证明一行。
                key: "formal_paths",
                title: "第 4 位·formal（按路径）",
                render: (r) => formalCell(r),
              },
              {
                key: "bit_audited",
                title: "第 5 位·audited（正式审查）",
                render: (r) => bitCell(r.bit_audited),
              },
              {
                // 正文（R93 体检）：盘上 `statement_text`（短版）常常是空的，而
                // `statement_full`（含完整假设的那一版）有字 —— 旧版直接印
                // `statement_text`，于是整列 7 行全是 `unknown`，看着像"没读到"。
                // 两者的分工是"短版 / 含假设全文"（`schema.Statement` 的 docstring），
                // 不是"有 / 没有"，所以这里按"短版优先、缺席退回全文"读，并说清退的是哪一版。
                key: "statement_text",
                title: "正文",
                render: (r) => {
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
                },
              },
              {
                // 引文回验（2026-10-23：五档）。比对对象是 `proof_text` 那一栏的逐字
                // 摘录，概念行结构上就没有引文 ⇒ 那一档是不适用，不是"未查"。
                // 五档：逐字通过 / 语义通过 / 不一致 / 未查 / 没有可复核的区间
                // （最后一档是"说通过了、而盘上拿不出可复核的区间"，与"还没查"欠的
                // 东西不同 —— 折平会让读的人去补一条不存在的工序）。
                key: "quote_state",
                title: "引文回验",
                render: (r) => quoteCell(r),
              },
              {
                // 2026-10-23 第二批：五元位那五格插在「派生等级」后面，这一格
                // （回验理由）跟着往后挪了一格 —— 内容一个字没动。
                key: "quote_reason",
                title: "回验理由",
                render: (r) => cell(r.quote_reason),
              },
            ]}
          />
        )}
      </Card>

      <Card
        title="猜想与反例"
        subtitle={`${ev.conjectures.length} 条`}
        right={<TriState tri={ev.conjectures_tri} label="conjectures" />}
      >
        {isUnreadable(ev.conjectures_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : (
          <Table
            rows={ev.conjectures}
            empty="0 条猜想（读到了，里面是空的）。"
            columns={[
              { key: "conjecture_id", title: "猜想号" },
              { key: "status", title: "状态", render: (r) => cell(r.status) },
              { key: "form", title: "形态", render: (r) => cell(r.form) },
              {
                key: "testable",
                title: "可检验",
                render: (r) => (r.testable === null ? "unknown" : String(r.testable)),
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
        {isUnreadable(ev.experiments_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : (
          <Table
            rows={ev.experiments}
            empty="0 条实验（读到了，里面是空的）。"
            columns={[
              { key: "experiment_id", title: "实验号" },
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
                // 2026-10-23（业主：sha 原文不显示）：这一格只说"台账钉的代码 sha 与盘上
                // 现在这一份脚本"一致不一致。三种"没得比"（没记 sha / 脚本不在盘上 /
                // 读不出来）都落 unknown，不冒充"不一致"。
                key: "code_sha_consistency",
                title: "代码一致",
                render: (r) => (
                  <Consistency
                    value={r.code_sha_consistency}
                    note="台账钉住的代码 sha 与盘上现在这一份脚本（脚本不在盘上或那一行没记 sha ⇒ 没得比）"
                  />
                ),
              },
              {
                // 2026-10-23 第二批（业主：实验表没挂穷举论证报告）：②③ 的落点是
                // `out/experiments/<号>/exhaustion.md`（V 会照它判证据档）。
                // 这一格把那份报告挂出来，没有就写「无」。
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
        {isUnreadable(ev.review_findings_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : (
          <Table
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
              { key: "status", title: "状态", render: (r) => cell(r.status) },
            ]}
          />
        )}
      </Card>

      <Card
        title="引文回验（relations 的五档 quote_state）"
        subtitle={`逐字 ${tally.verbatim} · 语义 ${tally.semantic} · 不一致 ${tally.mismatch} · 未查 ${tally.unchecked} · 没有可复核的区间 ${tally.no_evidence}`}
        right={<TriState tri={ev.relations_tri} label="relations" />}
      >
        {isUnreadable(ev.relations_tri) ? (
          <span class="empty">这一栏没查成 —— 那五个数不是 0，是没读到。</span>
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
              <Table
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
        <div class="readings">
          这一栏是 V 的签名行：<span class="mono">verdict</span> 只有「成立」显绿，其余档显黄
          （不假装通过）；<span class="mono">unresolved_errors</span> 与「证明一致」那一格要一起读，
          才知道这一行可不可回验。第一格是证明号（<span class="mono">proof_no</span>）——
          一个定理有多条证明路径时，reviewed 是逐条签的。sha 原文不上屏：那一格只说
          「一致 / 不一致 / unknown（没得比）」，比的是 V 签的那一份与命题现在这一份。
        </div>
        {isUnreadable(ev.verifications_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : (
          <Table
            rows={ev.verifications}
            empty="暂无验证台账（合法初态）。"
            columns={[
              { key: "verification_id", title: "验证号" },
              { key: "statement_id", title: "命题号" },
              {
                // reviewed 按证明逐条：证明号是这一格的主键（`#p1` 是 canonical 那一份）。
                key: "proof_no",
                title: "证明号",
                render: (r) => <span class="mono">#{r.proof_no}</span>,
              },
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
                // 2026-10-23（业主：sha 原文不显示）：这一格就是原来的「证明 sha」，
                // 现在只说两份是不是同一份。
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
        {isUnreadable(ev.secretary_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : (
          <Table
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
                // 不经判据的行它是 `null`。旧版直接 `cell()` ——对象被 String() 成
                // `[object Object]`（后来改成 JSON 一大坨），`null` 则印成 `unknown`。
                // 两种都不是给人看的。这里只读人真正要问的两件事：这一行经不经判据、
                // 判过没有；细节（依据/花销）折在理由那一栏里已有。
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
                        <span class="mono"> ${usd.toFixed(6)}</span>
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
                render: (r) => String(r.fail_open),
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
