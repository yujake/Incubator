# -*- coding: utf-8 -*-
"""论文对应表（业主 2026-10-22）：G 写正文之前先有这张表，H 依据它逐行核。

业主原话：「G 产出论文时需附上对应表，说明每条定理、引理、命题、例子、实验对应产出物的
真实文件和序号是什么，H 依据此核查，G 也依据此写作」。

## 两个落点、一份内容

- `out/paper/MAPPING.json`：机器读。本模块是它唯一的读侧（解析 + 校验）。
- `out/paper/MAPPING.md`：人读，由 json 生成（`render_markdown`）。不许手写第二份：
  两份不一致时，读 md 的人与读 json 的机器会得到两个结论，而没有任何东西会报错。

## 每一行的字段与口径

| 字段 | 口径 |
|---|---|
| `kind` | 受控词表 `ENV_KINDS`（theorem / lemma / proposition / corollary / example / experiment） |
| `label` | 正文里那个 `\\label{...}` 的值（不带花括号） |
| `env_no` | 正文里第几个该环境，1 起，按同类环境在正文里的出现顺序数（第 2 个 theorem ⇒ 2） |
| `ledger_id` | `stmt:NNNNNN` / `exp:NNNNNN` / `rel:NNNNNN`；多证明带 `#pN`（`stmt:000004#p2`） |
| `file` | 该条完整证明或实验所在的真实文件，相对工作区根（`proofs/thm-main.tex`） |
| `page_or_section` | 可选，给人看的定位（`§3` / `p.7`） |

## 双向都不许有孤儿

正文里每个定理类环境都必须在表里有一行，表里每一行也必须在正文里有一个环境。
两个方向的成因不同：前者是"写了正文没登记"，后者是"登记了但正文里没有它"，
两件事要分开报（合成一句就分不出该改哪一边）。

## 三态

- 表不在盘上 ⇒ `state="unknown"` + `mapping_missing`（不是通过，也不是"表坏了"）；
- 表在、但有 `MAPPING_KINDS` / `MD_KINDS` 里的问题 ⇒ `state="fail"`，逐条列；
- 表在且干净 ⇒ `state="pass"`。

"路径不存在"与"内容为空"必须分得开（`file_state` 的 `missing` 与 `empty`）：
前者是这一行指错了地方，后者是那个文件真的还没写。

## 与 H 的关系（这条边界的由来）

`schema.FINDING_KINDS` 是禁改区里的受控词表，四个 `mapping_*` 不在里面 ⇒ 这一类
暂时落不进 `review_findings`，只能落收工读数（`closing` 的 `mapping` 格）。
词表与分档在 `agent_h/mapping_judge.py`，本模块只负责"表与正文对不对得上"这个事实。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import papercompile as PC
from . import proofloc as PL
from . import schema as S

#: 论文包相对项目根的落点（与 `papercompile` 同一个目录）。
PACKAGE_SUBDIR: tuple[str, ...] = ("out", "paper")

#: 机器读那一份的文件名。
MAPPING_JSON_NAME = "MAPPING.json"

#: 人读那一份的文件名（由 `MAPPING_JSON_NAME` 生成）。
MAPPING_MD_NAME = "MAPPING.md"

#: 正文里要进对应表的六类环境（顺序就是 md 表里 kind 的推荐顺序）。
ENV_KINDS: tuple[str, ...] = (
    "theorem", "lemma", "proposition", "corollary", "example", "experiment",
)

#: 每一行的必填字段（`page_or_section` 可选，见 `OPTIONAL_ROW_FIELDS`）。
ROW_FIELDS: tuple[str, ...] = ("kind", "label", "env_no", "ledger_id", "file")

#: 可选字段。
OPTIONAL_ROW_FIELDS: tuple[str, ...] = ("page_or_section",)

#: 能解析的台账前缀（表名从 `schema.citation_prefix_table` 取，不在这里抄第二份）。
LEDGER_PREFIXES: tuple[str, ...] = ("stmt", "exp", "rel")

#: 表 / 正文 / 文件三条轴上的问题类别（H 认的客观四类，见 `agent_h/mapping_judge.py`）。
#:
#: `mapping_missing`：表不在盘上（或读不出来）；
#: `mapping_orphan`：孤儿 —— 正文里的环境表里没有，或表里的行正文里没有（`detail` 里写方向）；
#: `mapping_unresolvable`：这一行读不懂，或 `ledger_id` 在台账里解析不到；
#: `mapping_file_missing`：`file` 指的路径在盘上不存在。
MAPPING_KINDS: tuple[str, ...] = (
    "mapping_missing", "mapping_orphan", "mapping_unresolvable", "mapping_file_missing",
)

#: 人读那一份的问题类别（同一张表的第二落点）。
#:
#: `md_missing`：`MAPPING.md` 不在盘上；
#: `md_drifted`：它与 `MAPPING.json` 生成出来的内容不一致（手写了一份，或者改了没重生成）。
MD_KINDS: tuple[str, ...] = ("md_missing", "md_drifted")

#: 本模块会产出的全部问题类别（判据要覆盖它，见 `tests/test_paper_mapping_table.py`）。
ALL_PROBLEM_KINDS: tuple[str, ...] = MAPPING_KINDS + MD_KINDS

#: 三态取值。
STATES: tuple[str, ...] = ("pass", "fail", "unknown")

#: 正文里的一类环境：`\\begin{theorem}`（允许带星号，`end` 必须同名同星号）。
_ENV_RE = re.compile(
    r"\\begin\{(?P<kind>" + "|".join(ENV_KINDS) + r")(?P<star>\*?)\}"
    r"(?P<body>.*?)"
    r"\\end\{(?P=kind)(?P=star)\}",
    re.S,
)

#: 环境里的标签（取第一个）。
_LABEL_RE = re.compile(r"\\label\{([^{}]*)\}")

#: 台账代号必须是纯数字（宽度由 `schema.ID_DIGITS` 定，这里只判"是数字"）。
_DIGITS_RE = re.compile(r"^[0-9]+$")


@dataclass(frozen=True)
class Row:
    """对应表里的一行。"""

    kind: str
    label: str
    env_no: int
    ledger_id: str
    file: str
    page_or_section: str = ""

    def to_dict(self) -> dict[str, Any]:
        """写回 json 的形状（字段顺序固定，diff 才读得懂）。"""
        out: dict[str, Any] = {"kind": self.kind, "label": self.label,
                               "env_no": int(self.env_no), "ledger_id": self.ledger_id,
                               "file": self.file}
        if self.page_or_section:
            out["page_or_section"] = self.page_or_section
        return out


@dataclass(frozen=True)
class BodyEnv:
    """正文里的一个定理类环境（`line` 是 1 起的行号）。"""

    kind: str
    label: str
    env_no: int
    line: int


def _problem(kind: str, detail: str, *, label: str = "", where: str = "") -> dict[str, Any]:
    """一条问题（四个字段都要有：kind 是 H 的分档把手，其余是给人看的定位）。"""
    return {"kind": kind, "detail": detail, "label": label, "where": where}


def mapping_paths(project_root: str | Path) -> tuple[Path, Path]:
    """对应表两个落点的绝对路径（`(json, md)`）。"""
    pkg = Path(project_root).joinpath(*PACKAGE_SUBDIR)
    return pkg / MAPPING_JSON_NAME, pkg / MAPPING_MD_NAME


def body_envs(tex: str) -> list[BodyEnv]:
    """正文里全部定理类环境（按出现顺序，`env_no` 按同类计数、1 起）。"""
    text = str(tex or "")
    counts: dict[str, int] = {}
    out: list[BodyEnv] = []
    for m in _ENV_RE.finditer(text):
        kind = str(m.group("kind"))
        counts[kind] = counts.get(kind, 0) + 1
        label = _LABEL_RE.search(m.group("body"))
        out.append(BodyEnv(kind=kind, label=(label.group(1).strip() if label else ""),
                           env_no=counts[kind], line=text.count("\n", 0, m.start()) + 1))
    return out


def read_ledger(workspace_root: str | Path) -> dict[str, list[Mapping[str, Any]]]:
    """从盘上读三张台账表（`<工作区>/data/<表文件>`）。

    为什么读盘而不是读 store：这一格要在收工门里跑，而收工门有"运行外"的出口
    （`agentflow closing`）—— 那里没有 store，只有工作区目录。
    读不出来（不在盘上 / 坏 JSON）⇒ 那张表返回空列表，由"代号在表里找不到"报出来。
    """
    root = Path(workspace_root)
    out: dict[str, list[Mapping[str, Any]]] = {}
    for table in ("statements", "experiments", "relations"):
        name = str((S.TABLES.get(table) or {}).get("file") or "")
        rows: list[Any] = []
        if name:
            path = root / "data" / name
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = None
                if isinstance(payload, Mapping):
                    rows = list(payload.get("rows") or [])
                elif isinstance(payload, list):
                    rows = list(payload)
        out[table] = [r for r in rows if isinstance(r, Mapping)]
    return out


def ledger_ids(ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
               table: str) -> set[str]:
    """某张台账表里已有的全部代号（按 `schema.TABLES` 的 `id_field` 取列）。"""
    field = str((S.TABLES.get(table) or {}).get("id_field") or "")
    ids: set[str] = set()
    if not field:
        return ids
    for row in ((ledger or {}).get(table) or ()):
        if isinstance(row, Mapping):
            got = str(row.get(field) or "")
            if got:
                ids.add(got)
    return ids


def resolve_ledger_id(ledger_id: Any,
                      ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None) -> dict[str, Any]:
    """把一行的 `ledger_id` 解析到台账上。

    返回 `{"ok", "prefix", "table", "row_id", "proof_no", "reason", "ledger_id"}`。

    多证明的尾巴由 `proofloc.parse_used_by_checked` 解析（全仓唯一解析点）。
    坏尾巴必须红，不许折成 `#p1`：折平之后"这一行指的是第 2 条证明"这件事
    就静默变成了"第 1 条"，而台账上两条证明各自指向不同的文件。
    """
    raw = str(ledger_id or "").strip()
    out: dict[str, Any] = {"ledger_id": raw, "ok": False, "prefix": "", "table": "",
                           "row_id": "", "proof_no": PL.DEFAULT_PROOF_NO, "reason": ""}
    if not raw:
        out["reason"] = "`ledger_id` 是空的（它必须指到台账上的某一行）"
        return out
    prefix, sep, rest = raw.partition(":")
    if not sep or not prefix or not rest:
        out["reason"] = (f"`ledger_id` 的写法不对：{raw!r} —— 要 `stmt:000004` 这种"
                         f"（前缀 {list(LEDGER_PREFIXES)} 之一 + 冒号 + 代号）")
        return out
    table = S.citation_prefix_table(prefix)
    if table not in ("statements", "experiments", "relations"):
        out["reason"] = (f"`ledger_id` 的前缀 {prefix!r} 不认：只认 "
                         f"{[p + ':' for p in LEDGER_PREFIXES]}")
        return out
    out["prefix"], out["table"] = prefix, table
    row_id, proof_no = rest, PL.DEFAULT_PROOF_NO
    if "#" in rest:
        if table != "statements":
            out["reason"] = (f"`ledger_id` 带了证明号尾巴（{raw!r}），但证明号只对 "
                             "`stmt:` 有意义 —— `exp:` / `rel:` 没有多证明这一说")
            return out
        row_id, proof_no, problem = PL.parse_used_by_checked(rest)
        if problem:
            out["reason"] = (f"`ledger_id` 的证明号尾巴读不懂：{problem!r} "
                             "（坏尾巴不折成 #p1，也不猜它是第几条）")
            return out
    if not _DIGITS_RE.match(str(row_id)):
        out["reason"] = f"`ledger_id` 的代号不是纯数字：{str(row_id)!r}（收到 {raw!r}）"
        return out
    known = ledger_ids(ledger, table)
    if str(row_id) not in known:
        out["reason"] = (f"`{prefix}:{row_id}` 在 `{table}` 表里没有这一行"
                         f"（该表盘上共 {len(known)} 行）")
        return out
    out["row_id"], out["proof_no"], out["ok"] = str(row_id), int(proof_no), True
    return out


def file_state(workspace_root: str | Path, rel: Any) -> dict[str, Any]:
    """`file` 那一栏在盘上是什么状态。

    四态：`present`（在、非空）· `empty`（在、0 字节）· `missing`（路径不存在）·
    `outside`（不是工作区里的相对路径）· `directory`（路径在、但它是个目录）。

    `empty` 与 `missing` 必须分开：前者是"文件还没写内容"，后者是"根本没有这个文件"。
    把两者折成一个读数，就会把"指错地方"读成"写得短"。
    """
    raw = str(rel or "").strip()
    out: dict[str, Any] = {"file": raw, "state": "missing", "abs": "", "reason": ""}
    if not raw:
        out["state"] = "missing"
        out["reason"] = "`file` 是空的"
        return out
    path = Path(raw)
    root = Path(workspace_root)
    if path.is_absolute():
        out["state"] = "outside"
        out["abs"] = str(path)
        out["reason"] = ("`file` 必须相对工作区根写（收到的是绝对路径 "
                         f"{raw!r}）—— 换一台机器就指不到了")
        return out
    absolute = (root / path).resolve()
    out["abs"] = str(absolute)
    try:
        absolute.relative_to(root.resolve())
    except ValueError:
        out["state"] = "outside"
        out["reason"] = f"`file` 指到了工作区之外：{raw!r}"
        return out
    if absolute.is_dir():
        out["state"] = "directory"
        out["reason"] = f"`file` 指到的是一个目录：{raw!r}"
        return out
    if not absolute.is_file():
        out["state"] = "missing"
        out["reason"] = f"`file` 在盘上不存在：{raw!r}（解析成 {absolute}）"
        return out
    try:
        size = absolute.stat().st_size
    except OSError as exc:
        out["state"] = "missing"
        out["reason"] = f"`file` 读不到大小：{raw!r}（{type(exc).__name__}: {exc}）"
        return out
    out["state"] = "empty" if size == 0 else "present"
    return out


def parse_rows(payload: Any) -> tuple[list[Row], list[dict[str, Any]]]:
    """把 json 的载荷读成行（读不懂的行落一条 `mapping_unresolvable`，不静默丢）。

    载荷同时接受 `{"rows": [...]}` 与裸列表：前者是写侧（`write_mapping`）的形状，
    后者是人手写的常见形状 —— 两种都读，但每一行的字段判据只有一份。
    """
    if isinstance(payload, Mapping):
        raw_rows = payload.get("rows")
    else:
        raw_rows = payload
    problems: list[dict[str, Any]] = []
    if not isinstance(raw_rows, (list, tuple)):
        problems.append(_problem(
            "mapping_unresolvable",
            f"表的形状不对：顶层应当是 `{{\"rows\": [...]}}` 或一个列表，收到 {type(payload).__name__}"))
        return [], problems
    rows: list[Row] = []
    for i, item in enumerate(raw_rows, start=1):
        if not isinstance(item, Mapping):
            problems.append(_problem(
                "mapping_unresolvable", f"第 {i} 行不是对象（收到 {type(item).__name__}）"))
            continue
        missing = [f for f in ROW_FIELDS if not str(item.get(f) if f != "env_no" else item.get(f)).strip()
                   and item.get(f) not in (0,)]
        if missing:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行缺必填字段 {missing}（每行必须有 {list(ROW_FIELDS)}）",
                label=str(item.get("label") or "")))
            continue
        kind = str(item.get("kind") or "").strip()
        if kind not in ENV_KINDS:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `kind` = {kind!r} 不在受控词表 {list(ENV_KINDS)} 里",
                label=str(item.get("label") or "")))
            continue
        label = str(item.get("label") or "").strip()
        if label.startswith("label:"):
            label = label[len("label:"):].strip()
        env_no = item.get("env_no")
        if isinstance(env_no, bool) or not isinstance(env_no, (int, str)):
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `env_no` 不是整数：{env_no!r}", label=label))
            continue
        try:
            env_no_i = int(str(env_no).strip())
        except (TypeError, ValueError):
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `env_no` 读不成整数：{env_no!r}", label=label))
            continue
        if env_no_i < 1:
            problems.append(_problem(
                "mapping_unresolvable",
                f"第 {i} 行的 `env_no` 必须从 1 起：{env_no_i}", label=label))
            continue
        rows.append(Row(kind=kind, label=label, env_no=env_no_i,
                        ledger_id=str(item.get("ledger_id") or "").strip(),
                        file=str(item.get("file") or "").strip(),
                        page_or_section=str(item.get("page_or_section") or "").strip()))
    return rows, problems


def _rows_from_payload(payload: Any) -> tuple[list[Row], list[dict[str, Any]]]:
    """`parse_rows` 的别名（写侧与读侧共用同一份行解析）。"""
    return parse_rows(payload)


def render_markdown(rows: Iterable[Row]) -> str:
    """把行渲染成人读的那一份（表格列顺序固定，任何人都能用同一段代码重生成）。"""
    items = list(rows)
    lines = [
        f"# 论文对应表（`{MAPPING_JSON_NAME}` 的人读版）",
        "",
        f"这一份由 `{MAPPING_JSON_NAME}` 生成，不许手写第二份 —— 两份不一致时，"
        "读 md 的人与读 json 的机器会得出两个结论，而没有东西会报错。",
        "",
        f"重生成：`sync_markdown(项目根)`（`agentflow.papermapping`）。"
        f"`env_no` 的口径：正文里第几个该环境，1 起，按同类环境的出现顺序数。",
        "",
        "| # | kind | label | env_no | ledger_id | file | page_or_section |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, row in enumerate(items, start=1):
        lines.append("| {i} | {kind} | {label} | {no} | {ledger} | {file} | {where} |".format(
            i=i, kind=row.kind, label=row.label or "（没有 label）", no=int(row.env_no),
            ledger=row.ledger_id, file=row.file or "（空）",
            where=row.page_or_section or ""))
    lines.append("")
    counts: dict[str, int] = {}
    for row in items:
        counts[row.kind] = counts.get(row.kind, 0) + 1
    summary = "、".join(f"{k} {counts[k]}" for k in ENV_KINDS if k in counts) or "一行都没有"
    lines.append(f"合计 {len(items)} 行：{summary}。")
    lines.append("")
    return "\n".join(lines)


def _norm_text(text: str) -> str:
    """比对两份 markdown 时的归一化：只压掉行尾空白与首尾空行（内容一个字符都不放过）。"""
    body = str(text or "").replace("\r\n", "\n")
    return "\n".join(line.rstrip() for line in body.split("\n")).strip("\n")


def write_mapping(project_root: str | Path, rows: Iterable[Row]) -> tuple[Path, Path]:
    """写两份（json 与 md），返回它们的路径。

    只走这一个写口：两份由同一次 `rows` 生成，于是"手写第二份"在结构上不可能发生。
    """
    items = list(rows)
    json_path, md_path = mapping_paths(project_root)
    payload = {"rows": [row.to_dict() for row in items]}
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    md_path.write_bytes(render_markdown(items).encode("utf-8"))
    return json_path, md_path


def sync_markdown(project_root: str | Path) -> Path:
    """按盘上的 json 重生成 md（改了 json 之后唯一合法的修法）。"""
    json_path, md_path = mapping_paths(project_root)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    rows, _problems = parse_rows(payload)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_bytes(render_markdown(rows).encode("utf-8"))
    return md_path


def _md_reading(project_root: Path, rows: Sequence[Row]) -> tuple[str, list[dict[str, Any]]]:
    """人读那一份的状态（`present` / `missing` / `drifted` / `unreadable`）与问题。"""
    _json_path, md_path = mapping_paths(project_root)
    problems: list[dict[str, Any]] = []
    if not md_path.is_file():
        problems.append(_problem(
            "md_missing",
            f"人读那一份不在盘上：{md_path} —— 由 json 生成（`sync_markdown`），"
            "不许只交机器读那一份（H 与业主读的是这一份）"))
        return "missing", problems
    try:
        got = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        problems.append(_problem(
            "md_drifted", f"人读那一份读不出来：{md_path}（{type(exc).__name__}: {exc}）"))
        return "unreadable", problems
    want = render_markdown(rows)
    if _norm_text(got) != _norm_text(want):
        problems.append(_problem(
            "md_drifted",
            f"{md_path.name} 与 {MAPPING_JSON_NAME} 生成出来的内容不一致 —— "
            "它被手写过、或者 json 改了没重生成（`sync_markdown` 重生成一次）"))
        return "drifted", problems
    return "present", problems


def _orphan_problems(envs: Sequence[BodyEnv], rows: Sequence[Row]) -> list[dict[str, Any]]:
    """双向孤儿（正文有环境表里没有 / 表里有行正文没有 / 序号对不上 / label 重复）。"""
    problems: list[dict[str, Any]] = []
    body_by_key: dict[tuple[str, str], list[BodyEnv]] = {}
    for env in envs:
        body_by_key.setdefault((env.kind, env.label), []).append(env)
    row_by_key: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        row_by_key.setdefault((row.kind, row.label), []).append(row)

    for key, got in body_by_key.items():
        kind, label = key
        if not label:
            for env in got:
                problems.append(_problem(
                    "mapping_orphan",
                    f"正文第 {env.line} 行的 {kind} 环境没有 \\label —— 没有 label 就无法在表里"
                    "指到它（先给它一个 label，再在表里登记一行）",
                    where=f"{PC.TEX_NAME}:{env.line}"))
            continue
        if len(got) > 1:
            problems.append(_problem(
                "mapping_orphan",
                f"正文里 label={label!r} 的 {kind} 出现了 {len(got)} 次"
                f"（第 {[e.line for e in got]} 行）—— 重复的 label 无法与表行一一对应",
                label=label, where=f"{PC.TEX_NAME}:{got[0].line}"))
            continue
        matched = row_by_key.get(key) or []
        if not matched:
            env = got[0]
            problems.append(_problem(
                "mapping_orphan",
                f"正文第 {env.line} 行的 {kind}（label={label!r}，第 {env.env_no} 个 {kind}）"
                "在表里没有对应行 —— 正文有、表里没有，就是一个孤儿环境",
                label=label, where=f"{PC.TEX_NAME}:{env.line}"))
            continue
        env = got[0]
        for row in matched:
            if int(row.env_no) != int(env.env_no):
                problems.append(_problem(
                    "mapping_orphan",
                    f"表里 label={label!r} 那行写的是第 {row.env_no} 个 {kind}，"
                    f"而正文里它是第 {env.env_no} 个（正文第 {env.line} 行）—— "
                    "同一行对不上同一个环境",
                    label=label, where=f"{PC.TEX_NAME}:{env.line}"))

    for key, got in row_by_key.items():
        kind, label = key
        if not label:
            problems.append(_problem(
                "mapping_orphan",
                f"表里有 {len(got)} 行 {kind} 的 label 是空的 —— 空 label 在正文里指不到任何环境",
                where=MAPPING_JSON_NAME))
            continue
        if len(got) > 1:
            problems.append(_problem(
                "mapping_orphan",
                f"表里 label={label!r} 出现了 {len(got)} 行 —— 重复的行无法与正文环境一一对应",
                label=label, where=MAPPING_JSON_NAME))
            continue
        if key not in body_by_key:
            problems.append(_problem(
                "mapping_orphan",
                f"表里的行 label={label!r}（{kind} 第 {got[0].env_no} 个）在正文里找不到"
                f"对应环境（正文里有 {len(body_by_key)} 个环境）—— 表有、正文没有，"
                "就是一个孤儿行",
                label=label, where=MAPPING_JSON_NAME))
    return problems


def mapping_reading(project_root: str | Path, *,
                    workspace_root: str | Path | None = None,
                    ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
                    tex: str | None = None) -> dict[str, Any]:
    """读一个项目的对应表并校验（纯读，不写盘）。

    三态：`pass` / `fail` / `unknown`（`unknown` 是"没查成 / 不适用"，绝不是通过）。
    `problems` 里每一条都带 `kind`（取值在 `ALL_PROBLEM_KINDS` 里），
    由 `agent_h.mapping_judge.level_of` 决定它拦不拦门。
    """
    project = Path(project_root)
    workspace = Path(workspace_root) if workspace_root is not None else project
    json_path, md_path = mapping_paths(project)
    reading: dict[str, Any] = {
        "checked": False,
        "state": "unknown",
        "project_root": str(project),
        "workspace_root": str(workspace),
        "mapping_json": str(json_path),
        "mapping_md": str(md_path),
        "rows": 0,
        "envs": 0,
        "md_state": "",
        "empty_files": [],
        "problems": [],
        "reason": "",
    }
    if not json_path.is_file():
        reading["problems"] = [_problem(
            "mapping_missing",
            f"对应表不在盘上：{json_path} —— G 写正文之前必须先有它"
            f"（`out/paper/{MAPPING_JSON_NAME}` 与 `out/paper/{MAPPING_MD_NAME}`）")]
        reading["reason"] = ("对应表不存在 ⇒ 这一格没查成（不是通过，也不是表里有问题）；"
                             "先让 G 把它写出来再核一遍")
        return reading

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        reading["checked"] = True
        reading["state"] = "fail"
        reading["problems"] = [_problem(
            "mapping_unresolvable",
            f"对应表在盘上但读不出来：{json_path}（{type(exc).__name__}: {exc}）")]
        reading["reason"] = "表在盘上、但没有一行是能读的（先修 json 语法）"
        return reading

    rows, problems = _rows_from_payload(payload)
    reading["rows"] = len(rows)
    reading["checked"] = True

    md_state, md_problems = _md_reading(project, rows)
    reading["md_state"] = md_state
    problems += md_problems

    if tex is None:
        tex_path = json_path.parent / PC.TEX_NAME
        tex_text = tex_path.read_text(encoding="utf-8") if tex_path.is_file() else ""
    else:
        tex_text = str(tex)
    envs = body_envs(tex_text)
    reading["envs"] = len(envs)

    if not str(tex_text or "").strip():
        problems += [p for p in reading["problems"]]
        reading["problems"] = problems
        reading["state"] = "unknown"
        reading["reason"] = (f"这个项目没有论文正文（{json_path.parent / PC.TEX_NAME} 不在盘上）"
                             "⇒ 对应表没有可对的东西（不适用，不是通过）")
        return reading

    problems += _orphan_problems(envs, rows)

    for row in rows:
        got = resolve_ledger_id(row.ledger_id, ledger if ledger is not None else read_ledger(workspace))
        if not got["ok"]:
            problems.append(_problem(
                "mapping_unresolvable",
                f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个）的 "
                f"`ledger_id` = {row.ledger_id!r} 在台账里解析不到：{got['reason']}",
                label=row.label, where=MAPPING_JSON_NAME))
            continue
        if got["proof_no"] != PL.DEFAULT_PROOF_NO and got["table"] != "statements":
            problems.append(_problem(
                "mapping_unresolvable",
                f"表里 label={row.label!r} 的 `ledger_id` = {row.ledger_id!r} 带了证明号尾巴，"
                "而它指的不是 `statements`",
                label=row.label, where=MAPPING_JSON_NAME))

    for row in rows:
        state = file_state(workspace, row.file)
        if state["state"] == "empty":
            reading["empty_files"].append(state["file"])
            continue
        if state["state"] == "present":
            continue
        kind = "mapping_file_missing" if state["state"] in ("missing", "directory") \
            else "mapping_unresolvable"
        problems.append(_problem(
            kind,
            f"表里 label={row.label!r}（{row.kind} 第 {row.env_no} 个）的 `file` "
            f"读不到：{state['reason']}",
            label=row.label, where=MAPPING_JSON_NAME))

    reading["problems"] = problems
    if problems:
        reading["state"] = "fail"
        counts: dict[str, int] = {}
        for p in problems:
            counts[p["kind"]] = counts.get(p["kind"], 0) + 1
        reading["reason"] = ("表在盘上、但有 {n} 处问题（{by}）—— 逐条见 problems".format(
            n=len(problems), by="、".join(f"{k} {v}" for k, v in counts.items())))
    else:
        reading["state"] = "pass"
        reading["reason"] = (f"{len(rows)} 行与正文 {len(envs)} 个环境逐一对上，"
                             f"`ledger_id` 都能在台账里解析到，`file` 都在盘上")
    return reading
