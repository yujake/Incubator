/*
 * 名册（roster）面板：当前工作区整棵名册树，按父子关系展开。
 *
 * ## 它读的那一条端点
 * `GET /api/roster`（`readers.roster_face`）给了两份形状：
 * - `children_of`：`{父的绝对编号: [直接子的绝对编号...]}`，子按落盘行序 —— 页面照它
 *   递归，于是每一条分支都是"父 → 它的直接子"；
 * - `nodes`：每个节点的读数（层号 `depth`、名册名、角色、绝对编号、子数、状态、
 *   收件箱那三格）。数据源是盘上的 `out/roster/<父编号>.jsonl`（秘书写的
 *   append-only 名册）、`out/roster/<父编号>-index.jsonl`（对照表：复用过的名字
 *   此刻的编号）与 `data/tasks.json`（状态与板项）。只读：这个端点在路由表里只有
 *   一条 GET，面板上也就没有写操作。
 *
 * ## 为什么是树而不是"按层平铺"（业主 2026-10-24 的原话）
 * 「名册按树展开，不只是简单按层展开。」改前页面拿 `nodes` 的顺序 + `depth` 缩进
 * 直接平铺，画出来是 d1 / d2 d2 d2 / d3 ... / d4 ...：同一个名册名（F1 / B1 / V1）
 * 在两层各出现一次，而它们分属不同的父 —— 读的人看不出"谁是谁的子"。现在一条分支
 * 从父开始，子缩进在父下面并用连接线连起来；同一父的多个子按落盘行序排（不是按
 * 名册名重排）。
 *
 * ## 一个节点是一个子代理，它下面挂"管过的任务号"（业主 2026-10-24）
 * 「一个子代理可接收多个任务」「一个子代理后面可展开它管的任务号」。所以树里两层：
 * 1. 代理这一层（父子关系，`children_of`）—— 一个节点是一个常驻子代理（G1 / D1 / F1…）；
 * 2. 任务这一层（`nodes[].tasks[]`）—— 点开节点行尾那个「活 N」才列，一行一件活
 *    （编号 + 起止时间 + 状态 + 一句话）。任务号不是树的节点：把它们摆进树里会造出
 *    d1 上多出来的根，那正是 D-66 那个故障的形态（`t-000039` / `t-000068` 被抬到 d1）。
 *
 * ## 折叠（默认展开到第 2 层）
 * 树大起来一次铺开会把页面淹掉。所以默认只展开到第 2 层：第 1、2 层的节点展开，
 * 第 3 层的节点默认折叠（它们的子树要点一下才出来）。展开态在本次浏览内保持 ——
 * 藏在下面那个模块级的 `openOverride` 里，不在组件 state 里，因为这一页每来一条
 * 流事件就重取一次读数，挂在组件 state 上会被重置。它刻意不写 localStorage：
 * 刷新浏览器就是一次新的浏览。
 *
 * ## 为什么是一个面板而不是第十页
 * 这张树的消费者是运行态监控：人在「在飞」页问"现在到底有谁在跑、谁是谁的子"。
 * 做成单独一页等于让人在两个页面之间来回对号；而且新开一条客户端路由要动 C4 契约表
 * （`draft/75 §1.4`），而"监控面"本来就在「在飞」页。所以它落在这里，与那一页的
 * 「在飞」「停机」「用量」几张卡片并排 —— 同一份读数，一处实现。
 *
 * ## 已销号（退役）的节点怎么画（D-59，业主 2026-10-26 的两句口径）
 * 「对已销号的，名册 ui 显示默认折叠，只有用户再点击展开再显示」「已销号子代理为画删除线的
 * 格式并不再显示收件箱情况」。所以销号节点：
 *   - **仍然在树上、仍然有自己的那一行**（不能消失：消失就看不出"曾经有过、后来销了"）；
 *   - 名字画删除线（`.roster-retired`，token 走 `app.css`，不写字面色值）；
 *   - 行尾挂一个「已销号」标识，并把 `retired_branch`（退役时读到的那一支）写进明细；
 *   - **不显示收件箱那三格**（未读 / 已读未 ack / 未消）：销号即退场，收件箱读数对它没有
 *     意义 —— 它还挂在板上只说明有人往一个已经退场的名字上投过东西；
 *   - **默认折叠**（`isOpen`：已销号一律先折上，覆盖"默认展开到第 2 层"那条层数规则；
 *     用户点过就照用户点的，展开态住在 `openOverride` 里，重取读数不会把它吃掉）。
 *
 * ## 三态纪律（这一块最要紧的一条）
 * `answer === "unknown"` 是「名册没读到」（目录不在 / 读不出来 / 有一条读不出来），
 * 不是「这个工作区没有子代理」。所以那一档：
 *   - 不许画成"子代理：0"（后端给的是 `count: null`，不是 0）；
 *   - 必须把 `reason` 原样摆出来（后端逐档写清了是哪一档）；
 *   - 节点列表为空时也只能说"没读到"，不许说"没有"。
 * 反过来，`answer === "ok"` 而 `nodes` 是空数组才算"读到了、里面是 0 个"（合法空态）。
 *
 * ## 每个代理那一格三态（在飞 / 待机 / 静默 / 未读到）
 * 业主 2026-10-26：「『在飞』的读数要随着时钟式待机进行适配，分三种：1.在工作叫
 * 『在飞』，2.在等待（计时器）为『待机』，3.已收工，无任务，无计时器，叫『静默』。
 * 更新『活跃子代理』的定义为非静默子代理。」所以这一页有三处跟着变：
 *   - 每一行一个三态徽标（`stateBadge`，文案取 `rosterTree.STATE_TEXT`，悬停给
 *     `state_reason` —— 待机与静默的差别就在那句理由里）；
 *   - 行尾「▸ 活 N（飞 a · 待 b）」：N = 名下**非静默**的直接子数，不是
 *     `children.length`（那个数把早就收工的也算进来）；
 *   - 顶部合计「在飞 a · 待机 b · 静默 c」，读不到时显示"未读到 + 一句原因"，
 *     不显示 0（0 会被读成"全都收工了"），并把「活跃（非静默）」单列一格。
 * 三态的判定只有后端一处（`conductor.agent_state`）；这一层只负责把它画出来。
 *
 * ## 另一格容易读混的读数：`in_flight` 是**任务面**的
 * `nodes[].in_flight` 数的是台账里 `status ∈ pending/running` 的活（一件活一行），
 * 不是代理三态：一个挂机（待机）的代理名下那件活仍然是 `running`，所以它既不能读成
 * 「在飞 N 个」，也不能并进「活跃（非静默）」。页面把它逐字写成「未收口的活 N 件」，
 * 与三态徽标分开摆。
 *
 * ## 取数不许挨着渲染（2026-10-24 真机故障之后的划线）
 * 改前父子关系与"缺号怎么办"都长在这个组件里：`data.roots.map(renderBranch)`，而
 * `renderBranch` 第一句就是 `ctx.childrenOf[tid] ?? []`。真机上跑着的是旧后端
 * （进程起在 D-51 落盘之前），那一份读数里没有 `children_of` ⇒ `undefined[tid]`
 * 当场抛 TypeError，正文那一段永远到不了 DOM，于是"抬头在、树一行都没有"。
 * 现在这些判断全在 `../rosterTree`（纯函数、全函数、可被判据直接跑），这一层只
 * 负责把算好的行摆成 DOM：它不再直取任何一格可能不存在的读数。
 */
