/*
 * 名册（roster）面板：当前工作区**整棵名册树**，一个 agent 一个节点。
 *
 * ## 它读的那一条端点
 * `GET /api/roster`（`readers.roster_face`）—— 父是谁、子有哪些、每个成员的绝对编号
 * （`task_id`）/ 名册名 / 角色 / 深度，外加收件箱那三格（未读 / 已读未 ack / 未消总数）。
 * 数据源是盘上的 `out/roster/<父编号>.jsonl`（秘书写的 append-only 名册）、
 * `out/roster/<父编号>-index.jsonl`（对照表：复用过的名字此刻的编号）与 `data/tasks.json`
 * （状态与板项）。**只读**：这个端点在路由表里只有一条 GET，面板上也就没有写操作。
 *
 * ## 为什么是一个面板而不是第十页
 * 这张树的消费者是**运行态监控**：人在「在飞」页问"现在到底有谁在跑、谁是谁的子"。
 * 做成单独一页等于让人在两个页面之间来回对号；而且新开一条客户端路由要动 C4 契约表
 * （`draft/75 §1.4`），而"监控面"本来就在「在飞」页。所以它落在这里，与那一页的
 * 「在飞」「停机」「用量」几张卡片并排 —— 同一份读数，一处实现。
 *
 * ## 三态纪律（这一块最要紧的一条）
 * `answer === "unknown"` 是「**名册没读到**」（目录不在 / 读不出来 / 有一条读不出来），
 * **不是**「这个工作区没有子代理」。所以那一档：
 *   - 不许画成"子代理：0"（后端给的是 `count: null`，不是 0）；
 *   - 必须把 `reason` 原样摆出来（后端逐档写清了是哪一档）；
 *   - 节点列表为空时也只能说"没读到"，不许说"没有"。
 * 反过来，`answer === "ok"` 而 `nodes` 是空数组才算"读到了、里面是 0 个"（合法空态）。
 */
import { useState } from "preact/hooks";

import { api } from "../api";
import { useFace } from "../live";
import type { RosterChild, RosterInbox, RosterNode, RosterView } from "../types";
import { Badge } from "./Badge";
import { Card } from "./Card";
import { TriState, isUnreadable } from "./TriState";
import { cell } from "./Table";

/** 一层缩进（`depth` 只决定左缩进，不做别的 —— 树是后端按前序排好的）。 */
function indentOf(depth: number): string {
  return `calc(${Math.max(0, depth - 1)} * var(--sp-4))`;
}

/** 名册名那几档的空值（根不在任何人的名册里；名字一经退役永久不复用）。 */
function nameText(node: RosterNode): string {
  return node.name === "" ? "（顶层·无名册名）" : node.name;
}

/** 子那几格：绝对编号 + 名册名（读不到名册名就只给编号）。 */
function childText(children: RosterChild[]): string {
  if (children.length === 0) {
    return "（这个父名下没有子）";
  }
  return children
    .map((c) => `${c.name === "" ? "（无名）" : c.name}(${c.task_id})`)
    .join("、");
}

/** 收件箱那一格：读不到就是"未读到"（不是 0 条）。
 *
 * 三格分开（D13）：`unread` = 还没被读进任何一步（queued/claimed）；
 * `seen_not_acked` = 读了、还缺 ack。改前只有一个数，而它把 `seen` 也算成"积压"——
 * 那个数因此在正常流程下只涨不落（`close_item` 全仓只有一个调用者）。
 */
function inboxBadge(inbox: RosterInbox) {
  if (inbox.tri !== "computed" || inbox.open_total === null) {
    return <Badge kind="badge-unknown" text="收件箱：未读到" />;
  }
  if (inbox.open_total === 0) {
    return <Badge kind="badge-pass" text="收件箱：没有未消的条目" />;
  }
  const unread = inbox.unread ?? 0;
  const seen = inbox.seen_not_acked ?? 0;
  return (
    <Badge
      kind={unread > 0 ? "badge-fail" : "badge-pending"}
      text={`未读 ${unread} · 已读未 ack ${seen}`}
    />
  );
}

