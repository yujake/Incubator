/*
 * 泛型表：`columns[].key` 受 `keyof T` 约束 ⇒ 列名不可能写成不存在的键。
 * 这是"类型层对齐"的最便宜一档（对齐判据 E：`tsc --noEmit`）。
 *
 * 三态纪律在单元格上也成立：`null` / `undefined` / 空串一律渲染成 `unknown`
 * （不是 `0`、不是空、不是 `false`）。"这一格没读到"与"这一格是零"在读数上
 * 必须分得开 —— 后端把读不到的东西写成 `None`，前端不许在最后一跳把它折平。
 */
import type { ComponentChildren } from "preact";

export interface Column<T> {
  key: keyof T;
  title: string;
  /** 自定义单元格（不给就按 `cell()` 的通用读法渲染）。 */
  render?: (row: T) => ComponentChildren;
}

export interface TableProps<T> {
  rows: T[];
  columns: Array<Column<T>>;
  /** 空态那句话（必须是"读到了，里面是 0 行"，不是"没查成"）。 */
  empty: string;
}

/** 一个单元格的通用读法：读不到 ⇒ `unknown`（三态，不折成 0 / 空 / false）。 */
export function cell(value: unknown): string {
  if (value === null || value === undefined) {
    return "unknown";
  }
  if (typeof value === "string") {
    return value === "" ? "unknown" : value;
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (Array.isArray(value)) {
    return value.length === 0 ? "（空表）" : value.map((x) => cell(x)).join("、");
  }
  if (typeof value === "object") {
    // R90：对象不许落到 `String(value)` —— 那会印出 `[object Object]`（本机实测：
    // Mathlib 探针那一格就是这样上的屏）。JSON 至少是真的读数，读得懂。
    return JSON.stringify(value);
  }
  return String(value);
}

/** 一格里放的是**别人写的 markdown 正文**时用它：把强调记号去掉再上屏（R93）。
 *
 * 为什么要有这一档：交接手稿的 `summary` / `body` 是各角色自己写的 markdown
 * （本机实测：产物页那两列里就有 `**…**`）。表格里印 markdown 记号 = 读者看到一堆
 * 星号；而"去掉记号"只是**排版**选择，正文一个字都不改（盘上那份原件照旧）。
 * 与 `cell()` 的分工：`cell()` 管三态（读不到 ⇒ `unknown`），`plain()` 管排版。
 */
export function plain(value: unknown): string {
  return cell(value).replace(/\*\*([^*\n]+)\*\*/g, "$1");
}

export function Table<T>(props: TableProps<T>) {
  if (props.rows.length === 0) {
    return <div class="empty">{props.empty}</div>;
  }
  return (
    <table class="grid">
      <thead>
        <tr>
          {props.columns.map((col) => (
            <th key={String(col.key)}>{col.title}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {props.rows.map((row, i) => (
          <tr key={i}>
            {props.columns.map((col) => (
              <td key={String(col.key)}>
                {col.render === undefined ? cell(row[col.key]) : col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** 一格"按 X 拆解"的桶（`tokenmeter.by_role` / `by_scope` 的一格，四格读数都收成串）。 */
export interface BucketRow {
  name: string;
  usd: string;
  tokens: string;
  entries: string;
  attempts: string;
}

/**
 * 把 `{名字: {tokens, usd, entries, attempts}}` 摊成表格行。
 *
 * 为什么抽到这里（2026-10-27 业主裁定 W6）：`pages/Live.tsx` 与 `pages/Budget.tsx`
 * 此前各写了一份 `buckets()`，而 Live 那份少了 `attempts` 一格 —— 同一件事两份实现，
 * 漂了没有任何地方会报错（两页各印一张看起来都正常的表）。四格都从 `cell()` 走，
 * 于是"读不到"仍是 `unknown`，不会被折成 0。
 */
export function buckets(rec: Record<string, unknown>): BucketRow[] {
  return Object.keys(rec)
    .sort()
    .map((name) => {
      const one = (rec[name] ?? {}) as Record<string, unknown>;
      return {
        name,
        usd: cell(one.usd),
        tokens: cell(one.tokens),
        entries: cell(one.entries),
        attempts: cell(one.attempts),
      };
    });
}
