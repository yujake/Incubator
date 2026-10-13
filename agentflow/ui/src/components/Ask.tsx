/*
 * 两处"跟系统说话"的入口（业主 2026-10-13：「整个网页愣是没找到让我给系统说话的地方」+
 * 「肯定要能往正在跑的那一趟里插话」）。
 *
 * - `StartRunCard`：**一句话起一趟**（`POST /api/run`，等价 CLI
 *   `agentflow --root <项目> run-agent M --task "…" --subagents`）；
 * - `InterjectCard`：**往正在跑的那一趟插话**（`POST /api/task`）—— 只有用户能发、只有 M 收，
 *   主控在**下一步开头**读到，当前这一步不被打断。
 *
 * 两条都走写面：需要 `agentflow web --allow-writes`；回执（成了 / 没成 + 原因）原样显示，
 * 不替用户把它读成"成功"。
 */
import { useState } from "preact/hooks";
import { postInterject, postRun, whyOf } from "../api";
import type { WriteOutcome } from "../api";
import { Card } from "./Card";
import { ConfirmButton } from "./ConfirmButton";

function Outcome(props: { got: WriteOutcome | null; problem: string }) {
  if (props.problem !== "") {
    return <div class="readings">{props.problem}</div>;
  }
  if (props.got === null) {
    return null;
  }
  const got = props.got;
  return (
    <div class="readings">
      {got.ok ? "已提交" : "未提交"}（{got.tri}）：{got.reason}
    </div>
  );
}

export function StartRunCard() {
  const [task, setTask] = useState("");
  const [busy, setBusy] = useState(false);
  const [got, setGot] = useState<WriteOutcome | null>(null);
  const [problem, setProblem] = useState("");

  const start = (): void => {
    setBusy(true);
    setGot(null);
    setProblem("");
    postRun({ task })
      .then((out) => {
        setGot(out);
      })
      .catch((exc: unknown) => {
        setProblem(`请求失败：${whyOf(exc)}`);
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <Card title="交给系统一件事" subtitle="一句话即可；怎么排由主控决定">
      <div class="row">
        <input
          class="input"
          type="text"
          placeholder="例如：帮我把工作区里那篇论文从头到尾审核一遍，修改掉里面的错误和不恰当表述。"
          value={task}
          onInput={(ev) => {
            setTask(ev.currentTarget.value);
          }}
        />
        <ConfirmButton
          action="启动"
          impact={`会以这句任务起一趟（当前项目）：${task === "" ? "（还没写）" : task}`}
          onConfirm={start}
          disabled={busy || task.trim() === ""}
          note={
            busy
              ? "正在提交……"
              : task.trim() === ""
                ? "先写一句要它做的事"
                : "会真的起一趟并消耗预算（需要写面开启）"
          }
        />
      </div>
      <Outcome got={got} problem={problem} />
    </Card>
  );
}

export function InterjectCard(props: { sid?: string }) {
  const [body, setBody] = useState("");
  const [subject, setSubject] = useState("");
  const [busy, setBusy] = useState(false);
  const [got, setGot] = useState<WriteOutcome | null>(null);
  const [problem, setProblem] = useState("");

  const send = (): void => {
    setBusy(true);
    setGot(null);
    setProblem("");
    postInterject({ body, subject: subject === "" ? "用户插话" : subject, sid: props.sid })
      .then((out) => {
        setGot(out);
      })
      .catch((exc: unknown) => {
        setProblem(`请求失败：${whyOf(exc)}`);
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <Card title="插话给主控" subtitle="它在下一步开头读到；当前这一步不被打断">
      <div class="row">
        <input
          class="input"
          type="text"
          placeholder="例如：第二节那句「必然成立」改弱一点。"
          value={body}
          onInput={(ev) => {
            setBody(ev.currentTarget.value);
          }}
        />
        <input
          class="input"
          type="text"
          placeholder="标题（可留空）"
          value={subject}
          onInput={(ev) => {
            setSubject(ev.currentTarget.value);
          }}
        />
        <ConfirmButton
          action="送出"
          impact={`会把这句话交给主控（${props.sid === undefined || props.sid === "" ? "当前会话" : props.sid}）`}
          onConfirm={send}
          disabled={busy || body.trim() === ""}
          note={busy ? "正在提交……" : body.trim() === "" ? "先写要说的话" : "写面没开时后端回 403"}
        />
      </div>
      <Outcome got={got} problem={problem} />
    </Card>
  );
}
