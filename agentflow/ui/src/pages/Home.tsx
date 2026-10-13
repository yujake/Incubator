/*
 * 首页 = 对话（业主 2026-10-13：「用户和主控的对话不应该只做成只能一句话启动任务，
 * 应该是能对话的……要把前端做成对话框」）。
 *
 * 这一页把"跟系统说话"收进**一个输入框**，按当刻状态自动选路，并把"这一下会做什么"
 * 写在按钮旁边（四处，逐条对应一条真端点）：
 *
 * | 当刻状态 | 这一句话会走到哪 |
 * |---|---|
 * | 有提问在等回答 | `POST /answer`（qid + 这一句当自由回答） |
 * | 这一段的 M 在飞 | `POST /api/task` 插话（下一步开头读到，不打断当前步） |
 * | M 闲着、这一段有原来的任务 | 先 `POST /api/task` 记进收件箱，再 `POST /api/run` 带 `sid` + `resume` 唤醒它 |
 * | 还没有会话（或选了"新的一段"） | `POST /api/run` 起一趟 |
 *
 * 来回那一段由后端 `GET /api/chat` 逐条给（投影口径见 `readers.chat_face` 的 docstring）：
 * 用户的线与主控的线分列，团队动态（别的角色在频道里说的话）默认折起来、可展开。
 *
 * 三态纪律：这一页不把"没查成"画成"没有" —— 会话面读不出来显 `TriState` + 理由；
 * 没有会话显"还没有会话（合法初态）"；提问在等回答时显它阻塞了哪一趟。
 *
 * 为什么续跑要带**原来那句话**：`agent_loop.resume_messages` 按"role 相同 + task 原文
 * 相同 + 是全新开始"挑重建窗口，换了任务就是另一趟（`--resume` 会以指纹不符拒掉）。
 * 收件箱那一段是**现读**的，所以刚说出口的那句话正好落在 M 醒来的第一步里。
 */
import { useState } from "preact/hooks";

import { api, postAnswer, postInterject, postRun, whyOf } from "../api";
import type { WriteOutcome } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConfirmButton } from "../components/ConfirmButton";
import { Table } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace, useLive } from "../live";
import type { ChatLine, PendingQuestion, RunRow, StateSnapshot } from "../types";

/** 这条待答问题正被哪一趟等（`RunRow.waiting_on` 里有它的 qid）。 */
function blockedRun(snapshot: StateSnapshot, q: PendingQuestion): RunRow | null {
  for (const run of snapshot.runs) {
    if (run.sid === q.sid && run.waiting_on.includes(q.qid)) {
      return run;
    }
  }
  return null;
}

