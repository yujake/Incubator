# -*- coding: utf-8 -*-
"""依赖面：F 写在自己的证明手稿里，B 读稿登记（业主 2026-10-24 最终形态）。

    业主原话（唯一权威）：
    「依赖面登记是否是F在其手稿中写好，D的研究手稿引用F的证明手稿给B入库时，B侧读到
      F手稿处的依赖面，按此入库的？（即和V签一个逻辑）」
    「改」
    「proof_review级及以上才可引用」

⇒ 作者只写内容，登记由收方读稿产生（与 V 读 F 的手稿再签字同构）。所以这一份判据钉的是
一条链，而不是一个写入口：

- F 那一侧：`F.step` 的 `proof` 档要落一份手稿（`reports/f-proof-<命题号>.md`），
  里面有那一节固定格式的 `## 依赖`（四列表），并且 `deps_preview` 能只读地算出
  "这份手稿交给 B 会落成什么/为什么落不成"；
- B 那一侧：`B.register_statement(proof_manuscript=...)` 读那一节，按表落
  `dependencies`（`used_by="stmt:<命题号>#pN"` ＋ `path_group` ＋ `source_stmt_id`），
  并在整笔写库之前把三条判定走完（缺列/坏号 ⇒ 拒；来源不在册 ⇒ 拒；档位不够或读不到 ⇒ 拒）；
- 手稿没有依赖段而证明正文里引用了 `stmt:` ⇒ 整笔受控拒绝 `dependency_section_missing`
  （依赖面就在手稿里、B 按它入库；引了却交不出那一节 = 这份手稿不合格）；一条引用都没有的
  自足证明不适用这一条（`deps_missing=not_applicable`，不拒收）。

## 一条链在 2026-10-26 之后多了一处落点（D8）

F 的出口改成了 `B.register_statement`（"把内容与稿交出去"，F 不再持有 `statements`
的写权限），于是 F 自己那一轮递交时 B 就已经读过那份稿、并按那一节落了行。这不是
"多落了不该落的边"：落边的仍然只有 B（收方读稿），作者一个字节都没写 `dependencies`。
但它确实让盘上多了一组 `used_by = stmt:<F 的命号>` 的行，所以下面两条判据按
`used_by` 分组，一组是判据、另一组点名。

## 七条判据（含两条负控的两半）与各自的"改前红"

改前（HEAD）：`AgentF` 没有 `proof_manuscript` / `preview_dependencies`（F 那侧一行手稿都
不写），`AgentB.register_statement` 也不收 `proof_manuscript`（`TypeError`）⇒ a–e 全部在
第一句就红；f 的三条负控是"打桩之后 a/c/b 必红"，改前打桩的目标（解析器 / 档位判据）根本
不存在，红在 import 上。

| 判据 | 它要证明的事 |
|---|---|
| a 正控 | F 的手稿里有依赖段 ⇒ B 读稿后 `dependencies` 落出对应行，`used_by`/`path_group`/`source_stmt_id` 对得上 |
| b 档位负控 | 引用 `cross_check` 级 ⇒ 整笔受控拒绝 `citation_below_proof_review`，零写入 |
| c1 缺段负控 | 有 `stmt:` 引用但没有依赖段 ⇒ 整笔受控拒绝 `dependency_section_missing`，零写入 |
| c2 边界 | 没有引用、也没有依赖段 ⇒ `not_applicable`（自足证明合法，不拒收） |
| d 格式负控 | 依赖段某行缺列 / 命题号形状不对 ⇒ 受控拒绝并点明第几行、缺哪一列 |
| e 多证明 | 三份证明各引不同命题 ⇒ 三行、`path_group` 1/2/3、`groups_of` 两层分开 |
| f 反真空 | 解析打桩成空 ⇒ a 必红；档位判据恒放行 ⇒ b 必红；缺段检测恒 present ⇒ c1 必红 |

全部 tmp 工作区、零模型调用（F 那一轮用一个假缝，`complete()` 回一份 `proof` 产物，
花费 0），不读写 `projects/`（真机工作区只读）。
"""
from __future__ import annotations

import json
import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式：这一份也要能在一棵临时源码树上单独跑
# （"改前红"就是把 `git archive HEAD` 的旧文件铺到临时树里、再跑这一份）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_c.proof_chain import _DepGraph
from agentflow.agent_f import AgentF
from agentflow.secretary import Secretary
from agentflow.store import Store

