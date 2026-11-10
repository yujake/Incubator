# -*- coding: utf-8 -*-
"""判据：pending 台账行要认领第 3 位，先得有一份载体（业主 2026-11-04 裁定 · 乙-14）。

## 这一条堵的是什么

`vsigns._claim_pending_sign` 是"没有签文件、没有签块也能翻第 3 位"的唯一一条正路：
B 新建命题时按正文 sha 去 `verifications/pending/<sha>.jsonl` 认领 V 在命题还没在册时
审过的那一签。改前只要 pending 里有这一份正文就认 —— 纯内联旧行（`object_path=""`，
没有手稿、没有 e-proof 读数报告）也能把 `bits.reviewed` 翻上去。业主的口径：这一签的
合法性来自「V 对一份稿出过结论」，所以只认 `object_path` 是一份手稿
（`reports/{f,e,b}-proof-*.md`）或 E 的穷举读数报告
（`out/experiments/<实验号>/exhaustion.md`）的 pending 行；纯内联旧行不认。

## 判据（每条都两向）

| # | 造什么 | 期望 |
|---|---|---|
| a | `object_path=""` 的 pending 行 | 不认领：`proof_without_v_sign`、`bits.reviewed` 不翻、台账不回写号 |
| b | `object_path="reports/f-proof-<号>.md"` | 照旧认领：`bits.reviewed=True`、台账回写号 |
| c | `object_path="out/experiments/<实验号>/exhaustion.md"` | 照旧认领（E 那一档） |
| d | 反真空：把载体闸打桩成恒放行 | a 的裸行被认领（`bits.reviewed=True`）—— a 量的是这道闸 |
| e | 载体形状（纯读） | 手稿三前缀 / e-proof 报告 / 老盘计划名（`f-proof-plan-*`，2026-11-10 只读兼容）认；空串、`notes/…`、`foo.txt`、`b-proof` 的 plan 名、缺 `.md` 的名字不认 |
| f | `vsigns.py` 的 docstring / 注释（字面扫） | 不许再有「计划稿不是签的载体」这一类相反说法；反真空：把任一处改回旧说法 ⇒ 红 |
| g | `vsigns.issue` 的源码段（AST 定位） | 没有以 `MANUSCRIPT_NAME_PLAN` 为条件的死分支；常量保留（老读数还要能解释） |
| h | `reports/f-proof-000000`（缺 `.md`） | 签载体与 pending 载体两条口都是假（同源）；带上 `.md` 两条口都认 |
| i | `agent_v/core.py` 的注释 / docstring / 代码 | 旧口径的「计划稿」措辞一条都不留；以计划码为条件的死分支删掉（AST：零引用）；反真空：把旧原句喂回扫描器 ⇒ 红 |
| j | 两个同名口（`manuscriptfamily.is_sign_carrier` / `vsigns.is_sign_carrier`） | 9 个形状逐格一致（含缺 `.md`、plan 名、`b-proof-plan`、`notes/`、`e-num`、`exhaustion.md`）；反真空：摘掉「真文件名字」那一格 ⇒ 缺 `.md` 的形状红 |
| k | ② 的两条运行时 reason 串 + 一条选择式 | 旧串一条不留；`_claim_pending_sign` 不再引用计划码（常量保留）；反真空：把旧串喂回扫描器 ⇒ 红 |

2026-11-10（业主裁定）：「F 的稿自己维护一套号源，不依赖命题号和计划号」；
「计划不拥有稿件」⇒ 老盘计划名是只读兼容的签载体，与数字名同等。e 的缺扩展名那一格
与 f / g / h 是同一笔收口：旧口径的字面、`issue` 里的死分支、以及两条口对
`reports/f-proof-000000` 的相反读法，都不许再回来。

2026-11-10 晚（同一裁定的收尾 · 三处同族残留）：① `agent_v/core.py` 的旧口径字面与
那支同样死掉的计划名分支（3413–3416）；② `vsigns.py` 里两条运行时 reason 串
（`issue` 的兜底、`_claim_pending_sign` 的拒信）与 `_claim_pending_sign` 里以计划码为
条件的死选择式；③ `manuscriptfamily.is_sign_carrier` 只读名字表 ⇒ 缺 `.md` 的名字在
它那里是 True、在 `vsigns.is_sign_carrier` 是 False。i / j / k 是这三处的判据。
②③ 只收窄「两条口同源」，没有新增放行；① 只删死分支与改注释，签的行为一个字节没动。

零模型调用；夹具走生产的写口（`verifications.record_pending_sign` +
`AgentB.register_statement`），不手写台账。
"""
from __future__ import annotations

