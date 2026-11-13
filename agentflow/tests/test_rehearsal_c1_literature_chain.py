# -*- coding: utf-8 -*-
"""彩排判据 C1 · 文献链：M → A（`search_literature` + `ingest_local`）→ B（`run_once` 消化）。

## 这条链要走通的那一段

```text
Conductor.summon("A", "search_literature")   # 入队（过 I7 准入闸门）→ 领跑 → 逐源三态
Conductor.summon("A", "ingest_local")        # 盘上的书 → library/ + literature 行（真事务）
Conductor.summon("B", "run_once")            # 领取 → 真 LLMExtractor 抽取 → concepts + relations
```

这一份全部是真入口：真 `Store` / 真事务 / 真 `Conductor.summon`（派活、落
`tasks`、结算 `usage_ledger`）/ 真 `LLMExtractor`（切块、逐字引文回验、剔除幻觉关系）。
只有两处是假缝，且都是"模型外部"那一层：

- 检索源（`_StubProvider`）：不联网，把"上游返回了什么"定死；
- 模型网关（`_Gateway`）：把 LLM 的回复定死 —— 但它走的仍是真 `LlmSeam` + 真
  `TokenMeter`，所以"钱"落在真台账上（B 那一行 `tasks.usd` 与 `usage_ledger` 同额）。

## 这条链的"走通"按盘上读数认（不是看回执里的 ok=True）

| # | 终态读数（盘上/台账上） |
|---|---|
| 1 | `search_requests` 一行：`done=True`、`outcome="no_results"`（查过、没有 —— 有效结论） |
| 2 | `literature` 一行：`processed=True`、`path` 指向 library 下的字节 |
| 3 | `relations` 一行：`status="active"`、`quote_reason` 记的是逐字命中（不是"没比就收"） |
| 4 | 概念行两条（`conceptrows.view` 老形状投影；关系两端都在册） |
| 5 | `tasks` 三行（A.search_literature / A.ingest_local / B.run_once）`outcome="ok"` |
| 6 | 钱：`tasks` 的 B 行 `tokens>0`、`usd>0`，且 `Σtasks.usd == Σusage_ledger.usd`（逐分相等） |

## 反真空（两条，各打坏一环）

- B 那一环：把模型回复里的 `quote` 换成正文里不存在的句子 ⇒ 真 `LLMExtractor` 的
  逐字回验必须把这条关系剔掉（`relations` 0 行）⇒ 第 3 条判据必须红。它证明第 3 条
  读的是"引文真的在原文里"，不是"只要抽过就有一行"。
- A 那一环：把 `books_dir` 指向一个空目录 ⇒ 一条 `literature` 都不落 ⇒ B 只能
  `no_result` ⇒ 第 2 条判据必须红。它证明第 2 条读的是"书真的登记进来了"。

零真实模型调用、零联网；`tmp_path` 工作区，不碰 `projects/` / `demo/`。
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

from agentflow import conceptrows as CR
from agentflow import conductor as CO
from agentflow import tokenmeter as TM
from agentflow.agent_a import AgentA
from agentflow.agent_b import AgentB
from agentflow.extract import DocumentText
from agentflow.llm import LLMExtractor
from agentflow.llmseam import LlmSeam
from agentflow.store import Store

#: 文献正文（一篇文章的两句话；引文逐字取自第一句）。
TEXT = ("An abelian group is a group in which the commutative law holds. "
        "Every subgroup of an abelian group is normal.")
QUOTE = "An abelian group is a group in which the commutative law holds."

#: 模型回复：两个概念 + 一条关系。`quote` 由调用方给（反真空换成不存在的句子）。
EXTRACTION = json.dumps({
    "concepts": [
        {"name": "abelian group", "definition": "A group whose operation commutes.",
         "aliases": [], "page": 1},
        {"name": "group", "definition": "A set with an associative operation.",
         "aliases": [], "page": 1},
    ],
    "relations": [
        {"concept_names": ["abelian group", "group"], "description": "交换群是群",
         "quote": QUOTE, "page_range": {"start": 1, "end": 1}},
    ],
}, ensure_ascii=False)


# --------------------------------------------------------------------------- 替身


class _Doc:
    """`locallib` 抽取结果的替身：只给"有没有文本层"与逐页正文两格。"""

    pages = [TEXT]
    has_text_layer = True


class _StubProvider:
    """确定性检索源：零命中（"查过、没有"是有效结论，不是失败）。"""

    name = "stub"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def search(self, topic, mode, description="", limit=10):
        self.calls.append((str(topic), str(mode)))
        return []


class _Gateway:
    """打桩网关：每次 `complete` 回同一段 JSON 与同一份 usage（不碰网络、不花真钱）。"""

    def __init__(self, *, quote: str = QUOTE) -> None:
        self.quote = str(quote)
        self.calls = 0

    def complete(self, prompt, *, scope="", system=None, tools=None, **_kw):
        self.calls += 1
        payload = json.loads(EXTRACTION)
        payload["relations"][0]["quote"] = self.quote
        return SimpleNamespace(
            ok=True, text=json.dumps(payload, ensure_ascii=False),
            tokens_in=10_000, tokens_out=1_000, scope=scope, attempts=1,
            error_kind="", error_detail="",
            cache_hit_tokens=None, cache_miss_tokens=None,
        )


class _Client:
    """`LLMExtractor` 要的 `.complete(prompt) -> str`；每一问都走计费缝（真台账）。"""

    def __init__(self, seam: LlmSeam) -> None:
        self.seam = seam

    def complete(self, prompt: str) -> str:
        call = self.seam.ask(prompt)
        return call.text if call.ok else ""


# --------------------------------------------------------------------------- 夹具


def _workspace(base: pathlib.Path) -> Store:
    """一个真工作区：`books/` 下放一本书（字节是假的，抽取器是注入的）。

    另一个 `empty_books/` 是反真空那一档用的空目录（存在、但一本书都没有）——
    "目录里没有书"与"目录不在盘上"是两件事，反真空必须落在前者。
    """
    st = Store(base / "ws")
    st.init()
    books = pathlib.Path(st.root) / "books"
    books.mkdir(parents=True, exist_ok=True)
    (books / "notes.pdf").write_bytes(b"%PDF-1.4 fixture bytes")
    (pathlib.Path(st.root) / "empty_books").mkdir(parents=True, exist_ok=True)
    return st


@pytest.fixture(autouse=True)
def _local_extract(monkeypatch):
    """`locallib` 的字节 → 文本那一层换成替身（不装 PyMuPDF、不加注释）。

    这是 A 的 `ingest_local` 唯一的外部依赖（真 PDF 解析）；换掉它之后，
    "登记 / 判重 / 落 literature 行"仍然全走产品代码。
    """
    import agentflow.locallib as LL

    monkeypatch.setattr(LL, "extract_text", lambda _path: _Doc())


def _wire(st: Store, *, gateway: _Gateway) -> CO.Conductor:
    """三个角色都按真类装配；只有检索源与模型网关是替身。

    装配面刻意走 `registry=("factory", …)`（`LocalBackend.resolve` 的公开形态）：
    于是"这一次派活用的是真 `AgentA` / `AgentB`"由构造保证，而不是由测试假设。
    """
    seam = LlmSeam(role="B", session_root=st.root, gateway=gateway,
                   price=(1.0, 2.0), sid="rehearsal-c1", meter=TM.TokenMeter(st))
    provider = _StubProvider()

    def factory_a(*, store):
        return AgentA(store, providers=[provider], downloader=None,
                      config={"download": False, "lease_seconds": 900,
                              "max_attempts": 3, "retry_backoff_seconds": 0})

    def factory_b(*, store):
        return AgentB(
            store, extractor=LLMExtractor(_Client(seam)),
            extract_text=lambda _p: DocumentText(text=TEXT, pages=[TEXT],
                                                 source_kind="txt"),
            config={"lease_seconds": 900, "max_attempts": 3})

    return CO.Conductor(st, registry={"A": ("factory", factory_a),
                                      "B": ("factory", factory_b)})


def _payload_of(result: dict) -> dict:
    """`SummonResult.payload` → 普通 dict（B 的 `BRunResult` 是 dataclass，不是 Mapping）。"""
    payload = result.get("payload")
    if payload is None:
        return {}
    if hasattr(payload, "to_dict"):
        return dict(payload.to_dict())
    return dict(payload) if isinstance(payload, dict) else {}


def _run_chain(base: pathlib.Path, *, quote: str = QUOTE,
               books_dir: str = "books") -> dict:
    """把 C1 那条链整条跑一遍，返回盘上的读数（反真空拿同一份读数打红）。"""
    st = _workspace(base)
    gateway = _Gateway(quote=quote)
    cond = _wire(st, gateway=gateway)

    searched = cond.summon(
        "A", "search_literature",
        {"topic": "abelian group", "mode": "topical", "description": "abelian group"})
    ingested = cond.summon("A", "ingest_local", {"books_dir": books_dir})
    digested = cond.summon("B", "run_once", {})

    return {
        "store": st,
        "gateway": gateway,
        "searched": searched.to_dict(),
        "ingested": ingested.to_dict(),
        "digested": digested.to_dict(),
        # 动作自己的回执（`SummonResult.payload`）：与 `tasks` 的终态是两件事，
        # 判据读盘为主、回执只作交叉核对。
        "search_payload": _payload_of(searched.to_dict()),
        "ingest_payload": _payload_of(ingested.to_dict()),
        "digest_payload": _payload_of(digested.to_dict()),
        "requests": [dict(r) for r in st.rows("search_requests")],
        "literature": [dict(r) for r in st.rows("literature")],
        "relations": [dict(r) for r in st.rows("relations")],
        "concepts": [dict(r) for r in CR.view(st, shape="legacy")["rows"]],
        "tasks": [dict(r) for r in st.rows("tasks")],
        "ledger": [dict(r) for r in st.rows("usage_ledger")],
        "money": TM.reconcile_usage(st),
    }


# --------------------------------------------------------------------------- 判据本体


def _chain_problems(reading: dict) -> list[str]:
    """C1 的六条终态读数（空 = 通）。返回问题清单而不是布尔：红时要能说清差在哪。

    每条都读盘（`store.rows` / 台账读数），不看回执里的 `ok`：
    `ok=True` 只说明"这次调用做完了"，说明不了"链通了"。
    """
    problems: list[str] = []
    st: Store = reading["store"]

    # 1. A 的检索：入队一行、查过、结论是"没有"（不是"没查成"）。
    requests = [r for r in reading["requests"]
                if str(r.get("topic") or "") == "abelian group"]
    if len(requests) != 1:
        problems.append(f"A 的检索请求行应恰好 1 行，实得 {len(requests)} 行")
    else:
        req = requests[0]
        if req.get("done") is not True:
            problems.append(f"A 的检索请求没收口：done={req.get('done')!r}")
        if str(req.get("outcome") or "") != "no_results":
            problems.append(f"A 的检索结论不是 no_results：{req.get('outcome')!r}")

    # 2. A 的入库：literature 一行、已消化、字节在 library 下。
    lit = reading["literature"]
    if len(lit) != 1:
        problems.append(f"literature 应恰好 1 行，实得 {len(lit)} 行")
    else:
        row = lit[0]
        if row.get("processed") is not True:
            problems.append(f"literature 没被 B 消化（processed={row.get('processed')!r}）")
        rel_path = str(row.get("path") or "")
        if not rel_path or not (pathlib.Path(st.root) / "library" / rel_path).is_file():
            problems.append(f"literature.path 指不到 library 下的字节：{rel_path!r}")

    # 3. B 的消化：关系一行、状态 active、引文是逐字命中。
    relations = reading["relations"]
    if len(relations) != 1:
        problems.append(f"relations 应恰好 1 行（逐字回验过后），实得 {len(relations)} 行")
    else:
        rel = relations[0]
        if str(rel.get("status") or "") != "active":
            problems.append(f"关系不是 active：{rel.get('status')!r}")
        if "逐字命中" not in str(rel.get("quote_reason") or ""):
            problems.append(f"关系的 quote_reason 没记逐字命中：{rel.get('quote_reason')!r}")

    # 4. 概念行两条，且关系两端都在册。
    names = {str(c.get("name") or "") for c in reading["concepts"]}
    if names != {"abelian group", "group"}:
        problems.append(f"概念行不是抽取器给的那两条：{sorted(names)}")

    # 5. 派活的终态：三行 tasks、都 ok。
    got = [(str(t.get("role") or ""), str(t.get("action") or ""),
            str(t.get("outcome") or "")) for t in reading["tasks"]]
    want = [("A", "search_literature", "ok"), ("A", "ingest_local", "ok"),
            ("B", "run_once", "ok")]
    if sorted(got) != sorted(want):
        problems.append(f"tasks 的三行终态不对：{got}（期望 {want}）")

    # 6. 钱：B 真花过钱，且 tasks 与账本逐分相等。
    b_rows = [t for t in reading["tasks"] if str(t.get("action") or "") == "run_once"]
    if not b_rows:
        problems.append("tasks 里没有 B.run_once 那一行，钱无从对账")
    else:
        row = b_rows[0]
        if int(row.get("tokens") or 0) <= 0 or float(row.get("usd") or 0.0) <= 0:
            problems.append(f"B 那一行没有花销读数：tokens={row.get('tokens')!r} "
                            f"usd={row.get('usd')!r}")
        ledger_sum = round(sum(float(u.get("usd") or 0.0) for u in reading["ledger"]
                               if str(u.get("task_id") or "") == str(row.get("task_id"))), 6)
        if round(float(row.get("usd") or 0.0), 6) != ledger_sum:
            problems.append(f"B 那一行 tasks.usd={row.get('usd')!r} 与账本 {ledger_sum} 不等")
    money = reading["money"]
    if money.get("equal") is not True:
        problems.append(f"Σtasks.usd 与 Σusage_ledger.usd 不等：{money}")
    if not float(money.get("ledger_usd") or 0.0) > 0:
        problems.append(f"这次链路一分钱都没花 —— 钱那一格是空转：{money}")
    return problems


# ============================================================ ① 正控：链走通


def test_the_literature_chain_runs_end_to_end(tmp_path):
    """正控：M→A 两步→B 一步，六条终态读数全对（盘上 / 台账上，不看 ok=True）。"""
    reading = _run_chain(tmp_path)
    problems = _chain_problems(reading)
    assert problems == [], problems

    # 回执里那两条读数也核一眼：A 的检索"查到了但全在待裁"与"一条都没检索到"不同形。
    assert reading["search_payload"].get("outcome") == "no_results", reading["search_payload"]
    assert reading["ingest_payload"].get("ingested") == 1, reading["ingest_payload"]
    # 钱的那一格按"逐分相等"读（不是拿两处各算一遍但愿它们相等）。
    money = reading["money"]
    assert money["tasks_usd"] == money["ledger_usd"] > 0, money
    assert money["diff_usd"] == 0.0 and money["unattributed"]["count"] == 0, money
    assert money["named_residual"] == [] and money["dangling"] == [], money


# ============================================================ ② 反真空：打坏 B 那一环


def test_a_quote_that_is_not_verbatim_turns_the_chain_red(tmp_path):
    """反真空（B 那一环）：模型给的引文不在正文里 ⇒ 关系必须被剔除，判据必须红。

    打桩的是"模型说的那句话"（`quote`），不是判据：真 `LLMExtractor` 的逐字回验是
    产品本体，它整条剔除幻觉关系的动作一个字没改。若这一条不红，第 3 条判据就只是
    "抽过一次 ⇒ 必有一行"，而不是"引文真的在原文里"。
    """
    reading = _run_chain(tmp_path, quote="这是模型编出来的一句原文里没有的话。")
    assert reading["gateway"].calls > 0, "反真空没真的问过模型（缝一次都没被调）"
    problems = _chain_problems(reading)
    assert problems, "引文不是逐字命中，链却读成了通 —— 第 3 条判据是橡皮图章"
    assert any("relations" in p for p in problems), problems
    # 只该红在关系那一格：文献仍然登记并消化了（定位不是"整条链都炸了"）。
    assert [r["processed"] for r in reading["literature"]] == [True], reading["literature"]


# ============================================================ ③ 反真空：打坏 A 那一环


def test_an_empty_books_dir_turns_the_chain_red(tmp_path):
    """反真空（A 那一环）：`books_dir` 是空目录 ⇒ 一条 literature 都不落、判据必须红。

    打桩的是"盘上有没有书"（A 的输入），不是 A 的实现：`ingest_local` 照常走
    `locallib.ingest_directory` 的真判重与真事务。若这一条不红，第 2 条判据就只是
    "跑过 ingest_local"，而不是"书真的登记进来了"。
    """
    reading = _run_chain(tmp_path, books_dir="empty_books")
    assert reading["ingest_payload"].get("ingested") == 0, reading["ingest_payload"]
    assert reading["ingest_payload"].get("kind") == "nothing_matched", (
        "空目录应当读成'没匹配上文件'，而不是'读不了'：", reading["ingest_payload"])
    problems = _chain_problems(reading)
    assert problems, "一条文献都没登记，链却读成了通 —— 第 2 条判据是橡皮图章"
    assert any("literature" in p for p in problems), problems
    # B 那一行要如实说"没有可消化的"（`no_result`），不是假装做完了。
    assert reading["digested"]["outcome"] == "no_result", reading["digested"]
    assert reading["digest_payload"].get("processed") == 0, reading["digest_payload"]


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
