"""FC-05（顺序与集合分离）、契约版本、以及 `tasks`/`usage_ledger`/`eval_results` 的校验。

这三块是"正式版"新增的地基，因此每个判据都配正反两向：
- FC-05：集合字段必须升序去重（集中检查）、序列字段必须保序（round-trip）、
  未声明的数组字段必须报错（这是 FC-05 最关键的一条：默认值会静默破坏顺序）。
- 契约版本：`agentflow.CONTRACT_VERSION` 与 `interactions.CONTRACT_VERSION` 必须是同一个值。
- 新三表：悬空引用、深度断链、花销两处不一致、同口径冲突值。
"""

from __future__ import annotations

import dataclasses
import re

import pytest
from conftest import TS, sync_counters
from agentflow import interactions as I
from agentflow import schema as S
from agentflow.store import Store
from agentflow.verify import verify_all


def _issues(store, *, level=None, code=None):
    d = verify_all(store).to_dict()
    out = list(d["errors"]) + list(d["warnings"])
    if level is not None:
        out = [i for i in out if i["level"] == level]
    if code is not None:
        out = [i for i in out if i["code"] == code]
    return out


# ============================================================ FC-05


def test_every_array_field_is_declared():
    """判据①：每一个数组字段都在 `ARRAY_FIELD_KINDS` 里声明了 set/seq。

    这条是 FC-05 的核心机械保证：未声明的数组会被默认当成集合，
    于是"顺序本身携带信息"的字段被 `sorted(set(...))` 静默破坏。
    """
    undeclared: list[str] = []
    for table, spec in S.TABLES.items():
        declared = S.array_kinds(table)
        for f in dataclasses.fields(spec["row"]):
            if str(f.type).startswith("list["):
                if f.name not in declared:
                    undeclared.append(f"{table}.{f.name}")
    assert undeclared == [], f"这些数组字段没有声明 set/seq：{undeclared}"


def test_undeclared_array_field_is_reported_by_verify(store, monkeypatch):
    """负控：把某个声明删掉 ⇒ `verify` 必须报 `undeclared_array_field`。

    没有这条负控，"所有字段都声明了"就只能靠人眼看 —— 而人眼看不出的漏声明
    正是 FC-05 要防的那个缺陷。
    """
    store.init()
    patched = {k: dict(v) for k, v in S.ARRAY_FIELD_KINDS.items()}
    patched["relations"].pop("supporting_lit_ids")
    monkeypatch.setattr(S, "ARRAY_FIELD_KINDS", patched)
    got = _issues(store, level="error", code="undeclared_array_field")
    assert len(got) == 1 and "supporting_lit_ids" in got[0]["message"]


def test_set_fields_are_checked_centrally(store):
    """集合字段的升序去重由 `validate_table` 集中检查（唯一权威点）。

    为什么不在每行的 `validate()` 里手写：那是"同一判据多处实现"，
    漏写一处就静默失效（新增 `supporting_lit_ids` 时就差点漏了）。

    探针字段随并表换了一格：`concepts.related_concepts` 不再是任何表里的列
    （概念的"相关"由 `relations` 表回答），这里改用 `statements.derived_from` ——
    它在 `ARRAY_FIELD_KINDS` 里同样声明为 `set`，判据（"未声明的数组必须报
    `undeclared_array_field`、声明为 set 的必须升序去重"）与强度都没变。
    """
    store.init()
    with store.tx("statements", actor="t") as tx:
        tx.upsert("statements", S.Statement(stmt_id="0000", origin="own_result", kind="theorem",
                                            statement_full="A",
                                            quote_reason="尚未逐字校验").to_dict())
    # 直接往快照里塞一条 derived_from 未排序的行
    doc = store.read("statements")
    doc["rows"][0]["derived_from"] = ["0002", "0001"]
    store._atomic_write(store.data / "statements.json", doc)
    errs = _issues(store, level="error", code="schema_invalid")
    assert errs and "derived_from" in errs[0]["message"]


