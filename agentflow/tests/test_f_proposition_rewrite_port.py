# -*- coding: utf-8 -*-
"""W2·甲 判据：未入册命题的 `## 命题` 原位重写（受控写口）+ 三条边界。

## 为什么要这个写口

真机 `projects/octahedron-20261113`：`reports/f-proof-000002.md` 的 V 签已通过，而
`## 命题` 是修订说明。B 收编时拒收（`proposition_form_refused`），拒收的改法写「同一
稿号原位重写 `## 命题`」—— 可是当时没有任何写口做得到：`proofregistry` 的重写档只换
`## 证明`、`fs.write/edit` 按名拒写 `f-proof-*`、已签稿被冻结。

## 边界三条（业主 2026-11-13 裁定；缺一不许）

① 只在"这份稿还没被收进 `statements`"时允许（已登记的走重新登记）；
② 改后必须过「语义同一性判定」（复用 `proposition_identity` 轴、两态；判不了 ⇒ 拒；
   不许拿文字相似度 / 长度这类机械判据兜底）；
③ 走受控写口，不在冻结面上开洞：只换 `## 命题` 与稿头指纹，`## 证明` 的正文 sha
   未变，三句声明（改的是命题节 / 正文 sha 未变 / 不需要重签）进读数。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 未入册 + 判"同一条" ⇒ 改写成功：`## 命题` 换成新陈述、`## 证明` 的 sha 未变、签仍在（B 的签闸按同一 sha 认领）、B 能收编且入册正文是新陈述 | 没有这个写口（三条路都堵死） |
| b | 未入册 + 判"另一条" ⇒ 受控拒 `proposition_identity_refused`，盘上一个字节没动 | 同上；且若按"能改就改"实现，另一条命题会被静默换进来 |
| c | 已入册（`statements` 里有这一条）⇒ 受控拒 `proposition_already_registered`，稿不动 | 同上；改已登记命题的陈述 = 换了一条命题 |
| d | 反真空：把同一性判定打桩成恒"同一条" ⇒ b 的那条断言必红（改写真的发生了） | 证明 b 的绿来自那一道语义门，不是别处顺手拦的 |
| e | 没判成（词表外 / 没缝）⇒ 受控拒 `proposition_identity_unjudged`（fail-closed） | "没判成"折成"同一条"是这一族最贵的形态 |
| f | F 链的入口 `AgentF.rewrite_manuscript_proposition` 委托同一个实现（agent=F、读数同形） | 写口不在 F 链上就等于没有 |
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import conftest  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import proofregistry as PR  # noqa: E402
from agentflow import propositionrewrite as PRW  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_f import AgentF  # noqa: E402
from agentflow.store import Store  # noqa: E402

REL = "reports/f-proof-000002.md"
MID = "000002"

#: 真机 `reports/f-proof-000002.md` 的 `## 命题` 节（逐字：一段修订说明）。
NOTE = ("按 V u-000005 的唯一缺陷修订第 7 步：把「2|P_1| = 2/√(u²+v²)」改为"
        "「2|P_1| = 2√(u²+v²)/(u+v) = 2/(u+v)（用 u²+v² = 1）」，其余八步一字不动；"
        "同一份稿 reports/f-proof-000002.md 就地重写后重送 V。"
        "；这一条的可检验形式：V 对这一版正文给出两态结论「成立」。")

#: 改后的正确陈述（同一条定理：只是把"改法说明"换成"条件 → 结论"）。
PROPOSITION = ("设 a = 1/√2、O_a = {(x,y,z) : |x|+|y|+|z| ≤ a}；则对任意单位向量 n 与"
               "任意实数 t，截面面积 A_n(t) ≤ 2a²，且等号成立当且仅当 n 平行于某坐标轴"
               "且 t = 0。")

PROOF = ("1. 口径与齐次缩放：O_a = a·O_1，area(a·K) = a²·area(K)，故只需证 a=1 时 ≤ 2。\n"
         "2. 由 Brunn 凹性与 O_1 的中心对称得 A_n(t) ≤ A_n(0)：最大值在中心截面。\n"
         "3. 中心截面为六边形，面积闭式 2s/D ≤ 2，等号当且仅当 n=±e_i。")


class _Seam:
    """秘书模型缝的替身：`proposition_identity` 那一问回写死的判词。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "fake"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def __init__(self, decision: str) -> None:
        self.decision = str(decision)
        self.notes: list[str] = []
        self.prompts: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        self.notes.append(str(note))
        self.prompts.append(str(prompt))
        data = {"decision": self.decision, "reason": f"夹具：判 {self.decision}",
                "basis": ["夹具：条件一句", "夹具：结论一句"]}
        return dict(data), self._Call()


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _manuscript(proposition: str = NOTE) -> str:
    """真机稿的骨架（带登记元信息：正文 sha 与命题指纹都是"这一版"的）。"""
    body_sha = PR.proof_sha(PROOF)
    fp = PR.proposition_fingerprint(proposition)
    return ("# F 的证明手稿：按 V u-000005 的唯一缺陷修订第 7 步\n\n"
            "- 计划：000002 · 子目标：S4\n"
            f"- 正文sha：{body_sha}\n"
            f"- 命题指纹：{fp}\n"
            "- 标签：F 攻坚 000002 子目标 S4\n"
            "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
            f"## 命题\n\n{proposition}\n\n"
            f"## 证明\n\n{PROOF}\n\n"
            + DS.render_dependency_section([]) + "\n")


