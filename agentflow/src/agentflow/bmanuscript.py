# -*- coding: utf-8 -*-
"""B 的改写手稿：B 要把「改写后的正文」交给 V 签，先得有可签的载体。

## 为什么需要这一层

B 的改写要有可签的载体：给 B 手稿签块（与 F/E 同形）。

V 的签落点只有两处：在册命题的台账行、或一份手稿里的签块（`vsigns`）。
B 改写在册证明时，正文与在册命题的正文不同 ⇒ 旧签对不上新正文，台账行也盖不住；
它需要的是一份自己的手稿：`reports/b-proof-<B稿号>.md`，与 F / E 同形
（`## 命题` / `## 证明` / `## 依赖` 三节）。V 读这一份、三转成立后由收方秘书
（`secretary:B`）把签块落回稿里；B 再带这份稿调 `own.register_statement`，
`vsigns.manuscript_sign_standing` 读到「签到位」⇒ 第 3 位翻真、`reviewed=true`。

## B 稿号与命题号解耦

B 的稿名曾经是 `reports/b-proof-<命题号>.md`（`relpath(statement_id)` 拼出来的），
与 F 早先"稿名带命题号/计划号"是同一个毛病：名字里的数字同时被当成两种身份。
现在 B 的稿号由 `manuscriptids.next_manuscript_id(root, family="b-proof")` 发
（`counters.bmanuscript` 一条独立号段），稿名只回答"这是第几份 B 稿"。稿与命题的
对应关系记在稿头那一行 `- 命题号：stmt:<号>`：重新落同一命题时，靠
:func:`manuscript_id_for_statement` 按那一行找回它自己那份稿（而不是按名字里的数字猜）。

一个稿号 = 一份文件 = 一份证明。老盘上的 `reports/b-proof-<命题号>.md` 只读兼容：
名字形状与新名字逐字相同（都是六位），所以分类 / 读正文 / 认签三件事一个字都不用
改；只是新写路径不再把命题号写进稿名。

## 谁写这份稿

B 没有文件写口（工具面只有 `table.*` / `manuscripts.read|list` 这类），所以稿由框架
在 B 的登记入口（`AgentB.register_statement`）里按 B 交上来的正文渲染 ——
B 交的是内容，落盘的是框架，签由收方秘书落。这与 F/E 的分工一致：
作者只写内容，收方读稿落签。

## 与 F 的证明手稿共用一份实现

命名 / 渲染 / 搬签 / 落盘事务 / 拒信码全部在 `agentflow.manuscriptform`（与 F 共用）；
本模块的 `render` / `relpath` / `is_relpath` / `land_rewrite` 只做转发与适配。
`land_rewrite` 的 `write_dependencies` 与 F 的 `promote` 是同一条事务：落边失败
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
#: 文件名前缀（`reports/b-proof-<B稿号>.md`；B 自己那条号段发的号）。
PREFIX = _MF.PREFIX[_MF.FAMILY_B]

#: 稿头里"第几份证明"那一行（渲染与读侧同一个拼法）。
PROOF_NO_PREFIX = _MF.PROOF_NO_MARK

#: 稿头 `- 命题号：` 那一行的引用前缀（与 `schema` 的 `stmt:` 同一套）。
STATEMENT_PREFIX = "stmt:"


def relpath(statement_id: Any, proof_no: Any = 1) -> str:
    """这一条命题的 B 改写手稿落点（工作区相对）；号不合法 ⇒ 空串（不猜位置）。

    老盘的只读口径（新写路径不再用它）：B 的稿名就是
    `reports/b-proof-<命题号>.md`，老盘上那些稿仍是这个形状，读侧要能拼回它们。新写路径的落点由
    `manuscriptids.canonical_rel(稿号, family="b-proof")` 决定 —— 号来自 B 自己的
    计数器，不是命题号。

    拼名转发到 `manuscriptfamily.relpath` 的 `strict=False` 那一档（同一套校验，
    失败回空串 —— 与既有返回值契约一致）。
    """
    from .manuscriptfamily import relpath as _impl
    return _impl("b-proof", str(statement_id or "").strip(), proof_no or 1,
                 strict=False)


def _head_statement_id(text: Any) -> str:
    """一份稿的稿头 `- 命题号：` 那一行 ⇒ 裸命题号（认不出 ⇒ 空串）。"""
    raw = str(header_reading(text).get("statement_id") or "").strip()
    if raw.startswith(STATEMENT_PREFIX):
        raw = raw[len(STATEMENT_PREFIX):].strip()
    return raw


def manuscript_id_for_statement(root: Any, statement_id: Any) -> dict[str, Any]:
    """这一条命题「自己那份 B 稿」是哪一份（按稿头的 `- 命题号：` 行找）。

    ## 为什么不能按名字里的数字找

    B 的稿名曾经是 `reports/b-proof-<命题号>.md`，于是"这一条命题的稿"= "名字里那个
    数字等于命题号的那份文件"。B 稿号独立之后，名字里那个数字是 B 的号段，与命题号
    没有关系 —— 再按数字比就会把别人的稿当成自己的。

    唯一能把稿与命题钉在一起的证据是稿头那一行（框架渲染时写进去的
    `- 命题号：stmt:<号>`）。本函数扫 `reports/b-proof-*.md`、读那一行。

    三态：`checked=False` ⇒ 这一趟没法查（没给根）；`found=False` ⇒ 查过了、没有；
    `found=True` ⇒ 找到了（`manuscript_id` / `path`）。"没查成"绝不折成"没有"。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "manuscript_id": "",
                           "path": "", "candidates": [], "why": ""}
    sid = str(statement_id or "").strip()
    if not sid:
        out.update(checked=True, why="没给命题号 ⇒ 没有可找的稿（不是「没有这份稿」）")
        return out
    if root is None or str(root) == "":
        out["why"] = "这一趟没有工作区根 ⇒ 查不了（不是「没有这份稿」）"
        return out
    base = Path(str(root)) / MANUSCRIPT_DIR
    if not base.is_dir():
        out.update(checked=True, why=f"`{MANUSCRIPT_DIR}/` 不存在 ⇒ 还没有任何 B 稿")
        return out
    hits: list[tuple[bool, str, str]] = []
    for path in sorted(base.glob(f"{PREFIX}*.md")):
        rel = f"{MANUSCRIPT_DIR}/{path.name}"
        parsed = _VS.parse_manuscript_name(rel)
        if not (parsed.get("checked") and parsed.get("family")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _head_statement_id(text) != sid:
            continue
        block = _VS.manuscript_sign_reading(text, manuscript_path=rel)
        hits.append((bool(block.get("found")), rel,
                     str(parsed.get("manuscript_id") or "")))
    out["candidates"] = [rel for _signed, rel, _mid in hits]
    if not hits:
        out.update(checked=True,
                   why=f"`{MANUSCRIPT_DIR}/{PREFIX}*.md` 里没有一份稿头写着 "
                        f"stmt:{sid} ⇒ 这一条命题还没有 B 稿")
        return out
    # 多条同命题（优化副本会让同一命题短暂有两份 B 稿 —— 已签的源稿与
    # 未签的优化副本）：未签的那一份优先。B 正在改的就是它；已签的那一份按冻结
    # 纪律只读（丁），不该被下一笔落稿挑中。同档再按名字序，读数里给全部候选。
    hits.sort(key=lambda item: (item[0], item[1]))
    signed_any, rel, mid = hits[0]
    out.update(checked=True, found=True, manuscript_id=mid, path=rel,
               signed=signed_any,
               why=(f"稿头 `- 命题号：stmt:{sid}` 指向 `{rel}`（候选 "
                    f"{len(hits)} 份；这一份{'已' if signed_any else '未'}签）"))
    return out


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


def header_reading(text: Any) -> dict[str, Any]:
    """读一份稿的页头元信息（纯读；B 的改写稿据此与来源稿同骨架）。

    ## 为什么需要它

    B 的改写稿与 F 的证明手稿必须"除前缀与角色名外逐字相同"，而页头那几行不是渲染
    函数自己能猜出来的：`- 计划：` / 洗稿行 / `- 标签：` / 标题那一段都只活在来源稿
    里。运行期必须由调用点把它们读出来传全，否则 b-稿会缺 `- 计划：`、缺洗稿行，
    或凭 `label` 多出一行 `- 标签：`。

    返回 `{checked, title, statement_id, plan_id, sid, label, wash_actor, wash_filled}`：
    读不出来的格子回空串（不猜）；`checked=False` = 这一份没有页头可读（空稿）。
    """
    raw = str(text or "").replace("\r\n", "\n")
    out: dict[str, Any] = {
        "checked": bool(raw.strip()), "title": "", "statement_id": "",
        "plan_id": "", "sid": "", "label": "", "wash_actor": "", "wash_filled": ""}
    if not raw.strip():
        return out
    lines = raw.split("\n")
    for line in lines[:16]:
        stripped = line.strip()
        if stripped.startswith("#") and not out["title"]:
            # `# <族> 的证明手稿：<标题>`：取最后一个全角冒号之后那一段（标题里允许有冒号）。
            head, sep, tail = stripped.rpartition("：")
            out["title"] = tail.strip() if sep else stripped.lstrip("# ").strip()
            continue
        if stripped.startswith(_MF.STATEMENT_MARK):
            out["statement_id"] = stripped[len(_MF.STATEMENT_MARK):].strip()
            continue
        if stripped.startswith(_MF.PLAN_MARK):
            body = stripped[len(_MF.PLAN_MARK):].strip()
            parts = [p.strip() for p in body.split("·")]
            for part in parts:
                if part.startswith("子目标："):
                    out["sid"] = part[len("子目标："):].strip()
                elif part:
                    out["plan_id"] = part
            continue
        if stripped.startswith(_MF.LABEL_MARK):
            out["label"] = stripped[len(_MF.LABEL_MARK):].strip()
            continue
    wash = _DS.manuscript_wash_reading(raw)
    out["wash_actor"] = str(wash.get("actor") or "")
    out["wash_filled"] = str(wash.get("filled") or "")
    return out


def render(*, statement_full: Any, proof_text: Any, statement_id: Any = "",
           label: Any = "", proof_no: Any = 0,
           dependency_section: str = "", proposition: Any = None,
           plan_id: Any = "", sid: Any = "", wash_actor: Any = "",
           wash_filled: Any = "", title: Any = "") -> str:
    """渲染一份 B 的改写手稿（纯函数，逐字节可复现）。

    三节与 F/E 同形：`## 命题` 是这条命题的完整正文（含假设），`## 证明` 是 B 改写后
    的正文（被签的就是这一节），`## 依赖` 是四列表（空表也是声明）。实现本体是
    `manuscriptform.render_proof_manuscript`（F 的证明手稿走同一段代码），本函数只把
    B 的入参名换成那一套。

    `title` 与 `label` 分开：标题那一段来自来源稿的标题行，而 `- 标签：` 只有来源稿
    真有那一行时才写（b-稿不许凭自己的 `label` 多出一行）。
    """
    full = statement_full if proposition is None else proposition
    return _MF.render_proof_manuscript(
        _MF.FAMILY_B, title=(title or label), statement_id=statement_id,
        proposition=full, proof_text=proof_text,
        dependency_section=dependency_section, plan_id=plan_id, sid=sid,
        label=label, proof_no=proof_no, wash_actor=wash_actor,
        wash_filled=wash_filled)


def land_rewrite(root: Any, *, statement_id: Any, statement_full: Any,
                 proof_text: Any, label: Any = "", proof_no: Any = 0,
                 source_manuscript: Any = "", plan_id: Any = "",
                 sid: Any = "", wash_actor: Any = "", wash_filled: Any = "",
                 title: Any = "", manuscript_id: Any = "",
                 write_dependencies: Callable[
                     [Sequence[Mapping[str, Any]]],
                     Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """把 B 的改写手稿写到 `reports/b-proof-<B稿号>.md`（三态见模块 docstring）。

    `manuscript_id` 是 B 自己那一条号段发的稿号。给了它，
    落点只按它拼（`:func:`manuscriptids.canonical_rel``）；不给 ⇒ 退回老盘的只读口径
    （`reports/b-proof-<命题号>.md`），那是老调用方的形状，新写路径一律给号。

    返回 `{ok, path, written, preserved, signed, text, why, problem, code, refused,
    manuscript_id}`；`problem` 非空时一个字节都不写（已签的是另一份正文 / 目标读不出来）。

    `source_manuscript` 给了就先用与 F 同一套 `validate_manuscript` 判它（形状 /
    依赖段）：来源稿多命题或没有依赖段 ⇒ 两族同一个受控码与同一句 detail。

    `plan_id` / `sid` / `wash_actor` / `wash_filled` / `title` / `label` 是页头那几格：
    运行期由调用点从来源稿读出来传全，于是 b-稿与 f-稿除前缀与角色名外逐字相同。
    不给就照旧（老调用方的返回形状不变）。
    """
    sid_text = str(statement_id or "").strip()
    mid = str(manuscript_id or "").strip()
    # 一个稿号 = 一份文件 = 一份证明：新写路径不按 `proof_no` 拼 `-p<N>` —— 名字只由
    # 稿号（或老盘回退的命题号）决定。`proof_no` 形参保留只为旧调用点不必改签名；
    # 它不参与命名（也不参与渲染：稿头那一行已退役）。
    name = _MF.name_reading(_MF.FAMILY_B, statement_id=sid_text,
                            manuscript_id=mid, proof_no=1)
    out: dict[str, Any] = {"ok": False, "path": str(name.get("path") or ""),
                           "manuscript_id": mid, "written": False, "preserved": False,
                           "signed": False, "text": "", "why": "", "problem": {},
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
                  plan_id=plan_id, sid=sid,
                  wash_actor=wash_actor, wash_filled=wash_filled, title=title)
    got = _MF.commit_manuscript(
        root, family=_MF.FAMILY_B, text=text, statement_id=sid_text,
        manuscript_id=mid, proof_no=1, old_rel="", retitle="none",
        dependency_rows=rows, write_dependencies=write_dependencies)
    out["text"] = str(got.get("text") or text)
    out["path"] = str(got.get("path") or out["path"])
    out["manuscript_id"] = str(name.get("manuscript_id") or mid)
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
                   manuscript_id: Any = "",
                   write_dependencies: Callable[
                       [Sequence[Mapping[str, Any]]],
                       Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """把 B 这一族的一份稿改成 `reports/b-proof-<B稿号>.md`（转发到唯一实现）。

    F 的 `promote_manuscript` 与它是同一段代码（`manuscriptform.promote_formal`），
    两族各一次改名时签块按同一条判据搬、第 9 格按新名重算。

    `manuscript_id`：给了就只按 B 自己的稿号命名；不给则退回老盘口径
    （`b-proof-<命题号>`，只对老盘有意义）。
    """
    return _MF.promote_formal(
        root, family=_MF.FAMILY_B, statement_id=statement_id, source=source,
        text=text, delete_source=delete_source, manuscript_id=manuscript_id,
        write_dependencies=write_dependencies)


def read_rewrite(root: Any, rel: Any) -> dict[str, Any]:
    """读一份 B 的改写手稿（V 与 B 用同一处口径）。

    三态：文件不在盘上 ⇒ `state=missing`；读不出来 ⇒ `state=unreadable`；
    读到了 ⇒ `state=present`。另带 `proof_state`：
    稿里 `## 证明` 那一节是 `present` / `absent` —— 缺节时 `proof_body=""`，
    不拿 `## 依赖` 或整份全文顶替（调用方必须自己判，不把它读成"证明为空"）。
    """
    raw = str(rel or "").strip().replace("\\", "/")
    out: dict[str, Any] = {"ok": False, "state": "outside", "path": raw, "text": "",
                           "proof_body": "", "proof_state": "", "why": ""}
    if not is_relpath(raw):
        out["why"] = f"{raw!r} 不是 B 的改写手稿形态（`reports/b-proof-<号>.md`）"
        return out
    target = Path(str(root)) / raw
    if not target.is_file():
        out["state"] = "missing"
        out["why"] = f"手稿不在盘上：{raw}"
        return out
    reading = _DS.read_proof_body(root, raw)
    if not reading.get("checked"):
        out["state"] = "unreadable"
        out["why"] = str(reading.get("why") or "手稿读不出来")
        return out
    out["text"] = str(reading.get("text") or "")
    out["proof_body"] = str(reading.get("body") or "").strip("\n")
    out["proof_state"] = str(reading.get("state") or "")
    out.update(ok=True, state="present", why="")
    return out
