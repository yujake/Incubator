/*
 * sha 一致性读数：只显示是否一致，不显示 sha 值本身。
 *
 * ## 为什么是一个组件
 * 三处以上要用同一个词表（产物台账、台账对账、证明级、实验的代码、落盘文件），
 * 而"三档怎么显示"是同一个判据：`match` / `mismatch` / `unknown`。散落成几份渲染，
 * 就会有一处把 `unknown` 印成"不一致"——那时读的人会去追一份根本不存在的差异。
 *
 * ## 三档不许折平
 * `unknown` 说的是"没有第二份可比"（文件不在盘上、台账没记 sha、这一格不适用），
 * 它与"不一致"是两件事。所以三档各有各的词与颜色，副标题（`note`）说清
 * "比的是与哪一份"，hover 里也带着它。
 *
 * ## 不印半截哈希
 * 半截哈希既不能核也不能读，所以这里一个十六进制字符都不印，只印那个词；
 * 后端仍然把 sha 留在数据里（凭据要能复核）。
 */
import { Badge } from "./Badge";

/** 与后端 `readers.SHA_MATCH` 同一批取值（三档，不是布尔）。 */
export const CONSISTENCY_MATCH = "match";
export const CONSISTENCY_MISMATCH = "mismatch";

/** 三档的显示词（这是"渲染"的唯一落点）。 */
export function consistencyText(value: string): string {
  if (value === CONSISTENCY_MATCH) {
    return "一致";
  }
  if (value === CONSISTENCY_MISMATCH) {
    return "不一致";
  }
  return "unknown（没得比）";
}

/** 三档的视觉档（一致绿 / 不一致红 / 没得比灰）。 */
export function consistencyKind(value: string): string {
  if (value === CONSISTENCY_MATCH) {
    return "badge-pass";
  }
  return value === CONSISTENCY_MISMATCH ? "badge-fail" : "badge-unknown";
}

/** 一格一致性读数：`note` 说清"比的是与哪一份"（hover 里也带着它）。 */
export function Consistency(props: { value: string; note: string }) {
  const text = consistencyText(props.value);
  return (
    <span class="consistency" title={`${text} —— 比的是${props.note}`}>
      <Badge kind={consistencyKind(props.value)} text={text} />
    </span>
  );
}
