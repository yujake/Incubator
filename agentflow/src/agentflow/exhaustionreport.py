# -*- coding: utf-8 -*-
"""E 的 ②③ 落盘：程序设计思路与穷举论证要落成盘上一份可核的读数（业主 2026-10-23 晚）。

业主原话（逐字）：「E 写的报告要能落下来，且 V 也要会审这种东西，加 E 派 V 的边」。

## 这一格解决什么

改前 ②③ 只活在 `experiments.observations` 的自由格里（脚本自报，E 原样收下）：
读的人能看见那两段字，但它们不是一个"可引用的落点"—— B 登记时只能把文本贴进
`statements.proof_text`，G 在正文里也没法指向一份文件，V 更没有材料可核。
于是出现"写了但没落地"：台账上有字、盘上没有东西。

现在 ②③ 的载体是盘上一份 markdown：`out/experiments/<实验号>/exhaustion.md`。
落点是固定的（不是随手起的名字）、相对仓库根稳定（不是绝对路径）、且与论文对应表
那一格 `papermapping` 的 `exhaustion_note` 认的是同一个位置 —— 于是 E 写一份、
B 登记时指它、G 在正文里引它、V 审它，四处说的是同一份东西。

## 判据只有一份：`exhaustion_problems`

它是"这份读数在不在、三块齐不齐"的唯一实现。`numericproof.report_problems` 只是一次
转发（那一侧的 `exhaustion_problems` 是穷尽判定的唯一入口），所以：

- E 写侧：报告没落成 / 三块不齐 ⇒ 那条证据降档（`numericproof.sign_experiment` 的
  等级由 `exhaustion_problems` 单点决定 ⇒ 落成 cross_check，不是 proof）；
- B 的入库闸：证明栏三段齐但落盘核查不过 ⇒ 受控拒绝（`numericproof.filing_problems`）；
- V 的会审：缺材料 ⇒ `看不出来` 并点名缺哪一块，不许判 `成立`。

## 三态纪律：事实写在行上，盘上再核一次

`land_report` 写完立刻读回来算字节数与 sha256，把这几个事实写进
`observations["exhaustion_report"]`。为什么事实要写进行上而不是每次现读盘：

1. `schema.Experiment.validate` 是纯的（拿不到工作区根），它必须能判"这一行到底有没有
   一份落过盘的读数" —— 判据只能读行上的事实；
2. 但"行上说落过"与"盘上真的在"是两件事，所以写侧记录的是「读回来」的字节数与
   sha256（不是"我调了写函数"这个意图），读侧（V 的会审、B 的入库闸）拿到工作区根时
   再按这两个数核一次（:func:`disk_problems`）。核不上 ⇒ 那一份读数不认。

## 缺一块与缺文件都不是"没问题"

`exhaustion_problems` 返回空清单才是"报告在、三块齐"。缺文件、空文件、读不出来、
缺「程序设计思路」、缺「穷举论证」、缺署名、缺读数编号 —— 每一档都逐条写清缺什么，
因为下游（E 的降档、B 的拒信、V 的 findings）都要照着那句话去补。
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

#: ②③ 的落点（唯一口径）：`out/experiments/<实验号>/exhaustion.md`。
#:
#: 为什么是 `out/experiments` 而不是 `code/exp`：同一趟实验的原始输出已经落在
#: `out/experiments/<实验号>.log`（`agent_e._support._write_run_log`），
#: 把它与 E 写的读数放在同一个父目录下，读的人按实验号找一次就够；
#: 而 `code/` 是"可执行的东西"那一格，报告不是程序。
REPORT_DIR = "out/experiments"
#: 报告文件名（与论文对应表 `exhaustion_note` 那一格认的形态一致）。
REPORT_NAME = "exhaustion.md"
#: 落在 `observations` 里的那一格（写侧记录"落过什么"，读侧核它）。
REPORT_KEY = "exhaustion_report"

#: 三块的标题（逐字；`numerictheorem.blocks_missing` 与 G 的正文引的是同一批记号）。
BLOCK_DESIGN = "程序设计思路"
BLOCK_EXHAUSTION = "穷举论证"
BLOCK_ENVIRONMENT = "运行环境"
#: 署名（业主：②③ 由 E 写）。
AUTHOR_MARKER = "作者：E"
AUTHOR_ROLE = "E"
#: 签字的那一位（业主 2026-10-23 晚的更正：签字仍由 V 签，E 只是 ②③ 的作者）。
SIGNER_ROLE = "V"

#: 读数编号的前缀（`exp:000000`；与 `schema` 的引用前缀同一套）。
EVIDENCE_PREFIX = "exp:"
#: 报告里必须逐字出现的记号（顺序即业主口径的顺序）。
NOTE_MARKERS: tuple[str, ...] = (BLOCK_DESIGN, BLOCK_EXHAUSTION, BLOCK_ENVIRONMENT)
#: 读数编号的形状（判"写没写出处"）。
_EVIDENCE_ID_RE = re.compile(r"exp:[0-9]+")
#: 实验号的形状（判"路径是不是落在那条实验的目录里"）。
_ID_RE = re.compile(r"^[0-9]{4,}$")

#: `blocks` 那一格的三段键名（与上面的标题一一对应）。
DESIGN = "design"
ENUMERATION = "enumeration"
ENVIRONMENT = "environment"


# ---------------------------------------------------------------- 落点


def report_relpath(experiment_id: Any) -> str:
    """这条实验的读数该落在哪（相对仓库根）；实验号不合法 ⇒ 空串（不猜一个位置）。"""
    eid = str(experiment_id or "").strip()
    if not _ID_RE.match(eid):
        return ""
    return f"{REPORT_DIR}/{eid}/{REPORT_NAME}"


def is_report_relpath(value: Any) -> bool:
    """这一串字是不是"落点那一形态"的相对路径（`out/experiments/<数字>/exhaustion.md`）。

    只判形态，不判它在不在盘上（"盘上在不在"是 `read_report` 的事）。
    绝对路径 / 含 `..` / 盘符一律不认：那会让"报告在哪"变成一个随机器变的位置。
    """
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ":" in raw:
        return False
    if ".." in raw.split("/"):
        return False
    parts = raw.split("/")
    if len(parts) != 4:
        return False
    if parts[0] != "out" or parts[1] != "experiments":
        return False
    if not _ID_RE.match(parts[2]):
        return False
    return parts[3] == REPORT_NAME


def _resolve(root: str | Path | None, rel: Any) -> tuple[Path | None, str]:
    """把一条相对仓库根的路径解析成绝对路径（越界 / 没给根 ⇒ None + 理由）。"""
    if root is None:
        return None, "这一趟没给工作区根 ⇒ 这条相对路径无从解析（不是「合规」）"
    text = str(rel or "").strip().replace("\\", "/")
    if not text:
        return None, "路径是空的"
    candidate = Path(text)
    if candidate.is_absolute() or ":" in text:
        return None, "必须是相对仓库根的路径（收到绝对路径）"
    if ".." in text.split("/"):
        return None, "不许用 `..` 跳出仓库根"
    base = Path(root).resolve()
    target = (base / candidate).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None, "解析之后跑到仓库根外面去了"
    return target, ""


# ---------------------------------------------------------------- 写侧


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def blocks_from(*, observations: Mapping[str, Any] | None,
                certificate: Mapping[str, Any] | None = None,
                search_bound: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """②③ 两段的原文与搜索空间（读口只有一处：`numericproof` 的那几个读函数）。

    为什么不在这里再写一份"从哪一格读 design / enumeration"：别名（`coverage`）、
    三处出处（observations / certificate.detail / search_bound）与优先级都是
    `numericproof` 的口径，抄一份就会长出第二个答案 —— 而"同一份读数被读成两段不同的话"
    正是 E 与 V 之间最容易出错的地方。这里只做转发。

    返回 `{"design","enumeration","search_space","where"}`：前两个是 E 写的原文
    （可能为空：那就说明这一趟没有 ②③，报告里如实写"没有给出"），
    `search_space` 是判据认的那一份（`search_bound` 优先，与穷尽判定同一优先级）。
    """
    from . import numericproof as NP

    obs = _as_mapping(observations)
    cert = _as_mapping(certificate)
    bound = _as_mapping(search_bound)
    design, design_where = NP._design_reading(obs, cert, bound)
    enumeration, enumeration_where = NP._enumeration_reading(obs, cert, bound)
    space, space_where = NP._space_reading(obs, cert, bound)
    return {
        "design": design,
        "enumeration": enumeration,
        "search_space": space,
        "where": {"design": design_where, "enumeration": enumeration_where,
                  "search_space": space_where},
    }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    """落盘那一刻的时间戳（与 `schema.now_iso` 同一形态；这里不 import schema 免得成环）。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_text(value: Any) -> str:
    """一格自由读数进报告时的写法（不做排序归一：原样给，读的人才知道脚本报了什么）。"""
    import json

    try:
        return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def compose_report(*, experiment_id: Any, claim: Any, claim_key: Any,
                   script_path: Any, script_sha256: Any = "",
                   design: Any, enumeration: Any,
                   search_space: Any = None, environment: Any = "",
                   result: Any = "", evidence_kind: Any = "") -> str:
    """把 ②③ 拼成盘上那一份读数（纯函数：给定同一批事实，逐字节同一份文本）。

    形态（段序固定、标题逐字；`numerictheorem.blocks_missing` 与 G 的正文都按它核）::

        # exp:000000 的数值实验读数（作者：E）

        - 命题：...
        - 程序：code/enum.py（sha256 ...）
        - 搜索空间：{...}
        - 结论：supports（等级 cross_check）

        ## 程序设计思路

        ...

        ## 穷举论证

        ...

        ## 运行环境

        Python 3.x / exit_code=0 / runtime=0.12s

        作者：E
    """
    rel = report_relpath(experiment_id)
    eid = str(experiment_id or "").strip()
    header = [
        f"# {EVIDENCE_PREFIX}{eid} 的数值实验读数（{AUTHOR_MARKER}）",
        "",
        f"- 命题：{str(claim or '').strip()}",
        f"- 命题键：{str(claim_key or '').strip()}",
        f"- 程序：{str(script_path or '').strip()}"
        + (f"（sha256 {str(script_sha256).strip()}）" if str(script_sha256 or "").strip() else ""),
    ]
    if search_space is not None:
        header.append(f"- 搜索空间：{_json_text(search_space)}")
    header.append(
        f"- 结论：{str(result or '').strip() or '（未记）'}"
        f"（等级 {str(evidence_kind or '').strip() or '（未记）'}）")
    header.append(f"- 读数落点：{rel or '（实验号不合法，没有落点）'}")
    body = [
        "",
        f"## {BLOCK_DESIGN}",
        "",
        str(design or "").strip(),
        "",
        f"## {BLOCK_EXHAUSTION}",
        "",
        str(enumeration or "").strip(),
        "",
        f"## {BLOCK_ENVIRONMENT}",
        "",
        str(environment or "").strip(),
        "",
        AUTHOR_MARKER,
        "",
    ]
    return "\n".join(header + body)