import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";

import { api } from "../api";
import { useFace } from "../live";
import { ACTIVE_TEXT, STATE_TEXT, asAgentState, buildRosterTree, kidsStateText, stalledTag, stateSummary, taskLine } from "../rosterTree";
import type { TreeRow } from "../rosterTree";
import type { RosterChild, RosterInbox, RosterNode, RosterTask, RosterUnrostered, RosterView } from "../types";
import { Badge } from "./Badge";
import { Card } from "./Card";
import { TriState, isUnreadable } from "./TriState";
import { cell } from "./Table";

/** 默认展开到第几层：2 = 第 1、2 层的节点展开，第 3 层的节点默认折叠。 */
const DEFAULT_OPEN_DEPTH = 2;

/** 展开态：模块级（不在组件 state 里），本次浏览内保持。
 *
 * 为什么不能挂在组件 state 上：这一页每次流里来事件都会重取一次读数，
 * 重取只会重渲染、不会重新挂载，但"切到别的页再回来"会卸载重挂 —— 挂在 state 上
 * 那一次就丢了。为什么也不写 localStorage：刷新浏览器就是一次新的浏览，
 * 把上次点开的那些分支一直留着会让"默认展开到第 2 层"这句话失效。
 */
const openOverride: Map<string, boolean> = new Map();

