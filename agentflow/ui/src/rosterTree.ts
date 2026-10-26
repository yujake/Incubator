/*
 * 名册树的纯逻辑：把 `GET /api/roster` 的那一份读数变成"要画哪些行"。
 *
 * ## 为什么从组件里抽出来（真机故障：名册页整片不显示）
 * 改前这一段递归住在 `Roster.tsx` 里，写法是 `data.roots.map(renderBranch)`，
 * `renderBranch` 里第一句就是 `ctx.childrenOf[tid] ?? []` —— 只要后端那一份读数
 * 里没有 `children_of` 这一格，`ctx.childrenOf` 就是 `undefined`，取属性这一步当场
 * 抛 TypeError（`?? []` 救不了"表本身是 undefined"）。异常从渲染里冒出去，正文那
 * 一段就永远到不了 DOM：抬头（`count` / `max_depth`）已经提交了，树一行都没有，
 * 控制台之外没人看得见为什么。
 *
 * 真机上那一次就是这么来的：`web` 进程 17:36:34 起，D-51 18:15:10 才落盘 ⇒
 * 浏览器拿到新前端、旧后端，旧后端那 15 个键里没有 `children_of`。
 *
 * 所以这一层立三条规矩：
 * 1. 它是纯函数（不 import preact、不碰 DOM），于是"画哪些行"可以被判据直接跑；
 * 2. 它是全函数：任何一格取不到数组/字段都走"画一行说明"，绝不把异常抛给渲染；
 * 3. 它是穷尽的：`nodes` 里的每一个节点都必须出现在 `rows` 或 `unreached` 里，
 *    父子关系点名了、可这次读数里没有的编号必须有一行说明（带编号）。
 *
 * ## 三档口径（与面板那一段一致）
 * - 有 `children_of` ⇒ 就用它（它是"谁是谁的子"的唯一读数，顺序就是落盘行序）；
 * - 没有 / 是空的 ⇒ 退到每个节点自己的 `children`，再退到别人的 `parent_task_id`；
 * - `roots` 为空而 `nodes` 非空 ⇒ 按 `parent_task_id` 为空、且不在任何父名下的
 *   编号找根（退化的根也是根，不靠平铺兜底去凑数）。
 */
import type {
  RosterChild,
  RosterInbox,
  RosterInboxItem,
  RosterNode,
  RosterTask,
  RosterUnrostered,
  RosterView,
  Tri,
} from "./types";

/** 树里的一行：一个节点，或一行说明（父子关系里有它、这次读数里没有它）。 */
export interface TreeRow {
  /** `node` = 画这个节点；`missing` = 画一行说明（编号 + 一句为什么）。 */
  kind: "node" | "missing";
  task_id: string;
  /** `kind === "node"` 时是它的读数；`kind === "missing"` 时是 null。 */
  node: RosterNode | null;
  /** 它的直接子（`kind === "missing"` 时恒为空）。 */
  kids: TreeRow[];
  /** `kind === "missing"` 时那一行的文字；`kind === "node"` 时是空串。 */
  text: string;
}

/** 一整棵树：要画的行 + 降级的说明 + 缺号 + 从根上走不到的节点。 */
export interface RosterTree {
  rows: TreeRow[];
  /** 这一份读数里读不到 / 对不上的格子，逐条一句人话（照原样摆在树上面）。 */
  notes: string[];
  /** 父子关系点名了、可这次读数里没有的编号（每一个都有一行说明）。 */
  missing: string[];
  /** 从根上走不到、按平铺摆出来的节点（`nodes` 里剩下的那些）。 */
  unreached: RosterNode[];
}

/** 缺号那一行的文字（业主那一句原话；带编号，读的人认得出是哪一条）。 */
export function missingText(taskId: string): string {
  return `这次读数里没有 ${taskId === "" ? "unknown" : taskId}（可能被截断）`;
}

