# -- coding: utf-8 --
"""判据：C 的提示词只教它真做得到的事（外加"关系推断"该怎么查）。

## 改前实测的三处"教做不到的事"

1. `specs/c.py` 的 policy 教"报一个数（度数 / 割点 / 结构洞 / 绕行）"，而全仓
   没有 articulation 读数（没有这个工具、没有这个动作，`graph.` 也没有割点）——
   教了也报不出来；
2. 同一处 boundary 写"知识表（文献 / 概念 / 关系）"，而 `concepts` 表已经不存在
   （S1r 并表：概念行住 `statements`，`kind="concept"`）—— 点名一张不存在的表；
3. 同一处把"污染面"当读数报，却没教怎么查。2026-11-10 的裁定把第 3 处的修法换掉了
   （`draft/181`，业主逐字：「污染面查询是指一个命题被验证为错误后，通过被引面查询所有
   依赖其上的命题并反馈，这只是一种需求模式，不是一种工具」）：
   - 改前（已废）：教 C 自己用 `table.list(table="dependencies", …)` 读依赖行、
     反向走多跳、去重 —— 那是把代码侧的活交给模型，且每次都要 C 重算；
   - 现在：代码侧一次建好索引（不进上下文），C 按需 `ledger.resolve` 选根 →
     `ledger.expand(node=…, depth=…)`（层数由你决定、必填）→ 不够就对 `frontier`
     里的节点再 expand（拼接）。污染面只是一种查询模式（从被判错的命题向下展开），
     不是一件工具。

## 判据（两面）

a. 正面：这些"做不到的教法"都不在了；关系推断那一段教的是"选根 → 按层展开 → 拼接"，
   并明说污染面是查询模式、不是工具；
b. 反面（反真空）：把旧句逐处回灌 / 把关系推断那段抽掉，检查函数必须点名报出来 ——
   否则"提示词里没有 X"与"检查函数永远返回空"长得一模一样。
"""
from __future__ import annotations

from agentflow import agent_prompts as AP


def _c_text() -> str:
    """C 的边界 + 政策（提示词里常驻渲染的那两栏，`stance` 不算）。"""
    brief = AP.ROLE_BRIEFS["C"]
    return "\n".join(brief.boundary) + "\n" + "\n".join(brief.policy)


def _problems(text: str) -> list[str]:
    """这份 C 提示词里"教了做不到的事 / 没教怎么做"的地方（空列表 = 干净）。"""
    out: list[str] = []
    if "割点" in text:
        out.append("还在教「割点」：全仓没有 articulation 读数，C 报不出这个数")
    if "文献 / 概念 / 关系" in text:
        out.append("还把 `concepts` 当表名：`concepts` 已退役（概念行住 `statements`，kind=concept）")
    if "kind=concept" not in text:
        out.append("没有说清概念行的真身（`statements` 里的 `kind=concept`）")
    for needle, why in (
        ("ledger.resolve", "没教选根（`ledger.resolve` 只给候选节点）"),
        ("ledger.expand", "没教按层展开局部树（`ledger.expand`）"),
        ("层数由你决定、必填", "没写清层数由 C 自己定、且必填（不填会被拒）"),
        ("frontier", "没教不够就对 frontier 里的节点拼接"),
        ("污染面是一种查询模式", "没把污染面写成一种查询模式"),
        ("不是一件工具", "没明说污染面不是一件工具"),
        ("空面", "没教空面也是诚实读数（不是『没查成』）"),
    ):
        if needle not in text:
            out.append(f"关系推断那一段缺「{needle}」：{why}")
    for banned, why in (
        ('table.list(table="dependencies"',
         "还留着按 dependencies 表手算的多跳指令（代码侧已给索引与局部树）"),
        ("污染面不是框架给你的读数",
         "还在说污染面要 C 自己算（框架不给读数）—— 现在框架给的是局部树"),
    ):
        if banned in text:
            out.append(f"关系推断那一段还留着旧教法「{banned}」：{why}")
    return out


def test_c_prompt_does_not_teach_the_impossible() -> None:
    """a：三处都按裁定改过了；关系推断那段教的是"选根 → 展开 → 拼接"。"""
    bad = _problems(_c_text())
    assert not bad, "C 的提示词还在教做不到的事 / 没把关系推断教清：\n  " + "\n  ".join(bad)


