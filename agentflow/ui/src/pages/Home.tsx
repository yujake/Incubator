/*
 * 首页（W0 里唯一接了真数据的那一页）。
 *
 * 输入：`api.getState()` → `StateSnapshot`。三态纪律在这页上的落点：
 *
 * - 待答清单是**全局**的（不按会话过滤）：`snapshot.pending_questions` 逐条列出
 *   qid / 会话号 / 谁在问 / 正文 / 每个选项的 label 与 description；
 * - 读盘问题（`problems`）非空时显一条横幅 —— 那是"没查成"，不是"没有"；
 * - 空态是"没有待回答的问题"（`pending_questions` 为空且 `problems` 为空），
 *   与"没查成"分开；
 * - `sessions[].bad_lines > 0` 显红（这一段会话里有读不进来的行）。
 */
import { useEffect, useState } from "preact/hooks";

import { api, ApiError } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { TriState } from "../components/TriState";
import type { StateSnapshot } from "../types";

export function Home() {
  const [snapshot, setSnapshot] = useState<StateSnapshot | null>(null);
  const [problem, setProblem] = useState<string>("");

  useEffect(() => {
    let alive = true;
    api
      .getState()
      .then((got) => {
        if (alive) {
          setSnapshot(got);
        }
      })
      .catch((exc: unknown) => {
        if (alive) {
          const why = exc instanceof ApiError ? exc.reason : String(exc);
          setProblem(`读数没拿到：${why}`);
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  if (problem !== "") {
    return (
      <Card title="读数">
        <TriState tri="unreadable" reason={problem} label="工作区读数" />
      </Card>
    );
  }

  if (snapshot === null) {
    return (
      <Card title="读数">
        <span class="readings">正在读盘……</span>
      </Card>
    );
  }

  const pending = snapshot.pending_questions;
  const problems = snapshot.problems;

  return (
    <>
      {problems.length > 0 ? (
        <Card title="没查成" subtitle={`${problems.length} 条读盘问题（不是「没有」，是「没读到」）`}>
          {problems.map((p, i) => (
            <div class="row" key={i}>
              <span class="mono">{p}</span>
            </div>
          ))}
        </Card>
      ) : null}

      <Card title="待回答（全局，不按会话过滤）" subtitle={`${pending.length} 条`}>
        {pending.length === 0 ? (
          <span class="empty">没有待回答的问题（合法初态，不是「没查成」）。</span>
        ) : (
          pending.map((q) => (
            <section class="card" id={`q-${q.sid}-${q.qid}`} key={`${q.sid}-${q.qid}`}>
              <div class="card-head">
                <span class="caption">会话</span>
                <span class="mono">{q.sid}</span>
                <span class="caption">问题号</span>
                <span class="mono">{q.qid}</span>
                <Badge kind="badge-pending" text="等回答" />
                <span class="readings">
                  谁在问 <span class="mono">{q.role}</span> · 落档时间{" "}
                  <span class="mono">{q.ts === "" ? "unknown" : q.ts}</span>
                </span>
              </div>
              <div class="question">{q.text}</div>
              <div class="opts">
                {q.options.map((opt, i) => (
                  <div class="opt" key={i}>
                    <span class="label">{opt.label}</span>
                    {opt.description === "" ? null : <span class="desc">{opt.description}</span>}
                  </div>
                ))}
              </div>
            </section>
          ))
        )}
      </Card>

      <Card title="会话概览" subtitle={`${snapshot.sessions.length} 段`}>
        {snapshot.sessions.length === 0 ? (
          <span class="empty">盘上一段会话都没有。</span>
        ) : (
          <table class="grid">
            <thead>
              <tr>
                <th>会话</th>
                <th>事件</th>
                <th>坏行</th>
                <th>待答</th>
                <th>趟数</th>
                <th>轮次之外</th>
                <th>盘上最后一条</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.sessions.map((s) => (
                <tr key={s.sid}>
                  <td>
                    <a class="mono" href={`/run/${encodeURIComponent(s.sid)}`}>
                      {s.sid}
                    </a>
                  </td>
                  <td class="mono">{s.events_seen}</td>
                  <td class="mono">
                    {s.bad_lines > 0 ? <Badge kind="badge-fail" text={String(s.bad_lines)} /> : "0"}
                  </td>
                  <td class="mono">{s.pending}</td>
                  <td class="mono">{s.runs}</td>
                  <td class="mono">{s.orphans}</td>
                  <td class="mono">{s.last_kind}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="台账（第二个独立读数）">
        <div class="readings">
          台账事件 <span class="mono">{snapshot.ledger.events === null ? "unknown" : snapshot.ledger.events}</span> 条 ·
          落点 <span class="mono">{snapshot.ledger.path}</span>
          {snapshot.ledger.note === "" ? null : <span> · {snapshot.ledger.note}</span>}
        </div>
      </Card>
    </>
  );
}
