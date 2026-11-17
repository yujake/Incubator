# -*- coding: utf-8 -*-
"""D1：被闸拒掉的登记必须零盘写（C-1：落稿挪到闸后 + 显式 `land_manuscript`）。

## 缺陷现场（审计 + 98b）

`_land_b_manuscript` 在 `_unsigned_proof_gate` 之前执行 ⇒ 一笔被签闸 / 依赖面闸
拒掉的登记仍在盘上留下 `reports/b-proof-<命题号>.md`。真机 10:46:46 那笔：
稿在、台账 `proof_text` 空、`statements` 5 行全 `conjecture`。

## 这一份钉住的六件事

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | 无签闸拒 ⇒ 盘上零新增文件（before=0 / after=0），拒信点名「稿没有落盘」+ 一句改法 | 改前 after=1（`reports/b-proof-000000.md`） |
| b | 依赖面闸拒 ⇒ 同样零新增文件（before=0 / after=0） | 改前 after=1 |
| c | 正控：过所有闸的那一笔照常落 `reports/b-proof-<号>.md`，`## 证明` 的 sha 正确 | 改后不许把落稿一起删掉（这条在旧实现上也绿，防"删过头"） |
| d | 幂等：显式 `land_manuscript` 落一次、同内容再落一次 ⇒ `ok=True` / `written=False` / `preserved=True`，只有一份稿、不改名 | 这条同时钉"`preserved ⇒ ok=True`"（改前目标稿已存在分支不设 ok） |
| e | 反真空（源码顺序）：`_register_statement_impl` 里 `_land_b_manuscript` 的调用行号必须晚于 `_self_authored_gate` / `_unsigned_proof_gate` | 把调用挪回闸前 ⇒ 当场红 |
| f | 载体路：显式落稿 → V 三转签 → 带签登记成功；登记时隐式落稿幂等、不毁签 | 旧 `test_b_rewrite_manuscript_gets_signed::a` 的等价物；C-1 不许把这条真路挖断 |

零模型调用：不派 V、不调秘书模型；签走 `conftest.sign_for_the_gate` 的真台账写口。
"""
from __future__ import annotations

import ast
import contextlib
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from conftest import seed_statement_row, sign_for_the_gate  # noqa: E402

from agentflow import conductor as CND        # noqa: E402
from agentflow import depsection as DS         # noqa: E402
from agentflow import proofregistry as PR      # noqa: E402
from agentflow import schema as S              # noqa: E402
from agentflow import vsigns as VS             # noqa: E402
from agentflow.agent_b import AgentB           # noqa: E402
from agentflow.agent_v import AgentV           # noqa: E402
from agentflow.store import Store              # noqa: E402
from test_agent_v_exhaustion_review import _v_secretary  # noqa: E402
from test_v_reviews_three_times_before_signing import (  # noqa: E402
    CLEAN_REPLY, _ReviewSeam)

FULL = "设 G 是 3-正则群；则弦长函数不是常值（D1 判据）。"
TEXT = "弦长函数不是常值（D1 判据）"
P_OLD = "1. 旧版：由定义直接得到。\n2. 结论成立。"
P_NEW = "1. 新版：先取 ε>0。\n2. 由 1 与假设得结论。"
LOW_FULL = "引理 A：1+1=2。"
LOW_TEXT = "1+1=2"
LOW_PROOF = "1. 另有其证。"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _b(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None, config={})


def _own(**kw) -> dict:
# 2026-11-17（语义纠正）：`derived_from` / `source_lit_id` 是可选信息（`origin` 只是状态：自产/引用）；这一份夹具不测来路。
    base = {"origin": "own_result", "derived_from": ["999999"], "statement_full": FULL, "statement_text": TEXT,
            "label": TEXT, "doc_id": S.format_id(0),
            "line_range": {"start": 1}, "quote_verified": False,
            "quote_reason": "own_result：判据夹具"}
    base.update(kw)
    return base


def _seed_target(st: Store) -> str:
    """在册一条 conjecture（旧正文 P_OLD）；这一笔要改写的正是它。"""
    row = seed_statement_row(
        st, proof_text=P_OLD, statement_full=FULL, statement_text=TEXT,
        kind="conjecture", label=TEXT, stmt_id="000000",
        quote_reason="own_result：判据夹具", doc_id=S.format_id(0),
        line_range={"start": 1})
    return str(row["stmt_id"])


def _files(st: Store) -> list[str]:
    """工作区里所有文件的相对路径（"零新增文件"按整棵树数，不只数 b-proof）。"""
    root = pathlib.Path(st.root)
    return sorted(str(p.relative_to(root)).replace("\\", "/")
                  for p in root.rglob("*") if p.is_file())


def _b_files(st: Store) -> list[str]:
    base = pathlib.Path(st.root) / "reports"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.glob("b-proof-*.md"))


def _row(st: Store, sid: str) -> dict:
    return dict(next(r for r in st.rows("statements") if str(r["stmt_id"]) == sid))


