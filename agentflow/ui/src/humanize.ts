/*
 * 把后端送来的"人话"里夹着的 Python 表达式读回人话。
 *
 * ## 为什么需要这一层
 * `/api/errors` 的 `problems[].detail` 有一句是后端 `readouts.errors_readout` 用
 * `f"…：{loose}…"` 拼的，而 `loose` 是个 dict ⇒ 上屏就是
 * `结构判据认不出族的那几条没有猜类目：{'tool': 33, 'verdict': 1}（…）`
 * —— 读者看到的是 Python 表达式，不是读数（`draft/187` P2-3）。
 *
 * 那一句的落点在 `readouts.py`（CLI 与网页共用的读数层，不在网页这一侧），所以这里
 * 只做**呈现**：认得出来的 dict repr 译成"键 值、键 值"；认不出来（不是 dict repr /
 * 有一格不像 `'键': 值`）就**整块原样留着** —— 半译比不译更容易读错。
 *
 * 纯函数、零依赖：判据用 node 真跑它（`tests/test_webui_pages_show_the_words_the_backend_gives.py`）。
 */

/** 把一段人话里的 Python `dict` repr 读成人话（`{'tool': 33, 'verdict': 1}` ⇒ `tool 33、verdict 1`）。 */
export function humanDetail(text: string): string {
  return text.replace(/\{[^{}]*\}/g, (whole) => {
    if (!/'\s*:/.test(whole)) {
      return whole; // 不是 Python dict repr（`{}` / JSON 的空对象）⇒ 原样
    }
    const entries: string[] = [];
    for (const part of whole.slice(1, -1).split(/,\s*/)) {
      const one = part.match(/^'([^']*)'\s*:\s*(.+)$/);
      if (one === null) {
        return whole; // 有一格认不出 ⇒ 整块原样（半译比不译更容易读错）
      }
      entries.push(`${one[1]} ${one[2]}`);
    }
    return entries.join("、");
  });
}
