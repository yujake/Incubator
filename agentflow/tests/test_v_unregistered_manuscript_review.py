# -*- coding: utf-8 -*-
"""「未在册」那一支就是正统主路：V 不假定有号，签先落稿上（业主 2026-11-05 晚）。

## 这一组守什么

业主 2026-11-05 晚逐字（把同日上午那一条反过来）：

    「V 就不能假定有号，全签在稿上，B 侧录入时从稿拿签。这是已有口径」

真机 `projects/R-mk-infinite-90/reports` 的读数支撑这个口径（`f-proof-000019.md`：
`命题号=未在册` 而 `台账=verifications/000019.jsonl#v-000007` —— 那是真签）。

于是这一支的落点有三处、互不替代：

- 签块：`reports/(f|b|e)-proof-<数字>.md` 上那一行 `- V 签：`（`命题号=未在册` 合法）；
- 独立背书：`verifications/pending/<正文 sha>.jsonl`，三转三行，
  每行 `verification_id` / `at` / `proof_sha256` 三票齐全；
- 签文件：`out/vsigns/<正文 sha>.json`，`passes` 是那三张真票，`ledger` 指 pending 那一行。

## 判据（先红后绿；改前 a 是红的：`statement_id_missing` 挡在这条路上）

| # | 造什么 | 期望 |
|---|---|---|
| ① | 未在册手稿 + 三转干净 | 三转照问；稿上有签块（`命题号=未在册`）；pending 三行三票齐全；签文件的 passes 是那三行；`kind=proof_unregistered_signed` |
| ② | 三转里有一转拿不到合法结论 | `checked=False`、一个字节都不写（连 `verifications/` 都不建） |
| ③ | 同一份正文再送一次 | 不重复审（`already`），不写第二块、不再落 pending 行 |
| ④ | 反真空（结构）：`agent_v/**` 里 0 处签写口 | 扫描器在 `secretary.py` 找得到那 1 处 `land`（"0 处"不许由"扫不到"冒充） |
| ⑤ | 反真空（落签）：把 `vsigns.land` 摘掉 | 稿上没有块，但签与 pending 三行照旧（这一签不依赖落块） |
| ⑥ | 第 2 转判「有毛病」 | 只问 2 次就停；不写块；判词落 pending 一行；F 读数「未通过」 |
| ⑦ | 入口守卫 | 只收 F / E / B 那一份手稿的命名 |
| ⑧ | 计划稿 + 三转干净（真机 `f-proof-plan-000011` 的形状） | 看过、没签：不写块、不落 pending、不颁发 |

零模型调用：V 的审阅缝交出预置回复并计数（与三连判判据共用同一套替身）。
"""
from __future__ import annotations

import ast
import contextlib
import json
import pathlib

from agentflow import conductor as CND
from agentflow import depsection as _DS
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_f import vsign as FVS
from agentflow.agent_v import AgentV
from agentflow.store import Store

from test_v_reviews_three_times_before_signing import CLEAN_REPLY, _ReviewSeam

#: 未在册那一支的判定面是 V 自己的两态结论（没有秘书那一层：pending / 手稿这条血脉
#: 一直只认 `row_signable`，见 `agent_v/core.py::_review_unregistered_prose` 的说明）。
#: 所以这一组用"结论就是有毛病"的回复，而不是"判词写成立、秘书读出缺陷"那一招。
REJECT_REPLY = json.dumps({"verdict": "有毛病", "defect_step": 2,
                           "quote": "第 1 步直接取 δ=ε",
                           "why": "对一般连续函数 δ=ε 不成立",
                           "findings": [{"level": "error", "step": 2,
                                         "kind": "无依据的步骤",
                                         "detail": "第 1 步没有给出推导"}]},
                          ensure_ascii=False)

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
#: 与 `agent_f/manuscript.py::proof_manuscript` 同一个形状（V 只读 `## 证明` 那一节）。
MANUSCRIPT = ("# F 的证明手稿：一致连续\n\n"
              "- 命题号：stmt:（还没落号）\n"
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              "1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
              "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。\n\n"
              # 2026-11-04（甲）：`## 依赖` 那一节必须有四列表头（空表也是声明）；
              # V 读稿时缺这一节 ⇒ 受控拒绝 `dependency_section_missing`。
              + _DS.render_dependency_section([]))