/** 摊平成一串行（画的时候要递归，判据要数"到底画了哪些"）。 */
export function flattenRows(rows: TreeRow[]): TreeRow[] {
  const out: TreeRow[] = [];
  for (const row of rows) {
    out.push(row);
    for (const kid of flattenRows(row.kids)) {
      out.push(kid);
    }
  }
  return out;
}

/** 一个对象（不是数组、不是 null）。 */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 字符串那一格：不是字符串就当空串（本组件把空串读成"这一格没读到"）。 */
function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** 数字那一格：不是有限数字就当"未读到"（null），不折成 0。 */
function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** 三态那一格：词表外的一律当"没读到"（把"没查成"折成"算出来了"是这一页最忌的）。 */
function asTri(value: unknown): Tri {
  return value === "computed" || value === "not_applicable" || value === "unreadable"
    ? value
    : "unreadable";
}


/** 计数字典那一格（`{queued: 2}`）：非数字的取值丢掉，不猜。 */
function asDict(value: unknown): Record<string, number> {
  const out: Record<string, number> = {};
  if (!isRecord(value)) {
    return out;
  }
  for (const key of Object.keys(value)) {
    const num = asNumber(value[key]);
    if (num !== null) {
      out[key] = num;
    }
  }
  return out;
}

/** 编号数组那一格：只认字符串与 `{task_id: ...}` 两种形状，空编号丢掉。 */
function idsOf(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const out: string[] = [];
  for (const item of value) {
    const id = typeof item === "string" ? item : isRecord(item) ? asText(item["task_id"]) : "";
    if (id !== "" && !out.includes(id)) {
      out.push(id);
    }
  }
  return out;
}

/** 名册里的一个子（节点自己那一格 `children` 的元素）。 */
function asChildren(value: unknown): RosterChild[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const out: RosterChild[] = [];
  for (const item of value) {
    if (!isRecord(item)) {
      continue;
    }
    out.push({
      task_id: asText(item["task_id"]),
      name: asText(item["name"]),
      role: asText(item["role"]),
      retired: item["retired"] === true,
    });
  }
  return out;
}

/** 收件箱明细的一条。 */
function asInboxItems(value: unknown): RosterInboxItem[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const out: RosterInboxItem[] = [];
  for (const item of value) {
    if (!isRecord(item)) {
      continue;
    }
    out.push({
      task_id: asText(item["task_id"]),
      kind: asText(item["kind"]),
      state: asText(item["state"]),
      called_by: asText(item["called_by"]),
      detail: asText(item["detail"]),
    });
  }
  return out;
}

/** 这个子代理接过的那些活（`nodes[].tasks[]`；读不到就是空数组，不是"没干过活"）。 */
/** 未落名册的子（台账里有父、名册正文与对照表都没说谁接过它）。
 *
 * 旧后端给的读数里没有这一格 ⇒ 空数组（那时名册页与改前逐字一样，不是"没有未落名册"。）
 */
function asUnrostered(value: unknown): RosterUnrostered[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const out: RosterUnrostered[] = [];
  for (const item of value) {
    if (!isRecord(item)) {
      continue;
    }
    const taskId = asText(item["task_id"]);
    if (taskId === "") {
      continue;
    }
    out.push({
      task_id: taskId,
      role: asText(item["role"]),
      status: asText(item["status"]),
      started_at: asText(item["started_at"]),
      ended_at: asText(item["ended_at"]),
      why: asText(item["why"]),
    });
  }
  return out;
}

function asTasks(value: unknown): RosterTask[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const out: RosterTask[] = [];
  for (const item of value) {
    if (!isRecord(item)) {
      continue;
    }
    const taskId = asText(item["task_id"]);
    if (taskId === "") {
      continue;
    }
    out.push({
      task_id: taskId,
      role: asText(item["role"]),
      status: asText(item["status"]),
      started_at: asText(item["started_at"]),
      ended_at: asText(item["ended_at"]),
      task_found: item["task_found"] === true,
      brief: asText(item["brief"]),
      detail: asText(item["detail"]),
    });
  }
  return out;
}

