/*
 * 论文包三块：A 证明完整吗 / B 结构合规吗 / C 能不能收工。
 *
 * 一次 `GET /api/package` 拿三块：三块总是一起看，一次请求才有同一份快照。
 * 每一格都带 `source`（path / line / match），由 `SourceLink` 走 `/api/source`
 * 点开原文 —— 没有出处的数字不许上屏。
 *
 * 三态纪律（这一页的全部价值所在）：
 * - 块级 `tri`：`computed` / `unreadable` / `not_applicable`；读不到写"没查成"，
 *   不写 0。没有正文 ⇒ B 块 `not_applicable`（不是 0 行、0 个定理）。
 * - 八格是四态：`pass` / `fail` / `unknown`（没查成）/ `na`（不适用）。
 * - 内容级验收五条**不进机器门**：`failed`（真不过）与 `unchecked`（没查成）
 *   分两栏显示，不许折成一个 "failed"。
 */
import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";

import { api } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { SourceLink } from "../components/SourceLink";
import { formatCount, formatUsd } from "../components/Money";
import { blank } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace } from "../live";

/** 后端 `closing` 的 detail 里带 `**`；源码不是 Markdown，上屏前逐字去掉。 */
function plain(text: string): string {
  return text.split("**").join("");
}

/** 一条命题的 review state（六态；不认识的词原样显示，不假装认识）。 */
function stateBadge(state: string): ComponentChildren {
  if (state === "signed") {
    return <Badge kind="badge-pass" text="已签" />;
  }
  if (state === "rejected") {
    return <Badge kind="badge-fail" text="有毛病" />;
  }
  if (state === "stale") {
    return <Badge kind="badge-unknown" text="待复核" />;
  }
  if (state === "holding") {
    return <Badge kind="badge-na" text="累积中" />;
  }
  if (state === "unsigned") {
    return <Badge kind="badge-na" text="没签过" />;
  }
  if (state === "unreadable") {
    return <Badge kind="badge-unknown" text="没查成" />;
  }
  return <Badge kind="badge-na" text={state === "" ? "unknown" : state} />;
}

/** 八格的四态（`na` 不许折进 `unknown`）。 */
function gateBadge(status: string): ComponentChildren {
  if (status === "pass") {
    return <Badge kind="badge-pass" text="过了" />;
  }
  if (status === "fail") {
    return <Badge kind="badge-fail" text="没过" />;
  }
  if (status === "unknown") {
    return <Badge kind="badge-unknown" text="没查成（不是通过）" />;
  }
  if (status === "na") {
    return <Badge kind="badge-na" text="不适用" />;
  }
  return <Badge kind="badge-na" text={status === "" ? "unknown" : status} />;
}

/** 内容级五条的三态（`unknown` 是没查成，不是没过）。 */
function reviewBadge(value: string): ComponentChildren {
  if (value === "pass") {
    return <Badge kind="badge-pass" text="过了" />;
  }
  if (value === "fail") {
    return <Badge kind="badge-fail" text="没过" />;
  }
  if (value === "unknown") {
    return <Badge kind="badge-unknown" text="没查成（不是通过）" />;
  }
  return <Badge kind="badge-na" text={value === "" ? "unknown" : value} />;
}

function canCloseWord(value: boolean | null): string {
  if (value === true) {
    return "可以交（机器口径成立）";
  }
  if (value === false) {
    return "不能交（机器口径不成立）";
  }
  return "没接线（算不出来，不是通过）";
}