def test_relation_chain_preserves_order_round_trip(store):
    """序列字段的 round-trip：写→读→逐元素相等且顺序不变。

    `relation_chain` 与 `related_relation_ids` 是一对：后者是集合（升序去重），
    前者是序列（保序）。顺序是推理路径本身，不是同一集合的另一种写法。
    """
    store.init()
    chain = ["0009", "0010", "0005"]  # 故意不是升序
    row = S.ResearchQuestion(
        question_id="0000", question="这条链成立吗？",
        related_concept_ids=["0000", "0001"],
        related_relation_ids=sorted(chain),  # 集合：必须是升序
        relation_chain=chain,  # 序列：必须保序
        status="open", created_at=TS, updated_at=TS,
    )
    row.validate()
    with store.tx("research_questions", actor="t") as tx:
        tx.upsert("research_questions", row.to_dict())
    sync_counters(store)
    back = store.rows("research_questions")[0]
    assert back["relation_chain"] == chain, "序列字段被排序了 —— FC-05 的缺陷复发了"
    assert back["related_relation_ids"] == sorted(chain)


def test_relation_chain_must_be_a_subset_of_related_relation_ids(store):
    """负控：链条里出现集合里没有的代号 ⇒ 拒（否则链与集合会各自漂移）。"""
    with pytest.raises(ValueError, match="relation_chain"):
        S.ResearchQuestion(
            question_id="0000", question="q",
            related_concept_ids=["0000", "0001"],
            related_relation_ids=["0001", "0002"],
            relation_chain=["0001", "0099"],
            status="open", created_at=TS, updated_at=TS,
        ).validate()


def test_seq_field_is_not_forced_sorted_by_the_central_check(store):
    """防误伤：`seq` 字段不受集中检查约束（它本来就允许乱序）。"""
    store.init()
    row = S.Document(
        doc_id="0000", kind="note", title="t",
        claims=[{"claim_id": "c2", "text": "后写的", "citations": ["lit:0000"], "evidence_kind": "proof"},
                {"claim_id": "c1", "text": "先写的", "citations": ["lit:0000"], "evidence_kind": "proof"}],
        created_at=TS,
    )
    row.validate()  # 不抛：claims 是 seq，顺序自由
    assert [c["claim_id"] for c in row.claims] == ["c2", "c1"]


# ============================================================ 契约版本


def test_contract_version_is_single_sourced():
    """`agentflow.CONTRACT_VERSION` 与 `interactions.CONTRACT_VERSION` 是同一个值。

    为什么要版本号：`interactions` 是冻结契约，而"A 与 B 各自按不同版本的契约
    理解同一个字段"这种分裂没有任何报错。有了版本号，装配期就能断言一致。
    """
    import agentflow

    assert agentflow.CONTRACT_VERSION == I.CONTRACT_VERSION
    assert isinstance(I.CONTRACT_VERSION, int) and I.CONTRACT_VERSION >= 1
    assert "CONTRACT_VERSION" in I.__all__


