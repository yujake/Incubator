# -*- coding: utf-8 -*-
"""彩排（真路径）C1 · 文献链：CLI 入口 → A 检索/本地收录 → B `run_once` 真抽取 + 逐字回验。

## 这条链与真机差在哪（逐项，不许含糊）

| 这一趟用的东西 | 真机 | 这份彩排 |
|---|---|---|
| 入口 | `agentflow start --mode research` | 同一行：`cli.main(["start", "--mode", "research", …])` |
| 执行体 | `_run_spec` → `_exec_role` → `host.wired_llm_conductor` → `LlmBackend` → `AgentLoop.run` | 同一条（一次都没绕开） |
| 派活 | `Conductor.summon`（`M→A`、`A→B` 都是 `ALLOWED_EDGES` 里的真边） | 同一条 |
| 角色实现 | `AgentA.search_literature/ingest_local`、`AgentB.run_once` | 同一条（`own.*` / `search.*` 工具走 `LocalBackend` 的真实现） |
| 抽取 | `LLMExtractor` → `modelclient.client_from_env` → 网关 | 同一条（真 `LLMExtractor`、真 `b_extractor` 装配） |
| 文献解析 | `extract.extract_text`（`.txt` 走原生解码分支，不碰 PDF 后端） | 同一条：盘上真的是一份 `.txt` 藏书 |
| 检索源 | provider（HTTP） | `--provider fixture`（产品自带的离线 provider，读工作区里的 candidates.json） |
| 模型缝 | 真 `LlmSeam`（`_agent_seam_factory` / `for_role` / `for_secretary`） | 同一条：构造点一个都没替换 |
| 记账 | 真 `TokenMeter` → `usage_ledger` | 同一条 |
| 出网 | `modelgw.urllib_transport`（HTTP POST） | 只换这一处：回预置的 OpenAI 兼容 JSON |
| 模型 key | 机器上那把 | env `AGENTFLOW_MODEL_API_KEY` 给一个假值（只用来让"配置已就绪"成立） |

旧 `test_rehearsal_c1_literature_chain.py`（`CHAIN_ONLY` 里那份）入口是 `Conductor.summon`
（比 CLI 低一层）且把 `locallib.extract_text` 换掉了。这一份两处都不换：`extract_text`
真的读了盘上的 `.txt`，入口真的走 `_run_spec`。

## 这条链覆盖什么（业主点名的 C1）

```text
M --summon--> A --search_literature--> 检索请求一行（查过、没有 ⇒ no_results 是有效结论）
                --ingest_local-->      books/ 下的 .txt 真登记：library/ 字节 + literature 一行
                --summon--> B --run_once--> 真 LLMExtractor 抽概念与关系 + 逐字引文回验
```

判据读盘（不看回执的 `ok=True`）：`search_requests` 两行（`no_results` / `ok`）、
`literature` 一行且 `processed=True`、`relations` 一行且 `quote_reason` 记的是逐字命中、
概念两行、`tasks` 的 A/B 两行 `outcome="ok"`、钱账逐分相等且无主 0。

## 反真空（两条）

- 引文换成原文里没有的句子 ⇒ 真 `LLMExtractor` 的逐字回验必须把关系剔掉
  （`relations` 0 行、`quotes_failed>=1`）⇒ 链判据必须红。它证明「关系那一行」读的是
  「引文真的在原文里」，不是「只要抽过就有一行」。
- `books_dir` 指向空目录 ⇒ 一条 `literature` 都不落 ⇒ B 只能 `no_result` ⇒ 链判据必须红。

## Lean 两档

`AGENTFLOW_LEAN_ENABLED` 开/关各跑一遍：文学链与形式化开关无关，但「两档都干净」必须
自己说出来（关档尤其重要：这是旧 14 份彩排里链级覆盖为 0 的那一档）。
"""
from __future__ import annotations

import io
import json
import pathlib
import re
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

import pytest

import rehearsal_contract as RC

from agentflow import cli
from agentflow import conceptrows as CR
from agentflow import leanscope as LS
from agentflow import modelgw as MG
from agentflow.store import Store

SID = "cc3-c1"

#: 这是一份真的 `.txt` 藏书（`extract.extract_text` 的原生分支；不装 PDF 后端）。
TEXT = ("An abelian group is a group in which the commutative law holds. "
        "Every subgroup of an abelian group is normal.")
