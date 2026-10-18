"""判据（修法 2）：`G8` 在 H 参与的一趟里**不可能只因权限而恒为 `unknown`**。

## 这一条修的是哪一个现场读数

- `projects/mp3` 末节第 4 条逐字：「**H 的 G8 未知**：没人（H 只读、拿不到执行工具）
  在审校轮里重跑那四个脚本，可复跑门只能记 unknown」；
- `projects/t3d` 三·4 逐字：「H 第五轮 **G8/G11 为 unknown**：H 只读、无执行面」。/

两次 unknown 的成因完全相同：H 的工具面里没有任何 `external == "exec"` 的入口
（这是"只读"的结构定义，不该改），而旧实现里 `run_evidence` **只能由 H 自己造**
——于是"H 参与的一趟"里 G8 的结构上限就是 unknown。

## 修法（选的是 (b)：M 代跑、H 判回执 —— 实现代价小的那一条）

(a) 给 H 一个受控执行面要新开一层"只允许跑 ACCEPTANCE-CHECKS.json 里登记过的命令"
的沙箱闸，动的是权限面（`tools/base._role_surface` 的 `external == "exec"` 剥除、
`READONLY_CALL_EXCEPTIONS`、`specs/h.py` 的边界）—— 那是 FC-27 auth-audit 的整片改动。
(b) 不需要新的执行面：`run_evidence` 本来就是 `review.report` 的**调用方参数**
（M 派活时给），M 有 `M→E` 的边，E 的 `verify.run_experiment` 会返回 `exit_code`
与 stdout ⇒ 回执可以从"已经在手上的动作返回值"里凑出来。

所以这一趟修的是**判据**，不是权限：G8 现在会
  * 跑过且绿 ⇒ `pass`；
  * 跑过且红（`exit_code != 0`）⇒ `fail`；
  * 没跑 ⇒ `unknown`，**并把"为什么没跑"写成必填**（不写 ⇒ 那一条 unknown 自带一条 finding）；
  * 回执读不懂（不是数组 / 缺 `exit_code` / 缺 `output_tail`）⇒ `unknown`（不是 pass）。

## 负控（每条都证明"修好之前会红"）

本文件每条断言都钉在一个**具体的坏输入**上，而那些坏输入在修好之前的行为是：
  * `commands` 是空白字符串 ⇒ 旧实现读成 `[]`，`numeric=0` ⇒ `pass`（`mp3` round 2 现场）；
  * `checked=true` + `commands=[]` ⇒ 旧实现 `pass`（空回执被读成"覆盖了"）；
  * `exit_code != 0` ⇒ 旧实现根本不读退出码 ⇒ `pass`（红被读成绿）；
  * `checked=false` 不给理由 ⇒ 旧实现 `unknown` 但理由里只有一句"未给"。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import gates as G
from agentflow import schema as S
from agentflow.tools import build_registry
from agentflow.tools import base as TB

from conftest import TS


def _claim(**over: object) -> dict:
    base = {
        "claim_id": "claim-1",
        "kind": "定理",
        "statement": "谱落在区间内。",
        "status": "证",
        "proof_location": "code/p1.py:12",
        "numeric_evidence": {
            "script": "code/p1.py", "range": "d<=33", "n_cases": 256, "n_counterexamples": 0,
        },
        "counterexamples": [],
        "frozen": False,
        "freeze_reason": "",
        "allowed_use": "主结果",
        "scope_caveat": "",
        "revision_hash": "deadbeefdeadbeef",
        "errata_ids": [],
        "evidence_kind": "proof",
        "citations": ["rel:0000"],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": "",
        "section": "主要结果",
    }
    base.update(over)
    return base


def _doc() -> dict:
    return {
        "doc_id": "0000", "kind": "paper", "title": "G8 回执测试稿件",
        "markdown_path": "documents/0000.md", "claims": [_claim()],
        "open_problems": [], "status": "draft", "review_rounds": 0,
        "created_at": TS, "updated_at": TS,
    }


def _doc_with_no_numeric_claims() -> dict:
    """没有任何 `numeric_evidence.script` 的稿件（G8 的"真空"那一格）。"""
    doc = _doc()
    doc["claims"] = [_claim(numeric_evidence={}, status="猜想", evidence_kind="heuristic")]
    return doc


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "code").mkdir(parents=True)
    (root / "documents").mkdir(parents=True)
    (root / "code" / "p1.py").write_text("print('REPRO_RESULT: {}\\n')\n", encoding="utf-8")
    (root / "documents" / "0000.md").write_text("# 稿件\n", encoding="utf-8")
    return root


def _ctx(ws: Path, *, run_evidence: object) -> G.GateContext:
    return G.GateContext.build(
        _doc(), dependencies=[], files=["code/p1.py"], workspace_root=ws,
        run_evidence=run_evidence, findings=[], claim_counts=None, banned_words=[],
        own_errors=[],
    )


def _green_receipt() -> dict:
    return {
        "checked": True,
        "commands": [{"claim_id": "claim-1", "command": "python code/p1.py",
                      "exit_code": 0, "output_tail": "REPRO_RESULT: {}"}],
    }


# ============================================================ 结构：H 没有执行面

def test_h_structurally_has_no_exec_surface(tmp_path: Path) -> None:
    """正控（结构事实）：H 的工具面里没有任何 `exec` 入口 —— 这是"只读"的定义。

    这一条**不许**为了修 G8 而放松：放松它等于给审校者一把能跑任意程序的刀
    （`tools/base._role_surface` 对只读角色剥的就是"写"与"exec"两类）。
    G8 的修法必须建立在"这条事实不变"的前提上。
    """
    root = tmp_path / "ws"
    root.mkdir()
    reg = build_registry(workspace_root=root).registry
    h = [s for s in reg.for_role("H")]
    exec_like = [s.name for s in h if getattr(s, "external", "none") == "exec"]
    assert exec_like == [], f"H 的工具面里出现了 exec 入口：{exec_like}"
    # 反向：E 有（证明"判据不是恒空"—— 真有一条 exec 面时它看得见）
    e_exec = [s.name for s in reg.for_role("E") if getattr(s, "external", "none") == "exec"]
    assert e_exec, "E 的工具面里没有任何 exec —— 这条判据退化成真空"

    # 回执通道的结构前提：`review.report`（唯一接 `run_evidence` 的工具）在 H 的
    # 可调用面里，而它的 `run_evidence` 是**调用方参数**（M 派活时给）。
    assert "review.report" in {s.name for s in h}
    props = next(s for s in h if s.name == "review.report").params["properties"]
    assert "run_evidence" in props, props


# ============================================================ 四态：可判，不许恒 unknown

def test_g8_passes_on_a_green_receipt(ws: Path) -> None:
    """跑过且绿 ⇒ `pass`（H 参与的一趟里 `pass` 是可达的）。"""
    r = G.gate_g8(_ctx(ws, run_evidence=_green_receipt()))
    assert r.verdict == "pass", (r.verdict, r.reason)
    assert r.counts["退出码非零"] == 0, r.counts


def test_g8_fails_on_a_red_receipt(ws: Path) -> None:
    """跑过且红 ⇒ `fail`（负控：旧实现不读 `exit_code`，这一条在修好前会是 `pass`）。

    为什么这一条是本修法的核心：验收口径要求"跑过且红 ⇒ fail"，而旧实现只看
    `claim_id` 覆盖，于是"命令跑挂了"与"命令跑绿了"在门上同形 —— 这正是
    `draft/17` 那句"未报错被误读为无问题"的同族。
    """
    ev = _green_receipt()
    ev["commands"][0]["exit_code"] = 2
    ev["commands"][0]["output_tail"] = "Traceback: ..."
    r = G.gate_g8(_ctx(ws, run_evidence=ev))
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["退出码非零"] == 1, r.counts
    assert any("exit_code" in str(f.get("message") or "") for f in r.findings), r.findings


def test_g8_is_unknown_when_the_receipt_has_no_exit_code(ws: Path) -> None:
    """回执缺少 `exit_code` ⇒ `unknown`（不是 pass：分不出绿与红就等于没判）。"""
    ev = _green_receipt()
    ev["commands"][0].pop("exit_code")
    r = G.gate_g8(_ctx(ws, run_evidence=ev))
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert "exit_code" in r.reason, r.reason


def test_g8_is_unknown_when_the_receipt_is_a_blank_string(ws: Path) -> None:
    """负控（真机现场）：`commands` 是空白字符串 ⇒ `unknown`。

    `projects/mp3` round 2 的 H 就是这么传的：
    `{"checked": true, "commands": "     "}`。旧实现遍历那个字符串（每个字符都不是
    Mapping）得到 `[]`，而那一轮 `numeric = 0` ⇒ **G8 = pass**，报告里写着
    "0 条实跑记录覆盖全部数值断言"。
    """
    r = G.gate_g8(_ctx(ws, run_evidence={"checked": True, "commands": "     "}))
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert "回执" in r.reason and "str" in r.reason, r.reason


def test_g8_is_unknown_on_an_empty_receipt(ws: Path) -> None:
    """负控：`checked=true` 而 `commands=[]` ⇒ `unknown`（空回执不是"覆盖了全部"）。

    用一份**没有数值断言**的稿件：旧实现在这一格上是 `pass`（"0 条实跑记录覆盖
    全部数值断言"—— 真空通过）。有数值断言时同一条输入应当 `fail`（差集非空），
    那是另一条判据（见下面 `test_g8_still_fails_when_a_numeric_claim_is_missing`）。
    """
    ctx = G.GateContext.build(
        _doc_with_no_numeric_claims(), dependencies=[], files=["code/p1.py"],
        workspace_root=ws, run_evidence={"checked": True, "commands": []},
        findings=[], claim_counts=None, banned_words=[], own_errors=[],
    )
    r = G.gate_g8(ctx)
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert "空的" in r.reason, r.reason


def test_g8_still_fails_when_a_numeric_claim_is_missing(ws: Path) -> None:
    """不许削弱：差集（数值断言没有对应实跑记录）仍然是 `fail`，且优先于回执形状。"""
    r = G.gate_g8(_ctx(ws, run_evidence={"checked": True, "commands": []}))
    # 这一份上下文的 claims 里 `numeric_evidence.script` 非空 ⇒ 差集非空 ⇒ fail
    assert r.verdict == "fail", (r.verdict, r.reason)
    assert r.counts["缺命令"] == 1, r.counts
    # 覆盖了另一个 claim 也算差集（不是"有记录就行"）
    ev = _green_receipt()
    ev["commands"][0]["claim_id"] = "claim-9"
    r2 = G.gate_g8(_ctx(ws, run_evidence=ev))
    assert r2.verdict == "fail", (r2.verdict, r2.reason)
    assert r2.counts["缺命令"] == 1, r2.counts


def test_g8_unknown_must_say_why_it_did_not_run(ws: Path) -> None:
    """`unknown` 不许静默：`checked=false` 而没给理由 ⇒ 理由里点名"没写"，并留一条 finding。"""
    r = G.gate_g8(_ctx(ws, run_evidence={"checked": False}))
    assert r.verdict == "unknown", (r.verdict, r.reason)
    assert "没有写" in r.reason and "为什么没跑" in r.reason, r.reason
    assert any(f.get("target") == "run_evidence.reason" for f in r.findings), r.findings

    ok = G.gate_g8(_ctx(ws, run_evidence={"checked": False,
                                          "reason": "H 只读、无执行面；回执由 M 代跑后交来"}))
    assert ok.verdict == "unknown"
    assert "H 只读、无执行面" in ok.reason, ok.reason
    assert ok.counts["没跑的理由"] == "H 只读、无执行面；回执由 M 代跑后交来", ok.counts
    assert not ok.findings, "给了理由还报 finding ⇒ 判据把合规的第三态也当成缺陷"


# ============================================================ 通道被写进两边的 brief

def test_the_conductor_brief_tells_it_to_carry_the_receipt() -> None:
    """M 的 brief 必须写清"回执由谁凑、四个键是什么"（否则 G8 照样靠天吃饭）。"""
    from agentflow.specs.m import SPEC

    text = "\n".join(SPEC.brief.policy)
    for needle in ("run_evidence", "verify.run_experiment", "exit_code",
                   "output_tail", "为什么没跑"):
        assert needle in text, f"M 的 brief 里没有 {needle!r}（G8 的回执就没有产出口径）"


def test_the_reviewer_brief_tells_it_to_judge_the_receipt() -> None:
    """H 的 brief 必须写清"你判回执合不合格"，而不是"你跑不了所以只能 unknown"。"""
    from agentflow.specs.h import SPEC

    text = "\n".join(SPEC.brief.boundary) + "\n" + "\n".join(SPEC.brief.policy)
    for needle in ("run_evidence", "exit_code", "回执", "为什么没跑"):
        assert needle in text, f"H 的 brief 里没有 {needle!r}（G8 的判读口径不完整）"


def test_the_receipt_vocabulary_is_one_definition() -> None:
    """回执的四个键只有一份定义（`gates.G8_RECEIPT_KEYS`），且判据真的读它。"""
    assert tuple(G.G8_RECEIPT_KEYS) == ("claim_id", "command", "exit_code", "output_tail")
    assert G.g8_receipt_problems([]) == []
    probs = G.g8_receipt_problems([{"claim_id": "c", "command": "x"}])
    assert len(probs) == 1 and "exit_code" in probs[0] and "output_tail" in probs[0], probs
