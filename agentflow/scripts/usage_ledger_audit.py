"""`usage_ledger` 的存量重复账审计与清洗（跨进程幂等缺陷的既有数据处理）。

## 为什么需要它（以及为什么它不能顺手改快照了事）

修复前，同一幂等键在两个进程里并发入账会落两行，而两行的 `usage_id`
本来就不同 —— 所以 `verify` 的 `duplicate_id`（按主键数重复）不会响，
`store.validate_table` 也不会响。也就是说：存量重复在现有判据下是完全不可见的。
本脚本补的就是那个缺口。

## 核心陷阱：只改快照是不持久的

`usage_ledger.json` 只是快照，真源之一是 `data/events.jsonl`。
`Store.rebuild()` 会重放全部 `upsert` 事件并按主键 last-write-wins 折叠 ——
于是"把重复行从快照里删掉"这件事，会在下一次 `rebuild` 时被原样复活：
事件还在，行就还在。而 `rebuild` 恰恰是本项目推荐的恢复手段，
也就是说：只改快照的清洗会在用户按文档恢复数据时静默失效。

所以 `--apply` 做两件事，缺一不可：

1. 重写 `usage_ledger.json` 快照；
2. 压实 `events.jsonl`：丢掉被删掉的 `usage_id` 的 `upsert` 事件。

并做一次回放自证：在压实后的事件流上按 `rebuild` 的同一规则折叠一遍，
断言得到的行集合与清洗后的快照一致。不一致就整笔失败（备份原封不动）。
没有这一步，"清洗成功"与"清洗会在下次恢复时失效"在输出上长得一模一样。

## 三态（与 `noai_gate.py` / `release_check.py` 同一纪律）

```text
0 = clean             查过了：没有重复，且每一行都能判定
1 = requires_action   查过了：有重复，或**有行无法判定**（见下）
2 = unknown           **没查成**（工作区/表文件读不到、JSON 坏了）
```

`unknown` 绝不是 `clean`。同理，"这一行没有幂等键"不是"这一行没重复" ——
它是不可判定，必须与干净分开报（本项目的核心教训：把"没检查"与
"检查过了没问题"折叠成同一个"通过"）。

## 判定口径

- 幂等键是 `note` 里一个独立 token，形如 `idem-<12位十六进制>`
  （`modelcost`）或 `settle-<12位十六进制>`（`conductor`）。
- 同一个键出现多行 ⇒ 重复账（多扣了费/额度）。
- 一个键的多行若 `tokens_total` 不一致 ⇒ 标为 `conflicting`：
  这不该发生（同一个键意味着同一次调用）。此时拒绝自动清洗（除非 `--force`），
  因为"该保留哪一行"不再是一个可以机械决定的问题。
- 没有任何可识别键的行（例如直接调 `TokenMeter.charge` 写下的行）⇒ `unmarked`，
  不可判定，只报告不动它。

## 保留哪一行

同一个键的多行里保留 `usage_id` 最小的那一行（字典序，4 位定宽所以等于数值序）。
理由是它确定性且可复核：谁来跑都得到同一个结果，且可写进变更记录。
删除其余行会留下 `usage_id` 空洞 —— `verify` 会报 `id_gap`，而那是
warning（"无害，但值得查"），不是 error；`counters` 无需改动
（删除只会让 `got > want`，而 `verify` 只对 `got < want` 报错）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import schema as S  # noqa: E402
from agentflow.tokenmeter import note_tokens  # noqa: E402

#: 可识别的幂等键形状。与 `tokenmeter.marker_of` 的输出严格一致。
MARKER_RE = re.compile(r"^(?:idem|settle)-[0-9a-f]{12}$")

EXIT_CLEAN = 0
EXIT_REQUIRES_ACTION = 1
EXIT_UNKNOWN = 2

LEDGER_FILE = "usage_ledger.json"
EVENTS_FILE = "events.jsonl"


# --------------------------------------------------------------------- 读


class UnknownError(RuntimeError):
    """"没查成"。绝不降级成"干净"。"""


def _ledger_path(root: Path) -> Path:
    return root / "data" / LEDGER_FILE


def _events_path(root: Path) -> Path:
    return root / "data" / EVENTS_FILE


def load_rows(root: Path) -> list[dict]:
    """读账本行。读不到就抛 `UnknownError` —— 不许把"没查成"折叠成"没有重复"。"""
    p = _ledger_path(root)
    if not p.exists():
        raise UnknownError(
            f"{p} 不存在（工作区没 init 过？路径给错了？）—— "
            "无法判断有没有重复，这与'没有重复'是两件事"
        )
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise UnknownError(f"{p} 不是合法 JSON（{e}）⇒ 先修数据或从 events.jsonl 重建") from e
    rows = doc.get("rows")
    if not isinstance(rows, list):
        raise UnknownError(f"{p} 的 rows 不是数组（收到 {type(rows).__name__}）")
    return rows


# --------------------------------------------------------------------- 审计


def audit(rows: list[dict]) -> dict[str, Any]:
    """把账本按幂等键归组，分出 重复 / 冲突 / 不可判定 / 一行的键。"""
    by_key: dict[str, list[dict]] = defaultdict(list)
    unmarked: list[dict] = []
    multi_key: list[dict] = []

    for r in rows:
        keys = [t for t in note_tokens(r.get("note")) if MARKER_RE.match(t)]
        if not keys:
            unmarked.append(r)
            continue
        if len(keys) > 1:
            # 一行带多个键本身就不该发生：它会让"这一行属于哪一笔"没有唯一答案。
            multi_key.append(r)
            continue
        by_key[keys[0]].append(r)

    duplicates = {k: v for k, v in by_key.items() if len(v) > 1}
    conflicting = {
        k: v for k, v in duplicates.items()
        if len({int(x.get("tokens_total") or 0) for x in v}) > 1
    }
    return {
        "rows": len(rows),
        "keys": len(by_key),
        "single": sum(1 for v in by_key.values() if len(v) == 1),
        "duplicates": duplicates,
        "conflicting": conflicting,
        "unmarked": unmarked,
        "multi_key": multi_key,
        "duplicate_rows": sum(len(v) - 1 for v in duplicates.values()),
        "wasted_tokens": sum(
            sum(int(x.get("tokens_total") or 0) for x in v)
            - int(sorted(v, key=lambda r: str(r.get("usage_id") or ""))[0].get("tokens_total") or 0)
            for v in duplicates.values()
        ),
    }


def plan(audited: dict[str, Any]) -> dict[str, Any]:
    """决定保留/删除哪些行（确定性：每组保留 `usage_id` 最小的那一行）。"""
    keep: set[str] = set()
    drop: set[str] = set()
    for key, group in audited["duplicates"].items():
        ordered = sorted(group, key=lambda r: str(r.get("usage_id") or ""))
        keep.add(str(ordered[0].get("usage_id") or ""))
        drop.update(str(r.get("usage_id") or "") for r in ordered[1:])
    return {"keep": keep, "drop": drop}


# --------------------------------------------------------------------- 回放自证


def fold_usage_events(events_path: Path) -> list[str]:
    """按 `Store.rebuild()` 的同一规则折叠 `usage_ledger` 的 upsert 事件。

    只折叠这一张表（不调用 `Store.rebuild`：那会重写所有表，
    而本脚本的职责只有一个）。返回按首次出现顺序排列的 `usage_id` 列表。

    半行（崩溃时可能产生）保留在事件流里但不参与折叠 —— 与 `rebuild`
    把 `json.loads` 失败的事件记成 `corrupt` 后跳过的处置一致。
    """
    order: list[str] = []
    seen: set[str] = set()
    if not events_path.exists():
        return order
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("op") != "upsert" or e.get("table") != "usage_ledger":
            continue
        uid = str((e.get("row") or {}).get("usage_id") or "")
        if not uid:
            continue
        if uid not in seen:
            seen.add(uid)
            order.append(uid)
    return order


# --------------------------------------------------------------------- 写


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_ledger(root: Path, rows: list[dict]) -> None:
    doc = {"schema_version": S.SCHEMA_VERSION, "rows": rows}
    _atomic_write_text(_ledger_path(root), json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def compact_events(events_path: Path, drop: set[str]) -> dict[str, int]:
    """丢掉被删掉的 `usage_id` 的 upsert 事件（见模块 docstring 的陷阱说明）。"""
    kept: list[str] = []
    dropped = corrupt = 0
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                corrupt += 1
                kept.append(line)          # 半行是证据，留着（rebuild 会记 corrupt）
                continue
            if e.get("op") == "upsert" and e.get("table") == "usage_ledger":
                uid = str((e.get("row") or {}).get("usage_id") or "")
                if uid in drop:
                    dropped += 1
                    continue
            kept.append(line)
    _atomic_write_text(events_path, "".join(x + "\n" for x in kept))
    return {"dropped_events": dropped, "corrupt_kept": corrupt}


def backup(root: Path, dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    saved = []
    for name in (LEDGER_FILE, EVENTS_FILE, "counters.json"):
        src = root / "data" / name
        if src.exists():
            shutil.copy2(src, dest / name)
            saved.append(name)
    return saved


# --------------------------------------------------------------------- 入口


def run(root: Path, *, apply: bool, backup_dir: Path | None, force: bool) -> tuple[int, dict]:
    rows = load_rows(root)
    audited = audit(rows)
    p = plan(audited)

    result: dict[str, Any] = {
        "root": str(root),
        "rows": audited["rows"],
        "keys": audited["keys"],
        "duplicate_keys": len(audited["duplicates"]),
        "duplicate_rows": audited["duplicate_rows"],
        "wasted_tokens": audited["wasted_tokens"],
        "conflicting_keys": sorted(audited["conflicting"]),
        "unmarked_rows": len(audited["unmarked"]),
        "multi_key_rows": len(audited["multi_key"]),
        "applied": False,
    }

    if not audited["duplicates"] and not audited["multi_key"]:
        # 仍然要如实报"有不可判定的行"—— 那不叫干净。
        result["verdict"] = "clean" if not audited["unmarked"] else "requires_action"
        result["note"] = (
            "没有重复键"
            if not audited["unmarked"] else
            f"没有重复键，但有 {len(audited['unmarked'])} 行**没有幂等键** ⇒ 不可判定"
            "（这不是'没重复'，只是'看不出来'）"
        )
        return (EXIT_CLEAN if result["verdict"] == "clean" else EXIT_REQUIRES_ACTION), result

    if not apply:
        result["verdict"] = "requires_action"
        result["plan"] = {"keep": sorted(p["keep"]), "drop": sorted(p["drop"])}
        result["note"] = "只检查（未改动）。加 --apply --backup-dir <目录> 才会清洗。"
        return EXIT_REQUIRES_ACTION, result

    if audited["conflicting"] and not force:
        result["verdict"] = "requires_action"
        result["note"] = (
            f"拒绝自动清洗：{len(audited['conflicting'])} 个键的多行之间 tokens_total 不一致 —"
            "同一个键意味着同一次调用，不一致说明还有别的缺陷在起作用，"
            "保留哪一行不是一个可以机械决定的问题。请人工裁决后用 --force。"
        )
        return EXIT_REQUIRES_ACTION, result

    if backup_dir is None:
        result["verdict"] = "requires_action"
        result["note"] = "--apply 必须同时给 --backup-dir（清洗会改快照与事件流，且本仓库不是 git 仓库）"
        return EXIT_REQUIRES_ACTION, result

    saved = backup(root, backup_dir)
    result["backup"] = {"dir": str(backup_dir), "files": saved}

    kept_rows = [r for r in rows if str(r.get("usage_id") or "") not in p["drop"]]
    removed_usage_ids = sorted(p["drop"] & {str(r.get("usage_id") or "") for r in rows})
    write_ledger(root, kept_rows)
    ev = compact_events(_events_path(root), set(removed_usage_ids))

    # ---- 回放自证：压实后的事件流必须折叠出与清洗后快照相同的行集合。
    # 没有这一步，"清洗成功"与"下次 rebuild 时复活"在输出上长得一模一样。
    replayed = fold_usage_events(_events_path(root))
    snapshot_ids = [str(r.get("usage_id") or "") for r in kept_rows]
    if replayed != snapshot_ids:
        raise UnknownError(
            "回放自证失败：压实后的事件流折叠出的行与清洗后的快照不一致 ——\n"
            f"  事件流折叠：{replayed[:8]}{'…' if len(replayed) > 8 else ''}（{len(replayed)} 行）\n"
            f"  清洗后快照：{snapshot_ids[:8]}{'…' if len(snapshot_ids) > 8 else ''}（{len(snapshot_ids)} 行）\n"
            f"  备份在 {backup_dir}（原文件未被覆盖前请勿继续）。"
            "下一次 rebuild 会把删掉的行复活 ⇒ 这次清洗等于没做。"
        )

    result.update({
        "applied": True,
        "verdict": "clean",
        "removed_rows": len(removed_usage_ids),
        "removed_usage_ids": removed_usage_ids,
        "rows_after": len(kept_rows),
        "events": ev,
        "replay_check": "事件流与快照一致",
        "note": (
            "清洗完成并已自证：删掉的行在 rebuild 之后不会复活。"
            "删除会留下 usage_id 空洞 ⇒ verify 会报 id_gap（warning，无害）。"
        ),
    })
    return EXIT_CLEAN, result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="usage_ledger 存量重复账审计与清洗（默认只检查）",
    )
    ap.add_argument("--root", required=True, help="工作区根目录（data/ 的父目录）")
    ap.add_argument("--apply", action="store_true", help="真的清洗（默认只检查）")
    ap.add_argument("--backup-dir", default=None, help="--apply 必填：备份 data/ 三件套的目录")
    ap.add_argument("--force", action="store_true", help="即使多行之间 token 数不一致也清洗")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        code, result = run(
            root, apply=args.apply,
            backup_dir=Path(args.backup_dir).resolve() if args.backup_dir else None,
            force=args.force,
        )
    except UnknownError as e:
        payload = {"root": str(root), "verdict": "unknown", "error": str(e)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"[unknown] {e}")
        return EXIT_UNKNOWN

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        icon = {"clean": "clean", "requires_action": "requires_action"}[result["verdict"]]
        print(f"[{icon}] {result['root']}")
        print(f"  账本行数={result['rows']}  幂等键={result['keys']}  "
              f"重复键={result['duplicate_keys']}  多余行={result['duplicate_rows']}  "
              f"重复扣掉的 token={result['wasted_tokens']}")
        if result["conflicting_keys"]:
            print(f"  ⚠️ token 数不一致的键：{result['conflicting_keys'][:5]}")
        if result["unmarked_rows"]:
            print(f"  ⚠️ 不可判定（note 里没有幂等键）的行：{result['unmarked_rows']}")
        if result["multi_key_rows"]:
            print(f"  ⚠️ 一行带多个幂等键的行：{result['multi_key_rows']}")
        if result.get("note"):
            print(f"  {result['note']}")
        if result.get("applied"):
            print(f"  已删除 {result['removed_rows']} 行；备份={result['backup']['dir']}")
            print(f"  {result['replay_check']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
