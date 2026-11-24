/*
 * 义务面板的纯派生（不 import preact、不碰 DOM）：标题、空态、全收口判定。
 *
 * 为什么要单独一个文件：这三件事以前是写死在 JSX 里的字面量（族名列表、族数、
 * "这几族的板项都收口了"），产品侧加第四族 `d-handoff` 之后它们逐字变成了假话。
 * 把派生拿出来之后：族名从 payload 的 `families[]` 现取（不写死），空态由"四族
 * open 全 0"判（不是"表里 0 行"——只有 d-handoff 开着时表里也有行）。
 *
 * 这里刻意不依赖 `types.ts` 的具体接口：只要求 `{name, open}`，于是判据可以在
 * node 里直接喂人造数组（四族 / 少一族 / 空数组）验边界，不必起后端。
 */
export interface ObligationFamilyLike {
  name: string;
  open: number | null;
}

/** 面板标题：族名逐个来自 payload（空 payload 时只写"义务"，不编族名）。 */
export function familiesTitle(families: readonly ObligationFamilyLike[]): string {
  if (families.length === 0) {
    return "义务";
  }
  return `义务（${families.map((one) => one.name).join(" / ")}）`;
}

/** 四族都收口了没有：`open` 全 0 且至少有一族（没有族不是"全收口"）。 */
export function allClosed(families: readonly ObligationFamilyLike[]): boolean {
  return families.length > 0 && families.every((one) => one.open === 0);
}

/**
 * 表里 0 行时那句话。
 *
 * 只有"每一族的 open 都是 0"才允许说"都收口了"；否则说清"0 行与某一族的 open
 * 对不上，先查那一边"—— 改前这里只判"rows 是空数组"，于是只有 `d-handoff` 开着
 * （它当时根本不在族表里）时，页面会印"这几族的板项都收口了"，看着像全清。
 */
export function emptyWord(families: readonly ObligationFamilyLike[]): string {
  if (allClosed(families)) {
    return `这 ${families.length} 族的板项都收口了（读到了，里面是 0 行）。`;
  }
  const open = families.filter((one) => one.open !== 0).map((one) => one.name);
  return `表里 0 行，但 ${open.join(" / ") || "族表"} 的 open 不是 0`
    + "（读数自相矛盾：先查那一边，不把它读成「都收口了」）。";
}
