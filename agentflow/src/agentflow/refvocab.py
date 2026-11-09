# -*- coding: utf-8 -*-
"""D10 的受控引用词表（B1：纯模块，零 `agentflow` 依赖）。

## 这个模块解决什么

`refs`（交接手稿 / 收工 notify 里的"这一行的依据"）今天有四套写法、两张表：

- `manuscripts.OBJECT_REFS` 认 `stmt/exp/lit/rel/q/c`；
- `schema.CITATION_PREFIXES` 认 `rel/lit/exp/eval/doc/stmt`；
- 携带单另有一套 `stmt/exp/mss`（`depsection.CARRIED_KEYS`）；
- 提示词只教 `stmt:/exp:/lit:/rel:`。

同一个字符串在两张表里结论相反（`doc:` 在 citations 合法、在 refs 非法；`q:`/`c:` 反过来），
而真机已经付过一次代价：收工 `notify.refs` 写 `verifications/000001.jsonl#v-000003`，
被判"前序手稿不在盘上" ⇒ 整份交接没写成。

本模块把"能引什么、每种怎么寻址、怎么核它真的存在"收成一张表，并给两个入口：

- :func:`parse_ref` —— 只判形状（命名空间 / 地址 / 是否 legacy），不读盘；
- :func:`ref_problem` / :func:`ref_reading` —— 在给定工作区根下判存在性。

## 三态（本模块最要紧的一条纪律）

存在性返回值只有三种，不许折平：

| `state` | `checked` | `found` | 含义 |
|---|---|---|---|
| `ok` / `legacy_ok` | True | True | 目标确实在 |
| `missing` | True | False | 查过了，目标确实不在 |
| `unchecked` | False | None | 没查成（没有工作区根 / 表文件不在 / 读不出来） |
| `bad` | False | None | 形状就不成立（前缀不认识 / 号形不对） |
| `ambiguous` | True | None | 查过了，但一个裸稿号命中多个族（不猜） |

"表文件不在"算 `unchecked` 而不是 `missing`：读不到 ≠ 没有。这是 `manuscripts.ref_problem`
当前把"读不出表"说成"引用悬空"的反面。

## 两个文件、一张表（2026-11-09 拆开）

本模块是「解析 + 存在性」那一半：:func:`parse_ref` 判形状（含 legacy 映射），
:func:`ref_reading` 在工作区根下判存在性。词表本身（前缀 → 目标 / 寻址形 / 号形）
搬到了 :mod:`agentflow.refspecs`（纯数据、零读盘），这里按名字回引（re-export）——
`refvocab.parse_ref` / `refvocab.REF_SPECS` 等公开名照旧可用，调用点一个都不用改。

为什么拆：`tools/repo_survey.py` 的软判据（`tests/test_repo_survey_does_not_get_worse.py`）
量「>800 行的 src 文件数」，本模块 839 行越线；处置是拆模块而不是抬基线。搬的是整段
（缩进与注释逐字不动），行为由 `temp/_probe_refvocab.py` 的改前/改后读数对拍。

## 解析与存在性为什么留在同一个文件里

解析（`parse_ref`）只吃形状、不读盘；存在性（`ref_reading`）只读盘、不再判形状。
它们共用"这条引用已经被读成了什么"（`parse_ref` 的返回字典），而"号形怎么写"
（`refspecs` 的 regex 与 `_id_forms` 那一族）在词表那一侧 —— 于是"一个号有几种写法"
永远只有一处，两个文件的边界就是"数据 vs 读它"。

## 为什么是纯模块

两个文件都不 import 任何 `agentflow` 模块（尤其不 import `agent_*`），也不改既有文件。
`:func:`parse_ref` 的命名空间表是字面量；一致性由测试钉（`tests/test_ref_vocabulary_is_one_table.py`
逐条对 `schema.CITATION_PREFIXES` 与 `manuscripts.OBJECT_REFS` 比对），模块本身不制造导入边。

## 与设计文档的关系

口径见 `agentflow/temp/_design_D9_D10.md` §3（词表、legacy 映射、三态、写错时的形态）。
本模块是那份设计的 B1，不含写口接线（B2/B3 才改既有文件）。
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .refspecs import (
    CODE_AMBIGUOUS, CODE_BAD_ADDRESS, CODE_OK, CODE_TARGET_MISSING, CODE_UNCHECKED,
    CODE_UNKNOWN_NAMESPACE, KIND_FILE, KIND_LEDGER, KIND_TABLE, RefSpec,
    REF_NAMESPACES, REF_SPECS, STATE_AMBIGUOUS, STATE_BAD, STATE_LEGACY_OK,
    STATE_MISSING, STATE_OK, STATE_UNCHECKED, _MANUSCRIPT_FAMILIES,
    _MANUSCRIPT_NAME_RE, _PATH_TAIL_RE, _anchor_forms, _id_forms, _looks_like_family,
    _manuscript_from_name, _pad6, _text,
)


def _blank(raw: str) -> dict[str, Any]:
    """`parse_ref` 的完整返回形状（每一格都先给默认值，调用方不用 `.get` 猜键）。"""
    return {
        "raw": raw,
        "ok": False,
        #: 形状是否成立（不是存在性；存在性看 `ref_problem` 的 `checked`）。
        "checked": False,
        "namespace": "",
        "target": "",
        "anchor": "",
        "legacy": False,
        "legacy_from": "",
        "canonical": "",
        "kind": "",
        "target_name": "",
        "code": CODE_OK,
        "why": "",
    }


def _bad(out: dict[str, Any], code: str, why: str) -> dict[str, Any]:
    """把"形状不成立"写进返回字典（`ok=False`；不是异常 —— 引用写错是可读的读数）。"""
    out.update(ok=False, checked=False, code=code, why=why)
    return out


def _legacy_canonical(raw: str) -> tuple[str, str]:
    """legacy 写法 ⇒ `(规范写法, 为什么这样读)`；不是 legacy 返回 `("", "")`。

    ## 为什么 legacy 读成旧形而不拒

    `refs` 是 append-only 账本的证据：作者当时写了什么，要能复核。真机已经付过
    "整份拒"的代价（t-000032 的交接没写成）；把历史写法判成非法，等于让旧证据
    永久背锅。所以：读得出来就映射成规范形，并在读数里标 `legacy`；
    读不出来才进 `bad`。

    覆盖的历史形态（各一条判据，见 `tests/test_ref_vocabulary_is_one_table.py`）：

    - 裸交接号 `0007` / `7` ⇒ `manu:000007`；
    - `verifications/000001.jsonl#v-000003` ⇒ `verif:000001#v-000003`（真机那一形）；
    - `verifications/pending/<sha>.jsonl#u-000001` ⇒ `verif:pending/<sha>#u-000001`；
    - `reports/<family>-<id>.md`（可带 `#…` 或中文散文尾巴）⇒ `mss:<family>-<id>`；
    - `notes/<family>-<id>.md` ⇒ `mss:<family>-<id>`（并说明 `notes/` 不是规范目录）；
    - `documents:<号>` / `document:<号>` ⇒ `doc:<号>`；
    - `conjecture:<号>` ⇒ `c:<号>`；
    - `mss:<号>`（只有号）⇒ `mss:<号>`（族留给存在性判据按"唯一族"裁定）。
    """
    text = _text(raw)
    if not text:
        return "", ""

    # 1) 裸交接号。裸号在历史上一直指"前序交接手稿"，不指命题/实验。
    if re.fullmatch(r"\d{1,6}", text):
        return f"manu:{text.zfill(6)}", (
            "裸号按交接手稿读（`manu:`）；要引命题请写 `stmt:`，引实验请写 `exp:`")

    # 2) 验证台账的文件路径 + 锚（真机那一形）。
    match = re.fullmatch(r"verifications/(\d{1,6})\.jsonl#(v-\d{1,6})", text)
    if match is not None:
        return (f"verif:{match.group(1).zfill(6)}#v-{_pad6(match.group(2)[2:])}",
                "`verifications/<号>.jsonl#<v-id>` 是旧写法；规范形是 `verif:<号>#<v-id>`")
    match = re.fullmatch(
        r"verifications/pending/([0-9a-fA-F]{64})\.jsonl#(u-\d{1,6})", text)
    if match is not None:
        return (f"verif:pending/{match.group(1).lower()}#u-{_pad6(match.group(2)[2:])}",
                "pending 台账的旧写法；规范形是 `verif:pending/<sha>#<u-id>`")

    # 3) 单复数 / 旧前缀别名（历史里各出现过；都是同一张表）。
    match = re.fullmatch(r"documents?:(\d{1,6})", text)
    if match is not None:
        return f"doc:{match.group(1).zfill(6)}", "`documents:` 是旧前缀；规范形是 `doc:`"
    match = re.fullmatch(r"conjecture:(\d{1,6})", text)
    if match is not None:
        return f"c:{match.group(1).zfill(6)}", "`conjecture:` 是旧前缀；规范形是 `c:`"

    # 4) 裸 `mss:` 号（族留给存在性判据；多族命中 ⇒ ambiguous，不猜）。
    match = re.fullmatch(r"mss:(\d{4,6})", text)
    if match is not None:
        return f"mss:{match.group(1).zfill(6)}", (
            "`mss:<号>` 没写族；存在性按唯一族裁定，多族命中会报 ambiguous")

    # 5) `reports/…md` / `notes/…md`（可带 `#…` 或中文散文尾巴）。
    #    先把反斜杠归一：历史里有 `reports\drafts\…` 这种 Windows 写法。
    match = _PATH_TAIL_RE.match(text.replace("\\", "/"))
    if match is not None:
        directory, name, tail = match.group(1), match.group(2), match.group(3)
        family, ident = _manuscript_from_name(name)
        if not family:
            # 像路径但认不出族/号（`-v2` / `F-lemma42-sign.md` 一类）⇒ 不映射，
            # 交给 `parse_ref` 报"前缀不认识"并给出 mss: 的写法。
            return "", ""
        why = f"`{directory}/…md` 是路径写法；规范形是 `mss:{family}-{ident}`"
        if directory == "notes":
            why += "（`notes/` 不是签/收录的规范目录，存在性按 `reports/` 下的规范名核）"
        if tail:
            why += f"；路径后还有 `{_text(tail)[:24]}`，已忽略"
        return f"mss:{family}-{ident}", why

    return "", ""


def parse_ref(text: Any) -> dict[str, Any]:
    """只判形状：这条引用是什么前缀、目标是什么、是不是 legacy。

    ## 返回

    `{raw, ok, checked, namespace, target, anchor, legacy, legacy_from, canonical,
    kind, target_name, code, why}`。`checked` 在这里的含义是"形状已判"，
    不是"目标存在"；存在性看 :func:`ref_problem` / :func:`ref_reading` 的
    `checked` / `found` / `state`。

    ## 为什么先做 legacy 映射再解析规范形

    legacy 与规范形只差一个前缀/分隔符（`verifications/<号>.jsonl#v-x` →
    `verif:<号>#v-x`），先映射再走同一条解析，避免"legacy 一套判据、规范形一套判据"
    两处漂移。`legacy` 标记保留在返回值里，读侧据此区分"作者写的是旧写法"。

    ## 形状不成立时

    返回 `ok=False` + 受控 `code`，不抛异常：引用写错是一次可读的读数，
    不是让整次调用崩掉的理由（真机已经付过"一条 ref 让整份交接不写"的代价）。
    """
    raw = _text(text)
    out = _blank(raw)
    if not raw:
        out.update(ok=False, code=CODE_OK, why="空引用（调用方应先过滤空串）")
        return out

    canonical, legacy_why = _legacy_canonical(raw)
    if canonical:
        out.update(legacy=True, legacy_from=raw, why=legacy_why)
    else:
        canonical = raw

    namespace, sep, rest = canonical.partition(":")
    spec = REF_SPECS.get(namespace)
    if not sep and re.match(r"^(reports|notes)/", raw.replace("\\", "/")):
        return _bad(out, CODE_BAD_ADDRESS,
                    f"引用 {raw!r} 像一条路径，但认不出族/号；"
                    "要引证明稿请写 `mss:<family>-<id>`（family=f-proof/b-proof/e-proof/e-num）")
    if not sep or spec is None:
        known = "/".join(one.namespace for one in REF_NAMESPACES)
        return _bad(out, CODE_UNKNOWN_NAMESPACE,
                    f"引用 {raw!r} 的前缀不认识：认 {known} 这几种，"
                    "或者四位/六位裸交接号")
    if not rest:
        return _bad(out, CODE_BAD_ADDRESS, f"引用 {raw!r} 只有前缀没有目标")

    out.update(namespace=namespace, kind=spec.kind, target_name=spec.target)

    # ---- verif：`<target>#<anchor>`，target 是命题号或 pending/<sha>
    if namespace == "verif":
        if "#" not in rest:
            return _bad(out, CODE_BAD_ADDRESS,
                        f"引用 {raw!r} 缺 `#` 锚：要写成 {spec.address}")
        target, anchor = rest.split("#", 1)
        target = _text(target)
        anchor = _text(anchor)
        if target.startswith("pending/"):
            sha = target[len("pending/"):]
            if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
                return _bad(out, CODE_BAD_ADDRESS,
                            f"pending 台账的名字要是 64 位十六进制 sha256，收到 {sha!r}")
            if not re.fullmatch(r"u-\d{1,6}", anchor):
                return _bad(out, CODE_BAD_ADDRESS,
                            f"pending 台账的行号要是 `u-<数字>`，收到 {anchor!r}")
            target_norm = f"pending/{sha.lower()}"
            anchor_norm = f"u-{_pad6(anchor[2:])}"
        else:
            if not re.fullmatch(r"\d{4,6}", target):
                return _bad(out, CODE_BAD_ADDRESS,
                            f"命题号要是 4-6 位十进制，收到 {target!r}")
            if not re.fullmatch(r"v-\d{1,6}", anchor):
                return _bad(out, CODE_BAD_ADDRESS,
                            f"验证台账的行号要是 `v-<数字>`，收到 {anchor!r}")
            target_norm = _pad6(target)
            anchor_norm = f"v-{_pad6(anchor[2:])}"
        out.update(ok=True, checked=True, target=target_norm, anchor=anchor_norm,
                   canonical=f"verif:{target_norm}#{anchor_norm}")
        return out

    # ---- mss：`<family>-<id>`；裸号是 legacy，族留给存在性判据
    if namespace == "mss":
        family, ident = "", ""
        if re.fullmatch(r"\d{4,6}", rest):
            ident = _pad6(rest)
        else:
            for one in _MANUSCRIPT_FAMILIES:
                prefix = f"{one}-"
                if rest.startswith(prefix):
                    family = one
                    ident = rest[len(prefix):]
                    break
            if not family:
                return _bad(out, CODE_BAD_ADDRESS,
                            f"证明稿要写成 {spec.address}，收到 {rest!r}")
        if family:
            match = _MANUSCRIPT_NAME_RE[family].fullmatch(ident)
            if match is None:
                return _bad(out, CODE_BAD_ADDRESS,
                            f"族 {family} 的号形不对：{ident!r}")
            # `-pN` 是证明号，不是稿号：`mss:` 的地址只到 `<family>-<id>`。
            target = f"{family}-{match.group('id')}"
        else:
            target = ident
        out.update(ok=True, checked=True, target=target,
                   canonical=f"mss:{target}")
        return out

    # ---- 台账行 / manu：纯数字，补 6 位
    if not re.fullmatch(spec.id_pattern, rest):
        return _bad(out, CODE_BAD_ADDRESS,
                    f"引用 {raw!r} 的号形不对：要写成 {spec.address}")
    target = _pad6(rest)
    out.update(ok=True, checked=True, target=target,
               canonical=f"{namespace}:{target}")
    return out


# ---------------------------------------------------------------- 存在性（读盘）


def _root_path(root: Any) -> Path | None:
    """工作区根 ⇒ `Path`；没给/给空 ⇒ `None`（不是当前目录 —— 那会读错工作区）。"""
    text = _text(root)
    return Path(text) if text else None


def _cache_of(cache: Any) -> dict[Any, Any]:
    """调用方给的缓存字典，或本次调用自己的一个（不跨调用共享）。"""
    return cache if isinstance(cache, dict) else {}


def _read_json(path: Path) -> tuple[bool, Any, str]:
    """读一个 JSON 文件 ⇒ `(读成了吗, 内容, 为什么没读成)`；不抛异常。

    为什么把"没读成"与"内容是空的"分开：读不到的表不能当成"没有这一行"。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return False, None, f"`{path}` 读不出来（{type(exc).__name__}: {exc}）"
    try:
        return True, json.loads(text), ""
    except ValueError as exc:
        return False, None, f"`{path}` 不是合法 JSON（{type(exc).__name__}: {exc}）"


