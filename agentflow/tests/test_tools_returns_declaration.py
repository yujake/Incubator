"""`ToolSpec.returns` 的反真空门：声明必须机器可读，且必须是实现的子集。

## 这个文件修的是什么

仓库里早就有一条判据 `tests/test_tools_audit_fixes.py::declared_keys`：

```python
def declared_keys(returns: str) -> set[str]:
    return set(re.findall(r"'([a-z_][a-z0-9_]*)'", returns))
```

它只抓单引号键，下游断言是 ``declared - actual == set()``。于是任何不带引号
的写法（``data={src, dst}``、``{question_id, from, to}``、``data=整数行数。``）都被抽成
空集 —— 而空集永远是子集 ⇒ 判据真空通过，那条「docstring 与实现一致」
的审计结论在这些工具上从来没有被执行过。

本轮实测（`D:\\Incubator\\temp\\_probe_returns_parse.py`）：55 个工具里 36 个
（65%）的 ``returns=`` 非空却抽不出任何键。这个文件就是为这 36 个工具补上的门。

## 三条断言，以及它们各自不能证明什么

1. `test_every_tool_returns_declaration_is_machine_readable`
   —— 声明必须能被 `parse_declared_keys` 判成 `parsed`（键集合非空），
   除非它在 `NO_KEY_SET_EXEMPTIONS` 里（每条带「为什么它没有键集合」的理由）。
   它不能证明「声明的键是对的」—— 那是第 2 条的事。

2. `test_declared_keys_are_a_subset_of_what_the_handler_actually_returns`
   —— 对全部 55 个工具各跑一次（临时 store/workspace + 类型正确的占位参数），
   断言 ``declared - set(实际 data)`` 为空。它只抓「声明了却没给」，
   抓不到「给了却没声明」 —— 后者会让 LLM 少看到有用的键，但不会让调用方读错。
   这条不对称关系写在 `SUBSET_CHECK_SCOPE` 里，免得下一个人以为它更强。

3. 负控（`test_negative_control_*`）—— 没有负控的门就是橡皮图章：
   - 声明里塞一个实现不返回的键 ⇒ 第 2 条必须红；
   - 把某个 `returns=` 换回不带引号的写法 ⇒ 第 1 条必须红；
   - 把 `parse_declared_keys` 的 `unparseable` 折成 `parsed` + 空集
     （这正是旧 `declared_keys` 的形态）⇒ 第 1 条必须红。

最后一条负控是这个文件存在的理由：空集在下游是真空通过，
「我没抽到键」与「它没有键」必须分开（三态纪律）。
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow import manuscripts as MS
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import ROLES, build_registry
from agentflow.tools import ocr_tools as OT
from agentflow.tools import search_tools as ST
from agentflow.tools.base import ToolRegistry, ToolSpec

from conftest import add_concept, add_literature, add_relation, add_request, write_library_file
from test_tools_audit_fixes import declared_keys, parse_declared_keys

#: 共享判据所在的模块。判据的「判据」必须走模块属性取函数（不能只捕获 import 进来的
#: 那个名字）：负控要能把 `parse_declared_keys` 打成两态，而只有走模块属性才打得到
#: —— 打不到的话，那条负控就变成了在同义反复里自证。
import test_tools_audit_fixes as shared_declaration
# 假论文包项目的造法只留一份：直接用 `test_paperbuild` 里那个同名夹具函数，
# 免得"打包脚本长什么样"在测试里有两份实现（两份必然漂移）。
from test_paperbuild import _make_project as _make_paper_project

TS = "2026-01-01T00:00:00+00:00"

#: 名册规模。写死是刻意的：新增/删除工具时这条断言会红，而不是让新工具
#: 悄悄从这份门下面溜过去（「少测了几个」与「都测过了」必须能分开）。
TOOL_COUNT = 83

#: 本轮允许被跳过的工具数上限（依据见 `test_..._subset_...` 的 docstring）。
MAX_SKIPPED = 0

#: 判据的范围（写在常量里，免得它被当成比实际更强的东西）：
SUBSET_CHECK_SCOPE = (
    "本判据只抓『声明了却没给』（declared - actual 非空，键在**任意嵌套层**取并集）；"
    "它抓不到『给了却没声明』—— 那种漂移不会让调用方读错字段，只会让它少看到字段。"
    "它也不检查数组里逐元素的一致性：同一个数组的多个元素被并成一份键集合，"
    "所以『元素 A 有、元素 B 没有』这种漂移抓不到（那是更强的一条判据，本文件不做）。"
)

# ---------------------------------------------------------------- 豁免清单
#
# 豁免必须是写下来的、可审阅的，不是「抽不到就跳过」。
# 每一条都要回答同一个问题：为什么这个工具没有键集合？
#
# 判据（写死，不接受「我抽不出来」这个理由）：
#   data 是标量（bool/int/str），或「形状由别处决定的行对象」
#   ⇒ 这个工具自己没有键集合可声明。
# 绝不允许的豁免理由：「正则抽不到」「写起来麻烦」「暂时先放行」。
NO_KEY_SET_EXEMPTIONS: dict[str, str] = {
    "fs.read": (
        "data 是**字符串标量**（文件正文）；键集合只存在于 meta"
        "（encoding/bytes_read/total_bytes/truncated/had_errors/sha256），而 meta 不是 data。"
    ),
    "fs.delete": "data 是**布尔标量**（是否真的删掉了）；found 在 meta 里 —— 布尔没有键。",
    "table.count": (
        "data 是**整数标量**（行数）。它的契约是『计数不受 limit 影响』"
        "（见 `table_tools.table_count` 的 docstring），不是『返回哪些键』。"
    ),
    "table.create": "data 是**新主键字符串**（标量）；落盘整行在 meta.row 里，不是 data。",
    "table.update": "data 是**主键字符串**（标量）；合并后的整行在 meta.row 里，不是 data。",
    "table.delete": "data 是**布尔标量**（是否真的删掉了）；引用者清单在 meta.references 里，不是 data。",
    "table.get": (
        "data 是**行对象或 None** —— 行对象的字段由**那张表的 schema** 决定"
        "（statements 与 literature 的字段完全不同），本工具不承诺固定键集合；"
        "『有没有』由 meta.found 表达。"
    ),
}

# ---------------------------------------------------------------- 探针参数
#
# 每个工具一次调用，参数取「类型正确的最小占位值」。它们不是测试数据，
# 而是「让工具走到它的 ok 分支」的最小输入。
#
#: proof 级断言的落点（`D-1` 的写入期判据要求它真的存在）。`_seed` 会写出这个文件。
#: 定义必须在 `CLAIM` 之前：`CLAIM` 里要用它（模块级常量，顺序即依赖）。
PROOF_REL = "proofs/fixture.lean"
#
# `evidence_kind="proof"` 的断言在 `D-1` 之后还要满足写入期判据：必须引一条
# proof 级实验、并且给出一个盘上真的存在的 `proof_location`。所以这条夹具
# 引 `exp:0000`（`_seed` 已经把那一行造成 formal/proof），落点用 `PROOF_REL`
# （`_seed` 会真的在工作区里写出那个文件）。
# 这不是"为了让判据变绿而造数据"：判据要问的正是"实现到底给不给这些键"，
# 而一条走不到 ok 分支的探针压根没回答这个问题（与 `_seed` 里那段注释同一条理由）。
CLAIM: dict = {
    "claim_id": "claim-1",
    "section": "主要结果",
    "text": "谱落在区间内。",
    "evidence_kind": "proof",
    "citations": ["exp:0000", "lit:0000"],
    "is_negative": False,
    "negation_kind": None,
    "disclaimer": "",
    #: proof 级断言的可复核落点（`D-1`）：`_seed` 会真的把它写进工作区。
    "proof_location": PROOF_REL,
}

BUDGET: dict = {"max_rounds": 4, "max_parallel_subgoals": 2, "max_persist_attempts": 2, "max_depth": 2}

#: 工作区内的样例正文（fs.* / ocr.* / trace.literature / verify.* 都读它）。
SOURCE_REL = "library/0000/source.txt"
#: 论文包四件工具的假项目根（夹具在临时工作区里现造，脚本是会写文件的那几行 Python）。
PAPER_PROJECT = "projects/p2"
SOURCE_TEXT = "An abelian group is a group in which the commutative law holds.\n"

#: `ocr.run` 的输入：它只收 PDF 与图片（`.txt` 会以 `kind=unsupported_format` 失败 ——
#: 那是实现的有意设计，不是缺陷）。所以这里造一张真的 8x8 PNG。
OCR_IMAGE_REL = "library/0000/scan.png"

#: 给 `verify.run_experiment` 用的探针脚本（与 `tests/test_agent_e.py::HONEST_PROBE` 同形：
#: 只报告观察结果，不声称证据等级之外的东西）。
HONEST_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {"grid": 64, "max_err": 1e-9},
    "counterexample": None,
    "negation_kind": "not_proved",
}))
"""