def _manuscript(body: str, *, sid: str, dep_sid: str) -> str:
    """一份三节齐全的来源稿：形状过得了落稿校验，档位由依赖面闸拒。"""
    return (
        "# F 的证明手稿：D1 判据\n\n"
        "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
        f"## 命题\n\n{FULL}\n\n"
        f"## 证明\n\n{body}\n\n"
        "## 依赖\n\n"
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n"
        f"| 由命题 A 得。 | stmt:{dep_sid} | 第 1 步 | 1 |\n")


# ============================================================ a 无签闸拒 ⇒ 零盘写
def test_a_the_unsigned_gate_leaves_no_new_file(tmp_path: pathlib.Path) -> None:
    """a：conjecture 改写、无签 ⇒ `proof_without_v_sign`；盘上零新增文件。"""
    st = _ws(tmp_path)
    sid = _seed_target(st)
    before = _files(st)
    assert _b_files(st) == [], _b_files(st)

    got = _b(st).register_statement(**_own(kind="conjecture"), proof_text=P_NEW)

    assert got.get("ok") is False, got
    assert got.get("kind") == "proof_without_v_sign", got
    # 改前读数：这一格是 ['b-proof-000000.md']（after=1）。
    assert _files(st) == before, (
        f"被无签闸拒掉的登记在盘上留下了文件：{[p for p in _files(st) if p not in before]}")
    assert _b_files(st) == [], _b_files(st)
    err = str(got.get("error") or "")
    assert "稿没有落盘" in err, f"拒信没点名稿没有落盘：{err}"
    assert "建议" in err or "改法" in err, f"拒信没给一句怎么做：{err}"
    # 台账那一行一个字不动（不是"稿没落、账写了"）。
    assert _row(st, sid)["proof_text"] == P_OLD, _row(st, sid)["proof_text"]


# ============================================================ b 依赖面闸拒 ⇒ 零盘写
def test_b_the_dependency_gate_leaves_no_new_file(tmp_path: pathlib.Path) -> None:
    """b：依赖表引了一条不够档的命题 ⇒ 依赖面闸拒，盘上零新增文件。"""
    st = _ws(tmp_path)
    sid = _seed_target(st)
    seed_statement_row(
        st, proof_text=LOW_PROOF, statement_full=LOW_FULL, statement_text=LOW_TEXT,
        kind="conjecture", label="引理 A", stmt_id="000001",
        quote_reason="own_result：判据夹具")
    body = "1. 由引理 A（stmt:000001）直接得到。\n2. 结论成立。"
    before = _files(st)

    got = _b(st).register_statement(
        **_own(kind="conjecture"), proof_text=body,
        proof_manuscript=_manuscript(body, sid=sid, dep_sid="000001"))

    assert got.get("ok") is False, got
    assert got.get("kind") == DS.REFUSED_LEVEL_TOO_LOW, got
    # 改前读数：这一格是 ['b-proof-000000.md']（after=1）。
    assert _files(st) == before, (
        f"被依赖面闸拒掉的登记在盘上留下了文件：{[p for p in _files(st) if p not in before]}")
    assert _b_files(st) == [], _b_files(st)
    assert _row(st, sid)["proof_text"] == P_OLD, _row(st, sid)["proof_text"]
    assert not [d for d in st.rows("dependencies")
                if str(d.get("used_by") or "").startswith(f"stmt:{sid}")], (
        "被拒的那一笔把依赖边写进去了")


# ============================================================ c 正控：过闸照常落
def test_c_a_registration_that_passes_every_gate_still_lands(
        tmp_path: pathlib.Path) -> None:
    """c：同一笔先拿到覆盖 P_NEW 的签 ⇒ 过全闸，稿照常落、sha 正确。"""
    st = _ws(tmp_path)
    sid = _seed_target(st)
    sign_for_the_gate(st.root, statement_id=sid, proof_text=P_NEW, store=st)

    got = _b(st).register_statement(**_own(kind="conjecture"), proof_text=P_NEW)

    assert got.get("ok") is True, got
    rel = f"reports/b-proof-{sid}.md"
    path = pathlib.Path(st.root) / rel
    assert path.is_file(), f"过闸的那一笔没有落稿：{rel}"
    text = path.read_text(encoding="utf-8")
    for heading in ("## 命题", "## 证明", "## 依赖"):
        assert heading in text, heading
    assert PR.proof_sha(VS.manuscript_proof_body(text)) == PR.proof_sha(P_NEW), (
        "落下来的稿里 `## 证明` 的 sha 与这一笔交的正文不符")
    assert _row(st, sid)["proof_text"] == P_NEW, _row(st, sid)["proof_text"]
    assert _b_files(st) == [f"b-proof-{sid}.md"], _b_files(st)


