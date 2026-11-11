# -*- coding: utf-8 -*-
"""判据：F 的证明手稿与 B 的改写手稿在形式上完全统一（2026-11-04 业主裁定）。

## 业主裁定（逐字）

    F 落证明手稿（`reports/f-proof-<号>.md`）与 B 优化证明落稿
    （`reports/b-proof-<号>.md`）在形式上必须完全统一。

## 判据（a–e 与任务书逐条对应）

| # | 判据 | 钉住的东西 |
|---|---|---|
| a | 同一份正文 + 同一个号，两族各落一份 ⇒ 除前缀与角色名外逐字相同 | `manuscriptform.render_proof_manuscript` 是唯一渲染 |
| a2 | 反真空：把 B 的渲染改回它自己那一套 ⇒ a 立刻红 | a 的绿来自"同一段代码"，不是比较器太松 |
| b | `f-proof-000000-p2.md` / `b-proof-000000-p2.md` 都得到 (000000, 2)；乱名两族都受控拒 | 命名与解析同源（`vsigns.parse_manuscript_name`） |
| c | 带签块的稿改名（两族各一次）⇒ 签块跟着搬、第 9 格按新名重算；sha 不符 ⇒ 不搬 | 搬签块只有一份 |
| d | 带 `## 依赖` 四列表的 f-稿与 b-稿 ⇒ 各落 1 条 `dependencies`；打桩落边失败 ⇒ 两边都不留半截 | 写稿 + 依赖段 + 落边是一次事务 |
| e | 第二份实现不能复活（AST 扫描：同一件事只许一处定义/一处渲染） | "统一"不靠自觉 |

全部 tmp 工作区，不读写 `projects/`（真机工作区只读）。
"""
from __future__ import annotations

import ast
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import bmanuscript as BM  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import manuscriptform as MF  # noqa: E402
from agentflow import manuscriptids as MIDS  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_f import AgentF  # noqa: E402
from agentflow.agent_f.manuscript import promote_manuscript as promote_f  # noqa: E402
from agentflow.secretary import Secretary  # noqa: E402
from agentflow.store import Store  # noqa: E402

SID = "000002"
DEP = "000001"
PLAN = "000000"
SGID = "s1"
#: F 自己的稿号（与命题号无关；2026-11-10 口径）。
MID = "000900"
PROPOSITION = "对任意正整数 n，R(3,4)=9。"
STEP_TEXT = "由定理甲直接得到"
PROOF_TEXT = f"1. {STEP_TEXT}（依据：stmt:{DEP}）"

DEP_TABLE = (
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n"
    f"| 由定理甲 | stmt:{DEP} | 第 1 步 | 1 |\n"
)
EMPTY_DEP_TABLE = (
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n"
    "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n"
)


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _seed(st: Store, stmt_id: str, *, kind: str = "theorem",
          reviewed: bool = False) -> None:
    """铺一条在册命题。`reviewed=True` ⇒ 现算 `pre_theorem`（可引那一档）。

    2026-11-06（业主口径的纠正）：引用了不可引的号是整笔受控拒，所以凡是被
    依赖表引用的那条夹具（`DEP`）都要真的站到 `pre_theorem` 级 —— 这与真机里
    "被引的定理必须先过 V 的逐行走审"同一条口径，不是放宽判据。
    """
    bits: dict = {}
    if reviewed:
        from agentflow import evidencebits as _EB

        bits = _EB.bits_of(proof=True, proof_process="夹具证明正文", reviewed=True,
                           reviewed_by={"verification_id": "v-000001"}, kind=kind)
    row = {
        "stmt_id": stmt_id, "origin": "own_result", "kind": kind,
        "label": f"夹具命题 {stmt_id}", "statement_full": f"夹具命题 {stmt_id}。",
        "statement_text": f"夹具命题 {stmt_id}。", "proof_text": "夹具证明正文。",
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "判据夹具",
        "line_range": {"start": None, "end": None, "label": "夹具"},
        "created_at": "2026-11-04T12:00:00+08:00", "created_by": "secretary-B",
        "bits": bits,
    }
    with st.tx("statements") as tx:
        tx.upsert("statements", row, note="fixture:unify")


def _draft(*, dep_table: str = DEP_TABLE, washed: bool = True,
           title_role: str = "F") -> str:
    text = (
        f"# {title_role} 的证明手稿：判据夹具\n\n"
        "- 命题号：stmt:（还没落号）\n"
        f"- 计划：{PLAN} · 子目标：{SGID}\n\n"
        "## 命题\n\n"
        f"{PROPOSITION}\n\n"
        "## 证明\n\n"
        f"{PROOF_TEXT}\n\n"
        "## 依赖\n\n"
        + dep_table
    )
    return DS.mark_washed(text, actor="secretary-F") if washed else text