/** 收件箱那一格：读不到就是"未读到"（三格都是 null），不是 0 条。 */
function asInbox(value: unknown): RosterInbox {
  if (!isRecord(value)) {
    return {
      tri: "unreadable",
      unread: null,
      seen_not_acked: null,
      open_total: null,
      other: null,
      by_state: {},
      by_kind: {},
      items: [],
      more: 0,
      reason: "这一次读数里没有收件箱那一格 ⇒ 未读到（不是 0 条）",
    };
  }
  return {
    tri: asTri(value["tri"]),
    unread: asNumber(value["unread"]),
    seen_not_acked: asNumber(value["seen_not_acked"]),
    open_total: asNumber(value["open_total"]),
    other: asNumber(value["other"]),
    by_state: asDict(value["by_state"]),
    by_kind: asDict(value["by_kind"]),
    items: asInboxItems(value["items"]),
    more: asNumber(value["more"]) ?? 0,
    reason: asText(value["reason"]),
  };
}

/** 一个节点：每一格都补齐默认值，于是明细那一段不会因为某个字段是 undefined 就炸。 */
function asNode(value: unknown): RosterNode | null {
  if (!isRecord(value)) {
    return null;
  }
  const taskId = asText(value["task_id"]);
  if (taskId === "") {
    return null;
  }
  const children = asChildren(value["children"]);
  return {
    task_id: taskId,
    name: asText(value["name"]),
    role: asText(value["role"]),
    // 没有层号的节点按第 1 层算：折叠口径只会"多展开"，不会把整支藏在下面。
    depth: asNumber(value["depth"]) ?? 1,
    parent_task_id: asText(value["parent_task_id"]),
    parent_name: asText(value["parent_name"]),
    children,
    // 子数按台账数（读不到 ⇒ null，界面那一格退回名册项数并注明"台账未读到"）；
    // 名册项数缺省按 children 的数量算（旧后端只给 children）。
    child_count: asNumber(value["child_count"]),
    roster_child_count: asNumber(value["roster_child_count"]) ?? children.length,
    unrostered_children: asUnrostered(value["unrostered_children"]),
    retired: value["retired"] === true,
    retired_branch: asText(value["retired_branch"]),
    brief: asText(value["brief"]),
    brief_source: asText(value["brief_source"]),
    surface: asText(value["surface"]),
    status: asText(value["status"]),
    // 三态：词表外 / 缺那一格 ⇒ `unknown`（旧后端不给这一格时，页面说的是"未读到"，
    // 而不是把它当成"静默" —— 那正是这一批要修的那个读数的反面）。
    state: asAgentState(value["state"]),
    state_reason: asText(value["state_reason"]),
    task_found: value["task_found"] === true,
    in_flight: asNumber(value["in_flight"]),
    inbox: asInbox(value["inbox"]),
    tasks: asTasks(value["tasks"]),
  };
}

/** 一件活那一行的文字（业主 2026-10-24：「一个子代理后面可展开它管的任务号」）。
 *
 * 读不到的格子写"未读到"，不折成 0 / 空串冒充"没有"：这一行的用途是让人认出
 * "这个子代理管过哪几件活、各是什么时候跑的、什么结局"，缺一格就少一格的可判性。
 */
export function taskLine(task: RosterTask): string {
  const started = task.started_at === "" ? "开始未读到" : task.started_at;
  const ended = task.ended_at === "" ? "结束未读到" : task.ended_at;
  const status = task.status === "" ? "状态未读到" : task.status;
  const tail = task.brief !== "" ? task.brief : task.detail;
  const raw = `${started} → ${ended} · ${status}${tail === "" ? "" : ` · ${tail}`}`;
  // 台账里没有它那一行 ⇒ 把那件事说出来（编号来自名册的调用记录，时间是空的）。
  return task.task_found ? raw : `${raw}（台账里没有它这一行）`;
}

