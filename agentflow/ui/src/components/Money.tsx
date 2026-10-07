/*
 * 花销读数：`usd === null` 显 `unknown`（不是 $0.00），`unknownCalls > 0` 附一句
 * "（N 次算不出价钱）"。这两条都是三态纪律在数字上的落点：
 * "算不出来"不许折成"花了零"。
 */
export interface MoneyProps {
  usd: number | null;
  unknownCalls: number;
}

export function Money(props: MoneyProps) {
  const amount = props.usd === null ? "unknown" : `${props.usd.toFixed(6)} USD`;
  return (
    <span class="mono">
      {amount}
      {props.unknownCalls > 0 ? `（${props.unknownCalls} 次算不出价钱）` : ""}
    </span>
  );
}