#: 被引用的三条在册定理（B 已收录、已站到 proof_review 级）。
THEOREM_A = S.format_id(0)
THEOREM_B = S.format_id(1)
THEOREM_C = S.format_id(2)
#: 一条只有交叉验证（cross_check）的命题：低于引用门槛。
WEAK = S.format_id(3)
#: 一条还只是猜想、没有任何 V 签名的行。
CONJECTURE = S.format_id(4)

_PROOF_TEXT = "命题 {sid} 的证明正文（判据夹具）。"
#: 依赖段的正例（政策里写死的那张表，逐列固定）。
EXAMPLE_TABLE = (
    "## 依赖\n\n"
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n"
    "| 由定理甲，G 有 p 阶元 | stmt:000000 | 第 1 步 | 1 |\n"
)


# ------------------------------------------------------------------ 夹具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _add_statement(store: Store, stmt_id: str, *, kind: str = "theorem",
                   label: str = "", level: str = "heuristic", status: str = "active") -> dict:
    """写一条在册命题（走 schema 校验 + 事务；"B 已收录"的替身）。"""
    row = S.Statement(
        stmt_id=stmt_id,
        origin="own_result",
        kind=kind,
        label=label or f"在册命题 {stmt_id}",
        statement_text=f"命题 {stmt_id} 的短版",
        statement_full=f"命题 {stmt_id} 的完整正文（含假设）。",
        proof_text=_PROOF_TEXT.format(sid=stmt_id),
        evidence_kind=level,
        status=status,
        quote_verified=None,
        quote_reason="判据夹具：自产命题，没有外部引文要比对",
        created_at=S.now_iso(),
        created_by="agent-B",
    )
    row.validate()
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row.to_dict())
    return row.to_dict()


def _sign(store: Store, stmt_id: str) -> dict:
    """V 对那一行的证明正文签「成立」（proof_review 的凭据是台账，不是自报）。"""
    return VR.record_verification(
        store.root, statement_id=stmt_id, proof_text=_PROOF_TEXT.format(sid=stmt_id),
        verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
        store=store, proof_no=1)


def _set_level(store: Store, stmt_id: str, level: str) -> None:
    row = next(dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == stmt_id)
    row["evidence_kind"] = level
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)


def _theorem(store: Store, stmt_id: str, *, label: str = "",
             level: str = "proof_review", kind: str = "theorem") -> dict:
    _add_statement(store, stmt_id, kind=kind, label=label)
    if level == "proof_review":
        _sign(store, stmt_id)
    _set_level(store, stmt_id, level)
    return next(dict(r) for r in store.rows("statements")
                if str(r.get("stmt_id")) == stmt_id)


def _library(store: Store) -> None:
    _theorem(store, THEOREM_A, label="定理甲")
    _theorem(store, THEOREM_B, label="定理乙")
    _theorem(store, THEOREM_C, label="定理丙，已形式化核过", level="proof")
    _add_statement(store, WEAK, label="只有交叉验证的命题", level="cross_check")


class FakeSeam:
    """假模型缝（`judge.judge_json` 认 `complete(prompt) -> str` 这一种形状）。"""

    def __init__(self, product: dict) -> None:
        self.product = product
        self.calls = 0

    def complete(self, prompt: str) -> str:  # noqa: ARG002 - 提示词只用来计数
        self.calls += 1
        return json.dumps(self.product, ensure_ascii=False)


def _proof_product(*, cites: list[str]) -> dict:
    steps = [{"n": 1, "text": "由在册定理直接得到第一步。", "cites": cites,
              "assumption": False}]
    steps.append({"n": 2, "text": "由 1 得结论。", "cites": cites[:1], "assumption": False})
    return {"product": "proof", "strategy": "套用已知定理",
            "why_strategy": "两条已收录定理直接给出结论，不需要新的构造", "steps": steps}


def _f_with_seam(store: Store, product: dict) -> tuple[AgentF, FakeSeam]:
    seam = FakeSeam(product)
    return AgentF(store, config={"workspace_root": store.root}, llm=seam), seam


def _run_proof_round(store: Store, cites: list[str]) -> dict:
    """让 F 真跑一轮 proof（假缝，零模型钱），返回 `step` 的读数。"""
    f, _seam = _f_with_seam(store, _proof_product(cites=cites))
    plan = f.create_plan("引理：由在册定理推出结论", "PK-MANUSCRIPT", subgoals=[
        {"sid": "s1", "text": "由在册定理推出目标引理", "owner": "F",
         "testable": "手稿的依赖段每条引用一行，B 读稿后落成依赖边"}])
    assert plan.get("created") is True, plan
    out = f.step(str(plan["plan_id"]))
    assert out.get("action") == "proof", out
    return out


