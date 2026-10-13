/*
 * 首页 —— 全局待回答面板（`draft/74 §3.1` 逐行落）。
 *
 * 输入：`api.getState()` → `StateSnapshot`（`live` 层已经取了一次，这里读同一份）。
 * SSE：`state` / `question` / `answered`（`live` 层订阅一次，`version` 变了这页重渲染）。
 *
 * 三态纪律在这页上的落点：
 *
 * - 待答清单是全局的（不按会话过滤）—— 顶部那句说明它可能属于别的会话；
 * - 读盘问题（`problems`）非空时显一条横幅：那是"没查成"，不是"没有"；
 * - 空态是"没有待回答的问题"（`pending_questions` 为空**且** `problems` 为空），
 *   与"没查成"分开；
 * - `sessions[].bad_lines > 0` 显红（这一段会话里有读不进来的行）；
 * - 回答的三档结局（落盘 / 409 重复或未知 / 没查成）逐档如实显示，
 *   写面的统一回执（`WriteResult`）今天还没有 ⇒ 那一格记 `not_applicable` 并说明。
 */
import { useState } from "preact/hooks";

import { postAnswer, whyOf } from "../api";
import type { WriteOutcome } from "../api";
import { StartRunCard } from "../components/Ask";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { Table } from "../components/Table";
import { TriState } from "../components/TriState";
import { useLive } from "../live";
import type { PendingQuestion, RunRow, StateSnapshot } from "../types";

/** 这条待答问题正被哪一趟等（`RunRow.waiting_on` 里有它的 qid）。 */
function blockedRun(snapshot: StateSnapshot, q: PendingQuestion): RunRow | null {
  for (const run of snapshot.runs) {
    if (run.sid === q.sid && run.waiting_on.includes(q.qid)) {
      return run;
    }
  }
  return null;
}

function timeText(ts: string): string {
  return ts === "" ? "unknown" : ts;
}

function timeoutText(sec: number | null): string {
  return sec === null ? "一直等（没写超时）" : `${sec} 秒`;
}

