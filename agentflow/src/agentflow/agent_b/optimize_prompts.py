"""优化侧按 `kind` 分派的提示词注册表（业主 2026-11-14 的「优化侧一般性规定」）。

## 为什么单独一个模块、不放 `agent_prompts.py`

`agent_prompts.py` 挂着 `PROMPT_VERSION` 与十格冻结摘要（`_FROZEN_PROMPT_DIGESTS`
按段渲染现算）：往那里加一段，就得同轮抬版本、重冻摘要，而这一批改的是"优化轮发什么
提示词"，不是角色 system 提示词的段结构。所以注册表住这里，由批量开稿
（`B.open_polish_copy` 的 `open_optimization_drafts`）随每一份新稿发出去。

## 三档从哪来（不是拍脑袋写的）

- `theorem`：从 F 侧提示词派生 —— F 的活是"把证明写清楚、一步一理由、假设齐全"；
  优化目标同向，但不许改命题、也不许新增没证过的步骤；
- `exhaustive`：从 E 侧提示词派生 —— 穷举证明的说服力全在"搜索空间 + 穷尽判据 +
  边界处理"三件套（`numericproof` / `exhaustionreport`），优化只能把这三分写得更可核，
  不许把抽样说成穷尽；
- `well_defined`：待设计（业主逐字「良定义类需再做设计」）。这一档今天只返回
  `status="draft_pending"` 与一句"别拿 F 侧那套套上去"，不返回任何可执行的提示词正文
  —— 把"还没设计"写成"有提示词"就是伪造能力。

## 判"优化好了"的口径

每一档都带 `done_when`：它不是"B 自己觉得写清楚了"，而是这条链上可复核的三件 ——
正文改了、V 三转签盖在新正文 sha 上、收录那一笔把 `optimized` 记成 true。
真身分别是 `vsigns.sign_reading` / `evidencebits.optimized_signature` 与
`agent_b.ingest_manuscript` 的优化线路（`path_group>=1`）。
"""
from __future__ import annotations

from typing import Any

#: 三档的名字（与 `closing.OPTIMIZATION_PROMPT_CLASSES` 逐字一致；词表只有这两处，
#: 判据 `tests/test_optimization_candidates_and_wash_scope.py` 对拍）。
PROMPT_CLASSES: tuple[str, ...] = ("theorem", "exhaustive", "well_defined")

#: `done_when` 里反复出现的那一句（三档共用）：优化不是「B 说改好了」。
_DONE_COMMON = (
    "判「优化好了」只看三件可复核的事：① 正文真的改了（与源稿的 `## 证明` 正文 sha "
    "不同）；② V 的签盖在**新**正文的 sha 上（`vsigns.sign_reading` 的 "
    "`state == \"signed\"`，签到位才算）；③ 收录那一笔走优化线（`ingest_manuscript` 的 "
    "`path_group >= 1`）并把这一份记成 `optimized=true`（`evidencebits."
    "optimized_signature`）。缺任何一件都不算优化好了 —— 没有签的「改好了」只是草稿。")