/** 一条对话线（`谁来的一行 + 正文`）。 */
function Line(props: { line: ChatLine }) {
  const l = props.line;
  const who = l.who === "user" ? "你" : l.who === "conductor" ? "主控" : "团队";
  const cls = l.who === "user" ? "chat-user" : l.who === "conductor" ? "chat-m" : "chat-team";
  return (
    <div class={`chat-line ${cls}`}>
      <div class="readings">
        <b>{who}</b>
        <span class="tri-reason"> {l.title}</span>
        {" "}
        <span class="mono tri-reason">{l.ts}</span>
        {l.clipped ? <span class="tri-reason">（正文截断过）</span> : null}
      </div>
      <div class="chat-body">{l.text === "" ? "（这一条没有正文）" : l.text}</div>
      {l.options === undefined || l.options.length === 0 ? null : (
        <div class="opts">
          {l.options.map((o, i) => (
            <span class="opt" key={`${l.index}-${i}`}>
              <span class="mono">{o.label}</span>
              {o.description === "" ? null : <span class="desc">{o.description}</span>}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** 一条待答问题（全局面板上的一格）。
 *
 * 锚点带**会话号 + 问题号**两样：`qid` 只在会话内唯一（`sessions` 每段各自从 q0001
 * 起编），只按 qid 定位会撞；判据 `test_pending_list_is_never_filtered_by_session`
 * 钉着这一条。回答也一律带**这一条自己的** `sid`（不许拿当前选中的会话去顶）。
 */
function PendingBlock(props: {
  q: PendingQuestion;
  snapshot: StateSnapshot;
  busy: boolean;
  onAnswer: (q: PendingQuestion, selected: string[]) => void;
}) {
  const run = blockedRun(props.snapshot, props.q);
  return (
    <div class="chat-line" id={`q-${props.q.sid}-${props.q.qid}`}>
      <div class="readings">
        <b>主控在问</b> 会话 <span class="mono">{props.q.sid}</span> · 问题号{" "}
        <span class="mono">{props.q.qid}</span> · 谁问的 <span class="mono">{props.q.role}</span>
        {run === null ? null : <Badge kind="badge-fail" text="正阻塞一趟" />}
      </div>
      <div class="chat-body">{props.q.text}</div>
      {props.q.options.length === 0 ? (
        <div class="readings tri-reason">
          这条问题没有给选项（自由作答；「空表」是读到了 0 个选项）—— 用下面那个框回。
        </div>
      ) : (
        <div class="opts">
          {props.q.options.map((opt, i) => (
            <button
              class="btn"
              type="button"
              key={`${props.q.qid}-${i}`}
              disabled={props.busy}
              onClick={() => {
                props.onAnswer(props.q, [opt.label]);
              }}
            >
              {opt.label}
              {opt.description === "" ? "" : `（${opt.description}）`}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Home() {
  const live = useLive();
  const snapshot = live.snapshot;
  const [target, setTarget] = useState("");
  const [text, setText] = useState("");
  const [team, setTeam] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<WriteOutcome | null>(null);
  const [result, setResult] = useState("");
  const chat = useFace(() => api.getChat(target));
  const liveFace = useFace(() => api.getLive());

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

  const chatData = chat.data;
  const allLines = chatData === null ? [] : chatData.lines;
  const sid = chatData === null ? "" : chatData.sid;
  const lines = team ? allLines : allLines.filter((l) => l.who !== "team");
  const folded = allLines.length - lines.length;
  const sessions = chatData === null ? [] : chatData.sessions;
  // 待答问题是**全局**的（不按当前选中的会话过滤）：别的会话在等人回答也是事实，
  // 而且 qid 只在会话内唯一 —— 所以每一条各自带着自己的 sid 提交（判据同族）。
  const pending = snapshot.pending_questions;
  const firstQ = pending[0];
  const running = (liveFace.data === null ? [] : liveFace.data.running).some(
    (r) => r.sid === sid,
  );
  // 续跑要用**这一段原来那句话**（见文件头那张表下面那段）：先看台账那一栏，
  // 再退回对话里第一条属于用户的线。
  const topRun = snapshot.runs.find((r) => r.sid === sid && r.role === "M");
  const originalTask =
    topRun !== undefined && topRun.task !== ""
      ? topRun.task
      : (allLines.find((l) => l.kind === "agent_run_start" && l.who === "user")?.text ?? "");
  const newSession = target === "__new__";
  const mode =
    pending.length > 0 ? "answer"
      : newSession || sid === "" ? "start"
        : running ? "interject"
          : originalTask === "" ? "start" : "wake";

  const MODE_WORDS: Record<string, string> = {
    answer: `会把这句当回答提交给 ${firstQ === undefined ? "" : `${firstQ.sid}/${firstQ.qid}`}（走 /answer 那条写路径）`,
    interject: "会插话给正在跑的这一趟（下一步开头读到，不打断当前这一步）",
    wake: "先把这句话记进主控的收件箱，再用原来那句话唤醒这一段（续跑）—— 会花预算",
    start: newSession
      ? "会新起一趟（新的一段会话）—— 会花预算"
      : "还没有会话（或读不到原来的任务）⇒ 这一句会起一趟 —— 会花预算",
  };

  const done = (msg: string): void => {
    setResult(msg);
    setOutcome(null);
    live.refresh();
    chat.reload();
    liveFace.reload();
  };

  const send = (): void => {
    const body = text.trim();
    if (body === "") {
      return;
    }
    setBusy(true);
    setResult("");
    setOutcome(null);
    const fail = (exc: unknown): void => {
      setResult(`没成：${whyOf(exc)}`);
    };
    if (mode === "answer") {
      if (firstQ === undefined) {
        setBusy(false);
        return;
      }
      postAnswer({ qid: firstQ.qid, sid: firstQ.sid, custom: body, selected: [] })
        .then((got) => {
          setOutcome(got);
          done(`${got.ok ? "已提交" : "没提交"}（tri=${got.tri}）：${got.reason}`);
        })
        .catch(fail)
        .finally(() => {
          setBusy(false);
        });
      return;
    }
    if (mode === "interject") {
      postInterject({ body, sid })
        .then((got) => done(`${got.ok ? "已插话" : "没插上"}（tri=${got.tri}）：${got.reason}`))
        .catch(fail)
        .finally(() => {
          setBusy(false);
        });
      return;
    }
    if (mode === "wake") {
      postInterject({ body, sid })
        .then(() =>
          postRun({
            task: originalTask,
            sid,
            resume: true,
          }),
        )
        .then((got) =>
          done(`${got.ok ? "已唤醒这一段" : "没唤醒"}（tri=${got.tri}）：${got.reason}`),
        )
        .catch(fail)
        .finally(() => {
          setBusy(false);
        });
      return;
    }
    postRun({ task: body })
      .then((got) => done(`${got.ok ? "已起一趟" : "没起来"}（tri=${got.tri}）：${got.reason}`))
      .catch(fail)
      .finally(() => {
        setBusy(false);
      });
  };

  /** 点选项 = 用**这一条问题自己的** sid/qid 提交 `selected`。 */
  const answerOption = (q: PendingQuestion, selected: string[]): void => {
    setBusy(true);
    setResult("");
    postAnswer({ qid: q.qid, sid: q.sid, selected, custom: "" })
      .then((got) => {
        setOutcome(got);
        done(`${got.ok ? "已提交" : "没提交"}（tri=${got.tri}）：${got.reason}`);
      })
      .catch((exc: unknown) => {
        setResult(`没成：${whyOf(exc)}`);
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <>
      <Card
        title="对话"
        subtitle={
          chatData === null
            ? ""
            : `${sid === "" ? "还没有会话" : sid} · 共 ${chatData.total} 条来回` +
              (running ? " · 主控在飞" : "")
        }
        tone={chatData !== null && isUnreadable(chatData.tri) ? "problem" : "plain"}
        right={
          chatData === null ? (
            chat.problem === "" ? null : (
              <TriState tri="unreadable" reason={chat.problem} label="对话面" />
            )
          ) : (
            <TriState tri={chatData.tri} label="对话面" reason={chatData.reason} />
          )
        }
      >
        <div class="readings">
          <label class="opt">
            <span>会话</span>
            <select
              value={newSession ? "__new__" : sid}
              onChange={(ev) => {
                setTarget(ev.currentTarget.value);
                chat.reload();
              }}
            >
              {sessions.map((s) => (
                <option value={s.sid} key={s.sid}>
                  {s.sid}（{s.events} 条事件 · {s.last_ts}）
                </option>
              ))}
              <option value="__new__">新的一段（起一趟）</option>
            </select>
          </label>
          <label class="opt">
            <input
              type="checkbox"
              checked={team}
              onChange={(ev) => {
                setTeam(ev.currentTarget.checked);
              }}
            />
            <span class="readings">
              连团队动态一起看{folded > 0 ? `（现在折着 ${folded} 条）` : ""}
            </span>
          </label>
        </div>
        {chatData !== null && chatData.reason !== "" ? (
          <div class="readings">{chatData.reason}</div>
        ) : null}
        {lines.length === 0 ? (
          <span class="empty">
            还没有会话（合法初态）—— 在下面写一句话就能起一趟；主控的问与答都会出现在这里。
          </span>
        ) : (
          lines.map((l) => <Line line={l} key={`${l.index}-${l.kind}`} />)
        )}
      </Card>

      <Card
        title="说一句"
        subtitle={`M ${running ? "在飞" : "闲着"} · ${pending.length} 条待回答`}
      >
        {pending.length === 0 ? (
          <span class="empty">暂无待回答的问题（合法初态）。</span>
        ) : (
          pending.map((q) => (
            <PendingBlock
              q={q}
              snapshot={snapshot}
              busy={busy}
              key={`${q.sid}-${q.qid}`}
              onAnswer={answerOption}
            />
          ))
        )}
        <div class="row">
          <input
            class="input"
            type="text"
            placeholder={
              mode === "answer"
                ? "回答主控的问题（也可以直接点上面的选项）"
                : mode === "interject"
                  ? "插一句话给正在跑的那一趟"
                  : mode === "wake"
                    ? "接着说（会把这句话交给闲着的主控，让它接着干）"
                    : "例如：帮我把工作区里那篇论文从头到尾审核一遍，修改掉里面的错误和不恰当表述。"
            }
            value={text}
            onInput={(ev) => {
              setText(ev.currentTarget.value);
            }}
          />
          {/* 会花钱的两条（起一趟 / 续跑）走两次确认；回答与插话不花钱，一下即可。 */}
          {mode === "wake" || mode === "start" ? (
            <ConfirmButton
              action="送出"
              impact={MODE_WORDS[mode] ?? ""}
              onConfirm={send}
              disabled={busy || text.trim() === ""}
              note={
                busy
                  ? "正在提交……"
                  : text.trim() === ""
                    ? "先写一句要说的话"
                    : "写面没开（agentflow web --allow-writes）时后端回 403"
              }
            />
          ) : (
            <button
              class="btn"
              type="button"
              disabled={busy || text.trim() === ""}
              onClick={send}
            >
              {busy ? "提交中……" : mode === "answer" ? "提交回答" : "送出"}
            </button>
          )}
        </div>
        <div class="readings">{MODE_WORDS[mode]}</div>
        {result === "" ? null : <div class="readings">{result}</div>}
        {outcome === null ? null : (
          <TriState
            tri={outcome.tri}
            label={outcome.ok ? "这一句话" : "这一句话没落地"}
            reason={outcome.reason}
          />
        )}
      </Card>

      {snapshot.problems.length > 0 ? (
        <Card
          title="没查成"
          tone="problem"
          subtitle={`${snapshot.problems.length} 条读盘问题（不是「没有」，是「没读到」）`}
        >
          {snapshot.problems.map((p, i) => (
            <div class="row" key={i}>
              <span class="mono">{p}</span>
            </div>
          ))}
        </Card>
      ) : null}

      <Card title="会话概览" subtitle={`${snapshot.sessions.length} 段`}>
        {snapshot.sessions.length === 0 ? (
          <span class="empty">暂无会话（读到了，里面是 0 段）。</span>
        ) : (
          <Table
            rows={snapshot.sessions}
            empty="暂无会话。"
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

      <Card title="台账">
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

      <Card title="落点">
        <div class="readings">
          工作区根 <span class="mono">{snapshot.root}</span> · 生成于{" "}
          <span class="mono">{snapshot.generated_at}</span>
        </div>
      </Card>
    </>
  );
}