def _doc_row() -> dict:
    """一份合法稿件行（`review.scan_document` 的 doc 参数）。"""
    return S.Document(
        doc_id="0000",
        kind="paper",
        title="稿件",
        markdown_path=None,
        claims=[dict(CLAIM)],
        status="draft",
        review_rounds=0,
        created_at=TS,
        updated_at=TS,
    ).to_dict()


def tool_params() -> dict[str, dict]:
    """55 个工具各自那一次调用的参数。"""
    return {
        # ---- 主控的编排面工具（T0-9）：探针参数一律用"不会真的派活出去"的形态 ——
        # 主控的 Conductor 默认没有角色接线，派活会以 refused/not_wired 如实落台账，
        # 而 `ok(...)` 照样返回（拒绝 ≠ 工具失败）。`ensure_project` 的落点由夹具注入临时目录。
        "conductor.summon": {"target_role": "E", "action": "list_experiments",
                             "input_key": "probe"},
        # 批量派活：夹具里的 Conductor 没有角色接线 ⇒ 每一项都以 `refused/not_wired`
        # 落台账，而工具照样返回 ok 载荷（拒绝 ≠ 工具失败）。两个 target 用不同
        # `instance`，正是"同角色并发多实例"那条路（分波与峰值会出现在返回里）。
        "conductor.summon_many": {
            "targets": [
                {"target_role": "E", "action": "list_experiments", "instance": "1"},
                {"target_role": "E", "action": "list_experiments", "instance": "2"},
            ],
            "why": "探针：只验键集，不真的派活",
        },
        "conductor.ledger": {"view": "stats"},
        "conductor.stop": {},
        "conductor.resume_brief": {},
        "conductor.cancel": {},
        "conductor.ensure_project": {"project_name": "probe1", "start": "cold"},
        "conductor.state": {},
        # 工作项板（业主 2026-10-08 裁 A1=甲）：真跑一次，键集与 `returns=` 逐字比对。
        # 夹具工作区里板上是空的 ⇒ 走的是"读成了、板上没事"那一支（`checked=True, open_count=0`）。
        "conductor.board": {},
        "conductor.role_spec": {"role_name": "C"},
        "conductor.acceptance": {},
        # 收工门（`draft/37` §16 P3）：默认两格是 unknown（工作区里没有论文包与报告，
        # 而 unknown 不是失败）—— 这条走的就是那个成功支，`can_close` 为假不算工具失败。
        "conductor.closing": {},
        "conductor.status_report": {"since": "2026-10-05", "out_dir": "out/review"},
        # 广播（S6-b）：探针工作区里"M 名下的子代理"一个都没有 ⇒ 走的是
        # "读成了、没有收件人"那一支（`recipients=[]` + `note` 说清，不是失败）。
        # "我是谁"由 `observations` 夹具的 `calling_as` 提供（工具形状里没有这一格）。
        "conductor.broadcast": {"subject": "探针：广播一次", "body": "只验键集，不派活"},

        "attack.check_budget": {"budget": BUDGET},
        # 用另一个 problem_key：夹具里已经立过 "pk"，同一个 key 再来一次走的是
        # 「判重命中」那一支（只有 5 个键）—— 而声明的键集合是"成功创建"那一支的。
        # 观测必须打在声明所描述的那一支上，否则这条判据会假红。
        "attack.create_plan": {"problem": "P2", "problem_key": "pk2", "budget": BUDGET},
        "attack.list_plans": {},
        "attack.pick_next_subgoal": {"subgoals": [{"sid": "s1", "status": "todo"}]},
        "attack.status": {"plan_id": "0000"},
        "attack.step": {"plan_id": "0000"},
        "doc.build_document": {"kind": "note", "title": "T", "claims": [dict(CLAIM)]},
        "doc.compose_claim": {"text": "x", "citations": ["lit:0000"], "evidence_kind": "heuristic", "section": "s"},
        "doc.list_documents": {},
        "doc.register_dependency": {
            "used_by": "0000",
            "kind": "theorem",
            "label": "L",
            "status": "external_unavailable",
            "status_reason": "不在可得范围内",
        },
        "doc.scan_claim": {"claim": dict(CLAIM)},
        "doc.paper_anchor": {"project": PAPER_PROJECT, "timeout_sec": 60},
        "doc.paper_state": {"project": PAPER_PROJECT},
        "doc.paper_build": {"project": PAPER_PROJECT, "timeout_sec": 60},
        "doc.paper_compile": {"project": PAPER_PROJECT, "timeout_sec": 60},
        "doc.paper_render": {"project": PAPER_PROJECT, "timeout_sec": 60},
        "fs.delete": {"path": "out/new.txt"},
        "fs.list": {},
        "fs.move": {"src": SOURCE_REL, "dst": "library/0000/moved.txt"},
        "fs.read": {"path": SOURCE_REL},
        "fs.search": {"pattern": "abelian"},
        "fs.stat": {"path": SOURCE_REL},
        "fs.write": {"path": "out/new.txt", "content": "hi"},
        # `fs.edit` 只能改已存在的文件，而 `out/new.txt` 会被 `fs.delete` 先删掉
        # （`registry.names()` 是字母序 ⇒ delete < edit < write）⇒ 它有自己的目标文件
        # （`_seed` 里铺的 `out/edit-target.txt`）。
        "fs.edit": {"path": "out/edit-target.txt", "old_string": "hello", "new_string": "hello!",
                    "note": "来源登记：真跑一次定点替换"},
        "graph.build": {},
        "graph.neighbors": {"concept_id": "0000"},
        "graph.relations_between": {"a": "0000", "b": "0001"},
        "graph.stats": {},
        # `draft/37` §134：交接手稿的读面。编号 `0000` 由 `_seed` 真写一份手稿
        # （编号由脚本从 0000 起分配 —— 夹具不自己编文件名，走的是同一条实现）。
        "manuscripts.list": {},
        "manuscripts.read": {"id": "0000"},
        "ocr.backends": {},
        "ocr.detect_text_layer": {"path": SOURCE_REL},
        "ocr.run": {"path": OCR_IMAGE_REL, "backend": "auto"},
        "research.list_gaps": {},
        "research.poll_waiting": {},
        "research.set_status": {"question_id": "0000", "status": "researching"},
        "research.submit_gap": {"question_id": "0000", "topic": "群论", "mode": "topical"},
        "research.write_note": {"question_id": "0000", "note": "n"},
        "review.list_findings": {},
        "review.scan_document": {"doc": _doc_row(), "dependencies": []},
        "search.dedup_check": {"title": "Nobody wrote about this", "year": 2020},
        "search.ingest_local": {"books_dir": "books_probe", "pattern": "*.txt"},
        "search.download": {"url": "https://example.invalid/paper.pdf"},
        # `R2b` ⑱：`search.literature` 的多源分支也要被这次探针见证 ——
    # 声明里的 `sources[]` 是逐源读数的键集合，只有走 `providers=[…]` 才产生得出。
    # 两个名字都在 `provider_enum` 里、且 `P.build_providers` 已被打桩成返回
    # `_StubProvider()`（所以逐个都解析成桩、不联网）。单源分支的覆盖没丢：
    # `tests/test_tools_search_ocr.py` 里那条 `test_single_provider_path_...` 守着它。
    "search.literature": {"topic": "群", "mode": "topical",
                          "providers": ["fixture", "openalex"]},
        "search.local": {"query": "群"},
        "search.shelf": {},
        "search.providers": {},
        "search.register": {"title": "新文献", "type_code": "J", "summary": "s"},
        "table.count": {"table": "statements"},
        "table.create": {"table": "statements", "row": {"origin": "own_result", "kind": "theorem", "statement_full": "c9", "quote_reason": "尚未逐字校验"}},
        "table.delete": {"table": "statements", "id": "0002"},
        "table.get": {"table": "statements", "id": "0000"},
        "table.list": {"table": "statements"},
        "table.schema": {},
        "table.search": {"table": "statements", "query": "group"},
        "table.update": {"table": "statements", "id": "0000", "patch": {"statement_text": "d2"}},
        "trace.chain": {"relation_ids": ["0000"]},
        "trace.concept": {"concept_id": "0000"},
        "trace.literature": {"lit_id": "0000", "max_chars": 200},
        "trace.relation": {"relation_id": "0000"},
        "verify.check_formal": {"claim": "1+1=2"},
        "verify.code_hash": {"path": SOURCE_REL},
        "verify.detect_verifier": {},
        "verify.evidence_for": {"claim_key": "k"},
        "verify.list_experiments": {},
        "verify.run_experiment": {"claim": "c", "claim_key": "k", "script_path": "probes/honest.py"},
        # V 的三件（见 EXECUTED_KEY_SOURCE 里那一段注释）：探针不求模型，走"没查成"那条。
        "verify.verify_proof": {"statement_id": "0007", "proof_text": "1. 由定义直接得到。"},
        "verify.list_verifications": {"statement_id": "0007"},
        "verify.read_proof": {"statement_id": "0007"},
    }