def _table_rows(root: Path, table: str, cache: dict[Any, Any]) -> dict[str, Any]:
    """`data/<table>.json` 的 rows ⇒ `{checked, rows, bad_rows, why}`。

    `checked=False` 覆盖三种"没查成"：文件不在、读不出、`rows` 不是数组。
    坏行（不是对象的元素）单独计数：目标没找到而又有坏行时，也不能断言"没有"
    （那一行可能正是坏行里的）。
    """
    key = ("table", table)
    if key in cache:
        return cache[key]
    path = root / "data" / f"{table}.json"
    if not path.is_file():
        got = {"checked": False, "rows": [], "bad_rows": 0,
               "why": f"`data/{table}.json` 不在盘上（读不到 ≠ 没有这一行）"}
        cache[key] = got
        return got
    ok, doc, why = _read_json(path)
    if not ok:
        got = {"checked": False, "rows": [], "bad_rows": 0, "why": why}
        cache[key] = got
        return got
    rows = doc.get("rows") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        got = {"checked": False, "rows": [], "bad_rows": 0,
               "why": f"`data/{table}.json` 的 `rows` 不是数组 ⇒ 没查成"}
        cache[key] = got
        return got
    good = [row for row in rows if isinstance(row, dict)]
    got = {"checked": True, "rows": good, "bad_rows": len(rows) - len(good), "why": ""}
    cache[key] = got
    return got