/** "这个子代理管过哪些活"那一栏的开合态（业主 2026-10-24：「一个子代理后面可展开它管
 * 的任务号」）。
 *
 * 与 `openOverride` 分开存：子树的展开（父子关系）与任务清单的展开是两件事，
 * 一个默认按层数算、一个默认折上；混在一个键里会让点开任务清单顺手把子树也翻了。
 * 同样住在模块级：这一页每次流里来事件就重取读数，挂在组件 state 上会被重置。
 */
const taskOpen: Map<string, boolean> = new Map();

/** 任务清单默认折上（不看层数、不看 retired）：它是明细，不是树的一部分。 */
function isTasksOpen(node: RosterNode): boolean {
  return taskOpen.get(node.task_id) === true;
}


/** 一个节点此刻开不开：用户点过就照用户点的，没点过就按默认层数算。
 *
 * 层号读不出来（缺那一格）按第 1 层算：折叠守的是"别把页面淹掉"，它不该反过来
 * 把一整支藏起来 —— 看不见的节点等于没画。
 *
 * ## 已销号的节点一律先折上（D-59 业主口径：「已销号的，名册 ui 显示默认折叠」）
 * 这一条**覆盖**层数规则：销号节点的子树代表"它退场之前那一支"，不是"现在还在跑的东西"，
 * 默认铺开只会把当班的那几行挤下去。判定次序是刻意的：**先看用户点过的**
 * （`openOverride`），再看是不是已销号，最后才是层数 —— 反过来写会让"默认折叠"
 * 把用户刚点开的那个节点又折回去，而那正是这一条最容易被改坏的地方。
 */
function isOpen(node: RosterNode): boolean {
  const asked = openOverride.get(node.task_id);
  if (asked !== undefined) {
    return asked;
  }
  if (node.retired) {
    return false;
  }
  const depth = Number.isFinite(node.depth) ? node.depth : 1;
  return depth <= DEFAULT_OPEN_DEPTH;
}

/** 名册名那一格：名字一经退役永久不复用；根不在任何人的名册里。
 *
 * 兜底只在旧后端 / 缺那一格时走到 —— 正常路径不该走到这里：根节点的 `name` 与 `role`
 * 由读侧补成主控（`readers.roster_face` 的 `_roster_root_identity`），所以根那一行
 * 在页面上就叫 `M`。兜底写 `M（顶层）`，不写"这一格读坏了"那种措辞
 * （业主 2026-10-26：「顶层能不能标 M 啊，unknown 很怪」）。
 */
function nameText(node: RosterNode): string {
  return node.name === "" ? "M（顶层）" : node.name;
}