#: 键名的来源（本轮逐个工具的留痕；可审阅，不是报告里的一句话）。
#:
#: 为什么把这件事写成常量并由 `test_key_source_provenance_is_complete_and_accurate`
#: 检查：`returns=` 的键名必须从实现读出来。而"我从实现读出来的"是一句声明,
#: 声明就必须可核。这里把"哪几个工具是真跑出来的、哪几个是读代码读出来的"钉住,
#: 于是下一个人能一眼看出哪些键名还欠一次真跑（而不是"看起来都挺对"）。
#:
#: 分类判据（写死）：
#:   - `EXECUTED`：本轮真跑过一次，且那一次走到了返回数据的成功分支
#:     （`tests/test_tools_returns_declaration.py` 的 `observations` 夹具就是这次真跑）；
#:   - `CODE`：没真跑通过，键名是从实现里（`ok(...)` 的数据字典 / 返回语句）读出来的。
#:     它们要么需要真网络（`search.download` 的成功分支）、要么需要真 OCR 后端
#:     （`ocr.run`）。
EXECUTED_KEY_SOURCE: frozenset[str] = frozenset(
    {
        "attack.check_budget", "attack.create_plan", "attack.list_plans", "attack.pick_next_subgoal",
        "attack.status", "attack.step",
        "doc.build_document", "doc.compose_claim", "doc.list_documents", "doc.register_dependency",
        "doc.scan_claim",
        "doc.paper_anchor", "doc.paper_build", "doc.paper_compile", "doc.paper_render",
        "doc.paper_state",
        "fs.delete", "fs.edit", "fs.list", "fs.move", "fs.read", "fs.search", "fs.stat", "fs.write",
        "graph.build", "graph.neighbors", "graph.relations_between", "graph.stats",
        "manuscripts.list", "manuscripts.read",
        "ocr.backends", "ocr.detect_text_layer",
        "research.list_gaps", "research.poll_waiting", "research.set_status", "research.submit_gap",
        "research.write_note",
        "review.list_findings", "review.scan_document",
        "search.dedup_check", "search.ingest_local", "search.literature", "search.local",
        "search.providers",
        "search.register", "search.shelf",
        "table.count", "table.create", "table.delete", "table.get", "table.list", "table.schema",
        "table.search", "table.update",
        "trace.chain", "trace.concept", "trace.literature", "trace.relation",
        "verify.check_formal", "verify.code_hash", "verify.detect_verifier", "verify.evidence_for",
        "verify.list_experiments", "verify.run_experiment",
        # V（验证者，F-02 起）的三件只读工具。它们的探针没有模型缝（默认 None）
        # ⇒ `verify.verify_proof` 走 `checked=False, reason="judge_not_wired"` 那一条
        # （同 `verify.check_formal` 的 no_backend：没查成不是工具失败），
        # 而它的键集合在三条返回路径上完全相同 ⇒ 这条探针照样能验"声明 ⊆ 实现"。
        "verify.verify_proof", "verify.list_verifications", "verify.read_proof",
        "conductor.summon_many",        "conductor.summon",        "conductor.ledger",        "conductor.stop",        "conductor.resume_brief",        "conductor.cancel",        "conductor.ensure_project",        "conductor.state",        "conductor.role_spec",        "conductor.acceptance",        "conductor.closing", "conductor.status_report", "conductor.board",
        # 广播（S6-b）：探针走"读成了、没有收件人"那一支（工作区里没有子代理），
        # 键集合与有收件人那一支逐字相同 ⇒ 这条探针验得了"声明 ⊆ 实现"。
        "conductor.broadcast",
    }
)

#: 键名只能从代码读出来的那些工具（见 `EXECUTED_KEY_SOURCE` 的判据）。
CODE_ONLY_KEY_SOURCE: dict[str, str] = {
    "search.download": "需要一次成功的真实下载才能观测 ok 分支（`_h_download` 的 data 字典）；"
    "本机没有可用的下载目标，实测得到的是 fail 分支 ⇒ 键名逐字读自源码。",
    "ocr.run": "需要真的 OCR 后端（easyocr/pytesseract）。本机 torchvision↔numpy ABI 冲突会先炸；"
    "即使注入桩后端也只验证到「编排层」。data 字典的键名逐字读自 `_h_run`。",
}

#: `EXECUTED` 里带保留的那一条：真跑过，但那一次用的是桩 provider。
#: 留痕的理由是「候选字段是桩的输出形状」——真实 provider 可能出现桩没有的字段，
#: 而本条判据抓不到"给了却没声明"。写在常量里，免得被当成"这条已经完全核实"。
EXECUTED_WITH_CAVEAT: dict[str, str] = {
    "search.literature": "`observations` 夹具里走的是成功分支，但 provider 是**桩**："
    "候选的字段形状来自桩，不等于真实 provider 的全部字段（`authors`/`venue` 等本身来自 "
    "`providers.Candidate` 的 to-dict 形状，已按该形状声明）。",
}