#: 被签的那一份正文 = 手稿里「## 证明」那一节（`depsection.proof_body` 的口径）：
#: 签的 sha 按这一段算（`vsigns.ARTIFACT_SHA_RULE`），所以测试也从这里取，不另抄一份。
PROOF = _DS.proof_body(MANUSCRIPT).strip("\n")
#: 正式手稿名（签的载体）。改前这一格是 `reports/f-proof-plan-0000.md` ——
#: 计划稿不是签的载体（业主 2026-11-05），正统路必须用 `<数字>` 那一档。
REL = "reports/f-proof-000000.md"


def _ws(tmp_path: pathlib.Path, *, text: str = MANUSCRIPT) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return st


def _v(st: Store, replies: list[str]) -> tuple[AgentV, _ReviewSeam]:
    seam = _ReviewSeam(list(replies))
    return AgentV(st, workspace_root=st.root, llm=seam), seam


@contextlib.contextmanager
def _submitted_by_f():
    """V 这一趟是 F 派出来的（2026-11-03 件一：收方 = V 的 parent 那一侧）。"""
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        yield


def _manuscript_text(st: Store) -> str:
    return (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")


def _pending_rows(st: Store) -> list[dict]:
    base = pathlib.Path(st.root) / "verifications" / "pending"
    if not base.is_dir():
        return []
    return [json.loads(ln) for p in sorted(base.glob("*.jsonl"))
            for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _pending_file(st: Store) -> pathlib.Path:
    return (pathlib.Path(st.root) / "verifications" / "pending"
            / f"{VR.proof_sha(PROOF)}.jsonl")


def _sign_files(st: Store) -> list[pathlib.Path]:
    base = VS.signs_dir(st.root)
    if not base.is_dir():
        return []
    return [p for p in sorted(base.glob("*.json")) if p.name != VS.INDEX_NAME]


# ============================================================ ① 三转干净 ⇒ 正统路
def test_a_three_clean_rounds_sign_the_manuscript_and_back_it_with_pending(tmp_path):
    """① 未在册手稿 + 三转干净 ⇒ 签落稿上、三票齐全、背书指 pending（改前这里是红）。"""
    st = _ws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)

    assert seam.asked() == 3, seam.asked()
    assert got.get("checked") is True, got
    assert got.get("kind") == "proof_unregistered_signed", got
    assert got.get("verdict") == "成立", got
    assert got.get("signed_bit3") is False, got   # 没有命题行可翻，这一格是诚实的

    # ---- pending 台账：三转三行，每行三票齐全 ----
    rows = _pending_rows(st)
    assert len(rows) == 3, rows
    assert {str(r["verification_id"]) for r in rows} == {"u-000001", "u-000002", "u-000003"}
    for row in rows:
        for key in ("verification_id", "at", "proof_sha256"):
            assert str(row.get(key) or "").strip(), (key, row)
        assert row["proof_sha256"] == VR.proof_sha(PROOF), row
        assert row["verdict"] == "成立", row
        assert row["object_path"] == REL, row
    assert _pending_file(st).is_file(), "pending 台账没按正文 sha 落文件"
    assert got.get("verification_id") == "u-000003", got
    assert str(got.get("ledger") or "").endswith(
        f"verifications/pending/{VR.proof_sha(PROOF)}.jsonl#u-000003"), got

    # ---- 稿上的签块：已签、连续 3/3、命题号=未在册、台账指 pending ----
    block = VS.manuscript_sign_reading(_manuscript_text(st), manuscript_path=REL)
    assert block["found"] is True and block["signed"] is True, block
    assert block["streak"] == 3 and block["need"] == 3, block
    assert block["statement_id"] == "", block          # 命题号=未在册 是合法形态
    assert block["manuscript_id"] == "000000", block
    assert block["identity_state"] == "resolved", block
    assert block["ledger"] == (f"verifications/pending/{VR.proof_sha(PROOF)}.jsonl"
                               "#u-000003"), block

    # ---- 签文件：passes 就是那三张真票 ----
    files = _sign_files(st)
    assert len(files) == 1, files
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["statement_id"] == "", doc
    assert doc["ledger"] == block["ledger"], doc
    assert [p["verification_id"] for p in doc["passes"]] == [
        "u-000001", "u-000002", "u-000003"], doc["passes"]
    for one in doc["passes"]:
        for key in ("verification_id", "at", "proof_sha256"):
            assert str(one.get(key) or "").strip(), (key, one)

    # ---- F 的读数：已签（不再是「待签」）----
    reading = FVS.delivery_reading(st.root, proof_text=PROOF, manuscript_paths=(REL,))
    assert reading["state"] == FVS.STATE_SIGNED, reading
    assert reading["delivered"] is True, reading


# ============================================================ ② 缺材料 ⇒ 不落
def test_b_no_usable_reply_writes_nothing(tmp_path):
    """② 拿不到合法结论 ⇒ checked=False，一个字节都不写（连 `verifications/` 都不建）。"""

    class _Broken(_ReviewSeam):
        def ask(self, prompt: str = "", **_kw):
            call = super().ask(prompt, **_kw)
            call.ok = False
            call.text = ""
            call.problem = "fixture: 这一转没拿到回复"
            return call

    st = _ws(tmp_path)
    seam = _Broken([CLEAN_REPLY])
    v = AgentV(st, workspace_root=st.root, llm=seam)
    before = _manuscript_text(st)
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)

    assert got.get("checked") is False, got
    assert "没查成" in str(got.get("detail") or ""), got
    assert _manuscript_text(st) == before, "没查成的一趟改动了手稿"
    assert _pending_rows(st) == [], "没查成却落了 pending 行"
    assert _sign_files(st) == [], "没查成却产出了签文件"
    # 读数跟着回落：没签就是待签（不是"已签"）。
    assert FVS.delivery_reading(st.root, proof_text=PROOF,
                                manuscript_paths=(REL,))["state"] == FVS.STATE_WAITING


