# -*- coding: utf-8 -*-
"""秘书的标签洗（内部工作名 -> 名字，从 secretary.py 的 U20 逐字搬出）。

我保证哪条不变式：静默改名不许：每次改名都要留下 from / to / class / why 四格。

## 为什么它能单独成文件（依赖方向）

`secretary_label` 只 import 比它更低的那几层（词表 / 台账 / 时戳 / 装配口），反向 import 为零 ——
本文件里不许出现 `from .secretary import ...`：那一句会让「组装层 -> 混入层」与
「混入层 -> 组装层」同时成立，是为真 import 环。方法之间只经 `self.xxx` 互相调用
（那走 MRO，不产生 import），所以一个方法搬进混入类与留在 `class Secretary` 里
AST dump 完全相同 —— 「搬」不算「改」，`temp/secsplit/bodies_all.py` 逐名可复算。

## 对外名字

（`secretary_label` 这一份）类由 `secretary.py` 组装（`class Secretary(..., <X>Mixin, ...)`），所以本文件的公开面
是这个混入类；`secretary.py` 对搬走的模块级名字仍按原样再导出，外部 import 一个字不改。
"""

from __future__ import annotations

from . import propositionkey as _PK
import re

from .secretary_decl import (  # noqa: F401 — 这些名字由 secretary_decl 定义
    _is_concept_kind,
)

from .secretary_vocab import (  # noqa: F401 — 这些名字由 secretary_vocab 定义
    LABEL_FROM_STATEMENT_CHARS,
    LABEL_WASH_WORKING,
    LABEL_WORKING_NAME_RULES,
)



class LabelMixin:
    """标签洗的混入类：本模块今天没有方法，类在这里是为了组装口一致（命名与组装层同形）。"""

def _tidy_label(text: Any) -> str:
    """把删掉工作名之后剩下的那一截收拾成能当名字的样子。

    四件事：去掉空括号、折叠空白、削掉首尾的分隔符与句读、去掉落单的开/闭括号。
    为什么要有这一格：删掉「草稿」之后留下的 `（ ）` 与 `：` 都不是名字的一部分，
    而一个以冒号开头的标签看起来仍然像没洗过。
    """
    out = str(text or "")
    out = re.sub(r"[（(【\[]\s*[）)】\]]", " ", out)
    out = re.sub(r"\s+", " ", out).strip()
    out = out.strip(" ·—-,，;；:：、。.()（）[]【】")
    out = re.sub(r"^[（(【\[]\s*", "", out)
    out = re.sub(r"\s*[）)】\]]$", "", out)
    return out.strip()


def _readable_label(text: Any) -> bool:
    """这一截还剩不剩"能当名字念"的东西（至少两个字母或汉字，且不是一串编号）。

    为什么门槛是两个字而不是"非空"：删完之后常剩下 `S2` / `000000` 这种编号，
    它们不是名字；而把编号当名字落盘，下一次读的人只会以为这条定理就叫这个。
    """
    letters = re.findall(r"[A-Za-z\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", str(text or ""))
    return len(letters) >= 2


def _brackets_balanced(text: Any) -> bool:
    """这一串里的括号配对了吗（圆 / 方 / 六角 / 中文括号各算各自的）。

    为什么洗名要看它：命中的那段若在括号里（真机 sylow4 的
    `Sylow 三定理（路线一：…，自证草稿，待 V 审签）`），删掉之后会剩下半只括号 ——
    那说明这一处是"路线 / 草稿状态"那一类的落点，归模型洗名（`canonical_name`），
    不是本函数的活。括号不配对就整条不动，两种洗名各管各的。
    """
    pairs = (("(", ")"), ("【", "】"), ("[", "]"), ("（", "）"))
    body = str(text or "")
    for left, right in pairs:
        if body.count(left) != body.count(right):
            return False
    return True


def _strip_working_names(text: str) -> tuple[str, list[str]]:
    """把贴在首/尾的内部工作名那几段删掉，返回 `(剩下的, 命中的类名)`。

    只删首/尾（判定：那一段前面的部分、或后面的部分已经念不出名字）：中间的命中
    不动它 —— `草稿本上的定理` 这种名字里，"草稿"是名字的一部分，不是派活台账的残留。
    """
    out = str(text or "")
    hits: list[str] = []
    changed = True
    while changed:
        changed = False
        for cls, pattern in LABEL_WORKING_NAME_RULES:
            for found in re.finditer(pattern, out, flags=re.IGNORECASE):
                before, after = out[:found.start()], out[found.end():]
                if _readable_label(_tidy_label(before)) and _readable_label(_tidy_label(after)):
                    continue
                hits.append(cls)
                out = before + " " + after
                changed = True
                break
            if changed:
                break
    return out, hits