/** 没有 `children_of` 时：按每个节点自己的 `children` 拼，再按别人的 `parent_task_id` 补。 */
function deriveChildrenOf(byId: Map<string, RosterNode>): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  const placed = new Set<string>();
  for (const node of byId.values()) {
    const kids: string[] = [];
    for (const child of node.children) {
      // 子不在这次读数里也留着：它是"被点名却缺号"的那一条，要画说明行。
      if (child.task_id !== "" && !kids.includes(child.task_id)) {
        kids.push(child.task_id);
      }
    }
    if (kids.length === 0) {
      continue;
    }
    out[node.task_id] = kids;
    for (const kid of kids) {
      placed.add(kid);
    }
  }
  for (const node of byId.values()) {
    const parent = node.parent_task_id;
    if (parent === "" || parent === node.task_id || !byId.has(parent) || placed.has(node.task_id)) {
      continue;
    }
    const list = out[parent] ?? [];
    if (!list.includes(node.task_id)) {
      list.push(node.task_id);
    }
    out[parent] = list;
    placed.add(node.task_id);
  }
  return out;
}

/** 父到子的索引：优先用读数给的 `children_of`，没有就按节点自己拼。 */
function childrenIndexOf(
  view: RosterView,
  byId: Map<string, RosterNode>,
  notes: string[],
): Record<string, string[]> {
  const raw: unknown = view.children_of;
  if (!isRecord(raw)) {
    notes.push(
      "这一次读数里没有 children_of（父到子那一份）⇒ 改按每个节点自己的 children 拼父子关系",
    );
    return deriveChildrenOf(byId);
  }
  const out: Record<string, string[]> = {};
  for (const parent of Object.keys(raw)) {
    const kids = idsOf(raw[parent]);
    if (kids.length > 0) {
      out[parent] = kids;
    }
  }
  if (Object.keys(out).length === 0 && byId.size > 0) {
    notes.push("children_of 是空的（没有任何父有子）⇒ 改按每个节点自己的 children 拼父子关系");
    return deriveChildrenOf(byId);
  }
  return out;
}

/** 根：优先用读数给的 `roots`，没有就按 `parent_task_id` 为空找（退化的根也是根）。 */
function rootsOf(
  view: RosterView,
  byId: Map<string, RosterNode>,
  childrenOf: Record<string, string[]>,
  notes: string[],
): string[] {
  const given = idsOf(view.roots);
  if (given.length > 0) {
    return given;
  }
  if (byId.size === 0) {
    notes.push("这一份读数里既没有 roots 也没有 nodes ⇒ 没有树可画");
    return [];
  }
  const childIds = new Set<string>();
  for (const kids of Object.values(childrenOf)) {
    for (const kid of kids) {
      childIds.add(kid);
    }
  }
  const roots: string[] = [];
  for (const node of byId.values()) {
    if (node.parent_task_id === "" && !childIds.has(node.task_id)) {
      roots.push(node.task_id);
    }
  }
  if (roots.length === 0) {
    for (const node of byId.values()) {
      if (!childIds.has(node.task_id)) {
        roots.push(node.task_id);
      }
    }
  }
  if (roots.length === 0) {
    for (const node of byId.values()) {
      roots.push(node.task_id);
    }
  }
  notes.push(
    `roots 是空的（这一次没读到根）⇒ 按 parent_task_id 为空、且不在任何父名下的编号找根，共 ${roots.length} 个`,
  );
  return roots;
}

/** 兜底：按平铺摆出这次读数里的全部节点（异常那一档也一个都不丢）。 */
function flatRows(view: RosterView): TreeRow[] {
  const rows: TreeRow[] = [];
  const raw: unknown = view.nodes;
  if (!Array.isArray(raw)) {
    return rows;
  }
  for (const item of raw) {
    const node = asNode(item);
    if (node !== null) {
      rows.push({ kind: "node", task_id: node.task_id, node, kids: [], text: "" });
    }
  }
  return rows;
}

