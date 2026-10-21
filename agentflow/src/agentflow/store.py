"""共享存储：跨进程锁、原子写、事务、事件日志、ID 分配、重建。

这是 A/B 两个智能体唯一的交汇点，因此把三件事集中在这里做对：

1. 不存在"部分写入" —— 一律"写临时文件 → os.replace"，且先校验后落盘；校验失败就整笔放弃。
2. 不存在"丢失更新" —— 任何读-改-写都在同一把排他锁内完成（否则后写的一方覆盖先写的）。
3. 不存在"说不清谁改了什么" —— 每次落盘同时追加事件到 `events.jsonl`；事件里带的是整行
   upsert（不是 diff），于是 `rebuild()` 只需按主键折叠就能重建快照。

多表事务按固定顺序加锁（见 `LOCK_ORDER`），这是避免死锁的标准做法。

## "看着对、其实不成立"的地方（`F-1` / `F-3` / `G-12` / `R6-AN-1`，已修）

上面三句话曾经各自有反例，修法与代价逐条写在对应函数的 docstring 里：`_atomic_write`（固定
临时名 `<file>.tmp` ⇒ Windows 上并发写者互抢，`F-3`）· `init` / `rebuild`（不加锁 ⇒ 读到
"清空到一半"的中间态，`G-12`）· `tx` 的提交块（先快照后事件 ⇒ 崩一次就留下"快照有、事件无"
的行并被重建静默丢掉，`F-1`）· `_merge_counters_for_commit`（用事务缓存整份覆盖
`counters.json` ⇒ 窗口内的 `set_counters` 被静默吞掉，`R6-AN-1`）。
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from filelock import FileLock, Timeout

from . import migrate_concepts as MC
from . import schema as S

#: `_atomic_write` 的 `os.replace` 重试次数与退避基数（`F-3`）。
#: 总等待 = 0.02 + 0.04 + 0.08 + 0.16 + 0.32 = 0.62 秒 —— 足够跨过"另一个进程正
#: 持有目标文件"的瞬间，而短到不会让一次真实的权限错误变成一次长挂起。
#:
#: `R3-10`（重审实测）：这句注释此前漏掉了"第 6 次失败之后还 sleep 了 0.64s"
#: 那一笔，于是注释说 0.62s、实测是 1.27s（`os.replace` 恒定失败时）。而这段代码
#: 正处在写者锁内：多出来的那 0.64 秒会原样叠加到持锁时长上。
#: 修法选的是"让代码与注释一致"而不是"改数字"：最后一次尝试失败之后不再 sleep
#: （反正下一句就是抛 `StoreError`，那一觉是纯等待），总等待于是真的 ≈0.62 秒。
_REPLACE_ATTEMPTS = 6
_REPLACE_BACKOFF_S = 0.02

#: 加锁的固定顺序。任何多表事务都必须按这个顺序取锁，否则两个事务可能互相等待。
#: 新增表一律追加在 counters 之前（counters 永远是最后一把，因为任何 alloc 都要它）。
LOCK_ORDER: tuple[str, ...] = (
    "search_requests",
    "literature",
    # 待新增文献列表（业主 2026-10-20 口径）：紧跟在 `literature` 之后 ——
    # 一次检索的候选先落这里、筛完才写 `literature`，两把锁在同一条链路上相邻，
    # "先锁候选、再锁文献"与 ingest 的顺序一致（反过来会在两笔并行 ingest 里互相等待）。
    "lit_candidates",
    # `concepts` 那一格随并表退役（S1r / `SCHEMA_VERSION=2`）：概念行住 `statements`，
    # 于是它的锁就是 `statements` 的锁。留着一个"表已经不在 schema 里、锁还在"
    # 的格会让"老表"以半退役的形态活着（`tx("concepts")` 过了未知表这一关、
    # 拿了一把没人再争的锁，然后才在读行时报错）—— 那不是"并干净"。
    "relations",
    "analysis_reports",
    "research_questions",
    # 猜想：在研究层产生、在实验层被检验 ⇒ 紧跟 research_questions（`draft/30` §T1 第 5 处）。
    "conjectures",
    "reprocess_requests",
    "experiments",
    "attack_plans",
    "documents",
    # 命题台账（`draft/37` §16 P1）：插在 documents 之后、dependencies 之前。
    # 位置理由：命题是依赖的锚点（`dependencies.used_by` 的自然延伸就是 `stmt_id`），
    # 于是"先锁锚点、再锁依赖"与读图的顺序一致；反过来（依赖先锁）在
    # "B 消化入库 + G 登记引用"这种一笔事务里会让两个事务的取锁顺序相反。
    "statements",
    "dependencies",
    "review_findings",
    "tasks",
    "usage_ledger",
    "eval_results",
    "counters",
)

#: 编号空间的上限（当前宽度下全 9）。用满即 fail-closed（DESIGN.md §0.1 C4）。
#:
#: 宽度不在这里写死：`schema.ID_DIGITS` 是唯一定义处，导入期
#: `schema.assert_id_space_contract()` 会把这两处对账（改一边必红）。
#: 2026-10-14 业主裁定「所有四位编号改成六位，防溢出」⇒ 上限由 9999 抬到 999999。
MAX_ID = 10 ** S.ID_DIGITS - 1

#: 已经并走的表：名字 -> (新家, 怎么读它)。S1r 并表那一笔（`SCHEMA_VERSION=2`）
#: 把 `concepts` 从 `schema.TABLES` 里真删了，于是 `_load("concepts")` 会走到
#: "未知表"那一支。那一支与"这张表从来不存在"在结构上分不开，而两者的处置完全不同：
#: 前者要去读新家（`statements` 里 `kind="concept"` 的那些行，统一入口
#: `conceptrows.view(store, shape="legacy")`），后者要查是谁写错了表名。
#: 所以并走的表在这里显式留名，报一条带指路的受控错（`StoreError`），
#: 而不是让它落进笼统的"未知表"里。
#: 这张表只影响报错措辞与指路，不影响任何读写路径 —— 老表的行由
#: `rebuild` 折进新家（见 `_rebuild_locked` 的 `_fold_moved_tables`）。
_MOVED_TABLES: dict[str, dict[str, str]] = {
    "concepts": {
        "into": "statements",
        "id_field": "concept_id",
        "file": "concepts.json",
        #: 它在 `counters.json` 里的类别名（并表之后这一档要摘掉）。
        "counter_kind": "concept",
        #: 老表名在文本里被引用时（`concepts/0001` 这种），新家那一侧必须是
        #: 这一档 kind 的行才算数 —— 不筛的话，一个已被别的行占用的号
        #: 会被读成"这条引用落地了"（那是假的落地）。
        "kind": "concept",
        "how": "读 `statements` 里 `kind=\"concept\"` 的行；统一入口是 "
               "`conceptrows.view(store, shape=\"legacy\")`（老字段名）或 "
               "`conceptrows.view(store)`（新标准形状）",
        "why": "S1r 并表：`SCHEMA_VERSION=2` 起概念行住 `statements`（号由同一分配器重发）",
    },
}


class StoreError(RuntimeError):
    pass


class IdExhausted(StoreError):
    """4 位编号空间用尽。宁可显式失败，也不静默升位宽。"""


def _now() -> str:
    return S.now_iso()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        # 2026-10-17（store #12）：`lease_until` 是自由列（`Literature.validate` 不校验它），
        # 真机里可能是 int ⇒ `fromisoformat` 抛 TypeError，原来只接 ValueError。
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def lease_expired(lease_until: str | None) -> bool:
    """租约是否已过期。空租约视为"无人持有"。"""
    dt = _parse_iso(lease_until)
    if dt is None:
        return True
    return datetime.now(timezone.utc) >= dt


def make_lease(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()


#: 事件流里不参与重放、也不是"读不懂"的那几种 `op`（`R-57` 把这条清单显式化）。
#: `rebuild()` 只重放 `upsert` 与 `delete`；下面这些是记账/边界用的：
#:   - `commit`：批次提交标记（重放的分批依据）；
#:   - `info`：只记日志、不改状态；
#:   - `corrupt`：`read_events` 给坏行放的占位（半行 JSON 等）。
#: 不在这个集合里、又不是 `upsert`/`delete` 的 `op` ⇒ 进 `rebuild()` 的 `unknown_ops`
#: （必须被看见：静默忽略一个不认识的 op，等于"日志里有读不懂的东西"没有任何读数）。
_KNOWN_NON_REPLAY_OPS: frozenset[str] = frozenset({"commit", "info", "corrupt"})

#: 工作区根目录上属于本框架的条目（`R-32` 的守卫只看"有没有不属于我们的东西"）。
#:
#: 为什么 `projects/` 必须在这里：项目文件夹就住在工作区根下面
#: （`projects.projects_dir`），所以"根目录里有个 `projects/`"是正常部署的样子，
#: 而不是"别人的目录"。第一版判据漏了它，`tests/test_conductor_tools.py` 里那个
#: 先建 `projects/<名字>/`、再对根 `init()` 的布局被误拦（`draft/28` §176 记了这次误拦）。
#: `.agentflow-workspace` 是 `projects.classify` 认的工作区标记，与"有 `data/`"同义。
#:
#: 这张表刻意只列本框架自己会在根上放的东西：多列一项 = 少拦一种外来目录，
#: 少列一项 = 多拦一种正常布局。两种代价都实测过一次，所以它是逐条登记的。
_WORKSPACE_ROOT_ENTRIES: frozenset[str] = frozenset(
    {"data", "library", "projects", ".agentflow-workspace"}
)


def _refuse_fake_proof_review(root: Path, table: str, doc: Mapping[str, Any], *,
                              before_rows: Iterable[Mapping[str, Any]] = ()) -> None:
    """写入期闸（2026-10-19）：`evidence_kind="proof_review"` 的命题必须有 V 那一签。
    活证据（`projects/mp1` 现算）：10 条 `proof_review` 的 `verification_id` / `reviewed_by` 全是
    `null`、`bits` 是 `{}`，其中 3 条（`000031`/`000032`/`000036`）最近一签是「有毛病」—— 自称
    "证明经逐行审阅"却没有任何「成立」那一签，而 2026-10-19 之前没有任何代码强制它。
    为什么是拒收而不是"降档 + 待办"：`own_result` 缺 `proof_text` 那一档的缺省读数是"猜想级"，
    数据没说谎；而 `proof_review` 是一句话（"V 审过了"），真假只有 `verifications` 能回答 ⇒ 放行
    会让猜想级命题以"审阅过的证明"出现在交付面上（"测试全绿、上线即越权"的形态）。
    判据本体在 `verifications.proof_review_gap`（一处口径：写入期、审计期、收工门都读它）。
    作用域（2026-10-19 晚，`projects/mp2` 带出的一处过宽）：只核这一笔事务改到的行（`changed`），
    存量缺陷由审计期 `verify._check_13` 的 `proof_review_without_verification` 点名 ⇒ 改 A 行不再
    顺带核 B 行；新写/改写的行仍要过三条判据（`proof_text` / 最近一签「成立」/ `sha256` 相符）。
    """
    if table != "statements":
        return
    # 惰性 import：`verifications` 依赖 `schema` 与 `jsonlfile`，与 `store` 无环，
    # 但只有真写 `statements` 时才需要它（`tx` 是热路径上最常走的一段）。
    from . import verifications as VR

    rows = doc.get("rows") if isinstance(doc, Mapping) else None
    if not isinstance(rows, list):
        return
    before = {str(r.get("stmt_id") or ""): r for r in (before_rows or ())
              if isinstance(r, Mapping)}
    changed = [r for r in rows
               if isinstance(r, Mapping)
               and before.get(str(r.get("stmt_id") or "")) != r]
    gaps = VR.proof_review_gaps(root, changed)
    if not gaps:
        return
    first = gaps[0]
    # 拒收消息要能让写的人当场知道怎么改（业主 2026-10-19：「拒收消息要能让人看懂」）：
    # `first["why"]` 里已经逐字写着"最近一签是 `v-…`：verdict=…、unresolved_errors=…"、
    # 或"`verifications/<号>.jsonl` 不在盘上"；`checklist` 再给三条逐项的过关读数
    # （缺哪一项一眼可见），最后补两条出口（重派 V 再签 / 如实降档）。
    _checks = "；".join(
        f"{'✓' if c.get('ok') else '✗'} {c.get('item')}（{c.get('detail')}）"
        for c in (first.get("checklist") or []))
    raise ValueError(
        f"{VR.CODE_WRITE}：{len(gaps)} 条命题声称 evidence_kind='proof_review'，"
        f"而 `verifications` 里查不到能签住它的那一条。"
        f"第一条（stmt:{first.get('statement_id') or '?'}）缺的就是下面打了 ✗ 的那几项："
        f"{_checks or '（逐项读数读不到 —— 那是没查成，不是通过）'}。"
        f"它的完整理由：{first['why']}。"
        "这一档的定义逐字是「`proof_text` 非空 ＋ V 的 `verifications` 里那一条签"
        "『成立』且 `proof_sha256` 等于现行正文」（`schema.EVIDENCE_KINDS`），"
        "写入期现在强制它 —— 它**不**要别的字段（`disclaimer` / `verification_id` / "
        "`reviewed_by` 回填都不在这一档的判据里）。"
        "两条出口：① **重派 V 再签**（`verify.verify_proof`，产物就是 "
        "`verifications/<命题号>.jsonl` 的那一行），签完再写这一行；"
        "② 这一行**如实降档**成 `heuristic` 或 `cross_check`（F 的 `_proof_outlet` "
        "就是这么写的：V 没签过就只到 heuristic）。"
        "整笔事务**一行都没写**（与其余校验失败同一处置）。"
    )


#: 命题台账那两张表的写入口（2026-10-19 晚，`projects/mp2` 的 `stmt:000003` 带出来的）。
#:
#: 与 `secretary.STATEMENT_WRITE_TABLES` 同内容但不同用途：那边是"秘书的写集声明"，
#: 这里是"通用写入通道的禁区"。刻意不 import `secretary`（`store` 在依赖图最底层，
#: `secretary` 反过来 import 它）⇒ 清单有两处，由判据守着：
#: `tests/test_secretary.py::test_the_two_tables_are_named_the_same_in_both_places`。
STATEMENT_WRITE_TABLES: tuple[str, str] = ("statements", "dependencies")

#: 直写这两张表时的理由码（与 `Secretary.record_statement` 的拒绝码同一族：
#: 一个词说清"这次调用不成立"，而不是折成"执行了、没成功"）。
DIRECT_WRITE_REFUSED = "direct_write_refused"


def direct_write_refusal(table: str) -> str:
    """要直写 `table` 时返回拒信；空串 = 放行。这条口径只有这一处。

    ## 这一条在堵什么（活证据，`projects/mp2/sessions/mp2-7.jsonl`）：B 调 `register_statement` ⇒ `unknown_tool`
    （那名字不在它的工具面上），于是改走 `table.create(table="statements")` 手写 `evidence_kind="heuristic"` 与
    `bits={}` —— 秘书的四件活与五元位一件都没跑，而盘上那一行看起来完全合法（`stmt:000003` 有 1909 字证明、
    V 也签了「成立」，档位却停在 `heuristic`、`bits` 是空的）。
    ## 为什么判据落在这里而不是只落在工具层：工具层是模型的手（`table.create` / `table.update` 是 A–D 共用的
    通用写口），而"这两张表不许由通用写口碰"是关于表的规矩 —— 明天谁再加一支 `table.upsert_many`，它不该因为
    没人记得这条而重新打开这条路。所以工具层（`tools/table_tools.py`）在进事务之前就用本函数拒一次（拒信是
    `ToolResult.fail` 的可读形态），`Store.tx` 的提交块对带 `tool:` 记号的事务再拒一次（那一层是所有写者的必经
    之路，见 `tx()` 里 `_refuse_fake_proof_review` 的注释）；两处都调这一个函数 ⇒ 关掉它的负控对两层同时生效
    （判据见 `tests/test_statement_write_is_the_secretarys_only.py`）。
    ## 为什么不是"凡直写就拒"：这两张表的合法写者不止秘书一个，且都是人写过的代码路径：
    `agent_b/resolve_structural_duplicate`（合并要标 `superseded`）、`agent_f/core._proof_outlet`（证明结果与档位）、
    `conceptrows.write_concept`（B 的抽取产出）、`doc_tools.register_dependency`（G 登记依赖）、`paperledger`（论文
    台账映射）、`migrate_concepts`（迁移）—— 它们各有自己的判据（`F.step` / `B` 的动作 / `Dependency.validate`），
    且都不叫 `tool:*`；把闸口开在"所有写者"上等于让这些路径 fail-closed，那是权限面的改动，不是本条能决定的。
    ## 第二个用户：`lit_candidates`（业主 2026-10-20 的待新增文献列表）拒的是同一件事 —— 模型的通用写口直接改
    一张"每一格都带语义"的表；合法写者也全是人写过的代码路径（`agent_a/run_once` 的自动入库、`tools/search_tools.py`
    的四支 `lit.*` 工具），它们的 `tx` 记号都不是 `tool:*`。与秘书那两张表唯一的差别是拒信指向的路不同（不是
    `Secretary.record_statement`，而是 `lit.stage_add` / `lit.stage_withdraw` / `lit.stage_reject` / `lit.admit`），
    所以两支各写一句指路，而不是共用一句错的。
    """
    name = str(table or "")
    if name == "lit_candidates":
        # 待新增文献列表（业主 2026-10-20 口径）同样不许由通用写口直写。
        #
        # 为什么它与 `statements` 那一族同形：这张表上的每一条改动都带语义
        # （槽位只增不复用 / 撤掉要留理由 / 入库要回填 lit_id / 条数上限 10）。
        # `table.update(table="lit_candidates", patch={"status": "admitted"})` 能一把
        # 把这些全绕过去，而盘上那一行看起来完全合法 —— 与 `mp2-7` 那一笔直写
        # `statements` 的形态逐字相同（证据在那里，结论在这里通用）。
        # 三条正路都在 `tools/search_tools.py`：`lit.stage_add` / `lit.stage_withdraw` /
        # `lit.stage_reject` / `lit.admit`。
        return (
            f"{DIRECT_WRITE_REFUSED}：`{name}` 不由通用写口直写（`table.create` / `table.update` "
            "以及任何带 `tool:` 记号的裸事务）—— 这张表的每一次改动都带语义"
            "（槽位只增不复用、撤掉要留理由、入库要回填 lit_id、单次入库上限 10），"
            "直写会让它们**同时**失效而盘上那一行看起来完全合法。三条正路：\n"
            "  `lit.stage_add`（广搜结果进待新增列表；一次可追加任意条，超 10 条也允许，\n"
            "     因为超出的部分只是「待审」，不是「入库」）；\n"
            "  `lit.stage_withdraw` / `lit.stage_reject`（撤掉 / 审内容后拒收，都要写理由）；\n"
            "  `lit.admit`（正式入库：条数上限 10、DOI 重复与高重叠无 new_content 一律拒收）。\n"
            "`table.delete` 同样不适用于这张表：撤掉的槽位必须留在列表里"
            "（「第 3 号被撤了哪一篇、为什么」要能查得出来），请用 `lit.stage_withdraw`。"
        )
    if name not in STATEMENT_WRITE_TABLES:
        return ""
    return (
        f"{DIRECT_WRITE_REFUSED}：`{name}` 不由通用写口直写（`table.create` / `table.update` "
        "以及任何带 `tool:` 记号的裸事务）—— 它只有一条正路：\n"
        "  `Secretary.record_statement(payload, *, role=\"B\")` "
        "（B 交内容 ⇒ 秘书洗格式 / 发编号 / 查重 / 改表，四件一次做完；"
        "五元位 `bits`、出处核对、查重都在那一条上，只有它）\n"
        "在循环里请调 **`own.register_statement`**（就是那条正路的工具面："
        "参数与 `B.register_statement` 同形，闸门一个不少）。三条具体走法：\n"
        "  ① 新的一条命题 ⇒ `own.register_statement`（`statement_full` 含完整假设、"
        "`proof_text` 逐字、出处按 `origin` 给）；\n"
        "  ② V 签完之后**把同一份内容再交一次**并把 `evidence_kind` 写强"
        "（`heuristic` → `proof_review`）⇒ 秘书会把那一行**改上去**（不新建行）；\n"
        "  ③ 改别的字段：合并/作废走 `B.resolve_structural_duplicate`，"
        "证明结果与档位走 F 的证明落点（`F.step`），依赖走 `doc.register_dependency`。\n"
        "`table.delete` 不受这条限制（删除不制造证据），但仍受引用保护。"
    )


class Tx:
    """一次事务。通过 `tx.rows(t)` 拿行、`tx.mark_dirty(t)` 声明要写回。"""

    def __init__(self, store: "Store", tables: tuple[str, ...], actor: str, note: str = ""):
        self._store = store
        self.tables = tables
        self.actor = actor
        self.note = note
        self._rows: dict[str, list[dict]] = {}
        self._dirty: set[str] = set()
        self._events: list[dict] = []
        #: 本事务取过号的计数器类别（`R6-AN-1`）。提交块只允许改这些类别 ——
        #: `counters` 是整份写回的，没取过号的类别照盘上的值，否则一个没碰过
        #: 它的在飞事务会把窗口里 `set_counters` 写下的值覆盖回去。
        self._alloc_kinds: set[str] = set()
        #: 每类计数器"本事务读到的那个值"（`R7-AN-1`）。它是"窗口里有没有别的写者"
        #: 的判据：提交时盘上值与本事务自己那次推进之间的差（`cache - base`）是
        #: 本事务自己造成的，不能算别人写过。方向痕迹（`disk_higher` / `disk_lower`）
        #: 也以它为基准 —— 以缓存值为基准会让每一次普通取号都变成"盘上更低"。
        self._alloc_base: dict[str, int] = {}

    # ---- 读
    def rows(self, table: str) -> list[dict]:
        if table not in self.tables:
            raise StoreError(f"事务未声明表 {table}（声明了 {self.tables}）")
        if table not in self._rows:
            self._rows[table] = [dict(r) for r in self._store._load(table)["rows"]]
        return self._rows[table]

    def find(self, table: str, **eq: Any) -> dict | None:
        for r in self.rows(table):
            if all(r.get(k) == v for k, v in eq.items()):
                return r
        return None

    # ---- 写
    def upsert(self, table: str, row: dict, note: str = "") -> None:
        """按主键插入或整行替换一条记录。"""
        if table not in self.tables:
            raise StoreError(f"事务未声明表 {table}")
        id_field = S.TABLES[table]["id_field"]
        key = row.get(id_field)
        if key is None:
            raise StoreError(f"{table} 的行缺少主键 {id_field}")
        # 2026-10-18（业主：「完美跑通 T1」/ 缺陷 ⑩）：`created_by` 缺省时用本次写入的 actor
        # 填，而不是让 `schema` 的 per-table 默认值（`agent-F` 等）冒充作者。
        # 真机 T5：`conjectures.created_by` 全是 `agent-F`，而它其实是 D 写的。
        # 显式给了 `created_by` 就保留（不覆盖调用方的声明）。
        _row_cls = (S.TABLES.get(table) or {}).get("row")
        if _row_cls is not None and "created_by" in getattr(_row_cls, "__dataclass_fields__", {}):
            if not str(row.get("created_by") or "").strip():
                row["created_by"] = str(self.actor)
        rows = self.rows(table)
        for i, r in enumerate(rows):
            if r.get(id_field) == key:
                rows[i] = dict(row)
                break
        else:
            rows.append(dict(row))
        self._dirty.add(table)
        self._record(table, row, note)

    def append(self, table: str, row: dict, note: str = "") -> None:
        self.upsert(table, row, note=note)  # upsert 语义已足够（按主键去重）

    def delete(self, table: str, key: Any, *, key_field: str | None = None,
               note: str = "") -> dict | None:
        """按主键删一行；返回被删的那一行（没找到 ⇒ `None`，什么都没写）。

        ## 为什么它必须存在（`R-57`）：在此之前"删一行"只有一条路 —— 把 `tx.rows(table)` 那个列表就地改掉
        （`tools/table_tools.py::table_delete` 就是这么做的），然后 `mark_dirty` 让快照落盘。快照确实变了，但
        `events.jsonl` 里没有任何痕迹 —— 而重建的唯一输入是事件日志 ⇒ `rebuild()` 之后那一行复活。实测形态
        （`draft/28` §173 的 R-57）：删掉的行在 rebuild 后回来，而 `rebuild()` 返回的每一个计数都"正常"
        （`batches_incomplete=0`、`snapshot_rows_not_in_log=0`）—— 没有任何读数会告诉读的人"你刚恢复的数据比
        删之前多"。
        ## 事件里记什么：`op="delete"` 是新事件类型（`rebuild` 的重放认得它）；`row` 记被删的整行 —— 台账是审计
        面，"谁在什么时候删了哪一行、那一行长什么样"必须留在日志里（否则删除是不可审计的：事后只能看到"少了
        一行"，查不出少的是什么）；`key` 记主键的字符串形式，重放只按它删、不去校验 `row` —— 被删的历史行可能
        不符合当前 schema（schema 升级过），拿它去 `row_from_dict` 会让重建因为一条历史删除而整批失败。
        ## 顺序语义（与 `upsert` 同一个事务里混用时）：事件按调用顺序追加，重放也按顺序折叠 ⇒ 同一事务里
        `upsert` 后 delete ⇒ 删掉了；delete 后 `upsert` ⇒ 在。这与内存里的效果一致（本方法当场改 `rows`）。
        """
        if table not in self.tables:
            raise StoreError(f"事务未声明表 {table}（声明了 {self.tables}）")
        idf = key_field or S.TABLES[table]["id_field"]
        rows = self.rows(table)
        for i, r in enumerate(rows):
            if r.get(idf) == key:
                removed = rows.pop(i)
                self._dirty.add(table)
                self._record(table, dict(removed), note, op="delete",
                             extra={"key": str(key)})
                return removed
        return None

    def insert_unique(self, table: str, row: dict, key_field: str, note: str = "",
                      id_kind: str | None = None) -> bool:
        """`INSERT … ON CONFLICT DO NOTHING` 在本栈里的等价物。

        返回 `True` = 真的插进去了；`False` = 这个键已经有一行，本次什么都没写。
        它不自己加锁，唯一性只在"读与写同一个临界区"内成立：由 `store.tx` 持有该表排他锁来保证 —— `tx.rows()`
        在锁内读的是前一个进程刚提交的那一版，所以后到者一定看得见先到者。在 `store.tx` 之外调用它 = 把
        "先读后写"的窗口原样搬回来，而代码看起来像加了约束 —— 这是本方法唯一危险的误用方式。
        为什么空键要抛而不是"当作不冲突"：空键要么让每一行都冲突（唯一性变成"全表只能有一行"），要么让唯一性
        完全失效 —— 两种都不是调用方想要的，所以不给它一个静默的解释。
        `id_kind` 是本实现对提案的一处最小附加（见 §2.3 的"冲突时不调 `alloc_id` ⇒ 重放不消耗号"）：给了它，
        主键就在判重之后才分配，于是重复调用不会在计数器上留下永久空洞；不给则沿用提案原样的"主键由调用方
        填好"语义。
        """
        if table not in self.tables:
            raise StoreError(f"事务未声明表 {table}（声明了 {self.tables}）")
        key = str(row.get(key_field) or "").strip()
        if not key:
            raise StoreError(
                f"insert_unique({table}) 的 {key_field} 为空 —— "
                "空键在唯一性语义下没有定义（见 docstring）"
            )
        for r in self.rows(table):
            if str(r.get(key_field) or "") == key:
                return False
        if id_kind is not None:
            id_field = S.TABLES[table]["id_field"]
            row = dict(row)
            row[id_field] = self.alloc_id(id_kind)
        self.upsert(table, row, note=note)
        return True

    def mark_dirty(self, table: str) -> None:
        """声明"这张表被就地改过了，提交时要写回"。

        为什么需要这个公开方法：`tx.rows(t)` 返回的是可变列表，调用方可以直接
        改里面的 dict 或 `del` 掉一项（删行就是这么做的）。那种情况下 `upsert` 不会被调用，
        于是没有任何东西把这张表标成脏 —— 提交时它会被静默跳过，改动凭空消失。
        （此前 docstring 提到过 `mark_dirty` 但它并不存在，调用方只能去摸 `tx._dirty`
        这个私有属性，这是文档与实现对不上。）
        """
        if table not in self.tables:
            raise StoreError(f"事务未声明表 {table}（声明了 {self.tables}）")
        self._dirty.add(table)

    # ---- ID 分配（锁内进行，与建行同事务）
    def alloc_id(self, kind: str) -> str:
        """分配一个 4 位 ID。
        `counters.json` 是缓存、真源是各张表里已用掉的号；漂移（手工建行 / 从台账恢复 / 旧版
        `rebuild`）时分配器会发出已被占用的号，而 `upsert` 按主键替换 ⇒ 新行静默覆盖旧行（实测：
        `adjudicate` 新建的 0002/0004 被 0000 顶掉，调用方还看到"新建成功"）。所以三件事缺一不可：
        ① 在事务声明的表里查该号是否已被占用，占用就往后跳；② 跳完把 `counters` 推到最终号 + 1
        （缓存自愈，`verify` 不再报 `counter_behind`）；③ 越界抛 :class:`IdExhausted`，不静默升位宽。
        用"跳过"而不是"抛异常"：漂移是既成事实，往后跳既继续工作又保证不覆盖，失序由 `verify` 的
        `counter_behind` / `id_gap` 报出。
        `F-2`：查占用不许被静默跳过 —— `alloc_id(kind)` 要求事务声明了那张表，否则抛
        :class:`StoreError`（"要分配 X 的号就得同时声明表 Y"）。`R6-AN-1`：`counters.json` 整份写回，
        提交时直接用本事务缓存覆盖会吞掉窗口里 `set_counters` 写的值 ⇒ 只改 `self._alloc_kinds` 里
        那些类别（见 `Store._merge_counters_for_commit`）。"""
        if kind not in S.ID_COUNTERS:
            raise StoreError(f"未知 ID 类别：{kind}")
        if "counters" not in self.tables:
            raise StoreError("分配 ID 的事务必须声明 counters 表")
        #  必须优先用本事务内已改过的 counters，而不是重新从磁盘读。
        # 否则同一事务里连续 alloc 会反复读到同一个初值，把同一个 ID 发出去多次
        # —— 表现为"多行拿到同一个 lit_id"，而按主键 upsert 会静默互相覆盖。
        c = self._store._dirty_counters
        if c is None:
            c = self._store._load("counters")
            self._store._dirty_counters = c
        counters = c.setdefault("counters", {})
        # 2026-10-17（store #4）：counters 是可被手改的 JSON；`"lit": "abc"` 会让裸
        # `int()` 抛 ValueError，把一次取号变成 traceback。坏值当 0（并在下面照常报冲突）。
        _raw_next = counters.get(kind, 0)
        try:
            nxt = int(_raw_next)
        except (TypeError, ValueError):
            nxt = 0
        # `R7-AN-1`：记下"本事务读到的那一版"。提交时用它（而不是缓存值 c+1）去判断
        # "窗口里有没有别的写者"：`cache - base` 正是本事务自己的那次推进，
        # 拿缓存值当基准会把每一次普通取号都读成"盘上被别的写者拨低了"。
        if kind not in self._alloc_base:
            self._alloc_base[kind] = nxt

        # ---- [1] 跳过已被占用的号（`F-2`：目标表必须已声明，否则拒绝发号）
        field = S.ID_COUNTERS[kind]
        table = next((t for t, spec in S.TABLES.items() if spec["id_field"] == field), None)
        jumped = 0
        if table is not None and table not in self.tables:
            raise StoreError(
                f"分配 {kind} 的号必须同时声明表 {table}（当前事务声明的是 "
                f"{sorted(self.tables)}）。"
                "占用检查只能在目标表被读到的前提下做；跳过它会让发号器发出一个"
                "已被占用的号，而 `upsert` 按主键替换 ⇒ **静默覆盖旧行**（`F-2`）。"
                "若确实只需要取号、不建行，请用一个显式命名的接口并说明理由。"
            )
        if table is not None and table in self.tables:
            used = {str(r.get(field)) for r in self.rows(table) if r.get(field) is not None}
            while S.format_id(nxt) in used:
                nxt += 1
                jumped += 1
                if nxt > MAX_ID:
                    raise IdExhausted(
                        f"{kind} 的 {S.ID_DIGITS} 位编号空间已用尽（上限 {MAX_ID}）。"
                        "请勿静默升位宽 —— 那会破坏所有历史 ID 的解析（DESIGN.md §0.1 C4/§9.7）。"
                    )

        if nxt > MAX_ID:
            raise IdExhausted(
                f"{kind} 的 {S.ID_DIGITS} 位编号空间已用尽（上限 {MAX_ID}）。"
                "请勿静默升位宽 —— 那会破坏所有历史 ID 的解析（DESIGN.md §0.1 C4/§9.7）。"
            )
        counters[kind] = nxt + 1
        self._dirty.add("counters")
        self._alloc_kinds.add(kind)
        self._record("counters", {"kind": kind, "allocated": S.format_id(nxt)}, note="alloc_id")
        if jumped:
            # 跳过号这件事必须可见：它是"计数器和表已经漂移"的直接证据。
            self.info(
                "alloc_id_skipped_occupied",
                kind=kind,
                table=table,
                jumped=jumped,
                allocated=S.format_id(nxt),
                note=(
                    "计数器落后于表：已跳过被占用号以免 upsert 静默覆盖旧行。"
                    "建议跑 `agentflow verify`（会报 counter_behind）与 `agentflow rebuild`。"
                ),
            )
        return S.format_id(nxt)

    def raise_counter_to(self, kind: str, used_id: str) -> int:
        """把某个 ID 类别的计数器抬到 `used_id + 1`（只抬，不发号、不烧号）。

        ## 为什么需要它（`alloc_id` 的 docstring 自己点名要的形状）：那里面逐字写着"如果将来真的需要'只取号、
        不建行'，那必须是一个显式可审计的形状（例如另开一个 `reserve_id()` 并说明为什么不需要查占用），而不是
        默默把检查跳过"。这个方法是那个显式形状的另一支：不是"取号不建行"，而是"别的地方已经用了这个号，把
        计数器追上去"。
        现场（2026-10-09，S1r 并表过渡期）：概念行要同时写在 `concepts`（老表）与 `statements`（新标准，
        `kind="concept"`）里，两处同号而两张表各有自己的计数器。B 的 pipeline 从 `concept` 发号 ⇒ 镜像进
        `statements` 的那些行让 `stmt` 计数器落在后面，`verify` 当场报 `counter_behind`（"继续分配会撞号"）。
        第一版用"多调一次 `alloc_id` 把计数器顶上去"来修 —— 那是错的：它烧掉一个没建行的号，于是同一张表
        出现 `id_gap`，在真机上被 `test_demo_end_to_end` 的"零问题"判据当场抓出来。所以正确的形状是"把计数器
        设到 `max(used)+1`"，一个号都不烧。
        三条边界：未知类别 / 没声明 `counters` ⇒ 抛 `StoreError`（与 `alloc_id` 同一口径）；`used_id` 不是 4 位
        数字串 ⇒ 什么都不做，返回当前值（不猜）；只抬不降：`used_id + 1` 不大于当前值时不写盘（降计数器是
        `Store.set_counters` 的事，它有它自己的语义与痕迹）。
        """
        if kind not in S.ID_COUNTERS:
            raise StoreError(f"未知 ID 类别：{kind}")
        if "counters" not in self.tables:
            raise StoreError("抬计数器的事务必须声明 counters 表")
        c = self._store._dirty_counters
        if c is None:
            c = self._store._load("counters")
            self._store._dirty_counters = c
        counters = c.setdefault("counters", {})
        text = str(used_id or "")
        current = int(counters.get(kind, 0))
        if not text.isdigit():
            return current
        target = int(text) + 1
        if target <= current:
            return current
        counters[kind] = target
        self._dirty.add("counters")
        # 与 `alloc_id` 同一口径地记一笔：提交时这一类要写回（`_alloc_kinds`），
        # 事件行也让 `rebuild` 能把计数器折回来（见 `rebuild` 对 `counters` 的折叠）。
        self._alloc_kinds.add(kind)
        self._record("counters", {"kind": kind, "allocated": S.format_id(target - 1)},
                     note="raise_counter_to")
        return target

    # ---- 事件
    def _record(self, table: str, row: dict, note: str = "", *, op: str = "upsert",
                extra: dict | None = None) -> None:
        """把一次写追加进本事务的事件流。

        事件长什么样只在这一处定义（`R-57` 的删除事件也走这里）：
        两个调用点各自拼一个 dict，迟早会拼出两种字段顺序 / 两套默认值，
        而事件流是重建的唯一输入 —— 那种偏差不会有任何读数报出来。
        `extra` 的字段落在 `row` 与 `actor` 之间，既有的 `upsert` 事件因此逐字节不变。
        """
        self._events.append({
            "op": op, "table": table, "row": row, **(extra or {}),
            "actor": self.actor, "note": note or self.note,
        })

    def info(self, message: str, **extra: Any) -> None:
        """只记日志、不改状态。"""
        self._events.append({"op": "info", "message": message, "actor": self.actor, **extra})


class Store:
    """一个 data 目录 + 一个 library 目录。"""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.data = self.root / "data"
        self.library = self.root / "library"
        self.locks = self.data / ".locks"
        self.events_path = self.data / "events.jsonl"
        self._dirty_counters: dict | None = None
        #: 进程内的批次序号（`F-1` 的提交标记用）—— 让同一毫秒内的两批也不撞号。
        self._batch_seq = itertools.count(1)
        #: 事件序号的水位线（`c-6`）。每次追加前都会与日志尾巴取 max，
        #: 所以它只是"这一进程已经发到哪"，不是判断起点 —— 起点永远是
        #: `read_events()` 的尾巴，见 `_next_seq`。声明在这里是为了让
        #: "这个属性一定存在"成为类的事实，而不是某一次调用的副作用。
        self._seq = 0

    # ---------------------------------------------------------------- 初始化
    def _writer_lock(self, *, timeout: float = 60.0) -> FileLock:
        """全体表之外的一把写者锁（`G-12`）。

        为什么在 `LOCK_ORDER` 之外还要一把：`init()` / `rebuild()` / 直接调 `_atomic_write` 的写者不持有任何表锁，
        而它们会批量重写多张表。实测（`G-12`）的形态是：一个进程在 `init(force=True)` 或 `rebuild()`，另一个进程
        在 `tx()` 里读同一张表 ⇒ 读的人会看到"表被清空到一半 / 只有一半表是新版"的中间态 —— 那不是数据竞争，
        是可观测的中间态泄漏。
        `## 加锁顺序（防死锁的唯一规则）：先拿全部表锁，再拿这把写者锁（`tx` 的提交块就是这么做的）。`init` /
        `rebuild` 不拿表锁，所以它们只拿写者锁。任何地方都不许反过来（先写者锁、再表锁），否则两个写者会互相
        等待。锁文件放在 `.locks/` 下、名字以 `_` 开头 ⇒ 不会被 `LOCK_ORDER` 的表锁认为是某张表（`tx` 只按
        `LOCK_ORDER` 拼名字）。
        """
        self.locks.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self.locks / "_writer.lock"), timeout=timeout)

    def init(self, force: bool = False) -> None:
        """建立目录与空表。

        `force=True` 会覆盖已有的表 ⇒ 它是"清空这个工作区"的动作，所以在写者锁内完成（`G-12`）：这把锁保证写者
        之间互斥（两个清空/事务不会互相踩），它不排除并发读者在清空过程中读到中间态 —— 读侧今天不拿这把锁
        （`R3-1` 已裁定接受现状）。
        `## `R-32`：没有 `data/` 又不是空目录 ⇒ 拒绝（默认 fail-closed）`：实测事故（`draft/28` §136.3 事故 B）
        一个复核脚本对 `projects/` 下每个目录跑 `Store(...).init()`，于是 `projects/manual-notes/`（人的文件夹，
        里面只有 `我的资料.txt`）被补出整套 `data/`（19 个条目）+ `library/`；判态函数对它的判定自始至终是
        `not_a_project` —— 是那个脚本先动手、后判态。于是"从工具层走有守卫（`projects.ensure_project` 会拒绝外来
        目录）、直连 `Store` 没有"被修成两边都有。判据只有一条，刻意做得窄：
        ```text
        允许 init ⇔  root 不存在
                  ∨ data/ 已存在              （旧工作区/半成品工作区 ⇒ 只补缺失的表：T1 迁移的用法）
                  ∨ .agentflow-workspace 在   （`projects.classify` 认的工作区标记）
                  ∨ root 里没有不属于本框架的条目（白名单见 `_WORKSPACE_ROOT_ENTRIES`）
        否则 ⇒ StoreError（除非 force=True）
        ```
        为什么不看 `data/` 里的表齐不齐：补齐缺失的表正是 `init()` 的正当用法之一（`draft/30` §T1 加
        `conjectures` 表时就是这么给 8 个旧项目补上的）。判据要拦的是"在一个看起来不是我们的目录里凭空建库"，
        不是"表不齐"。
        `## 白名单为什么要包含 `projects/`（`§176` 当场抓到的一次误拦）：第一版把"除 `data/` 与 `library/` 之外
        还有条目"一律当外来目录，于是工作区根目录里有 `projects/` 这一种正常部署被拦下了（项目文件夹就住在
        `projects.projects_dir`，而 `tests/test_conductor_tools.py::test_ensure_project_refuses_foreign_directory`
        造的就是这个布局：先建 `projects/<名字>/`，再对根 `init()`，它在全量套件里当场变红）。这正是"守卫做宽
        ⇒ 一次数据毁灭事故换成一次功能报废"的实例，所以白名单按本框架自己在工作区根上会放什么来列。
        """
        # `R-32`：先判态、后动手（与那次事故的顺序正好相反）。
        if self.root.exists() and not self.root.is_dir():
            # 2026-10-17（store #11）：root 是个文件时 `iterdir()` 抛
            # `NotADirectoryError`（WinError 267）；init 承诺的失败类型是 `StoreError`。
            raise StoreError(f"拒绝 init：{self.root} 存在但不是目录（是个文件）")
        if not force and self._foreign_dir_guard_should_refuse():
            foreign = sorted(p.name for p in self.root.iterdir()
                             if p.name not in _WORKSPACE_ROOT_ENTRIES)
            raise StoreError(
                f"拒绝 init：{self.root} 既不是工作区（没有 data/）、又不是空目录 —— "
                f"里面有 {len(foreign)} 个不属于我们的条目：{foreign[:5]}"
                f"{' …' if len(foreign) > 5 else ''}。"
                "在别人的目录里凭空建出整套 data/ 与 library/ 是**不可逆**的"
                "（实测事故：一个复核脚本把 19 个条目写进了一个只放着 `我的资料.txt` 的文件夹，"
                "见 `draft/28` §136.3 事故 B）。三条出路："
                "① 这确实是新工作区 ⇒ 换一个空目录；"
                "② 确认就要在这里建 ⇒ `init(force=True)`（或 CLI `init --force`）；"
                "③ 走工具层：`projects.ensure_project`，它本来就有「拒绝外来目录」的守卫。"
            )
        self.data.mkdir(parents=True, exist_ok=True)
        self.library.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        try:
            with self._writer_lock(timeout=60.0):
                for table, spec in S.TABLES.items():
                    p = self.data / spec["file"]
                    if force or not p.exists():
                        self._atomic_write(p, S.empty_table())
                cp = self.data / "counters.json"
                if force or not cp.exists():
                    self._atomic_write(cp, {"schema_version": S.SCHEMA_VERSION, "counters": {}})
                self.events_path.touch(exist_ok=True)
        except Timeout as e:
            raise StoreError(
                "获取写者锁超时（init）。可能有另一个进程正在重建/初始化这个工作区；"
                "若进程已死，锁文件是可安全删除的（filelock 用 OS 锁，不含内容）。"
            ) from e

    def exists(self) -> bool:
        return all((self.data / s["file"]).exists() for s in S.TABLES.values())

    def _foreign_dir_guard_should_refuse(self) -> bool:
        """`R-32` 的判据本体（只有这一处实现）：`init()` 该不该拒绝这个目录。

        返回值 `True` = 拒绝。规则与理由见 :meth:`init` 的 docstring；
        这里只把它写成一段可单独调用的代码，好让测试可以直接喂各种形态
        （空目录 / 新目录 / 旧工作区 / 只放着 `projects/` 的工作区根 / 别人的文件夹）
        而不必真的去建文件。
        """
        if not self.root.exists():
            return False                      # 新目录：init 会连它一起建
        if not self.root.is_dir():
            # 2026-10-17（store #11）：root 是个文件时 `iterdir()` 抛
            # `NotADirectoryError`（WinError 267）；init 承诺的失败类型是 `StoreError`。
            return True
        if self.data.exists():
            return False                      # 有 data/ ⇒ 当工作区（补缺失的表是正当用法）
        if (self.root / ".agentflow-workspace").exists():
            return False                      # 与 `projects.classify` 的判据同一口径
        return any(p.name not in _WORKSPACE_ROOT_ENTRIES for p in self.root.iterdir())

    # ---------------------------------------------------------------- 低级 IO
    @staticmethod
    def _dump(doc: dict) -> str:
        return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False, default=str) + "\n"

    def set_counters(self, values: Mapping[str, int], *, actor: str, note: str = "") -> dict:
        """公开地写 `counters.json`（`c-7`；`R7-AN-1` 把"窗口里会怎样"写准）。
        保证：调用返回时文件里就是给定值（拿写者锁 + 原子落盘）。但不保证"与在飞事务不漂移"：若此刻
        有事务已读过 counters、尚未提交，它的提交会按 `_merge_counters_for_commit` 取
        `max(盘上值, 缓存值)`（`R6-AN-1`）⇒ 窗口里显式拨低不会降低盘上值，只留一条带方向的痕迹
        （`counters_commit_merged`，`direction=disk_lower`，带盘上/缓存/基线/合并四个读数）；窗口
        结束后拨低按正常语义生效。
        为什么需要这个公开入口：以前只能绕过事务调私有 `_atomic_write`（`tools/probe_gap_ledger.py`
        的 `c-7` 就是这么干的），那条路不拿写者锁、也不进事务 ⇒ 与并发 `alloc_id` 争同一份 counters
        ⇒ 漂移、严重时撞号并被 `upsert` 静默覆盖。所以给它一个公开路径（与 `init`/`rebuild`/`tx` 的
        提交块同一把写者锁）。但这把锁不保证上面那句"不漂移"：分辨力在提交侧的合并。
        返回值是写进去的文档。刻意不校验"计数器不得小于表里最大号"：本方法的用途之一正是故意造出
        落后状态去复现缺陷，该判据属于 `verify_all`（`counter_behind`）。"""
        kind_map = S.ID_COUNTERS
        unknown = sorted(set(values) - set(kind_map))
        if unknown:
            raise StoreError(
                f"set_counters 收到未知的计数器类别 {unknown}（合法：{sorted(kind_map)}）—— "
                "写进去的键必须能被 alloc_id 读懂，否则它只是盘上一个没人读的数字"
            )
        for k, v in values.items():
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise StoreError(f"set_counters 的 {k!r} 必须是非负整数，收到 {v!r}")
        doc = {"schema_version": S.SCHEMA_VERSION,
               "counters": {k: int(v) for k, v in values.items()}}
        with self._writer_lock(timeout=60.0):
            self._atomic_write(self.data / "counters.json", doc)
            # 进程内缓存也要跟着更新，否则同一进程里紧接着的 alloc_id 会从旧值起算。
            self._dirty_counters = doc
        _ = (actor, note)   # 预留：写者锁已经在锁文件里留下痕迹，这里只保留签名一致性
        return doc

    def _merge_counters_for_commit(self, t: "Tx") -> dict:
        """`R6-AN-1`：提交 counters 之前先读盘、再按"不丢"合并。
        调用点只有一个：`tx` 的提交块，且必须在写者锁内（读盘 → 合并 → 落盘三步要与 `set_counters`
        互斥，否则窗口只是变窄、没有关上）。这是缺陷而不是"刻意的 last-write-wins"：事务只对取过号
        的类别有所有权，却把整份文件按旧缓存覆盖，与"读-改-写都在同一把锁内"相反。
        合并规则（两条都是"不丢"而不是"谁赢"）：① 取过号的类别取 `max(盘上值, 缓存值)`；② 没碰过的
        类别用盘上的值（盘上没有而缓存里有时不补回来 —— 那是本事务读过的旧状态）。
        `R7-AN-1`：痕迹双向 —— 触发条件是"取过号的类别里盘上值 ≠ 基线 `Tx._alloc_base`"（拿缓存当
        基准会让每次普通取号都写一条假归因痕迹），方向给 `disk_higher` / `disk_lower`，读数按类别给
        `disk` / `cache` / `baseline` / `merged`；判据
        `tests/test_store_counters_commit.py::test_quiet_commit_advances_the_counter_without_a_trace`。
        事件在 `_append_events` 之前追加。边界：`rebuild` 的 counters 仍只由事件里的 alloc 推出
        （`set_counters` 不写事件）⇒ 重建后回到"日志里发过的号 + 1"（既有边界，不是本次引入）。"""
        disk = self._load("counters")
        cache = self._dirty_counters or disk
        # 2026-10-17（store #4 的真身）：counters 是可被手改的 JSON；`int("abc")` 会把
        # 一次正常提交打成 traceback。坏值按 0 计（它本就不是一个有效计数）。
        def _as_int(v: Any) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        disk_c = {k: _as_int(v) for k, v in (disk.get("counters") or {}).items()}
        cache_c = {k: _as_int(v) for k, v in (cache.get("counters") or {}).items()}
        out = dict(disk_c)
        changed: dict[str, dict[str, Any]] = {}
        for kind in sorted(t._alloc_kinds):
            d = disk_c.get(kind, 0)
            c = cache_c.get(kind, 0)
            out[kind] = max(d, c)
            base = t._alloc_base.get(kind)
            if base is None or d == base:
                # `base is None` 只可能出现在"没有经过 alloc_id 就进了 _alloc_kinds"时
                # （今天不可能）：没有基线就没有"窗口里有人写过"的证据，不写痕迹。
                continue
            changed[kind] = {
                "disk": d,
                "cache": c,
                "baseline": int(base),
                "merged": out[kind],
                "direction": "disk_higher" if d > base else "disk_lower",
            }
        if changed:
            higher = sorted(k for k, v in changed.items() if v["direction"] == "disk_higher")
            lower = sorted(k for k, v in changed.items() if v["direction"] == "disk_lower")
            t.info(
                "counters_commit_merged",
                differing=sorted(changed),
                direction={k: v["direction"] for k, v in changed.items()},
                # 兼容旧键名：它一直只表示"盘上的值更大、被并进来了"那一半。
                merged_from_disk=higher,
                disk_higher=higher,
                disk_lower=lower,
                disk={k: v["disk"] for k, v in changed.items()},
                cache={k: v["cache"] for k, v in changed.items()},
                baseline={k: v["baseline"] for k, v in changed.items()},
                merged={k: v["merged"] for k, v in changed.items()},
                note=("提交时盘上的计数器与本事务读到的基线不同 ⇒ 这个窗口里有别的"
                      "写者（例如 set_counters）。终值仍取 max(盘上, 缓存)：盘上更高"
                      "时保住它；盘上更低（显式拨低被 max 抬回）时不会让计数器倒退"
                      "（那会重开撞号方向）。两个方向都记在这里，于是被吞掉的那次"
                      "写入至少是可判定的（R6-AN-1 / R7-AN-1）。"),
            )
        merged = dict(disk)
        merged["schema_version"] = S.SCHEMA_VERSION
        merged["counters"] = out
        return merged

    def _atomic_write(self, path: Path, doc: dict) -> None:
        """写临时文件 → fsync → os.replace。同目录替换在 Windows 上也是原子的。

        `## `F-3`：临时名必须唯一，替换必须重试：旧版临时名是固定的 `path.with_suffix(path.suffix + '.tmp')`，`
        `os.replace` 不重试。实测（`temp/auditF-probe2.txt` 的 [F] 段，两个真进程并发各写同一个 `literature.json`
        12 次）：两进程都拿到退出码 0、各自以为写进了 24 行，而磁盘上只剩 8 行；`_atomic_write` 抛出 10 次
        `OSError`，逐字包括 `PermissionError [WinError 32] ... '...literature.json.tmp' -> '...literature.json'`。
        也就是说：模块 docstring 那句无条件的"不存在部分写入"在并发写者下不成立（Windows 上 `os.replace` 会因为
        目标或源被另一个进程打开而抛）。修法三条，都是"把冲突面缩到最小"：
        1. 临时名带 `pid` 与线程 id ⇒ 两个写者不再抢同一个临时文件（抢文件是 `WinError 32` 的直接来源）；
        2. `os.replace` 包一个短重试（指数退避，`R3-10` 之后总等待 ≈0.62 秒：5 次退避，最后一次失败后不再
           sleep）⇒ 目标文件被另一个进程短暂持有时不再硬崩；
        3. 重试耗尽才抛，且抛的是 :class:`StoreError`（带路径与最后一次的 OS 错误），不再是裸 `OSError` ——
           `tx()` 也会把它翻译成"这笔事务没做成"。
        它不保证"并发写同一个表不丢更新"：那件事只有一把锁能保证，见 `_writer_lock` 与 `tx` 的提交块；这里只保证
        单次落盘是原子的、且不会因为临时名相撞而硬崩。
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
        payload = self._dump(doc)
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            last: OSError | None = None
            for attempt in range(_REPLACE_ATTEMPTS):
                try:
                    os.replace(tmp, path)
                    return
                except OSError as exc:  # WinError 32 / Errno 13 都在这一支
                    last = exc
                    if attempt + 1 < _REPLACE_ATTEMPTS:
                        # `R3-10`：最后一次失败之后不 sleep（下面紧接着就抛）。
                        # 旧版无条件 sleep，于是注释里的 0.62 秒在实测里是 1.27 秒，
                        # 而这段在写者锁内 —— 那 0.64 秒是纯粹的持锁等待。
                        time.sleep(_REPLACE_BACKOFF_S * (2 ** attempt))
            raise StoreError(
                f"原子替换失败（重试 {_REPLACE_ATTEMPTS} 次后仍失败）：{tmp} -> {path}；"
                f"最后一次错误：{type(last).__name__}: {last}"
            ) from None
        finally:
            # 失败路径上把临时文件清掉：留着它只会让下一次诊断多一个可疑文件
            # （旧版正是这样攒下一堆 `<表>.json.tmp` —— 实测 [F] 段里能看到它们）。
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    # 清不掉（例如另一个进程正拿着它）不该掩盖真正的失败原因：
                    # 这个 `finally` 里抛出去会把"为什么这笔写失败"换成一个
                    # "临时文件删不掉"。留一个 `<表>.json.<pid>-<tid>.tmp` 的危害
                    # 远小于那个（而且它带 pid，一眼能看出是谁留下的）。
                    pass

    @staticmethod
    def _check_version(doc: dict, where: str) -> None:
        """`F-7`（人裁 = fail-closed，观测时刻 2026-09-26 19:5x）：读期拒绝版本不符。

        背景（`draft/28` 的 `F-7`，实测 `temp/auditF-probe2.txt` / `temp/f7-before.txt`）：版本判据此前只有
        `validate_table` 一处，而它只在提交时被调用 —— 那时校验的是本进程刚合成、`schema_version` 必为当前值
        的 doc。`_load` / `read` / `rows` / `rebuild` 从不校验版本，于是把一个旧版本号的 JSON 放进 `data/` 就能被
        照读不误：「旧字段被按新语义解释」这件事没有任何地方会响。
        现在的口径（所有者裁定）：读期拒绝。不符就抛 `StoreError`，消息里给出两个版本号与这一条的处置（先
        `rebuild` 或做迁移）。缺 `schema_version` 字段 = 与"旧版本"同档（拒读），但不许崩成 `KeyError`；版本相同
        才放行（不是 `>=`，也不是"读不出来就放过"）。
        """
        # 2026-10-17（store #2）：表文件被写成顶层数组（`[]`）时 `doc.get` 抛
        # `AttributeError`；这里按"版本读不出来"处理，与"缺字段"同档（fail-closed）。
        if not isinstance(doc, dict):
            raise StoreError(
                f"{where} 的顶层不是对象（收到 {type(doc).__name__}）⇒ **拒读**："
                "这一份文件坏了，不是\"没有版本问题\"；处置见 `agentflow verify` 的同一张表")
        got = doc.get("schema_version")
        if got == S.SCHEMA_VERSION:
            return
        raise StoreError(
            f"{where} 的 schema_version 与当前不符：盘上是 {got!r}，本进程期望 "
            f"{S.SCHEMA_VERSION!r} ⇒ **拒读**（`F-7` 的口径：读期 fail-closed，"
            "不许按当前语义解释旧数据）。处置：确认要以哪一版为准 ⇒ 必要时跑 "
            "`agentflow rebuild`（从 events.jsonl 重建）或做一次显式迁移；"
            "任何情况下都不许把这一条读成'没有版本问题'。"
        )

    def _load(self, table: str) -> dict:
        if table == "counters":
            p = self.data / "counters.json"
            if not p.exists():
                return {"schema_version": S.SCHEMA_VERSION, "counters": {}}
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                # 2026-10-17（store #1/#5）：counters 分支此前没有 try —— 而表分支有。
                # 坏 JSON / 非 UTF-8 都按"这份文件坏了"报 StoreError，不冒系统异常。
                raise StoreError(
                    f"counters.json 读不出来（{type(e).__name__}: {e}）⇒ **拒读**；"
                    "处置：修好它，或跑 `agentflow rebuild` 从 events.jsonl 重建计数"
                ) from e
            self._check_version(doc, "counters.json")
            return doc
        spec = S.TABLES.get(table)
        if spec is None:
            moved = _MOVED_TABLES.get(table)
            if moved is not None:
                # 受控错 + 指路：这张表并走了，不是"表名写错了"。
                # 两件事都必须能分辨，否则读的人拿到一句"未知表：concepts"
                # 之后不知道下一步该改代码还是该查笔误。
                raise StoreError(
                    f"表 {table!r} 已经并走（{moved['why']}）⇒ 它不在当前 schema 里。"
                    f"新家是 {moved['into']!r}：{moved['how']}。"
                    "处置：读侧改走那个统一入口；老工作区跑一次 `agentflow rebuild`，"
                    "它会把 v1 事件里的老表折进新家（改号逐条落 `out/migrate-map.jsonl`）。"
                )
            raise StoreError(f"未知表：{table}")
        p = self.data / spec["file"]
        if not p.exists():
            return S.empty_table()
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # 2026-10-17（store #5）：非 UTF-8 字节此前在更早一层抛，这一支接不到。
            raise StoreError(
                f"{spec['file']} 不是合法 JSON（{e}）。可用 `agentflow rebuild` 从 events.jsonl 重建。"
            ) from e
        self._check_version(doc, spec["file"])
        return doc

    def read(self, table: str) -> dict:
        """无锁快照读。仅用于展示/统计；要改数据必须走 `tx`。"""
        return self._load(table)

    def rows(self, table: str) -> list[dict]:
        doc = self.read(table)
        rows = doc.get("rows") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            # 2026-10-17（store #3）：表文件可能只剩 `{"schema_version": …}`（半途写坏/手改）
            # ⇒ 原来 `["rows"]` 直接 KeyError，读账的人看到的是 traceback 而不是"这表坏了"。
            raise StoreError(
                f"{table} 的表文件没有 rows 数组（收到 {type(rows).__name__}）⇒ **拒读**；"
                "处置：跑 `agentflow verify` 定位，必要时 `agentflow rebuild` 重建")
        return rows

    # ---------------------------------------------------------------- 事务
    @contextmanager
    def tx(self, *tables: str, actor: str = "unknown", note: str = "", timeout: float = 30.0) -> Iterator[Tx]:
        """多表事务。按 LOCK_ORDER 固定顺序加锁；任一表校验失败则整笔不落盘。"""
        unknown = [t for t in tables if t not in LOCK_ORDER]
        if unknown:
            raise StoreError(f"未知表：{unknown}")
        ordered = tuple(sorted(set(tables) | {"counters"}, key=LOCK_ORDER.index))
        held: list[FileLock] = []
        try:
            self.locks.mkdir(parents=True, exist_ok=True)
            for t in ordered:
                lk = FileLock(str(self.locks / f"{t}.lock"))
                try:
                    lk.acquire(timeout=timeout)
                except Timeout as e:
                    raise StoreError(
                        f"获取 {t} 的锁超时（{timeout}s）。可能有另一个智能体持有该锁；"
                        "若进程已死，锁文件是可安全删除的（filelock 用 OS 锁，不含内容）。"
                    ) from e
                held.append(lk)

            t = Tx(self, ordered, actor, note)
            yield t

            # ---- 提交：先全部校验，再在写者锁内落盘与追加事件。任一失败 => 什么都不写。
            #
            # `F-1`：顺序必须是「① 校验 → ② 追加事件+提交标记 → ③ 逐张落盘快照」。先快照后事件时崩一次
            # 会留下"快照里有、事件里没有"的行，而 `rebuild()` 不报错地丢掉那次提交（实测：快照 2 行 /
            # counters=2 ⇒ 重建后 1 行 / counters=1）。先落事件是安全方向：`rebuild()` 按主键 last-wins
            # 整行 upsert 折叠，重放一批完整事件得到的就是提交时的状态；反过来丢掉的是事件，而重建的
            # 唯一输入就是事件 ⇒ 那一次提交在重建后消失，且没有任何东西会报告这件事。
            to_write: list[tuple[Path, dict]] = []
            counters_pending = False
            for table in sorted(t._dirty, key=LOCK_ORDER.index):
                if table == "counters":
                    # `R6-AN-1`：counters 的内容不能在锁外定。
                    # `Tx.alloc_id` 只在第一次取号时读一次 `counters.json`，而事务体
                    # 全程不持写者锁（写者锁只在下面这一段里拿）；`set_counters`
                    # 拿的是同一把写者锁，所以它能在这个窗口里落盘，随后被这里
                    # 用那份旧缓存整份覆盖 —— 实测：C 写 999 且盘上确认 999，
                    # B 提交后盘上是 4，无日志无异常。现在改成：拿到写者锁之后再
                    # 读盘、再按"不丢"合并（`_merge_counters_for_commit`）。
                    # 落盘顺序里 counters 因此排在最后：事件先于快照这条顺序不变，
                    # 而若干张快照之间的先后没有语义（重建的唯一输入是事件）。
                    counters_pending = True
                    continue
                spec = S.TABLES[table]
                doc = {"schema_version": S.SCHEMA_VERSION, "rows": t.rows(table)}
                S.validate_table(table, doc)
                # ---- 写入期闸：`evidence_kind="proof_review"` 必须有 V 那一签。
                # 为什么落在这一层（`tx` 的提交块）而不是 `schema.Statement.validate`：那条判据要读盘上的
                # `verifications/<命题号>.jsonl`，而 `validate` 是字段级、手上没有工作区根；只有 `Store` 既有
                # `self.root`、又是所有写者的必经之路（`agent_b.register_statement` / F 的 `_proof_outlet` /
                # `table.create`·`table.update` 全落在这里）。落在某一条动作里只能管住那一条动作，而"绕开那条
                # 动作"正是本仓踩过的形态。`rebuild` 刻意不走这里（读历史不是改历史）：存量里已有的假
                # `proof_review` 由审计期 `verify._check_13` 的 `proof_review_without_verification` 点名。
                # `before_rows` 是盘上那一份（不是本事务缓存）：闸只核这一笔真改到的行，别的行的历史缺陷由审计期点名。
                _refuse_fake_proof_review(
                    self.root, table, doc,
                    before_rows=(self._load(table).get("rows") or []))
                # ---- 封野路（2026-10-19 晚）：`statements` / `dependencies` 不许由
                # 通用写口的裸事务建行/改行。
                #
                # 判据只有一份（`direct_write_refusal`），工具层在进事务之前也调它一次
                # ——那一层给模型可读的拒信，这一层是"结构性不可能"的兜底：
                # `tool:` 记号是通用表工具（`tools/table_tools.py` 的三个写口）的
                # 专属记号，秘书与其余合法写者（F 的证明落点 / B 的合并 / G 的依赖 /
                # 迁移 / 夹具）都不用它 ⇒ 这里拒的正好是"模型的手"，一条合法写者都不误伤。
                #
                # 删除不算直写：它不制造证据（`table.delete` 另有 `_REF_SPECS` 的引用
                # 保护），而"建行/改行"才是绕过秘书的那件事。判据因此看这一笔事务对这张表
                # 动了什么 `op`：只有 `delete` ⇒ 放行；有 `upsert`（或一条事件都没有 =
                # 就地改 `tx.rows()` 再 `mark_dirty`）⇒ 拒。
                if str(t.note or "").startswith("tool:"):
                    ops = {str(e.get("op")) for e in t._events
                           if str(e.get("table")) == table}
                    if ops != {"delete"}:
                        why = direct_write_refusal(table)
                        if why:
                            raise ValueError(why)
                to_write.append((self.data / spec["file"], doc))

            wlock = self._writer_lock(timeout=timeout)
            try:
                wlock.acquire()
            except Timeout as e:
                raise StoreError(
                    f"获取写者锁超时（{timeout}s，提交阶段）。可能有另一个进程正在"
                    "rebuild/init 这个工作区；若进程已死，锁文件是可安全删除的。"
                ) from e
            try:
                # `R6-AN-1`：counters 的最终内容在写者锁内定 —— 读盘、合并、
                # 必要时往这一批事件里追加一条痕迹，都必须在 `_append_events`
                # 之前完成（事件只追加一次，追加之后改 `t._events` 不会进日志）。
                if counters_pending:
                    to_write.append(
                        (self.data / "counters.json", self._merge_counters_for_commit(t))
                    )
                if t._events:
                    self._append_events(t._events)
                for path, doc in to_write:
                    # `G4-R2`（第 50 轮，判据四第 4 组带出来的新洞）：把写盘的 `OSError` 翻成
                    # `StoreError`。旧版让 `_atomic_write` 的裸 `OSError`（磁盘满 errno 28 /
                    # 权限 errno 13 / WinError 32）直接穿透 `tx()` —— 而本模块的落盘层
                    # （`init` / `_atomic_write` 的重试耗尽那一支）都抛 `StoreError`。
                    # 调用方按"`StoreError` 就是 store 报的失败"写恢复路径，会漏掉最该恢复的那一类
                    # （磁盘满 / 只读盘），拿到的是一次裸 `OSError`。
                    # 实测（`temp/g4-nospace.txt`，用 monkeypatch 模拟 ENOSPC，不改盘）：
                    # 原快照字节未变、无残留 `.tmp`、事务不生效 —— 数据是安全的，
                    # 唯独异常类型不对。把原始 errno 与路径带进消息，别丢诊断信息。
                    try:
                        self._atomic_write(path, doc)
                    except OSError as exc:
                        raise StoreError(
                            f"落盘失败（{type(exc).__name__}，errno="
                            f"{getattr(exc, 'errno', None)}）：{exc}。"
                            f"目标文件 {Path(path).name}。"
                            "事务**没有**生效（原快照未被改动、临时文件已清理）；"
                            "常见原因是磁盘满 / 只读盘 / 文件被别的进程占用 —— "
                            "处置是腾出空间或改权限后重试，而不是重跑整个流程。"
                        ) from exc
            finally:
                try:
                    wlock.release()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            #  无论成功还是失败都必须清空事务内的计数器缓存。
            # 只在提交成功时清，会让失败事务把改过的计数留在内存里：下一次
            # alloc_id 会基于一个磁盘上并不存在的值发号，轻则产生 ID 空洞，
            # 重则与另一个进程发出的号真撞号，而按主键 upsert 会静默覆盖。
            self._dirty_counters = None
            for lk in reversed(held):
                try:
                    lk.release()
                except Exception:  # noqa: BLE001
                    # 释放锁失败刻意不向上抛：这段在 `finally` 里，抛出去会掩盖
                    # 真正的失败原因（事务里那个异常才是要报的）。而且 filelock 用的是
                    # OS 锁，进程退出时由内核回收，锁文件可安全删除 —— 泄漏的代价是有限的，
                    # 而掩盖原始异常会让"为什么这笔事务失败"永远查不出来。
                    pass

    # ---------------------------------------------------------------- 事件日志
    def _append_events(self, events: list[dict]) -> None:
        """把一个事务的事件整批追加，并在末尾写一条提交标记（`F-1`）。

        一批事件 = 一个 `batch` 号（时间戳 + pid + 序号，进程内单调）。`rebuild()` 只重放带提交标记的批次：标记
        就是"这一批的每一行都已经完整落到这个文件里了"的证据。没有标记的批次一律不重放 —— 那是崩在追加中途
        留下的半批（`read_events` 早就会把半个 JSON 行读成 `corrupt`），重放它会让重建结果取决于崩在第几行。
        兼容口径：仓库里已有的历史事件没有 `batch` 字段，它们被当作"完整批次"处理（见 `rebuild` 的注释）——
        历史日志是旧版一行一 fsync 写出来的，把老事件一律当不完整会丢掉整个历史，那比它要防的风险大得多；
        `rebuild` 会把这条口径连同"重放了多少批、跳过多少批"一起返回。
        调用点约束（`c-6`）：序号由 `_next_seq` 从日志尾巴取，而"读尾巴 + 追加"必须是一个原子段 ⇒ 本方法只能在
        写者锁内调用（`tx` 的提交块与 `init` / `rebuild` 都拿同一把 `_writer_lock`），于是两个进程不可能同时读到
        同一个尾巴。反过来，在锁外直接调用它（探针脚本曾这么干过，见 `c-7`）会让两边的序号互相重叠。
        """
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        batch = f"{_now()}-{os.getpid()}-{next(self._batch_seq)}"
        with open(self.events_path, "a", encoding="utf-8", newline="\n") as f:
            for e in events:
                e = {"seq": self._next_seq(), "ts": _now(), "batch": batch, **e}
                f.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
            f.write(json.dumps(
                {"seq": self._next_seq(), "ts": _now(), "op": "commit",
                 "batch": batch, "rows": len(events)},
                ensure_ascii=False, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _next_seq(self) -> int:
        """取下一个事件序号 —— 来源是日志里已有的最大 seq，不是"数行数"（`c-6`）。

        `## `c-6`：序号必须由"日志的尾巴"决定，且首次加载要落在写者锁内（`draft/28` 的 `c-6` 说两件事）：`
        1. 旧版把 `len(events.jsonl 的行数)` 当序号来源（每进程只读一次）。行数与 `seq` 字段不是一回事：
        `read_events` 会把任何解析不了的行替换成 `{"seq": i, "op": "corrupt"}`，于是日志里出现过坏行之后，
        "第 n 行的 seq"与"第 n 行"就分家了，接着发出的号会与日志里已有的 `seq` 撞上。现在改成"日志里出现过的
        最大 `seq` + 1"（见 `_seq_high_water`）：坏行占位的 `seq=i` 也照算，序号只会往后走，不会回退到别人用过的
        值上。
        2. 旧版的惰性加载（第一次调用时数一遍行数）发生在任意位置；真正需要原子性的是"读日志尾巴 → 写入新行"
        这一段，它由 `_append_events` 在 `store.tx` 的写者锁内调用（提交块先 `wlock.acquire()` 再
        `_append_events`），所以读尾巴与追加是同一个临界区里的两步。
        由此带来一条对调用方的约束：`_append_events` / `_next_seq` 只能在写者锁内调用。`init` / `rebuild` 走
        `_writer_lock`，`tx` 在提交块里拿同一把锁 ⇒ 三者互斥，没有"两个写者同时读尾巴"。这一条不是靠自觉：
        `tests/test_store_r3_commit_order.py` 钉住提交顺序，而这里每次调用都重新读一遍日志尾巴（不再缓存一个可能
        与盘上分家的行数），代价是每次追加多读一遍 `events.jsonl` —— 相对"重复 seq 的时间线"，这个代价是划算的。
        """
        self._seq = max(self._seq, self._seq_high_water()) + 1
        return self._seq

    def _seq_high_water(self) -> int:
        """日志里出现过的最大 `seq`（没有日志 / 全是空行时是 0）。

        为什么单独一个函数而不是内联在 `_next_seq` 里：`rebuild` 与 `verify`
        都可能面对"手改过 / 旧格式"的日志，任何非整数的 `seq` 只该被当作
        "这一行没有可用序号"（记 0），而不该让一次追加或一次重建崩在 `int()` 上。
        `read_events` 早就承诺"坏行不中断重建"，序号提取必须守同一条承诺。
        """
        high = 0
        for e in self.read_events():
            try:
                n = int(e.get("seq", 0) or 0)
            except (TypeError, ValueError):
                continue
            high = max(high, n)
        return high

    def read_events(self) -> list[dict]:
        out = []
        if not self.events_path.exists():
            return out
        with open(self.events_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # 半行（崩溃时可能产生）——记录但不中断重建
                    out.append({"seq": i, "op": "corrupt", "raw": line[:200]})
        return out

    def rebuild(self, backup: bool = True) -> dict:
        """从 events.jsonl 重建全部快照。

        因为事件里存的是整行 upsert，折叠逻辑就是"按主键 last-write-wins"。
        `## `F-1`：只重放完整批次，并在写者锁内整个做完：旧版逐条重放，于是"崩在快照与事件之间"的那一次提交会`
        不报错地消失（实测：快照 2 行 / counters=2 ⇒ rebuild 后 1 行 / counters=1）。现在两条判据：完整批次才算数
        ——一批事件后面必须跟一条 `op="commit"` 的标记（`_append_events` 写）；没有标记的那一批整批跳过，并把跳过
        数报出来（`batches_incomplete`）；历史事件没有 `batch` 字段 ⇒ 当作完整批次（理由见 `_append_events`）。
        整个重建在一把写者锁内（`G-12`）：只保证写者之间互斥，它不排除并发读者读到中间态 —— 读侧今天不拿这把
        锁（`R3-1` 的口径裁决：接受现状，只把措辞改成事实）。
        返回值新增三个计数：`batches_applied` / `batches_incomplete` / `events_replayed`；旧调用方只看 `applied` /
        `skipped` / `counters`，那三个键原样保留。另有四个"必须能看见"的键：`legacy_events_without_version`
        （`F-7`，没有版本号的老事件条数）、`corrupt_events`（`I-5` / `R3-4`，日志里坏掉的行的条数 —— 旧版把这件事
        吞在 `read_events` 的 `corrupt` 占位里，"没抛异常"被读成"日志是好的"）、`snapshot_rows_not_in_log` 与
        `snapshot_ahead`（`R3-3`：快照里有、日志里从来没有过的行数与逐表明细）。
        `## `R3-3`：为什么必须比对快照与日志（而不只是看提交标记）`：上面两条都只问"日志里有没有问题"，而重建的
        输入是日志、输出会整表覆盖快照 ⇒ 另一类偏离是"快照超前于日志"：正常提交后手工往 `<表>.json` 加一行
        （日志无痕），旧版返回 `applied=1 / batches_incomplete=0`，那一行被静默丢掉而计数为 0 —— 于是
        "`batches_incomplete == 0`"被读成"库里没有丢过提交"，而那是错的。现在返回 `snapshot_rows_not_in_log`
        （差集行数）与 `snapshot_ahead`（`{表名: [主键, …]}`）；它不会让重建失败（重建是灾难恢复手段，不能因为它
        要修的东西而拒绝工作），但"这次会丢多少已有数据"从此在报告里看得见。口径：只算"快照有、日志没有"这一个方向；反方向（日志有、快照没有，例如删行）是正常形态，不在这里报 —— 删行不进事件日志是重建的已知边界，见 `F-9`。
        `## `F-9`（第 3 条）：这条"不丢信息"的承诺有边界`：折叠时是"合并而非替换"——事件行里带了的非 schema 键
        （`_keys`、`_quote_check` 这类诊断字段）会被保留下来，这一半是成立的。但重建的唯一输入是事件日志：一个键
        若只存在于快照、从未进过任何事件（例如有人手工往 `<表>.json` 里加了一个诊断字段），重建后它不在了。这
        不是缺陷，而是"从日志重建"的定义 —— 但它必须被写下来，否则"rebuild 什么都不丢"会被读成无条件的事实，
        而 `F-7` 那类"只改快照"的偏离会因此显得无害。
        """
        try:
            with self._writer_lock(timeout=120.0):
                return self._rebuild_locked(backup=backup)
        except Timeout as e:
            raise StoreError(
                "获取写者锁超时（rebuild）。可能有另一个进程正在写这个工作区；"
                "若进程已死，锁文件是可安全删除的（filelock 用 OS 锁，不含内容）。"
            ) from e

    def _snapshot_keys(self) -> dict[str, set[str]]:
        """各表当前快照里的主键集合（`R3-3` 的输入）。

        为什么读不出来就跳过这张表、而不是抛：`rebuild` 的典型调用场景恰恰是
        "快照坏了"（半截 JSON、版本不符、手工改坏）。在这里抛等于让
        "重建"这个灾难恢复手段在最需要它的时候失败。跳过的那张表不会进
        `snapshot_rows_not_in_log` 的分母 —— 于是这个计数只会少报、不会误报，
        方向与 `R3-3` 的"宁可如实说看不见"一致。
        """
        out: dict[str, set[str]] = {}
        for table, spec in S.TABLES.items():
            p = self.data / spec["file"]
            if not p.exists():
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rows = doc.get("rows")
            if not isinstance(rows, list):
                continue
            idf = spec["id_field"]
            out[table] = {str(r.get(idf)) for r in rows
                          if isinstance(r, dict) and r.get(idf) is not None}
        return out

    @property
    def migration_ledger_path(self) -> Path:
        """逐条改号账（append-only，一行一件事）：`out/migrate-map.jsonl`。

        为什么放在 `out/` 而不是 `data/`：它是一份报告（"这次迁移把哪个号改成了
        哪个号、为什么"），不是数据库的一部分 —— 放进 `data/` 会让"哪些文件是表"
        这件事多出一个例外，而 `verify` / `rebuild` / 备份三处都要认得那个例外。
        """
        return self.root / "out" / "migrate-map.jsonl"

    def _write_migration_ledger(self, lines: list[dict]) -> None:
        """把改号账逐行 append 到 `out/migrate-map.jsonl`（`migrate_concepts.ledger_lines`）。"""
        if not lines:
            return
        p = self.migration_ledger_path
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            for rec in lines:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def _fold_moved_tables(self, *, state: dict, order: dict, counters: dict,
                           moved_rows: Mapping[str, dict], moved_order: list[str]) -> dict:
        """把并走的表折进新家（S1r 并表那一笔的执行点）。

        口径（全部由 `migrate_concepts` 一处决定，这里只做"接上"）：
        - 号由同一分配器重发：从 `stmt` 计数器续着发、跳过既有命题号（`counter_alloc(start, taken=既有 stmt_id)`）
          —— 业主 D2「同表同分配器不可能撞号」；真盘实测有 22 条概念号与既有命题号撞上，不重发就会静默顶掉那些行；
        - 关系改号：`relations.concept_ids` 里的旧号换成新号，逐条落账；
        - 计数器续着走：折完之后 `stmt` 计数器必须 ≥ 新用到的号 + 1，否则 `verify` 的 `counter_behind` 会报
          "继续分配会撞号"；
        - `counters` 里那份 `concept` 残留删掉（表已退役，留着就是一个没有表的类别 —— 无害，但不是"并干净"）。
        返回读数（全部进 `rebuild` 的返回值，读的人必须看得见这次折了什么）。
        """
        rows = [moved_rows[k] for k in dict.fromkeys(moved_order) if k in moved_rows]
        taken = {str(k) for k in state["statements"]}
        start = int(counters.get("stmt", 0) or 0)
        for key in taken:
            if str(key).isdigit():
                start = max(start, int(key) + 1)
        plan = MC.plan_migration(rows, list(state["relations"].values()),
                                 existing_stmt_ids=taken,
                                 alloc=MC.counter_alloc(start, taken=taken))
        for row in plan["statements"]:
            sid = str(row.get("stmt_id") or "")
            if not sid:
                continue
            if sid not in state["statements"]:
                order["statements"].append(sid)
            state["statements"][sid] = row
        rel_idf = S.TABLES["relations"]["id_field"]
        for rel in plan["relations"]:
            rid = str(rel.get(rel_idf) or "")
            cur = state["relations"].get(rid)
            if cur is None:
                continue
            # 改号要连带把派生字段搬过来（`concept_group_key` / `dedup_key`）：
            # 只搬 `concept_ids` 的话，`verify` 的 `stale_group_key`（错误级，
            # 判的是 `concept_group_key == textutil.concept_group_key(concept_ids)`）
            # 会当场报出来 —— 迁移出来的库自己带着一条"判重会失效"。
            # 这两个键由 `migrate_concepts.remap_concept_ids` 按唯一实现重算。
            for key in ("concept_ids", "concept_group_key", "dedup_key"):
                if key in rel and rel.get(key) != cur.get(key):
                    cur[key] = rel.get(key)
        newest = int(counters.get("stmt", 0) or 0)
        for row in plan["statements"]:
            sid = str(row.get("stmt_id") or "")
            if sid.isdigit():
                newest = max(newest, int(sid) + 1)
        counters["stmt"] = newest
        counters.pop("concept", None)
        lines = MC.ledger_lines(plan)
        return {"concepts": len(plan["statements"]),
                "relations_renumbered": len(plan["changed"]),
                "pending_search": int(plan["counts"].get("pending_search", 0) or 0),
                "ledger_lines": len(lines), "ledger_lines_data": lines,
                "notes": list(plan["notes"])}

    def _moved_snapshot_ids(self, table: str) -> set[str]:
        """并走的那张表在老快照（`data/concepts.json`）里的主键集合。

        为什么必须在删老文件之前读它：`rebuild` 的唯一输入是事件日志（`F-9` 的边界），
        于是"快照里有、日志里从来没有过"的行不会被折进去。对普通表，这件事由
        `snapshot_ahead` 如实报出、数据留在原文件里；而对并走的表，老文件紧接着
        会被删掉 —— 如果不先把这份差集算出来，那些行就是"报都没报就没了"。
        读不出来（文件不在、坏了、版本不符）⇒ 返回空集，但要与"读到了、里面是空的"
        分得开：调用方据 `file` 那一路读数判断（见 `_remove_stale_moved_files`）。
        """
        meta = _MOVED_TABLES.get(table) or {}
        path = self.data / str(meta.get("file") or f"{table}.json")
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        rows = doc.get("rows")
        if not isinstance(rows, list):
            return set()
        field = str(meta.get("id_field") or "")
        return {str(r.get(field)) for r in rows
                if isinstance(r, Mapping) and r.get(field) is not None}

    def _remove_stale_moved_files(self, *, allow: bool,
                                  snapshot_ahead: Iterable[str] = ()) -> dict[str, list[str]]:
        """删掉并走的表留下的老文件（`data/concepts.json`），返回 `{removed, kept}`。

        `allow=False`（`rebuild(backup=False)`）时不删 —— 那一支没有备份，
        删掉就是不可逆的数据销毁；此时如实报 `kept`（"老文件还在，它装着迁移前
        的旧值"），而不是假装干净。

        `snapshot_ahead` 非空时同样不删：那些行只存在于老快照里、事件日志里
        从来没有过（`F-9` 的已知边界）⇒ 删掉它们等于把"日志漏掉的那一段"的唯一
        副本销毁。宁可留一个"看起来还是数据库"的文件（它会被
        `conceptrows.legacy_present` 点名成 `stale_file`），也不做不可逆的事。
        """
        out: dict[str, list[str]] = {"removed": [], "kept": []}
        ahead = {str(x) for x in snapshot_ahead}
        for name, meta in _MOVED_TABLES.items():
            p = self.data / str(meta.get("file") or f"{name}.json")
            try:
                if not p.is_file():
                    continue
            except OSError:
                continue
            if not allow or ahead:
                out["kept"].append(p.name)
                continue
            try:
                p.unlink()
                out["removed"].append(p.name)
            except OSError:
                out["kept"].append(p.name)
        return out

    def _rebuild_locked(self, *, backup: bool = True) -> dict:
        # `R3-3`（重审实测）：快照必须与日志比对，不能只看 `op=commit` 标记。
        #
        # 缺陷形态：正常提交之后手工往 `<表>.json` 多塞一行（日志无痕）⇒ 旧版
        # `rebuild` 返回 `{'applied': 1, 'batches_applied': 1, 'batches_incomplete': 0, …}`，
        # 那一行被静默丢掉而计数为 0 —— 也就是"快照超前于日志"（旧顺序
        # 先快照后事件留下的真实缺陷形态）在改后既不报错也不报数。
        # 于是"`batches_incomplete == 0`"被读成"库里没有丢过提交"，而那是错的。
        #
        # 快照必须在被覆盖之前读：下面这一段会把每张表整个重写。
        snapshot_before = self._snapshot_keys()
        if backup:
            bdir = self.data / f".backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            bdir.mkdir(parents=True, exist_ok=True)
            for spec in S.TABLES.values():
                src = self.data / spec["file"]
                if src.exists():
                    shutil.copy2(src, bdir / spec["file"])
            # 并走的表的老文件也必须进备份：下一步（折完之后）它会被删掉，
            # 而"删一个不在 TABLES 里的文件"如果没进备份就是不可逆的数据销毁。
            for meta in _MOVED_TABLES.values():
                src = self.data / str(meta.get("file") or "")
                if src.name and src.exists():
                    shutil.copy2(src, bdir / src.name)
            if (self.data / "counters.json").exists():
                shutil.copy2(self.data / "counters.json", bdir / "counters.json")

        events = self.read_events()
        # `F-7`（人裁 = fail-closed）落在事件流上的口径，与读快照故意不同，
        # 理由必须写清（否则这条判据会变成"把历史数据一律拒掉"）：
        #   - 事件里写了版本号且与当前不符 ⇒ 拒（拿旧语义重放会静默改写快照）；
        #   - 事件里没有版本号 ⇒ 视作"加版本号之前写下的历史事件"，照常重放，
        #     并把条数报进返回值（`legacy_events_without_version`）——
        #     这是 `_append_events` 对 `batch` 字段的同一条兼容口径，
        #     也是全部既有夹具（以及真实历史库）的形态；把它也拒掉等于
        #     让 `rebuild` 对历史库完全不可用，而 `rebuild` 正是灾难恢复的唯一手段。
        bad_versions = sorted({repr(e.get("schema_version")) for e in events
                               if "schema_version" in e
                               and e.get("schema_version") != S.SCHEMA_VERSION
                               and e.get("op") != "corrupt"})
        # S1r 并表那一笔（`SCHEMA_VERSION=2`）：上一版的事件不再算"版本不符"。
        # 口径与理由：v1 与 v2 的差别只有一处（`concepts` 折进 `statements`），
        # 而折叠规则是确定性的纯函数（`migrate_concepts`）⇒ 拿 v1 事件重放再折一次
        # 得到的快照与"当年就用 v2 写"应当一致。把它也拒掉的话，63 个真实工作区
        # 的灾难恢复手段（`rebuild` 是唯一的那个）会在一夜之间对历史库完全不可用 ——
        # 那是比"迁移"更坏的形态。读期仍然 fail-closed（`F-7` 人裁不变）：
        # 兼容只存在于这一条路径上，且它必须把"折了多少"报出来（`migrated_v1_events`）。
        known_old = (S.SCHEMA_VERSION - 1,)
        bad_versions = [v for v in bad_versions
                        if v not in {repr(x) for x in known_old}]
        if bad_versions:
            raise StoreError(
                "events.jsonl 的 schema_version 与当前不符（盘上出现 "
                f"{bad_versions}，期望 {S.SCHEMA_VERSION!r}；"
                f"已知旧版 {list(known_old)!r} 会被折叠，不算不符）⇒ **拒绝重建**（`F-7`）："
                "拿旧语义的事件重放会静默改写快照。处置：确认以哪一版为准 ⇒ "
                "必要时先做一次显式迁移，再 rebuild。"
            )
        # S1r：这一批事件里有多少条是上一版写的（它们要被折叠，必须报出来）。
        migrated_v1_events = sum(1 for e in events
                                 if e.get("op") != "corrupt"
                                 and e.get("schema_version") in known_old)
        legacy_no_version = sum(1 for e in events
                                if "schema_version" not in e and e.get("op") != "corrupt")
        # `I-5`（登记在 `draft/28`）：坏行必须被计数，不能只是"没抛异常"。
        # 旧返回值里有 `skipped`，但它的语义是"没进 state 的行"，而坏行根本
        # 进不了 `replay` ⇒ 一条恒真的断言（`skipped >= 0`）就能蒙混过关，
        # 而"日志里有几行坏了"这个事实在报告里看不见。
        corrupt_events = sum(1 for e in events if e.get("op") == "corrupt")
        # ---- 先算出"哪些批次是完整的"
        committed: set[str] = set()
        for e in events:
            if e.get("op") == "commit" and e.get("batch"):
                committed.add(str(e["batch"]))
        replay: list[dict] = []
        batches_seen: set[str] = set()
        batches_incomplete: set[str] = set()
        for e in events:
            b = e.get("batch")
            if b is None:
                replay.append(e)  # 历史事件：没有批次概念 ⇒ 一律算完整
                continue
            b = str(b)
            batches_seen.add(b)
            if b in committed:
                replay.append(e)
            else:
                batches_incomplete.add(b)

        state: dict[str, dict[str, dict]] = {t: {} for t in S.TABLES}
        order: dict[str, list[str]] = {t: [] for t in S.TABLES}
        counters: dict[str, int] = {}
        applied = skipped = 0
        #: `R-06`：`skipped` 是那个整数（既有读数与三处测试直接断言它，不许改名/改类型），
        #: 这里再补两份明细 —— 只报"跳过了 3 行"读不出下一步该做什么：
        #: 是"这一行本来就不合法"（`schema_rejected`）、还是"事件行的形状坏了"
        #: （`shape_broken`）、还是"这张表我根本不认识"（`unrecognized_table`）。
        #: 为什么不是收窄 `except`：`row_from_dict` 对缺必填字段的行抛的是 `TypeError`
        #: （dataclass 的形态），只接 `ValueError` 会把这类行直接炸出重建 —— 那是
        #: 比"静默跳过"更坏的中间态（`46-01 §2.2(b)` 判"收窄不可行"）。
        skipped_by_reason: dict[str, int] = {}
        skipped_details: list[dict] = []
        #: `R-57`：重放里真的删掉了几行（与 `applied` 分开报 —— `applied` 的历史含义是
        #: "写下了几行"，把删除混进去会让既有读数变味）。
        deleted_replayed = 0
        #: 认不出的 `op`（既不重放、也不在已知的非重放集合里）。它必须出现在返回值里：
        #: 静默忽略一个不认识的 op = "日志里有我读不懂的东西"这件事没有任何人看得见。
        unknown_ops: set[str] = set()
        #: S1r：并走的表（`_MOVED_TABLES`）在 v1 事件里的原始行。它们不在 `state` 里
        #: （`state` 只按当前 `TABLES` 建），所以单独收一份：这一批事件重放完之后
        #: 由 `_fold_moved_tables` 折进新家。不单独收的话，那些行会落进
        #: `unrecognized_table` 的 `skipped` —— 于是"旧库里的概念"以"跳过了 N 行"
        #: 的形式被静默丢掉，而返回值看起来完全正常。
        moved_rows: dict[str, dict[str, dict[str, Any]]] = {t: {} for t in _MOVED_TABLES}
        moved_order: dict[str, list[str]] = {t: [] for t in _MOVED_TABLES}
        moved_deleted: dict[str, int] = {t: 0 for t in _MOVED_TABLES}

        # `R3-3`：这次重放真的写下了哪些主键（逐表）。用它去减快照里已有的键，
        # 差集就是"快照里有、日志里没有"的行 —— 那是这次重建会静默丢掉的数据。
        logged_keys: dict[str, set[str]] = {}
        for e in replay:
            if e.get("op") != "upsert":
                continue
            table = e.get("table")
            if table not in S.TABLES:
                continue
            row = e.get("row") or {}
            idf = S.TABLES[table]["id_field"]
            key = row.get(idf)
            if key is not None:
                logged_keys.setdefault(table, set()).add(str(key))
        snapshot_ahead: dict[str, list[str]] = {
            t: sorted(keys - logged_keys.get(t, set()))
            for t, keys in snapshot_before.items()
            if keys - logged_keys.get(t, set())
        }
        snapshot_rows_not_in_log = sum(len(v) for v in snapshot_ahead.values())

        # `R-06`：跳过一次就要留两份明细（`skipped` 那个整数照旧 +1）。
        def _skip(reason: str, *, table: str = "", row: Any = None,
                  error: str = "", event_index: int | None = None) -> None:
            """记一次"这一行没进 state"：整数、按原因计数、逐条明细三者同时更新。"""
            nonlocal skipped
            skipped += 1
            skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
            rid = ""
            if isinstance(row, Mapping) and table in S.TABLES:
                rid = str(row.get(S.TABLES[table]["id_field"]) or "")
            skipped_details.append({"table": table, "id": rid, "reason": reason,
                                    "error": error, "event_index": event_index})

        for event_index, e in enumerate(replay):
            op = e.get("op")
            if op == "delete":
                # `R-57`：删除也必须重放。只按 `key` 删（不校验 `row`）：
                # 被删的历史行可能不符合当前 schema，拿它去 `row_from_dict` 会让
                # 重建因为一条历史删除而整批失败 —— 而这条事件的全部语义就是"这一行没了"。
                dtable = e.get("table")
                if dtable == "counters":
                    continue  # counters 没有"删一行"这回事（它的值由 alloc 事件折叠）
                if dtable in _MOVED_TABLES:
                    # 并走的表：删那一行也要算数（否则"删了又被折回来"）
                    mrow = e.get("row") or {}
                    mkey = e.get("key")
                    if mkey is None:
                        mkey = mrow.get(_MOVED_TABLES[dtable]["id_field"])
                    if mkey is not None:
                        moved_rows[dtable].pop(str(mkey), None)
                        moved_deleted[dtable] += 1
                    continue
                if dtable not in S.TABLES:
                    _skip("unrecognized_table", table=str(dtable), event_index=event_index)
                    continue
                dkey = e.get("key")
                if dkey is None:
                    # 老格式/手写的删除事件没有 `key` ⇒ 从 `row` 里取主键；再取不到就不猜
                    drow = e.get("row") or {}
                    dkey = drow.get(S.TABLES[dtable]["id_field"])
                if dkey is None:
                    _skip("missing_key", table=str(dtable), row=e.get("row"),
                          event_index=event_index)
                    continue
                if str(dkey) in state[dtable]:
                    del state[dtable][str(dkey)]
                    deleted_replayed += 1
                continue
            if op != "upsert":
                if op not in _KNOWN_NON_REPLAY_OPS:
                    unknown_ops.add(str(op))
                continue
            table = e.get("table")
            row = e.get("row") or {}
            if table == "counters":
                kind = row.get("kind")
                alloc = row.get("allocated")
                if kind and alloc is not None:
                    # 2026-10-17（store #13）：重放别的坏行有 `_skip()` 兜着，这一支裸 `int()`。
                    try:
                        _n = int(alloc) + 1
                    except (TypeError, ValueError):
                        _n = counters.get(kind, 0)
                    counters[kind] = max(counters.get(kind, 0), _n)
                applied += 1
                continue
            if table in _MOVED_TABLES:
                # 并走的表在 v1 事件里的 upsert：收进 `moved_rows`，不在这里校验
                # （老行的 schema 与当前不再是同一套 —— 它要按 `migrate_concepts`
                # 的折叠口径变形成新行，拿新 schema 去校验它是本末倒置：
                # 一条老概念行里没有 `kind`/`stmt_id`，校验必然失败，
                # 于是"旧库里的概念"会被读成"坏行"）。
                mkey = str(row.get(_MOVED_TABLES[table]["id_field"]) or "")
                if not mkey:
                    _skip("missing_key", table=str(table), row=row, event_index=event_index)
                    continue
                if mkey not in moved_rows[table]:
                    moved_order[table].append(mkey)
                moved_rows[table][mkey] = dict(row)
                applied += 1
                continue
            if table not in S.TABLES:
                _skip("unrecognized_table", table=str(table), row=row, event_index=event_index)
                continue
            try:
                obj = S.row_from_dict(table, row)
                obj.validate()
            except ValueError as e:
                # 形状对、值不合法（`validate()` 的那一族）⇒ 这一行本来就不合法。
                _skip("schema_rejected", table=str(table), row=row,
                      error=f"{type(e).__name__}: {e}", event_index=event_index)
                continue
            except Exception as e:
                # 其余（`row_from_dict` 的缺参 `TypeError`、意外的形态坏）⇒ 事件行坏了。
                # 不许把它并进 `schema_rejected`：两者的处置不同（前者改数据、
                # 后者查是谁写坏了事件），而合并之后这条读数就再也分不出来了。
                _skip("shape_broken", table=str(table), row=row,
                      error=f"{type(e).__name__}: {e}", event_index=event_index)
                continue
            key = getattr(obj, S.TABLES[table]["id_field"])
            if key not in state[table]:
                order[table].append(key)
            # 合并而非替换：schema 字段用校验后的规范值，其它键（`_keys`、
            # `_quote_check` 这类诊断/扩展字段）原样保留。
            # 早先这里只存 obj，导致 rebuild 后诊断字段全部丢失 —— 虽然判重靠
            # `doi`/`dedup_key` 兜底仍然可用，但"能重建"就不该"重建出更少的信息"。
            #
            # `F-9`（第 3 条）把这条承诺的边界写清，因为它原先写成了无条件的
            # "诊断字段不丢"：保留的是事件行里带了的非 schema 键。
            # 一个键若只存在于快照、而从未进过任何事件（例如有人手工往
            # `<表>.json` 里加了一个诊断字段），重建后它不在了 ——
            # 重建的唯一输入是事件日志，快照里没进过日志的东西无从恢复。
            # 这不是缺陷而是"重建"的定义，但读 docstring 的人有资格知道它。
            canonical = obj.to_dict()
            merged = {k: v for k, v in row.items() if k not in canonical}
            merged.update(canonical)
            state[table][key] = merged
            applied += 1

        # ---- S1r：把并走的表折进新家（`_MOVED_TABLES`）
        #
        # 这一步就是"并干净"的执行点：v1 事件里的概念行在 `moved_rows` 里等着，
        # 这里按 `migrate_concepts` 那一套确定的折叠口径把它们变成 `statements` 的行，
        # 号由同一分配器重发（从 `stmt` 计数器续着发、撞既有命题号往后跳），
        # 关系表里挂着的旧概念号同步改写，逐条改号账落到 `out/migrate-map.jsonl`。
        #
        # 为什么折叠内核在 `migrate_concepts` 而不是这里：`rebuild` 是 FC-27 禁改区
        # 的写入路径，而折叠规则本身是纯数据变换 —— 把它单独放一处，判据可以直接喂
        # 夹具（不需要真工作区、不需要跑一次迁移），这里只留"读事件 → 折 → 写快照"。
        # 真盘预演（`temp/_s1r_plan_readings.py`）与这里共用同一套内核 ⇒
        # "预演说会改成什么"与"真跑改成了什么"不可能分家。
        folded: dict[str, Any] = {"concepts": 0, "relations_renumbered": 0,
                                  "pending_search": 0, "ledger_lines": 0,
                                  "notes": []}
        moved_table = "concepts" if moved_rows.get("concepts") else ""
        if moved_table:
            folded = self._fold_moved_tables(state=state, order=order, counters=counters,
                                             moved_rows=moved_rows[moved_table],
                                             moved_order=moved_order[moved_table])
            self._write_migration_ledger(folded.get("ledger_lines_data") or [])
        #: 老快照里、而事件日志里从来没有过的概念号（`F-9` 的边界落在并走的表上）。
        #: 这一份必须在删老文件之前算出来 —— 见 `_moved_snapshot_ids` 的 docstring。
        moved_snapshot_ahead: dict[str, list[str]] = {}
        for _old in _MOVED_TABLES:
            snap = self._moved_snapshot_ids(_old)
            if not snap:
                continue
            ahead = sorted(snap - set(moved_rows.get(_old, {})))
            if ahead:
                moved_snapshot_ahead[_old] = ahead
        #: 老文件（`data/concepts.json`）在并走之后必须消失：留着一个"看起来还是
        #: 数据库"的老文件，下一次有人直接读它就会拿到迁移前的旧值，而这件事没有任何
        #: 自动判据看得见（`conceptrows.legacy_present` 只在读的时候点名 `stale_file`）。
        #: 备份已经在上面那一支里做过了（`_MOVED_TABLES` 的文件也进备份目录）；
        #: `backup=False` 那一支没有备份 ⇒ 不删，如实报 `kept`；
        #: 事件日志里没有的那些行（`moved_snapshot_ahead`）⇒ 同样不删（不可逆）。
        stale = self._remove_stale_moved_files(
            allow=bool(backup),
            snapshot_ahead=[x for v in moved_snapshot_ahead.values() for x in v])
        folded["stale_files_removed"] = list(stale["removed"])
        folded["stale_files_kept"] = list(stale["kept"])
        # 并走的那些类别也从计数器里摘掉（`_fold_moved_tables` 里摘过一次，这里再兜一次：
        # 事件流里一条概念 upsert 都没有、而 `counters.json` 里还留着 `concept: N` 的库
        # 也应当并干净）。表没了而类别还在不会让 `verify` 报错（它只遍历 `ID_COUNTERS`），
        # 但那是一份"指向不存在的表"的残留 —— 留着它，下一次有人按 counters 反推表结构
        # 就会推出一张不存在的表。
        for _old in _MOVED_TABLES:
            counters.pop(str(_old), None)
            counters.pop(str(_MOVED_TABLES[_old].get("counter_kind") or ""), None)

        for table in S.TABLES:
            # `R-57`：`order` 里可能留着被删掉的键（删除只从 `state` 里摘）⇒
            # 这里过滤一次，而不是在删除时对列表做手术（保持"首次插入顺序"稳定，
            # 也避免 `del` 与 `append` 在同一轮里互相错位）。
            #  还要去重：删掉之后又 upsert 同一个主键时，`order` 会追加第二次
            # （`key not in state` 成立）⇒ 不去重就会拼出两行同 ID，而 `validate_table`
            # 会以 `ValueError: 出现重复 ID` 报出来（本仓自己的测试当场抓到了这一点：
            # `tests/test_store_delete_events.py::test_order_inside_one_transaction_is_the_call_order`）。
            # `dict.fromkeys` 保序去重，语义就是"这个主键第一次出现的位置"。
            rows = [state[table][k] for k in dict.fromkeys(order[table]) if k in state[table]]
            doc = {"schema_version": S.SCHEMA_VERSION, "rows": rows}
            S.validate_table(table, doc)
            self._atomic_write(self.data / S.TABLES[table]["file"], doc)
        self._atomic_write(self.data / "counters.json", {"schema_version": S.SCHEMA_VERSION, "counters": counters})
        return {
            "applied": applied,
            "skipped": skipped,
            # `R-06`：`skipped` 只说"跳了几行"，说不出"为什么跳"。两份明细把
            # "重建成功"这个假的第三态拆开：`skipped_by_reason` 给分类计数、
            # `skipped_details` 给逐条（表 / 主键 / 原因 / 原话 / 事件下标）——
            # 没有它，"skipped=3" 与 "skipped=0" 的差别就只是三个数字，
            # 而人拿到三个数字之后仍然不知道该去查什么。
            "skipped_by_reason": dict(sorted(skipped_by_reason.items())),
            "skipped_details": skipped_details,
            "counters": counters,
            # 下面三个是 `F-1` 新增的"读的人必须能看见"的计数：
            # 一个不完整的批次意味着丢掉了一次提交，那件事绝不能只体现在行数上。
            "batches_applied": len(batches_seen - batches_incomplete),
            "batches_incomplete": len(batches_incomplete),
            "events_replayed": len(replay),
            # `F-7`：这一批事件里有多少条没有版本号（加版本号之前写下的）。
            # 它们照常重放，但读报告的人必须知道"这次重放里有 N 条是老格式"。
            "legacy_events_without_version": legacy_no_version,
            # S1r：这一批事件里有多少条是上一版（`SCHEMA_VERSION-1`）写的。
            # 它们被折叠而不是被拒 —— "折叠了多少"必须看得见，否则"重建成功"
            # 与"重建成功但折了一堆行"在返回值里同形。
            "migrated_v1_events": migrated_v1_events,
            # S1r：这次折叠的读数（并走的表 → 新家）。
            # `migrated_concepts` 是折出来的新行数；`migrated_relations_renumbered`
            # 是改号的关系条数；`migrated_pending_search` 是定义待补的条数；
            # `migration_ledger_lines` 是逐条改号账的行数（写在 `out/migrate-map.jsonl`）；
            # `migrated_notes` 是"合并痕迹 / 空定义 / 丢弃 normalized_name"这些点名。
            "migrated_concepts": int(folded.get("concepts", 0) or 0),
            "migrated_relations_renumbered": int(folded.get("relations_renumbered", 0) or 0),
            "migrated_pending_search": int(folded.get("pending_search", 0) or 0),
            "migration_ledger_lines": int(folded.get("ledger_lines", 0) or 0),
            "migrated_notes": list(folded.get("notes") or []),
            # 并走之后老文件的下场：`removed` 是删掉的（`backup=True`），
            # `kept` 是没删的（`backup=False` 没有备份 ⇒ 不销毁数据）。
            # 两个都要报：只报 removed 的话，"老文件还在"这件事看不见。
            "moved_stale_files_removed": list(folded.get("stale_files_removed") or []),
            "moved_stale_files_kept": list(folded.get("stale_files_kept") or []),
            # S1r：老快照里、而事件日志里从来没有过的概念号（逐表列出）。
            # 非空 ⇒ 老文件不删（`moved_stale_files_kept` 里会看到它）：
            # 那些行只存在于那份快照里，删掉就是不可逆的数据销毁。
            "moved_snapshot_ahead": {t: v for t, v in sorted(moved_snapshot_ahead.items())},
            # `I-5`：`events.jsonl` 里有几行坏了（半行 JSON / 不是 JSON）。
            # 旧版把这件事吞在 `read_events` 的 `corrupt` 占位里，
            # 返回值里看不见 ⇒ "没抛异常"被误读成"日志是好的"。
            "corrupt_events": corrupt_events,
            # `R3-3`：快照里有、而日志里从来没有过的行数（逐表明细在下一个键里）。
            # 为什么会发生：旧顺序（先快照后事件）崩在两者之间、或有人手工往
            # `<表>.json` 里加行。这些行本次重建不会出现在结果里（重建的唯一
            # 输入是日志），而旧版对这件事一个字都不说 —— 于是
            # "`batches_incomplete == 0`"被读成"库里没丢过提交"。
            # 方向：它只多不少地报"这次会丢多少已有数据"，读报告的人据此判断
            # 该不该先修日志再重建。
            "snapshot_rows_not_in_log": snapshot_rows_not_in_log,
            # 逐表明细（只有差集非空的表才在里面）：人排查时需要知道是哪张表，
            # 而不只是一个总数。
            "snapshot_ahead": {t: v for t, v in sorted(snapshot_ahead.items())},
            # `R-57`：这次重放里真的删掉了几行（删除事件是被算进重放的）。
            # 它与 `applied`（写下了几行）分开报：把两者混起来，"重建之后库里比删之前多"
            # 这件事就看不出来了 —— 而那正是 R-57 的原始形态。
            "deletes_replayed": deleted_replayed,
            # 认不出的 `op`：不重放，但必须被看见（静默忽略一个不认识的 op
            # 等于"日志里有读不懂的东西"没有任何读数）。
            "unknown_ops": sorted(unknown_ops),
        }

    # ---------------------------------------------------------------- 路径工具
    def library_path(self, rel: str | None) -> Path | None:
        """把表里的相对路径解析为绝对路径，并强制它仍在 library/ 内。

        这是防路径穿越的最后一道闸：即使有人手工把 `path` 改成 `../../etc/passwd`，
        这里也会拒绝，而不是去读那个文件。
        """
        if not rel:
            return None
        candidate = (self.library / rel).resolve()
        try:
            candidate.relative_to(self.library.resolve())
        except ValueError:
            raise StoreError(f"文献路径越出 library/：{rel!r}")
        return candidate

    def stats(self) -> dict:
        out: dict[str, Any] = {"root": str(self.root)}
        for t, spec in S.TABLES.items():
            rows = self.rows(t)
            out[t] = {"count": len(rows)}
            if t == "search_requests":
                out[t]["done"] = sum(1 for r in rows if r.get("done"))
                out[t]["pending"] = sum(1 for r in rows if not r.get("done"))
            if t == "literature":
                out[t]["processed"] = sum(1 for r in rows if r.get("processed"))
                out[t]["downloaded"] = sum(1 for r in rows if r.get("path"))
            if t == "relations":
                by_status: dict[str, int] = {}
                for r in rows:
                    by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
                out[t]["by_status"] = by_status
                out[t]["quote_verified"] = sum(1 for r in rows if r.get("quote_verified") is True)
                out[t]["quote_unverified"] = sum(1 for r in rows if r.get("quote_verified") is False)
                out[t]["quote_unknown"] = sum(1 for r in rows if r.get("quote_verified") is None)
        out["events"] = {"appended": len(self.read_events())}
        return out