/** 三态徽标（在飞 / 待机 / 静默 / 未读到）：文案与词表来自 `rosterTree.STATE_TEXT`，
 * 颜色三档由 CSS 那三个类给（`roster-state-*`，走 token，不写字面色值）：
 * 在飞 = 强调色、待机 = 中性偏冷（次要标签色 + 层底色）、静默 = 灰（三级标签色）、
 * 未读到 = 警示色。
 * `kind` 里带 `roster-state-` 前缀，于是 `Badge` 的 class 是 `badge roster-state-flying`。
 *
 * `unknown` 那一档刻意也画出来（不是不画）：不画会让"没读到"与"静默"在页面上
 * 长得一模一样 —— 而这一批要修的正是这个折叠。
 *
 * 悬停给 `state_reason`（后端那句"为什么判成这一格"）：三档文字只说得清"是哪一档"，
 * 说不清"凭什么" —— 而待机与静默的差别恰恰在理由里（挂着哪一条计时器 / 在等哪个子）。
 */
function stateTitle(node: RosterNode): string {
  const state = asAgentState(node.state);
  const why = node.state_reason === "" ? "（后端没给原因）" : node.state_reason;
  return `${STATE_TEXT[state]}：${why}`;
}

function stateBadge(node: RosterNode) {
  const state = asAgentState(node.state);
  return <Badge kind={`roster-state-${state}`} text={STATE_TEXT[state]} title={stateTitle(node)} />;
}

/** 疑似停滞那一枚小标记（业主 2026-10-26 第二条裁定）：画在三态徽标旁边。
 *
 * 为什么是"旁边一枚"而不是改那一枚：三态那一格回答"它现在属于哪一档"，而停滞回答
 * "它最近一步是什么时候"——两个问题，两枚标记。把停滞折进三态（例如判成静默）会让
 * 它可以被销号，而销号不可逆；所以这一格只加不改（`state` 仍是 `flying`）。
 *
 * 文案与悬停文字都来自 `rosterTree.stalledTag`（纯函数，判据能直接跑）：
 * 悬停给秒数与那一句理由，颜色走 `roster-stalled` 那一档。
 */
function stalledBadge(node: RosterNode) {
  const tag = stalledTag(node);
  if (tag === null) {
    return null;
  }
  return <Badge kind="roster-stalled" text={tag.text} title={tag.title} />;
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

/** 未落名册的子（台账里有父、名册正文与对照表里都没有任何名册项接过的那几行）。
 *
 * 旧后端（进程起在这次改动之前）给的读数里没有这一格 ⇒ 按空数组处理：那时页面
 * 与改前逐字一样，不是"没有未落名册的子"这个结论。
 */
function unrosteredOf(node: RosterNode): RosterUnrostered[] {
  return Array.isArray(node.unrostered_children) ? node.unrostered_children : [];
}

/** 「子 N」那一格：N = 台账里这个父的子数（不是名册项数）。
 *
 * 为什么改口径（2026-10-25 业主截图）：名册项只数"落了名册"的那些，名册漏写一个，
 * 父的子树读数就比台账低一个（sylow4：M 名下有 6 个，页面显示「子 4」）。所以：
 * - N 取 `child_count`（台账数）；台账读不到（null）⇒ 退回名册项数并注明"台账未读到"；
 * - 名册项数比台账少时，同一格后面显式写「其中 M 个未落名册」——不许悄悄少算。
 */
function childCountText(node: RosterNode): string {
  const missing = unrosteredOf(node).length;
  const total = typeof node.child_count === "number" ? node.child_count : node.children.length;
  const unknown = typeof node.child_count === "number" ? "" : "（台账未读到，按名册项数）";
  const tail = missing > 0 ? `（其中 ${missing} 个未落名册）` : "";
  return `子 ${total}${unknown}${tail}`;
}

/** 未落名册的子那一行：编号 + 角色 + 状态（业主：不许只躺在页面底部的 unplaced 里）。 */
function UnrosteredLine(props: { children: RosterUnrostered[] }) {
  const rows = props.children;
  if (rows.length === 0) {
    return null;
  }
  return (
    <div class="roster-unrostered">
      <span class="readings">未落名册的子（{rows.length}）：</span>
      {rows.map((u) => (
        <span class="roster-unrostered-item" key={`unrostered:${u.task_id}`}>
          <span class="mono">{u.task_id}</span>
          <Badge kind="badge-unknown" text={u.role === "" ? "unknown" : u.role} />
          <span class="readings">{u.status === "" ? "unknown" : u.status}</span>
        </span>
      ))}
    </div>
  );
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
        子（{typeof n.child_count === "number" ? n.child_count : n.children.length}）：
        <span class="roster-children">{childText(n.children)}</span>
      </div>
      <div class="row">
        它管过的活（{n.tasks.length}）：
        <span class="roster-children">
          {n.tasks.length === 0 ? "（名册里没有它接过的活的记录）" : n.tasks.map((t) => t.task_id).join("、")}
        </span>
      </div>
      <div class="row">
        台账那一行：{n.task_found ? "在" : "不在（tasks 里没有它这一行）"} ·
        状态 <span class="mono">{n.status === "" ? "unknown" : n.status}</span> ·
        名下未收口的活（台账 pending/running）{" "}
        <span class="mono" title="任务面读数：不是代理三态，也不是「活跃（非静默）」">
          {n.in_flight === null ? "未读到" : n.in_flight}
        </span>{" "}
        · 槽位面 <span class="mono">{n.surface === "" ? "（没有分到槽位）" : n.surface}</span>
      </div>
      <div class="row">
        三态：{stateBadge(n)}
        <span class="readings">
          {n.state_reason === "" ? "" : `原因：${n.state_reason}`}
        </span>
      </div>
      {n.retired ? (
        <div class="row roster-retired-note">
          已销号：这一支已退场（退役时读到的分支{" "}
          <span class="mono">{n.retired_branch === "" ? "unknown" : n.retired_branch}</span>）。
          名字永久不复用，所以这里不再显示收件箱那三格 —— 往一个已经退场的名字上投过的条目，
          读数归这条名册文件本身（`{n.task_id}` 那一份）。
        </div>
      ) : (
        <InboxBlock inbox={n.inbox} />
      )}
    </div>
  );
}

