# -*- coding: utf-8 -*-
"""`statements` / `dependencies` 只经秘书：正路接通了、野路被封了（带负控）。这一份在治什么（`projects/mp2/sessions/mp2-7.jsonl` 的活证据）：第 94 行：B 调
`register_statement` ⇒ `{"ok": false, "meta": {"kind": "unknown_tool"}}`—— 那个名字不在它的工具面上。
原因是装配漏了一格：`LlmBackend` 只在"派活点了动作"时把动作包成工具（`agent_loop.py` 的 `if str(action):`），而真机的派活是 S2 口径的「只派活、不指定能力」（`tasks.action=""`）⇒
注入一次都没发生。- 第 97 行：B 改走 `table.create(table="statements")`，手写 `evidence_kind="heuristic"`与 `bits={}`。于是秘书那四件活（洗格式 / 发编号 / 查重 / 改表）
与五元位一件没跑，而 `stmt:000003` 明明有 1909 字证明、V 也签了「成立」，档位却停在 `heuristic`。三条判据（每条都带负控 —— 没有负控的绿证明不了任何事）：

| 判据 | 它要的红 |
|---|---|
| ① 正控：一次工具调用 → `own.register_statement` → `Secretary.record_statement` → 落盘 | 走正路落下来的行必须是 `proof_review` + `bits` 非空 + 号由秘书分配 |
| ② 封路正控：`table.create("statements")` 直写 | 必须被拒（`direct_write_refused`），且拒信逐字写出该走哪条路 |
| ③a 负控：把封路钩子 patch 掉 | ② 必须红（直写又通了、`bits` 是 `{}`、档位回到 `heuristic`） |
| ③b 负控：把正路 patch 回"模型手写字段" | ① 的读数必须红（同一组断言，换一条路就判不过） |
| ③c 负控（升档那一格）：把秘书的升档 patch 掉 | ① 的 `evidence_kind` 必须退回 `heuristic` |

为什么 ① 要走"两趟"（先 heuristic、V 签完再交一次）：真机里不可能"先有签名再落行"：`verifications/<命题号>.jsonl` 的键就是落盘时才分配的那个号。所以诚实的顺序是：① 落一行（那时没有签名 ⇒ 如实降档
`heuristic`）→② V 走查签名（`verifications.record_verification` 就是 `verify.verify_proof` 的写入口）→③ B 把同一份内容再交一次并把 `evidence_kind` 写强 ⇒
秘书改那一行（不新建）。第三步就是"升档唯一的正路"：通用写口 `table.update("statements")` 被`store.direct_write_refusal` 拒了，而这条升档路不给出来，`evidence_kind` 在结构上永远到不了
`proof_review`（mp2 的那一行就是这么僵死的）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from conftest import TS, add_literature
from agentflow import schema as S
from agentflow import store as store_mod
from agentflow.agent_b import AgentB
from agentflow.agent_loop import LlmBackend
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import build_registry

PROOF = ("证明（逐行走查的对象）：\n"
         "1. 由引理 1，弦长闭式 L²/4 = N/A²；\n"
         "2. N 的 Fourier 展开无 4φ 成分，而 A² 的 cos4φ 系数是 ν²/2；\n"
         "3. 若 L 恒为常数则 N = k·A² 逐次谐波系数相等 ⇒ 0 = kν²/2 ⇒ 与 k>0 矛盾。∎")
STATEMENT = "设 a≠b 为半轴，椭圆 x²/a²+y²/b²=1 不存在等弦点（弦长函数非常值）。"

#: 一次 `own.register_statement` 的参数（只含动作面声明过的键：那是封闭集合）。
#: `line_range` 是 `origin="own_result"` 的出处那一栏（动作在写库前要它，否则
#: `missing_own_source` —— 真机 `mp2` 那一条也是这么写的：`notes/…md:17-83`）。
_PAYLOAD: dict[str, Any] = {
    "origin": "own_result", "kind": "theorem", "label": "椭圆无等弦点",
    "statement_full": STATEMENT, "proof_text": PROOF,
    "line_range": {"start": 17, "end": 83},
    "quote_verified": None,
    "quote_reason": "own_result：我方推导，没有第二份文本可比对；证明未机器检查",
}


def _payload(**patch: Any) -> dict[str, Any]:
    out = dict(_PAYLOAD)
    out.update(patch)
    return out


class _Scripted:
    """照剧本回答的替身模型：每次取一条，取完重复最后一条。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None, **kw):
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10, "tokens_out": 10,
                                  "error_detail": "", "error_kind": ""})()