# ============================================================ ③ 再送一次不重复写
def test_c_the_same_body_is_not_reviewed_or_signed_twice(tmp_path):
    """③ 同一份正文再送一次 ⇒ 认到稿上那一块（`already`），不问模型、不再落行。"""
    st = _ws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        first = v.verify_proof(proof_manuscript=REL)
    assert first.get("kind") == "proof_unregistered_signed", first
    rows_before = len(_pending_rows(st))
    text_before = _manuscript_text(st)

    with _submitted_by_f():
        again = v.verify_proof(proof_manuscript=REL)

    assert seam.asked() == 3, f"第二次送审又问了一遍模型（{seam.asked()} 次）"
    assert again.get("kind") == "proof_unregistered_signed", again
    assert len(_pending_rows(st)) == rows_before, "第二次送审又落了 pending 行"
    assert _manuscript_text(st) == text_before, "第二次送审把稿写动了"
    assert _manuscript_text(st).count(VS.SIGN_MARK) == 1, _manuscript_text(st)


# ============================================================ ④ 结构判据
#: 签写口的调用名（`vsigns.land` / 手稿块 / 台账位 / 旧的 `write_sign` 都算）。
#: 按 AST 的"调用末段名"扫，别名（`_VS.land(`）逃不掉；注释与 docstring 没有 Call
#: 节点，所以文件头那些"改前曾调 `write_manuscript_sign`"的说明不会误报。
_SIGN_WRITE_CALLS = ("land", "write_manuscript_sign",
                     "_reviewed_statement_row", "write_sign")


def _sign_writer_calls(path: pathlib.Path) -> list[tuple[str, int]]:
    """这一份源码里对签写口的调用（`[(末段名, 行号)]`；AST，别名也认）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else "")
        if name in _SIGN_WRITE_CALLS:
            hits.append((name, node.lineno))
    return hits


def test_d_the_sign_write_entries_are_reached_only_from_the_secretary():
    """④ 结构判据：`agent_v/**` 里 0 处签写口；同一扫描在 `secretary.py` 找到 1 处 land。

    反真空：如果 `secretary.py` 里那一处也找不到，说明扫描器失效（或落签又搬回了 V）——
    这一条必须红。"0 处"不许由"扫不到"冒充。
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    agent_v = sorted((root / "src" / "agentflow" / "agent_v").rglob("*.py"))
    assert agent_v, "扫描器没找到 `agent_v` 的源码 ⇒ 这一格没查成"
    found: list[str] = []
    for path in agent_v:
        for name, line in _sign_writer_calls(path):
            found.append(f"{path.relative_to(root)}:{line}: {name}(")
    assert found == [], "V 的代码里还直接调签写口：\n" + "\n".join(found)
    sec = root / "src" / "agentflow" / "secretary.py"
    landed = [line for name, line in _sign_writer_calls(sec) if name == "land"]
    assert len(landed) == 1, (
        f"`secretary.py` 里 `land` 调用有 {len(landed)} 处（期望 1 处）⇒ "
        "扫描失效，或者落签不在秘书那一侧")