def test_the_two_versions_come_from_two_different_sources():
    """两个版本号必须来自两个不同的来源 —— 而不是"数值恰好不相等"。

    原来这条写的是
    `assert agentflow.CONTRACT_VERSION != agentflow.__schema_version__ or True`
    —— `or True` 让整条断言恒真（`G-33`：用例名说"必须分开"，而它在两者相等时
    照样绿）。不能只删 `or True`：实测今天两者都等于 1，删掉之后断言立刻红，
    而那并不是缺陷 —— docstring 自己写着"允许偶合，但不要求相等"，那句话是对的。

    真正要钉的是"来源单一"（这也是 `G-33` 的正解）：

    - `CONTRACT_VERSION` 的权威定义在 `interactions`，`__init__` 只能 import 它
      （`is` 判据：同一个对象，不是数值相等）；
    - `__schema_version__` 的权威定义在 `__init__`，且必须等于 `schema.SCHEMA_VERSION`。

    于是"契约变了"与"数据格式变了"才真的能各自表达 —— 这正是用例名想说的那件事。
    """
    import ast
    from pathlib import Path

    import agentflow
    from agentflow import interactions as I

    assert agentflow.__schema_version__ == S.SCHEMA_VERSION
    # 动态：同一个对象。`is` 单独不可判定（CPython 会缓存小整数：注入
    # `CONTRACT_VERSION = 1` 之后 `is` 仍然为真），所以它必须与下面的静态检查并列。
    assert agentflow.CONTRACT_VERSION is I.CONTRACT_VERSION

    # 静态：`__init__` 里不许出现对 `CONTRACT_VERSION` 的赋值（只许 import 进来）。
    # 这一半才是注入 `CONTRACT_VERSION = 1` 时会变红的判据。
    tree = ast.parse(Path(agentflow.__file__).read_text(encoding="utf-8"))
    assigned = {
        t.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for t in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
        if isinstance(t, ast.Name)
    }
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "CONTRACT_VERSION" not in assigned, (
        "`agentflow/__init__.py` 里出现了一份自己的 CONTRACT_VERSION ⇒ 两个来源，"
        "而『契约变了』与『数据格式变了』就再也分不开了"
    )
    assert "CONTRACT_VERSION" in imported, "CONTRACT_VERSION 必须从 interactions import 进来"
    assert "__schema_version__" in assigned, "__schema_version__ 的权威定义应当在 __init__ 里"


# ============================================================ tasks 表


