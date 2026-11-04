# -*- coding: utf-8 -*-
"""B 的改写手稿：B 要把「改写后的正文」交给 V 签，先得有可签的载体。

## 业主裁定（逐字，2026-11-04）

    A 甲 —— B 的改写要有可签的载体：给 B 手稿签块（与 F/E 同形）

## 为什么需要这一层

V 的签落点只有两处：在册命题的台账行、或一份手稿里的签块（`vsigns`）。
B 改写在册证明时，正文与在册那一版不同 ⇒ 旧签读成 stale、台账行也盖不住新正文；
它需要的是一份自己的手稿：`reports/b-proof-<命题号>.md`，与 F / E 同形
（`## 命题` / `## 证明` / `## 依赖` 三节）。V 读这一份、三转成立后由收方秘书
（`secretary:B`）把签块落回稿里；B 再带这份稿调 `own.register_statement`，
`vsigns.manuscript_sign_standing` 读到「签到位」⇒ 第 3 位翻真、`reviewed=true`。

## 谁写这份稿

B 没有文件写口（工具面只有 `table.*` / `manuscripts.read|list` 这类），所以稿由框架
在 B 的登记入口（`AgentB.register_statement`）里按 B 交上来的正文渲染 ——
B 交的是内容，落盘的是框架，签由收方秘书落。这与 F/E 的分工一致：
作者只写内容，收方读稿落签（`draft/178` 的「签在稿上」）。

## 三态（写侧）

- `written=True`：这一趟把稿写下了（或重写成新正文，旧稿没有签可毁）；
- `written=False, preserved=True, signed=True`：目标稿已经是同一份正文的已签版
  ⇒ 一个字节都不动（不许用一份新正文盖掉签住的那一份）；
- `written=False, problem={...}`：目标稿已签、而这一笔要写的是另一份正文 ⇒ 不覆盖，
  把冲突留在读数里（签另算不是毁签）；B 要改这一版，得先让旧签失效/换一份稿。

判据：`tests/test_b_rewrite_manuscript_gets_signed.py`（a 正控 / b 无签仍拒 / c 反真空）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import depsection as _DS

#: 手稿落点（与 F/E 同一个目录）。
MANUSCRIPT_DIR = "reports"
#: 文件名前缀（`reports/b-proof-<命题号>.md`）。
PREFIX = "b-proof-"

#: 稿头里"第几份证明"那一行（与 F/E 同一写法：`depsection.manuscript_proof_no` 读它）。
PROOF_NO_PREFIX = "- 证明号："

_ID_RE = re.compile(r"^\d{4,6}$")


def relpath(statement_id: Any) -> str:
    """这一条命题的 B 改写手稿落点（工作区相对）；号不合法 ⇒ 空串（不猜位置）。"""
    sid = str(statement_id or "").strip()
    if not _ID_RE.match(sid):
        return ""
    return f"{MANUSCRIPT_DIR}/{PREFIX}{sid}.md"


def is_relpath(value: Any) -> bool:
    """这一串字是不是「B 的改写手稿」那一形态（`reports/b-proof-<数字>.md`）。

    与 `er.is_manuscript_relpath` 同一条纪律：只判形态、不判它不在盘上；
    绝对路径 / 含 `..` / 别的目录一律不认（"稿在哪"不许随机器变）。
    """
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ":" in raw:
        return False
    parts = raw.split("/")
    if ".." in parts or len(parts) != 2:
        return False
    if parts[0] != MANUSCRIPT_DIR or not parts[1].endswith(".md"):
        return False
    name = parts[1][: -len(".md")]
    return name.startswith(PREFIX) and bool(_ID_RE.match(name[len(PREFIX):]))


def _dependency_section(source_manuscript: Any) -> str:
    """从来源手稿（F / E / D 递过来的那一份）抄下 `## 依赖` 那一节；没有 ⇒ 空表声明。

    为什么抄而不是让 B 重写：B 改写的是证明正文，依赖面（引了哪几条在册命题）
    通常没变；让模型重抄一张四列表，唯一稳定的结果是把行抄丢。解析 → 渲染走的是
    `depsection` 同一对函数（B 收稿时读的也是它们），所以"抄过去"与"读得回"同一把尺。
    """
    text = str(source_manuscript or "")
    if text.strip():
        section = _DS.parse_dependency_section(text)
        if section.get("present") and not section.get("refused"):
            return _DS.render_dependency_section(section.get("rows") or [])
    return _DS.render_dependency_section([])


def render(*, statement_full: Any, proof_text: Any, statement_id: Any = "",
           label: Any = "", proof_no: Any = 0,
           dependency_section: str = "") -> str:
    """渲染一份 B 的改写手稿（纯函数，逐字节可复现）。

    三节与 F/E 同形：`## 命题` 是这条命题的完整正文（含假设），`## 证明` 是 B 改写后
    的正文（被签的就是这一节），`## 依赖` 是四列表（空表也是声明）。
    """
    sid = str(statement_id or "").strip()
    body = str(proof_text or "").strip()
    full = str(statement_full or "").strip()
    title = " ".join(str(label or full or "").split())[:60] or "（这一条没有写命题）"
    head = [
        f"# B 的改写手稿：{title}",
        "",
        f"- 命题号：stmt:{sid or '（还没落号）'}",
    ]
    try:
        no = int(proof_no or 0)
    except (TypeError, ValueError):
        no = 0
    if no >= 1:
        head.append(f"{PROOF_NO_PREFIX}{no}")
    head.extend([
        f"- 标签：{str(label or '').strip() or '（没有标签）'}",
        "",
        "## 命题",
        "",
        full,
        "",
        "## 证明",
        "",
        body,
        "",
        dependency_section or _DS.render_dependency_section([]),
    ])
    return "\n".join(head)


def land_rewrite(root: Any, *, statement_id: Any, statement_full: Any, proof_text: Any,
         label: Any = "", proof_no: Any = 0, source_manuscript: Any = "") -> dict[str, Any]:
    """把 B 的改写手稿写到 `reports/b-proof-<号>.md`（三态见模块 docstring）。

    返回 `{ok, path, written, preserved, signed, text, why, problem}`；
    `problem` 非空时一个字节都不写（已签的是另一份正文 / 目标读不出来）。
    """
    from . import verifications as _VR
    from . import vsigns as _VS

    sid = str(statement_id or "").strip()
    rel = relpath(sid)
    out: dict[str, Any] = {"ok": False, "path": rel, "written": False,
                           "preserved": False, "signed": False, "text": "",
                           "why": "", "problem": {}}
    if not rel:
        out["why"] = f"命题号 {statement_id!r} 认不出 ⇒ B 的改写手稿没有固定落点"
        return out
    if not str(proof_text or "").strip():
        out["why"] = "这一笔没有要改写的正文 ⇒ 不落 B 的手稿"
        return out
    text = render(statement_full=statement_full, proof_text=proof_text,
                  statement_id=sid, label=label, proof_no=proof_no,
                  dependency_section=_dependency_section(source_manuscript))
    out["text"] = text
    target = Path(str(root)) / rel
    if target.is_file():
        try:
            old = target.read_text(encoding="utf-8")
        except OSError as exc:
            out.update(
                preserved=True,
                problem={"kind": "target_unreadable",
                         "why": (f"按号命名的那份 B 手稿读不出来（{type(exc).__name__}: "
                                 f"{exc}）⇒ 不覆盖它（它可能已经是签住的那一版）")})
            out["why"] = out["problem"]["why"]
            return out
        standing = _VS.manuscript_sign_standing(old, manuscript_path=rel)
        if str(standing.get("state") or "") == "signed":
            old_sha = _VR.proof_sha(_VS.manuscript_proof_body(old))
            new_sha = _VR.proof_sha(str(proof_text or "").strip())
            if old_sha == new_sha:
                out.update(ok=True, preserved=True, signed=True, text=old,
                           why=("`reports/b-proof-<号>.md` 已经是这一份正文的已签版 ⇒ "
                                "一个字节都不动（签跟着正文走）"))
                return out
            out.update(
                preserved=True, signed=True,
                problem={"kind": "target_holds_a_signed_version",
                         "why": (f"`{rel}` 里那一版已被签住（正文 sha {old_sha[:12]}…），"
                                 f"而这一笔要写的是 {new_sha[:12]}… ⇒ 不覆盖（签另算不是毁签）；"
                                 "先把旧那一版的去留定下来，再交新正文")})
            out["why"] = out["problem"]["why"]
            return out
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        out["problem"] = {"kind": "write_failed",
                          "why": (f"B 的改写手稿没写成（{type(exc).__name__}: {exc}）⇒ "
                                  "这一份拿不到签（签要有载体）")}
        out["why"] = out["problem"]["why"]
        return out
    out.update(ok=True, written=True, why=f"B 的改写手稿已写成：{rel}")
    return out


def read_rewrite(root: Any, rel: Any) -> dict[str, Any]:
    """读一份 B 的改写手稿（V 与 B 用同一处口径）。"""
    raw = str(rel or "").strip().replace("\\", "/")
    out: dict[str, Any] = {"ok": False, "state": "outside", "path": raw, "text": "",
                           "proof_body": "", "why": ""}
    if not is_relpath(raw):
        out["why"] = f"{raw!r} 不是 B 的改写手稿形态（`reports/b-proof-<号>.md`）"
        return out
    target = Path(str(root)) / raw
    if not target.is_file():
        out["state"] = "missing"
        out["why"] = f"手稿不在盘上：{raw}"
        return out
    try:
        out["text"] = target.read_text(encoding="utf-8")
    except OSError as exc:
        out["state"] = "unreadable"
        out["why"] = f"手稿读不出来（{type(exc).__name__}: {exc}）"
        return out
    out["proof_body"] = _DS.proof_body(out["text"]).strip("\n")
    out.update(ok=True, state="present", why="")
    return out
