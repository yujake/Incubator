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
 * 5. 引文回验：`relations` 的 `quote_verified` 三个数（真 / 假 / 未查）——
 *    不是 true 的那些必须把 `quote_reason` 一起显出来，否则读的人不知道为什么；
 * 6. 证明级 `verifications`（裁定 K2：盘上无真机样本 ⇒ 夹具造一行；页面标明）；
 * 7. 秘书决策 `secretary`。
 */
import { api } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { Table, cell } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace } from "../live";
import type { RelationRow } from "../types";

/** 引文回验的三个数（真 / 假 / 未查）。读不到的那一档一律 `unknown`。 */
function quoteTally(rows: RelationRow[]): { yes: number; no: number; unchecked: number } {
  let yes = 0;
  let no = 0;
  let unchecked = 0;
  for (const r of rows) {
    if (r.quote_verified === true) {
      yes += 1;
    } else if (r.quote_verified === false) {
      no += 1;
    } else {
      unchecked += 1;
    }
  }
  return { yes, no, unchecked };
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
  const notTrue = ev.relations.filter((r) => r.quote_verified !== true);

  return (
    <>
      <Card
        title="证据链"
        subtitle={`七栏 · 整面 tri=${ev.tri}`}
        tone={isUnreadable(ev.tri) ? "problem" : "plain"}
        right={<TriState tri={ev.tri} label="证据面" reason={ev.reason} />}
      >
        <div class="readings">
          落点读数来自 <span class="mono">store.rows(...)</span> 七张表 + 验证台账 +
          秘书台账。每一栏另有一个自己的三态 —— 整面一个词会吞掉"哪一栏没读成"。
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
            empty="0 条命题（读到了，里面是空的 —— 不是「没查成」）。"
            columns={[
              { key: "stmt_id", title: "命题号" },
              { key: "status", title: "状态", render: (r) => cell(r.status) },
              { key: "kind", title: "类别", render: (r) => cell(r.kind) },
              { key: "label", title: "标签", render: (r) => cell(r.label) },
              { key: "statement_text", title: "正文" },
              {
                key: "quote_verified",
                title: "引文回验",
                render: (r) =>
                  r.quote_verified === null ? (
                    "未查"
                  ) : (
                    <Badge
                      kind={r.quote_verified ? "badge-pass" : "badge-fail"}
                      text={r.quote_verified ? "真" : "假"}
                    />
                  ),
              },
              { key: "quote_reason", title: "回验理由", render: (r) => cell(r.quote_reason) },
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
              { key: "code_hash", title: "代码 sha", render: (r) => cell(r.code_hash) },
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
        title="引文回验（relations 的 quote_verified）"
        subtitle={`真 ${tally.yes} · 假 ${tally.no} · 未查 ${tally.unchecked}`}
        right={<TriState tri={ev.relations_tri} label="relations" />}
      >
        {isUnreadable(ev.relations_tri) ? (
          <span class="empty">这一栏没查成 —— 那三个数不是 0，是没读到。</span>
        ) : (
          <>
            <div class="readings">
              一共 <span class="mono">{ev.relations.length}</span> 条关系。不是「真」的那些
              必须连理由一起看（`quote_reason` 是空的就写 unknown，不写空）。
            </div>
            {notTrue.length === 0 ? (
              <span class="empty">
                没有"不是真"的引文（读到了：这一批关系全是真或者一条关系都没有）。
              </span>
            ) : (
              <Table
                rows={notTrue}
                empty="没有不是真的引文。"
                columns={[
                  { key: "relation_id", title: "关系号" },
                  {
                    key: "quote_verified",
                    title: "回验",
                    render: (r) =>
                      r.quote_verified === false ? (
                        <Badge kind="badge-fail" text="假" />
                      ) : (
                        <Badge kind="badge-na" text="未查" />
                      ),
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
        subtitle={`${ev.verifications.length} 条`}
        right={<TriState tri={ev.verifications_tri} label="verifications" />}
      >
        <div class="readings">
          裁定 K2：盘上（真机）没有 <span class="mono">verifications/</span> 的样本 ⇒
          这一栏的读数由 `tests/conftest.py` 的夹具造（页面上如实标明"夹具样本"）。
        </div>
        {isUnreadable(ev.verifications_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : (
          <Table
            rows={ev.verifications}
            empty="这台机器还没有验证台账（合法初态：还没做过证明级验证）。"
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
              { key: "proof_sha256", title: "证明 sha" },
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
              { key: "judge", title: "判据", render: (r) => cell(r.judge) },
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