/** 读数齐了之后那一半：从根起递归，缺号与走不到的节点都摆出来。 */
function build(view: RosterView, notes: string[]): RosterTree {
  const byId = new Map<string, RosterNode>();
  const rawNodes: unknown = view.nodes;
  if (Array.isArray(rawNodes)) {
    for (const item of rawNodes) {
      const node = asNode(item);
      if (node === null) {
        notes.push("nodes 里有一行没有 task_id ⇒ 那一行摆不出来");
        continue;
      }
      if (!byId.has(node.task_id)) {
        byId.set(node.task_id, node);
      }
    }
  } else {
    notes.push("nodes 不是数组（这一份读数里没有节点表）⇒ 这一棵没有节点可画");
  }
  const childrenOf = childrenIndexOf(view, byId, notes);
  const roots = rootsOf(view, byId, childrenOf, notes);
  const visited = new Set<string>();
  const missing: string[] = [];
  const walk = (taskId: string): TreeRow => {
    const node = byId.get(taskId);
    if (node === undefined) {
      if (!missing.includes(taskId)) {
        missing.push(taskId);
      }
      return { kind: "missing", task_id: taskId, node: null, kids: [], text: missingText(taskId) };
    }
    if (visited.has(taskId)) {
      return {
        kind: "missing",
        task_id: taskId,
        node: null,
        kids: [],
        text: "这一支已经在上面画过（名册链成环）⇒ 不再往下展开",
      };
    }
    visited.add(taskId);
    return {
      kind: "node",
      task_id: taskId,
      node,
      kids: (childrenOf[taskId] ?? []).map(walk),
      text: "",
    };
  };
  const rows = roots.map(walk);
  const unreached: RosterNode[] = [];
  for (const node of byId.values()) {
    if (!visited.has(node.task_id)) {
      unreached.push(node);
    }
  }
  if (unreached.length > 0) {
    notes.push(
      `还有 ${unreached.length} 个节点从根上走不到（名册链成环，或它的父不在这次读数里）⇒ 按平铺摆出来，不当成它们不存在`,
    );
  }
  return { rows, notes, missing, unreached };
}

/** 名册树的唯一入口：一份读数进来，要画的行出去。不会抛异常。 */
export function buildRosterTree(view: RosterView | null | undefined): RosterTree {
  if (view === null || view === undefined) {
    return { rows: [], notes: ["名册读数还没到（这一格没有数据）"], missing: [], unreached: [] };
  }
  const face: RosterView = view;
  const notes: string[] = [];
  try {
    return build(face, notes);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    notes.push(
      `名册树这一层读不出来（${message}）⇒ 改成按平铺摆出这次读数里的全部节点，一个都不丢`,
    );
    return { rows: flatRows(face), notes, missing: [], unreached: [] };
  }
}

// ====================================================================== 三态（在飞 / 待机 / 静默）
//
// 业主 2026-10-26：「『在飞』的读数要随着时钟式待机进行适配，分三种……更新『活跃子代理』
// 的定义为非静默子代理。」判定只有后端一处（conductor.agent_state）；这一层只做
// 三件纯事：把那一格读成四档之一、数成合计、拼成页面上那一行字。

/** 一个代理的三态（业主 2026-10-26：「『在飞』的读数要随着时钟式待机进行适配」）。
 *
 * 判定只有后端一处（`conductor.agent_state`）；这一层只负责"把那一格读出来、
 * 读不出来就说读不出来"。四档与业主的原话一一对应：
 * - `flying` 在飞：正在工作；
 * - `standby` 待机：没在工作，但时钟上挂着等待（或在等名下的活）；
 * - `silent` 静默：已收工、无任务、无计时器；
 * - `unknown` 未读到：判不了（台账 / 名册 / 时钟有一处读不成）—— **不是静默的别名**。
 */
export type AgentState = "flying" | "standby" | "silent" | "unknown";

/** 四档的次序（与后端 `AGENT_STATES` 同一份；`unknown` 在三态之外）。 */
export const AGENT_STATES: AgentState[] = ["flying", "standby", "silent", "unknown"];

/** 三档文案（业主的原话）＋"没读到"。页面上每一处都从这里取，不许各写一份。 */
export const STATE_TEXT: Record<AgentState, string> = {
  flying: "在飞",
  standby: "待机",
  silent: "静默",
  unknown: "未读到",
};