import ast
import io
import pathlib
import tokenize

from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.store import Store

#: 判据 f 的被扫文件（与 e / h 是同一族的签载体判据）。
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow" / "vsigns.py"

#: 判据 i 的被扫文件（`agent_v/core.py`：① 的旧口径字面与死分支都在这里）。
CORE_SRC = (pathlib.Path(__file__).resolve().parents[1]
            / "src" / "agentflow" / "agent_v" / "core.py")

#: 2026-11-05 旧口径的原句（只用来做反真空与字面扫的靶）。命中任意一条 ⇒ 红。
OLD_CLAIMS: tuple[str, ...] = (
    "计划稿不是签的载体",
    "计划稿是合法落稿名，但不是签的载体",
    "计划稿与纯内联旧行都不算",
    "计划稿…都不算",
    "落签也不许盖到它上面",
    "把计划稿排除掉",
)

#: ① 在 `agent_v/core.py` 里的旧口径原句（2026-11-10 晚改前逐字）。
#: 它们全部带「计划稿」这个旧措辞 ⇒ i 的字面扫以那个词为判据；这张表只做反真空。
CORE_OLD_CLAIMS: tuple[str, ...] = (
    "计划稿是合法的落稿名，但不是签的载体",
    "计划稿是合法落稿名，但不是签的载体",
    "旧读法只挡计划稿",
    "计划稿都没有签的落点",
    "计划稿那一档的 `why` 已经在上面写好",
    "计划稿（不是签的载体）也走这一档",
    '它点名"计划稿"',
)

#: ② 的两条旧运行时 reason 串（改前逐字；它们是返回读数，不是注释）。
OLD_REASONS: tuple[str, ...] = (
    "计划稿 / 别的文件都不是签的载体",
    "计划稿 / 纯内联正文的 pending 行不给第 3 位",
)

#: ③ 两条同名口要逐格一致的九个形状（含缺 `.md`、plan 名、`b-proof-plan`、`notes/`、
#: `e-num`、`exhaustion.md`）：`(路径, 是不是签的载体)`。
MOUTH_SHAPES: tuple[tuple[str, bool], ...] = (
    ("reports/f-proof-000000.md", True),
    ("reports/f-proof-000000", False),              # 缺 `.md`
    ("reports/f-proof-plan-0001.md", True),         # 老盘计划名（2026-11-10 只读兼容）
    ("reports/b-proof-plan-0001.md", False),        # plan 号形只属于 f-proof
    ("notes/b-proof-000003.md", False),             # 目录不对
    ("reports/e-num-000012.md", False),             # 绿色通道，不签
    ("out/experiments/000000/exhaustion.md", False),  # E 的穷举报告：pending 载体，不是签载体
    ("reports/f-proof-000000-p2.md", True),
    ("reports/e-proof-000012.md", True),
)

FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
OK = {"verdict": "成立", "why": "逐步核过，没有缺陷"}
PROOF_MANUSCRIPT = "reports/f-proof-000000.md"
E_REPORT = "out/experiments/000000/exhaustion.md"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _pending(st: Store, *, object_path: str = "") -> dict:
    return VR.record_pending_sign(
        st.root, proof_text=PROOF, verdict=dict(OK), object_path=object_path, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})


