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
| ⑧ | 计划名 + 三转干净（真机 `f-proof-plan-000011` 的形状） | 老盘只读兼容：与数字名同等，照签（稿上有块、pending 三行、一份签文件），但稿名不改、第 8 格仍是「未在册」 |
| ⑨ | 未在册三转 clean | 返回值顶层 `secretary_judge` 读得到 `axis=clean` / `source=secretary:v_reply_defect`，与 pending 行是同一份判定 |

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
from agentflow.agent_v import core as V_CORE
from agentflow.store import Store

from test_v_reviews_three_times_before_signing import CLEAN_REPLY, _ReviewSeam

#: 未在册那一支的轴也由秘书语义判定给（p247：散文支每一转问一次 `_judge_v_reply`，
#: 穷举支由机械会审给）；V 的两态结论只是陈述。下面的 `_JudgeStub` 是替身自己在给轴，
#: 不是生产代码在按 `verdict` 字面定轴。
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
              "- 计划：0000 · 子目标：s1\n\n"
              "## 命题\n\n"
              f"{FULL}\n\n"
              "## 证明\n\n"
              "1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
              "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。\n\n"
              # 2026-11-04（甲）：`## 依赖` 那一节必须有三列表头（空表也是声明）；
              # V 读稿时缺这一节 ⇒ 受控拒绝 `dependency_section_missing`。
              + _DS.render_dependency_section([]))
#: 被签的那一份正文 = 手稿里「## 证明」那一节（`depsection.proof_body` 的口径）：
#: 签的 sha 按这一段算（`vsigns.ARTIFACT_SHA_RULE`），所以测试也从这里取，不另抄一份。
PROOF = _DS.proof_body(MANUSCRIPT).strip("\n")
#: 正式手稿名（签的载体）。2026-11-10 业主裁定之后老盘计划名也是只读兼容载体
#: （见 ⑧），但新稿只按 F 自己的稿号落（`reports/f-proof-<稿号>.md`）—— 正统路仍是 `REL`。
REL = "reports/f-proof-000000.md"


def _ws(tmp_path: pathlib.Path, *, text: str = MANUSCRIPT) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return st


class _JudgeStub:
    """V 的秘书替身（p247：轴必须由秘书给；这一支只量未在册那条路）。

    夹具按 V 回复里有没有「有毛病」给出轴 —— 这是替身自己的判定，不是生产代码在按字面
    定轴；生产代码里 `judge_v_reply` 读的是回复语义。
    落签那一半委托给一个没有缝的真秘书（`land_unregistered_sign` 的口径只有一处）。
    """

    def __init__(self, st: Store) -> None:
        from agentflow import secretary as _SEC

        self._real = _SEC.Secretary("V", root=st.root, store=st, seam=None,
                                    enable_model=False)

    @property
    def actor_label(self):
        return self._real.actor_label

    def land_unregistered_sign(self, envelope):
        return self._real.land_unregistered_sign(envelope)

    def judge_v_reply(self, *, reply="", verdict="", defect_step=None, **_kw):
        bad = "有毛病" in str(verdict) or "有毛病" in str(reply)
        return {"checked": True, "axis": "fault" if bad else "clean",
                "decision": "有缺陷要指出" if bad else "没问题",
                "reason": "夹具：秘书语义判定", "basis": ["夹具"],
                "defect_step": (defect_step if isinstance(defect_step, int) else 2)
                if bad else None}

    def wash_v_reply(self, **_kw):
        return {"checked": True, "washed": True, "text": "第 2 步需要补依据。",
                "findings": [], "dropped": [], "refused": ""}


