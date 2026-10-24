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
 * ## 三态纪律（这一块最要紧的一条）
 * `answer === "unknown"` 是「名册没读到」（目录不在 / 读不出来 / 有一条读不出来），
 * 不是「这个工作区没有子代理」。所以那一档：
 *   - 不许画成"子代理：0"（后端给的是 `count: null`，不是 0）；
 *   - 必须把 `reason` 原样摆出来（后端逐档写清了是哪一档）；
 *   - 节点列表为空时也只能说"没读到"，不许说"没有"。
 * 反过来，`answer === "ok"` 而 `nodes` 是空数组才算"读到了、里面是 0 个"（合法空态）。
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
import { buildRosterTree } from "../rosterTree";
import type { TreeRow } from "../rosterTree";
import type { RosterChild, RosterInbox, RosterNode, RosterView } from "../types";
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

/** 一个节点此刻开不开：用户点过就照用户点的，没点过就按默认层数算。
 *
 * 层号读不出来（缺那一格）按第 1 层算：折叠守的是"别把页面淹掉"，它不该反过来
 * 把一整支藏起来 —— 看不见的节点等于没画。
 */
function isOpen(node: RosterNode): boolean {
  const asked = openOverride.get(node.task_id);
  if (asked !== undefined) {
    return asked;
  }
  const depth = Number.isFinite(node.depth) ? node.depth : 1;
  return depth <= DEFAULT_OPEN_DEPTH;
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

/** 递归画树要用的那几样东西（一路传下去，免得每次取数都重算一遍）。 */
interface TreeCtx {
  /** 点开的那个节点的明细（一次只开一个，与改前一致）。 */
  picked: string;
  onToggle: (node: RosterNode) => void;
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
            <span class="roster-name">{nameText(node)}</span>
            <Badge kind="badge-unknown" text={node.role === "" ? "unknown" : node.role} />
            <span class="mono">{node.task_id === "" ? "unknown" : node.task_id}</span>
            <span class="readings">子 {node.children.length}</span>
            {node.retired ? <Badge kind="badge-na" text="已退役" /> : null}
            {node.in_flight === null ? (
              <Badge kind="badge-unknown" text="在飞：未读到" />
            ) : node.in_flight > 0 ? (
              <Badge kind="badge-pending" text="在飞" />
            ) : null}
            {inboxBadge(node.inbox)}
          </button>
        </div>
      </div>
      {ctx.picked === node.task_id ? <NodeDetail node={node} /> : null}
      {open && kids.length > 0 ? (
        <div class="roster-kids">{kids.map((kid) => renderBranch(kid, ctx))}</div>
      ) : null}
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
    onPick: (tid: string) => props.setPicked(props.picked === tid ? "" : tid),
  };
  const nodes = Array.isArray(data.nodes) ? data.nodes.length : 0;
  const coverage = data.coverage ?? ({ tasks_agents: null, roster_nodes: null, unrostered: null });
  const diagnostics = Array.isArray(data.diagnostics) ? data.diagnostics : [];
  return (
    <>
      <div class="readings">
        落点 <span class="mono">{data.dir}</span>（一份 &lt;父编号&gt;.jsonl = 一个父
        名下的子；折叠口径与秘书那一侧同一处实现）。树按父子展开：子挂在父下面，
        同一父的多个子按落盘行序排。默认展开到第 {DEFAULT_OPEN_DEPTH} 层，
        其余折叠（点行首的三角）；展开态在本次浏览内保持。
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
