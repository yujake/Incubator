# -*- coding: utf-8 -*-
"""判据：语义判定是「秘书主动查询」（不是把在册全表交给它过一遍）。

## 业主原话（验收标准，逐字）

```
「没有判不了。派人做。还有，语义判定当前实现是秘书主动查询还是必须全过一遍？应该是主动查询」
```

## 这一份钉的两条

| 条 | 它要证明的事 | 改前（块乙之前）为什么是红的 |
|---|---|---|
| a | 给一条在册命题（与待收措辞不同、共享数学关键词）⇒ 秘书自己挑词、自己在 statements 里检索、只把命中候选交给判定那一趟；`same_as` 命中、不新建行 | 改前候选是"按词面相似度把全表排一遍取前 4"（`propositionkey.candidates_for`），不命中关键词也会被塞进去；读数里没有 `keywords` / `hits_total` / `hits_named` |
| b | 主动查询确实在承重：把关键词提取打桩成空 ⇒ a 变红（这一趟"没判成"、不并、不新建） | 改前关键词那一问根本没被调用 ⇒ 打桩打不到任何东西，a 照样绿 |

## 判据 a 为什么能区分"主动查询"与"全表过一遍"

夹具里放两条在册命题：一条与待收命题同主题（共享关键词），一条是无关的图论命题。
关键词检索的命中数必须是 「1」，交给模型的候选里「不许有那条无关命题」；
而"全表按相似度取前 4"会把两条都塞进去（改前读数：`candidates` 2 条）。
"检索只是取候选、不参与判定"另有一条负控：命中的那一条也不是靠词面相似度进候选的
（检索规则只有"label / statement_full 包含关键词"）。

## 边界

全部 tmp 工作区、零真实模型调用（"模型说了什么"由 `_Seam` 按 note 回）；
`projects/` 只读；不碰 `agent_b/`。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import refusals as R
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow.secretary import Secretary
from agentflow.store import Store

from conftest import seed_statement_row
from conftest import BASIS_LIT_ID, ensure_basis_lit

#: 在册的那一条：与待收命题「措辞不同」、但共享数学关键词（Sylow / p-子群）。
IN_LEDGER = "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在。"
#: 待收的那一条（同一条定理的另一种写法）。
PARAPHRASE = "若 G 为有限群且 p 为素数，则它的 Sylow p-子群一定存在。"
#: 在册的「无关」那一条（图论）：它用来证明"没有把全表交给模型过一遍"。
DECOY = "设 G 是连通图；则 G 有一棵生成树。"


class _Call:
    """`llmseam.SeamCall` 的最小替身（`judge` 只读 `ok` / `problem` / `detail`）。"""

    def __init__(self, ok: bool = True, problem: str = "", detail: str = "") -> None:
        self.ok = bool(ok)
        self.problem = str(problem)
        self.detail = str(detail)


class _Seam:
    """打桩的秘书缝：按 `note` 回"挑词"与"判定"两问，并把调用顺序记下来。"""

    wired = True

    def __init__(self, *, keywords=("Sylow", "p-子群"), keyword_why: str = "这两个数学词两边都有",
                 keywords_bad: bool = False, decision: str = "same") -> None:
        self.keywords = [str(x) for x in keywords]
        self.keyword_why = str(keyword_why)
        self.keywords_bad = bool(keywords_bad)
        self.decision = str(decision)
        self.calls: list[str] = []
        self.materials: list[dict] = []

    def ask_json(self, prompt, *, system: str = "", task_id: str = "", note: str = ""):
        self.calls.append(str(note))
        if str(note).endswith("statement_keywords"):
            if self.keywords_bad:
                return None, _Call(False, "judge_timeout", "打桩：挑词没查成")
            return {"keywords": list(self.keywords), "why": self.keyword_why}, _Call()
        data = dict(self._material(prompt))
        self.materials.append(data)
        candidates = [c for c in (data.get("candidates") or []) if isinstance(c, dict)]
        same_as = str(candidates[0]["stmt_id"]) if (self.decision == "same" and candidates) else ""
        return {
            "decision": self.decision if (self.decision != "same" or candidates) else "different",
            "same_as": same_as,
            "canonical_name": "Sylow I",
            "route": "",
            "condition": "打桩：都是有限群 + p 是素数",
            "conclusion": "打桩：都是 Sylow p-子群存在",
            "reason": "打桩：条件与结论一致" if same_as else "打桩：没有可并的候选",
            "basis": ["条件：一致", "结论：一致"],
        }, _Call()

    @staticmethod
    def _material(prompt: str) -> dict:
        import json

        text = str(prompt or "")
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            return {}


def _ws(base: pathlib.Path) -> Store:
    st = Store(base / "ws")
    st.init()
    ensure_basis_lit(st)
    return st


def _seed_ledger(st: Store) -> str:
    row = seed_statement_row(st, statement_full=IN_LEDGER, statement_text=IN_LEDGER[:24],
                             kind="theorem", label="Sylow I")
    seed_statement_row(st, statement_full=DECOY, statement_text=DECOY[:24],
                       kind="theorem", label="生成树引理")
    return str(row["stmt_id"])


def _body(full: str) -> dict:
    # 2026-11-17（GATE2 尾巴）：own_result 必须写清来路。这一份量的是"秘书自己检索 /
    # 判词 / 不新建行"（候选、hits、行数），不是来路；真 literature 行当来路，
    # 它不进 statements ⇒ "仍 2 行"与命中那条的号一个字都不变。
    return {"statement_full": full, "statement_text": full[:24],
            "origin": "own_result", "kind": "conjecture",
            "source_lit_id": BASIS_LIT_ID,
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _sec(st: Store, seam: _Seam) -> Secretary:
    return Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)


def _adjudicate(st: Store, seam: _Seam) -> dict:
    return _sec(st, seam).adjudicate_proposition(
        {"statement_full": PARAPHRASE, "label": "Sylow I", "kind": "conjecture"})


# ============================================================ a：主动查询命中、不新建行

def test_the_secretary_searches_by_keywords_and_hits_the_registered_one(
        tmp_path: pathlib.Path) -> None:
    """a：挑词 → 检索 → 只把命中的那条交给判定 ⇒ same_as 命中，`record_statement` 不新建。

    读数四件必须同时在：`keywords` / `hits_total` / `hits_named` / `judged`；
    而且命中的只有同主题那一条 —— 无关的图论命题不许被塞进候选（那就是"全表过一遍"）。
    """
    st = _ws(tmp_path)
    sid = _seed_ledger(st)
    seam = _Seam()
    got = _adjudicate(st, seam)
    assert got["checked"] is True and got["verdict"] == "same", got
    assert got["same_as"] == sid, got
    # 读数：它确实自己查过
    assert got["keywords"] == ["Sylow", "p-子群"], got["keywords"]
    assert got["hits_total"] == 1, got["hits_total"]
    assert [str(x.get("stmt_id") or "") for x in got["hits_named"]] == [sid], got["hits_named"]
    assert "Sylow" in list(got["hits_named"][0].get("hit_words") or []), got["hits_named"]
    assert got["judged"] is True, got
    # 两问的顺序：先挑词、再判定；判定那一趟只拿到命中的那一条
    assert seam.calls == ["secretary:statement_keywords", "secretary:proposition_identity"], (
        seam.calls)
    judged_material = seam.materials[-1]
    assert [str(c.get("stmt_id") or "") for c in judged_material.get("candidates") or []] == [sid], (
        "交给判定的候选里混进了没命中的行 ⇒ 这不是主动查询，是把全表过了一遍")
    # 落盘：同一命题 ⇒ 不新建（没有正文 ⇒ 重复读数那一支）
    out = _sec(st, seam).record_statement(_body(PARAPHRASE), role="B")
    assert out.get("checked") is True, out
    assert out.get("created") is not True, out
    assert str(out.get("stmt_id") or "") == sid, out
    assert len(_rows(st)) == 2, _rows(st)


# ============================================================ b：主动查询在承重

def test_stubbing_the_keyword_step_empty_makes_the_same_call_unjudged(
        tmp_path: pathlib.Path) -> None:
    """b：把关键词提取打桩成空 ⇒ a 那一次判定当场变成"没判成"（不并、不新建）。

    这一条证明 a 的绿是"主动查询"给的：关键词是检索的唯一输入，没有它就捞不到候选，
    而「不许」退回"把全表/相似度候选交给模型"那条老路。
    """
    st = _ws(tmp_path)
    sid = _seed_ledger(st)
    seam = _Seam(keywords=())
    got = _adjudicate(st, seam)
    assert got["checked"] is False, got
    assert got["verdict"] == "", got
    assert got["keywords"] == [] and got["hits_total"] == 0, got
    assert got["same_as"] == "", got
    assert "关键词" in str(got.get("reason") or ""), got
    # 它没有偷偷改成"全表候选"再判：判定那一趟根本没发
    assert seam.calls == ["secretary:statement_keywords"], seam.calls
    # 上层 fail-closed：受控拒、不新建
    out = _sec(st, seam).record_statement(_body(PARAPHRASE), role="B")
    assert out.get("refused") == R.SAME_STATEMENT_UNJUDGED, out
    assert len(_rows(st)) == 2, _rows(st)


def test_a_failed_keyword_call_also_leaves_the_judgment_undone(
        tmp_path: pathlib.Path) -> None:
    """b（续）：挑词那一问整趟没成（超时）⇒ 同样没判成、受控拒、不新建。"""
    st = _ws(tmp_path)
    _seed_ledger(st)
    seam = _Seam(keywords_bad=True)
    got = _adjudicate(st, seam)
    assert got["checked"] is False and got["verdict"] == "", got
    assert got["judged"] is False, got
    assert got["hits_total"] == 0, got
    out = _sec(st, seam).record_statement(_body(PARAPHRASE), role="B")
    assert out.get("refused") == R.SAME_STATEMENT_UNJUDGED, out
    assert len(_rows(st)) == 2, _rows(st)


if __name__ == "__main__":          # pragma: no cover - 手动跑这一份时用
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