def _v(st: Store, replies: list[str]) -> tuple[AgentV, _ReviewSeam]:
    seam = _ReviewSeam(list(replies))
    return AgentV(st, workspace_root=st.root, llm=seam,
                  secretary=_JudgeStub(st)), seam


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
            / f"{VR.text_sha(PROOF)}.jsonl")


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
        assert row["proof_sha256"] == VR.text_sha(PROOF), row
        assert row["verdict"] == "成立", row
        assert row["object_path"] == REL, row
    assert _pending_file(st).is_file(), "pending 台账没按正文 sha 落文件"
    assert got.get("verification_id") == "u-000003", got
    assert str(got.get("ledger") or "").endswith(
        f"verifications/pending/{VR.text_sha(PROOF)}.jsonl#u-000003"), got

    # ---- 稿上的签块：已签、连续 3/3、命题号=未在册、台账指 pending ----
    block = VS.manuscript_sign_reading(_manuscript_text(st), manuscript_path=REL)
    assert block["found"] is True and block["signed"] is True, block
    assert block["streak"] == 3 and block["need"] == 3, block
    assert block["statement_id"] == "", block          # 命题号=未在册 是合法形态
    assert block["manuscript_id"] == "000000", block
    assert block["identity_state"] == "resolved", block
    assert block["ledger"] == (f"verifications/pending/{VR.text_sha(PROOF)}.jsonl"
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


# ============================================================ ⑧ 计划名也是载体（老盘）
def test_g_a_plan_manuscript_is_a_sign_carrier_now(tmp_path):
    """⑧ 计划名 + 三转干净（真机 `f-proof-plan-000011` 的形状）⇒ 照签，且不改名。

    ## 改前钉什么 / 改后钉什么

    改前（业主 2026-11-05）：计划稿是合法落稿名（`parse_manuscript_name` 认得出
    `plan-0000`），但不是签的载体 ⇒ 三转照判、只读「看过、没签」
    （`kind=proof_reviewed_not_signed`、不写块、不落 pending、不颁发）。

    2026-11-10 业主裁定：「F 的稿自己维护一套号源，不依赖命题号和计划号」「计划不拥有
    稿件」⇒ `manuscriptfamily.sign_carrier` 撤掉 `f-proof-plan-*` 的排除：老盘上的计划名
    是只读兼容名，与数字名同等 ⇒ 这一档与 ① 同形（签落稿上、pending 三行三票、
    签文件一份），且稿名一个字都不改（计划不拥有稿件：签不会把它"转正"成别人的稿）。

    反向断言（强度不降）：
    - 第 8 格仍是「未在册」（`statement_id==""`）—— 载体合法不等于计划成了命题；
    - 盘上不出现 `statements` 行，也不出现按数字名的那一份 `f-proof-0000.md`
      （这一签不产生第二份稿、不改名）；
    - 签块的台账指 pending 那一行（不是稿自己）。
    """
    st = _ws(tmp_path)
    plan_rel = "reports/f-proof-plan-0000.md"
    path = pathlib.Path(st.root) / plan_rel
    path.write_text(MANUSCRIPT, encoding="utf-8")
    v, seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=plan_rel)

    assert seam.asked() == 3, seam.asked()
    assert got.get("checked") is True, got
    assert got.get("kind") == "proof_unregistered_signed", got
    assert got.get("verdict") == "成立", got

    # ---- 稿上的签块：与数字名那一档同形（身份 resolved、命题号=未在册）----
    block = VS.manuscript_sign_reading(path.read_text(encoding="utf-8"),
                                       manuscript_path=plan_rel)
    assert block["found"] is True and block["signed"] is True, block
    assert block["statement_id"] == "", block          # 第 8 格：未在册
    assert block["manuscript_id"] == "plan-0000", block
    assert block["identity_state"] == "resolved", block
    assert block["ledger"] == (f"verifications/pending/{VR.text_sha(PROOF)}.jsonl"
                               "#u-000003"), block

    # ---- pending 三行三票：载体就是这份计划名（老盘只读兼容）----
    rows = _pending_rows(st)
    assert len(rows) == int(VR.SIGN_STREAK_NEED), rows
    assert {str(r["verification_id"]) for r in rows} == {"u-000001", "u-000002", "u-000003"}
    for row in rows:
        for key in ("verification_id", "at", "proof_sha256"):
            assert str(row.get(key) or "").strip(), (key, row)
        assert row["proof_sha256"] == VR.text_sha(PROOF), row
        assert row["object_path"] == plan_rel, row

    # ---- 签文件：passes 就是那三张真票，台账指 pending（不是稿自己）----
    files = _sign_files(st)
    assert len(files) == 1, files
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["statement_id"] == "", doc
    assert doc["ledger"] == block["ledger"], doc
    assert [p["verification_id"] for p in doc["passes"]] == [
        "u-000001", "u-000002", "u-000003"], doc["passes"]

    # ---- F 的读数：已签 ----
    assert FVS.delivery_reading(st.root, proof_text=PROOF,
                                manuscript_paths=(plan_rel,))["state"] == FVS.STATE_SIGNED

    # ---- 反向：载体合法 ≠ 计划成了命题 / ≠ 改出一份按数字名的稿 ----
    assert VS.parse_manuscript_name(plan_rel)["manuscript_id"] == "plan-0000"
    assert VS.is_sign_carrier(plan_rel) is True
    assert st.rows("statements") == [], st.rows("statements")
    assert not (pathlib.Path(st.root) / "reports" / "f-proof-0000.md").exists(), (
        "签这一趟把计划名转正了（收录不改名：稿名只由 F 的稿号决定）")