/** 收件箱明细（点开节点之后那一块）。 */
function InboxBlock(props: { inbox: RosterInbox }) {
  const inbox = props.inbox;
  if (inbox.tri !== "computed") {
    return (
      <div class="row">
        收件箱：
        <TriState
          tri={inbox.tri}
          label="收件箱"
          reason={inbox.reason === "" ? "这一格没有读数" : inbox.reason}
        />
        <span class="readings">
          （不是"没有消息"—— 这一格没读成）
        </span>
      </div>
    );
  }
  if (inbox.items.length === 0) {
    return <div class="row">收件箱：读到了，没有未消的条目（0 条）。</div>;
  }
  return (
    <>
      <div class="row">
        收件箱：未读 {inbox.unread === null ? "未读到" : inbox.unread} · 已读未 ack{" "}
        {inbox.seen_not_acked === null ? "未读到" : inbox.seen_not_acked} · 未消{" "}
        {inbox.open_total === null ? "未读到" : inbox.open_total}
        {(inbox.other ?? 0) > 0 ? `（其中状态读不出来 ${inbox.other} 条）` : ""}
        <span class="readings">
          按状态 {dictText(inbox.by_state)} · 按种类 {dictText(inbox.by_kind)}
          {inbox.more > 0 ? ` · 只列前 ${inbox.items.length} 条，还有 ${inbox.more} 条` : ""}
        </span>
      </div>
      {inbox.items.map((it) => (
        <div class="row roster-inbox-item" key={it.task_id}>
          <Badge kind={it.kind === "notice" ? "badge-na" : "badge-pending"} text={it.kind === "" ? "unknown" : it.kind} />
          <span class="mono">{it.task_id}</span>
          <span class="readings">
            状态 {it.state === "" ? "unknown" : it.state} · 谁发的 {it.called_by === "" ? "unknown" : it.called_by}
          </span>
          <span class="roster-brief">{it.detail === "" ? "（正文没读到）" : it.detail}</span>
        </div>
      ))}
    </>
  );
}

/** 一个计数字典（`{queued: 2}` = `queued 2`）；空字典说"没有。`"。 */
function dictText(rec: Record<string, number>): string {
  const keys = Object.keys(rec).sort();
  if (keys.length === 0) {
    return "（没有）";
  }
  return keys.map((k) => `${k === "" ? "unknown" : k} ${rec[k] ?? 0}`).join(" / ");
}

/** 一个节点的明细（点开之后那一块；全部是读数，没有写操作）。 */
function NodeDetail(props: { node: RosterNode }) {
  const n = props.node;
  const parent =
    n.parent_task_id === ""
      ? "（没有父：这一棵树的根）"
      : `${n.parent_task_id}${n.parent_name === "" ? "（父不在任何名册里，没有名册名）" : `（名册名 ${n.parent_name}）`}`;
  return (
    <div class="roster-detail">
      <div class="row">
        父：<span class="mono">{parent}</span> · 深度 <span class="mono">{n.depth}</span> ·
        角色 <span class="mono">{n.role === "" ? "unknown" : n.role}</span> · 绝对编号{" "}
        <span class="mono">{n.task_id === "" ? "unknown" : n.task_id}</span>
      </div>
      <div class="row">
        名册名：<span class="roster-name">{nameText(n)}</span>
        <span class="readings">
          简介 {n.brief === "" ? "（这一行没写简介）" : n.brief} · 简介来源{" "}
          {n.brief_source === "" ? "unknown（改前落的行）" : n.brief_source}
        </span>
      </div>
      <div class="row">
        子（{n.children.length}）：
        <span class="roster-children">{childText(n.children)}</span>
      </div>
      <div class="row">
        台账那一行：{n.task_found ? "在" : "不在（tasks 里没有它这一行）"} ·
        状态 <span class="mono">{n.status === "" ? "unknown" : n.status}</span> · 在飞{" "}
        <span class="mono">
          {n.in_flight === null ? "未读到" : n.in_flight > 0 ? "是" : "否"}
        </span>{" "}
        · 槽位面 <span class="mono">{n.surface === "" ? "（没有分到槽位）" : n.surface}</span>
      </div>
      <InboxBlock inbox={n.inbox} />
    </div>
  );
}

