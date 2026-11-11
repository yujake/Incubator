# -*- coding: utf-8 -*-
"""判据：拿签之后冻结 —— 这一份稿只读（业主 2026-11-11 裁定 ②）。

## 业主裁定（逐字）

```text
② 「稿通过后相当于这个命题证完了，后续只对稿允许有只读权，但由于尚未入台账暂无引用权，
    需要维护拿签稿的稿号表（在一次攻坚中应该是持续追加，后续交稿时一并递交给D）」
```

同日追加：「拿 V 签冻结后交哪份是明确的（一个稿号只有一份）」。

## 判据

| # | 判据 | 钉住的东西 |
|---|---|---|
| a | 已签 ⇒ `fs.write` / `fs.edit` 受控拒，拒信逐字点名"已经拿签（签 sha=…），只读；要改就开 B 的优化副本" | 写口 1/2 |
| a2 | 签后改过正文（签 sha ≠ 稿当前正文 sha）⇒ 同一句拒 + 把"签后改过正文"如实报出来 | 违规态不许静默 |
| a3 | `attack.step(product=…)` 重交同一稿号 ⇒ 受控拒，稿一个字节没动 | 写口 3 |
| a4 | `promote`（老盘搬家）不许动已签的稿 | 写口 4 |
| b | 未签 ⇒ 三种写口照旧能写 | 冻结只拦已签的 |
| c | 「暂无引用权」：未收录 ⇒ 已有的可引门（`refvocab` 的 `stmt:` 那一档）已经挡，本批不新加门 | 只确认 |
| d | 反真空：摘掉冻结 ⇒ a 红 | a 的绿来自冻结那一步 |

## 为什么 `e-num` 不在射程内

`e-num` 走绿色通道（不拿 V 签）：`manuscriptfamily.sign_carrier` 对它返回 `ok=False`
⇒ 没有"拿签之后"这回事，它照旧能写（b 的一格读数）。

全部 tmp 工作区，不读写 `projects/`（真机工作区只读），不跑全量。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import manuscriptform as MF
from agentflow import manuscriptfreeze as FZ
from agentflow import proofregistry as PR
from agentflow import refvocab as RV
from agentflow import vsigns as VS
from agentflow.agent_f import AgentF
from agentflow.store import Store
from agentflow.tools.fs_tools import FsContext, fs_edit, fs_write

import _credential_fixture as CF
import conftest

REL = "reports/f-proof-000000.md"
BODY_1 = "第一版正文：由定义直接得到。"
BODY_2 = "第二版正文：改用有限覆盖（签后改过这一版）。"
SID = "000001"

TEXT = """# F 的证明手稿：夹具命题

- 命题号：stmt:000001
- 依赖面洗稿：已洗=true；洗的人=secretary:F；补写=无
- 证明号：1

## 命题

夹具命题。

## 证明

{body}

## 依赖

| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |
|---|---|---|---|
（这一份证明没有引用任何在册命题 —— 空表就是声明。）
"""

#: `attack.step(product=…)` 那一档要的产物形状（与 `test_f_can_hand_in_its_own_proof`
#: 同一个 schema：`kind` 必填、`steps[].text` 逐条）。
PROBLEM = "证明：若 f_n→f μ-a.e. 且被可积 g 控制，则 ∫f_n dμ → ∫f dμ。"
SUBGOAL = "控制项 2g 可积，且 |f_n-f| ≤ 2g 在 X 上处处成立。"
TESTABLE = "手稿的 `## 证明` 里逐步给出依据（`cites` 或 `assumption: true`）。"
BUDGET = {"max_rounds": 6, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path, *, seed: bool = True) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    (pathlib.Path(st.root) / "reports").mkdir(parents=True, exist_ok=True)
    if seed:
        conftest.seed_statement_row(st, stmt_id=SID, statement_full="夹具命题。",
                                    kind="conjecture")
    return st


def _ctx(st: Store) -> FsContext:
    """工具上下文。刻意不挂调用角色：空角色 = 表外调用，保留表不生效 ⇒
    `fs.write` 对一份手稿本来就能写（这样 b 的"照旧能写"才是真读数）。"""
    return FsContext(root=pathlib.Path(st.root), actor="probe")


def _write_manuscript(st: Store, body: str = BODY_1) -> str:
    (pathlib.Path(st.root) / REL).write_text(TEXT.format(body=body), encoding="utf-8")
    return REL


def _signed(st: Store, *, body: str = BODY_1) -> str:
    """一份已拿签的稿：签块在稿上、签文件在颁发表里（两份都真）。"""
    rel = _write_manuscript(st, body)
    sha = PR.proof_sha(body)
    block = ("- V 签：已签=true；判词=成立；连续=3/3；正文sha={sha}；"
             "时间=2026-11-02T10:00:00+08:00；签名者=V；"
             "台账=verifications/000001.jsonl#v-000003；命题号=stmt:000001；手稿号=000000"
             ).format(sha=sha)
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    text = text.replace("- 依赖面洗稿：", block + "\n- 依赖面洗稿：", 1)
    (pathlib.Path(st.root) / rel).write_text(text, encoding="utf-8")
    CF.issue_credential(st.root, proof_text=body, statement_id=SID,
                        manuscript=rel, artifact_path=rel)
    return rel


# ------------------------------------------------------------------ a 写口 1/2

def test_a_fs_write_and_edit_on_a_signed_manuscript_are_refused(tmp_path) -> None:
    """a（写口 1/2）：已签的稿 ⇒ `fs.write` / `fs.edit` 受控拒，盘上逐字不动。"""
    st = _ws(tmp_path)
    rel = _signed(st)
    before = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    sign_sha = PR.proof_sha(BODY_1)

    got = fs_write(_ctx(st), path=rel, content="改一改", overwrite=True)
    assert got.ok is False, got
    assert got.meta.get("kind") == FZ.MANUSCRIPT_FROZEN, got.meta
    assert "已经拿签" in str(got.error), got.error
    assert sign_sha[:12] in str(got.error), got.error
    assert "只读" in str(got.error), got.error
    assert "open_polish_copy" in str(got.error), got.error

    got2 = fs_edit(_ctx(st), path=rel, old_string=BODY_1, new_string="改一改")
    assert got2.ok is False, got2
    assert got2.meta.get("kind") == FZ.MANUSCRIPT_FROZEN, got2.meta
    assert (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") == before


# ------------------------------------------------------------------ a2 违规态

def test_a2_edited_after_sign_is_reported_as_a_violation(tmp_path) -> None:
    """a2：签的 sha ≠ 稿当前正文 sha（签后改过）⇒ 受控拒 + 如实报「签后改过正文」。"""
    st = _ws(tmp_path)
    rel = _signed(st, body=BODY_1)
    # 手工重放"签后改正文"：正文换成另一版，签块与签文件都还是第一版的
    (pathlib.Path(st.root) / rel).write_text(TEXT.format(body=BODY_2), encoding="utf-8")

    reading = FZ.freeze_reading(st.root, rel)
    assert reading["frozen"] is True, reading
    assert reading["state"] == "edited_after_sign", reading
    assert "签后改过正文" in reading["message"], reading

    got = fs_edit(_ctx(st), path=rel, old_string=BODY_2, new_string="再改")
    assert got.ok is False and got.meta.get("kind") == FZ.MANUSCRIPT_FROZEN, got
    assert "签后改过正文" in str(got.error), got.error
    assert got.meta.get("state") == "edited_after_sign", got.meta


# ------------------------------------------------------------------ a3 attack.step

def _gate_ok(monkeypatch) -> None:
    """命题形态闸打桩成"判过、合格"（那不是这一份要测的闸；与
    `test_f_can_hand_in_its_own_proof` 同一手法）。"""
    def fake_gate(self, *, full, kind, body, label, task_id=""):  # noqa: ANN001, ARG001
        return {"checked": True, "well_formed": True, "submittable": True,
                "conditions": "夹具：设…", "conclusion": "夹具：则…",
                "problems": [], "decision": "夹具：形态合规",
                "refused": "", "reason": "夹具：形态合规"}

    monkeypatch.setattr(AgentF, "_proposition_form_gate", fake_gate)


def _proof_product(dep: str) -> dict:
    return {"kind": "proof", "label": "控制收敛的一段",
            "steps": [{"text": "设 g ≥ 0 可积（本步是前提）", "assumption": True},
                      {"text": "由控制函数得 |f_n-f| ≤ 2g，且 2g 可积",
                       "cites": [f"stmt:{dep}"]}]}


def _citable(st: Store) -> str:
    """铺一条够格（`pre_theorem`）的在册命题给依赖面用（同
    `test_f_can_hand_in_its_own_proof._citable_statement`）。"""
    row = conftest.seed_statement_row(
        st, statement_full="引理：被可积函数 g 控制的可测函数列，控制项 2g 可积。",
        statement_text="2g 可积", kind="lemma", label="前提A",
        bits={"proof": True, "reviewed": True,
              "evidence": {"proof_process": "夹具：第 1 步设 g 可积。",
                           "reviewed_by": {"verdict": "成立",
                                           "verification_id": "v-000001"}}})
    return str(row["stmt_id"])


def test_a3_attack_step_cannot_reland_a_signed_manuscript(
        tmp_path, monkeypatch) -> None:
    """a（写口 3）：`attack.step(product=…)` 重交同一稿号 ⇒ 受控拒，稿一个字没动。"""
    _gate_ok(monkeypatch)
    st = _ws(tmp_path, seed=False)
    dep = _citable(st)
    f = AgentF(st, config={"workspace_root": str(st.root)})
    made = f.create_plan(PROBLEM, "pk-frozen",
                         subgoals=[{"sid": "S1", "text": SUBGOAL, "owner": "F",
                                    "testable": TESTABLE}],
                         budget=dict(BUDGET))
    assert made.get("created") is True, made
    plan_id = str(made["plan_id"])

    first = dict(f.tools.call("attack.step", plan_id=plan_id,
                              product=_proof_product(dep)).data or {})
    assert first.get("action") == "proof", first
    rel = str(first.get("manuscript_path") or "")
    mid = str(first.get("manuscript_id") or "")
    assert rel and mid, first
    # 把这一份稿签住（签块 + 颁发表两份都真）
    body = VS.manuscript_proof_body(
        (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")).strip("\n")
    CF.issue_credential(st.root, proof_text=body, statement_id="",
                        manuscript=rel, artifact_path=rel)
    before = (pathlib.Path(st.root) / rel).read_bytes()

    again = dict(f.tools.call("attack.step", plan_id=plan_id,
                              product=_proof_product(dep)).data or {})
    assert again.get("action") == "no_change", again
    assert "已经拿签" in str(again.get("reason") or ""), again
    assert "open_polish_copy" in str(again.get("reason") or ""), again
    assert (pathlib.Path(st.root) / rel).read_bytes() == before
    # 这一档受控拒要进 history（不许无声）：`refusal.kind` 与写口同一格
    plan_row = next(dict(r) for r in st.rows("attack_plans")
                    if str(r.get("plan_id")) == plan_id)
    refusal = dict((plan_row.get("history") or [])[-1].get("refusal") or {})
    assert refusal.get("kind") == FZ.MANUSCRIPT_FROZEN, refusal
    assert str(plan_row["subgoals"][0].get("status")) == "blocked", plan_row["subgoals"]


# ------------------------------------------------------------------ a4 promote

def test_a4_promote_cannot_move_a_signed_manuscript(tmp_path) -> None:
    """a（写口 4）：老盘搬家（`promote`）不许动已签的稿。"""
    st = _ws(tmp_path)
    rel = _signed(st)
    got = MF.promote_formal(st.root, family=MF.FAMILY_F, statement_id=SID,
                            manuscript_id="000900", source=rel)
    assert got.get("promoted") is False, got
    assert str(got.get("refused") or "") == FZ.MANUSCRIPT_FROZEN, got
    assert "已经拿签" in str(got.get("why") or ""), got
    assert (pathlib.Path(st.root) / rel).is_file()
    assert not (pathlib.Path(st.root) / "reports/f-proof-000900.md").exists()


# ------------------------------------------------------------------ b 未签照旧

def test_b_unsigned_manuscripts_are_still_writable(tmp_path) -> None:
    """b：未签 ⇒ 三种写口照旧能写（冻结只拦已签的，不误伤）。"""
    from agentflow.tools import fs_tools as FT

    st = _ws(tmp_path)
    rel = _write_manuscript(st, BODY_1)

    # `fs.write` 对已有文件要求"先读过一次"（既有纪律），所以先读再写。
    assert FT.fs_read(_ctx(st), path=rel).ok is True
    got = fs_write(_ctx(st), path=rel, content=TEXT.format(body=BODY_2), overwrite=True)
    assert got.ok is True, (got.meta, got.error)
    assert FT.fs_read(_ctx(st), path=rel).ok is True
    got2 = fs_edit(_ctx(st), path=rel, old_string=BODY_2, new_string=BODY_1)
    assert got2.ok is True, (got2.meta, got2.error)

    # e-num（绿色通道，不拿签）照旧能写
    num = "reports/e-num-000000.md"
    (pathlib.Path(st.root) / num).write_text("## 命题\n\nP\n", encoding="utf-8")
    assert FT.fs_read(_ctx(st), path=num).ok is True
    assert fs_write(_ctx(st), path=num, content="## 命题\n\nP2\n",
                    overwrite=True).ok is True

    # promote：未签的稿照旧能转正
    promoted = MF.promote_formal(st.root, family=MF.FAMILY_F, statement_id=SID,
                                 manuscript_id="000900", source=rel,
                                 text=TEXT.format(body=BODY_1))
    assert promoted.get("promoted") is True, promoted
    assert (pathlib.Path(st.root) / "reports/f-proof-000900.md").is_file()


# ------------------------------------------------------------------ c 暂无引用权

def test_c_an_unregistered_signed_manuscript_is_not_citable(tmp_path) -> None:
    """c：未收录（不在 `statements`）⇒ 已有的可引门已经挡（本批不新加门）。"""
    st = _ws(tmp_path, seed=False)
    rel = _signed(st)
    # 稿签过了，但它所在的那条命题不在册 ⇒ `stmt:` 那一档查不到（可引门照旧生效）
    got = RV.ref_reading("stmt:000009", root=st.root)
    assert got.get("state") == RV.STATE_MISSING, got
    assert RV.is_problem(got) is True, got
    # 补上那一行之后同一条引用就能引了（说明挡它的是"在不在册"，不是"签没签"）
    conftest.seed_statement_row(st, stmt_id="000009", statement_full="夹具命题。",
                                kind="conjecture")
    assert RV.ref_reading("stmt:000009", root=st.root).get("state") == RV.STATE_OK
    # 冻结与可引是两件事：这份稿仍然是只读的
    assert FZ.freeze_reading(st.root, rel)["frozen"] is True


# ------------------------------------------------------------------ d 反真空

def test_d_without_the_freeze_the_signed_manuscript_is_writable_again(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d 反真空：摘掉冻结 ⇒ a 的写口立刻变红（稿又被写进去了）。"""
    st = _ws(tmp_path)
    rel = _signed(st)
    from agentflow.tools import fs_tools as FT

    monkeypatch.setattr(FT, "_manuscript_frozen", lambda *a, **k: None)
    assert FT.fs_read(_ctx(st), path=rel).ok is True
    got = fs_write(_ctx(st), path=rel, content=TEXT.format(body=BODY_2), overwrite=True)
    assert got.ok is True, ("冻结被摘掉之后仍拒？d 没打到这一格", got.meta, got.error)
    assert (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") == TEXT.format(body=BODY_2)