# ============================================================ ⑨ 顶层轴读数
def test_h_the_axis_reading_reaches_the_return_top_level(tmp_path):
    """⑨ 未在册三转 clean ⇒ 返回值顶层直接读得到轴，且与 pending 行是同一份判定。

    业主的规矩：读数不许丢。改前顶层 `secretary_judge` 是 `{}`，轴只躺在
    `review_passes[*].axis` 与 pending 台账行上 —— 调用方读返回值拿不到"轴是什么、
    谁判的"，只能去翻明细。这一条钉两处读数（返回值顶层 / pending 最后一行）逐字相等。
    """
    st = _ws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)

    assert seam.asked() == 3, seam.asked()
    judge = dict(got.get("secretary_judge") or {})
    assert judge.get("checked") is True, judge
    assert judge.get("axis") == "clean", judge
    assert judge.get("source") == "secretary:v_reply_defect", judge
    assert judge.get("defect_step") is None, judge

    # ---- 两处读数：返回值顶层 == pending 台账最后一行那一格 ----
    rows = _pending_rows(st)
    assert rows, "三转 clean 却没有 pending 行 ⇒ 这一格没查成"
    assert dict(rows[-1].get("secretary_judge") or {}) == judge, (
        f"返回值顶层的轴与 pending 行不是同一份判定：{judge!r} != "
        f"{rows[-1].get('secretary_judge')!r}")

    # ---- 第三处读数：逐转的轴也全是 clean（顶层不是另造的一格）----
    assert [str(p.get("axis") or "") for p in got.get("review_passes") or []] == [
        "clean"] * int(VR.SIGN_STREAK_NEED), got.get("review_passes")


def test_h2_dropping_the_projection_loses_the_top_level_axis(tmp_path, monkeypatch):
    """⑨ 的反真空：把投影函数换成恒空表 ⇒ 顶层读不到轴（h 的断言会红）。

    这不是"再断言一遍"：它真的把把轴搬到顶层的那一处摘掉，再看读数是不是变空 ——
    若摘掉之后 h 仍然读得到 clean，那 h 就是假绿（它量的不是那个投影）。
    """
    monkeypatch.setattr(V_CORE, "_unregistered_secretary_judge", lambda got: {})
    st = _ws(tmp_path)
    v, seam = _v(st, [CLEAN_REPLY])
    with _submitted_by_f():
        got = v.verify_proof(proof_manuscript=REL)

    assert seam.asked() == 3, seam.asked()
    assert got.get("secretary_judge") == {}, got.get("secretary_judge")
    # 逐转读数照旧：变空的只有顶层那一格（不是轴本身没了）。
    assert [str(p.get("axis") or "") for p in got.get("review_passes") or []] == [
        "clean"] * int(VR.SIGN_STREAK_NEED), got.get("review_passes")