def _write(st: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _read(st: Store, rel: str) -> str:
    return (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")


def _sign(st: Store, rel: str, *, sha: str = "") -> str:
    text = _read(st, rel)
    want = sha or VR.text_sha(VS.manuscript_proof_body(text))
    stamped = VS.stamp_manuscript_sign(
        text, proof_sha=want, streak=3, need=3, verdict="成立",
        at="2026-11-04T15:00:00+08:00",
        ledger="verifications/pending/probe.jsonl#v-000001",
        statement_id="", manuscript_id=VS.manuscript_id_of(rel))
    _write(st, rel, stamped)
    return want


def _product() -> dict:
    return {"product": "proof", "strategy": "套用已知定理",
            "why_strategy": "由在册定理逐条读出",
            "steps": [{"n": 1, "text": STEP_TEXT, "cites": [f"stmt:{DEP}"]}]}


def _f_text(st: Store) -> str:
    f = AgentF(st, config={"workspace_root": st.root})
    # 2026-11-10：F 的稿按自己的稿号命名（不传命题号）。命题号由 B 收录时现取，
    # 所以 F 这一份的稿头是 `- 命题号：stmt:（还没落号）` —— 那正是这一轮的真实形态。
    got = f.proof_manuscript(
        _product(), sg={"sid": SGID, "text": PROPOSITION, "testable": ""},
        plan={"plan_id": PLAN}, manuscript_id=MID,
        label=PROPOSITION, proof_no=1)
    assert got.get("ok") is True, got
    return str(got["text"])


def _number_normalized(text: str) -> str:
    """把页头 `- 命题号：` 那一行抹成同一个占位：F 的稿在收录前还没有命题号。

    两族比的是"同一段渲染骨架"；稿头那一格按新口径本来就可以不同（F 的稿号与命题号
    是两件事），把它当差异会让这条判据量错对象。
    """
    import re

    body = _role_normalized(text)
    return re.sub(r"^- 命题号：.*$", "- 命题号：stmt:<号>", body, flags=re.M)


def _role_normalized(text: str) -> str:
    """把标题里的角色名抹成同一个，并去掉登记元信息那几行：判据只允许角色名不同。

    2026-11-07（解耦落地）：一份稿现在是"手稿 + 登记元信息"两段。登记元信息
    （`- 正文sha：` / `- 命题指纹：` / `- 登记时间：` / `- 版本：` / `- 证据种类：`）
    由 `proofregistry` 按登记那一刻补，F 与 B 两族走同一段代码；旧入口
    （`publish_manuscript` / `bmanuscript.land_rewrite`）只落骨架、不补这几行。
    这一条判的要证明的是"两族落的是同一份骨架" ⇒ 比的是骨架；登记元信息有它自己的
    判据（`tests/test_proof_registration_is_decoupled.py` 的 a / i），不在这里重复比。
    """
    marks = ("- 正文sha：", "- 命题指纹：", "- 登记时间：", "- 版本：", "- 证据种类：")
    body = "\n".join(line for line in str(text).replace("\r\n", "\n").split("\n")
                     if not line.strip().startswith(marks))
    return (body.replace("# F 的证明手稿：", "# R 的证明手稿：")
            .replace("# B 的证明手稿：", "# R 的证明手稿："))


# ------------------------------------------------------------------ a 同一份渲染
def test_a_the_two_families_land_the_same_manuscript(tmp_path: pathlib.Path) -> None:
    """a：同一份正文 + 同一个号 ⇒ 两稿除前缀与角色名外逐字相同。"""
    st = _ws(tmp_path)
    _seed(st, DEP, reviewed=True)
    _seed(st, SID)
    f_text = _f_text(st)
    bout = BM.land_rewrite(
        st.root, statement_id=SID, statement_full=PROPOSITION,
        proof_text=DS.proof_body(f_text).strip("\n"),
        label=PROPOSITION, proof_no=1, source_manuscript=f_text,
        plan_id=PLAN, sid=SGID)
    assert bout.get("ok") is True, bout
    assert bout["path"] == f"reports/b-proof-{SID}.md", bout
    b_text = _read(st, bout["path"])
    assert _number_normalized(f_text) == _number_normalized(b_text), (
        "两族的稿不是同一段渲染出来的：\n--- F ---\n"
        f"{f_text}\n--- B ---\n{b_text}")
    # 骨架顺序也是同一条（不是"两稿刚好都含这三节"）。
    for text in (f_text, b_text):
        assert text.index("## 命题") < text.index("## 证明") < text.index("## 依赖"), text
    assert f"- 命题号：stmt:{SID}" in b_text, b_text
    assert f"- 命题号：stmt:{SID}" not in f_text, f_text
    # 洗稿行由同一段代码产出、落在同一个位置（`- 计划：` 的下一行）。
    rows = [{"stmt_id": DEP, "quote": "由定理甲", "step": "第 1 步",
             "path_group": 1}]
    kw = dict(title=PROPOSITION, statement_id=SID, proposition=PROPOSITION,
              proof_text=PROOF_TEXT, dependency_rows=rows, plan_id=PLAN,
              sid=SGID, label=PROPOSITION, proof_no=1,
              wash_actor="secretary-F")
    f_wash = MF.render_proof_manuscript(MF.FAMILY_F, **kw)
    b_wash = MF.render_proof_manuscript(MF.FAMILY_B, **kw)
    assert _role_normalized(f_wash) == _role_normalized(b_wash)
    lines = f_wash.split("\n")
    at_plan = next(i for i, x in enumerate(lines) if x.startswith("- 计划："))
    at_wash = next(i for i, x in enumerate(lines) if x.startswith(DS.WASH_MARK))
    assert at_wash == at_plan + 1, lines[:8]


# ------------------------------------------------------------------ a2 反真空
def test_a2_putting_b_render_back_makes_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a2 反真空：把 B 的渲染改回它自己那一套 ⇒ a 立刻不再逐字相同。"""
    st = _ws(tmp_path)
    _seed(st, DEP, reviewed=True)
    _seed(st, SID)
    f_text = _f_text(st)

    def _old_b_render(*, statement_full, proof_text, statement_id="", label="",
                      proof_no=0, dependency_section="", **_kw):
        """改前 B 的页头（`- 改写手稿：` + `- 标签：`，没有 `- 计划：`）。"""
        return ("# B 的改写手稿：" + str(label or statement_full)[:60] + "\n\n"
                f"- 命题号：stmt:{statement_id}\n"
                f"- 标签：{label}\n\n## 命题\n\n{statement_full}\n\n"
                f"## 证明\n\n{proof_text}\n\n{dependency_section}\n")

    monkeypatch.setattr(BM, "render", _old_b_render)
    bout = BM.land_rewrite(
        st.root, statement_id=SID, statement_full=PROPOSITION,
        proof_text=DS.proof_body(f_text).strip("\n"),
        label=PROPOSITION, proof_no=1, source_manuscript=f_text,
        plan_id=PLAN, sid=SGID)
    assert bout.get("ok") is True, bout
    assert _role_normalized(f_text) != _role_normalized(bout["text"]), (
        "把 B 的渲染改回旧实现之后两稿仍然相同 ⇒ a 那条绿不是「同一段代码」给的")


# ------------------------------------------------------------------ b 同一份命名
def test_b_naming_and_parsing_are_one_function(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：两族的 `<prefix>-proof-<号>[-p<N>].md` 走同一个解析器；乱名两族都拒。"""
    for fam in (MF.FAMILY_F, MF.FAMILY_B):
        got = MF.name_reading(fam, statement_id="000000", proof_no=2)
        assert got.get("ok") is True, got
        assert got["path"] == f"reports/{fam.lower()}-proof-000000-p2.md", got
        parsed = VS.parse_manuscript_name(got["path"])
        assert (parsed["manuscript_id"], parsed["proof_no"]) == ("000000", 2), parsed
        bad = MF.name_reading(fam, statement_id="abc")
        assert bad.get("ok") is False, bad
        assert bad.get("code") == MF.BAD_MANUSCRIPT_NAME, bad

    calls: list[str] = []
    real = VS.parse_manuscript_name

    def _spy(path):
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(VS, "parse_manuscript_name", _spy)
    MF.name_reading(MF.FAMILY_F, statement_id="000000", proof_no=2)
    MF.name_reading(MF.FAMILY_B, statement_id="000000", proof_no=2)
    assert len(calls) == 2, calls

    # 入口层：乱名两族都受控拒、零写入。
    st = _ws(tmp_path)
    _write(st, f"notes/乱名稿.md", _draft())
    # F 的稿号形不对（不是六位号）⇒ 受控拒、零写入（2026-11-10：F 的稿按稿号命名，
    # 命题号不再参与命名 ⇒ 这里要用 `manuscript_id` 而不是 `statement_id` 才量得到）。
    fout = promote_f(st.root, manuscript_id="abc", source="notes/乱名稿.md")
    assert fout.get("promoted") is False, fout
    assert dict(fout.get("problem") or {}).get("kind") == "bad_manuscript_name", fout
    bout = BM.land_rewrite(st.root, statement_id="abc",
                           statement_full=PROPOSITION, proof_text=PROOF_TEXT)
    assert bout.get("ok") is False, bout
    assert bout.get("code") == "bad_manuscript_name", bout
    assert not list((pathlib.Path(st.root) / "reports").glob("*-proof-abc.md"))


# ------------------------------------------------------------------ c 同一份搬签块
def test_c_the_sign_block_moves_for_both_families(tmp_path: pathlib.Path) -> None:
    """c：两族各搬一次稿 ⇒ 签块跟着搬、第 9 格按新名重算；sha 不符 ⇒ 不搬。

    2026-11-10：F 的那一档按稿号搬（`manuscript_id=MID`），B 的那一档照旧按命题号。
    """
    for fam, promote in ((MF.FAMILY_F, promote_f), (MF.FAMILY_B, BM.promote_formal)):
        st = _ws(tmp_path / fam)
        rel = f"notes/{fam}-draft.md"
        _write(st, rel, _draft())
        sha = _sign(st, rel)
        if fam == MF.FAMILY_F:
            got = promote(st.root, manuscript_id=MID, source=rel)
            target = f"reports/f-proof-{MID}.md"
            want_id = MID
        else:
            got = promote(st.root, statement_id=SID, source=rel)
            target = f"reports/b-proof-{SID}.md"
            want_id = SID
        assert got.get("promoted") is True, (fam, got)
        assert got.get("path") == target, (fam, got)
        assert got.get("sign_moved") is True, (fam, got)
        block = VS.manuscript_sign_reading(_read(st, target), manuscript_path=target)
        assert block.get("found") is True and block.get("signed") is True, (fam, block)
        assert block.get("proof_sha256") == sha, (fam, block)
        assert block.get("manuscript_id") == want_id, (fam, block)
        assert block.get("identity_state") == "resolved", (fam, block)

        # sha 不符 ⇒ 不搬（新稿从"没有签块"开始）。
        st2 = _ws(tmp_path / f"{fam}-stale")
        rel2 = f"notes/{fam}-stale.md"
        _write(st2, rel2, _draft())
        _sign(st2, rel2, sha="0" * 64)
        got2 = (promote(st2.root, manuscript_id=MID, source=rel2)
                if fam == MF.FAMILY_F else promote(st2.root, statement_id=SID, source=rel2))
        assert got2.get("promoted") is True, (fam, got2)
        assert dict(got2.get("problem") or {}).get("kind") == "sign_sha_mismatch", (
            fam, got2)
        assert VS.SIGN_MARK not in _read(st2, target), (
            f"{fam}: sha 不符的块被搬进了正式稿")


    # 改标题（B 那一族）：正文没变、页头标题变了 ⇒ 签块按 sha 相符跟着搬，
    # 而不是"标题一改，签就被另一个整文件写盖掉"。
    st3 = _ws(tmp_path / "B-retitle")
    target3 = f"reports/b-proof-{SID}.md"
    old_title = ("# B 的证明手稿：旧标题\n\n"
                 f"- 命题号：stmt:{SID}\n- 证明号：1\n\n"
                 "## 命题\n\n" + PROPOSITION + "\n\n## 证明\n\n" + PROOF_TEXT
                 # 2026-11-05：这里原来用空表，而 PROOF_TEXT 的正文点了 `stmt:{DEP}`
                 # —— 那正是缺陷甲的形态（正文引了、表里没写）。现在它会被
                 # `deps_table_disagrees_with_proof` 整份退回（判据见
                 # tests/test_deps_table_and_proof_must_agree.py）。这一条量的是
                 # "改标题时签块怎么搬"，与依赖面无关 ⇒ 用与正文一致的 DEP_TABLE，
                 # 断言一个字没动。
                 + "\n\n## 依赖\n\n" + DEP_TABLE)
    _write(st3, target3, old_title)
    old_sha = _sign(st3, target3)
    bout3 = BM.land_rewrite(
        st3.root, statement_id=SID, statement_full=PROPOSITION,
        proof_text=PROOF_TEXT, label="新标题", proof_no=1,
        # 2026-11-05：改写稿的依赖段由来源稿现渲染（`_dependency_rows(source)`）。
        # 不给来源稿而正文又点了 `stmt:` ⇒ 依赖表只能是 0 行，那正是缺陷甲的形态，
        # 现在会被整份退回。这一条量的是"改标题时签块怎么搬"⇒ 把已签的旧稿当来源交。
        source_manuscript=old_title)
    assert bout3.get("ok") is True, bout3
    assert bout3.get("signed") is True, bout3
    final3 = _read(st3, target3)
    assert "新标题" in final3.split("\n")[0], final3.split("\n")[:2]
    block3 = VS.manuscript_sign_reading(final3, manuscript_path=target3)
    assert block3.get("found") is True and block3.get("signed") is True, block3
    assert block3.get("proof_sha256") == old_sha, block3
    assert block3.get("manuscript_id") == SID, block3


# ------------------------------------------------------------------ d 同一份落盘事务
def _writer(st: Store, used_by: str):
    sec = Secretary("B", root=st.root, store=st)
    kinds = {DEP: "theorem", SID: "theorem"}

    def _write_edges(rows):
        groups = DS.deps_groups(rows, kinds)
        return sec.record_manuscript_dependency_face(
            used_by, groups, note="test:unify-dependency-transaction")

    return _write_edges


def test_d_dependency_edges_land_in_the_same_transaction(
        tmp_path: pathlib.Path) -> None:
    """d：两族各落一份带四列表的稿 ⇒ 各 1 条依赖边；落边打桩失败 ⇒ 两边都不留半截。"""
    # F 那一族：转正（notes/ → reports/f-proof-<号>.md）
    st_f = _ws(tmp_path / "f")
    _seed(st_f, DEP, reviewed=True)
    _seed(st_f, SID)
    _write(st_f, "notes/f-dep.md", _draft())
    fout = promote_f(st_f.root, manuscript_id=SID, source="notes/f-dep.md",
                     store=st_f, write_dependencies=_writer(st_f, SID))
    assert fout.get("promoted") is True, fout
    f_deps = [dict(r) for r in st_f.rows("dependencies")]
    assert len(f_deps) == 1, f_deps
    assert str(f_deps[0].get("used_by")) == f"stmt:{SID}", f_deps
    assert str(f_deps[0].get("source_stmt_id")) == DEP, f_deps

    # B 那一族：改写落稿（reports/b-proof-<号>.md）
    st_b = _ws(tmp_path / "b")
    _seed(st_b, DEP, reviewed=True)
    _seed(st_b, SID)
    bout = BM.land_rewrite(
        st_b.root, statement_id=SID, statement_full=PROPOSITION,
        proof_text=PROOF_TEXT, label="R(3,4)=9", proof_no=1,
        source_manuscript=_draft(), write_dependencies=_writer(st_b, SID))
    assert bout.get("ok") is True, bout
    b_deps = [dict(r) for r in st_b.rows("dependencies")]
    assert len(b_deps) == 1, b_deps
    assert str(b_deps[0].get("used_by")) == f"stmt:{SID}", b_deps
    assert str(b_deps[0].get("source_stmt_id")) == DEP, b_deps

    # 打桩：落边函数说没写成 ⇒ 刚写的稿回滚（原本没有 ⇒ 删掉），两边都不留半截。
    def _broken(_rows):
        return {"checked": False, "refused": "stub_edges_failed",
                "reason": "判据打桩：落边这一步失败"}

    st_f2 = _ws(tmp_path / "f-broken")
    _seed(st_f2, DEP, reviewed=True)
    _seed(st_f2, SID)
    _write(st_f2, "notes/f-dep.md", _draft())
    fout2 = promote_f(st_f2.root, manuscript_id=SID, source="notes/f-dep.md",
                      store=st_f2, write_dependencies=_broken)
    assert fout2.get("promoted") is False, fout2
    assert dict(fout2.get("problem") or {}).get(
        "kind") == "dependency_edges_not_written", fout2
    assert not (pathlib.Path(st_f2.root) / f"reports/f-proof-{SID}.md").exists(), (
        "F：落边失败却留下了稿（半截事务）")
    assert not list(st_f2.rows("dependencies")), "F：落边失败却留下了依赖行"

    st_b2 = _ws(tmp_path / "b-broken")
    _seed(st_b2, DEP, reviewed=True)
    _seed(st_b2, SID)
    bout2 = BM.land_rewrite(
        st_b2.root, statement_id=SID, statement_full=PROPOSITION,
        proof_text=PROOF_TEXT, source_manuscript=_draft(),
        write_dependencies=_broken)
    assert bout2.get("ok") is False, bout2
    assert bout2.get("code") == "dependency_edges_not_written", bout2
    assert not (pathlib.Path(st_b2.root) / f"reports/b-proof-{SID}.md").exists(), (
        "B：落边失败却留下了稿（半截事务）")
    assert not list(st_b2.rows("dependencies")), "B：落边失败却留下了依赖行"


# ------------------------------------------------------------------ e 不许有第二份
def _tree(path: pathlib.Path) -> ast.Module:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return ast.parse(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ f 同一批拒信码
def test_f_the_five_refusal_codes_are_shared(tmp_path: pathlib.Path) -> None:
    """五个码与 detail 模板两族共用（同一个 code ⇒ 同一句话）。"""
    # not_washed：同一个判定函数对两族都出这个码。
    unwashed = _draft(washed=False)
    for fam in (MF.FAMILY_F, MF.FAMILY_B):
        got = MF.validate_manuscript(unwashed, require_washed=True)
        assert got.get("code") == "not_washed", (fam, got)
        assert got.get("why") == MF.detail(MF.NOT_WASHED), (fam, got)

    # multiple_propositions：F 转正与 B 落稿都受控拒，且 detail 逐字相同。
    two_props = _draft().replace(
        "## 证明", "## 命题\n\n另一条命题。\n\n## 证明", 1)
    st = _ws(tmp_path / "multi-f")
    _write(st, "notes/two.md", two_props)
    fout = promote_f(st.root, manuscript_id=SID, source="notes/two.md")
    assert dict(fout.get("problem") or {}).get("kind") == "multiple_propositions", fout
    st_b = _ws(tmp_path / "multi-b")
    bout = BM.land_rewrite(
        st_b.root, statement_id=SID, statement_full=PROPOSITION,
        proof_text=PROOF_TEXT, source_manuscript=two_props)
    assert bout.get("code") == "multiple_propositions", bout
    assert (dict(fout.get("problem") or {}).get("why")
            == dict(bout.get("problem") or {}).get("why")), (fout, bout)
    assert dict(fout.get("problem") or {}).get("why") == MF.detail(
        MF.MULTIPLE_PROPOSITIONS, count=2), fout

    # no_proof_section：两族同一个码。
    no_proof = _draft().replace("## 证明", "## 不叫证明", 1)
    st_f2 = _ws(tmp_path / "noproof-f")
    _write(st_f2, "notes/np.md", no_proof)
    fout2 = promote_f(st_f2.root, manuscript_id=SID, source="notes/np.md")
    assert dict(fout2.get("problem") or {}).get("kind") == "no_proof_section", fout2
    st_b2 = _ws(tmp_path / "noproof-b")
    bout2 = BM.land_rewrite(
        st_b2.root, statement_id=SID, statement_full=PROPOSITION,
        proof_text=PROOF_TEXT, source_manuscript=no_proof)
    assert bout2.get("code") == "no_proof_section", bout2
    assert MF.detail(MF.NO_PROOF_SECTION) == dict(fout2.get("problem") or {}).get("why")

    # dependency_section_missing：正文里有引用、而稿里没有那一节 ⇒ 两族同一个码。
    no_dep = ("# F 的证明手稿：判据夹具\n\n- 命题号：stmt:（还没落号）\n\n"
              "## 命题\n\n" + PROPOSITION + "\n\n## 证明\n\n" + PROOF_TEXT + "\n")
    st_f3 = _ws(tmp_path / "nodep-f")
    _write(st_f3, "notes/nd.md", DS.mark_washed(no_dep, actor="secretary-F"))
    fout3 = promote_f(st_f3.root, manuscript_id=SID, source="notes/nd.md")
    assert dict(fout3.get("problem") or {}).get(
        "kind") == "dependency_section_missing", fout3
    st_b3 = _ws(tmp_path / "nodep-b")
    bout3 = BM.land_rewrite(
        st_b3.root, statement_id=SID, statement_full=PROPOSITION,
        proof_text=PROOF_TEXT, source_manuscript=no_dep)
    assert bout3.get("code") == "dependency_section_missing", bout3
    assert (dict(fout3.get("problem") or {}).get("why")
            == dict(bout3.get("problem") or {}).get("why")), (fout3, bout3)
    assert dict(fout3.get("problem") or {}).get("why") == MF.detail(
        MF.DEPENDENCY_SECTION_MISSING, refs=1), fout3


# ------------------------------------------------------------------ e 不许有第二份
def _module_defs(path: pathlib.Path) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for node in _tree(path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = node
    return out


def _calls_attr(node: ast.AST, attr: str) -> bool:
    return any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
               and x.func.attr == attr for x in ast.walk(node))


def test_e_there_is_no_second_implementation_to_come_back() -> None:
    """e：命名 / 渲染 / 搬签 / 转正各只有一份；旧模块里只许剩转发。"""
    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
    fm = root / "manuscriptform.py"
    af = root / "agent_f" / "manuscript.py"
    bm = root / "bmanuscript.py"
    vs = root / "vsigns.py"
    assert fm.is_file()
    assert "carry_sign_block" in _module_defs(fm)
    assert MF.carry_sign_block is MF.carry_sign_block  # noqa: PLR0124 - 只是取到对象
    # 1. 搬签块：全 src 只有 manuscriptform 一份定义（别的模块只能 import/转发）。
    defined: dict[str, list[str]] = {}
    for path in root.rglob("*.py"):
        try:
            defs = _module_defs(path)
        except SyntaxError:  # pragma: no cover - 源码树里不该有语法错
            continue
        for name in ("carry_sign_block", "ensure_statement_line",
                     "formal_shape_problem", "parse_manuscript_name"):
            if name in defs:
                defined.setdefault(name, []).append(str(path.relative_to(root)))
    assert defined["carry_sign_block"] == ["manuscriptform.py"], defined
    assert defined["ensure_statement_line"] == ["manuscriptform.py"], defined
    assert defined["formal_shape_problem"] == ["manuscriptform.py"], defined
    assert defined["parse_manuscript_name"] == ["vsigns.py"], defined
    # 2. 旧模块里没有自己的正则 / 渲染体：只许剩下对唯一实现的转发。
    af_defs = _module_defs(af)
    bm_defs = _module_defs(bm)
    for name in ("carry_sign_block", "ensure_statement_line", "formal_shape_problem"):
        assert name not in af_defs, (
            f"`agent_f/manuscript.py` 里又出现了第二份 `{name}`（应只从 manuscriptform 转发）")
    assert "render" in bm_defs, bm_defs.keys()
    assert _calls_attr(bm_defs["render"], "render_proof_manuscript"), (
        "`bmanuscript.render` 不再转发到唯一渲染")
    assert _calls_attr(bm_defs["land_rewrite"], "commit_manuscript"), (
        "`bmanuscript.land_rewrite` 不再走唯一落盘事务")
    assert _calls_attr(af_defs["promote_manuscript"], "promote_formal"), (
        "`agent_f.manuscript.promote_manuscript` 不再转发到唯一转正")
    # 3. 文件名规则的字面量只许出现在唯一实现 + 唯一判定表 + 保留表里。
    # `manuscriptfamily.py` 是 2026-11-09（T2）收编后的唯一真身：前缀、目录、号形、
    # 后缀都在那一张表里；`manuscriptform` / `depsection` 从它派生，不再各写一份。
    # `tools/fs_tools.py` 那一处是防线（保留目录里 `f-proof-*` 不许模型 fs.write），
    # 不是第二份命名实现：它按文件名形态拦，不参与"这份稿叫什么"。
    prefix_hits = [str(p.relative_to(root)) for p in root.rglob("*.py")
                   if '"f-proof-' in p.read_text(encoding="utf-8")
                   and p.name not in ("manuscriptfamily.py", "manuscriptform.py",
                                      "depsection.py", "fs_tools.py")]
    assert prefix_hits == [], prefix_hits
    assert "re.compile" not in bm.read_text(encoding="utf-8"), (
        "`bmanuscript.py` 又长出了自己的编号正则")
    assert "re.compile" not in af.read_text(encoding="utf-8"), (
        "`agent_f/manuscript.py` 又长出了自己的形状正则")


# ------------------------------------------------------------------ a-真入口（走查 D4）
#
# 2026-11-05 走查 walk-e2e 的 D4：改前的 a 只测 `land_rewrite` 直调，而运行期
# `B.register_statement` 只把 `label` 递给落稿函数 ⇒ 真落下来的 b-稿缺 `- 计划：`、
# 缺洗稿行、还多一行 `- 标签：`（与 f-族不是同一个骨架）。这一条改走两个真实入口：
# F 的 `proof_manuscript` → `publish_manuscript` 落 f-稿；B 的 `register_statement`
# 拿同一份稿落 b-稿；两稿除标题里的角色名外逐字比。

def _role_only(text: str) -> str:
    return _role_normalized(text)


def _no_cite_product() -> dict:
    """不引用任何在册命题的证明（这样稿里是空依赖表，不用抬被引命题的档位）。"""
    return {"product": "proof", "strategy": "直接计算", "why_strategy": "由定义与假设直接得到",
            "steps": [{"n": 1, "text": STEP_TEXT, "cites": [], "assumption": False}]}


def _stamp(st: Store, rel: str, *, sid: str, body: str) -> None:
    """把一张盖住 body 的 V 签块写进稿里，并落下它的独立台账行 + 可复算签。

    2026-11-05 晚（业主裁定「签必须有独立台账背书」）：B 的收录认签（`vsigns.
    bits_after_sign`）现在会按签块上 `台账=` 那格去读 `verifications/<号>.jsonl`，
    `ledger_row_missing` ⇒ 不认这一块。所以夹具不能再只盖块（那只是稿上的一句话）：
    同一份正文先由 V 连判三转「成立」，签块锚到第 3 行。

    2026-11-10（D268 批 2 跟进）：批 2 起「签」只认 `out/vsigns/<正文 sha>.json` 的
    可复算凭据（块降为渲染视图、`record_verification` 的三行只是票数）。旧夹具在这里
    写三行台账 + 盖块 = `unissued`（够票、没有签文件），于是 `_unsigned_proof_gate`
    按新口径拒。改用批 2 自己那份公共夹具
    （`_credential_fixture.issue_credential`：三票同源 + `vsigns.issue` 写签），
    再按它给出的 ledger 把块盖上去 —— 块仍是视图，认签看签文件。改的是夹具，不是
    断言：`_stamp` 本来就是"V 签过这一版"的替身。
    """
    from _credential_fixture import issue_credential

    path = pathlib.Path(st.root) / rel
    text = path.read_text(encoding="utf-8")
    signed = issue_credential(st.root, proof_text=str(body).strip("\n"),
                              statement_id=str(sid), manuscript=str(rel), proof_no=1)
    ledger = str(dict(signed.get("sign") or {}).get("ledger") or "")
    path.write_text(VS.stamp_manuscript_sign(
        text, proof_sha=VR.text_sha(str(body).strip("\n")),
        streak=VR.SIGN_STREAK_NEED,
        need=VR.SIGN_STREAK_NEED, verdict="成立", at="2026-11-05T12:00:00+08:00",
        ledger=ledger,
        statement_id=sid, manuscript_id=VS.manuscript_id_of(rel)), encoding="utf-8")


def _real_entries_run(st: Store) -> tuple[str, str, str]:
    """跑一遍真实入口：返回 (f-稿签之前的全文, b-稿全文, b-稿路径)。"""
    from agentflow.agent_b import AgentB

    proposition = PROPOSITION
    _seed(st, SID)
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == SID)
    row["statement_full"] = proposition
    row["statement_text"] = proposition
    row["proof_text"] = "旧正文（B 要改写的那一版）。"
    with st.tx("statements", actor="test", note="fixture:d4") as tx:
        tx.upsert("statements", row)

    f = AgentF(st, config={"workspace_root": st.root})
    got = f.proof_manuscript(_no_cite_product(),
                             sg={"sid": SGID, "text": proposition, "testable": ""},
                             plan={"plan_id": PLAN})
    assert got.get("ok") is True, got
    # F 的秘书在 proof_manuscript 之后、publish 之前洗一遍（真实入口的次序）。
    got["text"] = DS.mark_washed(str(got["text"]), actor="secretary-F")
    # 2026-11-10：收录不改稿名 ⇒ 洗过的那一份要自己写回 F 的稿号（`publish` 不再改名）。
    # 2026-11-10 第二刀：`publish_manuscript` 收不到命题号（签名里没有那一格）。
    rel_f = str(got["path"])
    (pathlib.Path(st.root) / rel_f).write_text(str(got["text"]), encoding="utf-8")
    published = f.publish_manuscript(got, manuscript_id=VS.manuscript_id_of(rel_f))
    assert published.get("published") is False, published
    assert str(published.get("path") or "") == rel_f, published
    f_unsigned = (pathlib.Path(st.root) / rel_f).read_text(encoding="utf-8")
    body = DS.proof_body(f_unsigned).strip("\n")
    # B 的入库闸要一份盖住正文的签（签块在稿上；签另算）。
    _stamp(st, rel_f, sid=SID, body=body)

    out = AgentB(st, extractor=None, extract_text=None).register_statement(
        statement_full=proposition, statement_text=proposition,
        origin="own_result", kind="conjecture", label=proposition,
        proof_text=body, proof_manuscript=rel_f, evidence_kind="heuristic",
        doc_id="000000", line_range={"start": 1}, quote_verified=False,
        quote_reason="判据夹具：自产命题")
    assert out.get("ok") is True, out
    b_ms = dict(out.get("b_manuscript") or {})
    rel_b = str(b_ms.get("path") or "")
    b_mid = str(b_ms.get("manuscript_id") or "")
    # 2026-11-11（业主裁定 ①「B侧稿号和命题号耦合是错的」）：B 的稿号来自 B 自己那条
    # 号段（`counters.bmanuscript`，经 `manuscriptids.next_manuscript_id(family=...)`），
    # 不再由命题号拼。断言从"字面等于 `b-proof-<命题号>`"换成更紧的三条：
    #   ① 这一笔真的带了稿号；② 路径恰好是那个稿号的规范名；③ 计数器已推到 稿号+1。
    assert b_mid, out
    assert rel_b == MIDS.canonical_rel(b_mid, family="b-proof"), out
    assert MIDS.peek_manuscript_counter(st, family="b-proof") == int(b_mid) + 1, out
    return f_unsigned, _read(st, rel_b), rel_b


def test_a2_the_real_entries_land_the_same_manuscript(tmp_path: pathlib.Path) -> None:
    """D4 a：经 `B.register_statement` 落的 b-稿与经 `F.publish_manuscript` 落的 f-稿
    逐字相同（只差标题里的角色名）。"""
    st = _ws(tmp_path)
    f_unsigned, b_text, _rel_b = _real_entries_run(st)
    assert _number_normalized(f_unsigned) == _number_normalized(b_text), (
        "两族经真实入口落下来的稿不是同一个骨架：\n--- F ---\n"
        f"{f_unsigned}\n--- B ---\n{b_text}")
    # 三行页头与三节都在（改前 B 缺 `- 计划：` / 洗稿行、多 `- 标签：`）。
    # 2026-11-11 业主裁定：`- 证明号：` 在手稿产出侧退役 ⇒ 两族新写的稿都没有这一行。
    for mark in ("- 命题号：stmt:", "- 计划：", "- 依赖面洗稿："):
        assert mark in b_text, (mark, b_text.split("\n")[:8])
    assert "- 证明号：" not in b_text, b_text.split("\n")[:8]
    assert "- 证明号：" not in f_unsigned, f_unsigned.split("\n")[:8]
    assert "- 标签：" not in b_text, b_text.split("\n")[:8]


def test_a2b_reverse_vacuum_dropping_the_three_arguments_makes_it_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D4 b：把 `plan_id` / `sid` / `wash_actor` 从调用点摘掉 ⇒ a 变红。"""
    from agentflow import bmanuscript as BM

    real = BM.header_reading

    def _without_three(text):
        got = dict(real(text))
        got.update(plan_id="", sid="", wash_actor="", wash_filled="")
        return got

    monkeypatch.setattr(BM, "header_reading", _without_three)
    st = _ws(tmp_path)
    f_unsigned, b_text, _rel_b = _real_entries_run(st)
    assert _role_only(f_unsigned) != _role_only(b_text), (
        "摘掉 plan_id / sid / wash_actor 之后两稿仍逐字相同 ⇒ a 的绿不是那三样给的")
    # c：f-族自己的稿一个字不许变（同一份渲染，b 侧的参数改动不回写 f）
    assert "- 计划：" in f_unsigned and "- 依赖面洗稿：" in f_unsigned, (
        f_unsigned.split("\n")[:8])
