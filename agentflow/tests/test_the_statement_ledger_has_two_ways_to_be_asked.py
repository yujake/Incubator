# -*- coding: utf-8 -*-
"""命题台账的查口：两种口径各自独立、各自带读数，三态不折平。

## 这一份钉的是什么（业主 2026-11-08：「查必须明确有两种口径」）

| # | 判据 | 改前为什么没有 |
|---|---|---|
| a | 口径一（按编号）：只给编号就能查，读数里看得见 `mode` / `found` / `hits_total` / `scanned` / `why` | 改前没有公共入口：按号找行散在 31 处，各写各的默认值 |
| b | 口径二（按内容关键字）：只给关键词就能查，读数里看得见 `hits_total` / 每条 `hit_words` / `scanned` / `why` | 改前只有一处私有方法（`Secretary._statements_matching_keywords`），任何角色都调不到 |
| c | 两条口径互不调用：静态 AST 证明（`by_id` 的函数体里没有 `by_keywords`，反之亦然），外加运行时一条打桩另一条照绿 | 改前不存在"两条口径"，只有一条检索 |
| d | 三态不折平：台账读不到 ⇒ `checked=False` 且 `found=None`；查过没有 ⇒ `checked=True` + `found=False` / `hits_total=0` | 改前各读点把「读不到」折成 `{}` / `None` / `[]`，与「没有」同形 |
| e | 口径一不过滤：`abandoned` 行、概念行按号都查得到（编号是主键事实，不是"active 的那一行"） | 改前有的读点顺手过滤状态，有的不过滤 |
| f | 口径二用的是 `textutil.normalize` 那把尺（全半角 / 大小写 / 标点），不是 `casefold` 子串 —— 搜「Ｇ」能命中「G」 | 工具层 `table.search` 是 `casefold` 子串，全角字母搜不到 |
| g | 反真空（口径二被降级）：把 `by_keywords` 换成「永远 0 命中」⇒ 判同一性那一趟再也认不出在册的同一条（红） | — |
| h | 反真空（口径一被降级）：把 `by_id` 换成「永远没查到」⇒ 判了 same 之后并表那一笔 fail-closed（红） | — |
| i | 只读 + 零模型：模块里没有 `tx(` / `upsert` / `alloc_id` / `judge(` 这类写与判定调用 | — |

零模型调用：`judge` 全程打桩，不碰网络。
"""
from __future__ import annotations

import ast
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import seed_statement_row  # noqa: E402
from agentflow import migrate_concepts as MIG  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import statementabandon as SA  # noqa: E402
from agentflow import statementledger as SL  # noqa: E402
from agentflow.store import Store  # noqa: E402

MODULE = SRC / "agentflow" / "statementledger.py"
FULL = "设 G 是有限群且 |G| = p^a·m（p∤m），则 G 有 p 阶元。"
DECOY = "另一条命题：设 n<=3，则 Q(n) 成立。"


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _seeded(tmp_path: pathlib.Path) -> Store:
    st = _store(tmp_path)
    seed_statement_row(st, statement_full=FULL, label="P 阶元", kind="theorem")
    seed_statement_row(st, statement_full=DECOY, label="Q(n)", kind="conjecture")
    return st


def _sec(store: Store) -> SEC.Secretary:
    return SEC.Secretary("B", root=store.root, store=store)


def _unreadable():
    """一个读台账必炸的来源（证明「读不到」与「没有」在读数上分得开）。"""
    class _Broken:
        @staticmethod
        def rows(table: str):  # noqa: ARG004
            raise RuntimeError("台账文件坏了")
    return _Broken()


# ===================================================== a 口径一：只给编号
def test_a_by_id_answers_from_the_number_alone(tmp_path: pathlib.Path) -> None:
    """a：只给编号就能查；读数里有 mode / found / hits_total / scanned / why。"""
    st = _seeded(tmp_path)
    first = st.rows("statements")[0]
    got = SL.by_id(st, stmt_id=first["stmt_id"])
    assert got["checked"] is True, got
    assert got["mode"] == SL.MODE_ID, got
    assert got["found"] is True, got
    assert got["hits_total"] == 1, got
    assert got["scanned"] == 2, got
    assert got["row"]["stmt_id"] == first["stmt_id"], got
    assert got["matched_by"] == SL.MATCHED_BY_ID, got
    assert "主键" in got["why"], got
    # 查过、没有：不是「没查成」。
    miss = SL.by_id(st, stmt_id="999999")
    assert miss["checked"] is True and miss["found"] is False, miss
    assert miss["hits_total"] == 0 and miss["row"] == {}, miss
    assert "没有编号 999999" in miss["why"], miss