def land_report(root: str | Path, *, experiment_id: Any, claim: Any, claim_key: Any,
                 script_path: Any, design: Any, enumeration: Any,
                 script_sha256: Any = "", search_space: Any = None,
                 environment: Any = "", result: Any = "",
                 evidence_kind: Any = "") -> dict[str, Any]:
    """把 ②③ 落成 `out/experiments/<实验号>/exhaustion.md`，并读回来记下事实。

    返回的 `exhaustion_report` 事实（写进 `observations[REPORT_KEY]`）::

        {"path": "out/experiments/000000/exhaustion.md", "bytes": 1832,
         "sha256": "...", "ok": True, "problems": [],
         "blocks": {"design": 42, "enumeration": 120, "environment": 30},
         "missing": [], "experiment_id": "000000", "at": "..."}

    三种失败都照实写进 `problems`（不抛异常、也不假装成了）：
    实验号不合法（没有落点）、目录建不起来、写不进去 / 读不回来。
    为什么不抛：这一趟实验已经真的跑过了，报告没落成是"这一条证据不够 proof"，
    不是"这次实验不算" —— 把它抛上去会让调用方以为实验本身失败。
    """
    problems: list[str] = []
    facts: dict[str, Any] = {
        "path": "", "bytes": 0, "sha256": "", "ok": False, "problems": problems,
        "blocks": {}, "missing": [], "experiment_id": str(experiment_id or "").strip(),
        "at": "",
    }
    rel = report_relpath(experiment_id)
    if not rel:
        problems.append(
            f"实验号 {experiment_id!r} 不是 {_ID_RE.pattern} 那一形态 ⇒ 没有固定落点，"
            "报告无处可落（这一条因此拿不到 proof）")
        return facts
    facts["path"] = rel
    text = compose_report(
        experiment_id=experiment_id, claim=claim, claim_key=claim_key,
        script_path=script_path, script_sha256=script_sha256, design=design,
        enumeration=enumeration, search_space=search_space,
        environment=environment, result=result, evidence_kind=evidence_kind)
    target, why = _resolve(root, rel)
    if target is None:
        problems.append(f"报回落点解析不了：{why}")
        return facts
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # 按字节写（不做换行翻译）：盘上那一份的字节数与 sha256 必须与这里算的同一份，
        # 而 `write_text` 在 Windows 上会把 `\n` 翻成 `\r\n` ⇒ 行上的字节数对不上盘上那份。
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, target)
    except OSError as exc:
        leftover = ""
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError as cleanup_exc:
                # 连临时文件都清不掉：那一份残留要留在读数里（静默吞掉它就成了一份
                # 没人知道的垃圾文件，而"落盘失败"的原因会被下一趟的人误读成磁盘满）。
                leftover = (f"；临时文件 {tmp.name} 没清掉"
                            f"（{type(cleanup_exc).__name__}: {cleanup_exc}）")
        problems.append(
            f"报告写不进去：{rel}（{type(exc).__name__}: {exc}{leftover}）⇒ ②③ 没有落在盘上，"
            "这一条拿不到 proof")
        return facts
    # 读回来：落过盘的事实只能从盘上取（"我调了写函数"不是事实）。
    got = read_report(root, rel)
    if not got.get("ok"):
        problems.extend(list(got.get("problems") or []))
        return facts
    facts.update({
        "bytes": int(got.get("bytes") or 0),
        "sha256": str(got.get("sha256") or ""),
        "blocks": dict(got.get("blocks") or {}),
        "missing": list(got.get("missing") or []),
        "ok": True,
        "at": _now_iso(),
    })
    return facts


