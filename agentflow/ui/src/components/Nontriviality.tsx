/*
 * 命题的非平凡度档位（业主 2026-10-23 原话：「对于命题的显示要标注非平凡度等级」）。
 *
 * ## 五档 + 一档"未判"，不是四档 + 一个 0
 * `T0` 是 2026-10-23 起是真的档位（基础定理或初步结论），与 T1–T4 同一根轴；
 * 而"没人判过"是另一件事（`nontriviality: null` + 空 label）。所以这一格：
 *
 * - 有档位 ⇒ 印 `T0`…`T4`（显示名由后端 `secretary.nontriviality_label` 给，
 *   这一层不自己拼 `T${level}`，免得两处各拼一份）；
 * - 没有档位 ⇒ 印"未判"。不是 T0：把"没人判过"印成 T0，就是拿一条基础定理
 *   冒充一次没做的判断 —— 而这两件事在盘上分得很开（`level is None` vs `level == 0`）。
 *
 * ## hover 给档位的语义
 * `meaning` 是后端 `_NONTRIVIALITY_MEANINGS` 的那一句（T0 基础定理或初步结论、
 * T1 有一定价值的非平凡结论、…）。判不了时它是空串 —— 那时 tooltip 说"未判，
 * 不是 T0"，绝不编一句档位说明。
 */
import { Badge } from "./Badge";

/** 判不了的那一档在页面上的写法（三态里的第三态，不是 T0）。 */
export const TIER_UNJUDGED = "未判";

/** 一格的显示词：有档位印档位，没有就印"未判"。 */
export function tierText(label: string): string {
  return label === "" ? TIER_UNJUDGED : label;
}

/** 三档的视觉档：判不了灰、T0 灰蓝（"平凡但真"，不是缺陷）、T1–T4 绿。 */
export function tierKind(label: string, tri: string): string {
  if (tri !== "computed" || label === "") {
    return "badge-unknown";
  }
  return label === "T0" ? "badge-na" : "badge-pass";
}

/** 一格的 hover 说明（判不了时明说"不是 T0"）。 */
export function tierNote(label: string, meaning: string, tri: string): string {
  if (tri !== "computed" || label === "") {
    return "这一条还没有档位读数：未判（不是 T0 —— 没人判过与基础定理是两件事）";
  }
  return meaning === "" ? label : meaning;
}

/** 一格非平凡度：`label` 是后端给的 `T0`…`T4`，空串 = 未判。 */
export function Nontriviality(props: { label: string; meaning: string; tri: string }) {
  const text = tierText(props.label);
  return (
    <span class="nontriviality" title={tierNote(props.label, props.meaning, props.tri)}>
      <Badge kind={tierKind(props.label, props.tri)} text={text} />
    </span>
  );
}
