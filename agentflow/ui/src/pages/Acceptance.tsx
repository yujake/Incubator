/*
 * 收工门内容级验收（`draft/74 §3.6` 逐行落）。
 *
 * 输入：`api.getAcceptance({projectDir, reportPath, capUsd})` → `AcceptanceView`
 * （B 线的 `readers.acceptance_face` ← `reviewaccept.check_review`）。SSE：`state`。
 *
 * 这一页的词表与别处不同，必须原样保留 —— `criteria` 的值是
 * `pass` / `fail` / `unknown`（`reviewaccept` 的判据读数），它不是 `Tri` 的三个词，
 * 也不是 `ReportTri` 的三个词。三态纪律在这里的落点是把它们**逐档分清**：
 *
 * - `pass` ⇒ 绿；
 * - `fail` ⇒ 红（这一格查过了、结论是没过）；
 * - `unknown` ⇒ 黄（这一格**没查成**）——`draft/74 §3.6` 第 3 行点名的就是这一档：
 *   不给 `cap_usd` ⇒「在成本上限内」那一格是"没查成"，**不是通过**；
 * - 上表没有的词 ⇒ 灰 + 原样显示那个词（不假装认识它）。
 *
 * 两处**如实标注的缺口**：第 4 行（与工具面 `conductor.closing` 同源的第二读数）
 * 与第 5 行（污染面），`AcceptanceView` 里都没有对应的栏，今天也没有别的端点给它们。
 */
import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";

import { api } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace } from "../live";

/** 一个判据格的视觉档（`pass` / `fail` / `unknown` 三档 + 不认识的词那一档）。 */
function verdictBadge(value: string): ComponentChildren {
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

export function Acceptance() {
  const [capText, setCapText] = useState("");
  const cap = capText.trim() === "" ? null : Number(capText);
  const face = useFace(() => api.getAcceptance({ capUsd: cap }));

  if (face.data === null) {
    return (
      <Card
        title="验收"
        tone={face.problem === "" ? "plain" : "problem"}
        right={face.problem === "" ? null : <TriState tri="unreadable" reason={face.problem} label="验收面" />}
      >
        <span class="readings">{face.problem === "" ? "正在读盘……" : face.problem}</span>
      </Card>
    );
  }

  const acc = face.data;
  const criteria = Object.keys(acc.criteria).sort();
  const auxiliary = Object.keys(acc.auxiliary).sort();
  const unknownCells = criteria.filter((k) => acc.criteria[k] === "unknown");

  return (
    <>
      <Card
        title="内容级验收（收工门）"
        subtitle={`${criteria.length} 条判据 + ${auxiliary.length} 条辅助读数`}
        tone={isUnreadable(acc.tri) ? "problem" : "plain"}
        right={<TriState tri={acc.tri} label="验收面" reason={acc.reason} />}
      >
        <div class="readings">
          判据名唯一来源：<span class="mono">reviewaccept.CRITERIA</span> 与 <span class="mono">AUXILIARY_SIGNALS</span>。
        </div>
        {acc.failed.length === 0 ? null : (
          <div class="readings">
            不是 pass 的格子 <span class="mono">{acc.failed.join("、")}</span>
 （后端把 fail 与 unknown 都放进 failed；逐条看「结论」列）
          </div>
        )}
        {unknownCells.length === 0 ? null : (
          <div class="readings">
            没查成的格子（不是通过）<span class="mono">{unknownCells.join("、")}</span>
          </div>
        )}
        <div class="card-head">
          <span class="caption">成本上限（cap_usd）</span>
          <input
            class="input"
            type="text"
            placeholder="不给就用不着：那一格会记「没查成」"
            value={capText}
            onInput={(ev) => {
              setCapText(ev.currentTarget.value);
            }}
          />
          <span class="readings">
            当前：<span class="mono">{cap === null || Number.isNaN(cap) ? "没给（那一格必为没查成）" : `$${cap}`}</span>
          </span>
        </div>
      </Card>

      <Card title="五条判据" subtitle="逐条：名字 · 三态 · 读数">
        {criteria.length === 0 ? (
          <span class="empty">一条判据都没读到（即"没查成"）。</span>
        ) : (
          <table class="grid">
            <thead>
              <tr>
                <th>判据</th>
                <th>结论</th>
                <th>读数</th>
              </tr>
            </thead>
            <tbody>
              {criteria.map((k) => {
                const detail = acc.details[k] ?? "";
                return (
                  <tr key={k}>
                    <td class="mono">{k}</td>
                    <td>{verdictBadge(acc.criteria[k] ?? "")}</td>
                    <td class="mono">{detail === "" ? "unknown" : detail}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="五种辅助读数" subtitle="逐条同形（读不出来写 unknown，不写 0）">
        {auxiliary.length === 0 ? (
          <span class="empty">一条辅助读数都没读到。</span>
        ) : (
          <table class="grid">
            <thead>
              <tr>
                <th>辅助读数</th>
                <th>值</th>
              </tr>
            </thead>
            <tbody>
              {auxiliary.map((k) => {
                const v = acc.auxiliary[k] ?? "";
                return (
                  <tr key={k}>
                    <td class="mono">{k}</td>
                    <td class="mono">{v === "" ? "unknown（没读到）" : v}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {acc.auxiliary_note === "" ? null : (
          <div class="readings">{acc.auxiliary_note}</div>
        )}
      </Card>

      <Card
        title="与工具面同源（缺口）"
        right={
          <TriState
            tri="not_applicable"
            label="conductor.closing 的第二读数"
            reason="draft/74 说这一栏要比 conductor.closing 的 review_acceptance 子树里同一个键的值，而 AcceptanceView 里没有那一栏"
          />
        }
      >
        <div class="readings">
 "同一件事在两处是否同值"要一条读 conductor_tools.conductor_closing 的端点
          才能给读数 —— 页面不许自己编一个数。
        </div>
      </Card>

      <Card
        title="污染面（缺口）"
        right={
          <TriState
            tri="not_applicable"
            label="pollution"
            reason="draft/74 说这一栏读 closing 的 readings['contradictions']（10 键，含 too_large 那一档），而 AcceptanceView 里没有这一栏"
          />
        }
      >
        <div class="readings">
 命题级 / 断言级分布与 too_large 那一档同样要新增端点才能给读数。
        </div>
      </Card>
    </>
  );
}