def _b(store: Store) -> AgentB:
    """B 的真实现（零模型调用：这条路只碰秘书与 store）。"""
    return AgentB(store, extractor=None, extract_text=None, config={})


def _register(store: Store, manuscript: str, *, proof_text: str = "1. 由在册定理得结论。",
              statement_full: str = "定理：由两条在册定理推出目标结论。") -> dict:
    return _b(store).register_statement(
        statement_full=statement_full,
        statement_text="由两条在册定理推出目标结论",
        origin="own_result",
        kind="conjecture",
        doc_id=S.format_id(0),
        quote_reason="我方自产命题（判据夹具）：没有外部引文要比对",
        proof_text=proof_text,
        proof_manuscript=manuscript,
    )


def _deps(store: Store) -> list[dict]:
    return [dict(r) for r in store.rows("dependencies")]


# ------------------------------------------------------------------ a 正控

def test_f_manuscript_section_is_read_by_b_and_lands_a_dependency(store: Store) -> None:
    """a F 手稿里写好依赖段 ⇒ B 登记后 `dependencies` 落出对应行，三格对得上。

    改前红：`AgentF` 没有 `proof_manuscript`（F 那侧一行手稿都不写）⇒ 第一句
    `AttributeError`；`AgentB.register_statement` 也不收 `proof_manuscript` ⇒ `TypeError`。

    2026-10-26（D8，F 的出口改成 B 的登记正路）之后盘上会多一组行：F 自己那一轮
    递交时 B 就已经读过同一份稿。所以这一条按 `used_by` 分组 —— 本笔的两行是判据，
    多出来的那两行也点名（谁落的、来源是哪几条），而不是把"恰好 N 条"放宽成"至少 N 条"。
    """
    _library(store)
    out = _run_proof_round(store, [f"stmt:{THEOREM_A}", f"stmt:{THEOREM_B}"])
    # ---- F 那一侧：手稿真的落盘，依赖段读得动，只读预览说"会落 2 行"
    rel = str(out.get("manuscript_path") or "")
    assert rel, out
    path = store.root / rel
    assert path.is_file(), rel
    text = path.read_text(encoding="utf-8")
    # 惰性 import：改前这一条要红在"F 那侧一行手稿都不写"上，而不是红在收集期
    from agentflow import depsection as DS

    assert DS.SECTION_HEADING in text, text
    section = DS.parse_dependency_section(text)
    assert section["present"] is True and section["refused"] == "", section
    assert [r["stmt_id"] for r in section["rows"]] == [THEOREM_A, THEOREM_B], section
    preview = out.get("deps_preview") or {}
    assert preview.get("ok") is True, preview
    assert preview.get("would_write") == 2, preview
    assert (preview.get("deps_missing") or {}).get("state") == "present", preview

    # ---- B 那一侧：读同一份手稿，落出两行依赖
    got = _register(store, text)
    assert got.get("ok") is True, got
    stmt_id = str(got["stmt_id"])
    # 2026-10-26（D8）之后 F 的出口就是 `B.register_statement`：F 自己那一轮已经把同一份稿
    # 交给 B、并让 B 按那一节落了行（`used_by = stmt:<F 的命号>`）。所以先按 `used_by` 分组
    # —— 这条判据钉的是"这一笔（`stmt:<新命号>`）读出的那两行"，多出来的那两行点名，不静默略过。
    rows = [r for r in _deps(store) if str(r.get("used_by")) == f"stmt:{stmt_id}"]
    assert len(rows) == 2, _deps(store)
    author_side = [r for r in _deps(store) if str(r.get("used_by")) != f"stmt:{stmt_id}"]
    assert {str(r.get("used_by")) for r in author_side} == {f"stmt:{out['statement_id']}"}, \
        author_side
    assert len(author_side) == 2, author_side
    assert {str(r.get("source_stmt_id")) for r in author_side} == {THEOREM_A, THEOREM_B}, \
        author_side
    by_source = {r["source_stmt_id"]: r for r in rows}
    assert sorted(by_source) == sorted([THEOREM_A, THEOREM_B]), by_source
    for source, row in by_source.items():
        assert row["used_by"] == f"stmt:{stmt_id}", row
        assert row["path_group"] == 1, row
        assert row["status"] == "closed", row
        assert row["source_stmt_id"] == source, row
    assert (got.get("deps_missing") or {}).get("state") == "present", got
    assert ((got.get("deps_missing") or {}).get("manuscript") or {}).get("present") is True, got


