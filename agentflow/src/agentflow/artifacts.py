# -*- coding: utf-8 -*-
"""产物登记：**谁在哪个路径产出了什么**（依据 `draft/28` §153 的 A3/A4 与 R-52）。

## 这一层补的是什么

`tasks.artifacts` 记的是"这次召唤产出了哪些引用"（`table:id` 或 `file:<相对路径>`），
`documents.markdown_path` 记的是"G 渲染的那一份稿件"。两者都只回答**单个对象自己的**
产出面。没有任何地方回答那个在 §153 里连撞两次的问题：

- **A3**（两份"断言台账"同义不同物）：`out/p2-claims-ledger.md` 与
  `out/paper/CLAIMS-LEDGER.md` 并存，而"这个路径归谁"没有登记 —— 于是谁都无法在
  事前判断"我要写的这个路径是不是另一个角色的产物"。
- **A4**（六个产生验收读数的脚本不在可审计对象图里）：`code/*.py` 既非 `experiments`
  行也非 `documents` 行 ⇒ 它们**不在任何对象图里**，产出的读数也就没有可核的来源。
- **R-52**：没有"构建产物"这个对象类型 ⇒ 产出物无法进图；且产物路径没有归属登记。

本模块不去改 `schema.py`（那是 FC-27 禁改区，且"新表"要人裁），而是把这件事做成
**工作区级文件台账**（与 `signatures` 的 `DOC-SIGNATURES.jsonl`、`sessions` 的
`sessions/*.jsonl` 同一形态）：`<工作区根>/ARTIFACTS.jsonl`，一行一条。

## 一条记录里有什么

```text
at         产出时刻（ISO，本地时区）
path       工作区**相对**路径（posix 分隔符；绝对路径与越界路径一律拒收）
sha256     产出时磁盘内容的 sha256（字节级，不做归一化）
bytes      字节数
producer   生产者（角色名 / 工具名 / "M"）
kind       产物类别（自由文本：script / report / paper / task-result / …）
task_id    这次产出属于哪一次召唤（可空）
exit_code  产生它的那次执行的退出码（可空；"没跑过"就不许填 0）
note       人读的补充（可空）
```

## 三态（不许折平）

- **文件找不到** ⇒ `record` **拒收**（fail-closed）。理由：一条"钉不住内容"的登记
  不是弱证据，是**假证据** —— 它让"这个路径有归属"这件事看起来成立。
- **路径越出工作区** ⇒ 拒收。理由与 `agent_e._resolve` 的 `script_path` 闸相同：
  越界写/读不留痕是框架层的红线。
- **台账里的 sha256 与盘上不一致** ⇒ `verify_entries` 报 `changed`（**不是** ok）；
  **读不出来**报 `unreadable`（**不是** missing）；**不在了**报 `missing`。
  三种状态各有各的处置，合成一个"有问题"就没人知道该干什么。

## 它不是判据的执行者

本模块只登记与核对；"这个产物该不该存在""这份读数可不可信"由各自的判据回答。
`unowned()` 是唯一的**判断**：给一组路径，答"哪些**没有**归属登记" —— A4 那六个
脚本正是靠它才看得见。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

#: 台账文件名（工作区根下）。与 `signatures.LEDGER_NAME` 同一层次。
LEDGER_NAME = "ARTIFACTS.jsonl"

#: 一条记录的字段全集（写侧逐字用；读侧容忍缺字段但会在 `verify_entries` 里如实报）。
FIELDS: tuple[str, ...] = (
    "at", "path", "sha256", "bytes", "producer", "kind", "task_id", "exit_code", "note",
)

#: `verify_entries` 的四种状态。刻意不是布尔：`missing`（不在了）与 `unreadable`
#: （还在但读不出来）的处置完全不同，`changed`（被改过）又是第三种。
STATUSES: tuple[str, ...] = ("ok", "changed", "missing", "unreadable", "not_a_file")


class ArtifactError(RuntimeError):
    """登记或核对不成立（越界路径 / 文件不存在 / 不是普通文件）。"""


def ledger_path(root: Any) -> pathlib.Path:
    """`<工作区根>/ARTIFACTS.jsonl`（只算路径，不建文件）。"""
    return pathlib.Path(str(root)) / LEDGER_NAME


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rel_path(root: Any, path: Any) -> str:
    """把 `path` 归一成工作区相对路径（posix 分隔符）；越界则抛 `ArtifactError`。

    为什么要归一：台账是**给人比对**的（"这个路径归谁"），绝对路径会随工作区搬家
    而失效，`\\` 与 `/` 混写会让同一个文件看起来是两条记录。
    """
    root_p = pathlib.Path(str(root)).resolve()
    target = pathlib.Path(str(path))
    if not target.is_absolute():
        target = root_p / target
    try:
        rel = target.resolve().relative_to(root_p)
    except ValueError as e:
        raise ArtifactError(
            f"路径越出工作区：{path!r}（工作区={root_p}）—— 越界的产物不许进台账："
            "登记了它，读者会以为这个路径在我们能看住的范围内"
        ) from e
    return rel.as_posix()


def sha256_of(path: pathlib.Path) -> str:
    """磁盘当前内容的 sha256（十六进制小写）。字节级，不做任何归一化。"""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(
    root: Any,
    *,
    path: Any,
    producer: str,
    kind: str = "file",
    task_id: str = "",
    exit_code: int | None = None,
    note: str = "",
    at: str | None = None,
) -> dict:
    """登记一条产物；返回写进去的那条记录。

    **先核文件再写台账**：文件不存在 / 不是普通文件 ⇒ `ArtifactError`，一个字节都不写。
    （"先记账、后产出"的顺序会让台账成为一份愿望清单 —— 而它唯一的用途是核对。）
    """
    if not str(producer).strip():
        raise ArtifactError("producer 不能为空：不知道是谁产的，这条登记没有归属可言")
    rel = rel_path(root, path)
    full = pathlib.Path(str(root)).resolve() / rel
    if full.is_dir():
        raise ArtifactError(f"不是文件（是目录）：{rel!r} —— 目录的 sha256 没有意义")
    if not full.is_file():
        raise ArtifactError(
            f"文件不存在：{rel!r}（解析为 {full}）—— 产物台账只登记**真的存在**的字节；"
            "钉不住内容的登记不是弱证据，是假证据"
        )
    entry = {
        "at": at or _now(),
        "path": rel,
        "sha256": sha256_of(full),
        "bytes": int(full.stat().st_size),
        "producer": str(producer),
        "kind": str(kind or "file"),
        "task_id": str(task_id or ""),
        "exit_code": exit_code if exit_code is None else int(exit_code),
        "note": str(note or ""),
    }
    p = ledger_path(root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as e:
        raise ArtifactError(f"台账写不进去（{type(e).__name__}: {e}）") from e
    return entry


def read_ledger(root: Any) -> tuple[list[dict], list[str]]:
    """读台账；返回 `(记录, 坏行说明)`。坏行逐条报出，不静默跳过（与 `sessions` 同形）。"""
    p = ledger_path(root)
    if not p.is_file():
        return [], []
    records: list[dict] = []
    problems: list[str] = []
    for i, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError as e:
            problems.append(f"第 {i} 行读不出来（{type(e).__name__}: {e}）")
            continue
        if not isinstance(obj, dict):
            problems.append(f"第 {i} 行不是对象")
            continue
        records.append(obj)
    return records, problems


def verify_entries(root: Any, records: Sequence[Mapping[str, Any]] | None = None) -> list[dict]:
    """逐条核对：台账钉的 sha256 与盘上现在这一版是不是同一版。

    返回每条的 `{path, status, sha256, sha256_now, producer, at, note}`；
    `status` 取 :data:`STATUSES` 之一（**没有布尔**：`missing` 与 `unreadable` 与
    `changed` 是三种不同的处置）。
    """
    if records is None:
        records, _bad = read_ledger(root)
    root_p = pathlib.Path(str(root)).resolve()
    out: list[dict] = []
    for r in records:
        rel = str(r.get("path") or "")
        full = root_p / rel
        row = {"path": rel, "sha256": str(r.get("sha256") or ""),
               "producer": str(r.get("producer") or ""), "at": str(r.get("at") or ""),
               "sha256_now": "", "status": "missing"}
        if full.is_dir():
            row["status"] = "not_a_file"
        elif not full.exists():
            row["status"] = "missing"
        else:
            try:
                row["sha256_now"] = sha256_of(full)
                row["status"] = "ok" if row["sha256_now"] == row["sha256"] else "changed"
            except OSError:
                row["status"] = "unreadable"
        out.append(row)
    return out


def owners_of(root: Any, path: Any) -> list[dict]:
    """这个路径在台账里的**全部**归属记录（按时间序）。空列表 = 没有归属登记。

    为什么返回全部而不是最后一条：同一个路径被两个生产者登记过（A3 那两份台账
    就是这种形态）本身就是一条**发现**，只给最后一条会把它抹掉。
    """
    rel = rel_path(root, path)
    records, _bad = read_ledger(root)
    return [dict(r) for r in records if str(r.get("path") or "") == rel]


def unowned(root: Any, paths: Iterable[Any]) -> list[str]:
    """给定的路径里，**没有**归属登记的（工作区相对路径，排序）。

    这是本模块唯一的**判断**：A4 那六个脚本（`code/*.py`，既非 `experiments` 行
    也非 `documents` 行）正是靠它才看得见 —— "不在可审计对象图里"这句话，
    在没有这条判据之前只能靠人肉比对。
    """
    known = {str(r.get("path") or "") for r in read_ledger(root)[0]}
    out: set[str] = set()
    for p in paths:
        rel = rel_path(root, p)
        if rel not in known:
            out.add(rel)
    return sorted(out)


def list_artifacts(root: Any, *, producer: str | None = None,
                   task_id: str | None = None, kind: str | None = None) -> list[dict]:
    """按生产者 / 召唤 / 类别筛台账（都是精确匹配；`None` = 不筛）。"""
    records, _bad = read_ledger(root)
    out = []
    for r in records:
        if producer is not None and str(r.get("producer") or "") != producer:
            continue
        if task_id is not None and str(r.get("task_id") or "") != task_id:
            continue
        if kind is not None and str(r.get("kind") or "") != kind:
            continue
        out.append(dict(r))
    return out


def summarize(root: Any) -> dict:
    """台账汇总：条数 / 生产者计数 / 类别计数 / 坏行数 / 四态计数。"""
    records, bad = read_ledger(root)
    by_producer: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for r in records:
        by_producer[str(r.get("producer") or "")] = by_producer.get(str(r.get("producer") or ""), 0) + 1
        by_kind[str(r.get("kind") or "")] = by_kind.get(str(r.get("kind") or ""), 0) + 1
    status: dict[str, int] = {}
    for v in verify_entries(root, records):
        status[v["status"]] = status.get(v["status"], 0) + 1
    return {"entries": len(records), "bad_lines": len(bad), "by_producer": by_producer,
            "by_kind": by_kind, "status": status, "problems": list(bad)}


def render_markdown(root: Any, entries: Sequence[Mapping[str, Any]] | None = None) -> str:
    """把台账渲染成一份可进包的表（A4 那六个脚本要的就是这一份）。

    逐条给：路径 / 生产者 / 类别 / 召唤号 / 退出码 / 字节 / sha256（前 16 位）/
    现在的状态。状态列**不许省**：一份只列 sha256 的表会让读者以为"列出来就是对的"。
    """
    if entries is None:
        entries = read_ledger(root)[0]
    status = {v["path"] + "\x00" + v["sha256"]: v["status"]
              for v in verify_entries(root, entries)}
    lines = [
        "# 产物归属登记（由 `agentflow.artifacts` 生成）",
        "",
        "| 路径 | 生产者 | 类别 | 召唤 | 退出码 | 字节 | sha256 | 现状 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in sorted(entries, key=lambda r: (str(r.get("producer") or ""), str(r.get("path") or ""))):
        st = status.get(str(e.get("path") or "") + "\x00" + str(e.get("sha256") or ""), "missing")
        exit_code = e.get("exit_code")
        lines.append(
            f"| `{e.get('path')}` | {e.get('producer')} | {e.get('kind')} | "
            f"{e.get('task_id') or '—'} | {'—' if exit_code is None else exit_code} | "
            f"{e.get('bytes')} | `{str(e.get('sha256') or '')[:16]}` | {st} |"
        )
    lines += ["", f"共 {len(entries)} 条；`现状` 列由 `verify_entries` 现算（"
                  "`ok` / `changed` / `missing` / `unreadable` / `not_a_file`）。", ""]
    return "\n".join(lines)


def selftest() -> int:
    """就地自检：登记 → 核对 → 篡改 → 删除 → 越界 → 坏行。"""
    import tempfile

    base = pathlib.Path(tempfile.mkdtemp(prefix="agentflow_artifacts_"))
    ok = True

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f" —— {detail}" if detail else ""))
        ok = ok and cond

    (base / "out").mkdir()
    f = base / "out" / "r.md"
    f.write_text("内容一", encoding="utf-8")
    e = record(base, path="out/r.md", producer="G", kind="report", task_id="t-0001")
    check("登记成功且哈希是盘上的", e["sha256"] == sha256_of(f), e["sha256"][:16])
    check("核对为 ok", [v["status"] for v in verify_entries(base)] == ["ok"])
    check("归属查询给出生产者", [o["producer"] for o in owners_of(base, "out/r.md")] == ["G"])

    f.write_text("内容二", encoding="utf-8")
    check("篡改后报 changed（不是 ok）", [v["status"] for v in verify_entries(base)] == ["changed"])
    f.unlink()
    check("删除后报 missing（不是 changed）", [v["status"] for v in verify_entries(base)] == ["missing"])

    for bad_path, tag in ((base / "out" / "不存在.md", "文件不存在"), (pathlib.Path("..") / "越界.md", "越界")):
        try:
            record(base, path=bad_path, producer="G")
            check(f"拒收：{tag}", False, "竟然写进去了")
        except ArtifactError as exc:
            check(f"拒收：{tag}", "文件不存在" in str(exc) or "越出工作区" in str(exc), str(exc)[:60])

    with ledger_path(base).open("a", encoding="utf-8") as fh:
        fh.write("{这不是 JSON\n")
    recs, bad = read_ledger(base)
    check("坏行逐条报出", len(recs) == 1 and len(bad) == 1, str(bad))
    check("unowned 能认出没登记的路径",
          unowned(base, [base / "out" / "另一个.md"]) == ["out/另一个.md"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