def _jsonl_rows(path: Path) -> tuple[bool, list[dict[str, Any]], int, str]:
    """读一份追加式 JSONL ⇒ `(读成了吗, 好行, 坏行数, 为什么没读成)`。"""
    if not path.is_file():
        return False, [], 0, f"`{path}` 不在盘上（读不到 ≠ 没有这一行）"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return False, [], 0, f"`{path}` 读不出来（{type(exc).__name__}: {exc}）"
    good: list[dict[str, Any]] = []
    bad = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            one = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(one, dict):
            good.append(one)
        else:
            bad += 1
    return True, good, bad, ""


def _handoff_rows(root: Path, cache: dict[Any, Any]) -> dict[str, Any]:
    """`manuscripts/handoffs.jsonl` 的行 ⇒ `{checked, rows, bad_lines, why}`。"""
    key = ("handoffs",)
    if key in cache:
        return cache[key]
    ok, rows, bad, why = _jsonl_rows(root / "manuscripts" / "handoffs.jsonl")
    got = {"checked": ok, "rows": rows, "bad_lines": bad, "why": why}
    cache[key] = got
    return got


def _verification_rows(root: Path, target: str, cache: dict[Any, Any]) -> dict[str, Any]:
    """验证台账里这一条的目标 ⇒ `{checked, rows, bad_lines, why, found_path}`。

    `target` 是 `verif:` 的 target 部分：`<命题号>` 或 `pending/<sha>`。
    """
    key = ("verif", target)
    if key in cache:
        return cache[key]
    if target.startswith("pending/"):
        paths = [root / "verifications" / "pending" / f"{target[len('pending/'):]}.jsonl"]
    else:
        paths = [root / "verifications" / f"{one}.jsonl" for one in
                 sorted(_id_forms(target), key=len, reverse=True)]
    existing = [path for path in paths if path.is_file()]
    if not existing:
        got = {"checked": False, "rows": [], "bad_lines": 0,
               "why": f"`verifications/` 下没有这条命题的台账（读不到 ≠ 没有这一行）",
               "found_path": ""}
        cache[key] = got
        return got
    all_rows: list[dict[str, Any]] = []
    bad_total = 0
    for path in existing:
        ok, rows, bad, why = _jsonl_rows(path)
        if not ok:
            got = {"checked": False, "rows": [], "bad_lines": 0, "why": why,
                   "found_path": ""}
            cache[key] = got
            return got
        all_rows.extend(rows)
        bad_total += bad
    got = {"checked": True, "rows": all_rows, "bad_lines": bad_total, "why": "",
           "found_path": str(existing[0])}
    cache[key] = got
    return got