#: 破坏前置数据的工具必须最后跑：`fs.move` 会把 `SOURCE_REL` 搬走，而
#: `fs.read` / `ocr.detect_text_layer` / `verify.code_hash` / `trace.literature` /
#: `verify.run_experiment` 都读它；`table.delete` 依赖 `table.create` 刚建的那一行。
#: 顺序是判据的一部分：顺序错了会让本来能跑的工具变成 ok=False ⇒ 白白多一个跳过。
MUTATING_LAST: frozenset[str] = frozenset(
    {
        "conductor.summon",
        "conductor.stop",
        "conductor.cancel",
        "conductor.ensure_project",
        "conductor.broadcast",
        "fs.move",
        "fs.delete",
        "fs.write",
        "fs.edit",
        "search.register",
        "doc.build_document",
        "doc.register_dependency",
        "table.create",
        "table.update",
        "table.delete",
        "research.submit_gap",
        "research.set_status",
        "research.write_note",
        "attack.create_plan",
        "attack.step",
        "verify.run_experiment",
    }
)


# ---------------------------------------------------------------- 桩（不联网的注入）
#
# 为什么必须有桩：`search.*` / `ocr.*` 是真的会联网/起子进程的（`search.providers`
# 逐个发探测请求、`search.literature` 走 provider、`search.download` 抓 URL、
# `ocr.backends` 会真的 mkdir ~/.EasyOCR 并 import easyocr）。在一条判据测试里
# 联网有三个坏处：慢、不确定（429/超时会让 ok=False ⇒ 白白多一个「跳过」）、
# 且会对外发请求。桩仍然走真实的 handler（分支没有被绕过），
# 所以子集判据照样打在实现上。


class _StubProvider:
    """最小 provider：固定回一个候选，不发任何请求。"""

    name = "openalex"

    def __init__(self) -> None:
        self.stats: dict = {"stub": True}
        self.last_query_text = "stub query"
        self.last_filter_notes: list = []
        self.last_filtered_out = 0

    def search(self, topic: str, mode: str = "topical", description: str = "", limit: int = 10) -> list:
        from agentflow import providers as P

        return [
            P.Candidate(
                title="Stub abelian groups",
                year=1930,
                doi="10.1000/stub",
                type_code="J",
                provider="openalex",
                summary="stub",
            )
        ]


class _StubDownloadResult:
    """`fetch` 层的下载结果（字段与 `_h_download` 读的逐个对齐）。"""

    def __init__(self, url: str) -> None:
        self.ok = True
        self.error = None
        self.http_status = 200
        self.bytes = 42
        self.sha256 = "0" * 64
        self.path = Path(tempfile.gettempdir()) / "agentflow_returns_gate_stub.pdf"
        self.url = url


class _StubDownloader:
    """最小下载器：不联网，回一个固定的成功结果。"""

    max_bytes = 50 * 1024 * 1024

    def download(self, url: str, dest: Path, hint: str = "paper") -> _StubDownloadResult:
        dest.mkdir(parents=True, exist_ok=True)
        return _StubDownloadResult(url)


class _StubOcrBackend:
    """最小 OCR 后端：produces_text=True、可用，回固定文本。"""

    name = "easyocr"
    produces_text = True

    def __init__(self) -> None:
        self.checks: dict = {"role": "测试桩"}

    def available(self, *, refresh: bool = False) -> tuple[bool, str]:  # noqa: ARG002
        return True, "桩：总是可用"

    def ocr_image(self, image: object, languages: object) -> str:  # noqa: ARG002
        return "stub ocr text"


# ---------------------------------------------------------------- 观测结果


class Observation:
    """一个工具那一次调用的观测结果。

    `keys` 返回 `None` 表示「这一次调用没能给出可比的键集合」（失败、或 data 不是对象）
    —— 它与「返回的键集合是空集」是两件不同的事，所以不折叠成 `set()`（三态纪律）。

    `declared_keys` 的正则会连嵌套键一起抽（``{'neighbors':[{'relation_ids'}]}``
    会抽出 ``relation_ids``），所以「实际键集合」也必须是递归的 —— 否则
    仓库里原本就合规的那些声明（`graph.neighbors` / `graph.relations_between` /
    `doc.list_documents` / `review.list_findings`）会在本判据下假红。
    这一点是本轮实测出来的：先把 nested 键算进来，判据才对得上解析器的口径。
    """

    def __init__(self, name: str, ok: bool, kind: object, error: object, data: object, meta: dict):
        self.name = name
        self.ok = ok
        self.kind = kind
        self.error = error
        self.data = data
        self.meta = meta

    @property
    def keys(self) -> set[str] | None:
        """data 里出现过的全部字典键（含嵌套）；data 不是对象时返回 None。"""
        if not isinstance(self.data, dict):
            return None
        out: set[str] = set()
        _collect_keys(self.data, out)
        return out

    @property
    def top_keys(self) -> set[str] | None:
        """只取 data 顶层的键（诊断用：`ok=False` 时人一眼看出缺的是哪一层）。"""
        return set(self.data) if isinstance(self.data, dict) else None

    @property
    def comparable(self) -> bool:
        """能不能做键比对：只有「查了、且返回对象」才算。"""
        return self.ok and isinstance(self.data, dict)


