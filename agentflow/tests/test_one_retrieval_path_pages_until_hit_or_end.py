# -*- coding: utf-8 -*-
"""缺陷 ②：检索只留一条路，判定按页问到命中或页尽（不再截断到前 4 条）。

## 审计探针 C（改前红）

`agent_b/register_statement.py` 自建关键词检索（`_numeric_same_candidates`）并按 20 条
分批；而判定那一侧 `_candidate_reading` 只把前 4 条交给模型。探针 C 传 20 条
候选，模型只看到 4 条；第 5–20 条永不入眼却被记成"这批都不是"（模型点了第 20 条
也会被接受 —— 它根本没看过那条的正文）。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 检索实现只有一处（`Secretary._statements_matching_keywords`），B 里没有自建检索 | 改前 B 有 `_numeric_same_candidates` 第二条检索路 |
| b | 20 条候选 ⇒ 5 页逐页问完，模型看到全部 20 条；读数 `pages_total=5` / `pages_judged=5` / `candidates_total=20` / `page_exhausted=True` | 改前只问 1 页、只看前 4 条，读数说"这批都不是" |
| c | 命中在第 5 页的第 20 条 ⇒ `same_as` 指向它、`pages_judged=5`、`page_exhausted=False` | 改前它不在前 4 条里，模型永远看不到 |
| d | 反真空：把分页打桩回"只给第一页"⇒ b 的同一批 20 条只看到 4 条、第 20 条找不到（红） | 证明 b/c 的绿真的来自分页 |
| e | 反真空：B 只把整趟交给 `adjudicate_proposition`（不带 `candidates=`）⇒ 若 B 恢复自建检索，它会带候选表来 | 改前 B 自己检索、只把候选递过去 |

零模型调用：`Secretary.judge` 打桩，不碰网络。
"""
from __future__ import annotations

import ast
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import seed_statement_row  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow.store import Store  # noqa: E402

SRC_DIR = pathlib.Path(SRC) / "agentflow"
FULL = "设 G 是有限群且 |G| = p^a·m（p∤m），则 G 有 p 阶元。"


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _sec(store: Store) -> SEC.Secretary:
    return SEC.Secretary("B", root=store.root, store=store)


def _supplied(n: int = 20) -> list[dict]:
    return [{"stmt_id": f"{i:06d}", "label": f"候选 {i}",
             "statement_full": f"候选命题 {i}：设 n<={i}，则 P(n) 成立。",
             "kind": "conjecture"} for i in range(1, n + 1)]


def _judge_pages(monkeypatch, *, same_when=None):
    """打桩 `judge`：记录每一页看到的候选号；`same_when` 里的号被看到 ⇒ 判 same。"""
    seen: list[list[str]] = []

    def _fake(self, kind, context, *, task_id="", note=""):
        ids = [str(c.get("stmt_id") or "") for c in (context.get("candidates") or [])]
        seen.append(ids)
        hit = ""
        if same_when is not None:
            hit = same_when if same_when in ids else ""
        return {"checked": True, "decision": "same" if hit else "different",
                "same_as": hit, "canonical_name": "", "route": "",
                "condition": "", "conclusion": "", "basis": [],
                "reason": "夹具", "cost": {}, "elapsed_sec": 0.0}

    monkeypatch.setattr(SEC.Secretary, "judge", _fake)
    return seen


# ===================================================== a 检索只有一处
def test_a_the_retrieval_has_exactly_one_implementation() -> None:
    """a：关键词检索只定义在 `statementledger.py` 一处、只被 `secretary.py` 调一处。

    2026-11-09（业主第三件「查必须明确有两种口径」）：这一格的落点跟着实现搬了 ——
    原先是 `Secretary._statements_matching_keywords`（秘书的私有方法），现在是
    `statementledger.by_keywords`（命题台账查口的口径二）。**判据强度不变**：
    仍然是「定义 1 处 + 调用 1 处」，只是定义搬到了能被各角色共用的那一层。
    为什么必须搬：私有方法谁都调不到，第 4 步「把查搬到各角色」就无从下手。
    """
    defs: list[str] = []
    calls: list[str] = []
    for path in SRC_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "def by_keywords(" in text:
            defs.append(path.name)
        calls.extend([path.name] * text.count("by_keywords("))
    assert defs == ["statementledger.py"], f"检索实现不止一处：{defs}"
    # 定义行本身算一次 ⇒ 查口内部不许再有调用；调用点必须只有 `_identity_candidates` 那一处。
    assert calls.count("statementledger.py") == 1, (
        f"查口内部又长出了第二条检索路：{calls}")
    assert calls.count("secretary.py") == 1, (
        f"`by_keywords` 的调用点清单不是「只有 `_identity_candidates` 一处」：{calls}")
    b_src = (SRC_DIR / "agent_b" / "register_statement.py").read_text(encoding="utf-8")
    tree = ast.parse(b_src)
    funcs = {node.name for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_numeric_same_candidates" not in funcs, "B 又长出了第二条检索路"
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "STATEMENT_SAME_CANDIDATE_PAGE" not in names, "B 又长出了自己的分批大小"
    resolver = next((node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef)
                     and node.name == "_resolve_same_statement"), None)
    assert resolver is not None
    attrs = {node.attr for node in ast.walk(resolver)
             if isinstance(node, ast.Attribute)}
    assert "adjudicate_proposition" in attrs, "B 没有把整趟交给秘书那一条路"