def _manuscript_index(root: Path, cache: dict[Any, Any]) -> dict[str, Any]:
    """`reports/` 下的证明稿索引 ⇒ `{checked, by_family, bad_names, why}`。"""
    key = ("mss",)
    if key in cache:
        return cache[key]
    base = root / "reports"
    if not base.is_dir():
        got = {"checked": False, "by_family": {}, "bad_names": 0,
               "why": "`reports/` 不在盘上（读不到 ≠ 没有这一份稿）"}
        cache[key] = got
        return got
    by_family: dict[str, dict[str, str]] = {family: {} for family in _MANUSCRIPT_FAMILIES}
    bad = 0
    try:
        paths = sorted(base.glob("*.md"))
    except OSError as exc:
        got = {"checked": False, "by_family": {}, "bad_names": 0,
               "why": f"`reports/` 读不出来（{type(exc).__name__}: {exc}）"}
        cache[key] = got
        return got
    for path in paths:
        family, ident = _manuscript_from_name(path.name)
        if not family:
            # 只有"像手稿族、但号形不对"的名字才算坏名（`f-proof-abc.md`）；
            # `RESEARCH.md` / `attack-000000.md` 不是手稿，不该阻止"目标确实不在"的判定。
            if _looks_like_family(path.name):
                bad += 1
            continue
        by_family[family][ident] = f"reports/{path.name}"
    got = {"checked": True, "by_family": by_family, "bad_names": bad, "why": ""}
    cache[key] = got
    return got


