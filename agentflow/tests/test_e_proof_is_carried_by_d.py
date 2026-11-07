# -*- coding: utf-8 -*-
"""E 的穷举证明稿走 D 的携带单入库（业主 2026-11-04：「E 的穷举论证和 V 签也是委托入库」）。

## 为什么单开这一份判据

业主本轮把两条通道的前置分开了（逐字）：

> 「L写的时候命题一定在台账所以不会写不到。E写数值实验时可能命题还没进台账，
>   需要进D手稿转交入库，同F侧手稿、V」

L 一定在验一条在册命题；E 出稿时命题可能还没有号。所以 E 的稿不能靠
`reports/f-proof-<命题号>.md` 那种"按命题号命名"的路被携带/寻址 —— 它的键只能是
`exp:<实验号>`。改前 `depsection.carried_manuscripts` 只认 `stmt:`：把 E 的稿写进
D 的携带单会被判 `dependency_section_unreadable`（真机读数：`命题号那一格要是
stmt:NNNNNN（收到 'exp:000000'）`），于是"E → D 携带单 → B 寻址"这一环整条断掉。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 已签的 e-proof ⇒ D 的携带单里有一行 `exp:<实验号>`，地址与文件字节 sha256 都对 | 改前 D 只扫 `statements` + `f-proof-*.md`，E 的稿一条都不在单里 |
| b | B 只拿证明栏（不给 `proof_manuscript`）⇒ 按携带单地址读到 E 的稿、`manuscript_source=carried_by_D`、第 3 位翻真、`evidence_kind=proof`、`grade=pre_theorem` | 改前携带单读不懂 `exp:` 行（`dependency_section_unreadable`）⇒ 寻址不到、签认不到 |
| c | 没签的 e-proof ⇒ D 不带（携带单是空的） | 反真空：不带是"签块判据"决定的，不是"恰好没有这条实验" |
| d | 打桩 `manuscript_sign_standing` 成恒 signed ⇒ c 必须变红 | 反真空：证明 c 的绿真的靠那一格 |

全部用例在 `tmp_path` 里自建工作区；V 的穷举会审是机械七项、B 的登记不发模型请求 ⇒
零模型调用。E 的实验脚本用 `test_agent_v_exhaustion_review` 的那一份（不抄第二份）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import add_literature, e_form_gate_ok  # noqa: E402
from agentflow import conductor as CND  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_d import AgentD  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402

from test_agent_v_exhaustion_review import EXHAUSTIVE_PROBE, SCRIPT_REL, _v_secretary  # noqa: E402

FULL = "对任意正整数 n，R(3,4)=9。"
CLAIM = "R(3,4)=9（K_9 的二染色穷举）"
CLAIM_KEY = "ramsey34=9"


def _env(tmp_path: pathlib.Path, *, sign: bool = True) -> dict:
    """E 跑一趟真穷举（落 ②③ + e-proof 手稿），可选让 V 三转把签块落进稿。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, S.format_id(0))
    script = pathlib.Path(st.root) / SCRIPT_REL
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(EXHAUSTIVE_PROBE, encoding="utf-8")
    e = e_form_gate_ok(AgentE(st, config={}, workspace_root=st.root))
    out = e.run_experiment(CLAIM, CLAIM_KEY, SCRIPT_REL, method="numeric")
    env = {"store": st, "out": out,
           "column": NP.proof_column(dict(st.rows("experiments")[-1])),
           "b": AgentB(st, extractor=None, extract_text=None)}
    if sign:
        v = AgentV(st, workspace_root=st.root, secretary=_v_secretary(st))
        with CND.calling_as("t-v-000001", "V", parent_task_id="t-e-000001",
                            parent_role="E"):
            got = v.verify_proof(proof_manuscript=str(out["proof_manuscript"]))
        assert got.get("kind") == "proof_unregistered_signed", got
    return env


def _write_note(env: dict, rows: list[dict]) -> str:
    """把 D 的携带单落成盘上的 `reports/RESEARCH.md`（渲染与解析共用同一节）。"""
    text = "# D 的研究报告\n\n- 计划：ramsey34\n\n" + DS.render_carried_section(rows)
    target = pathlib.Path(env["store"].root) / "reports" / "RESEARCH.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return text


