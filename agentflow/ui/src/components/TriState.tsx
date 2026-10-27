/*
 * 三态的视觉形态（裁定 N1：两套词表，一个组件里映射，字符串不许互相顶替）。
 *
 * 两套词表都是后端真在用的，各有各的语义，所以谁都不改名：
 *
 * | 词表 | 取值 | 出处 |
 * |---|---|---|
 * | `Tri` | `computed` / `unreadable` / `not_applicable` | `reviewaccept` 那一族读数（六个面都用它） |
 * | `ReportTri` | `ok` / `missing` / `unknown` | `webui/state.py` 的 `_read_report` |
 *
 * 两者都落到三种视觉态上，但**映射不同**，因为语义不同：
 * `missing`（交付说明还没写）是合法初态，灰；`unreadable`（在盘上但读不出来）
 * 是没查成，黄。把它们合成一个词就等于把"没有"与"没读到"折成一档 ——
 * 那正是本项目三态纪律要分开的那条线。
 */
import { Badge } from "./Badge";
import type { ReportTri as GenReportTri, Tri as GenTri } from "../types";

/*
 * 两套词表的**声明**只许有一份：真身在 `types.ts`（生成物，字段名与取值逐字来自
 * 后端）。这里此前各写了一份同形的字面量联合 —— 两处同形时 `tsc` 一声不吭，
 * 后端把三态词表改掉之后，生成物会跟着变，而这一份不会，页面就会画出不存在的档。
 * 所以这里改成从生成物导入再转发：多出来的一处定义没了，`tsc` 也就恢复了判据作用。
 */
export type Tri = GenTri;
export type ReportTri = GenReportTri;

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
  ok: "已读出",
  unknown: "未读出",
  na: "不适用",
};

const BADGE: Record<Visual, string> = {
  ok: "badge-pass",
  unknown: "badge-unknown",
  na: "badge-na",
};

/** 一个词落进哪一档视觉态（页面要单独显示徽标时用它；映射只有这一处）。 */
export function visualOf(tri: Tri | ReportTri | string): Visual {
  return VISUAL[tri] ?? "unknown";
}

/** 这个三态词是不是"没查成"（页面的静默判定统一走它，不各写一份比较）。 */
export function isUnreadable(tri: Tri | ReportTri | string): boolean {
  return visualOf(tri) === "unknown";
}

export interface TriStateProps {
  tri: Tri | ReportTri;
  reason?: string;
  label?: string;
}

export function TriState(props: TriStateProps) {
  const visual: Visual = visualOf(props.tri);
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
