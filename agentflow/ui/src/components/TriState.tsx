/*
 * 三态的视觉形态（裁定 N1：两套词表，一个组件里映射，字符串不许互相顶替）。
 *
 * 两套词表都是后端真在用的，各有各的语义，所以谁都不改名：
 *
 * | 词表 | 取值 | 出处 |
 * |---|---|---|
 * | `Tri` | `computed` / `unreadable` / `not_applicable` | `reviewaccept` 那一族读数 |
 * | `ReportTri` | `ok` / `missing` / `unknown` | `webui/state.py` 的 `_read_report` |
 *
 * 两者都落到三种视觉态上，但**映射不同**，因为语义不同：
 * `missing`（交付说明还没写）是合法初态，灰；`unreadable`（在盘上但读不出来）
 * 是没查成，黄。把它们合成一个词就等于把"没有"与"没读到"折成一档 ——
 * 那正是本项目三态纪律要分开的那条线。
 */
import { Badge } from "./Badge";

export type Tri = "computed" | "unreadable" | "not_applicable";
export type ReportTri = "ok" | "missing" | "unknown";

/** 视觉档（只有三种；两套词表都往这里投影）。 */
export type Visual = "ok" | "unknown" | "na";

const VISUAL: Record<string, Visual> = {
  computed: "ok",
  unreadable: "unknown",
  not_applicable: "na",
  ok: "ok",
  missing: "na",
  unknown: "unknown",
};

const WORD: Record<Visual, string> = {
  ok: "算出来了",
  unknown: "没查成",
  na: "用不着",
};

const BADGE: Record<Visual, string> = {
  ok: "badge-pass",
  unknown: "badge-unknown",
  na: "badge-na",
};

export interface TriStateProps {
  tri: Tri | ReportTri;
  reason?: string;
  label?: string;
}

export function TriState(props: TriStateProps) {
  const visual: Visual = VISUAL[props.tri] ?? "unknown";
  const text = props.label === undefined ? WORD[visual] : `${props.label}：${WORD[visual]}`;
  return (
    <span class="tri">
      <Badge kind={BADGE[visual]} text={text} />
      {props.reason === undefined || props.reason === "" ? null : (
        <span class="tri-reason">{props.reason}</span>
      )}
    </span>
  );
}