# ============================================================ ⑤ 反真空（落签）
def test_d2_without_landing_the_pending_backing_still_stands(tmp_path, monkeypatch):
    """反真空：把 `vsigns.land` 摘掉 ⇒ 稿上没有块，但签与 pending 三行照旧在。

    这一条量的是「三票齐全的签不依赖落块」：落块只是把签盖到稿上那一半，
    签本身的凭据（`out/vsigns/<sha>.json` + `verifications/pending/<sha>.jsonl`）
    在颁发那一刻就已经成立。改前（签根本不产）这一条是另一种形状：什么都不落。
    """
    st = _ws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    called = {"n": 0}
    real = VS.land

    def _refuse(*a, **kw):
        called["n"] += 1
        return {"landed": False, "state": "refused", "code": "land_removed",
                "reason": "夹具：把 land 摘掉", "manuscript_write": {},
                "ledger_bit": "not_attempted"}

    monkeypatch.setattr(VS, "land", _refuse)
    try:
        with _submitted_by_f():
            got = v.verify_proof(proof_manuscript=REL)
    finally:
        monkeypatch.setattr(VS, "land", real)

    assert seam.asked() == 3, seam.asked()
    assert called["n"] >= 1, "落签那一格没被走到（这一条量错了东西）"
    block = VS.manuscript_sign_reading(_manuscript_text(st), manuscript_path=REL)
    assert block["found"] is False, block
    assert len(_pending_rows(st)) == 3, _pending_rows(st)
    assert len(_sign_files(st)) == 1, _sign_files(st)
    assert got.get("kind") == "proof_unregistered_signed", got


# ============================================================ ⑥ 有毛病那一转
def test_e_a_fault_on_round_two_stops_and_writes_no_block(tmp_path):
    """第 2 转判「有毛病」⇒ 只问 2 次就停，稿上不写块（甲口径：负判不是签）。

    判词仍落 pending 一行（那是打回的凭据，F 的 `delivery_reading` 读成「未通过」）。
    """
    st = _ws(tmp_path)
    before = _manuscript_text(st)
    v, seam = _v(st, [CLEAN_REPLY, REJECT_REPLY])
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)

    assert seam.asked() == 2, f"判出有毛病之后还接着问（{seam.asked()} 次）"
    assert got.get("checked") is True, got
    assert got.get("kind") == "proof_unregistered_rejected", got
    assert got.get("verdict") == "有毛病", got
    assert got.get("defect_step") == 2, got
    assert got.get("findings"), got
    assert _manuscript_text(st) == before, "负判改动了手稿（应一个字节都不写）"
    assert VS.manuscript_sign_reading(_manuscript_text(st))["found"] is False, _manuscript_text(st)
    rows = _pending_rows(st)
    assert len(rows) == 1 and rows[0]["verdict"] == "有毛病", rows
    assert rows[0]["verification_id"] == "u-000001", rows
    assert FVS.delivery_reading(st.root, proof_text=PROOF,
                                manuscript_paths=(REL,))["state"] == FVS.STATE_REJECTED


# ============================================================ ⑦ 入口守卫
def test_f_only_proof_manuscripts_are_accepted(tmp_path):
    """入口只认 F / E / B 那一份手稿的命名（不按任意路径读盘）。"""
    st = _ws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    got = v.verify_proof(proof_manuscript="data/statements.json")
    assert got.get("checked") is False, got
    assert got.get("reason") == "bad_manuscript_path", got
    assert seam.asked() == 0, "路径被拒之后还问了模型"


# ============================================================ ⑧ 计划稿不是载体
def test_g_a_plan_manuscript_is_reviewed_but_never_signed(tmp_path):
    """⑧ 计划稿 + 三转干净（真机 `f-proof-plan-000011` 的形状）⇒ 看过、没签。

    计划稿是合法的落稿名（`parse_manuscript_name` 照旧认得出 `plan-000011`），
    但它不是签的载体：这一档不写块、不落 pending、不颁发签文件。
    """
    st = _ws(tmp_path)
    plan_rel = "reports/f-proof-plan-0000.md"
    path = pathlib.Path(st.root) / plan_rel
    path.write_text(MANUSCRIPT, encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    v, seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=plan_rel)

    assert seam.asked() == 3, seam.asked()   # 三转照判（读数照给）
    assert got.get("kind") == "proof_reviewed_not_signed", got
    assert "计划稿" in str(got.get("reason") or ""), got
    assert "不是签的载体" in str(got.get("reason") or ""), got
    assert path.read_text(encoding="utf-8") == before, "计划稿被写了签块"
    assert _sign_files(st) == [], "计划稿却产出了签文件"
    assert _pending_rows(st) == [], "计划稿却落了 pending 行"
    # 落稿名这一半照旧（F 的「先落计划名、拿到号再改名」工作流没被动）。
    assert VS.parse_manuscript_name(plan_rel)["manuscript_id"] == "plan-0000"
    assert VS.is_sign_carrier(plan_rel) is False