# ===================================================== b 口径二：只给关键字
def test_b_by_keywords_answers_from_the_words_alone(tmp_path: pathlib.Path) -> None:
    """b：只给关键词就能查；每条命中带 `hit_words`（为什么这条进来）。"""
    st = _seeded(tmp_path)
    got = SL.by_keywords(st, keywords=["p 阶元"])
    assert got["checked"] is True, got
    assert got["mode"] == SL.MODE_KEYWORDS, got
    assert got["hits_total"] == 1, got
    assert got["scanned"] == 2, got
    assert got["checked_rows"] == 2, got
    hit = got["hits"][0]
    assert hit["hit_words"] == ["p 阶元"], hit
    assert "p 阶元" in hit["statement_full"], hit
    assert got["keywords"] == ["p 阶元"], got
    assert "命中 1 条" in got["why"], got
    # 0 命中：查过、这批词没命中 —— 不许读成「不在册」。
    zero = SL.by_keywords(st, keywords=["根本不存在的一个词"])
    assert zero["checked"] is True and zero["hits_total"] == 0, zero
    assert "命中 0 条" in zero["why"], zero
    assert "不是「台账里没有」" in zero["why"], zero
    # 多词任一命中 + 排序：命中词多的排前面。
    two = SL.by_keywords(st, keywords=["p 阶元", "有限群"])
    assert two["hits_total"] == 1 and len(two["hits"][0]["hit_words"]) == 2, two


# ===================================================== c 两条口径互不依赖
def _function_bodies() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_c_the_two_modes_do_not_call_each_other(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """c：静态 AST 证明两条口径互不调用；运行时一条打桩另一条照绿。"""
    bodies = _function_bodies()
    assert set(bodies) >= {"by_id", "by_keywords"}, sorted(bodies)

    def _names(fn: ast.FunctionDef) -> set[str]:
        got: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Name):
                got.add(node.id)
            elif isinstance(node, ast.Attribute):
                got.add(node.attr)
        return got

    assert "by_keywords" not in _names(bodies["by_id"]), (
        "口径一调了口径二 —— 编号查不该依赖关键词检索")
    assert "by_id" not in _names(bodies["by_keywords"]), (
        "口径二调了口径一 —— 关键词检索不该依赖编号查")
    # 静态之外再加一层运行时：一条炸掉，另一条必须照绿。
    st = _seeded(tmp_path)
    monkeypatch.setattr(SL, "by_keywords", _boom)
    assert SL.by_id(st, stmt_id=st.rows("statements")[0]["stmt_id"])["found"] is True
    monkeypatch.undo()
    monkeypatch.setattr(SL, "by_id", _boom)
    assert SL.by_keywords(st, keywords=["p 阶元"])["hits_total"] == 1


def _boom(*_a, **_k):
    raise AssertionError("这一条口径不该被另一条调用")


# ===================================================== d 三态不折平
def test_d_unreadable_is_not_the_same_as_absent(tmp_path: pathlib.Path) -> None:
    """d：读不到 ⇒ checked=False + found=None；查过没有 ⇒ checked=True + found=False。"""
    broken = SL.by_id(_unreadable(), stmt_id="000001")
    assert broken["checked"] is False, broken
    assert broken["found"] is None, broken
    assert broken["hits_total"] == 0, broken
    assert "没查成" in broken["reason"], broken
    assert "不是「台账里没有这一行」" in broken["reason"], broken

    kw = SL.by_keywords(_unreadable(), keywords=["随便"])
    assert kw["checked"] is False and kw["hits_total"] == 0, kw
    assert "没查成" in kw["reason"], kw

    # 没给东西 / 没给号：也是「没查成」，不是「0 行」。
    assert SL.by_id(None, stmt_id="000001")["checked"] is False
    assert SL.by_id(None, stmt_id="  ")["found"] is None
    assert SL.by_keywords(None, keywords=[])["checked"] is False
    # 空表：查成了、0 行（不是「读不到」）。
    empty = _store(tmp_path / "empty")
    got = SL.by_keywords(empty, keywords=["x"])
    assert got["checked"] is True and got["scanned"] == 0, got
    assert got["hits_total"] == 0, got