def _world(tmp_path: pathlib.Path):
    """一个工作区 + 一张把 B 的真实现接在内层的工具面（真机那条路的缩小版）。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, S.format_id(0), title="Brown 1971")
    inner = LocalBackend({"B": ("object", AgentB(st, extractor=None, extract_text=None))})
    backend = LlmBackend(inner=inner, loops={("B", ""): {"max_steps": 4}},
                         session_root=st.root, store=st, sid="t", max_steps=4)
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond, workspace_root=str(st.root))
    backend.registry = built.registry
    return st, cond, built.registry, backend


def _drive(st, backend, *replies: str) -> dict[str, Any]:
    """跑一趟「只派活、不点动作」的 B 循环（空动作 = 真机的形状），返回结果。"""
    gw = _Scripted(list(replies) + [json.dumps({"final": "done", "evidence": []},
                                               ensure_ascii=False)])
    backend.seam_factory = lambda role: LlmSeam(
        role=role, session_root=st.root, gateway=gw, price=(0.0, 0.0), sid="t")
    return backend.call("B", "", {"task": "把这条命题登记进台账"}, token=None, task_id="")


def _tool(name: str, args: dict | None = None, why: str = "夹具这一步") -> str:
    """一步 `tool` 形状的替身回复（形状照循环协议）。"""
    return json.dumps({"tool": name, "args": dict(args or {}), "why": why},
                      ensure_ascii=False)


def _landed(st: Store) -> dict[str, Any]:
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    return dict(rows[0])


def _landed_problems(st: Store) -> list[str]:
    """判据 ① 的入场读数：盘上恰好一条，且那一条确实是秘书落的正路产出。

    收在一处是为了让反真空那一条用同一份读数打红（判据不经两套口径）：
    这里的第一条就是 `_landed` 的那句 `len(rows) == 1`，后面接
    `_honest_problems`（档位 / 五元位 / 留痕 / 号 / 正文）。
    """
    rows = st.rows("statements")
    if len(rows) != 1:
        return [f"盘上命题行 {len(rows)} 条（要恰好 1 条：秘书那一笔落下来的那一条）"]
    return _honest_problems(dict(rows[0]))


def _honest_problems(row: dict[str, Any]) -> list[str]:
    """一条落盘行作为"正路产出"缺了什么（空列表 = 它确实是正路的产出）。

    这三条就是判据 ①：`proof_text` 非空 + 有 V 的「成立」这一签之后，
    行上应当是 `evidence_kind="proof_review"`、`bits` 非空（五元位算出来了）、
    号与留痕都来自秘书。
    """
    problems: list[str] = []
    if str(row.get("evidence_kind") or "") != "proof_review":
        problems.append(f"evidence_kind={row.get('evidence_kind')!r}（要 'proof_review'）")
    if not dict(row.get("bits") or {}):
        problems.append("bits 是空的（五元位没算）")
    if str(row.get("created_by") or "") != "secretary-B":
        problems.append(f"created_by={row.get('created_by')!r}（落盘的不是秘书）")
    sid = str(row.get("stmt_id") or "")
    if not (sid.isdigit() and len(sid) == S.ID_DIGITS):
        problems.append(f"stmt_id={sid!r}（不是分配器给的 {S.ID_DIGITS} 位号）")
    if not str(row.get("proof_text") or "").strip():
        problems.append("proof_text 是空的")
    return problems


def _sign_off(st: Store, stmt_id: str, proof_text: str) -> dict[str, Any]:
    """V 走查签字（`verifications.record_verification` 就是 `verify.verify_proof` 的写入口）。"""
    from agentflow import verifications as VR

    return VR.record_verification(st.root, statement_id=stmt_id, proof_text=proof_text,
                                  verdict={"verdict": "成立", "why": "逐行走查三步都成立"})


# ==================================================== ① 正控：一次工具调用 → 落盘


def test_the_tool_call_lands_through_the_secretary(tmp_path):
    """① 正控：模型一次 `own.register_statement` ⇒ 行由秘书落盘（号、留痕、五元位都在）。"""
    st, cond, reg, backend = _world(tmp_path)
    # B-2 闸（`must_start_as_conjecture`）之后的正路：这一笔还没有 V 的签 ⇒ 先按猜想登记
    # （`kind="conjecture"` 是 B-2 明文放行的那一档），而不是一进门就叫 theorem。
    out = _drive(st, backend, _tool("own.register_statement", _payload(kind="conjecture")))
    assert out["stop_reason"] == "final", out

    row = _landed(st)
    # 号来自唯一分配器（第一行 ⇒ 最小号），留痕是秘书 —— B 自己一次写工具都没调。
    assert row["stmt_id"] == S.format_id(0), row["stmt_id"]
    assert row["created_by"] == "secretary-B", row["created_by"]
    # 五元位是动作现算的那一份（手写表那条路给的是 `{}`，见 ③b）
    assert dict(row["bits"]), row["bits"]
    assert row["bits"].get("proof") is True, row["bits"]
    assert row["bits"].get("evidence", {}).get("proof_process"), row["bits"]
    # 那一趟的真实事实：没有 V 的签名 ⇒ 弱档（动作的默认档 `cross_check`；
    # 这一格不是失败，是"还没有那一签"的如实登记 —— 判据 ① 只管"签完之后它是不是
    # 变成 proof_review"）
    assert row["evidence_kind"] in ("heuristic", "cross_check"), row["evidence_kind"]

    # ---- 第二段：V 签完之后把同一份内容再交一次 ⇒ 秘书改那一行（不新建）
    # 这一笔是「从猜想升成定理」的那一步：kind 回到 theorem（B-3 闸这时认得 V 的那一签）、
    # 档位给 proof_review（升档的唯一凭据）。
    _sign_off(st, row["stmt_id"], PROOF)
    again = _drive(st, backend,
                   _tool("own.register_statement",
                         _payload(kind="theorem", evidence_kind="proof_review")))
    assert again["stop_reason"] == "final", again
    rows = st.rows("statements")
    assert len(rows) == 1, f"升档不许新建行：{rows}"
    upgraded = dict(rows[0])
    assert upgraded["stmt_id"] == row["stmt_id"], upgraded["stmt_id"]
    assert upgraded["evidence_kind"] == "proof_review", upgraded["evidence_kind"]
    assert upgraded["_evidence_kind_upgrade"]["from"] == row["evidence_kind"], upgraded.get(
        "_evidence_kind_upgrade")
    assert upgraded["proof_text"] == row["proof_text"], "内容面一个字都不许动"
    # 判据 ① 的三条读数（同一组断言也被 ③b 拿去打红）
    assert _honest_problems(upgraded) == [], _honest_problems(upgraded)
    # 入场读数（盘上恰好一条 + 它就是正路的产出）与上面同一组，反真空那一条拿它打红。
    assert _landed_problems(st) == [], _landed_problems(st)


def test_the_bare_action_name_also_reaches_the_route(tmp_path):
    """正控之二（真机第 94 行那个形态）：模型按手册喊短名也能走通。

    `mp2-7.jsonl` 第 94 行模型喊的是 `register_statement`（它手册里的动作名），
    而工具面上那一件叫 `own.register_statement`（本仓工具名必须带点）⇒ 旧读数
    `unknown_tool`。`agent_loop._do_tool` 现在把短名映到 `own.<短名>`（只映到
    这一趟注册表里已经有的那一件，不打开任何权限），并留下 `aliased_from`。

    这一条与上一条成对：上一条走真名、这一条走短名，落下来的必须是同一条正路
    （秘书落盘、`bits` 由动作算、号由分配器给）。
    """
    st, cond, reg, backend = _world(tmp_path)
    # 与上一条同一条正路：首登按猜想（B-2 闸之后的唯一入口），这里只核"短名也走得到"。
    out = _drive(st, backend, _tool("register_statement", _payload(kind="conjecture")))
    assert out["stop_reason"] == "final", out
    run_path = str(out.get("llm_run_path") or "")
    step = json.loads(pathlib.Path(run_path).read_text(encoding="utf-8"))["steps"][0]
    assert (step.get("result") or {}).get("aliased_from") == "register_statement", step
    row = _landed(st)
    assert row["created_by"] == "secretary-B", row["created_by"]
    assert dict(row["bits"]), row["bits"]
    assert row["stmt_id"] == S.format_id(0), row["stmt_id"]


# ==================================================== ② 封路正控：野路被拒


def test_the_wild_road_is_refused_with_the_route_spelled_out(tmp_path):
    """② 封路正控：`table.create("statements")` 直写 ⇒ 被拒，拒信逐字写出该走哪条路。

    参数用的是 `mp2-7.jsonl` 第 97 行逐字那一份（手写 `evidence_kind` + `bits`）：
    判据要挡的正是那个形态，而不是一个抽象的表名。
    """
    st, cond, reg, backend = _world(tmp_path)
    for table, row in (
        ("statements", {"origin": "own_result", "kind": "proposition",
                        "label": "椭圆无等弦点", "statement_full": STATEMENT,
                        "proof_text": PROOF, "evidence_kind": "heuristic", "bits": {},
                        "line_range": {"start": 17, "end": 83},
                        "quote_reason": "尚未逐字校验"}),
        ("dependencies", {"used_by": "stmt:" + S.format_id(0), "kind": "theorem",
                          "label": "引理 1", "source_stmt_id": S.format_id(0)}),
    ):
        res = reg.call("table.create", role="B", table=table, row=row)
        assert res.ok is False, (table, res.data)
        assert res.meta.get("kind") == "direct_write_refused", (table, res.meta)
        err = str(res.error or "")
        assert "Secretary.record_statement" in err, err
        assert "own.register_statement" in err, err
        assert "table.delete" in err, "拒信要逐字写着哪条不受这条限制"
        assert res.meta.get("route_tool") == "own.register_statement", res.meta
    upd = reg.call("table.update", role="B", table="statements",
                   id=S.format_id(0), patch={"evidence_kind": "proof_review"})
    assert upd.ok is False and upd.meta.get("kind") == "direct_write_refused", upd.meta
    assert st.rows("statements") == [] and st.rows("dependencies") == [], "拒了就不许落行"


def test_the_store_commit_gate_is_the_second_lock(tmp_path, monkeypatch):
    """②b 结构性的那一半：不经过工具层、直接开一笔 `tool:` 事务 ⇒ 提交时同样被拒。

    为什么这一条必须单独在：工具层那一道只在"模型的手"上生效，而"明天有人新加一支
    通用写工具"这件事工具层拦不住。`Store.tx` 的提交块是所有写者的必经之路
    （与 `_refuse_fake_proof_review` 同一段注释），所以判据也落在那里。
    """
    st = Store(tmp_path / "ws")
    st.init()
    with pytest.raises(ValueError) as exc:
        with st.tx("statements", actor="tool", note="tool:table.create:statements") as tx:
            tx.upsert("statements", {"stmt_id": S.format_id(0), "origin": "own_result",
                                     "kind": "theorem", "statement_full": "手写的",
                                     "quote_reason": "尚未逐字校验"})
    assert "direct_write_refused" in str(exc.value), str(exc.value)
    assert st.rows("statements") == [], "提交期拒绝 ⇒ 一行都不落（不是落了一半）"

    # 反真空：删除不受这条限制（它不制造证据）—— 别的 `tool:` 事务照旧能提交。
    with st.tx("literature", actor="tool", note="tool:table.delete:literature") as tx:
        tx.upsert("literature", S.Literature(lit_id=S.format_id(0), title="T", type="J",
                                             summary="s", path=None, added_at=TS).to_dict())
    assert len(st.rows("literature")) == 1


# ==================================================== ③ 负控（两处 + 一处附带）


def test_negative_control_patching_the_gate_reopens_the_wild_road(tmp_path, monkeypatch):
    """③a 负控：把封路钩子 patch 掉 ⇒ ② 变红（直写又通了，落下来的正是 mp2 那一行）。

    它证明 ② 的绿是这道钩子带来的，不是"table.create 本来就写不进 statements"。
    `direct_write_refusal` 是唯一口径（工具层与 `Store.tx` 提交块都调它），
    所以一处 patch 同时关掉两层 —— 这也是那条判据"只有一处"的用处。
    """
    st, cond, reg, backend = _world(tmp_path)
    monkeypatch.setattr(store_mod, "direct_write_refusal", lambda table: "")
    res = reg.call("table.create", role="B", table="statements",
                   row={"origin": "own_result", "kind": "proposition",
                        "statement_full": STATEMENT, "proof_text": PROOF,
                        "evidence_kind": "heuristic", "bits": {},
                        "quote_reason": "尚未逐字校验"})
    assert res.ok is True, (res.error, res.meta)      # ← ② 在这里是红的
    row = _landed(st)
    assert dict(row["bits"]) == {}, row["bits"]       # 五元位一件没跑
    assert row["evidence_kind"] == "heuristic", row["evidence_kind"]
    assert str(row["created_by"]) != "secretary-B", row["created_by"]
    # 而判据 ①（同一组读数）在这一行上是红的 —— 这就是 ③b 要的第二段证据
    assert _honest_problems(row) != [], "手写的那一行居然满足了正路的判据 ⇒ 判据是恒真的"


def test_negative_control_hand_written_fields_cannot_satisfy_the_positive_reading(tmp_path,
                                                                                 monkeypatch):
    """③b 负控：把正路 patch 回"模型手写字段" ⇒ ① 的那组断言必须红。

    形态与 `mp2-7.jsonl` 第 97 行逐字相同：模型自己写 `evidence_kind` / `bits`。
    绿的 ① 与红的这里用的是同一个 `_honest_problems`（判据不经两套口径），
    所以"①绿"这件事除了"走的是正路"以外没有别的解释。
    """
    st, cond, reg, backend = _world(tmp_path)
    # 先把封路钩子关掉（否则手写这一笔进不来 ⇒ 本负控测的就不是"判据会不会红"）
    monkeypatch.setattr(store_mod, "direct_write_refusal", lambda table: "")
    # 形态与 `mp2-7.jsonl` 第 97 行逐字相同：模型自己写 `evidence_kind`、`bits` 留空
    res = reg.call("table.create", role="B", table="statements",
                   row={"origin": "own_result", "kind": "proposition",
                        "statement_full": STATEMENT, "proof_text": PROOF,
                        "evidence_kind": "heuristic",       # 明明有证明与 V 签，却写弱档
                        "bits": {},                         # 五元位一件没跑
                        "line_range": {"start": 17, "end": 83},
                        "quote_reason": "尚未逐字校验"})
    assert res.ok is True, (res.error, res.meta)
    row = _landed(st)
    problems = _honest_problems(row)
    assert problems != [], "手写字段竟然满足了正路判据 ⇒ ① 的绿说明不了任何事"
    # 三条一起红（这正是 mp2 那一行的三条读数）：
    assert any("evidence_kind" in p for p in problems), problems
    assert any("bits" in p for p in problems), problems
    assert any("created_by" in p for p in problems), problems


def test_negative_control_without_the_upgrade_the_kind_stays_heuristic(tmp_path, monkeypatch):
    """③c 负控（升档那一格）：把秘书的升档关掉 ⇒ ① 的 `evidence_kind` 退回 `heuristic`。

    这一格守的是"封了 `table.update` 之后，升档还有一条正路"这件事：
    少了它，`evidence_kind` 在结构上永远到不了 `proof_review`（mp2 的 `stmt:000003`
    就是这么僵死的），而 ① 会在一个看起来跑通了的流程上变红。
    """
    st, cond, reg, backend = _world(tmp_path)
    out = _drive(st, backend, _tool("own.register_statement", _payload(kind="conjecture")))
    assert out["stop_reason"] == "final", out
    row = _landed(st)
    _sign_off(st, row["stmt_id"], PROOF)

    monkeypatch.setattr(
        Secretary, "_upgrade_evidence_kind",
        lambda self, existing, body: {"upgraded": False, "row": {}, "changes": [],
                                      "reason": ""}, raising=True)
    _drive(st, backend, _tool("own.register_statement",
                              _payload(kind="theorem", evidence_kind="proof_review")))
    rows = st.rows("statements")
    assert len(rows) == 1, rows
    assert rows[0]["evidence_kind"] in ("heuristic", "cross_check"), rows[0]["evidence_kind"]
    assert _honest_problems(dict(rows[0])) != [], "升档被关掉了，判据 ① 却仍然是绿的"


def test_negative_control_without_the_secretarys_write_the_positive_reading_goes_red(
        tmp_path, monkeypatch):
    """反真空（判据 ① 的对象）：把秘书的写入关掉 ⇒ 盘上一行都不落，判据 ① 必须红。

    这一条问的是"① 的绿到底是谁给的"。判据 ① 的入场读数是"盘上恰好一条、而且它是
    秘书落下来的正路产出"（`_landed_problems`）。这里把 `Secretary.record_statement`
    关成"只报没写"（返回 `refused`、一行都不落）—— 如果这时 ① 仍然绿，那说明这组
    断言根本没对着写入，直接写表或凭空捏一条行也能过。

    三态不许折平：这里分两段核。第一段是"B 确实走到了秘书那一关"（`calls` 非空，
    否则测的就不是写入被关掉，而是 B 压根没交内容）；第二段才是"秘书没写 ⇒ 判据红"。
    """
    st, cond, reg, backend = _world(tmp_path)
    calls: list[str] = []

    def _no_write(self, payload, *, role="B", force_new=False):
        calls.append(str(payload.get("statement_full") or ""))
        return {"checked": False, "created": False, "duplicate": False, "upgraded": False,
                "stmt_id": "", "deps_written": 0, "path_groups": 0, "tables": [],
                "washed": False, "changes": [], "refused": "secretary_unavailable",
                "reason": "探针：秘书的写入被关掉了（这一笔不许落盘）", "pending": []}

    monkeypatch.setattr(Secretary, "record_statement", _no_write, raising=True)
    out = _drive(st, backend, _tool("own.register_statement", _payload(kind="conjecture")))
    assert out["stop_reason"] == "final", out
    assert calls, "B 根本没交到秘书那一关 ⇒ 这一条负控测的不是写入"
    assert st.rows("statements") == [], st.rows("statements")
    problems = _landed_problems(st)
    assert problems != [], "秘书的写入关掉了，判据 ① 却仍然是绿的（那组断言不是对着写入的）"
    assert any("盘上命题行" in p for p in problems), problems
