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

/**
 * 计数 / 数字读数的唯一写法（鲁棒 h：各页不许各写一套）。
 *
 * `null` / `undefined` ⇒ `unknown` —— "没读到"不许折成 0。页面要显示别的词
 * （例如"没读到"）时也只能在这里改一次，不许在页面里再抄一份。
 */
export function formatCount(value: number | null | undefined): string {
  return num(value);
}

/** 文本读数的唯一写法：空串 ⇒ `unknown`（"没写"与"没读到"在读数层是同一条口径）。 */
export function formatText(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? "unknown" : value;
}

/**
 * 一笔金额的写法（`Money` 自己也用它）。
 *
 * 金额的写法只留这一处：散在各页里，同一个读数就会在「预算」页与「一趟详情」
 * 各写各的。页面要"只有字符串"的场合（`impact` 提示、表格里的一格）也走它。
 */
export function formatUsd(value: number | null | undefined): string {
  return value === null || value === undefined ? "unknown" : `${value.toFixed(6)} USD`;
}

export function Money(props: MoneyProps) {
  const amount = formatUsd(props.usd);
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