def _manuscript_text() -> str:
    """B 登记这一笔必须带的手稿（2026-11-04 甲之后在册也要稿）。"""
    from agentflow import depsection as DS

    return ("# F 的证明手稿（夹具）\n\n- 命题号：stmt:（待登记）\n- 计划：0000\n\n"
            "## 命题\n\n" + FULL + "\n\n## 证明\n\n" + PROOF + "\n\n"
            + DS.render_dependency_section([]) + "\n")


def _register(st: Store) -> dict:
    return AgentB(st, extractor=None, extract_text=None).register_statement(
        statement_full=FULL, statement_text=FULL, proof_text=PROOF,
        proof_manuscript=_manuscript_text(),
        kind="conjecture", label="探针命题", origin="own_result",
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="夹具：自产证明，没有第二份文本可比对",
        line_range={"label": "reports/probe.md"})


def _reviewed(st: Store) -> bool:
    rows = [dict(r) for r in st.rows("statements")]
    assert len(rows) == 1, rows
    return bool(dict(rows[0].get("bits") or {}).get("reviewed"))


def _pending_row(st: Store) -> dict:
    rows, problems = VR.pending_rows(st.root)
    assert problems == [], problems
    assert len(rows) == 1, rows
    return dict(rows[0])


# ====================================================================== a 无载体
def test_a_an_inline_pending_row_is_not_claimed(tmp_path: pathlib.Path) -> None:
    """`object_path=""` 的 pending 行 ⇒ 不认领；B 的准入闸整笔拒（没有签）。"""
    st = _ws(tmp_path)
    _pending(st)
    got = _register(st)
    assert got.get("ok") is False, got
    assert got.get("kind") == "proof_without_v_sign", got
    assert str(_pending_row(st).get("statement_id") or "") == "", _pending_row(st)
    assert st.rows("statements") == [], st.rows("statements")
    # 认签那一格自己的读数（B 的准入闸只把 `proof_gate` 带出来，载体那一句在这里读）
    _, v_sign = VS.bits_after_sign(
        {"proof": True}, root=st.root, proof_text=PROOF, statement_id="",
        proof_no=1, kind="conjecture", store=st)
    assert v_sign.get("applied") is not True, v_sign
    assert "载体" in str(v_sign.get("why") or ""), v_sign


# ====================================================================== b 手稿载体
def test_b_a_pending_row_with_a_manuscript_carrier_is_claimed(
        tmp_path: pathlib.Path) -> None:
    """`object_path` 是 `reports/f-proof-<号>.md` ⇒ 照旧认领、翻第 3 位。"""
    st = _ws(tmp_path)
    _pending(st, object_path=PROOF_MANUSCRIPT)
    got = _register(st)
    assert got.get("ok") is True, got
    assert _reviewed(st) is True
    assert str(_pending_row(st).get("statement_id") or "") != "", _pending_row(st)


# ====================================================================== c E 的报告载体
def test_c_an_e_proof_report_pending_row_is_claimed(tmp_path: pathlib.Path) -> None:
    """`object_path` 是 `out/experiments/<实验号>/exhaustion.md` ⇒ 照旧认领（E 那一档）。"""
    st = _ws(tmp_path)
    _pending(st, object_path=E_REPORT)
    got = _register(st)
    assert got.get("ok") is True, got
    assert _reviewed(st) is True