def _task(store, **kw):
    base = dict(task_id="t-0001", role="C", action="paths", called_by="M", depth=1,
                input_key="paths:0000:0001", status="done", outcome="ok",
                detail="跑完", started_at=TS, ended_at=TS)
    base.update(kw)
    row = S.Task(**base)
    row.validate()
    with store.tx("tasks", "counters", actor="t") as tx:
        tx.upsert("tasks", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def test_clean_task_row_has_no_errors(store):
    store.init()
    _task(store)
    assert _issues(store, level="error") == []


def test_task_depth_must_be_parent_plus_one(store):
    """负控：深度断链 ⇒ error（深度是判循环与判越权的依据）。"""
    store.init()
    _task(store, task_id="t-0001", depth=1)
    _task(store, task_id="t-0002", parent_task_id="t-0001", depth=5)
    assert len(_issues(store, level="error", code="task_depth_discontinuous")) == 1


def test_dangling_parent_task_is_an_error(store):
    store.init()
    _task(store, task_id="t-0002", parent_task_id="t-9999", depth=2)
    assert len(_issues(store, level="error", code="dangling_parent_task")) == 1


def test_dangling_task_artifact_is_an_error(store):
    """`artifacts` 形如 `table:id`，指向不存在的行 ⇒ error。"""
    store.init()
    _task(store, artifacts=["experiments:0007"])
    assert len(_issues(store, level="error", code="dangling_task_artifact")) == 1


def test_running_task_is_reported_as_a_start_without_end(store):
    """离线校验时仍在 `running` 的行 = 没有 end 的 start ⇒ warning（交人看）。"""
    store.init()
    _task(store, status="running", outcome=None, detail="", ended_at=None)
    got = _issues(store, level="warning", code="task_still_running")
    assert len(got) == 1 and "没有 end 的 start" in got[0]["message"]


def test_task_without_input_key_is_reported(store):
    """`input_key` 为空 ⇒ 循环检测对它无效 ⇒ warning（不许静默）。"""
    store.init()
    _task(store, input_key="")
    assert len(_issues(store, level="warning", code="task_without_input_key")) == 1


# ============================================================ usage_ledger


def _usage(store, **kw):
    base = dict(usage_id="0000", scope="summon", role="C", tokens_in=10, tokens_out=5,
                tokens_total=15, usd=0.0, attempts=1, at=TS)
    base.update(kw)
    row = S.UsageEntry(**base)
    row.validate()
    with store.tx("usage_ledger", "counters", actor="t") as tx:
        tx.upsert("usage_ledger", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def test_usage_zero_value_needs_a_note(store):
    """零值也要记，但一条不带任何信息的零值行只会污染台账 ⇒ 必须写 note。"""
    with pytest.raises(ValueError, match="note"):
        S.UsageEntry(usage_id="0000", scope="summon", at=TS).validate()
    S.UsageEntry(usage_id="0000", scope="summon", at=TS, note="纯本地计算，无 token").validate()


def test_usage_total_must_cover_components(store):
    with pytest.raises(ValueError, match="tokens_total"):
        S.UsageEntry(usage_id="0000", scope="summon", at=TS,
                     tokens_in=10, tokens_out=5, tokens_total=3, note="x").validate()


def test_usage_task_total_mismatch_is_reported(store):
    """同一次召唤的花销在两处给出不同数字 ⇒ warning（预算判断会按哪一份？）。"""
    store.init()
    _task(store, tokens=99)
    _usage(store, task_id="t-0001", tokens_total=15)
    assert len(_issues(store, level="warning", code="usage_task_total_mismatch")) == 1


def test_dangling_usage_task_is_an_error(store):
    store.init()
    _usage(store, task_id="t-9999")
    assert len(_issues(store, level="error", code="dangling_usage_task")) == 1


# ============================================================ eval_results


def _eval(store, eid="0000", **kw):
    base = dict(eval_id=eid, claim_key="K", benchmark="miniF2F", benchmark_version="v2",
                split="test", k=1, value=0.348, decontamination="none-declared",
                date="2026-01-01", source="paper-x", samples=244, created_at=TS)
    base.update(kw)
    row = S.EvalResult(**base)
    row.validate()
    with store.tx("eval_results", "counters", actor="t") as tx:
        tx.upsert("eval_results", row.to_dict())
    sync_counters(store)
    return row.to_dict()


def test_eval_requires_every_scope_field():
    """FC-24 判据②：缺任一必填口径字段 ⇒ 拒。

    口径不是补充说明，口径就是那个数字的一部分 —— 同一个基准的同一个数字
    在不同口径下能差 13–30 个百分点。

    ## 这条判据在 2026-09-27 被加强（不是放宽）

    改前它断言消息里含「口径」二字。而实现给的是字段级消息：
    除了六个走通用分支的字段（消息形如「评测结果缺少必填口径字段 ['benchmark']」），
    `k` 走的是专门分支（「k 不能为空（pass@k 的 k 必填，见 EVAL_REQUIRED_FIELDS）」）——
    那句话比通用那句更具体（它说明了为什么 `k` 必填），但它没有「口径」二字。

    于是判据改成：消息必须点名缺的是哪一个字段（`re.escape(missing)`）。
    这比"句子里有『口径』二字"更强：改前只要句子含那两个字就过，
    改后必须写对字段名——把消息与被测字段绑在一起。
    实测（`temp/_probe_fc05_messages.py`，读数 `temp/fc05-messages.txt`）：
    `EVAL_REQUIRED_FIELDS` 七个字段的消息全部点名了自己（7/7），
    所以这条加强同时满足旧的六个与 `k` 那一个。
    """
    for missing in S.EVAL_REQUIRED_FIELDS:
        kw = dict(eval_id="0000", claim_key="K", benchmark="b", benchmark_version="v",
                  split="test", k=1, value=0.5, decontamination="none", date="d",
                  source="s", created_at=TS)
        kw[missing] = ""
        # 词边界：不能用裸子串 —— 字段 `k` 会被 `benchmark` 里那个 `k` 命中
        # （这条洞是我自己写负控时量出来的：`re.escape("k")` 在
        # `评测结果缺少必填口径字段 ['benchmark']` 上匹配成功）。
        with pytest.raises(ValueError,
                           match=rf"(?<![A-Za-z0-9_]){re.escape(str(missing))}(?![A-Za-z0-9_])"):
            S.EvalResult(**kw).validate()


def test_eval_value_must_be_a_ratio():
    """用百分数会让"97 与 0.97"在同一条记录里共存 ⇒ 只允许 0..1。"""
    with pytest.raises(ValueError, match="比率"):
        S.EvalResult(eval_id="0000", claim_key="K", benchmark="b", benchmark_version="v",
                     split="t", k=1, value=97.0, decontamination="none", date="d",
                     source="s", created_at=TS).validate()


def test_conflicting_duplicate_eval_is_an_error(store):
    """负控：同一口径下两个不同的值 ⇒ error（至少有一条是错的）。"""
    store.init()
    _eval(store, "0000", value=0.348)
    _eval(store, "0001", value=0.97)
    got = _issues(store, level="error", code="eval_duplicate_conflicting")
    assert len(got) == 1 and "口径就是数字的一部分" in got[0]["message"]


def test_same_value_duplicate_eval_is_clean(store):
    """防误伤：同一口径下相同的值重复登记不报（可能是不同来源的互证）。"""
    store.init()
    _eval(store, "0000", value=0.348)
    _eval(store, "0001", value=0.348, source="paper-y")
    assert _issues(store, level="error", code="eval_duplicate_conflicting") == []


def test_document_can_cite_an_eval_result(store):
    """稿件可以引评测结果：`eval:` 前缀要能被解析；不存在的要报悬空。"""
    store.init()
    _eval(store, "0000")
    docs = store.read("documents")
    docs["rows"].append({
        "doc_id": "0000", "kind": "note", "title": "t", "status": "draft",
        "claims": [
            {"claim_id": "c1", "text": "x", "citations": ["eval:0000"], "evidence_kind": "proof"},
            {"claim_id": "c2", "text": "y", "citations": ["eval:0099"], "evidence_kind": "proof"},
        ],
    })
    store._atomic_write(store.data / "documents.json", docs)
    errs = _issues(store, level="error", code="dangling_citation")
    assert len(errs) == 1 and "评测结果" in errs[0]["message"], errs


# ============================================================ FC-24 的渲染层 gate


def test_claim_with_a_benchmark_number_but_no_eval_citation_is_flagged(store):
    """核心：正文写了基准数字却没引用 `eval:` ⇒ warning（口径无法追溯）。

    FC-24 的判据②是"缺任一字段的数字不得进入对外报告"。
    `EvalResult.validate` 只在登记时管字段齐全，它管不到
    "正文里写了一个数字却没引用任何评测记录"—— 而后者才是真正会流出去的形态：
    读者看到"pass@1 达到 97%"，无法知道那是 LLM judge 分、端到端精确值、还是别人论文的数字。
    """
    store.init()
    docs = store.read("documents")
    docs["rows"].append({
        "doc_id": "0000", "kind": "note", "title": "t", "status": "draft",
        "claims": [{"claim_id": "c1", "text": "本方法在 miniF2F 上 pass@1 达到 34.8%。",
                    "citations": ["lit:0000"], "evidence_kind": "proof"}],
    })
    store._atomic_write(store.data / "documents.json", docs)
    got = _issues(store, level="warning", code="number_without_eval_scope")
    assert len(got) == 1 and "口径就是那个数字的一部分" in got[0]["message"]


def test_claim_with_a_benchmark_number_and_eval_citation_is_clean(store):
    """负控：引用了 `eval:` 就不再报（口径可追溯）。"""
    store.init()
    _eval(store, "0000", value=0.348)
    docs = store.read("documents")
    docs["rows"].append({
        "doc_id": "0000", "kind": "note", "title": "t", "status": "draft",
        "claims": [{"claim_id": "c1", "text": "本方法在 miniF2F 上 pass@1 达到 34.8%。",
                    "citations": ["eval:0000"], "evidence_kind": "proof"}],
    })
    store._atomic_write(store.data / "documents.json", docs)
    assert _issues(store, level="warning", code="number_without_eval_scope") == []


def test_claim_without_any_number_is_not_flagged(store):
    """负控（分级校准）：正文里没有基准数字 ⇒ 不报。

    这条门刻意是 warning 而不是 error：正则识别"基准数字"必然有假阳性，
    所以它交付的是指针而不是缺陷判定。没有这条负控，"它到底报不报"
    就无从判断 —— 而一个对每句话都报警的门等于没有门。
    """
    store.init()
    docs = store.read("documents")
    docs["rows"].append({
        "doc_id": "0000", "kind": "note", "title": "t", "status": "draft",
        "claims": [{"claim_id": "c1", "text": "K(m) 是 m-正则的，且围长为 6。",
                    "citations": ["lit:0000"], "evidence_kind": "proof"}],
    })
    store._atomic_write(store.data / "documents.json", docs)
    assert _issues(store, level="warning", code="number_without_eval_scope") == []


# ============================================================ 终态名单的单一来源


def test_attack_terminal_statuses_has_a_single_source_and_is_complete():
    """"终态"这个概念不可能有两个定义（FC-03）。

    实测缺陷：`attack_tools.TERMINAL_STATUSES` 原先写死
    `("resolved","abandoned","stalled")`，漏了 `supported_not_proved` ——
    而 `agent_f` 会真的写这个状态。后果是一个已达终态的计划被 `pick_next_subgoal`
    当成活计划重新拾起，于是"预算用尽"这个终止条件形同虚设。

    更值得注意的是：`attack_tools` 自己那段注释已经警告过这个形态
    （"把它排除在外，循环下一轮就会把它当活计划重新拾起"），却漏列了那个状态 ——
    这正是"同一判据两处实现"的典型后果：警告写在 A 处，名单写在 B 处，
    而 B 处漏了一个。
    """
    from agentflow import schema as S
    from agentflow.tools import attack_tools as AT

    assert AT.TERMINAL_STATUSES == S.ATTACK_TERMINAL_STATUSES, (
        "两处终态名单又分叉了 —— 它必须只有 schem.ATTACK_TERMINAL_STATUSES 一个来源"
    )
    assert "supported_not_proved" in S.ATTACK_TERMINAL_STATUSES, (
        "`supported_not_proved` 是 `agent_f` 会真的写的状态，必须算终态"
    )
    # 终态必须是 ATTACK_STATUSES 的子集（不能出现一个"终态但不是合法状态"的值）
    assert set(S.ATTACK_TERMINAL_STATUSES) <= set(S.ATTACK_STATUSES)


def test_terminal_statuses_covers_every_status_agent_f_can_finish_with():
    """负控：`_derive_status` 可能返回的每一个终态都必须在终态名单里。

    没有这条，"漏一个状态"就只能靠人眼比对两张表 —— 而人眼正是漏掉
    `supported_not_proved` 的那一环。
    """
    import inspect

    from agentflow import agent_f as AF
    from agentflow import schema as S

    src = inspect.getsource(AF)
    # `_derive_status` 里出现的所有字符串字面量状态，若它是 ATTACK_STATUSES 的成员，
    # 且不是"进行中"的那几个，就必须在终态名单里。
    in_progress = {"open", "attacking", "progress"}
    mentioned = {st for st in S.ATTACK_STATUSES if f'"{st}"' in src or f"'{st}'" in src}
    terminal_mentioned = mentioned - in_progress
    missing = terminal_mentioned - set(S.ATTACK_TERMINAL_STATUSES)
    assert missing == set(), (
        f"`agent_f` 里出现了这些终态但不在 ATTACK_TERMINAL_STATUSES 里：{sorted(missing)}"
    )