def _finish(parsed: dict[str, Any], *, state: str, code: str, why: str,
            checked: bool, found: bool | None) -> dict[str, Any]:
    """把 `parse_ref` 的形状读数 + 存在性读数拼成最终返回（键集对调用方稳定）。"""
    out = dict(parsed)
    detail = str(parsed.get("why") or "")
    final_why = why or detail
    if why and detail and detail not in why:
        # legacy 写法没找到时，读数里同时保留"它被读成了什么"与"为什么没找到"。
        final_why = f"{why}；{detail}"
    out.update(state=state, code=code, why=final_why, checked=checked, found=found)
    return out


def ref_reading(text: Any, *, root: Any = "", cache: dict[Any, Any] | None = None
                ) -> dict[str, Any]:
    """一条引用在给定工作区里的完整读数（形状 + 存在性 + legacy 标记）。

    ## 参数

    - `text`：作者写的原文（不要求已规范化；legacy 在这里读成旧形）；
    - `root`：工作区根。不给 ⇒ `state="unchecked"`（没有根就查不了，不猜）；
    - `cache`：可选字典，同一次写/审计里复用表与索引的读取（不跨调用共享）。

    ## 三态

    `state` 是权威读数（`ok` / `legacy_ok` / `missing` / `unchecked` / `bad` /
    `ambiguous`）；`checked` + `found` 是它的机器可读展开。`is_problem()` 只把
    `bad` / `missing` / `ambiguous` 当问题；`unchecked` 不是问题（是"没查成"）。

    ## 为什么 `bad` 也是 `checked=False`

    `checked` 回答的是"目标存在性查过没有"；形状都不成立时没有目标可查。
    调用方要判"这条引用能不能用"应看 `state`/`is_problem()`，不要只看 `checked`。
    """
    parsed = parse_ref(text)
    if not parsed["raw"]:
        return _finish(parsed, state=STATE_OK, code=CODE_OK,
                       why="空引用（不计）", checked=False, found=None)
    if not parsed["ok"]:
        return _finish(parsed, state=STATE_BAD,
                       code=str(parsed.get("code") or CODE_BAD_ADDRESS),
                       why=str(parsed.get("why") or "引用形状不成立"),
                       checked=False, found=None)

    workspace = _root_path(root)
    if workspace is None:
        return _finish(parsed, state=STATE_UNCHECKED, code=CODE_UNCHECKED,
                       why="没有给工作区根 ⇒ 这一条没查成（不是不存在）",
                       checked=False, found=None)

    store = _cache_of(cache)
    namespace = str(parsed["namespace"])
    spec = REF_SPECS[namespace]
    target = str(parsed["target"])
    legacy_state = STATE_LEGACY_OK if parsed.get("legacy") else STATE_OK

    # ---- 台账行
    if spec.kind == KIND_TABLE:
        got = _table_rows(workspace, spec.target, store)
        if not got["checked"]:
            return _finish(parsed, state=STATE_UNCHECKED, code=CODE_UNCHECKED,
                           why=str(got["why"]), checked=False, found=None)
        forms = _id_forms(target)
        found = any(_text(row.get(spec.id_field)) in forms for row in got["rows"])
        if found:
            return _finish(parsed, state=legacy_state, code=CODE_OK, why="",
                           checked=True, found=True)
        if got["bad_rows"]:
            return _finish(parsed, state=STATE_UNCHECKED, code=CODE_UNCHECKED,
                           why=(f"`data/{spec.target}.json` 有 {got['bad_rows']} 行不是对象 ⇒ "
                                "目标没找到也不能断言没有"),
                           checked=False, found=None)
        return _finish(parsed, state=STATE_MISSING, code=CODE_TARGET_MISSING,
                       why=f"引用 {parsed['raw']!r} 不在 `{spec.target}` 台账里",
                       checked=True, found=False)

    # ---- 交接账本
    if spec.kind == KIND_LEDGER and namespace == "manu":
        got = _handoff_rows(workspace, store)
        if not got["checked"]:
            return _finish(parsed, state=STATE_UNCHECKED, code=CODE_UNCHECKED,
                           why=str(got["why"]), checked=False, found=None)
        forms = _id_forms(target)
        found = any(_text(row.get("id")) in forms for row in got["rows"])
        if found:
            return _finish(parsed, state=legacy_state, code=CODE_OK, why="",
                           checked=True, found=True)
        if got["bad_lines"]:
            return _finish(parsed, state=STATE_UNCHECKED, code=CODE_UNCHECKED,
                           why=(f"`manuscripts/handoffs.jsonl` 有 {got['bad_lines']} 行读不出来 ⇒ "
                                "目标没找到也不能断言没有"),
                           checked=False, found=None)
        return _finish(parsed, state=STATE_MISSING, code=CODE_TARGET_MISSING,
                       why=f"引用 {parsed['raw']!r} 的前序手稿不在账本里",
                       checked=True, found=False)

    # ---- 验证台账
    if spec.kind == KIND_LEDGER and namespace == "verif":
        got = _verification_rows(workspace, target, store)
        if not got["checked"]:
            return _finish(parsed, state=STATE_UNCHECKED, code=CODE_UNCHECKED,
                           why=str(got["why"]), checked=False, found=None)
        forms = _anchor_forms(parsed["anchor"])
        found = any(_text(row.get("verification_id")) in forms for row in got["rows"])
        if found:
            return _finish(parsed, state=legacy_state, code=CODE_OK, why="",
                           checked=True, found=True)
        if got["bad_lines"]:
            return _finish(parsed, state=STATE_UNCHECKED, code=CODE_UNCHECKED,
                           why=(f"验证台账有 {got['bad_lines']} 行读不出来 ⇒ "
                                "目标没找到也不能断言没有"),
                           checked=False, found=None)
        return _finish(parsed, state=STATE_MISSING, code=CODE_TARGET_MISSING,
                       why=(f"引用 {parsed['raw']!r} 的那一签不在 "
                            f"`verifications/` 台账里"),
                       checked=True, found=False)

    # ---- 证明稿文件族
    if spec.kind == KIND_FILE:
        got = _manuscript_index(workspace, store)
        if not got["checked"]:
            return _finish(parsed, state=STATE_UNCHECKED, code=CODE_UNCHECKED,
                           why=str(got["why"]), checked=False, found=None)
        by_family = got["by_family"]
        family = ""
        ident = target
        for one in _MANUSCRIPT_FAMILIES:
            prefix = f"{one}-"
            if target.startswith(prefix):
                family = one
                ident = target[len(prefix):]
                break
        if family:
            found = ident in by_family.get(family, {})
            if found:
                return _finish(parsed, state=legacy_state, code=CODE_OK, why="",
                               checked=True, found=True)
            return _finish(parsed, state=STATE_MISSING, code=CODE_TARGET_MISSING,
                           why=(f"引用 {parsed['raw']!r} 指向的 "
                                f"`reports/{family}-{ident}.md` 不在盘上"),
                           checked=True, found=False)
        hits = [(one, by_family[one][ident]) for one in _MANUSCRIPT_FAMILIES
                if ident in by_family.get(one, {})]
        if len(hits) == 1:
            return _finish(parsed, state=legacy_state, code=CODE_OK, why="",
                           checked=True, found=True)
        if len(hits) > 1:
            shown = "、".join(f"{one}-{ident}" for one, _path in hits)
            return _finish(parsed, state=STATE_AMBIGUOUS, code=CODE_AMBIGUOUS,
                           why=(f"裸稿号 {ident!r} 命中多个族（{shown}）⇒ 不猜；"
                                "请写成 `mss:<family>-<id>`"),
                           checked=True, found=None)
        if got["bad_names"]:
            return _finish(parsed, state=STATE_UNCHECKED, code=CODE_UNCHECKED,
                           why=(f"`reports/` 有 {got['bad_names']} 个文件名认不出族/号 ⇒ "
                                "目标没找到也不能断言没有"),
                           checked=False, found=None)
        return _finish(parsed, state=STATE_MISSING, code=CODE_TARGET_MISSING,
                       why=(f"引用 {parsed['raw']!r} 指向的证明稿不在 `reports/` 下"),
                       checked=True, found=False)

    # 词表自洽时走不到这里；走到了就是词表加了 kind 而这里没接。
    return _finish(parsed, state=STATE_UNCHECKED, code=CODE_UNCHECKED,
                   why=f"词表里的 {namespace!r} 是未知目标类 {spec.kind!r} ⇒ 没查成",
                   checked=False, found=None)