# ---------------------------------------------------------------- 读侧


def read_report(root: str | Path | None, rel: Any) -> dict[str, Any]:
    """读一份 ②③ 读数：`{"ok","state","path","bytes","sha256","text","blocks","missing","problems"}`。

    `state` 五档：`present` / `outside`（路径不合口径或越界）/ `missing`（盘上没有）/
    `empty`（空文件）/ `unreadable`（读不出来）。后四档都带一条 `problems` 说明，
    因为"读不到"与"读过、没问题"必须分得开（三态纪律）。
    """
    out: dict[str, Any] = {
        "ok": False, "state": "outside", "path": str(rel or "").strip().replace("\\", "/"),
        "bytes": 0, "sha256": "", "text": "", "blocks": {}, "missing": [],
        "problems": [],
    }
    raw = str(rel or "").strip().replace("\\", "/")
    if not raw or not is_report_relpath(raw):
        out["problems"] = [
            f"读数落点不合口径（{raw!r}）：要的是 "
            f"{REPORT_DIR}/<实验号>/{REPORT_NAME} 这一形态的相对路径"]
        return out
    target, why = _resolve(root, raw)
    if target is None:
        out["problems"] = [f"读数落点解析不了：{why}"]
        return out
    if not target.is_file():
        out["state"] = "missing"
        out["problems"] = [f"报告不在盘上：{raw}（E 决定过 ②③，但没有落成这份文件）"]
        return out
    try:
        payload = target.read_bytes()
    except OSError as exc:
        out["state"] = "unreadable"
        out["problems"] = [f"报告读不出来：{out['path']}（{type(exc).__name__}: {exc}）"]
        return out
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        out["state"] = "unreadable"
        out["problems"] = [f"报告不是 UTF-8 文本：{out['path']}（{exc}）"]
        return out
    # sha256 算在字节上（那是盘上那一份的指纹）：只算归一化之后的文本，换行形态一变
    # 就对不上，而读的人问的正是"盘上这份还是不是签名时那一份"。
    out.update({"text": text, "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest()})
    if not text.strip():
        out["state"] = "empty"
        out["problems"] = [f"报告是空文件：{out['path']}（空文件不等于「这两块写过了」）"]
        return out
    blocks, missing = blocks_of(text)
    out.update({"state": "present", "blocks": blocks, "missing": missing})
    if missing:
        out["problems"] = [
            f"报告里缺 {missing}：{out['path']}（②③ 由 E 写；缺任何一块，"
            "这条证据的证明栏就没写完 ⇒ 最多是「有数值实验支持」）"]
        return out
    if not _EVIDENCE_ID_RE.search(text):
        out["problems"] = [
            f"报告里没有 E 的读数编号（{EVIDENCE_PREFIX}NNNNNN）：{out['path']} —— "
            "读的人没法把这份读数与实验台账那一行对上"]
        return out
    if AUTHOR_MARKER not in text:
        out["problems"] = [f"报告里没有署名「{AUTHOR_MARKER}」：{out['path']} —— ②③ 的作者必须是 E"]
        return out
    out["ok"] = True
    return out


def blocks_of(text: Any) -> tuple[dict[str, int], list[str]]:
    """三段各自的正文字数 + 缺哪几段（标题逐字判）。

    字数用"标题之后、下一个标题之前的非空字符数"量：它回答的是"这一段有没有真的写东西"
    （只有标题、底下空着，等于没写）。`None` 段的字数记 0 并进 `missing`。
    """
    raw_lines = str(text or "").replace("\r\n", "\n").split("\n")
    blocks: dict[str, int] = {}
    missing: list[str] = []
    headings = ((BLOCK_DESIGN, DESIGN), (BLOCK_EXHAUSTION, ENUMERATION),
                (BLOCK_ENVIRONMENT, ENVIRONMENT))
    current = ""
    for line in raw_lines:
        stripped = line.strip()
        hit = ""
        for label, key in headings:
            if stripped.startswith(f"## {label}") or stripped.startswith(f"# {label}"):
                hit = key
                break
        if hit:
            current = hit
            blocks.setdefault(current, 0)
            continue
        if current and stripped:
            blocks[current] = blocks.get(current, 0) + len(stripped)
    for _label, key in headings:
        if not blocks.get(key):
            missing.append({"design": BLOCK_DESIGN, "enumeration": BLOCK_EXHAUSTION,
                            "environment": BLOCK_ENVIRONMENT}[key])
    return blocks, missing


def section_text(text: Any, label: str) -> str:
    """取报告里某一节的正文（标题逐字、到下一个标题为止）。

    为什么需要它（真机读数）：判"③ 里有没有写清穷尽"时如果拿整份报告去搜，报告头里的
    落点路径 `out/experiments/000000/exhaustion.md` 里就带着 "exhaust" 这个词 ——
    于是一份写着"随机抽取"的 ③ 会被读成"写了穷尽"。判据只该看那一节的正文。
    """
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        heading = ""
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
        elif stripped.startswith("# "):
            heading = stripped[2:].strip()
        if heading:
            if inside:
                break
            inside = heading.startswith(label)
            continue
        if inside and stripped:
            out.append(stripped)
    return "\n".join(out)


# ---------------------------------------------------------------- 行上的事实


def report_facts(experiment_row: Mapping[str, Any] | None) -> dict[str, Any]:
    """这一行实验记下的 ②③ 落盘事实（没有 ⇒ 空 dict，不猜、不补）。"""
    row = _as_mapping(experiment_row)
    obs = _as_mapping(row.get("observations"))
    return _as_mapping(obs.get(REPORT_KEY))


def landing_problems(experiment_row: Mapping[str, Any] | None) -> list[str]:
    """②③ 落盘核查：空清单 = 有一份落过盘、三块齐的读数；非空 = 缺什么（逐条）。

    这是"报告在不在、齐不齐"的唯一实现（`numericproof.report_problems` 只转发到这里）。
    它只读行上的事实，不碰盘：`schema.Experiment.validate` 是纯的，而写侧记录的事实
    是"读回来的字节数与 sha256"（见 :func:`land_report`）；盘上再核一次是读侧
    （V 的会审 / B 的入库闸）用 :func:`disk_problems` 做的事。
    """
    row = _as_mapping(experiment_row)
    facts = report_facts(row)
    if not facts:
        return [
            "缺 ②③ 的落盘读数（`observations"
            f"[{REPORT_KEY!r}]` 里没有这一格）：业主 2026-10-23 晚的口径是"
            "「E 写的报告要能落下来」—— 程序设计（要解决什么、按什么结构搜、"
            f"为什么覆盖全域）与穷举论证（搜索空间多大、怎么算出、对称性/剪枝、"
            f"为什么不漏、边界怎么处理）要落成 {REPORT_DIR}/<实验号>/{REPORT_NAME}，"
            "并把它的路径、字节数与 sha256 记在这一格。没有这份读数，"
            "这条证据拿不到 proof（最多是「有数值实验支持」）"
        ]
    problems: list[str] = []
    rel = str(facts.get("path") or "").strip().replace("\\", "/")
    if not is_report_relpath(rel):
        problems.append(
            f"②③ 的落点不合口径（读到 {rel!r}）：要的是 "
            f"{REPORT_DIR}/<实验号>/{REPORT_NAME} 这一形态的相对路径 ——"
            "落点固定，B 与 G 才有一个可引用的地址")
    eid = str(row.get("experiment_id") or "").strip()
    if eid and rel and rel != report_relpath(eid):
        problems.append(
            f"②③ 的落点与这条实验对不上（读到 {rel!r}，按实验号应是 "
            f"{report_relpath(eid)!r}）：报告挂到别人的号上，读的人会核错对象")
    for item in (facts.get("problems") or []):
        text = str(item).strip()
        if text:
            problems.append(f"②③ 没落成：{text}")
    if facts.get("ok") is not True:
        problems.append(
            "②③ 的落盘没成功（行上记着 ok=false）：既然没有一份落在盘上的读数，"
            "这一条就不许标 proof")
    try:
        size = int(facts.get("bytes") or 0)
    except (TypeError, ValueError):
        size = 0
    if size <= 0:
        problems.append("②③ 的读数记着 0 字节：空文件不等于「这两块写过了」")
    sha = str(facts.get("sha256") or "").strip()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha.lower()):
        problems.append(
            f"②③ 的读数没有有效的 sha256（读到 {sha!r}）：没有指纹，"
            "读的人无法判断盘上那份还是不是 E 写的那一份")
    missing = [str(m) for m in (facts.get("missing") or []) if str(m).strip()]
    if not missing:
        blocks = _as_mapping(facts.get("blocks"))
        for key, label in ((DESIGN, BLOCK_DESIGN), (ENUMERATION, BLOCK_EXHAUSTION)):
            try:
                got = int(blocks.get(key) or 0)
            except (TypeError, ValueError):
                got = 0
            if got <= 0:
                missing.append(label)
    if missing:
        problems.append(
            f"②③ 的读数缺 {missing}：这两块由 E 写，缺任何一块，"
            "这条证据的证明栏就没写完（缺「程序设计」⇒ 读的人不知道它在搜什么；"
            "缺「穷举论证」⇒「在 B 内没有反例」与「整个论域没有反例」分不开）")
    return problems


def disk_problems(root: str | Path | None, experiment_row: Mapping[str, Any] | None) -> list[str]:
    """按行上的事实到盘上再核一次（读侧用：V 的会审、B 的入库闸）。

    三件事：文件在不在、字节数对不对、sha256 对不对。三条里任何一条不成立，
    这一份读数就不认 —— "行上说落过"不是"盘上真的在"。
    """
    facts = report_facts(experiment_row)
    if not facts:
        return ["行上没有 ②③ 的落盘事实 ⇒ 无从核（没查成不是查过了没问题）"]
    rel = str(facts.get("path") or "")
    got = read_report(root, rel)
    if not got.get("ok"):
        return list(got.get("problems") or [])
    problems: list[str] = []
    try:
        want_bytes = int(facts.get("bytes") or 0)
    except (TypeError, ValueError):
        want_bytes = 0
    if want_bytes != int(got.get("bytes") or 0):
        problems.append(
            f"盘上那份读数的字节数变了（行上记 {want_bytes}，现在 "
            f"{int(got.get('bytes') or 0)}）：它不是 E 签名时那一份了")
    if str(facts.get("sha256") or "") != str(got.get("sha256") or ""):
        problems.append(
            "盘上那份读数的 sha256 与行上记的不一致：E 签名之后它被改过"
            f"（行上 {str(facts.get('sha256') or '')[:12]}…，现在 "
            f"{str(got.get('sha256') or '')[:12]}…）")
    return problems


# ---------------------------------------------------------------- V 的会审（穷举型证据）


#: 三态（与 `verifications.VERDICTS` 同一套词，不另造词）。
VERDICT_OK = "成立"
VERDICT_BAD = "有毛病"
VERDICT_UNKNOWN = "看不出来"

#: 检查项的名字（读数里逐条给；`有毛病` 的 findings 用同一个名字点名）。
CHECK_PROGRAM = "程序地址存在且可读"
CHECK_REPORT = "报告落盘且三块齐"
CHECK_SPACE = "搜索空间数字与代码里的循环/参数一致"
CHECK_SYMMETRY = "对称性/剪枝的理由成不成立"
CHECK_BOUNDARY = "边界是否覆盖"
CHECK_EXHAUSTIVE = "结论是穷尽而不是抽样"
CHECK_SLOT = "形式化那一格填的是不是对的东西"

#: 代码里"做了剪枝/对称性处理"的记号（判"报告有没有解释它"）。
SYMMETRY_MARKERS: tuple[str, ...] = (
    "symmetr", "isomorph", "canonical", "automorphism", "orbit", "quotient",
    "prune", "dedup", "seen", "visited", "iso_",
)
#: 代码里"抽样"的记号（穷举证明要说明它不是抽样；命中就必须在报告里解释）。
SAMPLING_MARKERS: tuple[str, ...] = (
    "random", "randint", "choice(", "sample(", "shuffle", "randrange",
)
#: 报告里"穷尽"的记号（③ 的结论必须是穷尽，不是"抽查"）。
EXHAUSTIVE_WORDS: tuple[str, ...] = (
    "穷尽", "全部", "所有", "无一遗漏", "不漏", "exhaust", "complete", "全覆盖",
)
#: 数字记号（搜索空间与边界判定用）。
_NUM_RE = re.compile(r"[0-9]+")
#: `a^b` 形态（报告里常见的指数写法）。
_POW_RE = re.compile(r"([0-9]+)\s*[\^＊*]{1,2}\s*([0-9]+)")


def _computation_part(code: str) -> str:
    """脚本的"计算段"：`REPRO_RESULT` 那一行之前的部分。

    为什么要切掉报告那一行：搜索空间的数字总要被脚本打印出来，所以它必然出现在
    `REPRO_RESULT` 的载荷里 —— 拿整份源码去搜"这个数在不在代码里"，等于让脚本
    自己声明的那份读数给自己作证（真机读数：一份把 `2^40` 写进载荷的脚本，
    代码段里只有 2 的 36 次方，而整份源码里当然有 2^40）。
    切在第一次出现 `REPRO_RESULT` 的地方：计算在前、报数在后，这是那份协议本身的顺序。
    找不到这个记号（脚本不按协议打印）⇒ 原样返回整份源码。
    """
    text = str(code or "")
    idx = text.find("REPRO_RESULT")
    if idx > 0:
        return text[:idx]
    return text


def _numbers(text: Any, *, min_digits: int = 3) -> list[str]:
    """文本里的数字（去掉太短的：1 / 2 / 3 这种数到处都是，拿它判一致性只会假红）。"""
    out: list[str] = []
    for token in _NUM_RE.findall(str(text or "")):
        if len(token) >= min_digits and token not in out:
            out.append(token)
    return out


def _flat_numbers(value: Any, *, depth: int = 3) -> list[str]:
    """一格自由读数里出现的数字（递归有限层；字符串里的数字也算）。"""
    out: list[str] = []

    def walk(node: Any, level: int) -> None:
        if level > depth:
            return
        if isinstance(node, Mapping):
            for item in node.values():
                walk(item, level + 1)
            return
        if isinstance(node, (list, tuple)):
            for item in node[:40]:
                walk(item, level + 1)
            return
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, float)):
            out.append(str(int(node)) if float(node).is_integer() else str(node))
            return
        for token in _numbers(node):
            out.append(token)

    walk(value, 0)
    return out