/** 一行节点：左缩进 = 深度，点一下展开它自己的明细。 */
function NodeRow(props: { node: RosterNode; open: boolean; onPick: () => void }) {
  const n = props.node;
  return (
    <div class="roster-node" style={{ paddingLeft: indentOf(n.depth) }}>
      <button
        type="button"
        class="roster-pick"
        aria-expanded={props.open}
        onClick={props.onPick}
      >
        <span class="mono">d{n.depth}</span>
        <span class="roster-name">{nameText(n)}</span>
        <Badge kind="badge-unknown" text={n.role === "" ? "unknown" : n.role} />
        <span class="mono">{n.task_id === "" ? "unknown" : n.task_id}</span>
        <span class="readings">子 {n.children.length}</span>
        {n.retired ? <Badge kind="badge-na" text="已退役" /> : null}
        {n.in_flight === null ? (
          <Badge kind="badge-unknown" text="在飞：未读到" />
        ) : n.in_flight > 0 ? (
          <Badge kind="badge-pending" text="在飞" />
        ) : null}
        {inboxBadge(n.inbox)}
      </button>
      {props.open ? <NodeDetail node={n} /> : null}
    </div>
  );
}

/**
 * 名册面板（「在飞」页里的那一张卡）。
 *
 * 取数走 `useFace`：挂载时读一次，流里来过事件（`live.version` 变了）再读一次 ——
 * 与这一页其余几张卡同一个节拍，不另造一套定时器。
 */
export function RosterPanel() {
  const face = useFace(() => api.getRoster());
  const [picked, setPicked] = useState<string>("");
  const data: RosterView | null = face.data;
  const subtitle =
    data === null
      ? ""
      : `节点 ${cell(data.count)} 个 · 最深 ${cell(data.max_depth)} 层 · 读到的名册/对照表文件 ${data.files.length} 份`;
  return (
    <Card
      title="名册（roster）"
      subtitle={subtitle}
      tone={data !== null && isUnreadable(data.tri) ? "problem" : "plain"}
      right={
        data === null ? (
          face.problem === "" ? null : (
            <TriState tri="unreadable" reason={face.problem} label="名册" />
          )
        ) : (
          <TriState tri={data.tri} label="名册" reason={data.reason} />
        )
      }
    >
      {data === null ? (
        <span class="readings">{face.problem === "" ? "正在读盘……" : face.problem}</span>
      ) : (
        <>
          <div class="readings">
            落点 <span class="mono">{data.dir}</span>（一份 &lt;父编号&gt;.jsonl = 一个父
            名下的子；折叠口径与秘书那一侧同一处实现）。
          </div>
          {data.answer !== "ok" ? (
            <div class="readings roster-unread">
              <Badge kind="badge-unknown" text={`answer=${data.answer}`} />
              <b> 名册没读到</b>：
              {data.reason === "" ? "端点没有给理由" : data.reason}
              {" "}—— 这一档是「这份读数没拿到」，而不是「这个工作区没有子代理」
              （后端给的计数栏是 null，不是 0）。
            </div>
          ) : null}
          {data.nodes.length === 0 ? (
            <div class="empty">
              {data.answer === "ok"
                ? "读到了名册，但里面一个节点都没有（合法空态：读到了、里面是 0 个）。"
                : "节点列表是空的 —— 与上面那句「名册没读到」一起读，不许当成「没有子代理」。"}
            </div>
          ) : (
            <div class="roster-tree">
              {data.nodes.map((n) => (
                <NodeRow
                  key={n.task_id}
                  node={n}
                  open={picked === n.task_id}
                  onPick={() => setPicked(picked === n.task_id ? "" : n.task_id)}
                />
              ))}
            </div>
          )}
          {data.truncated ? (
            <div class="readings">
              这一棵树超过后端的规模上限 ⇒ 只画了一部分（`truncated=true`）。
            </div>
          ) : null}
          {data.coverage.roster_nodes === null ? null : (
            <div class="readings">
              对账：台账里 {cell(data.coverage.tasks_agents)} 个代理行 · 名册上{" "}
              {cell(data.coverage.roster_nodes)} 个节点 · 其中{" "}
              {cell(data.coverage.unrostered)} 个「有父的代理行」不在任何名册里
              （名册机制上线之前落的行）。
            </div>
          )}
          {data.diagnostics.length === 0 ? null : (
            <div class="readings">
              逐条诊断：
              {data.diagnostics.map((d) => (
                <span class="roster-diag" key={d}>
                  {" "}
                  {d}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  );
}