def _first_readable_claim(statement_full: Any, *, kind: str = "") -> str:
    """从正文里抽一句能当标签念的东西（抽不出 ⇒ 空串）。

    概念行优先用「概念（X）」里那个 X（那本来就是它的名字）；其余取第一句可读的命题
    陈述，按句读切（`。` `；` `;` `!` `?` 与换行），跳过太短的、抽不出字面的、以及
    换一行还是工作名的那些。markdown 记号在这里先摘掉：名字里不该出现星号与反引号。
    """
    text = str(statement_full or "")
    if not text.strip():
        return ""
    if _is_concept_kind(kind):
        term = _PK.defined_term(text)
        if term and _readable_label(term):
            return _clip_label(_tidy_label(term))
    plain = re.sub(r"[*`#>|]+", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    for chunk in re.split(r"[。；;！!？?\n]+", plain):
        piece = _tidy_label(chunk)
        if len(piece) < 4 or not _readable_label(piece):
            continue
        _rest, hits = _strip_working_names(piece)
        if hits and not _readable_label(_tidy_label(_rest)):
            continue
        return _clip_label(piece)
    return ""


def _clip_label(text: str) -> str:
    """标签截断（超过 `LABEL_FROM_STATEMENT_CHARS` 就切，不补省略号）。"""
    out = str(text or "").strip()
    limit = int(LABEL_FROM_STATEMENT_CHARS)
    if len(out) <= limit:
        return out
    return out[:limit].strip()


def wash_working_name(label: Any, *, statement_full: Any = "", kind: str = "",
                      stmt_id: str = "") -> dict[str, Any] | None:
    """把标签里的内部工作名洗掉；没命中 ⇒ `None`（原标签一个字节都不动）。

    ## 洗成什么（"不许洗成空"的三级）
    1. 删掉工作名那几段之后还剩能念的东西（`待推进：Noether 环` 这种"状态 + 名字"）⇒
       剩下的那一截就是名字；
    2. 整条标签都是工作名 ⇒ 从 `statement_full` 里抽：概念行先取「概念（X）」的 X，
       否则取第一句可读的命题陈述（截断到 `LABEL_FROM_STATEMENT_CHARS`）；
    3. 正文本身也抽不出（空正文，或者第一句还是工作名）⇒ 落成
       「<kind> 待命名（stmt:NNNNNN）」，并在读数里点名"原名不可用"。

    ## 返回
    `{"from", "to", "class", "why"}`：`from` 是交上来的原标签，`to` 是洗过的名字，
    `class` 点名触发的那一类（内部工作名 + 命中的类名；见 `LABEL_WORKING_NAME_RULES`），
    `why` 是一句人话 —— 静默改名是不许的，读的人要能看出"凭什么改"与"改成了什么"。
    """
    original = str(label or "")
    if not original.strip():
        return None
    rest, hits = _strip_working_names(original)
    if not hits:
        return None
    kept = _tidy_label(rest)
    if _brackets_balanced(original) and not _brackets_balanced(kept):
        # 命中的那段在括号里（路线 / 草稿状态那一类的落点）⇒ 交给模型洗名，这里不动它。
        return None
    classes = "、".join(dict.fromkeys(hits))
    if _readable_label(kept):
        to = _clip_label(kept)
        why = (f"标签里的内部工作名（{classes}）删掉之后还剩 {to!r} ⇒ 它就是名字"
               + ("（截断过）" if len(kept) > len(to) else ""))
    else:
        from_body = _first_readable_claim(statement_full, kind=kind)
        if from_body:
            to = from_body
            why = (f"整条标签都是内部工作名（{classes}），原名不可用 ⇒ "
                   f"从 statement_full 抽第一句可读的命题陈述当名字：{to!r}")
        else:
            tag = str(kind or "命题").strip() or "命题"
            to = f"{tag} 待命名（stmt:{str(stmt_id or '').strip() or '未发号'}）"
            why = (f"整条标签都是内部工作名（{classes}），而 statement_full 也抽不出可读的"
                   f"一句 ⇒ 原名不可用，名字待定：{to!r}")
    return {"from": original, "to": to,
            "class": f"{LABEL_WASH_WORKING}（{classes}）", "why": why}
