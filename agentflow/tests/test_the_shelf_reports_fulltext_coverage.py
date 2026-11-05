# -*- coding: utf-8 -*-
"""判据（阶段 ③ 第 2A 步）：`search.shelf` 必须报出「全文覆盖率」。

## 它补的是哪一格

真机读数（`draft/172` §4 第 4 轮 / `O-04`，projects/paper-rewrite-78）：

```
literature 32 行，只有 5 行有本地全文（15.6%）；statements 22 条的
`quote_verified` 全是 None —— 因为被引的那 27 篇根本没有可比的全文。
```

这不是"引文回验坏了"（`relations` 里凡是有全文的 8/8 都 `True`），而是
A 看不见这个缺口：`search.shelf` 只列"书架上有哪几本"，不报"文献表里
一共有几篇"。于是"32 篇里 5 篇能离线引用"这个事实没有任何一处会说出来，
M 可以一路写正文、到收工门才一次性撞上它（那时返工最贵）。

## 三态纪律：`no_location` 是「没去取」，不是「这篇不存在」

`coverage.no_location` 数的是「行上既没有 `path`、也没有可取全文的定位
（`pdf_url` / `landing_url`，或下载台账里记下的 `download.url`）」的条数。
它说的是一句关于我们自己的话：这些篇我们连全文地址都没留下 ⇒ 没去取。
它不说"这篇文献不存在" —— 把两者折叠，下游就会把"我们没做"当成
"查过了、没有"，然后据此删掉一条本该被引用的证据（`LESSONS` 的 FC-01 同族）。

### 业主裁定（2026-10-28）：`download.url` 算定位

`literature` 行上没有 `pdf_url` / `landing_url` 这两个字段
（`schema.Literature` 里根本没定义）；A 真机那趟把定位链接记在 `download.url`
里，note 逐字写着"只登记了候选源给出的定位链接（url 这一格），没有下载字节；
要全文请按它重取"。所以那个 URL 就是 landing 定位，必须算作"有地址"。
真机读数因此是：`total 32 / with_fulltext 5 / rate 0.15625 / missing 27 /
no_location 0` —— 27 篇是"有地址、没去取"，不是"没地址"。
（若把 `download.url` 排除在外，`no_location` 会恒等于 `missing`：一个数
同时说两件事，等于两件都没说。判据 `test_a_recorded_download_url_...`
就是钉这一格的负控。）

## 这一组守什么

1. 三类行各归哪一档（有 path 且在盘 / 有 pdf_url 但没取 / 两者都无）；
2. 空表 = `checked` 的 0 + `rate=None`（不是 0，也不是 unknown）；
3. 反真空：`no_location` 不许与 `missing` 恒等，返回里不许出现"不存在"
   这种断言键，note 与声明都必须明写两者不同；
4. `python -m agentflow.cli tools --role A` 走一遍真装配；
5. 真机那一趟的形状（32/5/27）读得出来。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import ROLES, build_registry, search_tools
from agentflow.tools.base import ToolRegistry

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 夹具


def _registry(store: Store | None) -> ToolRegistry:
    """绑定 A 的注册表（`search.*` 的 `roles` 只有 A；这里只测读面）。"""
    reg = ToolRegistry(name="shelf-coverage")
    reg.bound_role = "A"
    search_tools.register(reg, store=store, workspace=(store.root if store else None))
    return reg


def _shelf(store: Store) -> dict[str, Any]:
    res = _registry(store).call("search.shelf")
    assert res.ok, (res.error, res.meta)
    return res.data


def _row(store: Store, lit_id: str, *, path: str | None = None,
         download: dict | None = None, **extra: Any) -> dict[str, Any]:
    """铺一行 literature：走 `tx.upsert` 的公开写口（不手搓表文件）。

    `extra` 用来放行上的定位字段（`pdf_url` / `landing_url`）——
    `schema.Literature` 没有这两格，但盘上的行可以有：`Store.rows()` 读的是
    原始 dict（`_keys` 就是这么活着的），所以判据要能看见"实现到底读了哪几格"。
    """
    row = S.Literature(
        lit_id=lit_id, title=f"文献 {lit_id}", type="J", summary="判据用的行",
        path=path, processed=False, added_at=S.now_iso(),
        download=dict(download or {}),
    ).to_dict()
    row.update(extra)
    with store.tx("literature", "counters", actor="test") as tx:
        tx.upsert("literature", row)
    return row


def _put_fulltext(store: Store, lit_id: str, rel: str, text: str = "一页正文。\n") -> str:
    """把全文真写进 `library/` 并返回相对路径（"在盘上"与生产路径同一个判据）。"""
    dest = Path(store.library) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return rel


# ---------------------------------------------------------------- 1) 三类行


def test_the_three_kinds_of_rows_land_in_three_different_buckets(store: Store):
    """正向：有 path 且在盘 / 有 pdf_url 但没取 / 两者都无 —— 各归各的档。

    这条是 `coverage` 的全部语义，所以三类行同时摆在表里：
    只摆一类的话，"按 `missing` 再按 `path` 算"与"按定位算"长得一样。
    """
    rel = _put_fulltext(store, "0001", "0001/full.txt")
    _row(store, "0001", path=rel, download={"status": "ok", "bytes": 8, "sha256": "a" * 64})
    # 有 pdf_url 但没取：定位在 ⇒ 落进 missing，不落进 no_location
    _row(store, "0002", pdf_url="https://example.invalid/b.pdf",
         download={"status": "skipped", "error": "no_local_path"})
    # 两者都无：既没有 path 也没有任何定位
    _row(store, "0003", download={"status": "failed", "error": "no_open_access_location"})

    data = _shelf(store)
    cov = data["coverage"]
    assert cov["checked"] is True, cov
    assert cov["total"] == 3, cov
    assert cov["with_fulltext"] == 1, cov
    # with_fulltext 与 books 计数是同一件事（不筛时）
    assert cov["with_fulltext"] == data["count"], (cov, data["count"])
    assert cov["missing"] == 2, cov
    assert cov["no_location"] == 1, cov
    assert cov["rate"] == pytest.approx(1 / 3), cov


def test_coverage_describes_the_whole_table_not_the_filtered_view(store: Store):
    """`coverage` 是整张文献表的读数：`query` / `lit_id` / `limit` 只筛 `books`。

    为什么必须单钉一条：`with_fulltext` 若从 `books` 数（最省事的写法），
    一旦 A 带 `lit_id` 查某一篇，覆盖率会变成 1/1 = 100% —— 那正好把
    "32 篇里只有 5 篇有全文"这个缺口在最需要它的时候抹平。
    """
    _row(store, "0001", path=_put_fulltext(store, "0001", "0001/a.txt"),
         download={"status": "ok", "bytes": 8, "sha256": "a" * 64})
    _row(store, "0002", path=_put_fulltext(store, "0002", "0002/b.txt"),
         download={"status": "ok", "bytes": 8, "sha256": "b" * 64})
    _row(store, "0003", download={"status": "skipped", "error": "no_local_path"})

    res = _registry(store).call("search.shelf", lit_id="0001")
    assert res.ok, (res.error, res.meta)
    data = res.data
    assert data["count"] == 1, data
    cov = data["coverage"]
    assert cov["total"] == 3 and cov["with_fulltext"] == 2, cov
    assert cov["missing"] == 1 and cov["no_location"] == 1, cov


# ---------------------------------------------------------------- 2) 空表


def test_an_empty_literature_table_is_a_checked_zero_with_no_rate(store: Store):
    """空表：`checked` 的读数 + `total=0` + `rate=None`（不是 0，也不是 unknown）。

    "没有文献"与"覆盖率 0 成"是两件事：前者没有分母，后者有一个 0 的分母读数。
    把 `rate` 折成 0，下游会读成"我们有 32 篇、一篇都没全文"——
    一个看起来完全合理的假结论。
    """
    data = _shelf(store)
    cov = data["coverage"]
    assert cov["checked"] is True, cov
    assert cov["total"] == 0, cov
    assert cov["with_fulltext"] == 0 and cov["missing"] == 0, cov
    assert cov["rate"] is None, f"空表的 rate 只能是 None（不是 0、不是 unknown）：{cov}"

    # 而"没数成"是另一件事：表坏了 ⇒ 整件工具 fail，根本没有 coverage 块。
    # 这一半是反真空：证明 `checked=True` 不是无条件写在返回里的装饰。
    (store.root / "data" / "literature.json").write_text("{ 这不是 JSON", encoding="utf-8")
    res = _registry(store).call("search.shelf")
    assert not res.ok, res.data
    assert res.meta.get("kind") == "table_unreadable", res.meta
    assert "coverage" not in (res.data or {}), (
        "读表失败时还给了一个 coverage 块 ⇒ 「没数成」与「数出来是 0」被折叠了"
    )


# ---------------------------------------------------------------- 3) 反真空


#: 这些键名会把"我们没去取"写成"这篇不存在" —— 返回里出现任何一个都是缺陷。
NOT_FOUND_WORDS: frozenset[str] = frozenset({
    "not_found", "notfound", "nonexistent", "does_not_exist", "absent",
    "missing_paper", "no_such_paper", "paper_missing",
})


def test_no_location_is_not_the_same_claim_as_the_paper_does_not_exist(store: Store):
    """反真空：`no_location` 不许与 `missing` 恒等，也不许被读成"这篇不存在"。

    三段，缺一条这条判据就没有牙：

    ① 不许恒等：夹具里 `missing=2` 而 `no_location=1`（一行带 pdf_url）。
       若实现把 `no_location` 写成 `missing`（或反过来），这两个数会一起变 ⇒ 红。
    ② 不许有"不存在"这种键：`not_found` / `nonexistent` 这类键名本身
       就是一句关于文献的断言，而这件事我们无权说（我们只知道"没取"）。
    ③ note 必须明写两者不同：读数只有一个数，读它的人若不知道口径，
       0 会被读成"这些篇不存在"。声明面（`returns=`）里也要有同一句话。
    """
    _row(store, "0001", download={"status": "skipped", "error": "no_local_path"})
    _row(store, "0002", pdf_url="https://example.invalid/c.pdf",
         download={"status": "skipped", "error": "no_local_path"})

    data = _shelf(store)
    cov = data["coverage"]
    assert cov["missing"] == 2, cov
    assert cov["no_location"] == 1, (
        f"no_location 与 missing 变得一样了（{cov}）⇒ 这个数同时说两件事，等于两件都没说"
    )

    assert not (NOT_FOUND_WORDS & set(data)), (
        f"返回里出现了「这篇不存在」这种断言键：{sorted(NOT_FOUND_WORDS & set(data))}"
    )
    assert not (NOT_FOUND_WORDS & set(cov)), (
        f"coverage 里出现了「这篇不存在」这种断言键：{sorted(NOT_FOUND_WORDS & set(cov))}"
    )

    note = str(data["note"])
    assert "不存在" in note, f"note 没写清 no_location 不是「不存在」：{note!r}"
    assert ("没去取" in note) or ("没取" in note), (
        f"note 没写清 no_location 是「没去取」：{note!r}"
    )

    returns = _registry(store).get("search.shelf").returns
    assert "不存在" in returns and ("没去取" in returns or "没取" in returns), (
        f"`returns=` 里没写清 no_location 的口径（模型看得到的就是它）：{returns!r}"
    )


def test_a_recorded_download_url_counts_as_a_location_not_as_no_location(store: Store):
    """业主裁定（2026-10-28）：`download.url` 是 landing 定位 ⇒ 这一档不进 no_location。

    为什么必须有这条：`literature` 行上没有 `pdf_url` / `landing_url` 字段，
    真机那趟的定位链接全部记在 `download.url`（note：「只登记了候选源给出的定位
    链接……要全文请按它重取」）。判据若只认行上的两个字段，真机上
    `no_location` 会读出 27（= `missing`）—— 一个恒等于 missing 的数。
    正确读数是 0：27 篇全都有地址、只是没去取。
    """
    _row(store, "0001", path=None,
         download={"status": "skipped", "error": "no_local_path",
                   "url": "https://doi.org/10.1112/s0025579300002540"})
    _row(store, "0002", path=None,
         download={"status": "failed", "error": "no_open_access_location"})

    cov = _shelf(store)["coverage"]
    assert cov["missing"] == 2, cov
    assert cov["no_location"] == 1, (
        f"`download.url` 没被认成定位 ⇒ 真机上 no_location 会恒等于 missing：{cov}"
    )


def test_a_path_that_lives_in_downloads_is_still_on_the_shelf(store: Store):
    """真缺陷的回归判据：`literature.path` 的两个坐标系必须说同一件事。

    2026-10-28 在真机上撞出来的（`projects/paper-rewrite-78`）：有 4 行被
    `table.update` 改写成了 `downloads/lit-*.pdf`（事件日志 `tool:table.update`
    四处），文件真的在盘上；而 `search.shelf` / `search.local` 只按
    `library/` 解析 ⇒ 书架 `count=1`、`missing_files=4`、`have_path=5`。
    同一字段两个读法，没有任何一处报错 —— 那几篇的正文既取不到，也就无法
    做逐字引文回验。

    写入侧（`_adopt_file`）早就承认两个坐标系（"先 library/
    再 workspace"），所以读取侧照同一个约定解析即可；这条判据钉住它。
    """
    ws = Path(store.root)
    dl_dir = ws / "downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    (dl_dir / "lit-0001.pdf.txt").write_text("下载目录里的那一篇正文。\n", encoding="utf-8")
    _row(store, "0001", path="downloads/lit-0001.pdf.txt",
         download={"status": "ok", "bytes": 30, "sha256": "c" * 64})

    data = _shelf(store)
    assert data["count"] == 1, f"下载目录里的全文没被算成「在盘上」：{data}"
    assert data["missing_files"] == 0, data
    cov = data["coverage"]
    assert cov["with_fulltext"] == 1 and cov["missing"] == 0, cov
    # 而 `search.local` 读的是同一个解析（同一条 `_shelf_row`）⇒ 它也取得到这段正文
    res = _registry(store).call("search.local", query="下载目录", limit=2)
    assert res.ok and res.data["count"] >= 1, res.data
    assert res.data["skipped_no_file"] == [], res.data


def test_a_path_that_escapes_the_workspace_is_still_refused(store: Store):
    """负控：放宽"文件在哪"不等于能读到工作区外面去（`../` 那条路必须还是死路）。

    两种入口分开验：

    * 写口：`../outside-secret.txt` 进不了表（`schema` 的校验在落盘时拒它）——
      先用一条真实的 `tx` 证明这一点，否则下面那个"坏快照"会被读成我在造谣；
    * 读口：盘上的快照被手工改坏（`schema.library_path` 的 docstring 逐字
      点名了这一类："即使有人手工把 `path` 改成 `../../etc/passwd`"）⇒ 书架
      必须看不见它，而不是把工作区外的文件当成本地全文。
    """
    outside = Path(store.root).parent / "outside-secret.txt"
    outside.write_text("工作区外的文件。\n", encoding="utf-8")

    # ---- 读口：把快照改成一条越界行（走 store 自己的行形状，不手搓字段名）
    doc = json.loads((store.root / "data" / "literature.json").read_text(encoding="utf-8"))
    doc["rows"].append(S.Literature(
        lit_id="0001", title="越界那一行", type="J", summary="判据用",
        path="../outside-secret.txt", processed=False, added_at=S.now_iso(),
        download={"status": "skipped", "error": "no_local_path"},
    ).to_dict())
    (store.root / "data" / "literature.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    data = _shelf(store)
    assert data["count"] == 0, f"越出工作区的路径被当成书架上的书：{data}"
    assert data["coverage"]["with_fulltext"] == 0, data["coverage"]
    assert data["missing_files"] == 1, data

    # ---- 写口：同一个值进不了表（这一条让上面那个坏快照有出处：它只能来自手改）
    with pytest.raises(ValueError):
        with store.tx("literature", actor="test") as tx:
            tx.upsert("literature", S.Literature(
                lit_id="0002", title="越界那一行", type="J", summary="判据用",
                path="../outside-secret.txt", processed=False, added_at=S.now_iso(),
            ).to_dict())


# ---------------------------------------------------------------- 4) CLI 真装配

def test_the_cli_surfaces_the_shelf_on_role_a_and_the_registry_holds_the_new_key():
    """`python -m agentflow.cli tools --role A` 真跑一遍 + 新键在同一条装配的声明里。

    为什么分两半（这是判据的口径，不是偷懒）：

    - CLI 的 `--role` 那一支只印 `summary[:60]`（`cli.py::cmd_tools`），不印
      `returns`：要让它印，就得改 CLI 的输出格式 —— 而 CLI 的输出是
      `tests/golden/tool_surface_snapshot.json`（FC-27 冻结快照，11 条）的
      比对对象，改它需要人重冻。所以这里用同一条装配（`build_registry`）
      读声明：CLI 与这个注册表是同一份装配（`cmd_tools` 里就是
      `build_registry(store=…, workspace_root=…, roles=tuple(ROLES))`）。
    - 子进程那趟仍然必须真跑：它是"角色即权限面"的可打印事实，也是这次
      接线的端到端证据（A 拿得到、装配没崩）。
    """
    env = dict(os.environ)
    src = str(REPO / "src")
    env["PYTHONPATH"] = (src + os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else src
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    p = subprocess.run(
        [sys.executable, "-m", "agentflow.cli", "tools", "--role", "A"],
        cwd=src, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, env=env,
    )
    out = (p.stdout or "") + (p.stderr or "")
    assert p.returncode == 0, out[-800:]
    assert re.search(r"角色 A 可用工具（\d+ 个）", out), f"CLI 输出形状变了：{out[-800:]}"
    assert "search.shelf" in out, f"A 的工具面上没有 search.shelf：{out[-800:]}"

    # 同一条装配的声明面：新键必须在 `returns=` 里（`returns` 只是台账/快照的契约，
    # 模型面看不到它；判据 `test_tools_returns_declaration` 要求声明与实跑对上）
    reg = build_registry(store=None, workspace_root=None, roles=tuple(ROLES)).registry
    returns = reg.get("search.shelf").returns
    assert "'coverage'" in returns, f"`returns=` 里没有 coverage：{returns!r}"
    # 子键也要逐个点名（否则模型不知道 coverage 里有什么）
    for key in ("total", "with_fulltext", "rate", "missing", "no_location"):
        assert f"'{key}'" in returns, f"`returns=` 的 coverage 没点名 {key}：{returns!r}"


# ---------------------------------------------------------------- 5) 真机形状


def test_the_real_machine_shape_reads_as_five_of_thirty_two(store: Store):
    """现盘形状的复刻（`draft/172` §4 第 4 轮）：32 行 / 5 行有全文 / 27 行有地址没取。

    真机读数逐字：`literature 32（有本地全文只有 5 行，27 行没有）`，
    那 27 行各自都带着一个 `download.url`（DOI 落地链接）。所以这一条钉的是
    两个数都要说对：缺口是 27（`missing` / `rate`），而"连地址都没有"是 0
    （`no_location`）—— A 从今天起看得见这个缺口，而且知道它是"没去取"。
    """
    for i in range(5):
        lit_id = f"{i:06d}"
        _row(store, lit_id, path=_put_fulltext(store, lit_id, f"{lit_id}/ft.txt"),
             download={"status": "ok", "bytes": 8, "sha256": "a" * 64,
                       "url": f"https://arxiv.org/pdf/{i}"})
    for i in range(5, 32):
        lit_id = f"{i:06d}"
        _row(store, lit_id,
             download={"status": "skipped", "error": "no_local_path",
                       "url": f"https://doi.org/10.1112/{lit_id}",
                       "note": "本次无全文：只登记了候选源给出的定位链接"})

    data = _shelf(store)
    cov = data["coverage"]
    assert cov["total"] == 32, cov
    assert cov["with_fulltext"] == 5, cov
    assert cov["missing"] == 27, cov
    assert cov["rate"] == pytest.approx(5 / 32), cov
    assert cov["rate"] == pytest.approx(0.15625), cov
    assert cov["no_location"] == 0, (
        f"27 行都带 download.url ⇒「连地址都没有」的那一档是 0，不是 27：{cov}"
    )
