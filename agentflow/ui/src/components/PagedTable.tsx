/*
 * 分页 + 搜索表（大台账不许一次性渲染）。
 *
 * 为什么要有它：真机 `tasks` 已经 223 行、`secretary` 380 行、`ledger` 173 行，
 * 工作区跑久了还会更长。整表一次性进 DOM 有两个后果 —— 首屏卡，且读的人在
 * 几百行里找不到自己那一行。所以这一层只做两件事：按页切片（默认 50 行）与
 * 在表格的列值里做子串搜索。
 *
 * 小表不动：`rows.length <= pageSize` 时直接渲染原 `Table`，不显示搜索框与页码 ——
 * 十几行的表上加一个搜索框只是噪声。
 *
 * 三态不变：空表仍然走 `empty` 那句话（"读到了、里面是 0 行"）；搜索没有命中
 * 与"表里没有行"是两句话，不许折成一句（前者是用户输入的结果，后者是读数）。
 */
import { useMemo, useState } from "preact/hooks";

import { Table } from "./Table";
import type { Column } from "./Table";

/** 一页多少行（默认）。 */
export const DEFAULT_PAGE_SIZE = 50;

export interface PagedTableProps<T> {
  rows: T[];
  columns: Array<Column<T>>;
  /** 空态那句话（"读到了，里面是 0 行"）。 */
  empty: string;
  /** 一页多少行（缺省 `DEFAULT_PAGE_SIZE`）。 */
  pageSize?: number;
  /** 搜索框的提示词（缺省按行数自动写）。 */
  searchPlaceholder?: string;
}

/** 一行在搜索里参与匹配的文本：只取这一行在表格里真的会显示的那几列。 */
function searchBlob<T>(row: T, columns: Array<Column<T>>): string {
  const parts: string[] = [];
  for (const col of columns) {
    const value = (row as Record<string, unknown>)[String(col.key)];
    if (value === null || value === undefined) {
      continue;
    }
    // 长正文（detail / body）截断参与匹配：搜索要的是"找得到"，不是全文索引。
    parts.push(String(value).slice(0, 300));
  }
  return parts.join(" ").toLowerCase();
}

export function PagedTable<T>(props: PagedTableProps<T>) {
  const size = props.pageSize === undefined ? DEFAULT_PAGE_SIZE : props.pageSize;
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const needPager = props.rows.length > size;
  const word = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    if (!needPager || word === "") {
      return props.rows;
    }
    return props.rows.filter((row) => searchBlob(row, props.columns).includes(word));
  }, [props.rows, props.columns, word, needPager]);
  if (!needPager) {
    return <Table rows={props.rows} columns={props.columns} empty={props.empty} />;
  }
  const pages = Math.max(1, Math.ceil(filtered.length / size));
  const current = Math.min(page, pages - 1);
  const start = current * size;
  const shown = filtered.slice(start, start + size);
  const end = start + shown.length;
  return (
    <div class="paged">
      <div class="card-head">
        <label class="opt">
          <span>搜索</span>
          <input
            class="input"
            type="text"
            value={query}
            placeholder={
              props.searchPlaceholder === undefined
                ? `在 ${props.rows.length} 行里搜（只搜这一张表显示的列）`
                : props.searchPlaceholder
            }
            onInput={(ev) => {
              setQuery(ev.currentTarget.value);
              setPage(0);
            }}
          />
        </label>
        <span class="readings">
          {filtered.length === 0
            ? "0 行"
            : `第 ${start + 1}–${end} 行 / 共 ${filtered.length} 行`}
          {filtered.length === props.rows.length
            ? ""
            : `（全表 ${props.rows.length} 行）`}
        </span>
        <button
          class="btn"
          type="button"
          disabled={current <= 0}
          onClick={() => {
            setPage(Math.max(0, current - 1));
          }}
        >
          上一页
        </button>
        <button
          class="btn"
          type="button"
          disabled={current >= pages - 1}
          onClick={() => {
            setPage(Math.min(pages - 1, current + 1));
          }}
        >
          下一页
        </button>
      </div>
      {filtered.length === 0 ? (
        <div class="empty">
          没有匹配的行（搜索词：{query}）—— 这是搜索结果，不是"表里没有行"。
        </div>
      ) : (
        <Table rows={shown} columns={props.columns} empty={props.empty} />
      )}
    </div>
  );
}