QUOTE = "An abelian group is a group in which the commutative law holds."

#: 预置的抽取回复（`LLMExtractor` 的提示词以「你是文献知识抽取器」开头）。
EXTRACTION = {
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
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _roster_names(prompt: str) -> list[str]:
    """从派活结果里读名册名（`roster_name` 是父子之间唯一的指称）。"""
    return [m.group(1) for m in re.finditer(r'"roster_name":\s*"([A-Z]\d*)"', prompt)]


class _Wire:
    """预置的网络传输层替身（与 `modelgw.urllib_transport` 同签名）。

    它不是缝：预算闸 / 账本 / `llm_call` 事件 / ambient 解析全在真 `LlmSeam` 上；
    这里只回答"上游那一端收到了什么、回了什么"。剧本按角色与提示词分派。
    """

    def __init__(self, *, quote: str = QUOTE, books_dir: str = "books") -> None:
        self.quote = str(quote)
        self.books_dir = str(books_dir)
        self.bodies: list[dict[str, Any]] = []
        self._steps: dict[str, int] = {}

    # ------------------------------------------------------------ 剧本
    def _retire_or_final(self, prompt: str, done: list[str]) -> str:
        """名册里还有没销号的 → 销一个；都销完了 → final（整树销号是 M 的 final 闸）。"""
        todo = [n for n in _roster_names(prompt) if n not in done]
        if todo:
            done.append(todo[0])
            return _json({"tool": "conductor.retire_child",
                          "args": {"child_name": todo[0], "reason": "交完了"}})
        return _json({"final": "收工", "evidence": []})

    def _step(self, role: str, prompt: str) -> str:
        index = self._steps.get(role, 0)
        self._steps[role] = index + 1
        done = self._steps.setdefault(f"{role}:retired", [])  # type: ignore[arg-type]
        if role == "M":
            if index == 0:
                return _json({"summon": {"role": "A", "task": "检索并收录本地文献"}})
            return self._retire_or_final(prompt, done)  # type: ignore[arg-type]
        if role == "A":
            seq = [
                _json({"tool": "own.search_literature",
                       "args": {"topic": "abelian group", "mode": "topical",
                                "description": "abelian group"}}),
                _json({"tool": "search.ingest_local",
                       "args": {"books_dir": self.books_dir, "pattern": "*.txt"}}),
                _json({"summon": {"role": "B", "task": "消化已登记的文献"}}),
            ]
            if index < len(seq):
                return seq[index]
            return self._retire_or_final(prompt, done)  # type: ignore[arg-type]
        if role == "B":
            if index == 0:
                return _json({"tool": "own.run_once", "args": {}})
            return _json({"final": "B 消化完了", "evidence": []})
        return _json({"final": f"{role} 收工", "evidence": []})

    def _reply(self, system: str, prompt: str) -> str:
        head = system.lstrip()
        both = head + "\n" + prompt.lstrip()
        m = re.match(r"你是「秘书」的判断面（类别：([a-z_]+)）", head)
        if m:
            table = {
                "statement_aesthetic": {"decision": "T2", "reason": "彩排", "basis": ["夹具"]},
                "proposition_identity": {"decision": "same", "reason": "彩排",
                                         "basis": ["夹具"], "canonical_name": "群",
                                         "same_as": "", "route": "", "condition": "夹具",
                                         "conclusion": "夹具"},
                "proof_kind": {"decision": "same", "reason": "彩排", "basis": ["夹具"],
                               "same_path": 1},
                "dispatch_fit": {"decision": "这一件能做", "reason": "彩排",
                                 "basis": ["夹具"]},
            }
            return _json(table.get(m.group(1), {"decision": "可派", "reason": "彩排",
                                                "basis": ["夹具"]}))
        if both.lstrip().startswith("你是文献知识抽取器"):
            payload = json.loads(_json(EXTRACTION))
            payload["relations"][0]["quote"] = self.quote
            return _json(payload)
        if head.startswith("你是「命题形态闸」"):
            return _json({"well_formed": True, "conditions": "夹具", "conclusion": "夹具",
                          "problems": [], "decision": "形态合规", "refused": "",
                          "reason": "彩排"})
        m = re.match(r"你是 ([A-Z]) 号角色", head)
        if m:
            return self._step(m.group(1), prompt)
        return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["夹具"]})

    # ------------------------------------------------------------ 传输
    def __call__(self, url: str, headers: Any, body: bytes,
                 timeout_sec: float) -> tuple[int, str]:
        payload = json.loads(body.decode("utf-8"))
        messages = payload.get("messages") or []
        system = next((str(x.get("content") or "") for x in messages
                       if x.get("role") == "system"), "")
        prompt = "\n".join(str(x.get("content") or "") for x in messages
                           if x.get("role") == "user")
        text = self._reply(system, prompt)
        # `kind`：抽取那一笔走 `modelclient`（不经 `LlmSeam`，因此不落 `llm_call`），
        # 判据①要把它从「真缝调用」里分出去 —— 两件事不是同一个审计面。
        kind = ("extract" if (system.lstrip() + "\n" + prompt.lstrip()).lstrip()
                .startswith("你是文献知识抽取器") else "seam")
        self.bodies.append({"system": system, "prompt": prompt, "text": text, "kind": kind})
        return 200, json.dumps({"choices": [{"message": {"content": text},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 8, "completion_tokens": 8}},
                               ensure_ascii=False)


# ============================================================ 夹具


def _workspace(base: pathlib.Path) -> Store:
    """真工作区：`books/` 下一本真 `.txt` 藏书；`empty_books/` 是反真空用的空目录。

    `demo/fixtures/candidates.json` 是空的 —— `--provider fixture` 因此真的走到
    "查过、没有结果"这一档（那是有效结论，不是失败）。
    """
    st = Store(base / "ws")
    st.init()
    root = pathlib.Path(st.root)
    (root / "books").mkdir(parents=True, exist_ok=True)
    (root / "books" / "notes.txt").write_text(TEXT, encoding="utf-8")
    (root / "empty_books").mkdir(parents=True, exist_ok=True)
    # 2026-11-21 起非 dry 档按用户声明核（fail-closed：没点名的不许入库）。
    # 这一组判的是 M→A→B 那条链本身，所以把 books/ 整目录声明成用户点名的可靠参考文献。
    (root / "RELIABLE-REFERENCES.json").write_text(
        json.dumps({"paths": ["books/"], "verbatim": "books/ 里都是可靠参考文献"},
                   ensure_ascii=False),
        encoding="utf-8")
    (root / "demo" / "fixtures").mkdir(parents=True, exist_ok=True)
    (root / "demo" / "fixtures" / "candidates.json").write_text("[]", encoding="utf-8")
    return st


def _run(base: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
         lean: str = "0", quote: str = QUOTE, books_dir: str = "books") -> dict[str, Any]:
    """从 CLI 入口真跑一趟；只替换出网那一层（+ 一个假 key）。"""
    st = _workspace(base)
    wire = _Wire(quote=quote, books_dir=books_dir)
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "rehearsal-fake-key-never-used")
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", str(lean))
    monkeypatch.setattr(MG, "urllib_transport", wire)
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main([
                "start", "--mode", "research", "--root", str(st.root),
                "--sid", SID, "--provider", "fixture", "--subagents",
                "--task", f"检索并收录 abelian group 文献（books_dir={books_dir}）",
                "--max-steps", "8",
            ])
    except SystemExit as exc:                     # `cli.main` 正常是 return，不是 raise
        rc = int(exc.code or 0)
    return {"rc": int(rc), "ws": pathlib.Path(st.root), "store": Store(st.root),
            "wire": wire, "stdout": out.getvalue(), "stderr": err.getvalue()}