# ============================================================ d 幂等
def test_d_replaying_the_same_landing_preserves_the_one_file(
        tmp_path: pathlib.Path) -> None:
    """d：显式落稿两次 ⇒ 第二遍 `ok=True/written=False/preserved=True`，一份、不改名。

    附加要求 ①：`_land_b_manuscript` 的"目标稿已存在"分支此前不设 `ok`（只给
    `written/preserved`），调用方 `if got.get("ok")` 会把它读成失败。这一条把
    "preserved ⇒ ok=True"钉死。
    """
    st = _ws(tmp_path)
    sid = _seed_target(st)
    b = _b(st)
    first = b.land_manuscript(
        statement_id=sid, statement_full=FULL, proof_text=P_NEW, label=TEXT,
        proof_no=1)
    assert first.get("ok") is True, first
    rel = str(first.get("path") or "")
    assert rel == f"reports/b-proof-{sid}.md", rel
    assert first.get("written") is True, first
    assert first.get("sha256") == PR.proof_sha(P_NEW), first
    before_text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")

    again = b.land_manuscript(
        statement_id=sid, statement_full=FULL, proof_text=P_NEW, label=TEXT,
        proof_no=1)

    assert again.get("ok") is True, again
    assert again.get("written") is False, again
    assert again.get("preserved") is True, again
    assert again.get("path") == rel, again
    assert again.get("sha256") == PR.proof_sha(P_NEW), again
    assert _b_files(st) == [f"b-proof-{sid}.md"], _b_files(st)
    assert (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") == before_text, (
        "重放把同一份稿的字节改了")


# ============================================================ f 载体路不许断
@contextlib.contextmanager
def _submitted_by_b():
    """这一趟 V 是 B 派出来的 ⇒ 收方 = `secretary:B`（签块落回 B 的稿）。"""
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-b-000001",
                        parent_role="B"):
        yield


def test_f_the_b_rewrite_carrier_road_still_works(tmp_path: pathlib.Path) -> None:
    """f：显式落稿 → V 签 → 带签登记 ⇒ 台账换正文；载路不许断（C-1）。"""
    st = _ws(tmp_path)
    sid = _seed_target(st)
    b = _b(st)
    landed = b.land_manuscript(
        statement_id=sid, statement_full=FULL, proof_text=P_NEW, label=TEXT,
        proof_no=1)
    assert landed.get("ok") is True, landed
    rel = str(landed.get("path") or "")
    assert rel == f"reports/b-proof-{sid}.md", rel
    assert (pathlib.Path(st.root) / rel).is_file(), f"显式落稿没写出 {rel}"

    seam = _ReviewSeam([CLEAN_REPLY])
    v = AgentV(st, workspace_root=st.root, llm=seam,
               secretary=_v_secretary(st))
    with _submitted_by_b():
        reviewed = v.verify_proof(statement_id=sid, proof_manuscript=rel)
    assert reviewed.get("checked") is True, reviewed
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    block = VS.manuscript_sign_reading(text, manuscript_path=rel)
    assert block.get("found") is True and block.get("signed") is True, block
    assert block.get("signer") == "secretary:B", block

    filed = b.register_statement(
        **_own(kind="theorem"), proof_text=P_NEW, proof_manuscript=text)
    assert filed.get("ok") is True, filed
    row = _row(st, sid)
    assert row["proof_text"] == P_NEW, row["proof_text"]
    assert dict(row.get("bits") or {}).get("reviewed") is True, row.get("bits")
    # 带签重交时隐式落稿再跑一次也是幂等：同一路径、一份稿、签块不被毁。
    assert _b_files(st) == [f"b-proof-{sid}.md"], _b_files(st)
    after = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    assert VS.manuscript_sign_reading(after, manuscript_path=rel).get("signed") is True, (
        "带签登记把稿上的签块毁掉了")


# ============================================================ e 反真空（源码顺序）
def test_e_the_landing_call_is_after_every_gate() -> None:
    """e：落稿调用必须晚于自产签闸与无签闸；挪回闸前 ⇒ 本条红。

    没有这一条，"被拒零盘写"只靠 a/b 的行为读数；而 a/b 可以被"干脆永远不落稿"
    糊弄过去 —— 这一条与 c 一起把两头钉住：既不许闸前落，也不许不落。
    """
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow" / "agent_b" \
        / "register_statement.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    impl = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "_register_statement_impl"),
                None)
    assert impl is not None, "register_statement.py 里找不到 _register_statement_impl"

    lines: dict[str, list[int]] = {"_land_b_manuscript": [],
                                   "_self_authored_gate": [],
                                   "_unsigned_proof_gate": []}

    class _Calls(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            if node is impl:
                self.generic_visit(node)
            # 嵌套函数不进来：判的是登记入口这一层

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            func = node.func
            if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                    and func.value.id == "self" and func.attr in lines):
                lines[func.attr].append(int(node.lineno))
            self.generic_visit(node)

    _Calls().visit(impl)
    for name, where in lines.items():
        assert where, f"_register_statement_impl 里找不到 {name} 调用（判据的前提没了）"
    last_gate = max(lines["_self_authored_gate"] + lines["_unsigned_proof_gate"])
    assert min(lines["_land_b_manuscript"]) > last_gate, (
        "落稿调用在闸之前（D1 回来了）：land="
        f"{lines['_land_b_manuscript']} vs gates={last_gate}")
