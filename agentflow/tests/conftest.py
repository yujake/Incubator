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

from agentflow import schema as S  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 逐字节快照要覆盖的数据文件（"回滚后磁盘完全没变"的断言依赖它）。
#: 新增表必须加进来 —— `test_atomic_write_leaves_no_tmp_residue` 会断言
#: data/ 下恰好只有这些文件，漏加会以"多出文件"的形式报错（这正是我们想要的：
#: 防止初始化时悄悄多出意料之外的文件）。
DATA_FILES = (
    "search_requests.json",
    "literature.json",
    "concepts.json",
    "relations.json",
    "analysis_reports.json",
    "research_questions.json",
    "reprocess_requests.json",
    "experiments.json",
    "attack_plans.json",
    "documents.json",
    "dependencies.json",
    "review_findings.json",
    "tasks.json",
    "usage_ledger.json",
    "eval_results.json",
    "counters.json",
    "events.jsonl",
)

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
    原先这里写死了 3 个 kind，于是新增 `experiment` / `plan` / `doc` / `dep` /
    `finding` 五类之后，用本函数同步过的库仍会报 counter_behind ——
    而报错的内容与测试真正想验证的东西毫无关系，纯属噪音。
    这正是"跨模块约定必须只有一处定义"（FC-03）在测试代码里的形态：
    测试代码也是代码，写死第二份名单同样会漂移。
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
) -> dict:
    """插入一条合法的 search_requests 行（自带校验，防止测试数据本身不合法）。"""
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
    with store.tx("concepts", actor="test") as tx:
        tx.upsert("concepts", row.to_dict())
    if sync:
        sync_counters(store)
    return row.to_dict()


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
