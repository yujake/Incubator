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

## 2026-11-04（业主裁定）：与 F 的证明手稿收成一份实现

改前本模块自己有一套：自己的编号正则（`_ID_RE`）、自己的页头（`- 标签：` 那一套）、
`land_rewrite` 里的内联「已签就不覆盖」。F 那边同样的事各有一份 ⇒ 两份页头一开始就
不一样。现在：

- 命名 / 渲染 / 搬签 / 落盘事务 / 拒信码全部在 `agentflow.manuscriptform`（与 F 共用）；
- 本模块的 `render` / `relpath` / `is_relpath` / `land_rewrite` 只做转发与适配；
- `land_rewrite` 的 `write_dependencies` 与 F 的 `promote` 是同一条事务：落边失败
  ⇒ 刚写的稿回滚，不留半截。

## 三态（写侧）

- `written=True`：这一趟把稿写下了（或重写成新正文，旧稿没有签可毁）；
- `written=False, preserved=True, signed=True`：目标稿已经是同一份正文的已签版
  ⇒ 一个字节都不动（不许用一份新正文盖掉签住的那一份）；
- `written=False, problem={...}`：目标稿已签、而这一笔要写的是另一份正文 ⇒ 不覆盖，
  把冲突留在读数里（签另算不是毁签）；B 要改这一版，得先让旧签失效/换一份稿。

判据：`tests/test_b_rewrite_manuscript_gets_signed.py`（a 正控 / b 无签仍拒 / c 反真空）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import depsection as _DS
from . import manuscriptform as _MF
from . import vsigns as _VS

#: 手稿落点（与 F/E 同一个目录；唯一来源在 `manuscriptform`）。
MANUSCRIPT_DIR = _MF.MANUSCRIPT_DIR
#: 文件名前缀（`reports/b-proof-<命题号>.md`）。
PREFIX = _MF.PREFIX[_MF.FAMILY_B]

#: 稿头里"第几份证明"那一行（渲染与读侧同一个拼法）。
PROOF_NO_PREFIX = _MF.PROOF_NO_MARK


def relpath(statement_id: Any, proof_no: Any = 1) -> str:
    """这一条命题的 B 改写手稿落点（工作区相对）；号不合法 ⇒ 空串（不猜位置）。

    命名规则与解析在同一条路上：`manuscriptform.name_reading` 拼候选名，内部只走
    `vsigns.parse_manuscript_name`。
    """
    got = _MF.name_reading(_MF.FAMILY_B, statement_id=statement_id,
                           proof_no=proof_no)
    return str(got.get("path") or "") if got.get("ok") else ""


def is_relpath(value: Any) -> bool:
    """这一串字是不是「B 的改写手稿」那一形态（`reports/b-proof-<数字>.md`）。

    与 `er.is_manuscript_relpath` 同一条纪律：只判形态、不判它不在盘上；
    绝对路径 / 含 `..` / 别的目录一律不认（"稿在哪"不许随机器变）。解析只走
    `vsigns.parse_manuscript_name`（与 F 同一处），这里只多判"是不是 b- 这一族"。
    """
    raw = str(value or "").strip().replace("\\", "/")
    parsed = _VS.parse_manuscript_name(raw)
    if not (parsed.get("checked") and parsed.get("family")):
        return False
    return str(parsed.get("name") or "").startswith(PREFIX)


def _dependency_rows(source_manuscript: Any) -> list[dict[str, Any]]:
    """从来源手稿抄下 `## 依赖` 那一节的数据行；没有 ⇒ 空列表（空表也是声明）。"""
    text = str(source_manuscript or "")
    if not text.strip():
        return []
    section = _DS.parse_dependency_section(text)
    if section.get("present") and not section.get("refused"):
        return [dict(r) for r in (section.get("rows") or [])]
    return []


def _dependency_section(source_manuscript: Any) -> str:
    """从来源手稿（F / E / D 递过来的那一份）抄下 `## 依赖` 那一节；没有 ⇒ 空表声明。"""
    return _DS.render_dependency_section(_dependency_rows(source_manuscript))


def render(*, statement_full: Any, proof_text: Any, statement_id: Any = "",
           label: Any = "", proof_no: Any = 0,
           dependency_section: str = "", proposition: Any = None,
           plan_id: Any = "", sid: Any = "", wash_actor: Any = "",
           wash_filled: Any = "") -> str:
    """渲染一份 B 的改写手稿（纯函数，逐字节可复现）。

    三节与 F/E 同形：`## 命题` 是这条命题的完整正文（含假设），`## 证明` 是 B 改写后
    的正文（被签的就是这一节），`## 依赖` 是四列表（空表也是声明）。实现本体是
    `manuscriptform.render_proof_manuscript`（F 的证明手稿走同一段代码），本函数只把
    B 的入参名换成那一套。
    """
    full = statement_full if proposition is None else proposition
    return _MF.render_proof_manuscript(
        _MF.FAMILY_B, title=label, statement_id=statement_id,
        proposition=full, proof_text=proof_text,
        dependency_section=dependency_section, plan_id=plan_id, sid=sid,
        label=label, proof_no=proof_no, wash_actor=wash_actor,
        wash_filled=wash_filled)