def _collect_keys(value: object, out: set[str]) -> None:
    """递归收集 `value` 里出现过的字典键（数组里的对象也算）。

    `depth` 不设上限是刻意的：声明的嵌套深度就是实现的嵌套深度，多下一层不会误伤
    （本仓库的数据最深也就三四层：`data.tables.<表名>.fields[]`）。
    """
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(str(k))
            _collect_keys(v, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_keys(item, out)


# ---------------------------------------------------------------- 夹具


def _seed(store: Store, root: Path) -> None:
    """铺一份「每个工具都有东西可查」的最小自洽数据集。"""
    add_request(store, "r-0001", done=True, result_lit_ids=["0000"])
    add_literature(
        store,
        "0000",
        title="Commutativity in abelian groups",
        path="0000/source.txt",
        processed=True,
        source_request_ids=["r-0001"],
        doi="10.1000/demo.abelian",
        year=1930,
    )
    add_concept(store, "0000", "group", related_concepts=["0001"])
    add_concept(store, "0001", "abelian group", related_concepts=["0000"])
    add_relation(
        store,
        "0000",
        ["0000", "0001"],
        "0000",
        quote="An abelian group is a group in which the commutative law holds.",
        group_key="0000|0001",
    )
    write_library_file(store, "0000/source.txt", SOURCE_TEXT)
    # `fs.edit` 的观测目标：给它一份只属于这一次观测的小文件，别去改别的工具
    # 还要读的东西（`SOURCE_REL` 与 `probes/honest.py` 后面都有别的工具要看）。
    edit_target = store.root / "out" / "edit-target.txt"
    edit_target.parent.mkdir(parents=True, exist_ok=True)
    edit_target.write_text("hello\n", encoding="utf-8", newline="")
    # 真图片（`ocr.run` 只收 PDF/图片）。用 Pillow 造，避免手写 PNG 字节出错。
    from PIL import Image

    image_path = store.root / OCR_IMAGE_REL
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), "white").save(image_path)
    with store.tx("research_questions", actor="test", note="fixture") as tx:
        tx.upsert(
            "research_questions",
            S.ResearchQuestion(
                question_id="0000",
                question="群为何可交换？",
                origin="fixture",
                related_concept_ids=["0000"],
                priority="high",
                created_at=TS,
                updated_at=TS,
            ).to_dict(),
        )
    with store.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", _doc_row())
    # 交接手稿（`draft/37` §134）：`manuscripts.read` / `manuscripts.list` 要有东西可读。
    # 编号不写死：让 `manuscripts.write` 分配（`0000`），观测参数才与实现同源。
    _ms = MS.write(store.root, sender="D", recipient="F", title="夹具手稿",
                   body="铺夹具用的最小交接手稿。\n", summary="只验键集")
    assert _ms["id"] == "0000", _ms
    with store.tx("experiments", actor="test", note="fixture") as tx:
        tx.upsert(
            "experiments",
            S.Experiment(
                experiment_id="0000",
                claim="c",
                claim_key="k",
                # `CLAIM` 是 `evidence_kind="proof"` 的探针，而 `D-1` 的写入期判据
                # 要求它引用的实验本身就是 proof 级（并带检查器输出与受检命题）。
                method="formal",
                result="supports",
                evidence_kind="proof",
                negation_kind="not_proved",
                # 证明行的 `verifier_output` 必须是绑了被检查声明名的诊断
                # （`R2-AN-2`）：从前这里写的是 `"Lean4: no goals"`，
                # 那种输出里没有声明名 —— 行标着 `proof` 而依据读不出来，
                # 是夹具在说假话。本文件不跑 `verify_all`，所以变严的审计判据
                # 没有红它，但夹具仍按检查器真跑过的形态写
                # （`draft/28` §41.4：改夹具，不许放宽判据）。
                verifier_output="'k' does not depend on any axioms",
                verifier_subject_key="k",
                created_at=TS,
            ).to_dict(),
        )
    # `D-1`：proof 级断言的落点必须真的在盘上（`check_proofs` 会 `is_file()`）。
    proof_file = root / PROOF_REL
    proof_file.parent.mkdir(parents=True, exist_ok=True)
    proof_file.write_text("theorem fixture : True := trivial\n", encoding="utf-8")
    # 一条审校发现：`review.list_findings` 的 `returns=` 声明了 findings[] 里的嵌套键
    # （finding_id/doc_id/kind/level/target/message/evidence/status）。表里必须有行，
    # 否则那一支返回空数组 ⇒ 嵌套键一个都观察不到 ⇒ 已有声明会被这条判据假红。
    # 这不是"为了让测试变绿而造数据"：判据要问的正是"实现到底给不给这些键"，
    # 而空表压根没回答这个问题。
    with store.tx("review_findings", actor="test", note="fixture") as tx:
        tx.upsert(
            "review_findings",
            S.ReviewFinding(
                finding_id="0000",
                doc_id="0000",
                kind="unsupported_claim",
                level="warning",
                target="claim-1",
                evidence="citations=[]",
                message="夹具发现",
                created_at=TS,
            ).to_dict(),
        )
    probes = root / "probes"
    probes.mkdir(parents=True, exist_ok=True)
    (probes / "honest.py").write_text(HONEST_PROBE, encoding="utf-8")


class _RoleGateBypassedRegistry(ToolRegistry):
    """测试专用子类：本文件的判据要逐个工具跑一遍，而工具面跨越每个角色。

    `P-14` 把"这次是谁在调"做成调用期判据（`_callable_for`），于是没有任何一张
    正常注册表能调全部 55 个工具 —— 那是设计意图（只读角色拿不到写工具）。
    本文件的判据是"`returns=` 与实现逐条一致"，与权限无关，所以这里只覆写
    那一个谓词。

    为什么这是可接受的、而不是"测试把门拆了"：
    1. 覆写发生在本文件的子类上，生产类 `ToolRegistry` 一字未改
       （`test_tools_base.py` / `test_tools_readonly_roles.py` 有成对负控守着那个谓词）；
    2. 夹具里断言每个工具都至少属于一个角色（`_every_tool_has_a_role`）——
       于是"绕过"与"工具根本没挂给任何人"仍然分得开（后者是真实的声明缺陷）。
    """

    def _callable_for(self, spec, role, *, include_registered_writers):  # type: ignore[override]
        return None


def _every_tool_has_a_role(reg: ToolRegistry) -> list[str]:
    """返回"一个角色都拿不到"的工具名（空列表 = 每个工具都真的挂给了某个角色）。"""
    return sorted(s.name for s in reg._specs.values() if not s.roles)


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ToolRegistry:
    """一个装齐 55 个工具的注册表（联网工具用桩注入，不动装配代码）。

    `monkeypatch` 在夹具结束时自动还原，所以打桩不会泄漏到别的测试文件 ——
    这一点很重要：判据测试里的桩若泄漏，「别的测试变成了在测桩」是没有任何报错的。
    """
    store = Store(tmp_path / "ws")
    store.init()
    _seed(store, store.root)
    # `conductor.acceptance` 要一张真的验收表才走成功支：给夹具造一张最小的
    # （十行的形态与项目脚本产出的一致 —— 表头 + 一行判据）。
    # 登记本地目录的探针要有真目录（否则那一步是 `io_error` ⇒ "没查成"）：
    _books = store.root / "books_probe"
    _books.mkdir(parents=True, exist_ok=True)
    (_books / "probe.txt").write_text("探针书。\n", encoding="utf-8")
    # 登记本地目录的探针要有真目录（否则那一步是 `io_error` ⇒ "没查成"）：
    _books = store.root / "books_probe"
    _books.mkdir(parents=True, exist_ok=True)
    (_books / "probe.txt").write_text("探针书。\n", encoding="utf-8")
    _acceptance = store.root / "out" / "paper" / "ACCEPTANCE.md"
    _acceptance.parent.mkdir(parents=True, exist_ok=True)
    _acceptance.write_text(
        "# 最终验收：P1–P11 逐条读数\n\n结论：**全部成立**（1/1）\n\n"
        "| 判据 | 名称 | 结论 | 读数 |\n|---|---|---|---|\n"
        "| P1 | 真实检索 | 成立 | 夹具读数（探针用的假表） |\n",
        encoding="utf-8")
    # 论文包四件要一个真有脚本的项目根；造在夹具的工作区里。
    _make_paper_project(store.root / PAPER_PROJECT, check_exit=0)

    # 检索侧：provider 构造与探测函数都换成桩，下载器也不联网。
    # 三个 patch 都必须打在模块前缀所指的那个对象上：
    # `search_tools` 里 provider 工厂是 `P.build_providers`、下载器是
    # `F.default_downloader`（`from .. import providers as P` / `fetch as F`）。
    # 打在 `ST` 自己的属性上会 `AttributeError`；打错对象则更糟 ——
    # 会变成一次真实网络请求，而测试照样绿。
    monkeypatch.setattr(ST.P, "build_providers", lambda names, **kw: [_StubProvider()])  # noqa: ARG005
    monkeypatch.setattr(
        ST,
        "_probe_network_provider",
        lambda name, timeout=8.0: {  # noqa: ARG005
            "available": True,
            "status": "probed_ok",
            "reason": "桩：不联网",
            "latency_s": 0.0,
            "evidence": "stub",
        },
    )
    monkeypatch.setattr(ST.F, "default_downloader", lambda cfg: _StubDownloader())  # noqa: ARG005

    # OCR 侧：默认后端换成桩（否则 `ocr.backends` 会真的 mkdir ~/.EasyOCR 并 import easyocr，
    # 而本机 torchvision/numpy 版本冲突会让它抛异常 —— 那是环境问题，不是判据要测的东西）。
    monkeypatch.setattr(OT, "EasyOcrBackend", _StubOcrBackend)
    monkeypatch.setattr(OT, "PytesseractBackend", _StubOcrBackend)

    built = build_registry(store=store, workspace_root=store.root, roles=tuple(ROLES)).registry
    # 见 `_RoleGateBypassedRegistry` 的 docstring：本文件要逐个工具跑，跨每个角色面。
    # 用 `__class__` 就地换类（而不是重新逐条注册）是为了让这张表与
    # `build_registry` 的产物逐字节同源 —— 连 `default_budget` 那些装配期属性都不动。
    built.__class__ = _RoleGateBypassedRegistry
    reg = built
    assert reg.bound_role is None
    assert _every_tool_has_a_role(reg) == [], (
        f"这些工具不属于任何角色（声明缺失，不是权限问题）：{_every_tool_has_a_role(reg)}"
    )
    # 先立一个攻坚计划：`attack.status` / `attack.step` 只有计划存在时才走「查到了」
    # 那一支（不存在时它们照样 ok=True，但只有 checked/plan_id/reason 三个键 —— 那不是主路径）。
    bootstrap = reg.call("attack.create_plan", problem="P", problem_key="pk", budget=BUDGET)
    assert bootstrap.ok, bootstrap.error
    return reg