/** 递归画树要用的那几样东西（一路传下去，免得每次取数都重算一遍）。 */
interface TreeCtx {
  /** 点开的那个节点的明细（一次只开一个，与改前一致）。 */
  picked: string;
  onToggle: (node: RosterNode) => void;
  onToggleTasks: (node: RosterNode) => void;
  onPick: (tid: string) => void;
}

/** 一条分支：这个节点一行 + （展开了才画）它自己的子树。
 *
 * 缩进与连接线由嵌套的 `.roster-kids` 给（`border-left` 就是那条竖线），所以这里
 * 不再按 `depth` 现算左缩进 —— 那正是改前"按层平铺"的形态。层号仍然印在行首
 * （`dN` 是读数，不是缩进的来源）。
 *
 * 父子关系、"这一支缺号"这些判断全在 `rosterTree.buildRosterTree` 里做完了：
 * 这里只负责把一行树摆成 DOM。改前这里自己读 `children_of` 与 `nodes`，后端少给
 * 一格就整片不画 —— 那一次故障的教训是"取数不许挨着渲染"。
 */
function renderBranch(row: TreeRow, ctx: TreeCtx): ComponentChildren {
  const node = row.node;
  if (node === null) {
    // 父子关系里有它、可这次读数里没有它（截断 / 成环）：如实摆一行，不许跳过。
    return (
      <div class="roster-node roster-missing" key={`missing:${row.task_id}`}>
        <span class="mono">{row.task_id === "" ? "unknown" : row.task_id}</span>
        <span class="readings">{row.text}</span>
      </div>
    );
  }
  const kids = row.kids;
  const open = isOpen(node);
  const tasksShown = isTasksOpen(node);
  return (
    <div class="roster-branch" key={row.task_id}>
      <div class="roster-node">
        <div class="roster-row">
          {kids.length === 0 ? (
            <span class="roster-twist roster-twist-leaf" aria-hidden="true">
              ·
            </span>
          ) : (
            <button
              type="button"
              class="roster-twist"
              aria-expanded={open}
              aria-label={`${open ? "收起" : "展开"} ${nameText(node)} 的子（${kids.length} 个）`}
              onClick={() => ctx.onToggle(node)}
            >
              {open ? "▾" : "▸"}
            </button>
          )}
          <button
            type="button"
            class="roster-pick"
            aria-expanded={ctx.picked === node.task_id}
            onClick={() => ctx.onPick(node.task_id)}
          >
            <span class="mono">d{node.depth}</span>
            <span class={node.retired ? "roster-name roster-retired" : "roster-name"}>
              {nameText(node)}
            </span>
            <Badge kind="badge-unknown" text={node.role === "" ? "unknown" : node.role} />
            <span class="mono">{node.task_id === "" ? "unknown" : node.task_id}</span>
            <span class="readings">{childCountText(node)}</span>
            {/* 「▸ 活 N（飞 a · 待 b）」：N = 非静默（在飞 + 待机），不是 children.length
                （业主 2026-10-26：「『▸ 活 N』改成 ▸ 活 N（飞 a · 待 b），N = 非静默」）。
                这一格数的是本节点的直接子；`unknown` 单独列，不混进活跃。
                悬停把口径钉在字面上：静默的子不在 N 里，而未读到的子另列一格 ——
                "名下 5 个、其中 4 个昨天就收工了"与"5 个都在干活"从此长得不一样。 */}
            {kids.length === 0 ? null : (
              <span
                class="readings"
                title={`「活 N」的 N = ${ACTIVE_TEXT} = 在飞 + 待机，不是名下子节点的个数`
                  + "（静默的不算，未读到的单独列）"}
              >
                {`▸ ${kidsStateText(kids)}`}
              </span>
            )}
            {/* 三态徽标：在飞 / 待机 / 静默 / 未读到（文案与颜色都跟着这一档走，悬停给原因）。 */}
            {stateBadge(node)}
            {/* 疑似停滞（业主 2026-10-26 第二条）：紧挨着三态徽标的小标记 ——
                三态说"它属于哪一档"，这一枚说"它最近一步离现在多久"。只加不改：
                三态那枚不动，所以"它仍然在跑"与"它已经很久没动静"同时看得见。 */}
            {stalledBadge(node)}
            {/* 这一格是**任务面**读数：台账里 `status ∈ pending/running` 的活有几件。
                它不是代理三态 —— 挂机（待机）的代理名下那件活仍然是 running，所以
                它既不是「在飞 N 个」，也不能并进「活跃（非静默）」。 */}
            {node.in_flight === null ? (
              <Badge kind="badge-unknown" text="未收口的活：未读到"
                title="台账读不到 ⇒ 这一格不是 0 件" />
            ) : node.in_flight > 0 ? (
              <Badge kind="badge-pending" text={`未收口的活 ${node.in_flight} 件`}
                title="任务面读数：台账里 status ∈ pending/running 的活有几件（不含代理三态）" />
            ) : null}
            {node.retired ? null : inboxBadge(node.inbox)}
            {node.retired ? <Badge kind="badge-na" text="已销号" /> : null}
          </button>
          {node.tasks.length === 0 ? null : (
            <button
              type="button"
              class="roster-twist roster-twist-tasks"
              aria-expanded={tasksShown}
              aria-label={`${tasksShown ? "收起" : "展开"} ${nameText(node)} 管过的 ${
                node.tasks.length
              } 件活`}
              onClick={() => ctx.onToggleTasks(node)}
            >
              {`${tasksShown ? "▾" : "▸"} 活 ${node.tasks.length}`}
            </button>
          )}
        </div>
      </div>
      {/* ↓ 未落名册的子挂在父节点下面（编号 + 角色 + 状态，不必点开明细就看得见）。
          它们同时仍进页面底部的 unplaced 列表：两处是同一处判据的两个落位。 */}
      <UnrosteredLine children={unrosteredOf(node)} />
      {tasksShown ? <TaskList tasks={node.tasks} /> : null}
      {ctx.picked === node.task_id ? <NodeDetail node={node} /> : null}
      {open && kids.length > 0 ? (
        <div class="roster-kids">{kids.map((kid) => renderBranch(kid, ctx))}</div>
      ) : null}
    </div>
  );
}