def _events(ws: pathlib.Path) -> list[dict]:
    """这一趟的会话事件（不按 sid 过滤：任何一条都算这一趟的审计面）。"""
    got: list[dict] = []
    for path in sorted((ws / "sessions").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                got.append(json.loads(line))
            except ValueError:
                continue
    return got


def _tool_result(events: list[dict], *, role: str, tool: str) -> dict:
    for e in events:
        if (e.get("kind") == "agent_step" and e.get("role") == role
                and e.get("shape") == "tool"
                and str((e.get("payload") or {}).get("name") or "") == tool):
            return dict(e.get("result") or {})
    raise AssertionError(f"{role} 没有调过工具 {tool}（会话事件里找不到）")


def _rows(store: Store, table: str) -> list[dict]:
    return [dict(r) for r in store.rows(table)]


def _digest_of(result: dict) -> dict[str, Any]:
    """`B.run_once` 的回执读数。

    会话事件是按 JSON 落盘的，`BRunResult`（dataclass）在那一刻被 `default=str` 折成了
    `BRunResult(processed=1, …)` 这一串文本 —— 所以这里从那一串文本里读回需要的两格，
    而不是假装它是 dict（假装会让读数恒为 0，反真空也跟着假绿）。
    """
    data = result.get("data")
    if hasattr(data, "to_dict"):
        return dict(data.to_dict())
    if isinstance(data, dict):
        return data
    text = str(data or "")
    out: dict[str, Any] = {}
    for key in ("processed", "quotes_verified", "quotes_failed", "relations_added",
                "relations_suspect", "suspect_by_quote", "quotes_unknown",
                "concepts_created", "skipped_no_extractor", "failed"):
        m = re.search(rf"\b{key}=(-?\d+)", text)
        if m:
            out[key] = int(m.group(1))
    return out


def _chain_reading(got: dict[str, Any], *, books_dir: str = "books") -> dict[str, Any]:
    """把盘上的终态读成一份读数（正控与反真空用同一份量法）。"""
    ws, st = got["ws"], got["store"]
    events = _events(ws)
    digest = _tool_result(events, role="B", tool="own.run_once")
    return {
        "store": st,
        "ws": ws,
        "events": events,
        "digest": _digest_of(digest),
        "digest_ok": bool(digest.get("ok")),
        "books_dir": books_dir,
        "requests": _rows(st, "search_requests"),
        "literature": _rows(st, "literature"),
        "relations": _rows(st, "relations"),
        "concepts": [dict(r) for r in CR.view(st, shape="legacy")["rows"]],
        "tasks": _rows(st, "tasks"),
        "wire": got["wire"],
    }


# ============================================================ 判据本体


def _chain_problems(reading: dict[str, Any]) -> list[str]:
    """C1 的六条终态读数（空 = 通）。每条都读盘，不看回执里的 `ok`。"""
    problems: list[str] = []
    st: Store = reading["store"]
    root = pathlib.Path(st.root)

    # 1. A 的检索：入队一行、查过、结论是"没有"（不是"没查成"）。
    requests = reading["requests"]
    search = [r for r in requests if str(r.get("outcome") or "") == "no_results"]
    if len(search) != 1:
        problems.append(f"A 的检索请求行应恰好 1 行 no_results，实得 {len(search)} 行："
                        f"{[(r.get('outcome'), r.get('topic')) for r in requests]}")
    else:
        req = search[0]
        if str(req.get("topic") or "") != "abelian group":
            problems.append(f"A 的检索主题不对：{req.get('topic')!r}")
        if req.get("done") is not True:
            problems.append(f"A 的检索请求没收口：done={req.get('done')!r}")

    # 2. A 的入库：literature 一行、已消化、字节在 library 下。
    lit = reading["literature"]
    if len(lit) != 1:
        problems.append(f"literature 应恰好 1 行，实得 {len(lit)} 行")
    for row in lit:
        if row.get("processed") is not True:
            problems.append(f"literature 没被 B 消化（processed={row.get('processed')!r}）")
        rel_path = str(row.get("path") or "")
        if not rel_path or not (root / "library" / rel_path).is_file():
            problems.append(f"literature.path 指不到 library 下的字节：{rel_path!r}")

    # 3. B 的消化：关系一行、状态 active、引文是逐字命中（真 LLMExtractor 的回验）。
    relations = reading["relations"]
    if len(relations) != 1:
        problems.append(f"relations 应恰好 1 行（逐字回验过后），实得 {len(relations)} 行")
    for rel in relations:
        if str(rel.get("status") or "") != "active":
            problems.append(f"关系不是 active：{rel.get('status')!r}")
        if "逐字命中" not in str(rel.get("quote_reason") or ""):
            problems.append(f"关系的 quote_reason 没记逐字命中：{rel.get('quote_reason')!r}")

    # 4. 概念行两条（抽取器给的那两条）。
    names = {str(c.get("name") or "") for c in reading["concepts"]}
    if names != {"abelian group", "group"}:
        problems.append(f"概念行不是抽取器给的那两条：{sorted(names)}")

    # 5. 抽取回执：真的抽过、且逐字回验过。
    digest = reading["digest"]
    if not reading["digest_ok"]:
        problems.append("B 的 run_once 回执不是 ok")
    if int(digest.get("quotes_verified") or 0) != 1:
        problems.append(f"逐字回验通过的引文应 1 条：{digest.get('quotes_verified')!r}")
    if int(digest.get("quotes_failed") or 0) != 0:
        problems.append(f"逐字回验失败的引文应 0 条：{digest.get('quotes_failed')!r}")
    if int(digest.get("relations_added") or 0) != 1:
        problems.append(f"入账的关系应 1 条：{digest.get('relations_added')!r}")

    # 6. 派活的终态：A / B 两行都 ok。
    by_role = {str(t.get("role")): t for t in reading["tasks"]
               if not str(t.get("kind") or "") and str(t.get("role")) in ("A", "B")}
    if set(by_role) != {"A", "B"}:
        problems.append(f"tasks 里 A/B 两行不齐：{sorted(by_role)}")
    else:
        for role in ("A", "B"):
            if str(by_role[role].get("outcome")) != "ok":
                problems.append(f"{role} 的 outcome 不是 ok：{by_role[role].get('outcome')!r}")
    return problems


# ============================================================ ① 正控：链走通（Lean 关）


def test_the_literature_chain_runs_from_the_cli_with_only_the_wire_replaced(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：M→A 两步→B 一步，六条终态读数全对（盘上，不看回执里的 ok=True）。"""
    got = _run(tmp_path, monkeypatch, lean="0")
    reading = _chain_reading(got)

    # ---- 入口与"只换了网线"（两步都不能省）
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    assert got["wire"].bodies, "出网层一次都没被调到 ⇒ 这一趟没有真模型调用"
    assert MG.urllib_transport is got["wire"], "出网层没被替换（这一条会打真网络）"
    assert cli._agent_seam_factory.__module__ == "agentflow.cli", (
        "缝工厂被整体替换了 —— 这份彩排的承诺是「只换网线」，不是「换掉造缝的那一层」")
    # 真 LlmSeam 落下的审计记录（不是替身缝：替身缝不落 llm_call 事件）
    live = [e for e in reading["events"] if e.get("kind") == "llm_call"]
    assert live, "会话里一条 llm_call 都没有 ⇒ 走的不是真 LlmSeam"

    # ---- 抽取走的是真 LLMExtractor（`b_extractor` 装配），不是规则档
    extraction = [b for b in got["wire"].bodies
                  if b["system"].lstrip().startswith("你是文献知识抽取器")
                  or b["prompt"].lstrip().startswith("你是文献知识抽取器")]
    assert extraction, "这一趟没有问过抽取器 ⇒ B 走的不是 LLMExtractor"

    # ---- 六条盘上读数
    problems = _chain_problems(reading)
    assert problems == [], problems
    assert reading["requests"] and any(
        str(r.get("outcome")) == "no_results" for r in reading["requests"])

    # ---- 钱：账本有行、无主为 0、没有悬空号、逐分相等
    from agentflow.modelcost import reconcile_usage

    money = reconcile_usage(reading["store"])
    assert money["usage_ledger_rows"] > 0, money
    assert money["unattributed"]["count"] == 0, money["unattributed"]
    assert money["dangling"] == [], money["dangling"]
    assert money["equal"] is True, money


# ============================================================ ② 反真空：引文不是逐字


def test_a_quote_that_is_not_verbatim_turns_the_chain_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空（B 那一环）：模型给的引文不在正文里 ⇒ 关系必须被剔除，判据必须红。

    打桩的是"模型说的那句话"（预置回复里的 `quote`），不是判据：真 `LLMExtractor`
    的逐字回验是产品本体，它整条剔除幻觉关系的动作一个字没改。若这一条不红，第三条
    判据就只是"抽过一次 ⇒ 必有一行"，而不是"引文真的在原文里"。
    """
    got = _run(tmp_path, monkeypatch, lean="0",
               quote="这是模型编出来的一句原文里没有的话。")
    reading = _chain_reading(got)
    assert got["wire"].bodies, "反真空没真的问过模型"
    problems = _chain_problems(reading)
    assert problems, "引文不是逐字命中，链却读成了通 —— 第三条判据是橡皮图章"
    assert any("relations" in p or "逐字" in p for p in problems), problems
    # 只该红在关系那一格：文献仍然登记并消化了（定位不是"整条链都炸了"）。
    assert [r.get("processed") for r in reading["literature"]] == [True], reading["literature"]
    # 抽取真的跑过（概念两行），但那条引文回验不过的关系一条都没入账。
    assert int(reading["digest"].get("concepts_created") or 0) == 2, reading["digest"]
    assert int(reading["digest"].get("relations_added") or 0) == 0, reading["digest"]
    assert reading["relations"] == [], reading["relations"]


# ============================================================ ③ 反真空：空书架


def test_an_empty_books_dir_turns_the_chain_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空（A 那一环）：`books_dir` 是空目录 ⇒ 一条 literature 都不落、判据必须红。

    打桩的是"盘上有没有书"（A 的输入），不是 A 的实现：`ingest_local` 照常走真判重与
    真事务。若这一条不红，第二条判据就只是"跑过 ingest_local"，而不是"书真的登记进来了"。
    """
    got = _run(tmp_path, monkeypatch, lean="0", books_dir="empty_books")
    reading = _chain_reading(got, books_dir="empty_books")
    problems = _chain_problems(reading)
    assert problems, "一条文献都没登记，链却读成了通 —— 第二条判据是橡皮图章"
    assert any("literature" in p for p in problems), problems
    # B 那一行要如实说"没有可消化的"（`processed=0`），不是假装做完了。
    assert int(reading["digest"].get("processed") or 0) == 0, reading["digest"]
    assert reading["relations"] == [], reading["relations"]


# ============================================================ 判据①：每笔真调用一行账


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_real_call_has_exactly_one_ledger_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据①：这一趟的每一次真调用，`usage_ledger` 里有且只有一行（Lean 开/关各一遍）。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    reading = RC.ledger_identity(got["ws"], got["store"])
    seam_bodies = [b for b in got["wire"].bodies if b["kind"] == "seam"]
    print(f"[一行账] lean={lean} 真调用={reading['calls']} 出网={len(seam_bodies)} "
          f"（另有一次抽取走 modelclient，不经 LlmSeam） "
          f"账本行={reading['rows']} duplicate={len(reading['duplicates'])} "
          f"未配对={len(reading['unpaired'])} 未认领={len(reading['unclaimed'])}")
    assert reading["calls"] == len(seam_bodies), (
        "有真缝调用没有落 `llm_call` 事件（或反之）："
        f"事件 {reading['calls']} / 出网 {len(seam_bodies)}")
    problems = RC.one_row_per_call_problems(reading)
    assert problems == [], "判据①红：\n- " + "\n- ".join(problems)


# ============================================================ 判据②：会话归口


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_llm_call_lands_in_this_runs_session(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据②：这一趟所有 `llm_call` 事件都落在本趟 `sid`，缺省会话 0 条。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    split = RC.session_split(got["ws"], SID)
    print(f"[会话归口] lean={lean} 本趟={len(split['in_run'])} "
          f"别处={len(split['elsewhere'])} 会话={sorted(split['by_session'])}")
    assert split["calls"], "这一趟一次真调用都没有 ⇒ 判据没有对象（不是干净）"
    problems = RC.session_problems(split)
    assert problems == [], "判据②红：\n- " + "\n- ".join(problems)


# ============================================================ Lean 两档的开关读数


@pytest.mark.parametrize("lean,verdict,hidden", [("1", "on", False), ("0", "off", True)])
def test_the_switch_reading_matches_and_l_is_isolated_when_off(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        lean: str, verdict: str, hidden: bool) -> None:
    """Lean 开/关两档的开关读数（链本身与开关无关，但两档都要自己说出来）。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-1500:], got["stderr"][-1500:])
    reading = LS.lean_reading()
    assert reading.verdict == verdict, reading.to_dict()
    assert LS.is_hidden("L") is hidden, (lean, reading.to_dict())
    assert _chain_problems(_chain_reading(got)) == [], _chain_problems(_chain_reading(got))
    # 名册（`visible_roles`）才是"关档下 L 不存在"的落点：这条链不会派 L，
    # 所以任务表里本来就没有 L 的行 —— 拿任务行断言会让开关读数变成假判据。
    from agentflow import schema as S

    roles = set(LS.visible_roles(S.ROLES))
    assert ("L" in roles) is (not hidden), sorted(roles)


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
