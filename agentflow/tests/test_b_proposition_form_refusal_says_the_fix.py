# -*- coding: utf-8 -*-
"""W2 判据：B 收编一份「签已通过、`## 命题` 却是修订说明」的稿，拒收必须自己给出改法。

## 现场（真机 `projects/octahedron-20261113`，本文件逐字复刻）

`manuscripts/handoffs.jsonl#000013`（B→D）的标题就是缺陷本身：

> 「f-proof-000002 签字已核通过，但 `## 命题` 节是修订说明不是定理陈述 ⇒ 未登记，
>   请裁：让 F 重落一版还是走改写重签」

两处结构性浪费：① V 的三转签已经花掉（签作废、白干）；② "怎么办"被甩给 D —— 而 D 对
命题台账只有只读权限（业主 2026-11-08），命题形态的判据在 B 的秘书手上，他手上没有判据。
B 当时没有调动作（handoff 里写着「未调用 `own.register_statement` /
`own.ingest_manuscript`（零写入）」）—— 因为它调了也只会把那段修订说明收成命题：
改前探针 `temp/w2_probe/probe_before.py` 逐字是 `ok=true / statements 多一行 /
statement_full 就是那段修订说明`。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 签已通过 + `## 命题` 是修订说明 ⇒ 受控拒 `proposition_form_refused`，`fix` 明写「重写 `## 命题` 为定理陈述」「不要重落新稿号」「不用重签」，`next_step` 明写不经 D 裁；`statements` 零新行、稿与签一个字节没动、形态台账留一行 `role=B` | 改前 `ok=true`（探针：修订说明成了 `statement_full`）；模型只能停在动作外面写 B→D「请裁」—— 没有受控码、没有 `fix` |
| b | 正控：`## 命题` 是正常定理陈述 ⇒ 收编成功、分配 `path_group=1`、落库正文就是这一节 | 闸若把正常稿也拒了，a 就是"什么都拒"的假绿 |
| c | 反真空：把 `AgentB.PROPOSITION_FORM_FIX` 打桩成空串 ⇒ a 的三条断言必红 | 证明 a 读的确实是代码里那一格，不是自己长出来的 |
| d | 改前复刻：把这道闸摘掉 ⇒ 那段修订说明真的被收成一条 `statements` 行 | 证明"拒收"来自这道闸，不是别处顺手拦住的 |

## 不判什么

- 不判"命题对不对"（那是 V 的轴）；也不许用关键词/字数阈值代替判断 —— 判据本体只有
  `Secretary.judge_proposition_form` 那一次模型调用，本文件的替身只换"模型缝"。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import conftest  # noqa: E402
from agentflow import closing as CL  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import manuscriptpaths as MP  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

REL = "reports/f-proof-000002.md"

#: 真机 `reports/f-proof-000002.md` 的 `## 命题` 节（逐字；它就是"修订说明"）。
NOTE = ("按 V u-000005 的唯一缺陷修订第 7 步：把「2|P_1| = 2/√(u²+v²)」改为"
        "「2|P_1| = 2√(u²+v²)/(u+v) = 2/(u+v)（用 u²+v² = 1）」，其余八步一字不动；"
        "同一份稿 reports/f-proof-000002.md 就地重写后重送 V。"
        "；这一条的可检验形式：V 对这一版正文（新 sha）给出两态结论「成立」（零 finding），"
        "且稿上签块的正文 sha 与现行正文一致；判据：F.step 返回的 v_sign.label == '已签'。")

#: 正控用的正常定理陈述（同一份证明正文；`## 命题` 这一节才是变量）。
PROPOSITION = ("设 a = 1/√2、O_a = {(x,y,z) : |x|+|y|+|z| ≤ a}；则对任意单位向量 n 与"
               "任意实数 t，截面面积 A_n(t) ≤ 2a²，且等号成立当且仅当 n 平行于某坐标轴"
               "且 t = 0。")

PROOF = ("1. 口径与齐次缩放：O_a = a·O_1，area(a·K) = a²·area(K)，故只需证 a=1 时 ≤ 2。\n"
         "2. 由 Brunn 凹性与 O_1 的中心对称得 A_n(t) ≤ A_n(0)：最大值在中心截面。\n"
         "3. 中心截面为六边形，面积闭式 2s/D ≤ 2（对称函数估计），等号当且仅当 n=±e_i。\n"
         "4. 非零偏移 A_{e_1}(t) = 2(1-|t|)² < 2，故等号只在 t = 0。")


class _Seam:
    """秘书模型缝的替身：`ask_json` 回一段写死的 JSON（`SeamCall` 的最小形状）。

    为什么只换缝、不换秘书：形态台账（`out/secretary/proposition_form.jsonl`）那一行是
    `Secretary.judge_proposition_form` 自己写的 —— 换掉秘书就把"拒收读数进台账"这件事
    一起换掉了，那条判据就成了夹具的自说自话。
    """

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "fake"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def __init__(self, data: dict) -> None:
        self.data = dict(data)
        self.prompts: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        self.prompts.append(prompt)
        return dict(self.data), self._Call()


def _ill_formed_seam() -> _Seam:
    """真机那一次判定的形状：不是「条件 → 结论」，是流程要求 / 验收规格。"""
    return _Seam({"well_formed": False, "conditions": "", "conclusion": "",
                  "problems": ["这是修订与送审的流程要求，不是「从什么条件导出什么结论」"
                               "的数学命题",
                               "结论部分是操作指令与验收规格，不是可判真假的断言"],
                  "decision": "不是命题"})


def _well_formed_seam() -> _Seam:
    return _Seam({"well_formed": True, "conditions": "设 a = 1/√2、n 为单位向量",
                  "conclusion": "则 A_n(t) ≤ 2a²，等号当且仅当 n ∥ 坐标轴且 t = 0",
                  "problems": [], "decision": "前提与结论都写清了"})


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _manuscript(proposition: str) -> str:
    """真机稿的骨架（稿头 / 三节 / 空依赖表），只换 `## 命题` 那一节。"""
    return ("# F 的证明手稿：按 V u-000005 的唯一缺陷修订第 7 步\n\n"
            "- 命题号：stmt:（还没落号）\n"
            "- 计划：000002 · 子目标：S4\n"
            "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
            "## 命题\n\n" + proposition + "\n\n"
            "## 证明\n\n" + PROOF + "\n\n"
            + DS.render_dependency_section([]) + "\n")


def _b(store: Store, seam: _Seam) -> AgentB:
    """B + 真的 `Secretary`（`judge_proposition_form` 本体），只换模型缝。"""
    sec = SEC.Secretary("B", root=store.root, store=store, seam=seam,
                        enable_model=True)
    return AgentB(store, extractor=None, extract_text=None, config={}, secretary=sec)


def _ingest(store: Store, seam: _Seam, *, proposition: str = NOTE) -> dict:
    """现场：先把签落下（未在册档，按正文 sha），再把稿交给 B 收编。"""
    path = pathlib.Path(store.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_manuscript(proposition), encoding="utf-8")
    conftest.sign_before_registration(store.root, proof_text=PROOF)
    return _b(store, seam).ingest_manuscript(manuscript=REL, mode="register")


def _statements(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("statements")]


def _pending_files(store: Store) -> list[str]:
    base = VR.pending_dir(store.root)
    return sorted(p.name for p in base.glob("*.jsonl")) if base.is_dir() else []


# ------------------------------------------------------------------ a 受控拒 + 改法

def test_a_a_signed_revision_note_is_refused_with_an_executable_fix(tmp_path):
    """a：签已通过、`## 命题` 是修订说明 ⇒ 受控码 + 可执行改法 + 零写入。"""
    st = _store(tmp_path)
    seam = _ill_formed_seam()
    got = _ingest(st, seam)

    assert got.get("ok") is False, got
    assert got.get("refused") == "proposition_form_refused", got

    fix = str(got.get("fix") or "")
    assert "## 命题" in fix, fix
    assert "定理" in fix, fix
    assert "不要重落新稿号" in fix, fix
    assert "不用重签" in fix, fix

    nxt = str(got.get("next_step") or "")
    assert "不用 D 裁" in nxt, nxt
    assert "D 对命题台账只有只读权限" in nxt, nxt
    assert "原位" in nxt, nxt

    # 拒收回执本身把改法也带在 reason 里（模型只读 reason 也拿得到）
    assert "改法：" in str(got.get("reason") or ""), got.get("reason")

    # 零写入：statements 一行都没有，稿与签一个字节没动
    assert _statements(st) == [], _statements(st)
    assert "statements" in (got.get("write") or {}), got
    assert got["write"]["statements"] is False, got["write"]
    assert got["write"]["written"] is False, got["write"]
    assert _pending_files(st), "夹具的签没落成，这条用例就证明不了「签不动」"

    # 拒收读数进台账（收工门那一格 `readings.proposition_form` 按 role 读得到）
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == 1, rows
    assert rows[0]["role"] == "B", rows
    assert rows[0]["checked"] is True and rows[0]["well_formed"] is False, rows
    assert rows[0]["refused"] == "proposition_form_refused", rows
    read = CL.proposition_form_reading(st)
    assert read["checked"] is True, read
    assert read["by_role"]["B"]["refused"] == 1, read["by_role"]
    assert read["by_role"]["B"]["codes"] == [
        {"code": "proposition_form_refused", "count": 1}], read["by_role"]

    # 闸真的看到了稿上那一节（不是拿空串判的）
    assert seam.prompts and NOTE[:24] in seam.prompts[0], seam.prompts


# ------------------------------------------------------------------ b 正控

def test_b_a_well_formed_proposition_is_registered_with_path_group_one(tmp_path):
    """b：正控 —— `## 命题` 是定理陈述 ⇒ 收编成功、分到第 1 条路径。"""
    st = _store(tmp_path)
    seam = _well_formed_seam()
    got = _ingest(st, seam, proposition=PROPOSITION)

    assert got.get("ok") is True, got
    sid = str((got.get("target") or {}).get("stmt_id") or "")
    assert sid, got

    rows = _statements(st)
    assert len(rows) == 1, rows
    assert str(rows[0].get("statement_full") or "") == PROPOSITION, rows[0]
    assert int(rows[0].get("proof_no") or 0) >= 1, rows[0]

    reading = MP.path_reading(st, st.root, statement_id=sid)
    assert reading.get("checked") is True, reading
    assert int(reading.get("count") or 0) == 1, reading
    by_group = {int(p["path_group"]): p for p in (reading.get("paths") or [])}
    assert by_group[1]["manuscript"] == REL, by_group

    assert seam.prompts and PROPOSITION[:16] in seam.prompts[0], seam.prompts


# ------------------------------------------------------------------ c 反真空（fix 文案）

def test_c_an_empty_fix_text_makes_a_red(tmp_path, monkeypatch):
    """c：把 `fix` 文案打桩成空串 ⇒ a 的三条断言必红（判据读的是代码里那一格）。"""
    monkeypatch.setattr(AgentB, "PROPOSITION_FORM_FIX", "")
    st = _store(tmp_path)
    got = _ingest(st, _ill_formed_seam())

    assert got.get("ok") is False, got
    assert got.get("refused") == "proposition_form_refused", got
    fix = str(got.get("fix") or "")
    assert fix == "", fix
    assert not ("## 命题" in fix and "定理" in fix and "不要重落新稿号" in fix), (
        "反真空失效：fix 被打桩成空串之后 a 的断言仍然成立 ⇒ a 证明不了文案来自这一格")


# ------------------------------------------------------------------ d 改前复刻（摘掉闸）

def test_d_removing_the_gate_lands_the_revision_note_as_a_proposition(
        tmp_path, monkeypatch):
    """d：把这道闸摘掉 ⇒ 那段修订说明被收成一条 `statements` 行（改前形态）。"""
    monkeypatch.setattr(AgentB, "_manuscript_form_refusal", lambda self, **kw: {})
    st = _store(tmp_path)
    got = _ingest(st, _ill_formed_seam())

    assert got.get("ok") is True, (
        "反真空失效：摘掉命题形态闸之后仍然被拒 ⇒ 这条用例证明不了闸在起作用", got)
    rows = _statements(st)
    assert len(rows) == 1, rows
    landed = str(rows[0].get("statement_full") or "")
    assert landed.startswith("按 V u-000005"), landed
    assert "不要重落新稿号" not in landed, landed