/** 一个子代理管过的那些活（业主 2026-10-24：「一个子代理后面可展开它管的任务号」）。
 *
 * 一行一件活：编号 + 起止时间 + 状态 + 一句话（`taskLine` 在 `../rosterTree` 里，
 * 纯函数、可被判据直接跑）。这一栏与父子那一层是两个层次：先画代理树，再在每个
 * 代理下面挂它管过的任务号 —— 不把任务当节点摆进树里（那会造出 d1 上多出来的根，
 * 正是 D-66 那个故障的形态）。
 */
function TaskList(props: { tasks: RosterTask[] }) {
  return (
    <div class="roster-tasks">
      {props.tasks.map((task) => (
        <div class="row roster-task" key={`task:${task.task_id}`}>
          <span class="mono">{task.task_id}</span>
          <span class="readings">{taskLine(task)}</span>
        </div>
      ))}
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
  // 展开态本身住在模块级的 `openOverride` 里；这个计数器只负责让一次点击变成一次重绘。
  const [, setTick] = useState<number>(0);
  const data: RosterView | null = face.data;
  // `files` 那一格也照"取不到就是 0 份"处理：抬头这一句不许成为整张卡片的崩溃点。
  const files = data === null || !Array.isArray(data.files) ? 0 : data.files.length;
  const subtitle =
    data === null
      ? ""
      : `节点 ${cell(data.count)} 个 · 最深 ${cell(data.max_depth)} 层 · 读到的名册/对照表文件 ${files} 份`;
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
        <RosterBody data={data} picked={picked} setPicked={setPicked} repaint={() => setTick((t) => t + 1)} />
      )}
    </Card>
  );
}