# ====================================================================== d 反真空
def test_d_without_the_carrier_gate_the_inline_row_is_claimed(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：把载体闸打桩成恒放行 ⇒ a 的裸行被认领（a 量的是这道闸）。"""
    monkeypatch.setattr(VS, "_pending_carrier_path", lambda _row: PROOF_MANUSCRIPT)
    st = _ws(tmp_path)
    _pending(st)
    got = _register(st)
    assert got.get("ok") is True, got
    assert _reviewed(st) is True, (
        "打桩之后仍然没认领 ⇒ a 的拒信不来自载体闸（这一条量错了东西）")


# ====================================================================== e 载体形状
def test_e_the_carrier_shapes() -> None:
    """纯读：正式手稿三前缀 / e-proof 报告 / 老盘计划名认；其余不认。

    ## 改前钉什么 / 改后钉什么

    改前（业主 2026-11-05 晚）：`reports/f-proof-plan-<数字>` 是"计划稿"——合法的落稿名，
    但不是签的载体（真机 `f-proof-plan-000011` 上那块 3/3 被读成假签），所以它在
    `no` 这一列。

    2026-11-10 业主裁定：「F 的稿自己维护一套号源，不依赖命题号和计划号」「计划不拥有
    稿件」⇒ `manuscriptfamily.sign_carrier` 撤掉了 `f-proof-plan-*` 那条排除：老盘上的
    计划名是只读兼容名，与数字名同等（可签）。于是它从 `no` 搬回 `yes` ——
    只搬 `f-proof` 这一族：同一个 `plan-` 号形在 `b-proof` 里仍是认不出的坏名
    （`reports/b-proof-plan-000016.md` 留在 `no`，这是反向断言：翻转不是"凡 plan 都放行"）。

    2026-11-10 同一笔的第二件（与上面那条裁定无关的边缘不一致）：`reports/f-proof-000000`
    （缺 `.md`）改前在两条口上读数不同 —— `is_sign_carrier` 说是、`_pending_carrier_path`
    说不是。现在两条口同源（`vsigns.sign_carrier_reading` 里那一格"是不是一份真文件的
    名字"），所以这一形状两处都不认。

    另外三条留在 `no` 当反向：目录不对（`notes/…`）、号形坏（`plan-abc`）、
    不是手稿（`foo.txt`）—— 载体判据没有因为这一撤而变成"什么都认"。
    """
    yes = [
        "reports/f-proof-000000.md", "reports/e-proof-000001.md",
        "reports/b-proof-000002.md", "reports/f-proof-000000-p2.md",
        # 老盘只读兼容名（2026-11-10 裁定；新稿不再写这种名字）。
        "reports/f-proof-plan-0001.md", "reports/f-proof-plan-0001-p2.md",
    ]
    e_report = "out/experiments/000000/exhaustion.md"
    no = ["", "notes/proof.md", "foo.txt", "reports/f-proof-000000",
          "reports/f-proof-.md", "out/experiments/000000/report.md",
          "out/experiments//exhaustion.md", "reports/x/f-proof-000000.md",
          # 反向：`plan-` 号形只属于 f-proof 的老盘兼容；b-proof 里它仍是坏名。
          "reports/b-proof-plan-000016.md",
          # 反向：目录 / 号形不对时，计划名也不认。
          "notes/f-proof-plan-0001.md", "reports/f-proof-plan-abc.md"]
    #: `no` 里同时也不是「手稿族的签载体」的那几条：2026-11-10 起两条口同源，
    #: 缺 `.md` 的 `reports/f-proof-000000` 也在这一列（改前它只在 pending 那一口被拒）。
    not_a_carrier = ["", "notes/proof.md", "foo.txt", "reports/f-proof-000000",
                     "reports/f-proof-.md",
                     "out/experiments/000000/report.md",
                     "out/experiments//exhaustion.md",
                     "reports/x/f-proof-000000.md",
                     "reports/b-proof-plan-000016.md",
                     "notes/f-proof-plan-0001.md",
                     "reports/f-proof-plan-abc.md"]
    for path in yes:
        assert VS._pending_carrier_path({"object_path": path}) == path, path
        assert VS.is_sign_carrier(path) is True, path
    # E 的穷举读数报告是认领的载体，不是「手稿签载体」：两条判据不许折成一条。
    assert VS._pending_carrier_path({"object_path": e_report}) == e_report
    assert VS.is_sign_carrier(e_report) is False, e_report
    for path in no:
        assert VS._pending_carrier_path({"object_path": path}) == "", path
    for path in not_a_carrier:
        assert VS.is_sign_carrier(path) is False, path
    # 同源正控：缺扩展名的名字在两条口上都为假（2026-11-10 边缘不一致收口）。
    assert VS.is_sign_carrier("reports/f-proof-000000") is False
    assert VS._pending_carrier_path({"object_path": "reports/f-proof-000000"}) == ""


# ====================================================================== f 旧字面
def _docstrings_and_comments(src: str) -> list[tuple[int, str]]:
    """源码里全部 docstring 与注释：`[(行号, 文本)]`（行号只用于报错定位）。"""
    chunks: list[tuple[int, str]] = []
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                chunks.append((int(getattr(node, "lineno", 1)), doc))
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            chunks.append((tok.start[0], tok.string))
    return chunks


def _old_claims(text: str) -> list[str]:
    """这段文本里命中的旧口径原句（空列表 = 干净）。"""
    return [one for one in OLD_CLAIMS if one in text]


def test_f_no_old_claim_survives_in_docstrings_or_comments() -> None:
    """f：`vsigns.py` 的 docstring / 注释里不许再出现旧口径。"""
    src = SRC.read_text(encoding="utf-8")
    hits = [f"{line}: {one}" for line, text in _docstrings_and_comments(src)
            for one in _old_claims(text)]
    assert hits == [], "旧口径的相反说法还在（2026-11-10 裁定已撤）：" + "; ".join(hits)


def test_f2_the_scanner_is_not_vacuous() -> None:
    """反真空：喂旧句子必须命中；喂新口径必须不命中。"""
    for one in OLD_CLAIMS:
        assert _old_claims(f"#: {one}。"), one
    assert _old_claims("#: 老盘计划名是合法载体（2026-11-10）。") == []


# ====================================================================== g 死分支
def _issue_source() -> str:
    """`issue` 这个函数的源码段（AST 定位；找不到就红，不许静默跳过）。"""
    src = SRC.read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == "issue":
            return ast.get_source_segment(src, node) or ""
    raise AssertionError("`vsigns.issue` 没找到 ⇒ g 判据真空")


def test_g_issue_has_no_branch_on_the_plan_code() -> None:
    """g：`issue` 里没有以 `MANUSCRIPT_NAME_PLAN` 为条件的分支；常量保留。"""
    seg = _issue_source()
    assert seg, "取不到 `issue` 的源码段"
    assert "MANUSCRIPT_NAME_PLAN" not in seg, (
        "`issue` 里还留着以计划名为条件的分支：`sign_carrier` 现在对 plan 返回 "
        "ok=True / code=\"\"，那个条件永远不成立（死分支）")
    assert "plan_is_not_a_sign_carrier" not in seg
    assert VS.MANUSCRIPT_NAME_PLAN == "plan_is_not_a_sign_carrier", (
        "历史码必须保留（老盘旧读数还要能解释）")


# ====================================================================== h 同源
def test_h_missing_extension_is_false_on_both_ports() -> None:
    """h：缺扩展名的名字在签载体与 pending 载体两条口上都为假（两者同源）。"""
    truncated = "reports/f-proof-000000"
    assert VS.is_sign_carrier(truncated) is False, VS.sign_carrier_reading(truncated)
    assert VS.sign_carrier_reading(truncated)["ok"] is False
    # 缺扩展名那一档的码：这个名字不是一份手稿文件名（不是「像手稿、号读不出」）。
    assert VS.sign_carrier_reading(truncated)["code"] == VS.MANUSCRIPT_NAME_BAD
    assert VS._pending_carrier_path({"object_path": truncated}) == ""
    # 正控：同一份稿带上 `.md` 两条口都认（翻转不是"一律为假"）。
    real = truncated + ".md"
    assert VS.is_sign_carrier(real) is True
    assert VS._pending_carrier_path({"object_path": real}) == real


def test_h2_the_same_rule_reads_both_ports_for_every_shape() -> None:
    """h 的同源读数：除 E 的穷举报告外，"是 pending 载体" ⇔ "是签的载体"。"""
    shapes = (
        "reports/f-proof-000000", "reports/f-proof-000000.md",
        "reports/f-proof-plan-0001", "reports/f-proof-plan-0001.md",
        "reports/f-proof-000000-p2.md", "reports/e-num-000012.md",
        "reports/f-proof-abc.md", "reports/b-proof-plan-0001.md",
        "notes/f-proof-000000.md",
    )
    for rel in shapes:
        carried = VS._pending_carrier_path({"object_path": rel})
        assert (carried == rel) is VS.is_sign_carrier(rel), (
            rel, carried, VS.sign_carrier_reading(rel))


# ====================================================================== 共用读数
def _plan_word_hits(text: str) -> list[int]:
    """这段文本里「计划稿」出现的行号（旧口径的措辞；空列表 = 干净）。"""
    return [i for i, line in enumerate(text.splitlines(), 1) if "计划稿" in line]


def _reason_hits(text: str) -> list[str]:
    """这段文本里命中的旧 reason 串（空列表 = 干净）。"""
    return [one for one in OLD_REASONS if one in text]


def _function_node(src: str, name: str) -> ast.AST:
    """`src` 里名为 `name` 的那个函数节点（找不到就红：判据不许静默跳过）。"""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"`{name}` 没找到 ⇒ 这一条判据真空")


def _code_refs_to(node: ast.AST, name: str) -> list[str]:
    """`node` 这段代码里引用 `name` 的 AST 位置（属性访问或裸名；注释 / 字符串不算）。"""
    hits: list[str] = []
    for one in ast.walk(node):
        if isinstance(one, ast.Attribute) and one.attr == name:
            hits.append(f"attr@{one.lineno}")
        elif isinstance(one, ast.Name) and one.id == name:
            hits.append(f"name@{one.lineno}")
    return hits


# ====================================================================== i ① core.py
def test_i_core_has_no_plan_mouth_and_no_dead_plan_branch() -> None:
    """i：`agent_v/core.py` 里旧口径的「计划稿」措辞与那支死分支都不许留。

    2026-11-10 业主裁定「计划不拥有稿件」之后，老盘 `f-proof-plan-*` 是只读兼容的
    名字，与数字名同等；把它叫「计划稿」并当成签的反例是 2026-11-05 旧口径的措辞。
    这一条钉两件：

    - 字面：注释 / docstring / 代码里「计划稿」一条都不许留 —— 改后说的是
      「老盘 `f-proof-plan-*`」与「真文件名字」；
    - 死分支：改前 3413–3416 以 `MANUSCRIPT_NAME_PLAN` 为条件，而 `sign_carrier_reading`
      对计划名读 `ok=True / code=""`、它的码集合里没有那个值 ⇒ 这一支永不成立。
      现在 AST 上零引用，连带那行 `from .. import vsigns as _VS2` 也一起删掉。
    """
    src = CORE_SRC.read_text(encoding="utf-8")
    hits = _plan_word_hits(src)
    assert hits == [], f"旧口径的「计划稿」措辞还在 agent_v/core.py 这些行：{hits}"
    refs = _code_refs_to(_function_node(src, "_finish_unregistered"),
                         "MANUSCRIPT_NAME_PLAN")
    assert refs == [], f"`_finish_unregistered` 还有代码引用计划码（死分支）：{refs!r}"
    assert "_VS2" not in src, "死分支带上来的 `from .. import vsigns as _VS2` 还在"


def test_i2_the_plan_word_scan_is_not_vacuous() -> None:
    """i 的反真空：把 2026-11-05 的七条原句逐条喂进扫描器 ⇒ 每条都命中。"""
    for one in CORE_OLD_CLAIMS:
        assert _plan_word_hits(f"# {one}。"), one
    assert _plan_word_hits(
        "# 载体 = `reports/(f|b|e)-proof-<号>.md` 的真文件名字；老盘 `f-proof-plan-*` "
        "与数字名同等。") == []


# ====================================================================== j ③ 两条口
def test_j_the_two_is_sign_carrier_mouths_agree_on_nine_shapes() -> None:
    """j：`manuscriptfamily.is_sign_carrier` 与 `vsigns.is_sign_carrier` 逐格一致。

    2026-11-10 晚之前前者只读名字表（`reports/f-proof-000000` 缺 `.md` ⇒ True），
    后者已同源到「真文件名字」（False）—— 两个同名函数对同一串说两句话。现在那一格
    在表里（`manuscriptfamily._is_file_name`），`vsigns` 只转发（自己不再写第二份
    `.md` 判定）：九个形状逐格相同，缺 `.md` 在两边都是 False。
    """
    from agentflow import manuscriptfamily as MF

    for rel, want in MOUTH_SHAPES:
        assert MF.is_sign_carrier(rel) is want, (rel, MF.sign_carrier(rel))
        assert VS.is_sign_carrier(rel) is want, (rel, VS.sign_carrier_reading(rel))
        assert MF.is_sign_carrier(rel) is VS.is_sign_carrier(rel), rel


def test_j2_the_file_name_gate_is_what_makes_them_agree() -> None:
    """j 的反真空：缺 `.md` 那一格改前在表里判 True 的根据只剩「真文件名」一格。

    读数（不碰工作树）：`reports/f-proof-000000` 在表里的身份仍是 `tier=family`、
    族 `f-proof`、目录 `reports` —— 旧读法（只读名字表）据这三格判 True；现在
    `_is_file_name` 说它不是真文件，`sign_carrier` 因此 `ok=False`。把那一格摘掉，
    j 的形状表里这一行立刻红（探针 `temp/probe_residue_20261110.py` 同形读数）。
    """
    from agentflow import manuscriptfamily as MF

    rel = "reports/f-proof-000000"
    reading = MF.classify_manuscript(rel)
    old_verdict = (reading["tier"] == MF.TIER_FAMILY
                   and reading["name_family"] in ("f-proof", "b-proof", "e-proof")
                   and reading["directory"] == MF.MANUSCRIPT_DIR)
    assert old_verdict is True, (
        "反真空的前提不成立：名字表这一档已经判它 False，j2 量不到 `.md` 那一格", reading)
    assert MF._is_file_name(rel) is False     # noqa: SLF001 —— 量的就是这一格
    assert MF.sign_carrier(rel)["ok"] is False
    assert MF.sign_carrier(rel)["code"] == MF.CODE_BAD
    assert VS.sign_carrier_reading(rel)["code"] == VS.MANUSCRIPT_NAME_BAD


# ====================================================================== k ② 两条 reason
def test_k_the_two_reason_strings_and_the_dead_selection_are_gone() -> None:
    """k：② 的两条运行时 reason 串换成现行口径；死选择式删掉（常量保留）。

    两条串是返回读数（不是注释），所以看整份源码的字面；选择式用 AST 看 ——
    `_claim_pending_sign` 里不许再有任何代码引用 `MANUSCRIPT_NAME_PLAN`。
    常量本身保留：老盘上的旧读数还要能解释（g 已经钉了 `issue` 那一处）。
    """
    src = SRC.read_text(encoding="utf-8")
    assert _reason_hits(src) == [], f"旧的 reason 串还在：{_reason_hits(src)!r}"
    refs = _code_refs_to(_function_node(src, "_claim_pending_sign"),
                         "MANUSCRIPT_NAME_PLAN")
    assert refs == [], f"`_claim_pending_sign` 还引用计划码（死选择式）：{refs!r}"
    assert VS.MANUSCRIPT_NAME_PLAN == "plan_is_not_a_sign_carrier", (
        "历史码必须保留（老盘旧读数还要能解释）")
    # 新口径：两条拒信都点名"真文件名字"，不再拿计划名当反例。
    assert src.count("真文件名字") >= 2, "两条拒信没有换成现行口径"


def test_k2_the_reason_scan_is_not_vacuous() -> None:
    """k 的反真空：两条旧 reason 串逐条喂进扫描器 ⇒ 每条都命中。"""
    for one in OLD_REASONS:
        assert _reason_hits(f'out["why"] = "{one}"'), one
    assert _reason_hits('out["why"] = "没有载体的 pending 行不给第 3 位"') == []