# ===================================================== e 口径一不过滤
def test_e_by_id_finds_rows_whatever_their_status_or_kind(tmp_path: pathlib.Path) -> None:
    """e：编号是主键事实 —— 放弃的行、概念行照样按号查得到。"""
    st = _store(tmp_path)
    gone = seed_statement_row(
        st, statement_full="已放弃的一条。", status="abandoned",
        quote_reason=SA.abandon_marker(
            at="2026-11-09T00:00:00+08:00",
            reason=SA.structured_reason(kind="math_error", basis="夹具：第 2 步错了",
                                        defect_ref="stmt:000009")))
    concept = seed_statement_row(st, statement_full="", label="新概念",
                                 kind="concept", status="pending_definition",
                                 quote_reason=MIG.PENDING_SEARCH)
    for row in (gone, concept):
        got = SL.by_id(st, stmt_id=row["stmt_id"])
        assert got["found"] is True, (row, got)
        assert got["row"]["status"] == row["status"], got
    # 而池（唯一一份过滤）会把它们排除 —— 两件事分得开。
    pool = SL.pool(st.rows("statements"), kinds=("concept", "conjecture"))
    assert pool == [], pool


# ===================================================== f 口径二是 normalize 那把尺
def test_f_keyword_matching_is_the_normalize_ruler_not_casefold(tmp_path: pathlib.Path) -> None:
    """f：全角「Ｇ」与半角「G」是同一个词（normalize），而 casefold 认不出。"""
    assert "Ｇ".casefold() != "G", "前提变了：casefold 现在能归一全角？"
    st = _seed_fullwidth(tmp_path)
    got = SL.by_keywords(st, keywords=["Ｇ"])
    assert got["hits_total"] == 1, (got, "口径二没有走 textutil.normalize")
    assert got["hits"][0]["hit_words"] == ["Ｇ"], got


def _seed_fullwidth(tmp_path: pathlib.Path) -> Store:
    st = _store(tmp_path)
    seed_statement_row(st, statement_full="设 Ｇ 是有限群，则 Ｇ 有单位元。",
                       label="单位元", kind="theorem")
    return st


# ===================================================== g 反真空：口径二被降级
def _judge_same(*, same_as: str):
    def _fake(self, kind, context, *, task_id="", note=""):
        ids = [str(c.get("stmt_id") or "") for c in (context.get("candidates") or [])]
        hit = same_as if same_as in ids else ""
        return {"checked": True, "decision": "same" if hit else "different",
                "same_as": hit, "canonical_name": "P 阶元", "route": "",
                "condition": "", "conclusion": "", "basis": ["夹具"],
                "reason": "夹具", "cost": {}, "elapsed_sec": 0.0}
    return _fake


