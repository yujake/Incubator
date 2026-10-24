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
  return {
    task_id: taskId,
    name: asText(value["name"]),
    role: asText(value["role"]),
    // 没有层号的节点按第 1 层算：折叠口径只会"多展开"，不会把整支藏在下面。
    depth: asNumber(value["depth"]) ?? 1,
    parent_task_id: asText(value["parent_task_id"]),
    parent_name: asText(value["parent_name"]),
    children: asChildren(value["children"]),
    retired: value["retired"] === true,
    retired_branch: asText(value["retired_branch"]),
    brief: asText(value["brief"]),
    brief_source: asText(value["brief_source"]),
    surface: asText(value["surface"]),
    status: asText(value["status"]),
    task_found: value["task_found"] === true,
    in_flight: asNumber(value["in_flight"]),
    inbox: asInbox(value["inbox"]),
  };
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
