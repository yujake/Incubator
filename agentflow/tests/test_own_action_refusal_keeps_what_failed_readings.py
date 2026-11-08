# -*- coding: utf-8 -*-
"""判据③：`own.<动作>` 受控拒的返回必须带回"为什么没判成"的读数。

## 真机形态（2026-11-08）

B 的动作 `register_statement` 在"有候选、而同一命题这一问没查成"时受控拒
（`kind=same_statement_unjudged`）：它自己的返回里带着 `same_statement` 整份读数
（`keywords` / `keyword_checked` / `hits_total` / `hits_named` / `judged` /
`model_calls`）与 `problems`。可 `_own_action_tool` 的白名单只留
`problems` / `missing` / `stmt_id` / `available_lit_ids` / `literature_rows` /
`unresolved` / `changes` / `upgraded` ⇒ 模型只看到"被拒"两个字，分不清
"关键词没挑出来" / "挑出来了但 0 命中" / "命中了但判定没成"。

## 这一份钉的两条

| 条 | 它要证明的事 |
|---|---|
| a | `kind=same_statement_unjudged` 的返回里能读到 `keywords` / `hits_total` / `hits_named` / `judged` / `model_calls`（逐字贴读数） |
| b | 反真空：把白名单退回改前那一份 ⇒ 同一份拒信里这些读数立刻没了（这条判据真的在看白名单） |

零模型调用、零网络：内层替身直接返回一份受控拒的形状。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_loop as AL
from agentflow import capabilities as C
from agentflow.agent_loop import LlmBackend

KEYWORDS = ["Sylow", "子群", "共轭"]
HITS_NAMED = [{"stmt_id": "000003", "hit_words": ["Sylow"]}]

#: 与 `agent_b/register_statement.py::_resolve_same_statement` 的受控拒同形（只取要判的键）。
REFUSAL = {
    "ok": False, "kind": "same_statement_unjudged",
    "error": "这条命题要查「是不是在册的同一条」，而这一问没查成 => 受控拒、不新注册",
    "refusal_reason": "precondition_failed",
    "same_statement": {"checked": False, "keyword_checked": True,
                       "keywords": list(KEYWORDS), "hits_total": 3,
                       "hits_named": list(HITS_NAMED), "judged": True,
                       "model_calls": 2, "found": "", "refused": "same_statement_unjudged"},
    "searched": {"checked": False, "keywords": list(KEYWORDS), "hits_total": 3,
                 "hits_named": list(HITS_NAMED), "judged": True, "model_calls": 2},
    "same_as": "", "seam_source": "body（夹具：判定没成）",
    "keywords": list(KEYWORDS), "keyword_checked": True, "hits_total": 3,
    "hits_named": list(HITS_NAMED), "judged": True, "model_calls": 2,
    "problems": ["夹具：判定没成"],
    "_row": {"stmt_id": "000003", "statement_full": "不该漏给模型的内部行缓存"},
}


class _RefusingInner:
    """内层确定性实现替身：`call` 永远回同一份受控拒。"""

    def known_roles(self) -> list[str]:
        return ["B"]

    def resolve(self, role: str) -> None:
        return None

    def call(self, role, action, params, **_kw):
        return dict(REFUSAL)


def _tool():
    backend = LlmBackend(inner=_RefusingInner(), loops={},
                         session_root=pathlib.Path("."), store=None)
    spec = C.find_action("B", "register_statement")
    assert spec is not None, "B 没有 register_statement 这个动作"
    return backend._own_action_tool(spec, "register_statement", role="B")


def _call() -> dict:
    return dict(_tool().handler(statement_full="设 G 是有限群；则 G 的阶是偶数。"))


# ============================================================ a：读数看得见

def test_a_same_statement_unjudged_keeps_keywords_and_hits() -> None:
    got = _call()
    assert got.get("ok") is False, got
    assert got.get("kind") == "same_statement_unjudged", got
    # ① 整份检索读数（受控拒自带的那个键）。
    same = dict(got.get("same_statement") or {})
    assert same.get("keywords") == KEYWORDS, got
    assert int(same.get("hits_total") or 0) == 3, got
    assert same.get("hits_named") == HITS_NAMED, got
    assert same.get("judged") is True and int(same.get("model_calls") or 0) == 2, got
    # ② 摊平的那几格也看得见（模型按扁平键读也读得到）。
    assert got.get("keywords") == KEYWORDS, got
    assert got.get("keyword_checked") is True, got
    assert int(got.get("hits_total") or 0) == 3, got
    assert got.get("hits_named") == HITS_NAMED, got
    assert got.get("judged") is True, got
    assert int(got.get("model_calls") or 0) == 2, got
    # ③ 两条缝 / 判定读数不许丢。
    assert got.get("searched", {}).get("hits_total") == 3, got
    assert got.get("seam_source") == "body（夹具：判定没成）", got
    assert got.get("same_as") == "", got
    # ④ 白名单仍然是白名单：内部行缓存不许漏。
    assert "_row" not in got, got


# ============================================================ b：反真空

def test_b_restoring_the_old_whitelist_makes_the_readings_disappear(monkeypatch) -> None:
    """b（反真空）：把白名单退回改前那一份 ⇒ 上面那些读数立刻没了。

    不退这一步，"a 绿"就分不清是"新白名单在起作用"还是"旧白名单其实也带"。
    """
    monkeypatch.setattr(
        AL, "_OWN_REFUSAL_READING_KEYS",
        ("problems", "missing", "stmt_id", "available_lit_ids",
         "literature_rows", "unresolved", "changes", "upgraded"),
        raising=True)
    got = _call()
    assert got.get("ok") is False and got.get("kind") == "same_statement_unjudged", got
    # 改前形态：这几格一个都不在（正是这条判据要挡的"读数说谎"）。
    for key in ("same_statement", "searched", "keywords", "keyword_checked",
                "hits_total", "hits_named", "judged", "model_calls",
                "seam_source", "same_as"):
        assert key not in got, (key, got)
    # 旧白名单本来就保留的那几格仍在（证明拒信主体没被这条判据改动）。
    assert got.get("problems") == ["夹具：判定没成"], got