def test_g_degrading_the_keyword_mode_breaks_identity(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """g：把口径二降级成「永远 0 命中」⇒ 判同一性再也认不出在册的那一条（红）。"""
    st = _seeded(tmp_path)
    target = st.rows("statements")[0]["stmt_id"]
    sec = _sec(st)
    monkeypatch.setattr(SEC.Secretary, "judge", _judge_same(same_as=target))
    monkeypatch.setattr(SEC.Secretary, "pick_statement_keywords",
                        lambda self, **kw: {"checked": True, "keywords": ["p 阶元"],
                                            "why": "夹具"})
    ok = sec.adjudicate_proposition({"statement_full": FULL, "label": "P 阶元",
                                     "kind": "theorem"}, use_cache=False)
    assert ok["checked"] is True and ok["verdict"] == "same", ok
    assert ok["same_as"] == target and ok["hits_total"] == 1, ok

    monkeypatch.setattr(SL, "by_keywords", lambda *a, **k: {
        "checked": True, "mode": SL.MODE_KEYWORDS, "keywords": ["p 阶元"],
        "hits": [], "hits_total": 0, "scanned": 2, "checked_rows": 2,
        "matched_by": SL.MATCHED_BY_KEYWORDS, "why": "降级：永远 0 命中", "reason": ""})
    bad = sec.adjudicate_proposition({"statement_full": FULL, "label": "P 阶元",
                                      "kind": "theorem"}, use_cache=False)
    assert bad["verdict"] != "same", ("口径二被降级了，判同一性却还认得出来 ⇒ "
                                      "它没走查口", bad)
    assert bad["hits_total"] == 0, bad


# ===================================================== h 反真空：口径一被降级
def test_h_degrading_the_id_mode_breaks_the_merge(tmp_path: pathlib.Path,
                                                  monkeypatch) -> None:
    """h：把口径一降级成「永远没查到」⇒ 判了 same 之后并表那一笔 fail-closed。

    「判了 same ⇒ 并进点名的那一条」这一支第一件事就是按号把那一行读回来
    （`Secretary._proposition_owner`）。口径一被降级成永远查不到，它必须 fail-closed
    （读数 `adjudication.fail_closed=True`、不并、也不新建），而不是照旧并进去。
    """
    st = _seeded(tmp_path)
    target = st.rows("statements")[0]["stmt_id"]
    sec = _sec(st)
    adj = {"checked": True, "verdict": "same", "same_as": target,
           "attempted": True, "basis": "夹具", "seam_source": "fixture"}

    with st.tx("statements", actor="夹具") as tx:
        out: dict = {}
        hit = sec._proposition_owner(tx, FULL, kind="theorem", adj=dict(adj), out=out)
    assert hit is not None and hit["stmt_id"] == target, (hit, out)
    assert not out["adjudication"].get("fail_closed"), out

    monkeypatch.setattr(SL, "by_id", lambda *a, **k: {
        "checked": True, "mode": SL.MODE_ID, "stmt_id": str(k.get("stmt_id") or ""),
        "found": False, "hits_total": 0, "row": {}, "scanned": 2,
        "source": "rows", "matched_by": SL.MATCHED_BY_ID, "why": "降级", "reason": ""})
    with st.tx("statements", actor="夹具") as tx:
        out2: dict = {}
        bad = sec._proposition_owner(tx, FULL, kind="theorem", adj=dict(adj), out=out2)
    assert bad is None, ("口径一被降级了，并表却还找得到那一行 ⇒ 它没走查口", bad)
    assert out2["adjudication"].get("fail_closed") is True, out2
    assert "读不到那一条" in str(out2.get("proposition_reason") or ""), out2


# ===================================================== i 只读 + 零模型
def test_i_the_box_is_read_only_and_model_free() -> None:
    """i：模块里没有写盘 / 发模型 / 开事务的调用（结构判据，不是自觉）。"""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    banned = {"tx", "upsert", "alloc_id", "judge", "write_sign", "mark_dirty", "commit"}
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    bad = sorted(banned & used)
    assert not bad, f"查口里出现了写盘 / 判定调用：{bad}"
    imports = {node.module for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) and node.module}
    assert all(not str(m).endswith("secretary") for m in imports), (
        f"查口不许 import 秘书（那是第 4 步搬不动的根因）：{imports}")


