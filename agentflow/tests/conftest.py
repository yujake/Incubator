"""公共 fixture 与构造工具。

设计约束：
- 所有测试都在 ``tmp_path`` 下自建工作区，绝不碰 ``test/test1/data/``
  或 ``test/test1/demo/run/``（那是演示数据，必须保持干净）。
- 只通过 ``sys.path`` 注入 ``src/``，不要求安装包。
- 时间戳一律写死为常量，避免测试依赖"当前时间/时区"。

## 为什么这里要显式钉临时根（`X-2` 的剩余面）

`draft/25` 的 `X-2` 登记过一处残留：仓库根冒出 `pytest-of-unknown/`。读 pytest 9.1.0
的 `TempPathFactory.getbasetemp` 可以看清成因 —— 没有显式 `--basetemp` 时，它算的是

    temproot = Path(os.environ.get("PYTEST_DEBUG_TEMPROOT") or tempfile.gettempdir()).resolve()
    rootdir  = temproot / f"pytest-of-{get_user() or 'unknown'}"

而 `tempfile.gettempdir()` 在没有任何可写临时目录时会退回当前工作目录
（Python 的既有行为，不是 pytest 的 bug）⇒ 这时 basetemp 就落在仓库根；
`PYTEST_DEBUG_TEMPROOT` 若给的是相对路径，`.resolve()` 也会把它解到 cwd。

本文件在导入期把 `PYTEST_DEBUG_TEMPROOT` 钉到一个先验证过可写的绝对路径。
为什么是导入期而不是某个 hook：`getbasetemp()` 是惰性的（第一次用 `tmp_path` 才调用），
而它每次都现读这个环境变量；conftest 的导入早于任何用例执行，所以这个写入一定在它之前生效。
为什么不用 `pytest_load_initial_conftests` 往 args 里插 `--basetemp`（第一版这么写过，
实测不生效：pytest 9.1.0 下 `tests/conftest.py` 的这个 hook 根本没被调用 —— 加了
调试打印也一行都不出）。教训与 `draft/28` 的"装置陷阱"同族：注入要证明它真的生效，
本模块的自测用例（`test_x2_temp_root_is_pinned`）就是钉这件事的。

候选临时根一个都写不了时退回包内固定目录（`.pytest-tmp/`，已在仓库根 `.gitignore` 登记）。
于是"跑一次全量 ⇒ 仓库根不新增目录"这条判据不再依赖环境变量对不对。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

#: 把 src/ 注入 sys.path（src 是 agentflow 的父目录）。
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

#: 包根（`agentflow/`）：临时根全都不可写时的兜底落点就在它下面。
_PROJ = Path(__file__).resolve().parents[1]

#: 关掉钉临时根这一手（只为负控用：让"残留会不会出现"这件事能被观察一次）。
_NO_PIN_ENV = "AGENTFLOW_NO_TEMPROOT_PIN"


def _writable_temp_root() -> Path | None:
    """挑一个真的能写的临时根；一个都没有时返回 None。

    为什么不用 `tempfile.gettempdir()` 当判据：它只回答"我认为哪个目录能当临时目录"，
    在没有可写候选时它自己就退回 cwd，于是"用它再拼一层"并不能躲开那个坑。
    这里的判据是写一个探针文件再删掉。
    """
    candidates = [
        os.environ.get("TMPDIR"),
        os.environ.get("TEMP"),
        os.environ.get("TMP"),
        str(Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp")
        if os.environ.get("USERPROFILE") else "",
        "/tmp",
    ]
    for raw in candidates:
        if not raw:
            continue
        root = Path(raw)
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / f".agentflow-temp-probe-{os.getpid()}"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError:
            continue
        return root
    return None


def _pin_temp_root() -> str:
    """把 `PYTEST_DEBUG_TEMPROOT` 钉成绝对路径；返回这一次钉到的值（空串 = 没钉）。"""
    if os.environ.get(_NO_PIN_ENV):
        return ""
    if os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        return os.environ["PYTEST_DEBUG_TEMPROOT"]
    root = _writable_temp_root()
    target = (root / "agentflow-pytest") if root is not None else (_PROJ / ".pytest-tmp")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ""
    os.environ["PYTEST_DEBUG_TEMPROOT"] = str(target.resolve())
    return os.environ["PYTEST_DEBUG_TEMPROOT"]


PINNED_TEMP_ROOT = _pin_temp_root()

# ---------------------------------------------------------------------------
# 机器级设置与"这台机器上装了东西"类的环境变量：判据一律在"什么都没配"里跑
# ---------------------------------------------------------------------------

#: 关掉设置钉（只为负控用：让"没钉会怎样"这件事能被观察一次）。
_NO_SETTINGS_PIN_ENV = "AGENTFLOW_NO_SETTINGS_PIN"

#: 本机事实类的环境变量：判据不该受"开发者的 shell 里 export 过什么"影响。
#: 逐条与 `agentflow/settings.py` 的档位对应（模型 key 与四档工具链查找里的前两档）。
_MACHINE_ENV_NAMES = (
    "AGENTFLOW_SETTINGS",
    "AGENTFLOW_MODEL_API_KEY",
    "AGENTFLOW_LEAN_BIN",
    "AGENTFLOW_COQ_BIN",
    "AGENTFLOW_ISABELLE_BIN",
    "AGENTFLOW_PROVER_PATH",
    "AGENTFLOW_MATHLIB_ROOT",
    "AGENTFLOW_PROJECTS_DIR",
)


def _pin_settings_path() -> str:
    """把"设置文件在哪"钉到一个不存在的路径，并清掉本机事实类的环境变量。

    ## 为什么必须有这一手（2026-10-07 全量门的真事故，12 条红全是它）

    机器级设置文件（`agentflow/settings.json`）落地之后，这台机器上真的有那份文件
    （里面有真的 API key 与这台机器的 Lean / Mathlib 落点）。而判据里有一批断言的是
    "没配的时候"的行为：`agentflow run` 没有 key ⇒ 退出码 2 且报 `no_key`、
    `detect_verifier` 报"没装"、"build 期不碰模型"…… 它们在本机那份文件面前全部变红
    （实测：`test_agent_cli` / `test_cli_run` / `test_cli_console_encoding` /
    `test_host_wiring`×3 / `test_formalgw` / `test_tools_audit_fixes`×2 /
    `test_user_quickstart` / `test_user_channel_stop_and_resume` 共 12 条）。

    ## 为什么"把判据改成看环境"是错的答案

    那些判据守的是代码的分支（没配 ⇒ 三态里的"没查成"），不是"这台机器上装了什么"。
    让它们随本机配置变形，等于把"这条分支还在不在"变成一台机器上一个答案 ——
    而 CI 上（没配）与开发机上（配了）会给出不同的结论，绿灯的含义随之漂移。

    ## 所以：判据在确定性环境里跑；要测设置层的判据自己造文件

    `tests/test_settings.py` 用 `monkeypatch.setenv(SET.ENV_SETTINGS, <自己造的>)` ——
    monkeypatch 在用例结束时会把它还原成这里钉的值，两者不冲突。守卫在
    `tests/test_settings.py::test_the_suite_pins_the_machine_settings_away`。
    """
    if os.environ.get(_NO_SETTINGS_PIN_ENV):
        return ""
    for name in _MACHINE_ENV_NAMES[1:]:
        os.environ.pop(name, None)
    base = Path(PINNED_TEMP_ROOT) if PINNED_TEMP_ROOT else _PROJ / ".pytest-tmp"
    target = base / "no-settings.json"
    try:
        target.unlink()          # 上一趟跑剩的会被读成"配了文件" ⇒ 先清掉
    except OSError:
        pass
    os.environ["AGENTFLOW_SETTINGS"] = str(target)
    return str(target)


PINNED_SETTINGS_PATH = _pin_settings_path()

#: 判据套件跑在「Lean 形式化开着」那一档（产品缺省是关的，业主 2026-10-12：
#: 「默认设置中 Lean 关闭帮用户在无严苛要求时省钱」）。
#:
#: ## 为什么套件与产品缺省不同
#:
#: 这一套判据守的是形式化那条路的接线：桥接层（`formalgw` / `verify_tools`）、
#: E 的动作与受控理由、提示词里的"怎么写"那一段、收工门的承重格、`runflow` 的 Lean 段、
#: 以及两份冻结快照里的形式化声明。产品缺省关掉它，只是"默认不烧那笔钱"，
#: 不是"这条路没有了" —— 业主写 `lean_enabled: true` 时全流程必须逐字回到老套路。
#: 若让整批跑在关掉那一档，几百条判据会去测一个"这条路不存在"的世界，
#: 而"开着时逐字不变"这条性质就再没有判据看着了（2026-10-12 实测：翻缺省的那一刻
#: 98 条判据变红，全部落在这一档）。
#:
#: ## 两个方向都有判据
#:
#: `tests/test_lean_switch.py` 自己设置/删除这个环境变量（它按用例显式声明自己测哪一档），
#: 并显式钉住"产品缺省是 `False`"与"设置文件示例里写的是 `false`"这两件事；
#: 本行由 `test_settings.py::test_the_suite_pins_the_lean_switch_on` 守着。
#: 子进程（`python -m agentflow.agent_e` 这类自检）继承 `os.environ`，所以它们也在这条钉上。
os.environ["AGENTFLOW_LEAN_ENABLED"] = "1"

from agentflow import conceptrows as _CR  # noqa: E402  （并表过渡期：夹具也要两处同号）
from agentflow import schema as S  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 逐字节快照要覆盖的数据文件（"回滚后磁盘完全没变"的断言依赖它）。
#: 新增表必须加进来 —— `test_atomic_write_leaves_no_tmp_residue` 会断言
#: data/ 下恰好只有这些文件，漏加会以"多出文件"的形式报错（这正是我们想要的：
#: 防止初始化时悄悄多出意料之外的文件）。
#: S1r 并表（2026-10-10）：改成从 `schema.TABLES` 现推，不再手抄第二份名单 ——
#: 这份名单当年抄了一份，于是 `concepts` 从 `TABLES` 退役之后它还断言着
#: 一个已经不存在的文件（"抄第二份名单"在本仓已经栽过一次，见 `sync_counters`
#: 的 docstring）。顺序按 `TABLES` 的声明序，末尾两个是存储层自己的文件。
DATA_FILES = tuple(spec["file"] for spec in S.TABLES.values()) + ("counters.json", "events.jsonl")

#: 固定时间戳：不依赖当前时间，保证可复现。
TS = "2026-01-01T00:00:00+00:00"


# --------------------------------------------------------------------------- 工具


def read_data_bytes(store: Store) -> dict[str, bytes]:
    """读取所有数据文件的原始字节，用于事务前后逐字节比对。"""
    out: dict[str, bytes] = {}
    for name in DATA_FILES:
        p = store.data / name
        out[name] = p.read_bytes() if p.exists() else b"<absent>"
    return out


def write_library_file(store: Store, rel: str, text: str) -> Path:
    """在 library/ 下写一个素材文件，返回其绝对路径。"""
    p = store.library / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def sync_counters(store: Store) -> None:
    """把 counters.json 对齐到"max(已用 4 位 ID) + 1"。

    verify 会检查 counters 与表内已用 ID 的一致性；测试里手工插行必须同步它，
    否则会引入与"本次要验证的不变量"无关的 ``counter_behind`` 噪音。

    覆盖范围由 `S.ID_COUNTERS` 反查，不在这里另写一张 (kind, table) 表。
    原先这里写死了 3 个 kind（lit/concept/relation），于是新增
    `experiment` / `plan` / `doc` / `dep` / `finding` 五类之后，用本函数同步过的库
    仍会报 counter_behind —— 而报错的内容与测试真正想验证的东西毫无关系，纯属噪音。
    这正是"跨模块约定必须只有一处定义"（FC-03）在测试代码里的形态：
    测试代码也是代码，写死第二份名单同样会漂移。
    S1r 并表之后 `concept` 这一档随表退役（`ID_COUNTERS` 里已经没有它）⇒
    本函数自动不再写那一格，调用方一个字都不用改（这正是"反查"的用处）。
    """
    counters: dict[str, int] = {}
    for kind, field in S.ID_COUNTERS.items():
        table = next((t for t, spec in S.TABLES.items() if spec["id_field"] == field), None)
        if table is None:
            continue
        ids = [int(r[field]) for r in store.rows(table) if field in r]
        counters[kind] = (max(ids) + 1) if ids else 0
    (store.data / "counters.json").write_text(
        json.dumps(
            {"schema_version": S.SCHEMA_VERSION, "counters": counters},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- 构造行


def add_request(
    store: Store,
    request_id: str,
    *,
    topic: str = "群论",
    mode: str = "broad",
    content_description: str = "",
    done: bool = False,
    result_lit_ids: list[str] | None = None,
    last_error: str | None = None,
    attempts: int = 0,
    claimed_by: str | None = None,
    lease_until: str | None = None,
    providers: list[str] | None = None,
) -> dict:
    """插入一条合法的 search_requests 行（自带校验，防止测试数据本身不合法）。

    `providers` 是"这一行点名的检索源"（空 = 按角色级接线查，与加这一格之前
    的行为一致）。它必须能在这里给出来：领取侧按行上的名字选源，
    而别的入队口（CLI `submit` / 别的角色的 gap 分支）写的也是同一种行。
    """
    row = S.SearchRequest(
        request_id=request_id,
        timestamp=TS,
        topic=topic,
        mode=mode,  # type: ignore[arg-type]
        content_description=content_description,
        done=done,
        result_lit_ids=list(result_lit_ids or []),
        last_error=last_error,
        attempts=attempts,
        claimed_by=claimed_by,
        lease_until=lease_until,
        providers=list(providers or []),
    )
    row.validate()
    with store.tx("search_requests", actor="test") as tx:
        tx.upsert("search_requests", row.to_dict())
    return row.to_dict()


def set_request_done(store: Store, request_id: str, done: bool) -> None:
    """把请求的 done 置回指定值（模拟"崩溃后重跑"或"重新入队"）。"""
    with store.tx("search_requests", actor="test") as tx:
        row = tx.find("search_requests", request_id=request_id)
        assert row is not None, f"请求 {request_id} 不存在"
        row["done"] = done
        row["claimed_by"] = None
        row["lease_until"] = None
        if not done and not row.get("result_lit_ids") and not row.get("last_error"):
            row["last_error"] = "requeued_for_test"
        tx.upsert("search_requests", row)


def add_literature(
    store: Store,
    lit_id: str,
    *,
    title: str = "T",
    type_code: str = "J",
    path: str | None = None,
    processed: bool = False,
    source_request_ids: list[str] | None = None,
    dedup_key: str = "",
    doi: str | None = None,
    year: int | None = None,
    download: dict | None = None,
    sync: bool = True,
) -> dict:
    """插入一条合法的 literature 行。"""
    row = S.Literature(
        lit_id=lit_id,
        title=title,
        type=type_code,
        summary="",
        path=path,
        processed=processed,
        source_request_ids=list(source_request_ids or []),
        dedup_key=dedup_key,
        doi=doi,
        year=year,
        added_at=TS,
        download=dict(download or {}),
    )
    row.validate()
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict())
    if sync:
        sync_counters(store)
    return row.to_dict()


def add_concept(
    store: Store,
    concept_id: str,
    name: str,
    *,
    definition: str = "",
    related_concepts: list[str] | None = None,
    aliases: list[str] | None = None,
    sync: bool = True,
) -> dict:
    """插入一条合法的 concepts 行。"""
    row = S.Concept(
        concept_id=concept_id,
        name=name,
        definition=definition,
        related_concepts=list(related_concepts or []),
        normalized_name=name,
        aliases=list(aliases or []),
        created_at=TS,
        updated_at=TS,
    )
    row.validate()
    _data = row.to_dict()
    # 夹具是"生产写侧"的替身，所以它走过渡层的入口（`upsert_legacy_shaped`）：
    # 老表还在（并表过渡期）⇒ 老表照旧写全 + 同一笔事务里同步一份新标准（两处同号）；
    # 老表已退役（S1r 落刀之后）⇒ 只写新标准。一处判断，夹具在落刀前后一个字都不用改。
    # 只写老表的话，测试世界里的概念永远只活在老表那一侧，于是所有"读侧走合成视图"
    # 的判据在夹具里都只测了一半。
    with store.tx(*_CR.tables_for_concept_write(), actor="test") as tx:
        _CR.upsert_legacy_shaped(tx, _data, actor="test")
    if sync:
        sync_counters(store)
    return _data


def add_relation(
    store: Store,
    relation_id: str,
    concept_ids: list[str],
    lit_id: str,
    *,
    quote: str = "",
    description: str | None = None,
    status: str = "active",
    page_range: tuple[int, int] = (1, 1),
    group_key: str | None = None,
    quote_verified: bool | None = None,
    duplicate_of: str | None = None,
    sync: bool = True,
) -> dict:
    """插入一条合法的 relations 行。"""
    from agentflow import textutil as T

    pr = S.PageRange(page_range[0], page_range[1], f"pp. {page_range[0]}-{page_range[1]}")
    row = S.Relation(
        relation_id=relation_id,
        concept_ids=list(concept_ids),
        description=description if description is not None else (quote or "-"),
        lit_id=lit_id,
        page_range=pr,
        quote=quote,
        quote_normalized=T.normalize_for_quote(quote),
        quote_verified=quote_verified,
        statement=description if description is not None else (quote or "-"),
        concept_group_key=group_key if group_key is not None else T.concept_group_key(concept_ids),
        dedup_key=f"{T.concept_group_key(concept_ids)}::{T.short_hash(quote)}",
        status=status,
        duplicate_of=duplicate_of,
        created_at=TS,
    )
    row.validate()
    with store.tx("relations", actor="test") as tx:
        tx.upsert("relations", row.to_dict())
    if sync:
        sync_counters(store)
    return row.to_dict()


# --------------------------------------------------------------------------- J2/K2 夹具
#
# 裁定 J2 / K2：六件产物与 V 的验证台账真机没有样本（`draft/74 §0.3` 实测：
# 全树 `**/run-manifest.json` 搜到 0 个、`verifications/` 目录 0 个），所以它们的
# 判据输入由夹具造，并在页面上标明"夹具样本"。造在这里（`tests/conftest.py`）的理由
# 是 `draft/78 §2` 的边界：这个文件归 B 线独有，A/C 要造夹具就造在自己文件的局部
# fixture 里 —— 一份共享样本只有一个落点，改了不会只改一半。
#
# 形状逐个有出处，不是编的：
# - 六件产物的名字：`runflow.ARTIFACTS`（六个名字）；
# - 台账行的 9 个键：`artifacts.FIELDS`；
# - 交接行的键：`manuscripts.write` 写的那个 dict；
# - 秘书决策行的键：`secretary.Secretary.note_decision`；
# - 验收表的行键 `id/kind/min/name/note`：`draft/75 §1.3` 的真机读数（8 行 C1–C8）；
# - 体例的四节名字：`draft/74 §0.4` 的真机读数；
# - 检查点的 10 个键：`agent_loop.save_run_checkpoint`（第 10 个 `prompt_cache`
#   是 2026-10-19 补的，形状 = `promptstability.summarize_prompt_cache` 的 11 格）；
# - 验证行的键：`verifications.record_verification`。

#: 六件产物的名字（`runflow.ARTIFACTS`；真机没有样本 ⇒ 裁定 J2 用夹具造）。
RUN_PRODUCT_NAMES: tuple[str, ...] = (
    "run-manifest.json", "model-transcript.jsonl", "evidence.json", "claims.json",
    "cost.json", "report.md",
)

#: 验收表的机器可判行（真机 `p9b/out/paper/ACCEPTANCE-CHECKS.json` 是 8 行 C1–C8，
#: 键 `id/kind/min/name/note`）。这里造同样的形状。
ACCEPTANCE_CHECKS_SAMPLE: tuple[dict, ...] = (
    {"id": "C1", "kind": "research_question_rows", "min": 1,
     "name": "立题：研究问题已立", "note": "夹具样本"},
    {"id": "C2", "kind": "literature_rows", "min": 1,
     "name": "取材：文献已入库", "note": "夹具样本"},
    {"id": "C3", "kind": "experiment_rows", "min": 1,
     "name": "实验：至少跑过一次", "note": "夹具样本"},
)

#: 报告体例的四节名字（真机 `p9b/out/review/REPORT-STYLE.json` 逐字）。
REPORT_STYLE_SECTIONS: tuple[str, ...] = (
    "一、任务与范围", "二、逐条读数", "三、谁做了什么（含 input_key 与花销）",
    "四、证据不足与未做",
)


def make_run_products(root: Path, *, run: str = "out/run-1") -> Path:
    """造一份"跑过一次"的六件产物样本（裁定 J2），返回那个运行目录。

    内容刻意短而确定（`report.md` 是一行可断言的中文），因为判据要按字节核对它。
    `model-transcript.jsonl` 造两行，于是 `RunProduct.lines` 那一栏有一个非空读数
    （其余五件是 `.json`/`.md`，`lines` 按设计是 `None` —— 三态，不是 0）。
    """
    d = root / run
    (d / "assets").mkdir(parents=True, exist_ok=True)
    (d / "run-manifest.json").write_text(
        json.dumps({"run": run, "topic": "夹具样本：群论", "calls": 2},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (d / "model-transcript.jsonl").write_text(
        json.dumps({"i": 1, "role": "M", "text": "夹具样本第一轮"},
                   ensure_ascii=False) + "\n"
        + json.dumps({"i": 2, "role": "M", "text": "夹具样本第二轮"},
                     ensure_ascii=False) + "\n", encoding="utf-8")
    (d / "evidence.json").write_text(
        json.dumps({"claims": 1, "note": "夹具样本"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (d / "claims.json").write_text(
        json.dumps([{"claim_key": "c-1", "claim": "夹具样本命题"}],
                   ensure_ascii=False) + "\n", encoding="utf-8")
    (d / "cost.json").write_text(
        json.dumps({"spent_usd": 0.25}, ensure_ascii=False) + "\n", encoding="utf-8")
    (d / "report.md").write_text("夹具样本：这一趟的交付说明。\n", encoding="utf-8")
    return d


def make_artifacts_sample(root: Path, *, sid: str = "fix-sid") -> Path:
    """在临时工作区里造出六个只读面各自的样本（裁定 J2）。

    造出来的东西逐项对应一个读者：

    | 造的东西 | 谁读它 |
    |---|---|
    | `out/run-1/` 六件产物 | `readers.run_products` |
    | `ARTIFACTS.jsonl`（`artifacts.record` 写） | `readers.artifacts_face` 的 `ledger` |
    | `manuscripts/handoffs.jsonl`（`manuscripts.write`） | `handoffs` |
    | `out/paper/ACCEPTANCE-CHECKS.json` | `checks` |
    | `out/review/REPORT-STYLE.json` + `REPORT.md` | `style` / `RunView.report` |
    | `out/secretary/M.jsonl`（`Secretary.note_decision`） | `secretary` |
    | `out/experiments/*.log` + `out/tasks/t-.json` | 产物面的"M 那一路真机产物" |
    | `runs/agent-<角色>-<sid>.json`（`save_run_checkpoint`） | `readers.run_view` 的检查点 |
    | `data/tasks.json` 一行（`S.Task`） | 产物面的 `tasks` |
    | 一场会话（提问 + 一趟） | 证据面的 `triage_branch_recorded` |

    返回工作区根。顺序有讲究：文件先落盘，`artifacts.record` 才登记得进去
    （它拒绝登记不存在的路径 —— 那是它的核心纪律）。
    """
    from agentflow import agent_loop as AL
    from agentflow import artifacts as AR
    from agentflow import manuscripts as MS
    from agentflow import secretary as SEC
    from agentflow import sessions as SESS
    from agentflow import userio as U
    from agentflow import verifications as V

    root.mkdir(parents=True, exist_ok=True)
    st = Store(root)
    st.init()

    # ---- 六件产物 + M 那一路的真机产物（out/experiments · out/tasks · out/paper）
    run_dir = make_run_products(root)
    (root / "out" / "experiments").mkdir(parents=True, exist_ok=True)
    (root / "out" / "experiments" / "e-0001.log").write_text(
        "夹具样本：实验日志一行。\n", encoding="utf-8")
    (root / "out" / "tasks").mkdir(parents=True, exist_ok=True)
    (root / "out" / "tasks" / "t-0001.json").write_text(
        json.dumps({"task_id": "t-0001", "status": "done"},
                   ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "out" / "paper").mkdir(parents=True, exist_ok=True)
    (root / "out" / "paper" / "ACCEPTANCE-CHECKS.json").write_text(
        json.dumps({"checks": list(ACCEPTANCE_CHECKS_SAMPLE)},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "out" / "review").mkdir(parents=True, exist_ok=True)
    (root / "out" / "review" / "REPORT.md").write_text(
        "夹具样本交付说明：三条读数、两条没查成。\n", encoding="utf-8")
    (root / "out" / "review" / "REPORT-STYLE.json").write_text(
        json.dumps({"sections": list(REPORT_STYLE_SECTIONS)},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 台账（走 artifacts.record 这一个写入口，不手拼 JSON 行）
    for rel, producer, kind in (
        (f"{run_dir.relative_to(root).as_posix()}/run-manifest.json", "runflow", "manifest"),
        (f"{run_dir.relative_to(root).as_posix()}/model-transcript.jsonl",
         "runflow", "transcript"),
        ("out/experiments/e-0001.log", "agent-e", "log"),
        ("out/tasks/t-0001.json", "agent-m", "task"),
        ("out/paper/ACCEPTANCE-CHECKS.json", "agent-m", "checks"),
    ):
        AR.record(root, path=rel, producer=producer, kind=kind, task_id="t-0001",
                  at=TS)

    # ---- 交接手稿（走 manuscripts.write；它自己校验必填的三栏）
    MS.write(root, sender="M", recipient="E", summary="夹具样本：把口径交给 E",
             body="夹具样本正文：这一条交接是判据输入，不是真机产物。",
             refs=("out/run-1/report.md",), task_id="t-0001", sid=sid, note="夹具样本")

    # ---- 秘书决策台账（走 Secretary.note_decision 这一个写入口）
    sec = SEC.Secretary("M", root=root, store=st)
    sec.note_decision(duty=1, decision="可派", reason="夹具样本：还有余量",
                      basis=("tasks",), before="idle")
    sec.note_decision(duty=2, decision="已提醒", reason="夹具样本：预算快到了",
                      basis=("usage_ledger",), before="0.20")

    # ---- 检查点（走 agent_loop.save_run_checkpoint）
    AL.save_run_checkpoint(root, "M", sid, task="夹具样本：写一份交付说明",
                           step=3, stop_reason="waiting_for_user",
                           waiting_for="q0001",
                           spend={"calls": 2, "tokens_in": 30, "tokens_out": 40,
                                  "usd": 0.25, "unknown_usd_calls": 0},
                           # 2026-10-19：缓存汇总与 `spend` 并列（11 格，
                           # `promptstability.summarize_prompt_cache` 的形状）。
                           # 夹具造的是"上游给了读数"那一档：hit+miss == tokens_in。
                           prompt_cache={"calls": 2, "no_request_calls": 0,
                                         "hit": 20, "miss": 10, "unknown_calls": 0,
                                         "tokens_in": 30, "hit_rate": 0.6667,
                                         "mismatched_calls": 0, "saved_usd": 0.000002,
                                         "saved_unknown_calls": 0, "why": ""})

    # ---- 任务台账一行（走 schema + store.tx）
    with st.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", S.Task(
            task_id="t-0001", role="M", action="run", called_by="user",
            status="done", outcome="ok", input_key="M.run", detail="夹具样本：顶趟行",
            started_at=TS, ended_at=TS).to_dict())

    # ---- 一场会话：开场 → 一步 → 收尾，外加一条没答的提问（撑起 triage 那一格）
    SESS.append(root, {"kind": "agent_run_start", "role": "M", "task": "夹具样本",
                       "ts": TS}, sid=sid)
    SESS.append(root, {"kind": "agent_step", "role": "M", "index": 0,
                       "shape": "fs.write", "ts": TS}, sid=sid)
    SESS.append(root, {"kind": "agent_run_end", "role": "M", "stop_reason": "final",
                       "steps": 1, "final_chars": 6, "summons": 1, "messages": 0,
                       "elapsed_sec": 2.0, "ts": TS}, sid=sid)
    U.ask_user(root, role="M", question="夹具样本：这四处改动要不要保留？",
               options=({"label": "保留", "description": "第一档"},), timeout_sec=0,
               sid=sid)

    # ---- V 的验证台账（裁定 K2：造一行，含 verdict 与 proof_sha256）
    V.record_verification(root, statement_id="0001", proof_text="夹具样本：证明正文",
                          verdict={"verdict": "成立"}, verifier="V")
    return root


@pytest.fixture(autouse=True)
def _reset_provider_cooldowns():
    """每条判据前后都清空 provider 冷却表（缺陷 ⑰ 的副作用隔离）。

    `providers` 的冷却是**进程级**的字典（生产里正是要"这一趟记住这个源被限流了"），
    但判据之间必须互不污染：先前跑过的那条判据把一个 provider 打进冷却，
    下一条就会拿到 `ProviderError: …正在限流冷却`，看起来像本身的断言失败。
    """
    from agentflow import providers as _P

    _P.clear_provider_cooldowns()
    yield
    _P.clear_provider_cooldowns()


@pytest.fixture
def artifacts_ws(tmp_path: Path) -> Path:
    """六面只读模型的夹具工作区（裁定 J2/K2；见 :func:`make_artifacts_sample`）。"""
    return make_artifacts_sample(tmp_path / "ws")


# --------------------------------------------------------------------------- fixture


@pytest.fixture
def store(tmp_path: Path) -> Store:
    """一个空的、已 init 的临时工作区（data/ + library/ + .locks/）。"""
    st = Store(tmp_path / "ws")
    st.init()
    return st


@pytest.fixture
def clean_store(tmp_path: Path) -> Store:
    """一份完全自洽的最小数据集：verify 应当零错误零警告。

    结构：1 条已完成请求 → 1 篇已处理文献 → 2 个互为相关的概念 → 1 条 active 关系。
    """
    st = Store(tmp_path / "ws")
    st.init()
    write_library_file(
        st,
        "0000/source.txt",
        "An abelian group is a group in which the commutative law holds.",
    )
    add_request(st, "r-0001", done=True, result_lit_ids=["0000"])
    add_literature(
        st,
        "0000",
        title="Commutativity in abelian groups",
        path="0000/source.txt",
        processed=True,
        source_request_ids=["r-0001"],
        dedup_key="doi:10.1000/demo.abelian",
        doi="10.1000/demo.abelian",
        year=1930,
        download={
            "status": "ok",
            "http_status": 200,
            "bytes": 62,
            "sha256": "0" * 64,
            "error": None,
        },
    )
    add_concept(st, "0000", "group", related_concepts=["0001"])
    add_concept(st, "0001", "abelian group", related_concepts=["0000"])
    add_relation(
        st,
        "0000",
        ["0000", "0001"],
        "0000",
        quote="An abelian group is a group in which the commutative law holds.",
        group_key="0000|0001",
        quote_verified=True,
    )
    sync_counters(st)
    return st