/** 名册卡片的正文（读数齐了之后那一半）。
 *
 * 为什么单独一个组件：树的遍历要在渲染之前先跑一遍，而 `RosterPanel` 那一层还要
 * 管取数与三态——把"画树"这一段单独摆开，读的人一眼看得出哪几行是树、哪几行是壳。
 *
 * 父子关系、"缺号"、"走不到"这些判断都不在这里：它们在 `rosterTree.buildRosterTree`
 * 里（纯函数、全函数）。改前这一段自己读 `data.roots` / `data.children_of`，后端
 * 少给一格就整片不画 —— 取数不许挨着渲染，这就是那一次故障的教训。
 */
function RosterBody(props: {
  data: RosterView;
  picked: string;
  setPicked: (tid: string) => void;
  repaint: () => void;
}) {
  const data = props.data;
  const tree = buildRosterTree(data);
  const ctx: TreeCtx = {
    picked: props.picked,
    onToggle: (node: RosterNode) => {
      openOverride.set(node.task_id, !isOpen(node));
      props.repaint();
    },
    onToggleTasks: (node: RosterNode) => {
      taskOpen.set(node.task_id, !isTasksOpen(node));
      props.repaint();
    },
    onPick: (tid: string) => props.setPicked(props.picked === tid ? "" : tid),
  };
  const nodes = Array.isArray(data.nodes) ? data.nodes.length : 0;
  const summary = stateSummary(data, tree.rows, tree.unreached);
  const coverage = data.coverage ?? ({ tasks_agents: null, roster_nodes: null, unrostered: null });
  const diagnostics = Array.isArray(data.diagnostics) ? data.diagnostics : [];
  const unplaced = Array.isArray(data.unplaced) ? data.unplaced : [];
  return (
    <>
      <div class="readings">
        落点 <span class="mono">{data.dir}</span>（一份 &lt;父编号&gt;.jsonl = 一个父
        名下的子；折叠口径与秘书那一侧同一处实现）。树按父子展开：子挂在父下面，
        同一父的多个子按落盘行序排。默认展开到第 {DEFAULT_OPEN_DEPTH} 层，
        其余折叠（点行首的三角）；展开态在本次浏览内保持。
      </div>
      {/* 顶部合计（业主 2026-10-26：「顶部合计：在飞 a · 待机 b · 静默 c」）。
          读不到就显示「未读到」+ 一句原因，绝不显示 0 / 0 / 0 ——
          那一行 0 会被读成"全都收工了"，而它可能是"这一格没查成"。
          活跃 = 非静默 = 在飞 + 待机；`未读到` 单独列，不混进活跃也不混进静默。
          「活跃（非静默）」单列一格，是因为页面别处还有几处"在跑几个"的读数
          （任务面 / 循环面）—— 口径必须钉在字面上，读的人才不会拿两个数互相当证据。 */}
      <div class="readings roster-states">
        三态合计：<b>{summary.text}</b>
        {" · "}
        {summary.active === null
          ? `${ACTIVE_TEXT} 未读到`
          : `${ACTIVE_TEXT} ${summary.active}${
            summary.total === null ? "" : ` · 共 ${summary.total}`}`}
        {summary.reason === "" ? null : (
          <span class="tri-reason">（{summary.reason}）</span>
        )}
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
      {nodes === 0 ? (
        <div class="empty">
          {data.answer === "ok"
            ? "读到了名册，但里面一个节点都没有（合法空态：读到了、里面是 0 个）。"
            : "节点列表是空的 —— 与上面那句「名册没读到」一起读，不许当成「没有子代理」。"}
        </div>
      ) : null}
      {tree.notes.map((note) => (
        <div class="readings roster-note" key={note}>
          {note}
        </div>
      ))}
      {tree.missing.length === 0 ? null : (
        <div class="readings roster-note">
          这一份父子关系里有 {tree.missing.length} 个编号不在这次的节点读数里（可能被截断）
          ⇒ 逐个摆出说明行，不跳过：
          <span class="roster-diag">{tree.missing.join("、")}</span>
        </div>
      )}
      {unplaced.length === 0 ? null : (
        <div class="readings roster-note">
          台账里有 {unplaced.length} 个「有父的代理行」没有任何名册项接过 ⇒ 平铺在这里并点名，
          不把它们抬成树根（名册那一格缺了它们的归属）：
          {unplaced.map((row) => (
            <span class="roster-diag" key={`unplaced:${row.task_id}`}>
              {" "}
              {row.task_id}（父 {row.parent_task_id} · 角色 {row.role} · 状态{" "}
              {row.status === "" ? "unknown" : row.status}）
            </span>
          ))}
        </div>
      )}
      {nodes === 0 ? null : (
        <div class="roster-tree">
          {tree.rows.map((row) => renderBranch(row, ctx))}
          {tree.unreached.length === 0 ? null : (
            <div class="roster-missing">
              <span class="readings">
                还有 {tree.unreached.length} 个节点从根上走不到（名册链成环，或它的父不在这次
                读数里）⇒ 按平铺摆在这里，不当成它们不存在：
              </span>
              {tree.unreached.map((n) => (
                <span class="roster-diag" key={`unreached:${n.task_id}`}>
                  {" "}
                  d{n.depth} {nameText(n)}（<span class="mono">{n.task_id}</span>）
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      {data.truncated ? (
        <div class="readings">
          这一棵树超过后端的规模上限 ⇒ 只画了一部分（`truncated=true`）。
        </div>
      ) : null}
      {coverage.roster_nodes === null ? null : (
        <div class="readings">
          对账：台账里 {cell(coverage.tasks_agents)} 个代理行 · 名册上{" "}
          {cell(coverage.roster_nodes)} 个节点 · 其中{" "}
          {cell(coverage.unrostered)} 个「有父的代理行」不在任何名册里
          （名册机制上线之前落的行）。
        </div>
      )}
      {diagnostics.length === 0 ? null : (
        <div class="readings">
          逐条诊断：
          {diagnostics.map((d) => (
            <span class="roster-diag" key={d}>
              {" "}
              {d}
            </span>
          ))}
        </div>
      )}
    </>
  );
}