# ===================================================== b 20 条 ⇒ 5 页看完
def test_b_twenty_candidates_are_judged_across_five_pages(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """b：20 条候选 ⇒ 5 页、20 条都入眼、页尽。"""
    seen = _judge_pages(monkeypatch)
    sec = _sec(_store(tmp_path))
    got = sec.adjudicate_proposition(
        {"statement_full": FULL, "label": "P 阶元", "kind": "theorem"},
        candidates=_supplied(20), use_cache=False)
    assert got["checked"] is True, got
    assert got["verdict"] == "different", got
    assert got["pages_total"] == 5, got
    assert got["pages_judged"] == 5, got
    assert got["candidates_total"] == 20, got
    assert got["candidates_seen"] == 20, got
    assert got["page_exhausted"] is True, got
    assert [len(page) for page in seen] == [4, 4, 4, 4, 4], seen
    flat = [sid for page in seen for sid in page]
    assert flat == [f"{i:06d}" for i in range(1, 21)], flat


# ===================================================== c 第 20 条命中
def test_c_a_hit_on_the_fifth_page_is_found(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c：命中在第 5 页第 20 条 ⇒ 找得到、停在命中那一页。"""
    seen = _judge_pages(monkeypatch, same_when="000020")
    sec = _sec(_store(tmp_path))
    got = sec.adjudicate_proposition(
        {"statement_full": FULL, "label": "P 阶元", "kind": "theorem"},
        candidates=_supplied(20), use_cache=False)
    assert got["checked"] is True, got
    assert got["verdict"] == "same", got
    assert got["same_as"] == "000020", got
    assert got["pages_judged"] == 5, got
    assert got["pages_total"] == 5, got
    assert got["page_exhausted"] is False, got
    assert seen[-1][-1] == "000020", seen


# ===================================================== d 反真空：只给第一页
def test_d_truncating_to_the_first_page_hides_the_twentieth(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """d：把分页打桩回"只给第一页"⇒ 第 20 条永远看不到（b/c 的绿依赖分页）。"""
    seen = _judge_pages(monkeypatch, same_when="000020")
    monkeypatch.setattr(
        SEC.Secretary, "_identity_pages",
        staticmethod(lambda candidates, page_size=4: [list(candidates)[:4]]))
    sec = _sec(_store(tmp_path))
    got = sec.adjudicate_proposition(
        {"statement_full": FULL, "label": "P 阶元", "kind": "theorem"},
        candidates=_supplied(20), use_cache=False)
    assert got["pages_total"] == 1, got
    assert got["pages_judged"] == 1, got
    assert got["same_as"] == "", got
    assert [sid for page in seen for sid in page] == ["000001", "000002", "000003", "000004"], seen


# ===================================================== e 反真空：B 不自建检索
def test_e_b_hands_the_whole_trip_to_the_secretary(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """e：B 的 `_resolve_same_statement` 调 `adjudicate_proposition` 且不带候选表。

    若把 B 的自建检索恢复，它一定会先把候选检索好、再用 `candidates=` 递过去 ——
    这一条断言就是那个形态的负控。
    """
    store = _store(tmp_path)
    seed_statement_row(store, statement_full="另一条命题：设 n<=3，则 Q(n) 成立。",
                       kind="conjecture", label="Q(n)")
    from agentflow.agent_b import AgentB

    calls: list[dict] = []

    def _fake(self, stmt_like, **kwargs):
        calls.append({"stmt_like": dict(stmt_like), **kwargs})
        return {"checked": True, "verdict": "different", "same_as": "",
                "candidates": [], "keywords": [], "hits_total": 0,
                "hits_named": [], "judged": False, "pages_total": 1,
                "pages_judged": 0, "candidates_total": 0, "page_exhausted": True,
                "reason": "夹具", "basis": "", "seam_source": "fixture",
                "cost": {}, "reused": False}

    monkeypatch.setattr(SEC.Secretary, "adjudicate_proposition", _fake)
    got = AgentB(store, extractor=None, extract_text=None, config={}
                 )._resolve_same_statement(full=FULL, label="P 阶元",
                                           kind="theorem")
    assert got["checked"] is True, got
    assert len(calls) == 1, calls
    assert "candidates" not in calls[0], (
        "B 把候选表递过去了 ⇒ 自建检索又回来了", calls[0])
    assert calls[0]["stmt_like"]["statement_full"] == FULL, calls[0]
    # 读数照原样带出来（页数 / 候选数 / 页尽）。
    assert got["pages_total"] == 1 and got["page_exhausted"] is True, got


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