def _write(st: Store, *, proposition: str = NOTE) -> pathlib.Path:
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    # 按字节写（换行不随平台翻译）：这一档的判据要按"盘上那串字节没动"读。
    path.write_bytes(_manuscript(proposition).encode("utf-8"))
    return path


def _secretary(st: Store, decision: str = "same") -> SEC.Secretary:
    return SEC.Secretary("F", root=st.root, store=st, seam=_Seam(decision),
                         enable_model=True)


def _rewrite(st: Store, *, decision: str = "same", proposition: str = PROPOSITION,
             proposition_before: str = NOTE) -> dict:
    _write(st, proposition=proposition_before)
    conftest.sign_before_registration(st.root, proof_text=PROOF)
    return PRW.rewrite_proposition(
        store=st, root=st.root, manuscript=REL, proposition=proposition,
        secretary=_secretary(st, decision), label="F 攻坚 000002 子目标 S4")


def _sections(text: str) -> dict[str, str]:
    _head, got = PR.split_sections(text)
    return {name: body.strip() for name, body in got}


def _rows(st: Store, table: str) -> list[dict]:
    return [dict(r) for r in st.rows(table)]


# ------------------------------------------------------------------ a 同一条 ⇒ 改写成功

def test_a_the_same_proposition_is_rewritten_and_b_can_ingest_it(tmp_path):
    """a：未入册 + 判「同一条」⇒ 只换命题节；正文 sha 未变、签仍有效、B 收编。"""
    st = _store(tmp_path)
    got = _rewrite(st, decision="same")

    assert got.get("checked") is True, got
    assert got.get("ok") is True and got.get("wrote") is True, got
    assert got.get("refused") == "", got
    assert got.get("attempted") is True, got
    assert got["proposition_before"].startswith("按 V u-000005"), got
    assert got["proposition_after"] == PROPOSITION, got

    # 只改命题节：`## 证明` 的正文 sha 逐字未变（签盖的就是它）
    text = (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    sections = _sections(text)
    assert sections["命题"] == PROPOSITION, sections["命题"]
    assert PR.proof_sha(text) == PR.proof_sha(_manuscript()), (
        "`## 证明` 的正文 sha 变了 ⇒ 这一笔动了签盖的那段字节")
    assert got.get("body_unchanged") is True, got
    assert got["proof_sha256_after"] == got["proof_sha256_before"], got

    # 稿头的命题指纹跟着换（否则下一次登记会撞 `proposition_text_changed`）
    entry = PR.parse_entry(text)
    assert entry.get("fingerprint") == PR.proposition_fingerprint(PROPOSITION), entry
    assert entry.get("sha256") == PR.proof_sha(_manuscript()), (
        "稿头的正文 sha 被改写了 ⇒ 这一笔假装「证明换了一版」", entry)

    # 三句声明进读数
    assert list(got.get("declarations") or []) == list(PRW.DECLARATIONS), got
    assert "不需要重签" in " ".join(got["declarations"]), got["declarations"]

    # 签没被撤：收录前落的那一签（按正文 sha）还在
    assert [p.name for p in VR.pending_dir(st.root).glob("*.jsonl")], "夹具的签没落成"
    assert "ingest_manuscript" in str(got.get("next_step") or ""), got.get("next_step")

    # B 能收编：签按同一正文 sha 认领，入册的正文是新陈述
    b = conftest.b_form_gate_ok(
        AgentB(st, extractor=None, extract_text=None, config={}))
    ing = b.ingest_manuscript(manuscript=REL, mode="register")
    assert ing.get("ok") is True, ing
    row = _rows(st, "statements")[0]
    assert row["statement_full"] == PROPOSITION, row["statement_full"]
    assert row["proof_sha256"] == PR.proof_sha(_manuscript()), row["proof_sha256"]
    assert str(row.get("manuscript_id") or "") == MID, row


# ------------------------------------------------------------------ b 另一条 ⇒ 受控拒

def test_b_a_different_proposition_is_refused_and_nothing_is_written(tmp_path):
    """b：未入册 + 判「另一条」⇒ 受控拒，盘上一个字节没动。"""
    st = _store(tmp_path)
    path = pathlib.Path(st.root) / REL
    before_bytes = _manuscript().encode("utf-8")
    got = _rewrite(st, decision="different")
    assert got.get("ok") is False, got
    assert got.get("refused") == PRW.REFUSED_DIFFERENT, got
    assert got.get("wrote") is False, got
    assert "另一条命题" in str(got.get("why") or ""), got.get("why")
    assert path.read_bytes() == before_bytes, "受控拒却动了稿"
    assert _rows(st, "statements") == [], _rows(st, "statements")


# ------------------------------------------------------------------ c 已入册 ⇒ 受控拒

def test_c_a_registered_proposition_is_refused(tmp_path):
    """c：已经进 statements ⇒ 受控拒（走重新登记），稿不动。"""
    st = _store(tmp_path)
    _write(st)
    conftest.seed_statement_row(st, stmt_id="000001", statement_full=NOTE,
                                kind="conjecture", manuscript_id=MID)
    before = (pathlib.Path(st.root) / REL).read_bytes()
    got = PRW.rewrite_proposition(
        store=st, root=st.root, manuscript=REL, proposition=PROPOSITION,
        secretary=_secretary(st, "same"))
    assert got.get("ok") is False, got
    assert got.get("refused") == PRW.REFUSED_REGISTERED, got
    assert "stmt:000001" in str(got.get("why") or ""), got.get("why")
    assert (pathlib.Path(st.root) / REL).read_bytes() == before, "受控拒却动了稿"


# ------------------------------------------------------------------ d 反真空（语义门）

def test_d_stubbing_the_identity_judgement_makes_b_red(tmp_path, monkeypatch):
    """d：把同一性判定打桩成恒「同一条」⇒ b 的那条断言必红（另一条命题被换进来）。"""
    monkeypatch.setattr(
        SEC.Secretary, "judge_same_proposition",
        lambda self, **_kw: {"checked": True, "decision": "same",
                             "reason": "夹具：恒判同一条", "basis": "", "cost": {}})
    st = _store(tmp_path)
    got = _rewrite(st, decision="different")
    assert got.get("ok") is True, (
        "反真空失效：打桩成恒「同一条」之后仍然被拒 ⇒ 这条用例证明不了 b 的绿来自语义门",
        got)
    text = (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    assert _sections(text)["命题"] == PROPOSITION, _sections(text)["命题"]


# ------------------------------------------------------------------ e 没判成 ⇒ fail-closed

@pytest.mark.parametrize("decision", ["maybe", ""], ids=["词表外", "空判词"])
def test_e_an_undecided_judgement_is_refused(tmp_path, decision):
    """e：判定没判成（词表外 / 空）⇒ 受控拒，不许折成「同一条」。"""
    st = _store(tmp_path)
    got = _rewrite(st, decision=decision)
    assert got.get("ok") is False, got
    assert got.get("refused") == PRW.REFUSED_UNJUDGED, got
    assert (pathlib.Path(st.root) / REL).read_bytes() == _manuscript().encode("utf-8")


# ------------------------------------------------------------------ f F 链的入口

def test_f_the_f_chain_entry_delegates_to_the_one_port(tmp_path):
    """f：`AgentF.rewrite_manuscript_proposition` 委托同一个实现（agent=F）。"""
    st = _store(tmp_path)
    _write(st)
    conftest.sign_before_registration(st.root, proof_text=PROOF)
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0002"})
    f.f_secretary = _secretary(st, "same")
    got = f.rewrite_manuscript_proposition(
        manuscript=REL, proposition=PROPOSITION, label="F 攻坚 0002 子目标 S4")
    assert got.get("agent") == "F", got
    assert got.get("ok") is True and got.get("wrote") is True, got
    text = (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    assert _sections(text)["命题"] == PROPOSITION, _sections(text)["命题"]