/** 词表外的一律当 `unknown`（旧后端不给这一格 ⇒ 未读到，不是静默）。 */
export function asAgentState(value: unknown): AgentState {
  return value === "flying" || value === "standby" || value === "silent" || value === "unknown"
    ? value
    : "unknown";
}

/** 活跃 = 非静默 = 在飞 + 待机（业主：「更新『活跃子代理』的定义为非静默子代理」）。
 *
 * `unknown` 刻意不算活跃：判不了不等于活跃。它也不算静默 —— 它自己那一格单独数。
 */
export function isActiveState(state: AgentState): boolean {
  return state === "flying" || state === "standby";
}

/** 四档各几个 + `active`（= 在飞 + 待机）+ `total`。 */
export interface StateTally {
  flying: number;
  standby: number;
  silent: number;
  unknown: number;
  active: number;
  total: number;
}

/** 数一串三态（`unknown` 单独一格，不并进静默）。 */
export function tallyStates(states: AgentState[]): StateTally {
  const out: StateTally = { flying: 0, standby: 0, silent: 0, unknown: 0, active: 0, total: 0 };
  for (const state of states) {
    out[state] += 1;
    out.total += 1;
  }
  out.active = out.flying + out.standby;
  return out;
}

/** 一个节点名下那些子的三态合计；缺号那一行（`kind === "missing"`）算 `unknown`。 */
export function tallyKids(kids: TreeRow[]): StateTally {
  return tallyStates(kids.map((kid) => (kid.node === null ? "unknown" : asAgentState(kid.node.state))));
}

/** 行尾那一格「活 N（飞 a · 待 b）」：N = 非静默 = 在飞 + 待机。
 *
 * 业主 2026-10-26：「『▸ 活 N』改成 ▸ 活 N（飞 a · 待 b），N = 非静默」。
 * 为什么不用 `children.length`：那个数把已收工（静默）的子也算进来，于是"名下 5 个、
 * 其中 4 个早在昨天就收工了"与"名下 5 个都在干活"长得一模一样 —— 这正是这一批要修的
 * 那个读数。`unknown` 不进 N（判不了不等于活跃），但它一定单独显示出来，不许被吃掉。
 */
export function kidsStateText(kids: TreeRow[]): string {
  const tally = tallyKids(kids);
  const unknown = tally.unknown > 0 ? ` · 未读到 ${tally.unknown}` : "";
  return `活 ${tally.active}（飞 ${tally.flying} · 待 ${tally.standby}${unknown}）`;
}

/** 「活跃」的唯一措辞（业主：「更新『活跃子代理』的定义为非静默子代理」）。
 *
 * 页面每一处说"活跃"都从这里取：活跃 = 非静默 = 在飞 + 待机，`未读到` 不在里面。
 * 为什么不写成"活跃"两个字：那个词在本项目里被用过好几套口径（在跑 / 非静默 /
 * 名下有未收口的活），只写两个字读的人分不出是哪一套 —— 括注等于把口径钉在字面上。
 */
export const ACTIVE_TEXT = "活跃（非静默）";

/** 合计读不到时那一行文字。刻意**一个数字都没有**：`0` 会被读成"全都收工了"，
 * 而这一档说的是"没查成"。判据逐字断言这一行里没有数字（`states.checked=false`）。
 */
export const STATES_UNREADABLE_TEXT =
  "在飞 / 待机 / 静默：未读到（这一份读数没给出合计，因此不显示任何数字）";

/** 顶部合计那一行：`在飞 a · 待机 b · 静默 c`（读不到就说读不到 + 一句原因，不显示 0）。 */
export interface StateSummary {
  /** 那一行文字。 */
  text: string;
  /** 未读到几个（`-1` = 合计整格没读到，页面不该显示任何数字）。 */
  unknown: number;
  /** 活跃（非静默）= 在飞 + 待机；`null` = 没读到（不许折成 0）。 */
  active: number | null;
  /** 四档之和；`null` = 没读到。 */
  total: number | null;
  /** 为什么没读到 / 哪两格对不上（空串 = 读到了、也对得上）。 */
  reason: string;
}

