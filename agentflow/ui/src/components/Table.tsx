/*
 * 泛型表：`columns[].key` 受 `keyof T` 约束 ⇒ 列名不可能写成不存在的键。
 * 这是"类型层对齐"的最便宜一档（对齐判据 E：`tsc --noEmit`）。
 */
export interface Column<T> {
  key: keyof T;
  title: string;
}

export interface TableProps<T> {
  rows: T[];
  columns: Array<Column<T>>;
  empty: string;
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
              <td key={String(col.key)}>{String(row[col.key])}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