# ===================================================== j 收口登记表（S1：按编号）
#: 改前各自手写「读一遍全表，再 `next(...)` 按号找」的那些函数。现在它们必须调
#: `statementledger.by_id`（口径一）—— 恢复成自己扫全表 ⇒ 这一条当场红。
MIGRATED_BY_ID: tuple[tuple[str, str], ...] = (
    ("agentflow/secretary.py", "record_manuscript_dependency_face"),
    ("agentflow/secretary.py", "amend_statement_meta"),
    ("agentflow/secretary.py", "land_statement"),
    ("agentflow/secretary.py", "_record_statement_tx"),
    ("agentflow/secretary.py", "record_proof_deps"),
    ("agentflow/secretary.py", "_proposition_owner"),
    ("agentflow/secretary.py", "proof_text_manuscript_sign_gate"),
    ("agentflow/agent_b/register_statement.py", "_update_numeric_evidence"),
    ("agentflow/agent_b/register_statement.py", "_evidence_kind_on_disk"),
    ("agentflow/agent_b/register_statement.py", "_register_statement_impl"),
    ("agentflow/agent_b/register_statement.py", "_register_pointer_manuscript"),
    ("agentflow/agent_b/register_statement.py", "_apply_declared_manuscript_kind"),
    ("agentflow/agent_b/register_statement.py", "_resolve_same_statement"),
    ("agentflow/vsigns.py", "sign_filing_reading"),
    ("agentflow/vsigns.py", "_land_ledger_bit"),
    ("agentflow/vreceipts.py", "registration_gap"),
    ("agentflow/vreceipts.py", "_author_of"),
    ("agentflow/vreceipts.py", "_detail_from_ledger"),
    ("agentflow/verifications.py", "sign_statement"),
    ("agentflow/verifications.py", "_apply_grade_backfill"),
    ("agentflow/statementabandon.py", "apply_abandonment"),
    ("agentflow/conceptrows.py", "sync_from_legacy"),
    ("agentflow/agent_f/core.py", "_proof_tier"),
    ("agentflow/agent_f/core.py", "_hand_proof"),
    ("agentflow/agent_f/core.py", "_statement_row"),
    ("agentflow/agent_d/write_report.py", "_deliver_carried_to_b"),
    ("agentflow/agent_l/formalize.py", "_pick_statement"),
    ("agentflow/agent_l/record.py", "_statement_row"),
)


def _module_tree(rel: str) -> ast.Module:
    return ast.parse((SRC / rel).read_text(encoding="utf-8"))


def _function_node(rel: str, name: str) -> ast.AST:
    for node in ast.walk(_module_tree(rel)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{rel} 里没有函数 {name}（登记表失去对象 = 没查成，不是通过）")


def _calls_attr(fn: ast.AST, attr: str) -> bool:
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == attr for node in ast.walk(fn))


def _hand_rolled_id_lookup(fn: ast.AST) -> bool:
    """函数体里还有没有「`next((r for r in rows if r.get("stmt_id") == sid), …)`」那种手写。"""
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "next" and node.args):
            continue
        gen = node.args[0]
        if not isinstance(gen, ast.GeneratorExp):
            continue
        for inner in ast.walk(gen):
            if (isinstance(inner, ast.Compare)
                    and any(isinstance(op, ast.Eq) for op in inner.ops)
                    and "stmt_id" in ast.unparse(inner)):
                return True
    return False


def test_j_every_by_id_site_goes_through_the_box() -> None:
    """j：S1 的 26 个调用点都问查口；谁恢复自己扫全表，这一条当场红。

    这一条是「同一件事只留一处实现」的机器读数：登记表里每个函数都必须出现
    `statementledger.by_id(...)` 的调用，且不许再出现手写的按号 `next(...)`。
    """
    assert len(MIGRATED_BY_ID) >= 20, "登记表被悄悄缩短了（收口点少了 = 判据面变小）"
    for rel, name in MIGRATED_BY_ID:
        fn = _function_node(rel, name)
        assert _calls_attr(fn, "by_id"), (
            f"{rel}::{name} 没有走 `statementledger.by_id` —— 按号查的实现又长出了第二处")
        assert not _hand_rolled_id_lookup(fn), (
            f"{rel}::{name} 里还有手写的按号 `next(...)` —— 自己扫全表又回来了")
    # 反真空：检测器自己要认得出改前那种写法（否则上面的"没有"是空的）。
    sample = ast.parse(
        'def f(rows, sid):\n'
        '    return next((r for r in rows if str(r.get("stmt_id") or "") == sid), None)\n')
    assert _hand_rolled_id_lookup(sample.body[0]), "反真空：检测器认不出改前那种写法"
    # 唯一实现：`by_id` 只定义在查口一处。
    defs = [path.name for path in (SRC / "agentflow").rglob("*.py")
            if "def by_id(" in path.read_text(encoding="utf-8")]
    assert defs == ["statementledger.py"], f"按号查的实现不止一处：{defs}"