def _file(env: dict) -> dict:
    """B 收录：只给命题与证明栏，不给 `proof_manuscript` —— 稿得靠携带单寻址。"""
    return env["b"].register_statement(
        origin="own_result", kind="theorem", label="R(3,4)=9",
        statement_full=FULL, statement_text="R(3,4)=9",
        proof_text=env["column"], evidence_kind="proof",
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")


# ============================================================ a D 的携带单认 exp
def test_a_the_signed_e_proof_is_carried_under_its_experiment_key(
        tmp_path: pathlib.Path) -> None:
    """a：已签的 e-proof ⇒ D 的携带单里有 `exp:<实验号>` 那一行（地址 + 文件 sha）。"""
    env = _env(tmp_path)
    eid = str(env["out"]["experiment_id"])
    rel = str(env["out"]["proof_manuscript"])

    rows, _note = AgentD(env["store"])._carried_manuscripts()
    mine = [dict(r) for r in rows if str(r.get("experiment_id") or "") == eid]
    assert len(mine) == 1, rows
    one = mine[0]
    assert one["statement_id"] == "", one
    assert one["path"] == rel, one
    import hashlib

    blob = (pathlib.Path(env["store"].root) / rel).read_bytes()
    assert one["sha256"] == hashlib.sha256(blob).hexdigest(), one

    section = DS.render_carried_section(rows)
    assert f"| exp:{eid} | {rel} |" in section, section
    parsed = DS.carried_manuscripts(section)
    assert parsed["refused"] == "" and parsed["problems"] == [], parsed
    assert [r["experiment_id"] for r in parsed["rows"]] == [eid], parsed


# ============================================================ b B 按地址收录
def test_b_b_collects_the_e_proof_through_the_carried_note(
        tmp_path: pathlib.Path) -> None:
    """b：B 只拿证明栏 ⇒ 按携带单地址读到 E 的稿，签认到、第 3 位翻真。"""
    env = _env(tmp_path)
    assert not list(env["store"].rows("statements")), "前提：命题还没进台账"
    rows, _note = AgentD(env["store"])._carried_manuscripts()
    _write_note(env, rows)

    filed = _file(env)
    assert filed.get("ok") is True, filed
    addr = dict(filed.get("addressing") or {})
    assert addr.get("source") == DS.SOURCE_CARRIED, addr
    assert addr.get("hit") is True, addr
    assert addr.get("address") == str(env["out"]["proof_manuscript"]), addr
    assert filed.get("manuscript_source") == DS.SOURCE_CARRIED, filed.get("manuscript_source")
    v_sign = dict(filed.get("v_sign") or {})
    assert v_sign.get("applied") is True, v_sign

    row = [dict(r) for r in env["store"].rows("statements")][-1]
    bits = dict(row.get("bits") or {})
    assert row.get("evidence_kind") == "proof", row
    assert bits.get("reviewed") is True, bits
    assert bits.get("proof") is True, bits
    assert bits.get("grade") == "pre_theorem", bits
    # 没有新增第二行：E 出稿没有自己建 statements 行，B 这一笔才是唯一那一行。
    assert len(list(env["store"].rows("statements"))) == 1
    # 实验行仍是 E 的那一条 proof（E 的账），没有被 B 改写。
    exp = [dict(r) for r in env["store"].rows("experiments")][-1]
    assert exp.get("evidence_kind") == "proof", exp


# ============================================================ c 没签就不带
def test_c_an_unsigned_e_proof_is_not_carried(tmp_path: pathlib.Path) -> None:
    """c：没签的 e-proof ⇒ D 的携带单里没有它（带上它只会让 B 白拒一次）。"""
    env = _env(tmp_path, sign=False)
    eid = str(env["out"]["experiment_id"])
    rows, _note = AgentD(env["store"])._carried_manuscripts()
    assert [r for r in rows if str(r.get("experiment_id") or "") == eid] == [], rows
    text = DS.render_carried_section(rows)
    assert f"exp:{eid}" not in text, text


# ============================================================ d 反真空
def test_d_stubbing_the_sign_reading_carries_the_unsigned_one(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：把"签块读成 signed"那一格打桩成恒 signed ⇒ c 必须红。

    这一条量的是 c 的绿真的来自 `manuscript_sign_standing` 那一格，而不是
    "恰好盘上没有这条实验"（c 与 d 用的是同一个夹具形态）。
    """
    env = _env(tmp_path, sign=False)
    eid = str(env["out"]["experiment_id"])

    def _always_signed(text, *, proof_sha="", manuscript_path=""):
        return {"state": "signed", "checked": True, "found": True, "signed": True,
                "why": "打桩：这一份当作已签"}

    monkeypatch.setattr(VS, "manuscript_sign_standing", _always_signed)
    rows, _note = AgentD(env["store"])._carried_manuscripts()
    assert [r["experiment_id"] for r in rows] == [eid], rows


# ============================================================ e 在册命题：落回那一行
def test_e_a_delivery_for_a_registered_statement_lands_on_that_row(
        tmp_path: pathlib.Path) -> None:
    """e：命题已在册（先落成猜想、没有证明正文）⇒ 这一笔落回那一行，不新增。"""
    env = _env(tmp_path)
    first = env["b"].register_statement(
        origin="own_result", kind="conjecture", label="R(3,4)=9",
        statement_full=FULL, statement_text="R(3,4)=9", proof_text="",
        evidence_kind="cross_check", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert first.get("ok") is True, first
    sid = str(first.get("stmt_id") or "")
    assert len(list(env["store"].rows("statements"))) == 1

    rows, _note = AgentD(env["store"])._carried_manuscripts()
    _write_note(env, rows)
    filed = _file(env)
    assert filed.get("ok") is True, filed
    assert str(filed.get("stmt_id") or "") == sid, filed
    got = [dict(r) for r in env["store"].rows("statements")]
    assert len(got) == 1, "同一份交付被登记成了第二行"
    row = got[0]
    bits = dict(row.get("bits") or {})
    assert bits.get("reviewed") is True, bits
    # 2026-11-05（业主裁定「穷举证书相当于 lean 形式化」）：`derive_grade` 的定理条件放宽成
    # `proof ∧ (formal=verified ∨ numeric=verified)`。这一笔的证明栏就是 E 的穷举三段式、
    # 台账里那一签盖住的就是现行这一版 ⇒ 第 1 位由 `_grade_recomputed_from_signature`
    # 的 `exhaustion` 通道落成 `verified`（见上面的 `bits["numeric"]`）⇒ 等级是 `theorem`。
    # 同一形态的兄弟判据：`test_b_register_collects_the_proof_bit.py` 的
    # `test_d_an_exhaustive_proof_collected_later_is_still_a_theorem`（同批改口径）。
    assert bits.get("numeric") == "verified", bits
    assert bits.get("grade") == "theorem", bits
    assert str(row.get("proof_text") or "").startswith("程序："), row.get("proof_text")


# ============================================================ f 反真空：归属判断
def test_f_removing_the_ownership_judgement_registers_a_second_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f：把三层归属判断全摘掉 ⇒ 必有一边错（注册重复）。

    归属判断有三层，任何一层单独在就足以让这一笔"落回在册那一行"：

    1. 规范化正文相等（`Secretary.record_statement` 的 `T.normalize` 那一步）；
    2. 同一命题的确定性键 / 词面相似度（`propositionkey.same_proposition`）；
    3. 稿名里的号当候选号（`agent_b.register_statement` 的 D2 那一格，
       `vsigns.manuscript_id_of`，2026-11-05 起）：E 这份稿叫
       `reports/e-proof-000000.md` ⇒ 候选号 000000，被在册那一行占着 ⇒ 受控拒收
       `stmt_id_taken`（不另发号）。只摘 ①② 时这一层会接住，于是"没有多出一行"
       变成一条假读数（它不再说明 ①② 在判）。

    所以这里三层一起摘：稿名认不出号 ⇒ 候选号为空 ⇒ 退回按计数器发号，而查重恒不
    命中 ⇒ 同一份交付落成第二行。b/e 的绿因此不是来自"恰好只有一条"，而是来自这些
    归属判断真的在判（`after == before + 1` 是它们的反真空读数）。
    """
    from agentflow import propositionkey as PK
    from agentflow import textutil as T

    counter = {"n": 0}
    real = T.normalize

    def _unique(text: Any) -> str:
        counter["n"] += 1
        return f"u{counter['n']}:{real(text)}"

    def _never_same(a: Any, b: Any, *, threshold: float = 0.0) -> dict:
        return {"state": "different", "basis": "", "similarity": 0.0,
                "key_a": "", "key_b": "", "detail": "", "reason": "打桩：不判同一条",
                "threshold": threshold, "judgeable": True}

    env = _env(tmp_path)
    first = env["b"].register_statement(
        origin="own_result", kind="conjecture", label="R(3,4)=9",
        statement_full=FULL, statement_text="R(3,4)=9", proof_text="",
        evidence_kind="cross_check", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert first.get("ok") is True, first
    before = len(list(env["store"].rows("statements")))

    # 三层归属判断一起摘掉：① 规范化正文相等（`T.normalize`）；
    # ② 同一命题的确定性键 / 词面相似度（`propositionkey.same_proposition`）；
    # ③ 稿名候选号（`vsigns.manuscript_id_of`，D2 2026-11-05）：不摘它，
    #    这一笔会被 `stmt_id_taken` 接住（稿名 e-proof-000000.md 指着一个被占的号），
    #    "没有多出一行"就量不到 ①② 在不在判。
    monkeypatch.setattr(T, "normalize", _unique)
    monkeypatch.setattr(PK, "same_proposition", _never_same)
    monkeypatch.setattr(VS, "manuscript_id_of", lambda _path: "")
    rows, _note = AgentD(env["store"])._carried_manuscripts()
    _write_note(env, rows)
    _file(env)
    after = len(list(env["store"].rows("statements")))
    assert after == before + 1, (
        f"摘掉三层归属判断之后应当多出一行（before={before}, after={after}）—— "
        "没有多出来，说明 e 的「不新增」不是这三层判出来的")


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
