/*
 * 花销读数：`usd === null` 显 `unknown`（不是 $0.00），`unknownCalls > 0` 附一句
 * "（N 次算不出价钱）"。这两条都是三态纪律在数字上的落点：
 * "算不出来"不许折成"花了零"。
 *
 * 可选的三栏（`calls` / `tokensIn` / `tokensOut`）也是三态：`null` 显 `unknown`。
 * Run 页把"检查点"与"事件求和"两个来源并排摆，用的就是这个组件（两次渲染）。
 */
export interface MoneyProps {
  usd: number | null;
  unknownCalls: number;
  calls?: number | null;
  tokensIn?: number | null;
  tokensOut?: number | null;
  label?: string;
}

/** 一个数字读数的通用写法：`null` ⇒ `unknown`（不折成 0）。 */
function num(value: number | null | undefined): string {
  return value === null || value === undefined ? "unknown" : String(value);
}

export function Money(props: MoneyProps) {
  const amount = props.usd === null ? "unknown" : `${props.usd.toFixed(6)} USD`;
  return (
    <span class="mono">
      {props.label === undefined ? null : `${props.label} `}
      {amount}
      {props.unknownCalls > 0 ? `（${props.unknownCalls} 次算不出价钱）` : ""}
      {props.calls === undefined ? null : ` · 调用 ${num(props.calls)} 次`}
      {props.tokensIn === undefined && props.tokensOut === undefined
        ? null
        : ` · tokens 进 ${num(props.tokensIn)} / 出 ${num(props.tokensOut)}`}
    </span>
  );
}