# ===================================================== k 收口登记表（S2：全表→索引）
#: 改前各自写 `{号: 行}` 推导式（或号集合 / 号元组）的那些函数。现在它们必须调
#: `statementledger.index_by_id` —— 恢复成自己建索引 ⇒ 这一条当场红。
MIGRATED_INDEX: tuple[tuple[str, str], ...] = (
    ("agentflow/statementabandon.py", "_statement_rows"),
    ("agentflow/closing.py", "_statement_rows"),
    ("agentflow/verify.py", "verify_all"),
    ("agentflow/verifications.py", "_apply_grade_backfill"),
    ("agentflow/vreceipts.py", "reconcile_resubmits"),
    ("agentflow/agent_b/register_statement.py", "_register_statement_impl"),
    ("agentflow/agent_b/register_statement.py", "_context_theorem_gaps"),
    ("agentflow/vsigns.py", "_registered_ids"),
    ("agentflow/conceptrows.py", "mirror_gaps"),
    # 这四处拿到的是一批已经读出来的 statements 行（不自己读表），索引的构造同样是
    # 同一件事 —— 改前各写一遍 `{号: 行}`（`paperledger` 与 `_DepGraph` 连 keys 都一样）。
    ("agentflow/depsection.py", "uncitable_statement_finding"),
    ("agentflow/depsection.py", "gate_rows"),
    ("agentflow/depsection.py", "quote_mismatch_finding"),
    ("agentflow/depsection.py", "wash_dependency_section"),
    ("agentflow/paperledger.py", "check_paper_ledger"),
    ("agentflow/agent_c/proof_chain.py", "__init__"),
)


def _index_comprehension(fn: ast.AST) -> bool:
    """函数体里还有没有 `{str(r.get("stmt_id") …): …}` / `{… for r in …}` 那种手写索引。"""
    for node in ast.walk(fn):
        if isinstance(node, ast.DictComp):
            if "stmt_id" in ast.unparse(node.key):
                return True
        if isinstance(node, (ast.SetComp, ast.GeneratorExp)):
            text = ast.unparse(node).replace('"', "").replace("'", "")
            if "stmt_id" in text and "index_by_id" not in text:
                return True
    return False


def test_k_every_index_site_goes_through_the_box() -> None:
    """k：S2 的 9 个调用点都问查口；谁恢复自己建索引，这一条当场红。"""
    assert len(MIGRATED_INDEX) >= 8, "登记表被悄悄缩短了"
    for rel, name in MIGRATED_INDEX:
        fn = _function_node(rel, name)
        assert _calls_attr(fn, "index_by_id"), (
            f"{rel}::{name} 没有走 `statementledger.index_by_id` —— 全表→索引又长出了第二处")
    # 反真空：检测器认得出改前那种写法。
    sample = ast.parse('def f(rows):\n'
                       '    return {str(r.get("stmt_id") or ""): dict(r) for r in rows}\n')
    assert _index_comprehension(sample.body[0]), "反真空：检测器认不出改前那种写法"
    defs = [path.name for path in (SRC / "agentflow").rglob("*.py")
            if "def index_by_id(" in path.read_text(encoding="utf-8")]
    assert defs == ["statementledger.py"], f"全表→索引的实现不止一处：{defs}"


# ===================================================== l 收口登记表（S5：正文规范化全等）
#: 改前各自写 `normalize(statement_full) == key` 的那些函数。现在它们必须调
#: `statementledger.duplicate_hits` —— 恢复成自己比一遍 ⇒ 这一条当场红。
#:
#: 注意：`agent_l/formalize.py` 的 `claim_match` 与 B 的 `_v_signature_for` 不在这张表里
#: —— 它们比的不是 `textutil.normalize(statement_full)`：前者用 `_flat`
#: （只压空白，比 normalize 更严），后者用 `statementbody.body_of`（会回退到
#: `statement_text`）。两条都是另一件事，折进来会悄悄放宽判据。
MIGRATED_TEXT: tuple[tuple[str, str], ...] = (
    ("agentflow/agent_b/register_statement.py", "_existing_statement_for"),
    ("agentflow/agent_b/register_statement.py", "_resolve_same_statement"),
    ("agentflow/secretary.py", "_record_statement_tx"),
    ("agentflow/secretary.py", "proof_text_manuscript_sign_gate"),
)