def _pow_in(text: Any) -> set[tuple[str, str]]:
    return {(m.group(1), m.group(2)) for m in _POW_RE.finditer(str(text or ""))}


def _number_in_code(token: str, code: str, code_pows: set[tuple[str, str]]) -> bool:
    """这个数字在代码里有没有着落（字面出现，或由 a^b / 2 的 k 次方这类写法算得出来）。"""
    if token in code:
        return True
    for base, exp in code_pows:
        try:
            if str(int(base) ** int(exp)) == token:
                return True
        except ValueError:
            continue
    # 代码里写 2 的 36 次方这种（python 的指数写法）
    for m in re.finditer(r"([0-9]+)\s*\*\*\s*([0-9]+)", code):
        try:
            if str(int(m.group(1)) ** int(m.group(2))) == token:
                return True
        except ValueError:
            continue
    return False


def _finding(level: str, check: str, detail: str, step: int) -> dict[str, Any]:
    """一条 finding（形状照 `verifications.parse_verdict` 的要求：level/step/kind/detail）。"""
    return {"level": level, "step": step, "kind": check, "detail": detail}


def is_exhaustion_column(statement: Mapping[str, Any],
                         experiments: Sequence[Mapping[str, Any]] = ()) -> bool:
    """这条命题的证明栏是不是"穷举型证据"（第 ① 段是程序、且不是 Lean 源码）。

    为什么不要求"台账里已经有一条 E 签的穷举证明"：那正是本判据要判的东西 ——
    报告没落地时台账里根本没有那条签名，而 V 仍然必须去看、并且报「看不出来（缺材料）」。
    反过来，`.lean` 路径不算这一档：那是理论定理的形式化格（V 的逐行走查那一支）。
    """
    from . import numericproof as NP

    text = str(_as_mapping(statement).get("proof_text") or "").strip()
    script = NP.proof_column_script(text)
    if not script:
        return False
    return not NP.is_lean_path(script)