export function Acceptance() {
  const [capText, setCapText] = useState("");
  const cap = capText.trim() === "" ? null : Number(capText);
  // 只有"读成一个有限数字"才算给了上限：`Number("abc")` 是 NaN，而后端的
  // `float("NaN")` 不抛 —— 那一格会从"没查成"变成一条假的"没过"。
  const usableCap = cap !== null && Number.isFinite(cap) ? cap : null;
  // `project_dir` / `report_path` 必须传：不传时 `_auxiliary` 的 tex / pdf / 回执
  // 三格按构造永远空/unknown（块 1 的缺陷）。`"."` 按后端 `resolve_under_workspace`
  // 解析成工作区根，不是进程 cwd。
  const face = useFace(() => api.getPackage({
    projectDir: ".",
    reportPath: "out/review/REPORT.md",
    capUsd: usableCap,
  }));

  if (face.data === null) {
    return (
      <Card
        title="论文包"
        tone={face.problem === "" ? "plain" : "problem"}
        right={face.problem === "" ? null : <TriState tri="unreadable" reason={face.problem} label="论文包" />}
      >
        <span class="readings">{face.problem === "" ? "正在读盘……" : face.problem}</span>
        {face.problem === "" ? null : (
          <div class="readings">
            若这一条是「没有这个端点」，说明 8720 的 web 服务进程还是改动前那一版
            （路由表在导入期固化）：刷新只换前端，需要重启 web 服务进程；
            正在跑的那一趟（82）不要动。
          </div>
        )}
      </Card>
    );
  }

  const pkg = face.data;
  const proofs = pkg.proofs;
  const structure = pkg.structure;
  const closing = pkg.closing;
  const gates = closing.gates;
  const content = closing.content;
  // machine_pass 的两句判词各问一件事（哪些格失败 / 哪些格没全 pass）。改前每句都
  // 各扫两遍（some 判有没有 + filter 取清单），这里分两组各扫一遍，两句各取一组。
  const failedCells = gates.blocking_cells.filter((one) => one.status === "fail");
  const notPassCells = gates.blocking_cells.filter((one) => one.status !== "fail");
  // 一份权威结论（ROOTGATE-②）：verdict · 八格逐格 · 红格的 why · m_says_done 并列显示。
  // 没有这一格（旧后端）时退回逐格读数，不假装"没有结论"。
  const authority = gates.closing_verdict ?? null;
  const redCells = authority === null
    ? []
    : authority.cells.filter((one) => one.status !== "pass");
  const authorityRetire = authority === null
    ? "没查成"
    : String((authority.retire["state"] as string | undefined) ?? "没查成");
  const authorityPrograms = authority === null
    ? "没查成"
    : String((authority.programs["state"] as string | undefined) ?? "没查成");

  return (
    <>
      <Card
        title="论文包"
        subtitle="A 证明完整吗 · B 结构合规吗 · C 能不能收工"
        tone={isUnreadable(pkg.tri) ? "problem" : "plain"}
        right={<TriState tri={pkg.tri} label="论文包" reason={pkg.reason} />}
      >
        <div class="readings">
          生成时刻 <span class="mono">{pkg.generated_at}</span>；三块一次读盘。
          读不到就写「没查成（不是通过）」，不写 0。
        </div>
        {pkg.reason === "" ? null : (
          <div class="readings">三块里没查成的部分：<span class="mono">{pkg.reason}</span></div>
        )}
        <div class="card-head">
          <span class="caption">成本上限（cap_usd）</span>
          <input
            class="input"
            type="text"
            placeholder="不给就不用：那一格会记「没查成」"
            value={capText}
            onInput={(ev) => {
              setCapText(ev.currentTarget.value);
            }}
          />
          <span class="readings">
            当前：
            <span class="mono">
              {cap === null || Number.isNaN(cap)
                ? "没给（那一格必为没查成）"
                : formatUsd(cap)}
            </span>
          </span>
        </div>
      </Card>

      <Card
        title="A 证明完整吗"
        subtitle="每 statement 的 review state · streak · V 签覆盖率 · 回执送达"
        tone={isUnreadable(proofs.tri) ? "problem" : "plain"}
        right={<TriState tri={proofs.tri} label="证明面" reason={proofs.reason} />}
      >
        {proofs.tri === "unreadable" ? (
          <span class="empty">{proofs.reason || "证明那一块没查成"}</span>
        ) : (
          <>
            <div class="readings">
              正文定理类环境 <span class="mono">{formatCount(proofs.paper_theorem_envs)}</span> ·
              有证明的命题 <span class="mono">{formatCount(proofs.propositions_with_proof)}</span> ·
              台账定理类 <span class="mono">{formatCount(proofs.ledger_theorem_kinds)}</span> ·
              V 已签（阅签状态为 signed 的命题）{" "}
              <span class="mono">{formatCount(proofs.signed)}</span>
              <SourceLink source={proofs.source} label="验收表" />
            </div>
            <div class="readings">{proofs.coverage_note}</div>
            <div class="readings">
              C3「{proofs.c3.name || "逐行走查签字的证明"}」：
              <span class="mono">{formatCount(proofs.c3.got)}</span> / 要求 ≥
              <span class="mono">{formatCount(proofs.c3.min)}</span> ·
              {proofs.c3.ok ? " 过了" : " 没过"} <SourceLink source={proofs.c3.source} label="验收表" />
            </div>

            <div class="readings">
              V 签侧文件：<span class="mono">out/vsigns/</span> 在盘上
              <span class="mono">{proofs.vsign.files}</span> 份 · 复算通过（这就是「签了几份」）{" "}
              <span class="mono">{formatCount(proofs.vsign.recomputable)}</span> 份 · 状态
              <span class="mono">{proofs.vsign.tri}</span>
              <SourceLink source={proofs.vsign.source} label="签文件" />
            </div>
            <div class="readings">
              第 3 位为真（签过）<span class="mono">{proofs.vsign.signed.length}</span> 条 ·
              其中盘上有对应签文件 <span class="mono">{proofs.vsign.backed.length}</span> 条 ·
              其中没有侧文件 <span class="mono">{proofs.vsign.without_sign.length}</span> 条
              （历史签 / 直调写的签：它是 `signed` 的子集，不是另一个签数）· 孤儿签{" "}
              <span class="mono">{proofs.vsign.orphan_signs.length}</span> 份
            </div>
            <div class="readings">
              签台账 <span class="mono">{proofs.vsign.ledger_path}</span>{" "}
              {proofs.vsign.ledger_present === null ? (
                <Badge kind="badge-unknown" text="不知道（整块没查成）" />
              ) : proofs.vsign.ledger_present ? (
                <Badge kind="badge-na" text="在盘上（索引，不是签）" />
              ) : (
                <Badge kind="badge-na" text="不在盘上" />
              )}
            </div>
            {proofs.vsign.note === "" ? null : (
              <div class="readings tri-reason">{proofs.vsign.note}</div>
            )}
            {proofs.vsign.reason === "" ? null : (
              <div class="readings">{proofs.vsign.reason}</div>
            )}

            <div class="readings">
              回执：<span class="mono">{proofs.receipt.receipts}</span> 条
              （<span class="mono">{proofs.receipt.statements}</span> 条命题）· 已投出
              <span class="mono">{proofs.receipt.dispatched}</span>（送达
              <span class="mono">{proofs.receipt.delivered}</span>）· 未投出
              <span class="mono">{proofs.receipt.not_dispatched}</span> · 未送达
              <span class="mono">{proofs.receipt.undelivered}</span>
              <SourceLink source={proofs.receipt.source} label="回执" />
            </div>
            {Object.keys(proofs.receipt.steps).length === 0 ? null : (
              <div class="readings">
                缺陷步分布：
                {Object.entries(proofs.receipt.steps).map(([step, n]) => `第${step}步×${n}`).join("、")}
                ；替人送审 <span class="mono">{proofs.receipt.submitter_is_not_author}</span> ·
                作者未记录 <span class="mono">{proofs.receipt.author_not_recorded}</span>
              </div>
            )}
            {proofs.receipt.reason === "" ? null : (
              <div class="readings">{proofs.receipt.reason}</div>
            )}

            <div class="caption">review 六态（分母 = 有 proof_text 的命题）</div>
            <table class="grid">
              <thead>
                <tr>
                  <th>状态</th>
                  <th>条数</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(proofs.review_states).sort().map(([state, count]) => (
                  <tr key={state}>
                    <td>{stateBadge(state)}</td>
                    <td class="mono">{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div class="caption">逐条命题（{proofs.rows.length} 行；每行带原文出处）</div>
            {proofs.rows.length === 0 ? (
              <span class="empty">一条带证明的命题都没读到（查过了，里面是 0 行）。</span>
            ) : (
              <table class="grid">
                <thead>
                  <tr>
                    <th>命题</th>
                    <th>状态</th>
                    <th>证明（streak/need）</th>
                    <th>缺陷步</th>
                    <th>原文</th>
                  </tr>
                </thead>
                <tbody>
                  {proofs.rows.map((row) => {
                    // 「缺陷步」这一格要两件事：有没有、有哪些。改前每行 flatMap 两次
                    // （先判 length、再 join），这里一次算好 —— 那一格的值一个都不变。
                    const defectSteps = row.proofs.flatMap((p) => p.defect_steps);
                    return (
                      <tr key={row.stmt_id}>
                        <td class="mono">{row.stmt_id} {row.label}</td>
                        <td>{stateBadge(row.state)}</td>
                        <td class="mono">
                          {row.proofs.length === 0 ? "—" : row.proofs.map((p) => (
                            <span key={p.proof_no}>
                              #{p.proof_no} {p.streak}/{p.need}
                              {p.streak_ok ? "（够了）" : ""}
                              {" "}
                              <SourceLink source={p.source} label="签行" />
                            </span>
                          ))}
                        </td>
                        <td class="mono">{defectSteps.length === 0 ? "—" : defectSteps.join("、")}</td>
                        <td><SourceLink source={row.source} label="台账行" /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </>
        )}
      </Card>

      <Card
        title="B 结构合规吗"
        subtitle="定理↔proof 配对 · cites/refs/inputs/duplicates · 字符六类 · 台账覆盖"
        tone={isUnreadable(structure.tri) ? "problem" : "plain"}
        right={<TriState tri={structure.tri} label="结构面" reason={structure.reason} />}
      >
        {structure.tri === "not_applicable" ? (
          <span class="empty">
            还没有可查的正文：{structure.reason}
            <SourceLink source={structure.source} label="正文" />
          </span>
        ) : structure.tri === "unreadable" ? (
          <span class="empty">{structure.reason || "结构那一块没查成"}</span>
        ) : (
          <>
            <div class="readings">
              正文 <span class="mono">{formatCount(structure.paper.lines)}</span> 行 ·
              <span class="mono">{formatCount(structure.paper.sections)}</span> 节 ·
              定理类 <span class="mono">
                {(structure.paper.env_counts.theorem ?? 0)
                  + (structure.paper.env_counts.lemma ?? 0)
                  + (structure.paper.env_counts.proposition ?? 0)
                  + (structure.paper.env_counts.corollary ?? 0)}
              </span> 个 · PDF <span class="mono">{formatCount(structure.paper.pdf_pages)}</span> 页 ·
              编译回执 <span class="mono">{structure.paper.receipt_verdict}</span>
              <SourceLink source={structure.source} label="正文" />
            </div>
            <div class="readings">
              定理类环境 <span class="mono">{formatCount(structure.ledger.statement_envs)}</span> ·
              proof 环境 <span class="mono">{formatCount(structure.ledger.proof_envs)}</span> ·
              命题台账行 <span class="mono">{formatCount(structure.ledger.statement_ledger_rows)}</span> ·
              命题 <span class="mono">{formatCount(structure.ledger.ledger_propositions)}</span> ·
              台账定理类 <span class="mono">{formatCount(structure.ledger.ledger_theorem_kinds)}</span> ·
              对应表 <span class="mono">{formatCount(structure.ledger.mapping_rows)}</span> ·
              surplus <span class="mono">{structure.ledger.statement_surplus.length}</span>
            </div>

            <div class="caption">七类扫描（`review.scan` 的同一份实现）</div>
            <table class="grid">
              <thead>
                <tr>
                  <th>类</th>
                  <th>三态</th>
                  <th>命中</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(structure.checks).map(([kind, check]) => (
                  <tr key={kind}>
                    <td class="mono">{kind}</td>
                    <td>{check.checked ? <Badge kind="badge-pass" text="查了" /> : <Badge kind="badge-unknown" text="没查成" />}</td>
                    <td class="mono">{check.findings}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div class="readings">
              字符六类：
              {["cjk", "control", "zero_width", "replacement", "bidi", "nbsp"].map((name) => (
                <span key={name} class="mono">{name}={structure.checks.text_integrity?.counts[name] ?? "—"} </span>
              ))}
            </div>

            <div class="caption">命中（{structure.findings.length} 条；每条都能点开原文）</div>
            {structure.findings.length === 0 ? (
              <span class="empty">没有命中（查过了，里面是 0 条）。</span>
            ) : (
              <table class="grid">
                <thead>
                  <tr>
                    <th>类</th>
                    <th>级别</th>
                    <th>位置</th>
                    <th>为什么</th>
                    <th>原文</th>
                  </tr>
                </thead>
                <tbody>
                  {structure.findings.map((f, i) => (
                    <tr key={`${f.file}:${f.line}:${i}`}>
                      <td class="mono">{f.kind}</td>
                      <td class="mono">{f.severity}</td>
                      <td class="mono">{f.file}:{f.line} {f.ref}</td>
                      <td>{plain(f.why)}</td>
                      <td><SourceLink source={f.source} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </Card>

      <Card
        title="C 能不能收工"
        subtitle="八格四态 · machine_pass · can_close 三态 · retire · 成本 · 时间轴"
        tone={isUnreadable(closing.tri) ? "problem" : "plain"}
        right={<TriState tri={closing.tri} label="收工面" reason={closing.reason} />}
      >
        {closing.tri === "unreadable" ? (
          <span class="empty">{closing.reason || "收工那一块没查成"}</span>
        ) : (
          <>
            <div class="readings">
              八格计数：pass <span class="mono">{gates.counts.pass}</span> ·
              fail <span class="mono">{gates.counts.fail}</span> ·
              unknown <span class="mono">{gates.counts.unknown}</span> ·
              na <span class="mono">{gates.counts.na}</span> ·
              machine_pass <span class="mono">{String(gates.machine_pass)}</span> ·
              can_close <span class="mono">{canCloseWord(gates.can_close)}</span>
            </div>
            <div class="readings">
              M 判据：m_says_done <span class="mono">{String(gates.m_says_done)}</span> ·
              {gates.verdict_met === null ? "没有人判过" : `met ${String(gates.verdict_met)}`}
              {gates.verdict_at === "" ? "" : `（${gates.verdict_at}）`}
              {gates.can_close_reason === "" ? "" : `；${plain(gates.can_close_reason)}`}
              <SourceLink source={closing.source} label="判据行" />
            </div>

            {/* 一份权威结论（ROOTGATE-②）：结论 + m_says_done + retire/programs 并列；
                红格逐条列出 why —— 不许让上面任何一行绿色读数盖住它们。 */}
            {authority === null ? null : (
              <div class="readings">
                收工结论：
                <span class="mono">{` ${authority.verdict} `}</span>
                （exit <span class="mono">{String(authority.exit_code)}</span>）·
                m_says_done <span class="mono">{String(authority.m_says_done)}</span> ·
                retire <span class="mono">{authorityRetire}</span> ·
                programs <span class="mono">{authorityPrograms}</span>
                {authority.reason === "" ? null : (
                  <div class="caption">{plain(authority.reason)}</div>
                )}
                {redCells.length === 0 ? null : (
                  <ul class="caption">
                    {redCells.map((one) => (
                      <li>
                        <span class="mono">{one.check}</span>
                        {" = "}
                        {one.status}
                        {one.why === "" ? "" : `：${plain(one.why)}`}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            <table class="grid">
              <thead>
                <tr>
                  <th>格</th>
                  <th>四态</th>
                  <th>原话</th>
                  <th>原文</th>
                </tr>
              </thead>
              <tbody>
                {gates.cells.map((cell) => (
                  <tr key={cell.name}>
                    <td class="mono">{cell.name}</td>
                    <td>{gateBadge(cell.status)}</td>
                    <td>{blank(plain(cell.detail))}</td>
                    <td><SourceLink source={cell.source} /></td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* machine_pass=false 有两条来源 —— 格失败与 blocker。
                空 blockers 不等于"门没拦住"，只看 counts 又会漏掉不进八格的 blocker。 */}
            {gates.machine_pass_cause === "pass" ? (
              <div class="readings">机器口径成立：八格全 pass 且没有 blocker。</div>
            ) : (
              <div class="readings">
                machine_pass=false 的原因：
                {failedCells.length > 0
                  ? `因格失败：${failedCells.map((one) => `${one.name}=${one.status}`).join("、")}；`
                  : ""}
                {notPassCells.length > 0
                  ? `格没全 pass：${notPassCells.map((one) => `${one.name}=${one.status}`).join("、")}；`
                  : ""}
                {gates.blockers.length > 0
                  ? `blocker ${gates.blockers.length} 条（清单在下面）；`
                  : ""}
                {gates.machine_pass_cause === "unknown"
                  ? "既没有格失败也没有 blocker —— 这是一条缺陷读数（不许静默）。"
                  : ""}
              </div>
            )}
            {gates.blockers.length === 0 ? null : (
              <>
                <div class="caption">blocker（{gates.blockers.length} 条；不进八格，却拦 machine_pass）</div>
                <table class="grid">
                  <thead>
                    <tr>
                      <th>格</th>
                      <th>码</th>
                      <th>级别</th>
                      <th>原话</th>
                    </tr>
                  </thead>
                  <tbody>
                    {gates.blockers.map((b, i) => (
                      <tr key={`${b.check}:${b.code}:${i}`}>
                        <td class="mono">{b.check}</td>
                        <td class="mono">{b.code}</td>
                        <td class="mono">{b.level}</td>
                        <td>{blank(plain(b.detail))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            <div class="readings">
              机器口径：retire <span class="mono">{String(closing.machine.retire_complete)}</span>
              （在册 <span class="mono">{closing.machine.retire_nodes}</span> · 未消
              <span class="mono">{closing.machine.retire_open_items}</span>）·
              程序在跑 <span class="mono">{closing.machine.programs_running_count}</span> ·
              <span class="mono">{closing.machine.reason}</span>
              <SourceLink source={closing.machine.source} label="名册" />
            </div>

            <div class="readings">
              成本：事件求和 <span class="mono">{formatUsd(closing.cost.event_usd)}</span> ·
              收工行自报 <span class="mono">{formatUsd(closing.cost.spend_usd)}</span> ·
              无人认领 <span class="mono">{formatUsd(closing.cost.unattributed_usd)}</span> ·
              没有自报账的趟 <span class="mono">{closing.cost.runs_without_spend}</span> ·
              usage_ledger <span class="mono">{formatUsd(closing.cost.ledger_usd)}</span>
              （<span class="mono">{formatCount(closing.cost.usage_ledger_rows)}</span> 行）
              <SourceLink source={closing.cost.source} label="台账" />
            </div>
            {/* 四个数并排却不给差额的解释 = 读者只能说"三个对不上"（`draft/187` P4-1 / B10）。
                差额 = 归口里 extract 那几笔（事件流里没有这些调用）；账本行数另不等于
                事件里的调用数（一次调用可记 0..n 行）。 */}
            <div class="readings">
              成本对账：账本 − 事件 ={" "}
              <span class="mono">{formatUsd(closing.cost.reconciliation.ledger_minus_event_usd)}</span>
              {closing.cost.reconciliation.explained_by_extract === null
                ? "（有一边没读到 ⇒ 差额算不出来，不是 0）"
                : closing.cost.reconciliation.explained_by_extract
                  ? " = 归口里 extract 那几笔（事件流里没有这些调用）"
                  : " ≠ 归口里 extract 那几笔（差额还有别的来源，别当它是 extract）"}
              ：extract <span class="mono">{formatUsd(closing.cost.reconciliation.extract_usd)}</span>
              （<span class="mono">{formatCount(closing.cost.reconciliation.extract_entries)}</span> 笔）
              · usage_ledger 行 <span class="mono">{formatCount(closing.cost.usage_ledger_rows)}</span> 行 vs
              事件里的调用{" "}
              <span class="mono">{formatCount(closing.cost.reconciliation.event_llm_calls)}</span>{" "}
              次（不是同一个数）
              {closing.cost.reconciliation.note === "" ? null : (
                <div class="caption">{closing.cost.reconciliation.note}</div>
              )}
            </div>

            <div class="readings">
              时间轴：<span class="mono">{formatCount(closing.runtime.runs_total)}</span> 趟 ·
              未闭合 <span class="mono">{formatCount(closing.runtime.open_runs)}</span> ·
              已跑 <span class="mono">{formatCount(closing.runtime.elapsed_sec)}</span> 秒 ·
              最后收工读数 <span class="mono">{blank(closing.runtime.last_closing_at)}</span>
            </div>
            <div class="readings">
              名册：节点 <span class="mono">{closing.runtime.roster_nodes}</span> ·
              台账子 <span class="mono">{formatCount(closing.runtime.children_in_ledger)}</span> ·
              名册项 <span class="mono">{formatCount(closing.runtime.roster_child_count)}</span> ·
              未销号 <span class="mono">{formatCount(closing.runtime.children_unretired)}</span> ·
              活跃 <span class="mono">{formatCount(closing.runtime.active_child_count)}</span> ·
              未登记 <span class="mono">{closing.runtime.unplaced}</span>
              <SourceLink source={closing.runtime.source} label="会话" />
            </div>

            <details>
              <summary class="readings">
                内容级验收（只读，不进机器门）：{content.failed.length} 条真不过 ·
                {content.unchecked.length} 条没查成
              </summary>
              <div class="readings">{content.note}</div>
              <table class="grid">
                <thead>
                  <tr>
                    <th>判据</th>
                    <th>结论</th>
                    <th>读数</th>
                    <th>原文</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(content.criteria).sort().map(([key, value]) => (
                    <tr key={key}>
                      <td class="mono">{key}<br />{content.titles[key] ?? ""}</td>
                      <td>{reviewBadge(value)}</td>
                      <td>{blank(plain(content.details[key] ?? ""))}</td>
                      <td>
                        <SourceLink source={content.sources[key] ?? { path: "", line: 0, match: "", label: "" }} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div class="readings">
                真不过：<span class="mono">{content.failed.join("、") || "无"}</span>；
                没查成：<span class="mono">{content.unchecked.join("、") || "无"}</span>
              </div>
            </details>
          </>
        )}
      </Card>
    </>
  );
}
