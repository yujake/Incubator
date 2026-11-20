/*
 * 命题的非平凡度档位。
 *
 * ## 五档 + 两档"没有档位"，不是四档 + 一个 0
 * `T0`（基础定理或初步结论）与 T1–T4 同一根轴；而"没有档位"其实是**两件不同的事**：
 *
 * - `不适用`：这一问对它天然不成立（概念 / 定义行没有证明正文，结构上不需要判）；
 * - `未判`：该判而没判（台账里没有 / 记的是判不了 / 读不出来）。
 *
 * 折平它们的后果：真机 `projects/mp3-r3` 的 30 条概念行与 1 条真的没判过的命题
 * 在屏幕上都是"未判"——读者没有任何办法把"再判一次也不会有结论"与"再判一次就会有
 * 结论"分开（`draft/187` P1-2 / A2）。
 *
 * ## 页面印的那个词由后端给（`nontriviality_word`）
 * 三个词（`T0`…`T4` / `不适用` / `未判`）只有一个判断点：`readers._statement_tier_reading`
 * 的 `word`。这一层**不自己拼**——拼一份就会在两处各判一次"该不该判"。
 * `nontriviality_label` 仍然只装档位名（空串 = 没有档位），它是"有没有档位"那个判据，
 * 不许被一个显示词抹掉。
 *
 * ## hover 给档位的语义
 * `meaning` 是后端 `_NONTRIVIALITY_MEANINGS` 的那一句。判不了时它给空串 ——
 * 那时 tooltip 说"未判，不是 T0"，绝不编一句档位说明。
 */
import { Badge } from "./Badge";

/** 判不了的那一档在页面上的写法（三态里的第三态，不是 T0）。 */
export const TIER_UNJUDGED = "未判";

/** 这一问对它不成立（概念 / 定义行没有证明正文）。与"未判"是两件事。 */
export const TIER_NOT_APPLICABLE = "不适用";

/** 一格的显示词：有档位印档位，没有就印"未判"（老调用点 / 没有 word 时的兜底）。 */
export function tierText(label: string): string {
  return label === "" ? TIER_UNJUDGED : label;
}

/**
 * 页面**真正印出来**的那个词：后端的 `word` 优先（`T0`…`T4` / `不适用` / `未判`），
 * `word` 是空串（旧后端）时退回 `tierText(label)` —— 那时至少不会把"没有档位"
 * 印成一个空单元格。
 */
export function tierWord(word: string, label: string): string {
  return word === "" ? tierText(label) : word;
}

/** 三档的视觉档：不适用 / 判不了灰、T0 灰蓝（"平凡但真"，不是缺陷）、T1–T4 绿。 */
export function tierKind(label: string, tri: string): string {
  if (tri === "not_applicable") {
    return "badge-na";
  }
  if (tri !== "computed" || label === "") {
    return "badge-unknown";
  }
  return label === "T0" ? "badge-na" : "badge-pass";
}

/** 一格的 hover 说明（判不了时明说"不是 T0"；不适用时明说"这一问不成立"）。 */
export function tierNote(label: string, meaning: string, tri: string): string {
  if (tri === "not_applicable") {
    return "这一问对它不成立（概念 / 定义行没有证明正文）：不适用 —— 不是「未判」，也不是 T0";
  }
  if (tri !== "computed" || label === "") {
    return "这一条还没有档位读数：未判（不是 T0 —— 没人判过与基础定理是两件事）";
  }
  return meaning === "" ? label : meaning;
}

/** 一格非平凡度：`word` 是后端给的显示词，`label` 是 `T0`…`T4`、空串 = 没有档位。 */
export function Nontriviality(props: { word: string; label: string; meaning: string; tri: string }) {
  const text = tierWord(props.word, props.label);
  return (
    <span class="nontriviality" title={tierNote(props.label, props.meaning, props.tri)}>
      <Badge kind={tierKind(props.label, props.tri)} text={text} />
    </span>
  );
}