def verdict_of(reviewed: Mapping[str, Any] | None) -> dict[str, Any]:
    """把一次会审的读数翻成一次审校的结论（`verifications.parse_verdict` 收的那一形态）。

    `有毛病` 必须带 `defect_step`：这里用它自己算出来的"第几项检查"（1 起数），
    所以 findings 里的 `step` 与 `defect_step` 说的是同一件事 —— 读的人照着那个号
    就能翻到 `checks` 里失败的那一项。
    """
    rev = _as_mapping(reviewed)
    return {
        "verdict": str(rev.get("verdict") or VERDICT_UNKNOWN),
        "defect_step": rev.get("defect_step"),
        "quote": str(rev.get("quote") or ""),
        "why": str(rev.get("why") or ""),
        "findings": [dict(f) for f in (rev.get("findings") or [])],
    }


def review(*, workspace_root: str | Path | None, statement: Mapping[str, Any],
           experiments: Sequence[Mapping[str, Any]] = (),
           experiment_row: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """V 的穷举型证据会审：三态结论 + 逐项检查 + 点名的 findings。

    检查项（业主 2026-10-23 晚点名的那几条，一条一项，逐条给读数）：

    1. 程序地址存在且可读（证明栏第 ① 段那份脚本）；
    2. 报告落盘且三块齐（②③ 的读数，判据在 :func:`exhaustion_problems`）；
    3. 搜索空间数字与代码里的循环/参数一致（报告里的数要在代码里有着落）；
    4. 对称性/剪枝的理由成不成立（代码做了剪枝 ⇒ 报告必须解释它；反之亦然）；
    5. 边界是否覆盖（边界那一段必须在报告里写出来，数字与搜索空间对得上）；
    6. 结论是穷尽而不是抽样（`exhaustive` 是布尔 true；代码里没有抽样构造；
       ③ 里写着"穷尽/全部/不漏"）；
    7. 形式化那一格填的是不是对的东西（数值定理 ⇒ 数值程序；理论定理 ⇒ .lean；
       判据在 `numericproof.formal_slot`）。

    三态的口径：
    - 材料缺（没有对应的实验行 / 报告没落地）⇒ `看不出来`，findings 点名缺哪一块；
    - 材料在但自相矛盾（数字对不上 / 剪枝没解释 / 抽样 / 边界没写 / 形式化格填错）
      ⇒ `有毛病`，`defect_step` 指到失败的那一项；
    - 全部通过 ⇒ `成立`（V 签；②③ 的作者仍是 E）。

    为什么这一档不是"再问一次模型"：这几条都是可机械核的事实（文件在不在、
    数字对不对得上、代码里有没有那个构造）。让模型来判"数字对不对"只会把可核的
    事实变成不可复核的意见 —— 而业主的口径是"缺材料就不许判成立"，那是判据能保证的。
    """
    root = workspace_root
    stmt = _as_mapping(statement)
    proof_text = str(stmt.get("proof_text") or "").strip()
    out: dict[str, Any] = {
        "kind": "exhaustion",
        "checked": True,
        "verdict": VERDICT_UNKNOWN,
        "defect_step": None,
        "quote": "",
        "why": "",
        "findings": [],
        "checks": [],
        "missing": [],
        "signed_by": SIGNER_ROLE,
        "proof_authors": [AUTHOR_ROLE],
        "program": "",
        "report_path": "",
        "report_sha256": "",
        "report_bytes": 0,
        "search_space": {},
        "problems": [],
    }
    from . import numericproof as _NP

    before = len(out["findings"])
    checks: list[dict[str, Any]] = out["checks"]
    findings: list[dict[str, Any]] = out["findings"]

    # ---- 材料：证明栏第 ① 段（程序）与那条 E 写的 ②③
    script = ""
    parsed = _NP.parse_proof_column(proof_text)
    if parsed.get("script"):
        script = str(parsed["script"]).strip().replace("\\", "/")
    elif _NP.is_script_path(proof_text):
        script = proof_text.replace("\\", "/")
    row = dict(experiment_row) if isinstance(experiment_row, Mapping) else None
    if row is None and script:
        row = _NP.find_signed_exhaustion(experiments, script)
    if row is None and script:
        row = next((dict(r) for r in (experiments or ())
                    if isinstance(r, Mapping)
                    and _NP.norm_rel(r.get("code_path")) == _NP.norm_rel(script)), None)
    if script:
        out["program"] = script
    if row is not None:
        facts = report_facts(row)
        out["report_path"] = str(facts.get("path") or "")
        out["report_sha256"] = str(facts.get("sha256") or "")
        try:
            out["report_bytes"] = int(facts.get("bytes") or 0)
        except (TypeError, ValueError):
            out["report_bytes"] = 0
        space = row.get("search_bound") or _as_mapping(
            _as_mapping(row.get("observations")).get("bound")).get("search_bound")
        if space:
            out["search_space"] = dict(space) if isinstance(space, Mapping) else {"value": space}

    # ---- 检查 1：程序地址
    code = ""
    step = 1
    if not script:
        out["missing"].append("程序（证明栏第 ① 段的相对路径）")
        checks.append({"name": CHECK_PROGRAM, "ok": None,
                       "detail": "证明栏里取不出程序路径 ⇒ 这不是穷举型证据的证明栏"})
        findings.append(_finding("error", CHECK_PROGRAM,
                                 "证明栏里没有程序相对路径（第 ① 段读不到）："
                                 "穷举证明的签名就是那份程序，读的人无从核它跑了什么", step))
    else:
        target, why = _resolve(root, script)
        if target is None:
            checks.append({"name": CHECK_PROGRAM, "ok": False, "detail": f"程序路径不可解析：{why}"})
            findings.append(_finding("error", CHECK_PROGRAM,
                                     f"程序 {script!r} 不可解析：{why}", step))
        elif not target.is_file():
            checks.append({"name": CHECK_PROGRAM, "ok": False,
                           "detail": f"程序不在盘上：{script}"})
            findings.append(_finding("error", CHECK_PROGRAM,
                                     f"证明栏指的 {script!r} 不在盘上：材料指着一份不存在的东西", step))
        else:
            try:
                code = target.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                checks.append({"name": CHECK_PROGRAM, "ok": False,
                               "detail": f"程序读不出来：{type(exc).__name__}: {exc}"})
                findings.append(_finding("error", CHECK_PROGRAM,
                                         f"程序 {script!r} 读不出来（{type(exc).__name__}: {exc}）", step))
            else:
                checks.append({"name": CHECK_PROGRAM, "ok": True,
                               "detail": f"程序 {script}（{len(code)} 字符）在盘上、可读"})

    # ---- 检查 2：报告落盘
    step = 2
    report_text = ""
    report_state = ""
    if row is None:
        out["missing"].append("与这条证明栏对应的实验行")
        checks.append({"name": CHECK_REPORT, "ok": None,
                       "detail": "台账里没有与这份证明栏对应的实验行 ⇒ ②③ 无处可查"})
        findings.append(_finding("error", CHECK_REPORT,
                                 "台账里没有与这份证明栏对应的实验行：没有那条 E 的读数，"
                                 "②③ 的两段论证与它的落盘报告都无从复核", step))
    else:
        got = read_report(root, out["report_path"]) if out["report_path"] else None
        if got is not None:
            report_state = str(got.get("state") or "")
            report_text = str(got.get("text") or "")
        probs = list(landing_problems(row)) + list(disk_problems(root, row))
        if probs:
            # 读数读不到（不在盘上 / 空文件 / 读不出来）时，缺的就是那两块本身：
            # 业主的口径是「报告缺失 ⇒ V 必须报看不出来（缺穷举论证 / 缺程序设计）」，
            # 所以这一档的 missing 直接点名那两块，而不是只说一句"报告不在"。
            if got is not None and not got.get("ok"):
                for label in (BLOCK_DESIGN, BLOCK_EXHAUSTION):
                    if label not in out["missing"]:
                        out["missing"].append(label)
            for item in probs:
                label = _missing_label(str(item))
                if label not in out["missing"]:
                    out["missing"].append(label)
            checks.append({"name": CHECK_REPORT, "ok": False,
                           "detail": "；".join(probs)})
            findings.append(_finding("error", CHECK_REPORT,
                                     "②③ 的落盘读数不成立：" + "；".join(probs), step))
        else:
            checks.append({"name": CHECK_REPORT, "ok": True,
                           "detail": f"报告 {out['report_path']} 在盘上、sha256 与行上一致、三块齐"})

    # ---- 缺材料 ⇒ 看不出来（不是"有毛病"：还没东西可判）
    if not out["missing"] and row is not None:
        report_text = report_text or str(_read_text(root, out["report_path"]) or "")

    # ---- 检查 3：搜索空间与代码一致
    step = 3
    if code and report_text:
        space_nums = _flat_numbers(out["search_space"])
        enum_numbers = _numbers(parsed.get("enumeration") or "")
        # 只拿"计算段"（`REPRO_RESULT` 之前）去核：报数那一行里出现的数字不算数
        build = _computation_part(code)
        code_pows = _pow_in(build)
        bad: list[str] = []
        for token in dict.fromkeys(space_nums + enum_numbers):
            if not _number_in_code(token, build, code_pows):
                bad.append(token)
        if bad:
            checks.append({"name": CHECK_SPACE, "ok": False,
                           "detail": f"这些数在代码里没有着落：{bad[:8]}"})
            findings.append(_finding(
                "error", CHECK_SPACE,
                f"报告/读数里的数字 {bad[:8]} 在程序 {script} 里找不到对应的循环或参数 ——"
                "搜索空间是报出来的，不是这段代码算出来的", step))
        else:
            checks.append({"name": CHECK_SPACE, "ok": True,
                           "detail": "报告里的搜索空间数字都能在代码里找到着落"})

    # ---- 检查 4：对称性/剪枝的理由
    step = 4
    if code and report_text:
        # 只读 ③ 的正文（整份报告里带着落点路径，路径里的 "exhaustion.md" 会把判据骗过去）
        enum_text = (parsed.get("enumeration") or "") + "\n" + section_text(
            report_text, BLOCK_EXHAUSTION)
        code_markers = [m for m in SYMMETRY_MARKERS if m in code.lower()]
        report_markers = [m for m in SYMMETRY_MARKERS if m in enum_text.lower()]
        if code_markers and not report_markers:
            checks.append({"name": CHECK_SYMMETRY, "ok": False,
                           "detail": f"代码做了剪枝/对称性处理（{code_markers}），报告没有解释它"})
            findings.append(_finding(
                "error", CHECK_SYMMETRY,
                f"代码里有 {code_markers} 这类剪枝/对称性构造，而 ③ 里一个字都没解释它们为什么"
                "不丢解 —— 剪枝不可靠就等于没有穷尽（漏掉的那部分恰好没被检查）", step))
        elif report_markers and not code_markers:
            checks.append({"name": CHECK_SYMMETRY, "ok": False,
                           "detail": f"报告说用了剪枝/对称性（{report_markers}），代码里没有这类构造"})
            findings.append(_finding(
                "error", CHECK_SYMMETRY,
                f"③ 声称用了 {report_markers} 这类剪枝/对称性，而程序里没有对应构造 ——"
                "报告与代码说的不是同一件事", step))
        else:
            checks.append({"name": CHECK_SYMMETRY, "ok": True,
                           "detail": (f"代码与报告都提到剪枝/对称性（{code_markers}）"
                                      if code_markers else "代码与报告都没有声称做过剪枝/对称性")})

    # ---- 检查 5：边界覆盖
    step = 5
    if code and report_text:
        boundary_nums = _flat_numbers(out["search_space"])
        enum_text = (parsed.get("enumeration") or "") + "\n" + section_text(
            report_text, BLOCK_EXHAUSTION)
        absent = [t for t in boundary_nums if t not in enum_text and t not in code]
        if absent:
            checks.append({"name": CHECK_BOUNDARY, "ok": False,
                           "detail": f"边界数字既不在报告里、也不在代码里：{absent[:8]}"})
            findings.append(_finding(
                "error", CHECK_BOUNDARY,
                f"边界那一段读不到 {absent[:8]}：既没写清边界是什么（n 的最大值 / 区间端点），"
                "也没在代码里出现 ⇒ '边界覆盖到哪儿'不可核", step))
        else:
            checks.append({"name": CHECK_BOUNDARY, "ok": True,
                           "detail": "边界的数字在报告与代码里都读得到"})

    # ---- 检查 6：穷尽而不是抽样
    step = 6
    if row is not None and report_text:
        obs = _as_mapping(row.get("observations"))
        flag = obs.get("exhaustive")
        if flag is not True:
            bound = _as_mapping(row.get("search_bound"))
            flag = bound.get("exhaustive", _as_mapping(obs.get("bound")).get("exhaustive"))
        enum_text = (parsed.get("enumeration") or "") + "\n" + section_text(
            report_text, BLOCK_EXHAUSTION)
        sampled = [m for m in SAMPLING_MARKERS
                   if m in code.lower() or m in enum_text.lower()]
        words = [w for w in EXHAUSTIVE_WORDS if w in enum_text]
        if flag is not True:
            checks.append({"name": CHECK_EXHAUSTIVE, "ok": False,
                           "detail": f"exhaustive 读到 {flag!r}（要布尔 true）"})
            findings.append(_finding(
                "error", CHECK_EXHAUSTIVE,
                f"exhaustive 读到 {flag!r}：穷举证明要的是布尔 true 本身"
                "（缺省、'true'、1 都算没说清）", step))
        elif sampled and not any(w in enum_text for w in EXHAUSTIVE_WORDS):
            checks.append({"name": CHECK_EXHAUSTIVE, "ok": False,
                           "detail": f"代码/报告里有抽样构造 {sampled}，③ 没写清穷尽"})
            findings.append(_finding(
                "error", CHECK_EXHAUSTIVE,
                f"代码/报告里出现抽样构造 {sampled}，而 ③ 没有一句说清它是穷尽而不是抽样 ——"
                "'抽样'与'穷尽'是两件事，后者才是证明", step))
        elif not words:
            checks.append({"name": CHECK_EXHAUSTIVE, "ok": False,
                           "detail": "③ 里没有一句写清'穷尽/全部/不漏'"})
            findings.append(_finding(
                "error", CHECK_EXHAUSTIVE,
                f"③ 里没有一句写清它是穷尽（{list(EXHAUSTIVE_WORDS[:5])} 一个都没有）⇒"
                "读的人把它读成'抽了一批点'，那不是证明", step))
        else:
            checks.append({"name": CHECK_EXHAUSTIVE, "ok": True,
                           "detail": f"exhaustive=true，③ 写清了穷尽（{words[:3]}）"})

    # ---- 检查 7：形式化那一格填得对不对（数值定理 / 理论定理不许互相冒充）
    step = 7
    slot = _NP.formal_slot(stmt, experiments, filled=script)
    out["formal_slot"] = slot
    if slot.get("problems"):
        checks.append({"name": CHECK_SLOT, "ok": False, "detail": "；".join(slot["problems"])})
        findings.append(_finding("error", CHECK_SLOT, "；".join(slot["problems"]), step))
    else:
        checks.append({"name": CHECK_SLOT, "ok": True,
                       "detail": f"形式化那一格应当是 {slot.get('kind') or '（不适用）'}"
                                 f"，填的是 {script or '（没填）'}"})

    # ---- 三态
    real_findings = [f for f in findings[before:] if str(f.get("level")) == "error"]
    out["problems"] = [str(f.get("detail") or "") for f in real_findings]
    if out["missing"]:
        out["verdict"] = VERDICT_UNKNOWN
        out["defect_step"] = None
        out["why"] = ("缺材料：" + "、".join(out["missing"]) +
                      " ⇒ 判不了成立（缺材料的诚实结论是看不出来，不是成立）")
        out["quote"] = ""
        out["findings"] = [f for f in findings if str(f.get("level")) == "error"]
        return out
    if real_findings:
        first = real_findings[0]
        out["verdict"] = VERDICT_BAD
        out["defect_step"] = int(first.get("step") or 1)
        out["why"] = f"第 {out['defect_step']} 项不成立：{first.get('kind')}"
        out["quote"] = str(first.get("kind") or "")
        out["findings"] = real_findings
        return out
    passed = [c["name"] for c in checks if c.get("ok") is True]
    out["verdict"] = VERDICT_OK
    out["defect_step"] = None
    out["why"] = f"{len(passed)} 项检查全部通过：{'；'.join(passed)}"
    out["quote"] = ""
    out["findings"] = []
    return out


def _missing_label(problem: str) -> str:
    """把一条问题翻成"缺哪一块"的短名（给 V 的 findings 与读数用）。"""
    for label in (BLOCK_DESIGN, BLOCK_EXHAUSTION, BLOCK_ENVIRONMENT):
        if label in problem:
            return label
    if "不在盘上" in problem or "没落成" in problem:
        return "落盘的报告"
    return "②③ 的落盘读数"


def _read_text(root: str | Path | None, rel: Any) -> str:
    got = read_report(root, rel)
    return str(got.get("text") or "")


def environment_reading(*, exit_code: Any = None, runtime_sec: Any = None,
                        extra: Any = "") -> str:
    """运行环境那一行（报告里的第三块）：解释器版本 + 退出码 + 耗时 + 调用方补的说明。"""
    bits = [f"Python {sys.version.split()[0]}"]
    if exit_code is not None:
        bits.append(f"exit_code={exit_code}")
    if runtime_sec is not None:
        try:
            bits.append(f"runtime={float(runtime_sec):.3f}s")
        except (TypeError, ValueError):
            bits.append(f"runtime={runtime_sec!r}")
    text = str(extra or "").strip()
    if text:
        bits.append(text)
    return "；".join(bits)