function QuestionCard(props: { q: PendingQuestion; snapshot: StateSnapshot; onDone: () => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [custom, setCustom] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<WriteOutcome | null>(null);
  const run = blockedRun(props.snapshot, props.q);

  const toggle = (label: string): void => {
    setSelected((now) =>
      props.q.multi
        ? now.includes(label)
          ? now.filter((x) => x !== label)
          : [...now, label]
        : [label],
    );
  };

  const submit = (): void => {
    setBusy(true);
    setOutcome(null);
    postAnswer({
      qid: props.q.qid,
      sid: props.q.sid,
      selected,
      custom,
    })
      .then((got) => {
        setOutcome(got);
        if (got.ok) {
          props.onDone();
        }
      })
      .catch((exc: unknown) => {
        setOutcome({ ok: false, tri: "unreadable", reason: whyOf(exc) });
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <section class="card" id={`q-${props.q.sid}-${props.q.qid}`}>
      <div class="card-head">
        <span class="caption">会话</span>
        <span class="mono">{props.q.sid}</span>
        <span class="caption">问题号</span>
        <span class="mono">{props.q.qid}</span>
        <Badge kind="badge-pending" text={props.q.multi ? "等回答（多选）" : "等回答"} />
        {run === null ? null : <Badge kind="badge-fail" text="正阻塞一趟" />}
        <span class="readings">
          谁在问 <span class="mono">{props.q.role}</span> · 落档时间{" "}
          <span class="mono">{timeText(props.q.ts)}</span> · 超时{" "}
          <span class="mono">{timeoutText(props.q.timeout_sec)}</span>
        </span>
      </div>
      <div class="question">{props.q.text}</div>
      <div class="opts">
        {props.q.options.map((opt, i) => (
          <label class="opt" key={`${props.q.qid}-${i}`}>
            <input
              type={props.q.multi ? "checkbox" : "radio"}
              name={`pick-${props.q.sid}-${props.q.qid}`}
              checked={selected.includes(opt.label)}
              onChange={() => {
                toggle(opt.label);
              }}
            />
            <span class="label">{opt.label}</span>
            {opt.description === "" ? null : <span class="desc">{opt.description}</span>}
          </label>
        ))}
        {props.q.options.length === 0 ? (
          <span class="empty">这条问题没有给选项（自由作答；「空表」是读到了 0 个选项）。</span>
        ) : null}
      </div>
      <div class="opts">
        <label class="opt">
          <span class="readings">自己写一句（可留空）</span>
          <input
            class="input"
            type="text"
            value={custom}
            onInput={(ev) => {
              setCustom(ev.currentTarget.value);
            }}
          />
        </label>
      </div>
      <div class="card-head">
        <button class="btn" type="button" disabled={busy} onClick={submit}>
          {busy ? "提交中……" : "提交回答"}
        </button>
        {run === null ? null : (
          <span class="readings">
            这一趟 <span class="mono">{run.role}</span> 停在{" "}
            <span class="mono">{run.stop_reason === "" ? "unknown" : run.stop_reason}</span>
          </span>
        )}
      </div>
      {outcome === null ? null : (
        <TriState
          tri={outcome.tri}
          label={outcome.ok ? "这次回答" : "这次回答没落地"}
          reason={outcome.reason}
        />
      )}
    </section>
  );
}

export function Home() {
  const live = useLive();
  const snapshot = live.snapshot;

  if (snapshot === null) {
    return (
      <Card
        title="读数"
        right={<TriState tri="unreadable" reason={live.problem} label="工作区读数" />}
      >
        <span class="readings">正在读盘……（还没读到就是「还没读到」，不是「空工作区」）</span>
      </Card>
    );
  }

  const pending = snapshot.pending_questions;
  const problems = snapshot.problems;
  const unreachable = live.problem !== "";

  return (
    <>
      <StartRunCard />
      {problems.length > 0 ? (
        <Card
          title="没查成"
          tone="problem"
          subtitle={`${problems.length} 条读盘问题（不是「没有」，是「没读到」）`}
        >
          {problems.map((p, i) => (
            <div class="row" key={i}>
              <span class="mono">{p}</span>
            </div>
          ))}
        </Card>
      ) : null}

      <Card
        title="待回答（全局，不按会话过滤）"
        subtitle={`${pending.length} 条 · 快照 ${snapshot.generated_at}`}
        right={unreachable ? <TriState tri="unreadable" reason={live.problem} label="快照" /> : null}
      >
        <div class="readings">这些提问可能属于别的会话 —— 面板一次取全工作区，不按会话过滤。</div>
        {pending.length === 0 ? (
          <span class="empty">没有待回答的问题（合法初态，不是「没查成」）。</span>
        ) : (
          pending.map((q) => (
            <QuestionCard
              q={q}
              snapshot={snapshot}
              key={`${q.sid}-${q.qid}`}
              onDone={live.refresh}
            />
          ))
        )}
      </Card>

      <Card title="会话概览" subtitle={`${snapshot.sessions.length} 段`}>
        {snapshot.sessions.length === 0 ? (
          <span class="empty">盘上一段会话都没有（读到了，里面是 0 段 —— 不是「没查成」）。</span>
        ) : (
          <Table
            rows={snapshot.sessions}
            empty="盘上一段会话都没有。"
            columns={[
              {
                key: "sid",
                title: "会话",
                render: (s) => (
                  <a class="mono" href={`/run/${encodeURIComponent(s.sid)}`}>
                    {s.sid}
                  </a>
                ),
              },
              { key: "events_seen", title: "事件" },
              {
                key: "bad_lines",
                title: "坏行",
                render: (s) =>
                  s.bad_lines > 0 ? (
                    <Badge kind="badge-fail" text={String(s.bad_lines)} />
                  ) : (
                    <span class="mono">0</span>
                  ),
              },
              { key: "pending", title: "待答" },
              { key: "runs", title: "趟数" },
              { key: "orphans", title: "轮次之外" },
              { key: "last_kind", title: "盘上最后一条" },
              { key: "last_ts", title: "最后时间" },
            ]}
          />
        )}
      </Card>

      <Card title="台账（第二个独立读数）">
        <div class="readings">
          台账事件{" "}
          <span class="mono">{snapshot.ledger.events === null ? "unknown" : snapshot.ledger.events}</span>{" "}
          条 · tasks 行数{" "}
          <span class="mono">{snapshot.ledger.tables === null ? "unknown" : snapshot.ledger.tables}</span>{" "}
          · 落点 <span class="mono">{snapshot.ledger.path}</span>
        </div>
        {snapshot.ledger.tables_note === "" ? null : (
          <div class="readings">{snapshot.ledger.tables_note}</div>
        )}
        {snapshot.ledger.note === "" ? null : <div class="readings">{snapshot.ledger.note}</div>}
      </Card>

      <Card title="落点" subtitle="这页读的那一份快照从哪来">
        <div class="readings">
          工作区根 <span class="mono">{snapshot.root}</span> · 生成于{" "}
          <span class="mono">{snapshot.generated_at}</span>
        </div>
      </Card>
    </>
  );
}