def test_the_policy_example_is_the_format_the_parser_accepts() -> None:
    """政策里那个正例与解析器同形（格式漂了，这一条会红）—— 它钉的是"表头四列逐字"。"""
    from agentflow import depsection as DS

    section = DS.parse_dependency_section(EXAMPLE_TABLE)
    assert section["present"] is True and section["refused"] == "", section
    assert section["rows"] == [{"line": 5, "quote": "由定理甲，G 有 p 阶元",
                                "stmt_id": S.format_id(0), "step": "第 1 步",
                                "path_group": 1}], section["rows"]
    # 渲染器渲染出来的那一份，解析器必须读得回同一批行（渲染与解析不许各一套口径）
    rendered = AgentF.render_dependency_section(section["rows"])
    again = DS.parse_dependency_section(rendered)
    assert again["present"] is True and again["refused"] == "", again
    assert [(r["stmt_id"], r["path_group"], r["step"]) for r in again["rows"]] == [
        (S.format_id(0), 1, "第 1 步")], again["rows"]


# ------------------------------------------------------------------ b 档位负控

def test_a_cross_check_source_makes_the_whole_registration_refused(store: Store) -> None:
    """b 引用 `cross_check` 级 ⇒ 整笔受控拒绝 `citation_below_proof_review` 且零写入。

    改前红：同 a（没有 `proof_manuscript` 这个入口）。这一条在 ⑦ 里被"打桩成恒放行"
    反向钉住 —— 那时它会变红。
    """
    _library(store)
    manuscript = (
        "## 证明\n\n1. 由那条只有交叉验证的命题得结论。\n\n"
        "## 依赖\n\n"
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n"
        f"| 由数值交叉验证，这一步成立 | stmt:{WEAK} | 第 1 步 | 1 |\n")
    before_statements = len(store.rows("statements"))
    got = _register(store, manuscript)
    assert got.get("ok") is False, got
    assert got.get("kind") == "citation_below_proof_review", got
    assert WEAK in got.get("error", ""), got
    assert "cross_check" in got.get("error", ""), got
    assert "引用要求 proof_review 级及以上" in got.get("error", ""), got
    # 整笔不写：命题一行没多，依赖一行都没有
    assert _deps(store) == [], _deps(store)
    assert len(store.rows("statements")) == before_statements, store.rows("statements")


# ------------------------------------------------------------------ c 缺段负控

def test_a_manuscript_without_the_section_is_refused_whole(store: Store) -> None:
    """c（= g）手稿有 `stmt:` 引用但没有依赖段 ⇒ 整笔受控拒绝 `dependency_section_missing`、零写入。

    改前红：同 a。业主 2026-10-24 的裁定把这一档定成"拒收"而不是"只报一句缺"：
    依赖面就在手稿里、B 按它入库；正文引了却交不出那一节 = 这份手稿不合格，补上再来。
    只报 `deps_missing` 就照常入库，等于给"不写依赖段"留一条最省事的路 —— 而"没人被逼着
    把依赖写清楚"正是四趟真机 `dependencies` 全 0 的直接原因。
    """
    _library(store)
    before_statements = len(store.rows("statements"))
    manuscript = (f"## 证明\n\n1. 由 stmt:{THEOREM_A} 直接得到结论。\n"
                  f"2. 由 stmt:{THEOREM_B} 补上最后一步。\n")
    got = _register(store, manuscript, proof_text=f"1. 由 stmt:{THEOREM_A} 得结论。\n"
                                                 f"2. 由 stmt:{THEOREM_B} 收尾。")
    assert got.get("ok") is False, got
    assert got.get("kind") == "dependency_section_missing", got
    assert "没有 `## 依赖` 那一节" in got.get("error", ""), got
    assert f"stmt:{THEOREM_A}" in got.get("error", ""), got      # 点名引用了哪一条
    assert "补上那一节再交" in got.get("error", ""), got
    assert _deps(store) == [], _deps(store)                      # 零写入
    assert len(store.rows("statements")) == before_statements, store.rows("statements")