@pytest.fixture
def observations(registry: ToolRegistry) -> dict[str, Observation]:
    """对 55 个工具各调一次，记录观测结果。

    调用顺序 = 非破坏性工具在前、破坏性工具在后（见 `MUTATING_LAST`）。
    """
    params = tool_params()
    order = [n for n in registry.names() if n not in MUTATING_LAST]
    order += [n for n in registry.names() if n in MUTATING_LAST]
    out: dict[str, Observation] = {}
    # `conductor.ensure_project` 会写盘：给它一个临时落点，探针绝不碰真实数据面
    # （`D:\Incubator\projects` 是运行数据面，245 MB，已在 .gitignore 里排除）。
    tmp_projects = Path(tempfile.mkdtemp(prefix="probe-projects-"))
    # S6-b：工具调用也带"我是谁"（生产路径里是 `AgentLoop._do_tool` 的 `calling_as`）。
    # 探针这一层照做 —— 否则 `conductor.broadcast` 会走"不知道我是谁"那条受控拒绝，
    # 而它不是工具失败（判据会把"没查成"与"查过了"分开，这条探针必须打在成功支上）。
    with calling_as("t-probe", "M"):
        for name in order:
            kw = dict(params.get(name, {}))
            if name == "conductor.ensure_project":
                kw["projects_dir"] = str(tmp_projects)
            res = registry.call(name, **kw)
            out[name] = Observation(name, res.ok, res.meta.get("kind"), res.error, res.data,
                                    dict(res.meta))
    return out


# ---------------------------------------------------------------- 判据的「判据」
#
# 这两条与真实用例里的断言逐字同形，抽出来是为了让负控能直接打在它们上
# （负控若不经过同一条判据，就证明不了那条判据会红）。


def _machine_readable_violation(returns: str) -> str | None:
    """返回违反「机器可读」的理由；合规返回 None。

    走 `shared_declaration.parse_declared_keys`（模块属性）而不是本文件 import
    进来的那个名字：负控把模块属性折成两态之后，这里必须跟着变，否则那条负控
    证明的是「别的某个函数没读状态」而不是「门依赖三态入口」。
    """
    _, status = shared_declaration.parse_declared_keys(returns)
    if status == "parsed":
        return None
    return f"状态={status!r}（需要一个能被机器读出的键集合）"


def _declared_minus_actual(returns: str, obs: Observation) -> set[str] | None:
    """`declared - actual`：声明了、但实现没给的那些键（同样走模块属性）。

    `None` 表示判不了（返回的 data 不是 dict ⇒ 键集合根本拿不到）。

    这里曾经写成 `if actual is None: return set()` —— 把"拿不到键集合"（判不了）
    折叠成了"没有缺键"（判过了、没问题），`∅ − ∅ = ∅` 那种纸面通过正是这么来的
    （`G-21`）。而且因为 `None` 与 `set()` 都是 falsy，调用点的 `if missing:` 也分不出来。
    三态纪律：判不了必须能被调用方看见，不许与"没问题"同形。
    """
    actual = obs.keys
    if actual is None:
        return None
    return shared_declaration.declared_keys(returns) - actual


# ---------------------------------------------------------------- 1) 反真空门


def test_registry_ships_exactly_the_expected_number_of_tools(registry: ToolRegistry) -> None:
    """名册规模写死：新增/删除工具必须显式改这里（否则新工具会从门下面溜走）。"""
    assert len(registry) == TOOL_COUNT, (
        f"工具数变成了 {len(registry)}（预期 {TOOL_COUNT}）。"
        "新增工具时请同步：本文件的 tool_params()、MUTATING_LAST，以及这条常量。"
    )
    assert set(registry.names()) == set(tool_params()), "有工具没有探针参数，或探针参数里有已删的工具"


def test_every_tool_returns_declaration_is_machine_readable(registry: ToolRegistry) -> None:
    """反真空：55 个工具逐个，`returns=` 必须能被机器读出键集合。

    放行条件只有一个：工具在 `NO_KEY_SET_EXEMPTIONS` 里（每条带「为什么没有键集合」）。
    失败信息带上原始 `returns=` 字符串 —— 否则人不知道该改什么。

    为什么必须有这条：下游判据是 ``declared - actual == set()``，而空集永远是子集。
    一份抽不出键的声明会让那条判据静默地什么都不检查 —— 本轮实测 36/55（65%）
    的工具处于这个状态，「docstring 与实现一致」这条结论在它们身上从未被执行。
    """
    bad: list[str] = []
    exempted: set[str] = set()
    for name in registry.names():
        returns = registry.get(name).returns or ""
        reason = _machine_readable_violation(returns)
        if reason is None:
            continue
        if name in NO_KEY_SET_EXEMPTIONS:
            exempted.add(name)
            continue
        bad.append(f"  {name}\n      returns={returns!r}\n      问题：{reason}")
    assert not bad, (
        "以下工具的 returns= 抽不出键集合，因此『声明 vs 实现』这条判据在它们身上**真空通过**。\n"
        "请改写成合规写法（单引号键 + 花括号 + 嵌套列表用 [{...}]），键名从实现里读出来；"
        "确实没有键集合的（标量/行对象）请写进 NO_KEY_SET_EXEMPTIONS 并给出理由：\n" + "\n".join(bad)
    )
    # 豁免清单不能是「写了就完事」：每一条都必须在册，且真的是抽不出键的那一类
    # （防「顺手把好工具也豁免掉」这种把门改宽的做法）。
    assert exempted == set(NO_KEY_SET_EXEMPTIONS), (
        "豁免清单与实际豁免的工具不一致："
        f"清单里多出的 {sorted(set(NO_KEY_SET_EXEMPTIONS) - exempted)}（它们其实能抽出键 ⇒ 不该豁免）；"
        f"实际豁免但清单没写的 {sorted(exempted - set(NO_KEY_SET_EXEMPTIONS))}"
    )
    assert exempted <= set(registry.names()), "豁免清单里有不存在的工具（清单会腐烂）"


def test_negative_control_the_gate_turns_red_on_a_declaration_it_cannot_parse(registry: ToolRegistry) -> None:
    """负控：把 `returns=` 换回不带引号的写法 ⇒ 反真空门必须红。

    这是最要命的一条负控：`fs.move` 的真实声明曾经是 ``data={src, dst}。``，
    它抽出空集，于是下游「声明 ⊆ 实现」这条断言永远是绿的。
    本用例证明新的门对这种写法会给出违反理由（而不是「没抽到就跳过」）。
    """
    old_style = "data={src, dst}。"  # 改动前的原文，逐字保留
    assert declared_keys(old_style) == set(), "夹具本身要能复现『空集』这个前提"
    assert _machine_readable_violation(old_style) is not None, "不带引号的声明被判成机器可读 ⇒ 门是橡皮图章"
    # 而合规写法必须过（否则这道门就成了「永远拒绝」）
    assert _machine_readable_violation(registry.get("fs.move").returns) is None, registry.get("fs.move").returns


