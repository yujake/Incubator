# -*- coding: utf-8 -*-
"""判据：五处提示词对「通用写口能改 statements 什么」说的是同一件事（业主 2026-11-04 裁定 C）。

## 业主裁定（逐字）

    C 按建议 —— 放弃命题：统一成"通用写口可改非正文三格（含 status），且会触发作废"，
    三处一起改

## 为什么必须统一

改前这几处说的是两件相反的事：

- `specs/b.py`：`table.update` 那类通用写口对 statements 已被封；
- `specs/d.py` / `agent_skills.py`（两处）：只在通用表写口改状态时，作废不会发生。

而实现早就是另一件事（`tools/table_tools.py::_route_to_secretary` 的非正文 patch 分支 +
`_abandon_reading`）：通用写口能改 `status` / `kind` / `quote_reason` 三格，
而且改 `status=abandoned` 会当场作废名下的 `v-resubmit@` 项。
模型照旧文字走只有两种下场：不敢用这条出口，或者用了之后以为板项还开着、
回头再补一遍 —— 两者都不是"措辞问题"，是把一条活着的出口在提示词里写成死的。

## 第五处（2026-11-04 收口）

改前 `specs/m.py` 仍写着「只经通用表写口改状态与标记时它不会发生」——
与上面统一后的口径相反。业主已就同一条口径裁定过"按建议"，所以这一处也改成
同一句；判据随之从四处扩到五处。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 五个落点各自同时出现「非正文三格」与「会触发作废」，且都带「正文仍需走证明入口」 | 改前 0 处这样写：b 说"已被封"、d 与 skills 说"不会发生"、m 说"不会发生" |
| b | 反真空：把任一句从任一落点的文本里删掉 ⇒ 校验函数必须红 | 证明 a 的绿不是"随便出现两个词"，而是那两句真的在 |
| c | 五处逐字同义：源码里那整句归一到同一串之后，每一处都找得到 | 改前 m 那一处根本没有这一句 |
| d | 端到端 `test_statements_unsigned_and_resubmit.py` 的那一组仍绿（只改措辞，实现不动） | —— |

本文件只读源码文本（不导入 `specs/*`、不跑动作）：它量的是"模型看得到的那句话"。
"""
from __future__ import annotations

import pathlib
import re

PROJECT = pathlib.Path(__file__).resolve().parents[1]

#: 五个落点（业主逐一点名；行号会漂，所以按文件 + 落点计数找，不写死行号）。
#: `count` 是这一份文件里应当出现的次数（agent_skills 有两处手册）。
SITES: tuple[tuple[str, int], ...] = (
    ("src/agentflow/specs/b.py", 1),
    ("src/agentflow/specs/d.py", 1),
    ("src/agentflow/specs/m.py", 1),
    ("src/agentflow/agent_skills.py", 2),
)

#: 统一后的两句话（业主逐字给出的口径）。
CELLS = "非正文三格"
ABANDON = "会触发作废"
BODY_ENTRY = "正文仍需走证明入口"

#: 统一后的那整句（五处逐字同义，只有源码里的换行位置不同）。
#: 2026-11-06 p250a（f507b528）把作废后的板项状态按实现改准：`ITEM_CLOSES` 里没有
#: `closed`，真读数是 `item_state=done` + `item_close=expired` ⇒ 这一句跟着改成
#: `done` + `expired`；五处同步（判据的强度不变：仍是「五处逐字同义」）。
CANONICAL = (
    "通用写口可改 `statements` 的**非正文三格**（含 `status` / `kind` / `quote_reason`），"
    "且改 `status=abandoned` 时**会触发作废**（`v-resubmit` 项随之 `done` + `expired`）；"
    "正文仍需走证明入口。"
)

#: 改前那两句相反的话（统一之后一句都不许留）。
STALE: tuple[str, ...] = (
    "只经通用表写口改状态时它不会发生",
    "只经通用表写口改状态与标记时",
    "table.update` 那类通用写口对 ",
    "table.update` 那类通用写口对 statements 已被封",
)


def _read(rel: str) -> str:
    return (PROJECT / rel).read_text(encoding="utf-8")


def _squash(text: str) -> str:
    """去掉源码里的引号与全部空白 —— 用来比"相邻字面量拼出来的那句话"。

    两处都做同一个归一（源码一侧与 `CANONICAL` 一侧），所以换行位置、
    行内缩进、三引号与相邻字面量的差别都不影响比对。
    """
    return re.sub(r"\s+", "", text.replace('"', ""))