def test_a_self_contained_proof_is_not_refused_and_reads_not_applicable(store: Store) -> None:
    """c 的另一半：没有引用、也没有依赖段 ⇒ `not_applicable`（自足证明合法，不许拒）。

    改前红：同 a。这一条守住上面那条拒收的边界：它只惩罚"引了却不写"，
    不惩罚"这条证明本来就不靠别人"。
    """
    _library(store)
    manuscript = "## 证明\n\n1. 由定义直接得到，本证明不引用任何在册命题。\n"
    got = _register(store, manuscript, statement_full="定理：自足的证明（判据夹具）。",
                    proof_text="1. 由定义直接得到，不引用任何在册命题。\n")
    assert got.get("ok") is True, got
    reading = got.get("deps_missing") or {}
    assert reading.get("state") == "not_applicable", reading
    assert (reading.get("manuscript") or {}).get("present") is False, reading
    assert (reading.get("manuscript") or {}).get("refs_in_proof") == 0, reading
    assert _deps(store) == [], _deps(store)


def test_stub_the_missing_section_detection_and_the_refusal_turns_red(
        store: Store, monkeypatch) -> None:
    """f-c 反真空：把"缺段检测"打桩成恒 present ⇒ c 的拒收必红（照常入库）。

    打桩点就是那一条判据读的东西：`parse_dependency_section` 的 `present`。
    """
    _library(store)
    manuscript = f"## 证明\n\n1. 由 stmt:{THEOREM_A} 直接得到结论。\n"
    from agentflow import depsection as DS

    monkeypatch.setattr(DS, "parse_dependency_section",
                        lambda text: {"checked": True, "present": True, "heading_line": 1,
                                      "rows": [], "problems": [], "refused": "", "reason": ""})
    got = _register(store, manuscript, proof_text="1. 由定义直接得到。\n")
    assert got.get("ok") is True, got        # ← c 的"整笔拒绝"在这里是红的


# ------------------------------------------------------------------ d 格式负控

def test_a_broken_row_is_refused_with_the_line_and_the_missing_column(store: Store) -> None:
    """d 依赖段某行缺列 / 命题号形状不对 ⇒ 受控拒绝并点明第几行、缺哪一列。

    改前红：同 a。这一条是"散文读不出来"的正面修法所要求的配套：格式固定，
    所以格式坏了要能指出坏在第几行 —— 而不是静默少一条边。
    """
    _library(store)
    # 第一行少一列（只有三列）
    three_cells = (
        "## 依赖\n\n"
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n"
        f"| 由定理甲，G 有 p 阶元 | stmt:{THEOREM_A} | 第 1 步 |\n")
    got = _register(store, three_cells)
    # 惰性 import：改前这一条要红在"没有 `proof_manuscript` 这个入口"上
    from agentflow import depsection as DS

    assert got.get("ok") is False, got
    assert got.get("kind") == DS.REFUSED_SECTION, got
    assert "第 5 行" in got.get("error", ""), got
    assert _deps(store) == [], _deps(store)

    # 命题号形状不对（写成裸号 / 号不是六位）
    bad_id = (
        "## 依赖\n\n"
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n"
        f"| 由定理甲，G 有 p 阶元 | {THEOREM_A} | 第 1 步 | 1 |\n")
    got2 = _register(store, bad_id, statement_full="定理：另一条（判据夹具）。")
    assert got2.get("ok") is False, got2
    assert got2.get("kind") == DS.REFUSED_SECTION, got2
    assert "第 5 行" in got2.get("error", ""), got2
    assert "命题号" in got2.get("error", ""), got2
    assert _deps(store) == [], _deps(store)

    # 缺"路径号"这一列（表头只有三列）
    missing_col = (
        "## 依赖\n\n"
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |\n"
        "|---|---|---|\n"
        f"| 由定理甲，G 有 p 阶元 | stmt:{THEOREM_A} | 第 1 步 |\n")
    got3 = _register(store, missing_col, statement_full="定理：第三条（判据夹具）。")
    assert got3.get("ok") is False, got3
    assert got3.get("kind") == DS.REFUSED_SECTION, got3
    assert "缺列" in got3.get("error", ""), got3
    assert "路径号" in got3.get("error", ""), got3
    assert _deps(store) == [], _deps(store)


# ------------------------------------------------------------------ e 多证明