/** 顶部合计：优先用后端那一格（`view.states`），没有就按树上的节点现算并标明。
 *
 * 三档文案与"不显示 0"都在这里收口：读不到合计时给的是"未读到 + 原因"，
 * 而不是 0 / 0 / 0 —— 后者会被读成"全都收工了"，而它恰恰可能是"没查成"。
 *
 * ## 为什么四档必须都是数字才算读到了
 * 后端把四格声明成 `number | null`，`null` 是"没读到"（不是 0）。所以这里**不许**
 * 用 `?? 0` 把缺格补齐：那一句会把"没读到"当场折成"读到了、它是 0"，而这一批要修的
 * 正是这个折叠。缺一格 ⇒ 整行走"未读到 + 原因"那一档。
 *
 * ## 活跃与合计：以定义为准，不以某一格为准
 * `active` = 在飞 + 待机、`total` = 四档之和都是**定义**；后端那两格只是同一件事的
 * 另一份读数。两者对不上时按定义显示，并把"对不上"写进 `reason`（读数互相矛盾也是
 * 读数的一部分，静默地挑一个用等于把矛盾藏起来）。
 */
export function stateSummary(view: RosterView, rows: TreeRow[], unreached: RosterNode[]): StateSummary {
  const raw: unknown = view.states;
  if (isRecord(raw)) {
    const reason = asText(raw["reason"]);
    if (raw["checked"] === true) {
      const flying = asNumber(raw["flying"]);
      const standby = asNumber(raw["standby"]);
      const silent = asNumber(raw["silent"]);
      const unknown = asNumber(raw["unknown"]);
      if (flying === null || standby === null || silent === null || unknown === null) {
        const hole = reason === ""
          ? "合计那一格说它读到了，但四档里有不是数字的格（null = 没读到，不是 0）"
          : reason;
        return { text: STATES_UNREADABLE_TEXT, unknown: -1, active: null, total: null, reason: hole };
      }
      const notes: string[] = [];
      const active = flying + standby;
      const activeRaw = asNumber(raw["active"]);
      if (activeRaw !== null && activeRaw !== active) {
        notes.push(`合计里的 active（${activeRaw}）不等于在飞 + 待机（${active}）`
          + "⇒ 这一行按定义显示");
      }
      const total = flying + standby + silent + unknown;
      const totalRaw = asNumber(raw["total"]);
      if (totalRaw !== null && totalRaw !== total) {
        notes.push(`合计里的 total（${totalRaw}）不等于四档之和（${total}）⇒ 这一行按四档之和显示`);
      }
      let text = `在飞 ${flying} · 待机 ${standby} · 静默 ${silent}`;
      if (unknown > 0) {
        text += ` · 未读到 ${unknown}`;
      }
      return {
        text,
        unknown,
        active,
        total,
        reason: [reason, ...notes].filter((one) => one !== "").join("；"),
      };
    }
    return {
      text: STATES_UNREADABLE_TEXT,
      unknown: -1,
      active: null,
      total: null,
      reason: reason === "" ? "这一份读数里 states 那一格说它没查成，但没写原因" : reason,
    };
  }
  // 旧后端没有 `states` 这一格 ⇒ 按树上的节点现算，并在文字里说清是现算的。
  const states: AgentState[] = [];
  for (const row of flattenRows(rows)) {
    states.push(row.node === null ? "unknown" : asAgentState(row.node.state));
  }
  for (const node of unreached) {
    states.push(asAgentState(node.state));
  }
  const tally = tallyStates(states);
  let text = `在飞 ${tally.flying} · 待机 ${tally.standby} · 静默 ${tally.silent}`;
  if (tally.unknown > 0) {
    text += ` · 未读到 ${tally.unknown}`;
  }
  return {
    text,
    unknown: tally.unknown,
    active: tally.active,
    total: tally.total,
    reason: "后端没给三态合计 ⇒ 这一行按树上的节点现算（节点自己的 state 那一格说它没读到）",
  };
}