def _hand_rolled_text_lookup(fn: ast.AST) -> bool:
    """函数体里还有没有 `next((r for r in rows if normalize(r["statement_full"]) == key))`。"""
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "next" and node.args):
            continue
        gen = node.args[0]
        if not isinstance(gen, ast.GeneratorExp):
            continue
        for inner in ast.walk(gen):
            if not (isinstance(inner, ast.Compare)
                    and any(isinstance(op, ast.Eq) for op in inner.ops)):
                continue
            text = ast.unparse(inner)
            if "normalize" in text and "statement_full" in text:
                return True
    return False


def test_l_every_exact_text_site_goes_through_the_box() -> None:
    """l：S5 的 4 个调用点都问查口；谁恢复自己比正文，这一条当场红。"""
    assert len(MIGRATED_TEXT) >= 4, "登记表被悄悄缩短了"
    for rel, name in MIGRATED_TEXT:
        fn = _function_node(rel, name)
        assert _calls_attr(fn, "duplicate_hits"), (
            f"{rel}::{name} 没有走 `statementledger.duplicate_hits` —— "
            "正文规范化全等又长出了第二处")
        assert not _hand_rolled_text_lookup(fn), (
            f"{rel}::{name} 里还有手写的正文比对 —— 自己扫全表又回来了")
    # 反真空：检测器认得出改前那种写法。
    sample = ast.parse(
        'def f(rows, key, T):\n'
        '    return next((r for r in rows\n'
        '                 if T.normalize(str(r.get("statement_full") or "")) == key), None)\n')
    assert _hand_rolled_text_lookup(sample.body[0]), "反真空：检测器认不出改前那种写法"
    defs = [path.name for path in (SRC / "agentflow").rglob("*.py")
            if "def duplicate_hits(" in path.read_text(encoding="utf-8")]
    assert defs == ["statementledger.py"], f"正文规范化全等的实现不止一处：{defs}"


# ===================================================== m 收口登记表（S3 池 / S4 关键词）
#: 改前各自内联「active ∧ 命题性 ∧ 有号有正文」那三条过滤的函数；现在必须调 `pool`。
MIGRATED_POOL: tuple[tuple[str, str], ...] = (
    ("agentflow/secretary.py", "_ledger_pool"),
    ("agentflow/secretary.py", "_same_proposition_candidate"),
    ("agentflow/secretary.py", "_fail_closed_reason"),
    ("agentflow/agent_b/register_statement.py", "_resolve_same_statement"),
)

#: 改前保管关键词检索的那个私有方法（已删）：现在只有 `by_keywords` 一处实现，
#: 唯一调用点是秘书的 `_identity_candidates`（挑词仍在本层、判定仍只经 `judge`）。
KEYWORD_CALLERS: tuple[tuple[str, str], ...] = (
    ("agentflow/secretary.py", "_identity_candidates"),
)


def test_m_pool_and_keywords_have_one_implementation_each() -> None:
    """m：池过滤 4 个调用点、关键词 1 个调用点都问查口；恢复内联 ⇒ 当场红。"""
    for rel, name in MIGRATED_POOL:
        assert _calls_attr(_function_node(rel, name), "pool"), (
            f"{rel}::{name} 没有走 `statementledger.pool` —— 可检索池又长出了第二处")
    for rel, name in KEYWORD_CALLERS:
        assert _calls_attr(_function_node(rel, name), "by_keywords"), (
            f"{rel}::{name} 没有走 `statementledger.by_keywords` —— 检索又长出了第二条路")
    for entry in ("pool", "by_keywords"):
        defs = [path.name for path in (SRC / "agentflow").rglob("*.py")
                if f"def {entry}(" in path.read_text(encoding="utf-8")]
        assert defs == ["statementledger.py"], f"{entry} 的实现不止一处：{defs}"
    # 旧私有方法（改前的唯一检索实现）不许复活：定义与调用都不许再有。
    old = [path.name for path in (SRC / "agentflow").rglob("*.py")
           if "def _statements_matching_keywords(" in path.read_text(encoding="utf-8")]
    assert old == [], f"改前那个私有检索方法又回来了：{old}"


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
