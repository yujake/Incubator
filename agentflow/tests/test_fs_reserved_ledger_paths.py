# -*- coding: utf-8 -*-
"""框架账本区不许被文件口架空：data/ / locks/ / events.jsonl 上四个写口一律拒。

## 改前是什么形态（Q10 审计的真机读数，零模型钱）

```text
fs.write(path="data/usage_ledger.json", overwrite=True)（先 fs.read 一次）
⇒ 账本 10.51 美元 → 0；events.jsonl 里该表记录数 8 → 8（一个字节的痕迹都没留）
⇒ verify 一声不响
data/counters.json 同样可被整份覆盖（实测写进去的是 {"lit":0}）
fs.delete("data", recursive=True) 改前也成功：整本账连目录一起消失
```

改前这条路由三件事组成：`fs.write` / `fs.edit` 只过手稿保留表（文件名级，`data/`
下的 `.json` 一个都不命中）；`fs.delete` / `fs.move` 连那张表都不查。于是表口的三层
（表属性枚举 / 直写弃置 / 事务里的工具身份闸）一层都不经过 —— 文件口把表口整个架空了。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a 四份账本文件的 write | 先 fs.read 再 fs.write(overwrite=True)：每一份都拒，盘上逐字节未动 | 改前四份全被抹平 |
| b 四份账本文件的 edit / delete / move | 三个口同样拒、逐字节未动；`data/` 整目录 recursive 删也拒 | 改前 edit 改得进去、delete 删得掉、move 挪得走 |
| c 误伤面正控 | `out/x.md` / `reports/x.md` / `notes/f-proof-x.md` 仍可写 | —— |
| d 反真空（整表） | 把保留表打桩成空 ⇒ a / b 必红（于是它们的绿来自那张表） | —— |
| e 反真空（规则存在性） | 表里确实有一条覆盖 `data/` 的规则；只摘掉 data 那两行 ⇒ 只有 data 松动、locks 仍拒 | —— |

a 必须先读：不读的话撞到的是 `not_observed` 那道无关的闸，测出来的是假绿
（Q10 踩过这一次：没先读，write 被拒，看起来像"已经挡住了"）。

## 为什么拒信不指路

模型对 `data/` 没有合法正路（表口的写入由框架自己的落盘路径完成）。指一条空气路只会
让它换着写法重试到 `no_progress_limit`，所以这里的拒信只说"这是框架账本区，不是你的
落点"，并点名三条绕行口（换名字 / 换目录 / 整份覆盖）都不行。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import fs_tools as FT

#: 四份账本文件：表快照 / 计数 / 评测结果 / 事件日志。
LEDGERS = (
    "data/usage_ledger.json",
    "data/counters.json",
    "data/eval_results.json",
    "data/events.jsonl",
)
#: 受控码：账本区（与手稿那一个 `reserved_framework_artifact` 分开）。
KIND = "reserved_framework_ledger"
#: 拒信里必须出现的那半句（说清"这是什么地方、不是你的落点"）。
MESSAGE = "这是框架账本区"


def _ws(path: pathlib.Path):
    root = path / "ws"
    store = Store(root)
    store.init()
    reg = build_registry(store=store, workspace_root=root).registry
    return root, reg


def _call(reg, role: str, tool: str, **params):
    """按某个角色的身份调一次工具（与真机同一条身份挂点）。"""
    with calling_as("t-ledger", role):
        return reg.call(tool, role=role, **params)


def _bytes(root: pathlib.Path, rel: str) -> bytes:
    return (root / rel).read_bytes()


# ============================================================ a：write


def test_a_write_is_refused_on_every_ledger_file(tmp_path: pathlib.Path) -> None:
    """a 判据：先读、再整份覆盖，四份账本文件每一份都拒且逐字节未动。

    改前红：四份都会被写成 `{"lit":0}`（Q10 实测账本 10.51 美元 → 0，且
    `events.jsonl` 里该表记录数 8 → 8，一个字节的痕迹都没留）。
    """
    root, reg = _ws(tmp_path)
    for rel in LEDGERS:
        before = _bytes(root, rel)
        rd = _call(reg, "A", "fs.read", path=rel)
        assert rd.ok is True, (rel, rd)
        wr = _call(reg, "A", "fs.write", path=rel, content='{"lit":0}', overwrite=True)
        assert wr.ok is False, (rel, wr)
        assert wr.meta.get("kind") == KIND, (rel, wr.meta)
        assert MESSAGE in str(wr.error or ""), (rel, wr.error)
        assert _bytes(root, rel) == before, f"{rel} 被拒了却仍然落盘或变了"


# ============================================================ b：edit / delete / move


def test_b_edit_is_refused_on_every_ledger_file(tmp_path: pathlib.Path) -> None:
    """b 判据（edit）：定点替换同样被拒，且盘上那一份逐字未动。

    改前红：`fs.edit` 能改正文 —— 改一份表与整份覆盖它在账本上是同一件事。
    """
    root, reg = _ws(tmp_path / "edit")
    # `events.jsonl` 起手是空的（没有 `old_string` 可锚），先直接落一行，模拟"账本里本来就有记录"。
    (root / "data" / "events.jsonl").write_text(
        '{"seq": 1, "table": "usage_ledger"}\n', encoding="utf-8")
    old_new = {
        "data/usage_ledger.json": ('"schema_version": 2', '"schema_version": 9'),
        "data/counters.json": ('"counters"', '"counters_x"'),
        "data/eval_results.json": ('"rows"', '"rows_x"'),
        "data/events.jsonl": ("usage_ledger", "forged"),
    }
    for rel in LEDGERS:
        before = _bytes(root, rel)
        rd = _call(reg, "A", "fs.read", path=rel)
        assert rd.ok is True, (rel, rd)
        old, new = old_new[rel]
        ed = _call(reg, "A", "fs.edit", path=rel, old_string=old, new_string=new,
                   allow_multiple=True)
        assert ed.ok is False, (rel, ed)
        assert ed.meta.get("kind") == KIND, (rel, ed.meta)
        assert _bytes(root, rel) == before, f"{rel} 被拒了却仍然被改"


def test_b_delete_is_refused_on_every_ledger_file(tmp_path: pathlib.Path) -> None:
    """b 判据（delete）：删一份表 / 删整个 `data/` 都拒，账本仍在盘上。

    改前红：四份文件都能删掉；`fs.delete("data", recursive=True)` 也成功
    （整本账连事件日志一起消失，而 `rebuild` 之后它会以一行没有任何事件来源的状态复活）。
    """
    root, reg = _ws(tmp_path / "delete")
    for rel in LEDGERS:
        dl = _call(reg, "A", "fs.delete", path=rel)
        assert dl.ok is False, (rel, dl)
        assert dl.meta.get("kind") == KIND, (rel, dl.meta)
        assert (root / rel).is_file(), f"{rel} 被拒了却没了"
    dl = _call(reg, "A", "fs.delete", path="data", recursive=True)
    assert dl.ok is False, dl
    assert dl.meta.get("kind") == KIND, dl.meta
    assert (root / "data").is_dir(), "整目录被拒了却没了"
    # 闸是路径判据，不是"存在才拒"：一个还不存在的 locks/ 也一并拒。
    dl = _call(reg, "A", "fs.delete", path="locks", recursive=True)
    assert dl.ok is False and dl.meta.get("kind") == KIND, dl


def test_b_move_is_refused_on_both_ends(tmp_path: pathlib.Path) -> None:
    """b 判据（move）：把表挪走、把文件挪进账本区、整目录改名，三种都拒。

    改前红：`fs.move(src="data/usage_ledger.json", dst="out/usage_ledger.json")` 成功
    —— 表就这么消失了，而 events.jsonl 里一个字都没有。
    """
    root, reg = _ws(tmp_path / "move")
    for rel in LEDGERS:
        mv = _call(reg, "A", "fs.move", src=rel,
                   dst="out/" + pathlib.PurePosixPath(rel).name)
        assert mv.ok is False, (rel, mv)
        assert mv.meta.get("kind") == KIND, (rel, mv.meta)
        assert (root / rel).is_file(), f"{rel} 被拒了却没了"
    # 反方向：dst 落在账本区（`data/ledger-copy.json` 起手并不存在，所以
    # 改前它一定成功 —— 这是真正的"挪进去"口，不是被"目标已存在"挡住的假绿）。
    (root / "out").mkdir(parents=True, exist_ok=True)
    (root / "out" / "payload.md").write_text("payload\n", encoding="utf-8")
    mv = _call(reg, "A", "fs.move", src="out/payload.md", dst="data/ledger-copy.json")
    assert mv.ok is False, mv
    assert mv.meta.get("kind") == KIND, mv.meta
    assert (root / "out" / "payload.md").is_file(), "被拒了却把源挪走了"
    assert not (root / "data" / "ledger-copy.json").exists(), "被拒了却落进了账本区"
    # 整目录：`data` 自己（`exact:data` 那一行）。
    mv = _call(reg, "A", "fs.move", src="data", dst="out/data")
    assert mv.ok is False and mv.meta.get("kind") == KIND, mv
    assert (root / "data").is_dir()


# ============================================================ c：误伤面


def test_c_legit_landing_spots_are_untouched(tmp_path: pathlib.Path) -> None:
    """c 判据（正控）：合法落点照旧可写。

    `out/` / `reports/` / `notes/` 是角色的正常产出面；`out/data/notes.md` 一起钉住
    "前缀按分段锚定"（`data/` 只在路径首段才算账本区，不是"路径里出现 data/"）。
    """
    root, reg = _ws(tmp_path)
    for rel in ("out/x.md", "reports/x.md", "notes/f-proof-x.md", "out/data/notes.md"):
        wr = _call(reg, "A", "fs.write", path=rel, content="正常产出")
        assert wr.ok is True, (rel, wr)
        assert (root / rel).is_file(), (rel, "被误伤了")
    # 正控也要有删除/移动的活口：自己 out/ 下的文件删得掉、挪得动。
    dl = _call(reg, "A", "fs.delete", path="out/x.md")
    assert dl.ok is True, dl
    mv = _call(reg, "A", "fs.move", src="reports/x.md", dst="reports/y.md")
    assert mv.ok is True, mv


# ============================================================ d：反真空（整表）


def test_d_stubbing_the_table_out_turns_a_and_b_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """d 判据（反真空）：把保留表打桩成空 ⇒ a / b 必红。

    打桩点就是那张表（`fs_tools.RESERVED_ARTIFACT_TABLE`）：清空之后同一条路径必须
    写得进去、改得进去、删得掉、挪得走 —— 于是"账本区被拒"这件事的来源是那张表，
    而不是四个口各自顺手写的某个判断。
    """
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", ())
    root, reg = _ws(tmp_path / "d")
    rd = _call(reg, "A", "fs.read", path="data/usage_ledger.json")
    assert rd.ok is True, rd
    wr = _call(reg, "A", "fs.write", path="data/usage_ledger.json",
               content='{"lit":0}', overwrite=True)
    assert wr.ok is True, ("表被清空了却还是拒 ⇒ a 的绿不来自那张表", wr)
    assert (root / "data" / "usage_ledger.json").read_text(encoding="utf-8") == '{"lit":0}'
    ed = _call(reg, "A", "fs.edit", path="data/usage_ledger.json",
               old_string='"lit"', new_string='"lit2"')
    assert ed.ok is True, ("表被清空了却还是拒 ⇒ b 的 edit 绿不来自那张表", ed)
    dl = _call(reg, "A", "fs.delete", path="data/counters.json")
    assert dl.ok is True, ("表被清空了却还是拒 ⇒ b 的 delete 绿不来自那张表", dl)
    mv = _call(reg, "A", "fs.move", src="data/eval_results.json", dst="out/eval.json")
    assert mv.ok is True, ("表被清空了却还是拒 ⇒ b 的 move 绿不来自那张表", mv)


# ============================================================ e：反真空（规则存在性）


def test_e_the_data_rule_really_exists_and_is_the_source(tmp_path: pathlib.Path,
                                                         monkeypatch) -> None:
    """e 判据（反真空，规则存在性）：表里确实有一条覆盖 `data/` 的规则。

    没有这一条，"表被清空"与"规则没写"同形：d 只证明"清空之后松动"，空表与
    从没写过规则的表在 d 里长得一样。所以这里两件事一起钉：① 表里有那条规则本身
    （角色 `*` 的 `exact:data` / `prefix:data/`）；② 只摘掉 data 那两行之后，
    只有 data 松动、locks 与 events.jsonl 仍拒 —— 于是 data 的拒信来源精确地是那两行。
    """
    have = {rule for who, rule in FT.RESERVED_ARTIFACT_TABLE if who == "*"}
    assert "prefix:data/" in have, have
    assert "exact:data" in have, have
    for rel in LEDGERS:
        assert FT._reserved_ledger(rel) is True, rel
    assert FT._reserved_ledger("data") is True
    assert FT._reserved_ledger("data/.locks/_writer.lock") is True
    assert FT._reserved_ledger("locks/_writer.lock") is True
    assert FT._reserved_ledger("DATA/Usage_Ledger.json") is True, "Windows 上这两个是同一份文件"
    assert FT._reserved_ledger("out/events.jsonl") is True, "事件日志换目录仍是同一本账"
    assert FT._reserved_ledger("out/myevents.jsonl") is False, "后缀规则按分段判，不许吞掉长名字"
    # 与角色无关：没挂角色上下文（脚本直调）同样是拒。
    assert FT._reserved_refusal("data/usage_ledger.json", "") is not None

    kept = tuple(row for row in FT.RESERVED_ARTIFACT_TABLE
                 if row[1] not in ("exact:data", "prefix:data/"))
    assert len(kept) < len(FT.RESERVED_ARTIFACT_TABLE), "data 那两行没找到 ⇒ 这条打桩点在核空气"
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", kept)
    root, reg = _ws(tmp_path / "e")
    rd = _call(reg, "A", "fs.read", path="data/usage_ledger.json")
    assert rd.ok is True, rd
    wr = _call(reg, "A", "fs.write", path="data/usage_ledger.json",
               content='{"lit":0}', overwrite=True)
    assert wr.ok is True, ("data 那两行被摘掉了却还是拒 ⇒ data 的拒信不来自它们", wr)
    assert FT._reserved_ledger("locks/_writer.lock") is True, "摘 data 把 locks 一起摘掉了"
    assert FT._reserved_ledger("out/events.jsonl") is True, "摘 data 把 events.jsonl 一起摘掉了"