#: 兼容名：与 :func:`ref_reading` 是同一个函数（赋值别名，不是第二份实现）。
#:
#: 为什么保留这个名字：既有调用方与设计文档都用 `ref_problem`（"这条引用有什么问题"）；
#: 但"有问题"不该遮住"没查成"这一档，所以真正的读数入口叫 `ref_reading`，这里只做别名。
ref_problem = ref_reading


def _as_reading(reading: Any) -> dict[str, Any]:
    """任意入参 ⇒ 读数字典；不是 Mapping 的当空读数（不抛）。"""
    return dict(reading) if isinstance(reading, Mapping) else {}


def is_problem(reading: Any) -> bool:
    """这条读数算不算"引用有问题"（`unchecked` 不算 —— 它是"没查成"）。"""
    state = str(_as_reading(reading).get("state") or "")
    return state in (STATE_BAD, STATE_MISSING, STATE_AMBIGUOUS)


def is_legacy(reading: Any) -> bool:
    """这条读数是不是走 legacy 写法读通的（不是问题，但要在读数里可见）。"""
    return str(_as_reading(reading).get("state") or "") == STATE_LEGACY_OK


def explain(reading: Any) -> str:
    """一条读数的一句话（回执/日志用；问题点名建议写法，unchecked 明说没查成）。"""
    got = _as_reading(reading)
    state = str(got.get("state") or "")
    raw = str(got.get("raw") or "")
    why = str(got.get("why") or "")
    canonical = str(got.get("canonical") or "")
    if state in (STATE_OK, STATE_LEGACY_OK):
        if state == STATE_LEGACY_OK and canonical and canonical != raw:
            return f"{raw} ⇒ {canonical}（legacy，读得通）"
        return f"{raw}（读得通）"
    if state == STATE_UNCHECKED:
        return f"{raw}：没查成（{why or '没有工作区根'}）—— 不是『不存在』"
    if state == STATE_AMBIGUOUS:
        return f"{raw}：{why}"
    if state == STATE_BAD:
        return f"{raw}：{why}"
    return f"{raw}：{why}（目标不存在）"