def land_rewrite(root: Any, *, statement_id: Any, statement_full: Any,
                 proof_text: Any, label: Any = "", proof_no: Any = 0,
                 source_manuscript: Any = "", plan_id: Any = "",
                 sid: Any = "", write_dependencies: Callable[
                     [Sequence[Mapping[str, Any]]],
                     Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """把 B 的改写手稿写到 `reports/b-proof-<号>.md`（三态见模块 docstring）。

    返回 `{ok, path, written, preserved, signed, text, why, problem, code, refused}`；
    `problem` 非空时一个字节都不写（已签的是另一份正文 / 目标读不出来）。

    `source_manuscript` 给了就先用与 F 同一套 `validate_manuscript` 判它（形状 /
    依赖段）：来源稿多命题或没有依赖段 ⇒ 两族同一个受控码与同一句 detail。
    """
    sid_text = str(statement_id or "").strip()
    name = _MF.name_reading(_MF.FAMILY_B, statement_id=sid_text,
                            proof_no=proof_no or 1)
    out: dict[str, Any] = {"ok": False, "path": str(name.get("path") or ""),
                           "written": False, "preserved": False, "signed": False,
                           "text": "", "why": "", "problem": {},
                           "code": "", "refused": ""}
    if not name.get("ok"):
        out.update(code=str(name.get("code") or _MF.BAD_MANUSCRIPT_NAME),
                   refused=str(name.get("code") or _MF.BAD_MANUSCRIPT_NAME),
                   why=str(name.get("why") or ""),
                   problem={"kind": str(name.get("code") or _MF.BAD_MANUSCRIPT_NAME),
                            "stage": "name", "why": str(name.get("why") or "")})
        return out
    if not str(proof_text or "").strip():
        out["why"] = "这一笔没有要改写的正文 ⇒ 不落 B 的手稿"
        return out
    source = str(source_manuscript or "")
    if source.strip() and any(h in source for h in
                              ("## 命题", "## 证明", "## 依赖")):
        verdict = _MF.validate_manuscript(source)
        if not verdict.get("ok"):
            out.update(code=str(verdict.get("code") or ""),
                       refused=str(verdict.get("code") or ""),
                       why=str(verdict.get("why") or ""),
                       problem={"kind": str(verdict.get("code") or ""),
                                "stage": "source", "why": str(verdict.get("why") or "")})
            return out
    rows = _dependency_rows(source)
    text = render(statement_full=statement_full, proof_text=proof_text,
                  statement_id=sid_text, label=label, proof_no=proof_no,
                  dependency_section=_DS.render_dependency_section(rows),
                  plan_id=plan_id, sid=sid)
    got = _MF.commit_manuscript(
        root, family=_MF.FAMILY_B, text=text, statement_id=sid_text,
        proof_no=proof_no or 1, old_rel="", retitle="none",
        dependency_rows=rows, write_dependencies=write_dependencies)
    out["text"] = str(got.get("text") or text)
    out["path"] = str(got.get("path") or out["path"])
    out["written"] = bool(got.get("written"))
    out["preserved"] = bool(got.get("preserved"))
    out["signed"] = bool(got.get("signed"))
    out["problem"] = dict(got.get("problem") or {})
    out["code"] = str(got.get("refused") or "")
    out["refused"] = out["code"]
    if got.get("ok"):
        if out["preserved"] and out["signed"]:
            out["why"] = ("`reports/b-proof-<号>.md` 已经是这一份正文的已签版 ⇒ "
                          "一个字节都不动（签跟着正文走）")
        else:
            out["why"] = f"B 的改写手稿已写成：{out['path']}"
        out["ok"] = True
        return out
    if out["code"] == "target_holds_a_signed_version":
        out.update(preserved=True, signed=True)
    out["why"] = str(got.get("why") or "")
    return out


def promote_formal(root: Any, *, statement_id: Any, source: Any = "",
                   text: Any = "", delete_source: bool = False,
                   write_dependencies: Callable[
                       [Sequence[Mapping[str, Any]]],
                       Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """把 B 这一族的一份稿改成 `reports/b-proof-<号>.md`（转发到唯一实现）。

    F 的 `promote_manuscript` 与它是同一段代码（`manuscriptform.promote_formal`），
    两族各一次改名时签块按同一条判据搬、第 9 格按新名重算。
    """
    return _MF.promote_formal(
        root, family=_MF.FAMILY_B, statement_id=statement_id, source=source,
        text=text, delete_source=delete_source,
        write_dependencies=write_dependencies)


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