def test_negative_control_folding_unparseable_into_parsed_makes_the_gate_red(
    registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """负控：把 `unparseable` 折成 `parsed` + 空集 ⇒ 反真空门必须红。

    这个折叠正是旧 `declared_keys` 的形态：它只返回一个集合，于是「抽不到」与
    「没有键」在下游长得一模一样。本用例把三态入口打回两态，证明门确实依赖那个状态
    —— 换句话说，证明「三态纪律」不是一句装饰。

    打桩打在模块属性上（而不是本文件 import 进来的名字）：真实用例调的是
    `test_tools_audit_fixes.parse_declared_keys`。所以这里直接读模块属性。
    """
    import test_tools_audit_fixes as shared

    old_style = "data={src, dst}。"  # `fs.move` 改动前的原文
    # ---- 折叠前：门必须判出违反（这正是「反真空」的形态）
    assert shared.parse_declared_keys(old_style) == (set(), "unparseable")
    assert _machine_readable_violation(old_style) is not None, "门对不可解析的声明必须是红的"

    real = shared.parse_declared_keys  # 先把真实现抓在闭包里，避免自我递归

    def two_state(returns: str) -> tuple[set[str], str]:
        keys, _status = real(returns)
        return keys, "parsed"  # ← 把「没抽到」折叠成「parsed」，空集照样往下走

    shared.parse_declared_keys = two_state  # type: ignore[assignment]
    try:
        assert shared.parse_declared_keys(old_style) == (set(), "parsed"), "夹具：折叠后必须是 空集 + parsed"
        # ---- 折叠后：门变绿了。这就是缺陷本身：空集在下游是真空通过。
        # （`_machine_readable_violation` 里调用的是模块属性，所以它看到的是折叠版。）
        assert _machine_readable_violation(old_style) is None, (
            "折叠成两态之后门却仍然是红的 ⇒ 本负控证明不了任何事（门本来就没读那个状态）"
        )
    finally:
        shared.parse_declared_keys = real  # type: ignore[assignment]
    # ---- 还原：同一份声明必须重新被判为 red（证明上面的绿是折叠造成的）
    assert shared.parse_declared_keys(old_style) == (set(), "unparseable")
    assert _machine_readable_violation(old_style) is not None


# ---------------------------------------------------------------- 2) 子集判据（全部 55 个）


def test_declared_keys_are_a_subset_of_what_the_handler_actually_returns(
    registry: ToolRegistry, observations: dict[str, Observation]
) -> None:
    """全部 55 个工具：`declared - set(实际 data)` 必须为空。

    ## 三态：`ok=False` 怎么办

    有些工具会因为缺前置数据而失败（`ok=False`）。这类调用必须与「查了、结果不一致」
    分开：

    * `ok=False` ⇒ 跳过键比对，但记下来（它既不是「一致」也不是「不一致」）；
    * `ok=True` 且 data 是对象 ⇒ 做比对。

    不许把「工具跑不起来」当成「一致」—— 那正是本项目反复踩过的坑
    （「没检查」被读成「检查过了没问题」）。因此末尾还要断言
    被跳过的工具数 ≤ MAX_SKIPPED。

    `MAX_SKIPPED = 0` 的依据：本文件的 `_seed()` 铺齐了每个工具需要的前置数据
    （概念/关系/文献/正文/稿件/研究问题/实验行），联网工具用桩注入，
    `verify.run_experiment` 有真的探针脚本 ⇒ 55 个工具全部走到 ok 分支。
    把它改成非零之前，请先在测试输出里逐条说明「哪个工具为什么跑不起来」。

    本判据只抓「声明了却没给」（见 `SUBSET_CHECK_SCOPE`），抓不到「给了却没声明」。

    ## `ok=False` 与「豁免的工具」是两种不同的"没法比对"

    * `ok=False` ⇒ 工具没查成 ⇒ 计入 `skipped`（末尾断言其数量 ≤ MAX_SKIPPED）；
    * 声明在 `NO_KEY_SET_EXEMPTIONS` 里（data 是标量/行对象）⇒ 查成了，
      只是没有键集合可比 ⇒ 不计入 skipped（它有自己的一条负控
      `test_negative_control_an_exempted_tool_is_still_probed_for_real` 盯着它的行为）。
      但豁免 ≠ 免检：`ok=True` 是硬要求 —— 一个标量工具若连跑都跑不起来，照样要红。

    `MAX_SKIPPED = 0` 的依据：本文件的 `_seed()` 铺齐了每个工具需要的前置数据
    （概念/关系/文献/正文/稿件/审校发现/研究问题/实验行），联网工具用桩注入，
    `verify.run_experiment` 有真的探针脚本，`ocr.run` 给的是真图片 ⇒ 55 个工具
    全部走到 ok 分支。把它改成非零之前，请先在测试输出里逐条说明
    「哪个工具为什么跑不起来」。
    """
    mismatches: list[str] = []
    skipped: list[str] = []
    exempted_not_ok: list[str] = []
    for name in registry.names():
        obs = observations[name]
        spec = registry.get(name)
        if name in NO_KEY_SET_EXEMPTIONS:
            if not obs.ok:
                exempted_not_ok.append(
                    f"  {name}（豁免的是键集合，不是行为）ok=False kind={obs.kind} error={(obs.error or '')[:80]}"
                )
            continue
        if not obs.comparable:
            skipped.append(f"  {name}（ok={obs.ok} kind={obs.kind} error={(obs.error or '')[:80]}）")
            continue
        missing = _declared_minus_actual(spec.returns, obs)
        if missing is None:
            # 三态：走到这里说明 `obs.comparable` 说是"可比"、而键集合却拿不到 ——
            # 判据自己矛盾了。显式失败，别让它因为 `None` 是 falsy 而被读成"没有缺键"。
            raise AssertionError(
                f"{name}: `comparable` 为真但 data 不是 dict ⇒ 判据自相矛盾（`G-21`），"
                "不许把它读成『一致』"
            )
        if missing:
            mismatches.append(
                f"  {name}\n      声明了但实现没给：{sorted(missing)}\n"
                f"      returns={spec.returns!r}\n"
                f"      实际 data 键：{sorted(obs.keys or [])}"
            )
    assert not mismatches, "以下工具『声明了一套、返回另一套』：\n" + "\n".join(mismatches)
    assert not exempted_not_ok, "以下工具在豁免清单里，但**这一次调用没成功**（豁免 ≠ 免检）：\n" + "\n".join(
        exempted_not_ok
    )
    assert len(skipped) <= MAX_SKIPPED, (
        f"{len(skipped)} 个工具没跑起来（上限 {MAX_SKIPPED}）—— ok=False **不是**『一致』，"
        "它只是『没查成』。请补齐前置数据或按需调整 tool_params()：\n" + "\n".join(skipped)
    )


def test_negative_control_a_declared_key_the_handler_never_returns_makes_the_subset_check_red(
    registry: ToolRegistry, observations: dict[str, Observation]
) -> None:
    """负控：声明里塞一个实现不返回的键 ⇒ 子集判据必须红。

    用的是与真实用例逐字同形的 `_declared_minus_actual`，并且把这个坏 spec
    真的注册进一个注册表再调用（不是拿手工字典冒充「实现」）。
    """
    good = observations["graph.neighbors"]
    assert good.comparable, "夹具要一个 ok=True 的观测"
    assert not _declared_minus_actual(registry.get("graph.neighbors").returns, good), "好样本必须先绿"

    bogus = replace(registry.get("graph.neighbors"), returns="{'concept_id','degree','nonexistent_key'}")
    assert isinstance(bogus, ToolSpec)
    # 夹具自检：`declared_keys` 只认小写下划线键名 —— 用一个不合键名规格的字符串
    # （比如中文或大写）会抽出空集，于是这条负控会变成"绿"，而它本该红。
    # 这个真实的边界（不合规格的声明键会被静默漏掉）写在 test_declarations_... 的
    # docstring 里，不在这里假装它不存在。
    assert declared_keys(bogus.returns) == {"concept_id", "degree", "nonexistent_key"}
    control_reg = ToolRegistry(name="control")
    control_reg.register(bogus)
    control_reg.bound_role = "C"  # `P-14`：`graph.*` 的声明角色是 C/D
    res = control_reg.call("graph.neighbors", concept_id="0000")
    assert res.ok, res.error
    obs = Observation("graph.neighbors", res.ok, res.meta.get("kind"), res.error, res.data, dict(res.meta))
    missing = _declared_minus_actual(bogus.returns, obs)
    assert missing == {"nonexistent_key"}, f"子集判据没抓住多出来的键：{sorted(missing)}"
    # 负控的负控：把声明改回真实键集合后必须重新变绿（门不能永远关着）
    assert not _declared_minus_actual(registry.get("graph.neighbors").returns, obs)


def test_negative_control_an_exempted_tool_is_still_probed_for_real(registry: ToolRegistry) -> None:
    """负控：豁免 ≠ 免检。

    `table.get` 在豁免清单里（data 是「行对象或 None」，形状由表 schema 决定）——
    但豁免的是键集合，不是行为：它照样必须真的被调用、真的返回一行。
    这条断言防止豁免清单退化成「这些工具从此不用管了」。
    """
    assert "table.get" in NO_KEY_SET_EXEMPTIONS
    hit = registry.call("table.get", table="statements", id="0000")
    assert hit.ok and isinstance(hit.data, dict) and hit.meta.get("found") is True
    miss = registry.call("table.get", table="statements", id="9999")
    assert miss.ok and miss.data is None and miss.meta.get("found") is False


# ---------------------------------------------------------------- 3) 三态入口自身的性质


@pytest.mark.parametrize(
    ("returns", "expected_status", "expected_keys"),
    [
        ("{'checked','verified'}", "parsed", {"checked", "verified"}),
        ("{'count','documents':[{'doc_id','kind'}]}", "parsed", {"count", "documents", "doc_id", "kind"}),
        ("{'a'}；后面可以继续跟中文说明（人可读的部分不许被删掉）", "parsed", {"a"}),
        ("", "empty_declaration", set()),
        ("   ", "empty_declaration", set()),
        ("data={src, dst}。", "unparseable", set()),
        ("{concept_id, name, degree}", "unparseable", set()),
        ("data=整数行数。", "unparseable", set()),
        ("{'Bad-Key'}", "unparseable", set()),  # 大写与连字符都不算键名（与旧正则一致）
    ],
)
def test_parse_declared_keys_is_honest_about_all_three_states(
    returns: str, expected_status: str, expected_keys: set[str]
) -> None:
    """三态入口自身：`parsed` / `empty_declaration` / `unparseable` 必须分得开。

    重点是后几行：「没抽到键」与「没有键」是两件事。旧 `declared_keys` 把它们
    折叠成同一个空集，而空集在下游是真空通过。
    """
    keys, status = parse_declared_keys(returns)
    assert (keys, status) == (expected_keys, expected_status)
    # 薄封装必须与三态入口给出同一个键集合（同一判据不许有两份实现，linter R003）
    assert declared_keys(returns) == keys


def test_key_source_provenance_is_complete_and_accurate(registry: ToolRegistry) -> None:
    """来源可审：每个工具的键名是「真跑出来的」还是「读代码读出来的」，必须都登记在册。

    这条断言的价值不在于"证明键名对"（那是前两条的事），而在于：
    「我的键名是从实现读出来的」本身是一句声明，而声明必须可核。
    它同时挡住两种偷懒：

    * 新加的工具没登记来源 ⇒ 红（不许"顺手抄一个"）；
    * 把读代码得来的键名冒名登记成"真跑过" ⇒ 由 `EXECUTED` 与 `CODE_ONLY` 的
      并集与差集断言挡住（两边必须不重叠、且合起来正好是全部 55 个）。
    """
    all_tools = set(registry.names())
    executed = set(EXECUTED_KEY_SOURCE)
    code_only = set(CODE_ONLY_KEY_SOURCE)
    assert not (executed & code_only), f"同一个工具被登记成两种来源：{sorted(executed & code_only)}"
    assert executed | code_only == all_tools, (
        "来源登记与工具名册不一致："
        f"漏登记 {sorted(all_tools - (executed | code_only))}；"
        f"多出 {sorted((executed | code_only) - all_tools)}"
    )
    assert set(EXECUTED_WITH_CAVEAT) <= executed, (
        f"带保留的来源必须先在 EXECUTED 里：{sorted(set(EXECUTED_WITH_CAVEAT) - executed)}"
    )
    assert CODE_ONLY_KEY_SOURCE, (
        "『读代码得来』的清单空了 —— 若确实都已真跑过，请把这条断言连同常量一起改掉，"
        "而不是让它静默地恒真"
    )


def test_declared_keys_still_behaves_exactly_like_before(registry: ToolRegistry) -> None:
    """`declared_keys` 的兼容性：签名、返回值、语义逐字不变（调用方还在用）。

    `returns=` 改写成合规写法之后，它对合规声明的输出必须与「旧实现逐字复刻」
    完全一致 —— 否则这次重构就顺手改了判据的严格程度，而那是另一件事。
    """
    for name in registry.names():
        returns = registry.get(name).returns or ""
        old_impl = set(re.findall(r"'([a-z_][a-z0-9_]*)'", returns))
        assert declared_keys(returns) == old_impl, name
    # 空声明：旧实现返回空集，新实现必须照样返回空集（签名/返回值不变）
    assert declared_keys("") == set()


# ---------------------------------------------------------------- G-23：两条分支同一套键


def test_search_register_declares_keys_that_the_duplicate_branch_also_returns(
    registry: ToolRegistry,
) -> None:
    """负控（`G-23`）：`search.register` 的判重命中支也必须给全声明里的键。

    为什么这条必须单独走一次"重复登记"：上面那条子集判据对每个工具只跑一次
    真实调用，走的是"新建成功"那一支 —— 于是另一支成了声明看不见的缺口，
    `returns=` 只描述主路径也没人发现。修前实测：判重命中支只有 8 个键，
    缺 `path` / `dedup_key` / `type_code` / `processed` / `download`
    ⇒ 调用方得先判 `created` 才能安全读 `lit_id`（而那正是让 `returns=` 说谎的根源）。

    修法与口径（我选定的）：两条分支返回同一套键，分支无关处给诚实的
    `None`/`False`（不许用 `""`/`0` 冒充"没有"）。
    """
    args = {"title": "G-23 判重命中支的键集合", "type_code": sorted(S.LIT_TYPES)[0], "summary": "s"}
    first = registry.call("search.register", **args)
    assert first.ok, first.error
    assert first.data["created"] is True, first.data

    second = registry.call("search.register", **args)
    assert second.ok, second.error
    assert second.data["created"] is False, second.data

    declared = declared_keys(registry.get("search.register").returns)
    missing = declared - set(second.data)
    assert not missing, (
        f"判重命中支缺少声明里的键：{sorted(missing)} —— "
        "两条分支的键集合必须相同，否则声明只能描述一支，另一支永远是缺口（G-23）"
    )
    # 如实给空值：这两个是"新建成功"那一支才有的东西，本支没发生过
    assert second.data["path"] is None and second.data["download"] is None, second.data
    assert first.data["reason"] is None and first.data["existing"] is None, first.data