def test_three_paths_in_one_manuscript_make_three_dependency_rows(store: Store) -> None:
    """e 三份证明各引不同命题 ⇒ 三行、`path_group` 1/2/3、`groups_of` 两层分开。

    改前红：同 a；而且改前 `used_by` 的 `#pN` 尾巴一次都没被写出来过
    （依赖 0 行，`proof_no` 恒 1）。
    """
    _library(store)
    manuscript = (
        "## 证明\n\n这里的证明分三条可选的路径（路径号 1/2/3）。\n\n"
        "## 依赖\n\n"
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n"
        f"| 路线一：由定理甲 | stmt:{THEOREM_A} | 第 1 步 | 1 |\n"
        f"| 路线二：由定理乙 | stmt:{THEOREM_B} | 第 1 步 | 2 |\n"
        f"| 路线三：由定理丙（形式化过） | stmt:{THEOREM_C} | 第 1 步 | 3 |\n")
    got = _register(store, manuscript, statement_full="定理：三条路线都可推出结论。")
    assert got.get("ok") is True, got
    stmt_id = str(got["stmt_id"])
    rows = _deps(store)
    assert len(rows) == 3, rows
    assert sorted(int(r["path_group"]) for r in rows) == [1, 2, 3], rows
    assert sorted(r["source_stmt_id"] for r in rows) == sorted(
        [THEOREM_A, THEOREM_B, THEOREM_C]), rows
    assert sorted(r["used_by"] for r in rows) == [f"stmt:{stmt_id}", f"stmt:{stmt_id}#p2",
                                                  f"stmt:{stmt_id}#p3"], rows
    # 与既有的二维机制对齐：C 的依赖图先按证明号、再按 path_group 分组
    graph = _DepGraph(stmts=[dict(r) for r in store.rows("statements")],
                      deps=rows, exps=[], lits=[])
    groups = graph.groups_of(f"stmt:{stmt_id}")
    assert sorted(groups) == [1, 2, 3], groups
    for proof_no, by_group in groups.items():
        assert sorted(by_group) == [proof_no], by_group
        assert len(by_group[proof_no]) == 1, by_group
    assert graph.bad_used_by == [], graph.bad_used_by


# ------------------------------------------------------------------ f 反真空

def test_stub_the_parser_out_and_the_positive_control_turns_red(
        store: Store, monkeypatch) -> None:
    """⑦-a 反真空：把"解析依赖段"打桩成空 ⇒ a 必红（a 的绿是那条解析带来的）。

    盘上那一组行是 F 自己那一轮递交时落下的（D8），所以这一条比的是"这一笔有没有
    新增"—— 判据仍然是"零新增"，不是"盘上一行都没有"（后者已经被多落的那一组行
    变成了永远假）。
    """
    _library(store)
    out = _run_proof_round(store, [f"stmt:{THEOREM_A}"])
    manuscript = (store.root / str(out["manuscript_path"])).read_text(encoding="utf-8")
    before = _deps(store)          # F 那一轮落的那一行（与本笔无关）
    # 惰性 import：改前这一条先红在"F 那侧不写手稿"上
    from agentflow import depsection as DS

    monkeypatch.setattr(DS, "parse_dependency_section",
                        lambda text: {"checked": True, "present": False, "heading_line": 0,
                                      "rows": [], "problems": [], "refused": "", "reason": ""})
    got = _register(store, manuscript)
    # 解析被打桩成"没有这一段" ⇒ 这一笔一行依赖都落不出来（a 的"两行"在这里是红的）；
    # 而"有引用、没段"这一档现在是整笔拒收，理由码也在这里如实读出来。
    assert _deps(store) == before, _deps(store)
    assert got.get("ok") is False, got
    assert got.get("kind") == "dependency_section_missing", got


def test_stub_the_level_judge_open_and_the_negative_control_turns_red(
        store: Store, monkeypatch) -> None:
    """⑦-b 反真空：把档位判据打桩成恒放行 ⇒ b 必红（弱档会被照写）。"""
    _library(store)
    from agentflow import depsection as DS

    manuscript = (
        "## 依赖\n\n"
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n"
        f"| 由数值交叉验证，这一步成立 | stmt:{WEAK} | 第 1 步 | 1 |\n")
    monkeypatch.setattr(DS, "citation_level_allowed", lambda level: True)
    got = _register(store, manuscript)
    assert got.get("ok") is True, got                      # ← b 的"整笔拒绝"在这里是红的
    rows = _deps(store)
    assert len(rows) == 1 and rows[0]["source_stmt_id"] == WEAK, rows