def _problems(text: str, *, want: int) -> list[str]:
    """这一份文本离「五处措辞统一」还差什么（空列表 = 合格）。"""
    out: list[str] = []
    got_cells = text.count(CELLS)
    got_abandon = text.count(ABANDON)
    got_body = text.count(BODY_ENTRY)
    if got_cells != want:
        out.append(f"「{CELLS}」出现 {got_cells} 次，应为 {want} 次")
    if got_abandon != want:
        out.append(f"「{ABANDON}」出现 {got_abandon} 次，应为 {want} 次")
    if got_body != want:
        out.append(f"「{BODY_ENTRY}」出现 {got_body} 次，应为 {want} 次")
    for stale in STALE:
        if stale in text:
            out.append(f"还留着改前那句相反的话：{stale!r}")
    if _squash(CANONICAL) not in _squash(text):
        out.append("找不到与另外四处逐字同义的那一整句（口径分家了）")
    return out


# ============================================================ a 五处同口径
def test_a_each_site_says_non_body_cells_and_will_abandon() -> None:
    """a+c：每个落点都同时写着那两句，且五处逐字同义（缺一句就红）。"""
    for rel, want in SITES:
        text = _read(rel)
        problems = _problems(text, want=want)
        assert problems == [], f"{rel}：\n  - " + "\n  - ".join(problems)
        # 两句必须落在同一段（不是文件两头各出现一次、拼起来才算）：
        # 以「非正文三格」为中心，前后各 200 字里必须找得到「会触发作废」。
        for hit in re.finditer(re.escape(CELLS), text):
            window = text[max(0, hit.start() - 200): hit.end() + 200]
            assert ABANDON in window, (
                f"{rel}：`{CELLS}` 附近没有「{ABANDON}」——那两句必须写在同一句口径里，"
                "分开写等于让读者自己拼")


# ============================================================ b 反真空
def test_b_removing_either_sentence_turns_the_check_red() -> None:
    """b：从每一处删掉任一句 ⇒ 校验函数必须红（a 的绿来自这两句真的在）。"""
    for rel, want in SITES:
        real = _read(rel)
        assert _problems(real, want=want) == []
        broken_cells = real.replace(CELLS, "")
        assert _problems(broken_cells, want=want) != [], (
            f"{rel}：删掉「{CELLS}」之后校验仍然绿 —— a 量的不是这句话")
        broken_abandon = real.replace(ABANDON, "")
        assert _problems(broken_abandon, want=want) != [], (
            f"{rel}：删掉「{ABANDON}」之后校验仍然绿 —— a 量的不是这句话")
        broken_body = real.replace(BODY_ENTRY, "")
        assert _problems(broken_body, want=want) != [], (
            f"{rel}：删掉「{BODY_ENTRY}」之后校验仍然绿 —— a 量的不是这句话")


# ============================================================ c 反真空（整句）
def test_c_rewording_one_site_back_to_the_old_line_turns_it_red() -> None:
    """c：把任一处那整句改回旧口径（三个词一个不少）⇒ 逐字同义这一条必须红。"""
    tail = "（`v-resubmit`项随之`done`+`expired`）；正文仍需走证明入口。"
    rewound_tail = "；作废落在`v-resubmit`项上（closed/expired）；正文仍需走证明入口。"
    for rel, want in SITES:
        squashed = _squash(_read(rel))
        assert _squash(CANONICAL) in squashed, f"{rel}：盘上没有改后那整句 ⇒ 反真空打不中"
        rewound = squashed.replace(tail, rewound_tail)
        assert rewound != squashed, f"{rel}：那一句的尾巴没找到 ⇒ 反真空打不中"
        # 三个词都还在 ⇒ 这一条红不能是"少了一个词"，只能是同一句口径被改散了。
        for word in (CELLS, ABANDON, BODY_ENTRY):
            assert word in rewound, f"{rel}：反真空把 {word!r} 也删了（那就不是 c 这一条）"
        problems = _problems(rewound, want=want)
        assert problems != [], (
            f"{rel}：把口径改回旧写法之后校验仍然绿 —— a 量的不是同一句口径")
        assert any("逐字同义" in p for p in problems), problems