PROMPTS: dict[str, dict[str, Any]] = {
    "theorem": {
        "key": "theorem",
        "status": "ready",
        "goal": (
            "把这份定理证明改得**更清楚、更短、更规范**：每一步写清用的是哪条假设 / 哪条"
            "已证命题；省掉重复的过渡句与自我复述；术语与记号前后一致。**不许改变命题"
            "本身**（假设、结论、量词一个都不动），**不许新增没有证过的步骤**，也不许把"
            "「显然」当成理由。"),
        "inputs": (
            "你手上是 `manuscripts/B/b-proof-<B稿号>.md`：`## 命题`（原命题，只读）+ "
            "`## 证明`（原证明的逐字复制版）+ `## 依赖`（引用了哪些在册命题）。"
            "源稿的 V 签已经被清掉 —— 这一份是未签的新稿，改完要重新派 V。"),
        "done_when": _DONE_COMMON,
        "prompt": (
            "你在做「证明优化」，不是重证。对象是这条命题的原证明（见 `## 证明`）。\n"
            "目标按这个次序：① 每步给出理由（引哪条假设 / 哪条已证命题 / 哪条定义）；"
            "② 删掉重复与自我复述，句子能短就短；③ 记号与术语前后一致；"
            "④ 保留原有的证明骨架与证明路线，不许换一条没写过的路线。\n"
            "硬边界：命题（`## 命题`）一个字节不动；不新增没有理由的步骤；"
            "不把「显然 / 易得」当理由；不删依赖（`## 依赖` 只增不删，删之前先确认那一"
            "步真的不用了）。\n"
            "改完把新正文送去 V 拿签；V 退回就按退回的那一步补，不要整篇重写。\n"
            + _DONE_COMMON),
    },
    "exhaustive": {
        "key": "exhaustive",
        "status": "ready",
        "goal": (
            "把这份穷举证明的**证明栏**写得可核：① 搜索空间多大（对象的个数 / 参数范围，"
            "与程序里的循环对得上）；② 用了哪些对称性 / 剪枝、为什么它们不丢解；"
            "③ 边界怎么处理（端点、退化情形）。**不许把抽样说成穷尽**，不许改程序路径，"
            "也不许把穷举论证改写成「由计算可知」。"),
        "inputs": (
            "证明栏第 ① 段是程序路径（`experiments.code_path`，只读、不许改），第 ③ 段"
            "是穷举论证（要优化的就是这一段）。判据只认三件套：搜索空间 / 穷尽判据 / "
            "边界处理（`numericproof.parse_proof_column` 与 `exhaustionreport."
            "exhaustion_problems`）。"),
        "done_when": _DONE_COMMON,
        "prompt": (
            "你在做「穷举证明的证明栏优化」：程序是证据本体（只读），你改的是"
            "「穷举论证」那一段。\n"
            "目标：① 搜索空间写明对象个数与参数范围，数字要与程序里的循环/边界对得上；"
            "② 说明用了哪些对称性 / 剪枝，以及为什么它们不丢解（没有就写「没有用剪枝，"
            "因为……」）；③ 端点与退化情形逐条说清怎么覆盖。\n"
            "硬边界：不改程序路径与代码；不把抽样写成穷尽（`exhaustive` 必须是布尔 "
            "true 才谈得上穷尽）；不删掉原有的三段结构。\n"
            "改完派 V 走穷举型证据会审；缺材料就按 V 点名的第几项补，补完再送。\n"
            + _DONE_COMMON),
    },
    "well_defined": {
        "key": "well_defined",
        "status": "draft_pending",
        "goal": (
            "**待业主裁**：良定义论证该比原稿好在哪，今天没有定论。业主逐字「良定义类需"
            "再做设计」⇒ 这一档先不发提示词。"),
        "inputs": (
            "概念行的定义正文（`statement_full`）+ 它原来那份良定义论证（若有，住在"
            "`proof_text` / `manuscripts/B/b-proof-<号>.md`）。概念没有等级轴，判据不是"
            "「够不够定理」，而是「这个定义立不立得住」。"),
        "done_when": (
            "同上三件（正文改了 / V 签在新正文 sha 上 / 收录记成 optimized=true）—— "
            "但「良定义论证写成什么样算合格」这一条本身还没设计，所以 `prompt` 是空的："
            "拿 F 侧那套「把证明写清楚」套上去会把判据换掉。"),
        "prompt": "",
    },
}


def optimization_prompt(prompt_class: Any) -> dict[str, Any]:
    """按档取提示词（`{key, status, goal, inputs, done_when, prompt}`，纯读）。

    未登记的档：退回 `theorem` 那一档并把 `status` 标成 `unregistered`（不静默
    —— 一个拼错的档名不能拿到一份看起来正常的提示词却没人知道档名写错了）。
    """
    key = str(prompt_class or "").strip()
    got = PROMPTS.get(key)
    if got is not None:
        return dict(got)
    fallback = dict(PROMPTS["theorem"])
    fallback.update(key=key, status="unregistered",
                    why=f"未登记的优化提示词档 {key!r}（已登记：{PROMPT_CLASSES}）⇒ "
                        "退回定理那一档，请把档名写对或先在注册表里登记")
    return fallback