def test_the_checker_is_not_vacuous() -> None:
    """b：逐处回灌旧句 / 抽掉关系推断那段 ⇒ 检查函数必须点名（不是永远返回空）。"""
    text = _c_text()

    # ① 回灌"割点"
    doctored = text.replace("度数 / 结构洞 / 绕行", "度数 / 割点 / 结构洞 / 绕行")
    assert doctored != text, "夹具前提：新文案里有「度数 / 结构洞 / 绕行」可回灌"
    hit = _problems(doctored)
    assert any("割点" in one for one in hit), hit

    # ② 回灌旧的概念表文案
    doctored = text.replace("文献 / 命题 / 关系", "文献 / 概念 / 关系")
    assert doctored != text, "夹具前提：新文案里有「文献 / 命题 / 关系」可回灌"
    hit = _problems(doctored)
    assert any("concepts" in one for one in hit), hit

    # ③ 回灌改前那段手算指令 ⇒ 必须点名（`table.list` 那种多跳计算已废）
    old = ('用 `table.list(table="dependencies", filter={"source_stmt_id": "<号>"})` '
           "读依赖行，反向走多跳、去重。")
    hit = _problems(text + old)
    assert any("table.list" in one for one in hit), hit

    # ③' 把"选根"抹掉（教法退化成回到手算）⇒ 必须点名
    cut = text.replace("ledger.resolve", "查表")
    hit = _problems(cut)
    assert any("ledger.resolve" in one for one in hit), hit

    # ④ 空串 ⇒ 全部事实都报缺（检查函数不是对任何串都返回空）
    assert len(_problems("")) >= 8, _problems("")


# ---------------------------------------------------------------- 手册三句（同一件）


def _c_manual_text() -> str:
    """C 的三条 skill 正文（`agent_skills.CATALOG["C"]`，真跑时进提示词的那一份）。"""
    from agentflow import agent_skills as AS

    return "\n\n".join(skill.body for skill in AS.CATALOG["C"])


def _manual_problems(text: str) -> list[str]:
    """C 的手册里"教了做不到的事"的地方（空列表 = 干净）。

    2026-11-04：`347d6267` 把"交接手稿（handoff）"那一串改名插进了这一句
    （`manuscripts.read`（交接手稿，handoff）只有 `id` 那一格）—— 判据要的是"手册说清
    它只有 `id` 这一个实参"，不是"逐字连在一起"，所以这一格跟着新措辞走；强度不变
    （没有这句话，下面第一条照样点名）。
    """
    out: list[str] = []
    if "产出登记口只有 `C.handle`" in text:
        out.append("还说 `C.handle` 是产出登记口：它是动作、不在 C 的工具面上")
    if "产出登记口只有 `analysis.register_report`" not in text:
        out.append("没有点名真登记口 `analysis.register_report`")
    if "`manuscripts.read` 同理" in text:
        out.append("还说 `manuscripts.read` 能截段：它只有 `id`，没有 start_line / max_lines")
    if "`manuscripts.read`（交接手稿，handoff）**只有 `id`**" not in text:
        out.append("没有把 `manuscripts.read` 的实参说清（只有 `id`）")
    if "`path_shape.join_segments" in text and "没有工具面入口" not in text:
        out.append("还把 `path_shape.join_segments` 写成可调用的读数（没有工具面入口）")
    if "没有工具面入口" not in text:
        out.append("没有说清 `join_segments` 没有工具面入口")
    return out


def test_c_manual_does_not_teach_the_impossible() -> None:
    """a（手册三句）：登记口 / `manuscripts.read` 的参数 / `join_segments` 的入口都改成真话。"""
    bad = _manual_problems(_c_manual_text())
    assert not bad, "C 的手册还在教做不到的事：\n  " + "\n  ".join(bad)


def test_the_manual_checker_is_not_vacuous() -> None:
    """b（手册三句）：逐处回灌旧句 ⇒ 检查函数必须点名。"""
    text = _c_manual_text()

    hit = _manual_problems(text.replace(
        "产出登记口只有 `analysis.register_report`", "产出登记口只有 `C.handle`"))
    assert any("C.handle" in one for one in hit), hit

    hit = _manual_problems(text.replace(
        "`manuscripts.read`（交接手稿，handoff）**只有 `id`**", "`manuscripts.read` 同理"))
    assert any("manuscripts.read" in one for one in hit), hit

    hit = _manual_problems(text.replace("没有工具面入口", ""))
    assert any("join_segments" in one or "没有工具面入口" in one for one in hit), hit

    assert len(_manual_problems("")) >= 3, _manual_problems("")
