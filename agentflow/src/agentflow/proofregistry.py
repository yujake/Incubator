# -*- coding: utf-8 -*-
"""手稿登记（把「登记命题」与「写/改证明」解耦；业主 2026-11-07 裁定）。

## 业主要的两件事（逐字）

> 「要让注册命题和写证明两件事解耦，不然无法做到只一遍又一遍修改证明」
> 「F侧反复修改一个命题的证明时要直接动那个命题所指手稿的 proof 板块」
> 「就是F侧登记新命题F秘书闸拦的那块」

⇒ 一次登记（过 F 秘书的形态闸）之后，反复改证明不再登记：只改同一份手稿的
`## 证明` 那一节（顺手按 cites 重渲 `## 依赖`），把 `proof_no` 递增、`正文 sha256` 重算。
不新落第二个文件（不出现 `f-proof-000041-v2.md` 这类名字），也不新落 statements 行。

## 登记条目住在哪（没有新表、没有新列）

业主 2026-11-07（逐字）：「手稿文件本身（规范路径 + 文件头元信息：命题文本 / 证明号 /
正文 sha256 / cites）」「`attack_plans.history` 的既有格（`manuscript_path` 等）里带上
这份稿的身份」「不要开新表」。所以：

1. 手稿文件就是登记条目（唯一落点，`manuscriptform.name_reading` 定的规范路径）：
   `reports/f-proof-<命题号>.md`（B 侧 `reports/b-proof-<命题号>.md`；还没有命题号时
   按计划名 `reports/f-proof-plan-<计划号>.md`，与既有两段命名一致）。文件头多了四行
   元信息（都只在给了值时才写，旧稿逐字节不变）：

   ```
   - 证明号：<N>            （既有那一行，`manuscriptform.PROOF_NO_MARK`）
   - 正文sha：<sha256>      （`## 证明` 那一节的 sha256 —— 与 V 签盖的是同一把尺）
   - 命题指纹：<sha256>     （`## 命题` 那一节规范化后的 sha256，判"还是不是同一条命题"）
   - 证据种类：<kind>       （`lemma` / `theorem` / `conjecture` …，B 收录时按它落 kind）
   - 登记时间：<ISO8601>    （这一条第一次落成手稿的时刻；重写不改它）
   - 版本：p<N>@<ISO8601>@<sha256>；p<N-1>@…   （append-only，每次重写追加一格）
   ```

2. `attack_plans.history` 的既有格（F 侧）：每轮那一行照旧落 `manuscript_path` /
   `manuscript_proof_no` / `manuscript_sha256` / `manuscript_registered` / `manuscript_label`
   —— 于是"这一轮是登记还是重写"在计划台账上读得出来。B 侧没有 attack_plans，身份就在
   手稿头的 `- 版本：` 那一行里（同一份文件，不是第二张账）。

3. 没有新表、没有新列：`schema.py` 零改动（判据 `tests/test_proof_registration_is_decoupled.py`
   的 f 那一格）。

## 什么算「新命题」（这是"过不过闸"的唯一判据）

- 手稿登记里没有同 label 的条目 ⇒ 新命题 ⇒ 过 F 秘书形态闸（`gate` 回调，一次）；
- 有同 label 的条目、且 `## 命题` 的规范化指纹相同 ⇒ 重写证明 ⇒ 不过闸、不登记；
- 有同 label 的条目、而命题指纹不同 ⇒ 受控拒 `proposition_text_changed`
  （"这是新命题／或走放弃+换号，不要用挂证明改命题正文"）。

为什么"同 label + 命题指纹"两条都看：label 是作者给的粗键（同一子目标的第 N 轮），
指纹是内容键。只看 label 会把"同一个子目标换了命题"读成重写（静默改命题，正是这次要
消灭的形态）；只看指纹则同一命题的标点级改写会变成"新命题"（多登记一次）。
所以：label 定"这是不是同一个登记槽"，指纹定"这个槽里是不是同一条命题"。

## 手稿由框架写

`reserved_framework_artifact` 的既有口径不变：`fs.write` / `fs.edit` 仍写不了
`f-proof-*` / `b-proof-*`。本模块是框架侧的落稿入口（作者的正文由调用方传进来）。

## 分节哈希（判据 i 的机器证据）

`section_hashes(text)` 按 `## ` 切节、逐节 sha256；重写那一笔只换 `## 证明`（与它后面
的 `## 依赖`），所以「其余小节的分节哈希逐次相同、`## 证明` 的逐次不同」是可直接读的。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import depsection as _DS
from . import manuscriptform as _MF
from . import verifications as _VR

#: 手稿头里的元信息标记（与 `manuscriptform` 的既有标记同一个风格；只增不改）。
SHA_MARK = "- 正文sha："
FINGERPRINT_MARK = "- 命题指纹："
KIND_MARK = "- 证据种类："
REGISTERED_AT_MARK = "- 登记时间："
VERSION_MARK = "- 版本："

#: 受控码（写读两侧共用，不另起第二套词）。
REFUSED_TEXT_CHANGED = "proposition_text_changed"
REFUSED_GATE = "proposition_form_refused"
REFUSED_PATH = "manuscript_path_unavailable"
REFUSED_READ = "manuscript_unreadable"
REFUSED_WRITE = "manuscript_write_failed"
REFUSED_SHAPE = "manuscript_shape_refused"

#: 「新命题 / 重写」两档（读数用；不参与任何判据分支的第三档）。
MODE_REGISTERED = "registered"
MODE_REWRITTEN = "rewritten"

#: `- 版本：` 那一格的条目分隔符。
_VERSION_SEP = "；"

_SECTION_RE = re.compile(r"^##\s+(?P<name>.+?)\s*$")


def _now() -> str:
    """这一笔的时间戳（唯一实现在 `schema.now_iso`；这里只转发，不写第二份）。"""
    from .schema import now_iso

    return str(now_iso())


def _norm(text: Any) -> str:
    """规范化（判"还是不是同一条命题"用的那把尺；只归一空白与全半角空格）。"""
    return " ".join(str(text or "").replace("\u3000", " ").split())


def proposition_fingerprint(proposition: Any) -> str:
    """命题指纹：规范化之后 sha256（与 `## 命题` 那一节的字节无关）。"""
    return hashlib.sha256(_norm(proposition).encode("utf-8")).hexdigest()


def proof_sha(proof_text: Any) -> str:
    """`## 证明` 那一节的 sha256（与 V 签盖的是同一把尺）。

    2026-11-09（D4）：入参有两种形态 —— 一份手稿（有 `## 证明` 那一节）或
    一段证明正文（登记/重写那一笔直接把正文交进来，没有小节标题）。后者按
    `depsection.proof_body_or_whole` 的显式回退取整份正文（`fell_back=True`
    在那一格内部），否则 `proof_body` 严格化之后这里会把"一段正文"算成空串的 sha
    （`e3b0c44…`），版本号与正文 sha 会一起失真。

    ## 为什么这里允许"退而取全文"（这一句是给后人的）
    `proof_sha` 的入参在登记/重写路径上就是一段没有 markdown 标题的证明正文
    （`register_or_rewrite` 的 `proof_text`），把它当手稿切小节只会得到空串；
    而 sha 一旦变成空串的 sha，版本记录与 V 签的对拍会同时静默失真。
    所以这一处走显式回退，并且只在这一处用 `proof_body_or_whole`。
    """
    reading = _DS.proof_body_or_whole(str(proof_text or ""))
    body = str(reading.get("body") or "").strip("\n")
    return _VR.proof_sha(body)


# ---------------------------------------------------------------- 分节（切 / 换 / 哈希）

def split_sections(text: Any) -> tuple[str, list[tuple[str, str]]]:
    """把手稿切成 `(头部, [(节名, 节内容), …])`；内容不含节标题那一行。"""
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    if not starts:
        return "\n".join(lines), []
    head = "\n".join(lines[: starts[0]])
    out: list[tuple[str, str]] = []
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        name = lines[i][3:].strip()
        out.append((name, "\n".join(lines[i + 1: end])))
    return head, out


def section_hashes(text: Any) -> dict[str, str]:
    """按 `## ` 切节算 sha256：`{"## 命题": …, "## 证明": …, "## 依赖": …}`。

    节名保留 `## ` 前缀（读的人不必猜是哪个键）；同一节重复出现时按出现次序加 `#2`。
    """
    _head, sections = split_sections(text)
    out: dict[str, str] = {}
    seen: dict[str, int] = {}
    for name, body in sections:
        key = f"## {name}"
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key = f"{key}#{seen[key]}"
        out[key] = hashlib.sha256(body.strip("\n").encode("utf-8")).hexdigest()
    return out


def _replace_section(text: str, name: str, body: str) -> tuple[str, bool]:
    """只换 `## <name>` 那一节的内容，其余字节原样（判据 i 的"只动那一块"）。"""
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    starts = [i for i, line in enumerate(lines) if _SECTION_RE.match(line)]
    for k, i in enumerate(starts):
        if _SECTION_RE.match(lines[i]).group("name").strip() != name:
            continue
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        mid = [""] + str(body).strip("\n").split("\n")
        if end < len(lines) or (lines and lines[-1] == ""):
            mid.append("")
        lines[i: end] = [lines[i]] + mid
        return "\n".join(lines), True
    return text, False


# ---------------------------------------------------------------- 头部元信息（解析 / 改写）

def parse_entry(text: Any) -> dict[str, Any]:
    """读手稿头的登记元信息（纯读；读不出来给空串，不猜）。"""
    head, _sections = split_sections(text)
    out: dict[str, Any] = {
        "statement_id": "", "plan_id": "", "sid": "", "label": "", "proof_no": 0,
        "sha256": "", "fingerprint": "", "kind": "", "registered_at": "",
        "versions": [], "checked": False, "problems": [],
    }
    for line in head.split("\n"):
        raw = line.strip()
        if raw.startswith(_MF.STATEMENT_MARK):
            got = raw[len(_MF.STATEMENT_MARK):].strip()
            if got.startswith("stmt:"):
                got = got[5:].strip()
            out["statement_id"] = "" if got.startswith("（") else got
        elif raw.startswith(_MF.PLAN_MARK):
            got = raw[len(_MF.PLAN_MARK):].strip()
            plan, _, rest = got.partition("·")
            out["plan_id"] = plan.strip()
            if "子目标：" in rest:
                out["sid"] = rest.split("子目标：", 1)[1].strip()
        elif raw.startswith(_MF.LABEL_MARK):
            out["label"] = raw[len(_MF.LABEL_MARK):].strip()
        elif raw.startswith(_MF.PROOF_NO_MARK):
            got = raw[len(_MF.PROOF_NO_MARK):].strip()
            try:
                out["proof_no"] = int(got or 0)
            except ValueError:
                out["problems"].append(f"证明号读不出整数：{got!r}")
        elif raw.startswith(SHA_MARK):
            out["sha256"] = raw[len(SHA_MARK):].strip().lower()
        elif raw.startswith(FINGERPRINT_MARK):
            out["fingerprint"] = raw[len(FINGERPRINT_MARK):].strip().lower()
        elif raw.startswith(KIND_MARK):
            out["kind"] = raw[len(KIND_MARK):].strip()
        elif raw.startswith(REGISTERED_AT_MARK):
            out["registered_at"] = raw[len(REGISTERED_AT_MARK):].strip()
        elif raw.startswith(VERSION_MARK):
            payload = raw[len(VERSION_MARK):].strip()
            for item in payload.split(_VERSION_SEP):
                item = item.strip()
                if not item:
                    continue
                parts = item.split("@", 2)
                got = {"raw": item, "proof_no": 0, "at": "", "sha256": ""}
                if len(parts) == 3:
                    try:
                        got["proof_no"] = int(parts[0].lstrip("pP") or 0)
                    except ValueError:
                        got["proof_no"] = 0
                    got["at"] = parts[1].strip()
                    got["sha256"] = parts[2].strip().lower()
                out["versions"].append(got)
    out["checked"] = bool(out["versions"] or out["sha256"] or out["fingerprint"])
    return out


def render_version(proof_no: Any, at: Any, sha: Any) -> str:
    return f"p{int(proof_no or 0)}@{str(at or '')}@{str(sha or '')}"


def _rewrite_head(head: str, values: Mapping[str, str]) -> str:
    """就地改写头部的那几行（缺的按固定次序插在 `- 证明号：` 之后）。

    `- 版本：` 是 append-only 的一整行（一次重写 append 一格），所以它与其他标记同样
    替换：`values[VERSION_MARK]` 已经是"旧版本 + 这一版"的完整清单。
    """
    lines = head.split("\n")
    order = [SHA_MARK, FINGERPRINT_MARK, KIND_MARK, REGISTERED_AT_MARK, _MF.LABEL_MARK]
    touched: set[str] = set()
    out: list[str] = []
    for line in lines:
        raw = line.strip()
        hit = next((mark for mark in [_MF.PROOF_NO_MARK, *order, VERSION_MARK]
                    if raw.startswith(mark)), "")
        if hit and hit in values and str(values[hit]) != "":
            if hit in touched:   # 同一格出现第二次（手写稿／旧格式）⇒ 只留一份
                continue
            touched.add(hit)
            out.append(f"{hit}{values[hit]}")
            if hit == _MF.PROOF_NO_MARK:
                for mark in order:
                    if mark in values and str(values[mark]) != "" and mark not in touched:
                        out.append(f"{mark}{values[mark]}")
                        touched.add(mark)
            continue
        out.append(line)
    missing = [mark for mark in [*order, VERSION_MARK]
               if mark in values and str(values[mark]) != "" and mark not in touched]
    if missing:
        # `- 证明号：` 那一行都没有的旧稿：插在头部最后一行之前（贴近稿头，不污染分节）。
        at = len(out)
        while at > 0 and not out[at - 1].strip():
            at -= 1
        for mark in reversed(missing):
            out.insert(at, f"{mark}{values[mark]}")
    return "\n".join(out)


def _versions_block(entry: Mapping[str, Any], *, proof_no: int, at: str,
                    sha: str) -> tuple[str, list[dict[str, Any]]]:
    """把这一版追进 `- 版本：` 那一行（一次重写只加一格；同一版重复写 ⇒ 幂等）。"""
    versions = [dict(v) for v in (entry.get("versions") or [])]
    if not versions and int(entry.get("proof_no") or 0) >= 1 and entry.get("sha256"):
        versions.append({"proof_no": int(entry["proof_no"]),
                         "at": str(entry.get("registered_at") or ""),
                         "sha256": str(entry.get("sha256") or "")})
    if versions and int(versions[-1].get("proof_no") or 0) == int(proof_no) \
            and str(versions[-1].get("sha256") or "") == str(sha):
        return "", versions
    versions.append({"proof_no": int(proof_no), "at": str(at), "sha256": str(sha)})
    return _VERSION_SEP.join(render_version(v.get("proof_no"), v.get("at"), v.get("sha256"))
                            for v in versions), versions


# ---------------------------------------------------------------- 槽位识别（A1/A2）

def same_slot_reading(entry: Mapping[str, Any], *, statement_id: Any = "", plan_id: Any = "",
              sid: Any = "", label: Any = "") -> bool:
    """盘上这一条登记条目与这一笔要写的是不是「同一条命题的槽」。

    三种身份键，按优先级取第一个两边都有的：

    1. 命题号（`- 命题号：stmt:<号>`）：拿到号之后，号就是身份；
    2. `（计划号，子目标）`（`- 计划：<plan> · 子目标：<sid>`）：F 还没有号时，
       这是唯一稳定的槽位键 —— 计划稿的路径里没有子目标，光看路径会把同一计划下
       的不同子目标读成同一槽；
    3. `- 标签：`：只有前两样都缺时才用（旧稿 / 手写稿的兜底）。

    调用方必须先确认 `entry["checked"]`（有正文 sha / 命题指纹 / 版本记录）：
    手写稿可以给自己写一行 `- 标签：`，但它没有登记元信息，不是登记条目
    （A3 的判据 `test_a_handwritten_labelled_head_is_not_an_entry`）。

    为什么要有这一格：改前 `register_or_rewrite` 只比 label，而生产路径
    （`agent_f/core.py::_apply_round` → `proof_manuscript` 先写一份计划稿）那一份
    稿头没有 `- 标签：`（渲染时 `label=""`）⇒ 每一轮都读成"新命题" ⇒ 每轮重新登记
    （实测 3 轮 `modes=[registered×3]`、闸 3 次、`proof_no=[1,1,1]`）。
    槽位从稿头元信息取，于是"传不传 `manuscript_text`"不再决定解耦成不成立。
    """
    want_sid = str(statement_id or "").strip()
    have_sid = str(entry.get("statement_id") or "").strip()
    if want_sid and have_sid:
        return want_sid == have_sid
    want_plan = str(plan_id or "").strip()
    have_plan = str(entry.get("plan_id") or "").strip()
    if want_plan and have_plan and want_plan == have_plan:
        want_sg = str(sid or "").strip()
        have_sg = str(entry.get("sid") or "").strip()
        return not want_sg or not have_sg or want_sg == have_sg
    want_label = str(label or "").strip()
    have_label = str(entry.get("label") or "").strip()
    return bool(want_label) and want_label == have_label


def _find_registered_text(root: Any, *, family: Any, statement_id: Any = "",
                          plan_id: Any = "", sid: Any = "", label: Any = "",
                          exclude: Any = "") -> dict[str, Any]:
    """在 `reports/` 下按槽位找一份已在册的条目：拿号前后是同一份稿，不换槽。

    返回 `{"path", "text", "entry"}`；找不到 ⇒ `{}`。只在规范路径上没有条目时用：
    命题在 V 签之后被 B 收录、拿到命题号，落点从 `f-proof-plan-<计划>.md` 变成
    `f-proof-<号>.md` —— 这一条不认旧路径，就会在拿号之后重新登记一次
    （版本历史从 1 重来、形态闸再跑一次），而"一份命题只住一份稿"就断了。
    """
    prefix = _MF.PREFIX.get(str(family or ""), "")
    if not prefix:
        return {}
    base = Path(str(root or "")) / _MF.MANUSCRIPT_DIR
    if not base.is_dir():
        return {}
    want_rel = str(exclude or "").strip()
    for path in sorted(base.glob(f"{prefix}*.md")):
        rel = f"{_MF.MANUSCRIPT_DIR}/{path.name}"
        if rel == want_rel:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        got = parse_entry(text)
        if not got.get("checked"):
            continue
        if same_slot_reading(got, statement_id=statement_id, plan_id=plan_id,
                     sid=sid, label=label):
            return {"path": rel, "text": text, "entry": got}
    return {}


# ---------------------------------------------------------------- 路径（唯一来源：manuscriptform）

def entry_relpath(*, family: Any, statement_id: Any = "", plan_id: Any = "") -> str:
    """这一条命题的手稿落点（`manuscriptform.name_reading`；认不出 ⇒ 空串，不猜）。"""
    got = _MF.name_reading(family, statement_id=statement_id, plan_id=plan_id)
    return str(got.get("path") or "") if got.get("ok") else ""


def read_entry(root: Any, *, family: Any, statement_id: Any = "",
               plan_id: Any = "") -> dict[str, Any]:
    """读这一条命题的登记条目（手稿 + 头部元信息）；稿不在 ⇒ `exists=False`。"""
    rel = entry_relpath(family=family, statement_id=statement_id, plan_id=plan_id)
    out: dict[str, Any] = {"checked": True, "exists": False, "path": rel, "text": "",
                           "entry": parse_entry(""), "why": ""}
    if not rel:
        out.update(checked=False, why=f"手稿落点认不出（family={family!r}，"
                                      f"statement_id={statement_id!r}，plan_id={plan_id!r}）")
        return out
    path = Path(str(root or "")) / rel
    if not path.is_file():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        out.update(checked=False, why=f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）")
        return out
    out.update(exists=True, text=text, entry=parse_entry(text))
    return out


# ---------------------------------------------------------------- 登记 / 重写（唯一写入口）

def _head_for_new_version(text: str, *, proof_no: int, new_sha: str, new_fp: str,
                          label: Any, kind: Any, mode: str, entry: Mapping[str, Any],
                          at_text: str, versions_line: str,
                          statement_id: Any) -> str:
    """把稿头元信息改成本笔这一版（`## 证明` 之后一个字节不动），并补上命题号那一行。

    稿头那一行必须写上这一笔的命题号（2026-11-07：解耦之后的漏格）。解耦之后登记条的
    底稿常常是 `proof_manuscript` 先写的那份计划稿，而它渲染时还没有命题号
    （`manuscriptform.render_proof_manuscript` 写的是 `- 命题号：stmt:（还没落号）`）。
    `_rewrite_head` 只管元信息那几行、不碰这一行，于是登记落在
    `reports/f-proof-<号>.md` 上而稿头仍说"还没落号"—— 双读数。后果是可直接读到的：
    `entries_on_disk` 把这一条读成"未落号的登记条目"，D 的携带单于是把同一份稿再列一遍
    （`mss:<号>` 与 `stmt:<号>` 两行、路径与 sha 相同），而按号核对携带单的那一侧找不到
    它。号已经拿到 ⇒ 这一行必须写它。

    这一段是纯搬移：`register_or_rewrite` 原来内联在这里的几行原样搬进来，
    入参与返回值都是原来的那几格（拆分只为了把 210 行压回 200 行以内）。
    """
    head_now = split_sections(text)[0]
    head_new = _rewrite_head(head_now, {
        _MF.PROOF_NO_MARK: str(proof_no),
        SHA_MARK: new_sha, FINGERPRINT_MARK: new_fp,
        _MF.LABEL_MARK: str(label or ""),
        KIND_MARK: (str(kind or "") if mode == MODE_REGISTERED
                    else str(kind or entry.get("kind") or "")),
        REGISTERED_AT_MARK: (at_text if mode == MODE_REGISTERED
                             else str(entry.get("registered_at") or at_text)),
        VERSION_MARK: versions_line,
    })
    text = head_new + text[len(head_now):]
    if str(statement_id or "").strip():
        text, _applied = _MF.ensure_statement_line(text, str(statement_id))
    return text


def register_or_rewrite(
    root: Any, *, family: Any, label: str, proposition: str, proof_text: str,
    dependency_rows: Sequence[Mapping[str, Any]] = (),
    statement_id: Any = "", plan_id: Any = "", sid: Any = "", title: Any = "",
    kind: Any = "", author: Any = "", at: Any = "", template: str = "",
    gate: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """登记一条新命题（过闸一次）／重写一条已登记命题的证明（不过闸、不登记）。

    `template` 是新命题那一档的底稿（调用方刚渲染并洗过的那一份手稿正文）：
    给了就用它当基稿（只补头部的登记元信息），于是洗稿元信息、依赖段一个字节都不丢；
    不给就按 `proposition` / `proof_text` / `dependency_rows` 现渲染。

    返回（键固定）：
    `{checked, ok, mode, statement_id, proof_no, manuscript_path, sha256, deps_rows,
      problems, refused, why, entry, section_hashes, gate, written, migrated}`。

    - `mode="registered"`：这一条第一次落成手稿（过闸；`gate` 读数的原文在 `gate`）；
    - `mode="rewritten"`：同一条命题的下一版证明（`## 证明` 就地换、`proof_no` 递增）；
    - `ok=False` 时 `refused` 是受控码，盘上一个字节都不动（`written=False`）。
    """
    at_text = str(at or "") or _now()
    rel = entry_relpath(family=family, statement_id=statement_id, plan_id=plan_id)
    out: dict[str, Any] = {
        "checked": True, "ok": False, "mode": "", "statement_id": str(statement_id or ""),
        "proof_no": 0, "manuscript_path": rel, "sha256": "", "deps_rows": [],
        "problems": [], "refused": "", "why": "", "entry": {}, "gate": {},
        "written": False, "section_hashes": {}, "migrated": False, "preserved": False,
        "relocated_from": "",
    }
    if not rel:
        out.update(refused=REFUSED_PATH,
                   why=(f"手稿落点认不出（family={family!r}、statement_id={statement_id!r}、"
                        f"plan_id={plan_id!r}）⇒ 不登记、不写盘"))
        return out
    before = read_entry(root, family=family, statement_id=statement_id, plan_id=plan_id)
    if not before.get("checked"):
        out.update(checked=False, refused=REFUSED_READ,
                   why=f"登记条目读不出来 ⇒ 没查成（不是「新命题」）：{before.get('why')}")
        return out
    old_text = str(before.get("text") or "")
    entry = dict(before.get("entry") or {})
    new_fp = proposition_fingerprint(proposition)
    # ---- 槽位识别（A1）：先看规范路径；不在册/路径换了再看同一槽的旧落点 -----------
    #
    # `checked` 是"这是不是一条登记条目"的判据（A3）：手写稿可以自己写一行
    # `- 标签：`，但它没有正文 sha / 命题指纹 / 版本记录 ⇒ 不是在册条目。
    same_slot = bool(before.get("exists") and entry.get("checked")
                     and same_slot_reading(entry, statement_id=statement_id,
                                           plan_id=plan_id, sid=sid, label=label))
    relocated_from = ""
    if not same_slot:
        found = _find_registered_text(root, family=family, statement_id=statement_id,
                                      plan_id=plan_id, sid=sid, label=label,
                                      exclude=rel)
        if found:
            relocated_from = str(found.get("path") or "")
            old_text = str(found.get("text") or "")
            entry = dict(found.get("entry") or {})
            same_slot = True
    out["relocated_from"] = relocated_from
    old_fp = str(entry.get("fingerprint") or "")
    migrated = False
    if same_slot and not old_fp:
        # 旧稿（解耦之前落的那一批）没有指纹行：这一笔是"给旧稿补上登记元信息"，
        # 不是"改命题"。补的时候不拿旧稿的 `## 命题` 去拒新正文 —— 权威判定在调用方
        # （F 已经按 statements 那一行核过命题正文），这里只如实标 `migrated=True`。
        _head, sections = split_sections(old_text)
        old_prop = next((body for name, body in sections if name == "命题"), "")
        entry["fingerprint"] = proposition_fingerprint(old_prop) if old_prop.strip() else ""
        migrated = True
    if same_slot and old_fp and old_fp != new_fp:
        out.update(refused=REFUSED_TEXT_CHANGED,
                   why=("命题正文与登记条目里那一条不一致（指纹 "
                        f"{old_fp[:12]}… → {new_fp[:12]}…）⇒ 受控拒。"
                        "这是**另一条新命题**（走登记），或者要走「放弃 + 换号」；"
                        "**不要用挂证明改命题正文** —— 重写只能改 `## 证明` 那一节"),
                   entry=entry, problems=["proposition_text_changed"])
        return out
    mode = MODE_REWRITTEN if same_slot else MODE_REGISTERED
    # ---- 幂等：同一份正文再挂一次 ⇒ 一个字节都不动（版本号也不涨） ------------------
    #
    # 真机上 D 的交付动作每写一份报告都会把同一批稿再递一遍（`write_report` 每次都跑），
    # 而"同一份正文"不该被记成第 N+1 版 —— 否则 `proof_no` 会被无意义的重复递交顶高，
    # V 台账也会被同一 sha 灌满。
    if (mode == MODE_REWRITTEN and str(entry.get("fingerprint") or "") == new_fp
            and proof_sha(proof_text) == str(entry.get("sha256") or "")):
        out.update(ok=True, checked=True, mode=mode,
                   proof_no=int(entry.get("proof_no") or 1),
                   sha256=str(entry.get("sha256") or ""),
                   deps_rows=[dict(r) for r in (dependency_rows or [])],
                   written=False, preserved=True, entry=dict(entry),
                   section_hashes=section_hashes(old_text), why="")
        return out
    # ---- 新命题：登记这一刻过 F 秘书的形态闸（只在这里跑；重写永不再跑） ----------
    gate_reading: dict[str, Any] = {}
    if mode == MODE_REGISTERED and gate is not None:
        try:
            gate_reading = dict(gate(statement_full=str(proposition or ""),
                                     kind=str(kind or ""), body=str(proof_text or ""),
                                     label=str(label or "")) or {})
        except Exception as exc:  # noqa: BLE001 —— 闸自己炸了 = 没判成（fail-closed）
            gate_reading = {"checked": False, "well_formed": False, "submittable": False,
                            "refused": REFUSED_GATE,
                            "reason": f"形态闸抛了（{type(exc).__name__}: {exc}）⇒ 没判成",
                            "problems": []}
        out["gate"] = gate_reading
        if not gate_reading.get("submittable"):
            problems = [str(x) for x in (gate_reading.get("problems") or [])]
            out.update(checked=bool(gate_reading.get("checked", False)),
                       refused=REFUSED_GATE,
                       problems=problems,
                       why=("命题形态闸没放行 ⇒ 这一条不登记、不落盘（手稿一个字节都没写）："
                            + str(gate_reading.get("reason") or "形态不合规")
                            + ("；逐条缺什么：" + "；".join(problems[:4])
                               if problems else "")),
                       entry=entry)
            return out
    # ---- 渲染：新命题整份渲染；重写只换 `## 证明` 与它后面的 `## 依赖` -------------
    rows = [dict(r) for r in (dependency_rows or [])]
    deps_section = _DS.render_dependency_section(rows)
    new_sha = proof_sha(proof_text)
    proof_no = int(entry.get("proof_no") or 0) + 1 if mode == MODE_REWRITTEN else 1
    if mode == MODE_REGISTERED:
        versions_line = render_version(1, at_text, new_sha)
        versions = [{"proof_no": 1, "at": at_text, "sha256": new_sha}]
        if str(template or "").strip():
            # 调用方刚渲染并洗过的那一份：拿它当基稿（洗稿行 / 依赖段原样保留）。
            text = str(template).replace("\r\n", "\n")
            # `## 证明` 的内容以参数为准：template 也可能是一份"骨架"（B 的改写拿
            # F 的稿当底稿时就是这样，正文必须换成 B 交来的那一份）。
            # 2026-11-09（D4）：`proof_body` 缺节 ⇒ 空串（不回退到依赖段 / 全文）⇒
            # 与参数正文的 sha 不同 ⇒ 走 `_replace_section`；基稿若没有那一节，
            # 下面会受控拒 / 整份重渲染（`_replace_section` 的 `ok` 说了算）。
            if str(proof_text or "").strip() and not proof_sha(proof_text) == proof_sha(
                    _DS.proof_body(text)):
                text, _ok_proof = _replace_section(text, "证明", str(proof_text))
                if not _ok_proof:
                    text = _MF.render_proof_manuscript(
                        family, title=title, statement_id=statement_id,
                        proposition=proposition, proof_text=proof_text,
                        dependency_section=deps_section, plan_id=plan_id, sid=sid,
                        label=label, proof_no=proof_no)
            if rows and not _DS.parse_dependency_section(text).get("present"):
                deps_body = (deps_section[len(_DS.SECTION_HEADING):]
                             if deps_section.startswith(_DS.SECTION_HEADING) else deps_section)
                text, _added = _replace_section(text, "依赖", deps_body)
        else:
            text = _MF.render_proof_manuscript(
                family, title=title, statement_id=statement_id,
                proposition=proposition, proof_text=proof_text,
                dependency_section=deps_section, plan_id=plan_id, sid=sid,
                label=label, proof_no=proof_no)
    else:
        versions_line, versions = _versions_block(
            entry, proof_no=proof_no, at=at_text, sha=new_sha)
        text = old_text
        text, ok_proof = _replace_section(text, "证明", proof_text)
        if not ok_proof:
            out.update(refused=REFUSED_SHAPE,
                       why="手稿里没有 `## 证明` 那一节 ⇒ 没有可替换的板块（不整份重写）")
            return out
        deps_body = (deps_section[len(_DS.SECTION_HEADING):]
                     if deps_section.startswith(_DS.SECTION_HEADING) else deps_section)
        text, _ok_deps = _replace_section(text, "依赖", deps_body)
    # 头部元信息就地更新（其余字节原样 —— 判据 i 的"只动那一块"），并补上命题号那一行。
    # 那一段（含"为什么必须写命题号"的现场）搬进 `_head_for_new_version`：纯搬移。
    text = _head_for_new_version(
        text, proof_no=proof_no, new_sha=new_sha, new_fp=new_fp, label=label,
        kind=kind, mode=mode, entry=entry, at_text=at_text,
        versions_line=versions_line, statement_id=statement_id)
    # ---- 落盘（框架写；原子替换） ------------------------------------------------
    target = Path(str(root or "")) / rel
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        _MF._atomic_write(target, text)
    except OSError as exc:
        out.update(checked=True, refused=REFUSED_WRITE,
                   why=f"手稿没写成（{type(exc).__name__}: {exc}）⇒ 登记条目没有落盘")
        return out
    # ---- 换槽迁移：拿到命题号之后落点换了名，旧名那一份要收掉（一份命题只住一份稿）--
    if relocated_from and relocated_from != rel:
        try:
            (Path(str(root or "")) / relocated_from).unlink(missing_ok=True)
        except OSError:  # noqa: BLE001 —— 旧名删不掉只多一份稿，不改这一笔的结论
            out["relocated_kept"] = relocated_from
    out.update(ok=True, checked=True, mode=mode, proof_no=proof_no, sha256=new_sha,
               deps_rows=rows, written=True, migrated=migrated,
               entry={**entry, "label": str(label or ""), "statement_id": str(statement_id or ""),
                      "proof_no": proof_no, "sha256": new_sha, "fingerprint": new_fp,
                      "kind": str(kind or entry.get("kind") or ""),
                      "registered_at": str(entry.get("registered_at") or at_text),
                      "versions": versions},
               section_hashes=section_hashes(text), why="")
    return out


# ---------------------------------------------------------------- 读数（proof_revisions）

def entries_on_disk(root: Any) -> list[dict[str, Any]]:
    """扫 `reports/` 下的证明手稿，返回逐份的登记条目（纯读）。"""
    base = Path(str(root or "")) / _MF.MANUSCRIPT_DIR
    out: list[dict[str, Any]] = []
    if not base.is_dir():
        return out
    for family, prefix in ((_MF.FAMILY_F, _MF.PREFIX[_MF.FAMILY_F]),
                           (_MF.FAMILY_B, _MF.PREFIX[_MF.FAMILY_B])):
        for path in sorted(base.glob(f"{prefix}*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            got = parse_entry(text)
            rel = f"{_MF.MANUSCRIPT_DIR}/{path.name}"
            if not got.get("checked"):
                continue
            out.append({"family": family, "path": rel, "label": str(got.get("label") or ""),
                        "statement_id": str(got.get("statement_id") or ""),
                        "proof_no": int(got.get("proof_no") or 0),
                        "sha256": str(got.get("sha256") or ""),
                        "versions": [dict(v) for v in (got.get("versions") or [])],
                        "kind": str(got.get("kind") or "")})
    return out


def proof_revisions(store: Any) -> dict[str, Any]:
    """逐命题读「登记了几次 / 挂过几次证明 / 每次的 sha 与 proof_no / 有几次被判有毛病」。

    "登记了几次"按条目算（一条在册命题的手稿条目 = 一次登记；同一个 label 的手稿只有
    一份是这次解耦的直接形态）；"被判有毛病"读两处：形态闸台账（`proposition_form`）
    与计划历史里那些 `proposition_form_refused` / `proposition_text_changed` 的拒收行。
    """
    out: dict[str, Any] = {"checked": False, "propositions": [], "problems": [],
                           "registrations": 0, "proof_versions": 0,
                           "checked_from": f"{_MF.MANUSCRIPT_DIR}/*proof-*.md",
                           "reason": ""}
    root = str(getattr(store, "root", "") or "")
    if not root:
        out["reason"] = "这一层没有工作区根 ⇒ 手稿登记读不到（没查成）"
        return out
    try:
        on_disk = entries_on_disk(root)
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        out["reason"] = f"手稿目录读不出来（{type(exc).__name__}: {exc}）⇒ 没查成"
        return out
    out["checked"] = True
    refused_by_label: dict[str, int] = {}
    try:
        from . import secretary as _SEC

        for one in _SEC.proposition_form_rows(root):
            # 这本台账 2026-11-07 起是 F 与 E 共用的（同一道形态闸同步到了 E 的数值
            # 证明路线）。这一格数的是"F 的手稿登记被拒了几次" ⇒ 只认 F 自己的行
            # （历史上 role 缺省为空的那几条也归 F）；E 的拒收进
            # `closing.proposition_form_reading` 的 `by_role["E"]`，不在这里冒充 F。
            if str(one.get("role") or "") not in ("", "F"):
                continue
            if one.get("checked") and not one.get("well_formed"):
                key = str(one.get("label") or "")
                refused_by_label[key] = refused_by_label.get(key, 0) + 1
    except Exception as exc:  # noqa: BLE001 —— 台账读不到只少一格，不改"查过了"的那一半
        out["problems"].append(f"形态闸台账读不出来：{type(exc).__name__}: {exc}")
    for one in on_disk:
        versions = [dict(v) for v in (one.get("versions") or [])]
        if not versions:
            versions = [{"proof_no": int(one.get("proof_no") or 0),
                         "at": "", "sha256": str(one.get("sha256") or "")}]
        label = str(one.get("label") or "")
        out["propositions"].append({
            "family": str(one.get("family") or ""),
            "label": label,
            "statement_id": str(one.get("statement_id") or ""),
            "manuscript_path": str(one.get("path") or ""),
            "registrations": 1,
            "proof_count": len(versions),
            "versions": [{"proof_no": int(v.get("proof_no") or 0),
                          "sha256": str(v.get("sha256") or ""),
                          "at": str(v.get("at") or "")} for v in versions],
            "problems": int(refused_by_label.get(label, 0)),
        })
    out["registrations"] = sum(int(p["registrations"]) for p in out["propositions"])
    out["proof_versions"] = sum(int(p["proof_count"]) for p in out["propositions"])
    if not out["propositions"]:
        out["reason"] = ("查过了：`reports/` 下没有一份带登记条目的证明手稿 ⇒ "
                         "这个读数不是「命题登记一次、证明改 N 次」的那种形态")
    else:
        out["reason"] = (f"查过了：{len(out['propositions'])} 条手稿登记、"
                         f"{out['proof_versions']} 个证明版本 —— "
                         + "；".join(f"{p['label'] or p['manuscript_path']}：登记 "
                                    f"{p['registrations']} 次 / 证明 {p['proof_count']} 版 / "
                                    f"有毛病 {p['problems']} 次"
                                    for p in out["propositions"][:6])
                         + "（读数，不拦门）")
    return out


# ---------------------------------------------------------------- 手稿头的那句话（给提示词用）

def registration_note() -> str:
    """提示词里那一句（业主 2026-11-07 逐字口径的正面表述）。"""
    return ("你登记一条**新命题**时，你的秘书会先看它是否写清了「从什么条件导出什么结论」；"
            "已经在登记里的命题**重写证明**时不再过这一步 —— 改证明不需要重新登记。")



