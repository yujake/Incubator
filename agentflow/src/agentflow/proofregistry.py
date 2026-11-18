# -*- coding: utf-8 -*-
"""手稿登记（把「登记命题」与「写/改证明」解耦）。

## 业主要的两件事（逐字）

> 「要让注册命题和写证明两件事解耦，不然无法做到只一遍又一遍修改证明」
> 「F侧反复修改一个命题的证明时要直接动那个命题所指手稿的 proof 板块」
> 「就是F侧登记新命题F秘书闸拦的那块」

⇒ 一次登记（过 F 秘书的形态闸）之后，反复改证明不再登记：只改同一份手稿的
`## 证明` 那一节（顺手按 cites 重渲 `## 依赖`），把 `正文 sha256` 重算。`proof_no` 不涨
（「一个稿号就相当于是该稿的文件名，不再细分 version 几」）。
不新落第二个文件（不出现 `f-proof-000041-v2.md` 这类名字），也不新落 statements 行。

## 登记条目住在哪（没有新表、没有新列）

业主（逐字）：「手稿文件本身（规范路径 + 文件头元信息：命题文本 / 证明号 /
正文 sha256 / cites）」「`attack_plans.history` 的既有格（`manuscript_path` 等）里带上
这份稿的身份」「不要开新表」。所以：

1. 手稿文件就是登记条目（唯一落点，`manuscriptform.name_reading` 定的规范路径）：
   `reports/f-proof-<稿号>.md`（B 侧 `reports/b-proof-<稿号>.md`；老盘上的
   `<命题号>` / 计划名只读兼容）。文件头多了四行元信息（都只在给了值时才写，旧稿
   逐字节不变）：

   ```
   - 正文sha：<sha256>      （`## 证明` 那一节的 sha256 —— 与 V 签盖的是同一把尺）
   - 命题指纹：<sha256>     （`## 命题` 那一节规范化后的 sha256，判"还是不是同一条命题"）
   - 命题类型：<kind>       （交叉核对用；权威是台账 `statements.kind`，见 `kind_crosscheck`）
   - 登记时间：<ISO8601>    （这一条第一次落成手稿的时刻；重写不改它）
   - 版本：<ISO8601>@<sha256>   （同一个证明号只有一格：改正文就替换它，不涨版本；
     老盘 `-pN` 的不同号各留一格，读侧写成 `p<N>@<ISO8601>@<sha256>`）
   ```

   「proof_no 确实该退役……手稿产出侧和 V 签侧甚至呈递侧可退役，
   台账不能退役」⇒ 新写的稿头不再有 `- 证明号：<N>` 那一行（一个稿号 = 一份文件 =
   一份证明，身份是稿号 + 正文 sha）。老盘稿头里已有的那一行、以及 `- 版本：` 里
   `p<N>@` 的老格式，读侧照旧认（`parse_entry` 两种格式都读）—— 读能力不删。

2. `attack_plans.history` 的既有格（F 侧）：每轮那一行照旧落 `manuscript_path` /
   `manuscript_proof_no` / `manuscript_sha256` / `manuscript_registered` / `manuscript_label`
   —— 于是"这一轮是登记还是重写"在计划台账上读得出来。B 侧没有 attack_plans，身份就在
   手稿头的 `- 版本：` 那一行里（同一份文件，不是第二张账）。

3. 没有新表、没有新列：`schema.py` 零改动（判据 `tests/test_proof_registration_is_decoupled.py`
   的 f 那一格）。

## 什么算「新命题」／「改命题表述」（"过不过闸"的唯一判据）

- 手稿登记里没有同 label 的条目 ⇒ 新命题 ⇒ 过 F 秘书形态闸（`gate` 回调，一次）；
- 有同 label 的条目、且 `## 命题` 的规范化指纹相同 ⇒ 重写证明 ⇒ 不过闸、不登记；
- 指纹不同 ⇒ 走 `statementamend`：V 对盘上这一份正文判过「有毛病」（finding）+ 新表述
  过同一道闸 ⇒ 沿用原稿号原位改写 `## 命题`（业主 2026-11-16 裁定 6）；缺一 ⇒ 受控拒
  `proposition_text_changed`（新命题走登记，或「放弃 + 换号」；不要用挂证明改命题正文）。

为什么两条都看：label 是作者给的粗键（同一子目标的第 N 轮），指纹是内容键。只看 label
会把"换了命题"读成重写（静默改命题）；只看指纹则标点级改写会变成"新命题"（多登记一次）。

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
from . import manuscriptkind as _MK  # 命题类型那一轴（标签 / 交叉核对）的唯一权威来源
from . import verifications as _VR
from .proofoutcomes import (  # 登记这一步的三段结局读数
    FAMILY_MARK, OWNER_MARK, REFUSED_CLAIM_NOT_YOURS, REFUSED_CLAIM_UNCHECKED,
    REFUSED_GATE, REFUSED_PATH, REFUSED_READ, REFUSED_SHAPE, REFUSED_TEXT_CHANGED,
    REFUSED_WRITE, amend_statement, claim_guard, form_gate_reading, head_for_new_version,
    manuscript_artifact, preserved_reading,
)
from .proofrevisions import (  # 收工读数那一半
    entries_on_disk, proof_revisions, registration_note,
)

#: 手稿头里的元信息标记（与 `manuscriptform` 的既有标记同一个风格；只增不改）。
#: 「命题类型」那一行 2026-11-14 前叫 `- 证据种类：`（借了等级那根轴的词）；
#: 字面量住在 `manuscriptkind`，旧名只在读侧认（仓的纪律「读能力不删」）。
SHA_MARK = "- 正文sha："
FINGERPRINT_MARK = "- 命题指纹："
KIND_MARK = _MK.PROPOSITION_KIND_MARK
LEGACY_KIND_MARK = _MK.LEGACY_PROPOSITION_KIND_MARK
REGISTERED_AT_MARK = "- 登记时间："
VERSION_MARK = "- 版本："

#: 受控码（写读两侧共用，不另起第二套词）：定义点在 `proofoutcomes.py`
#: （与「跑闸 / 解释拒收」和「幂等保留」两段读数同一处）。这里从它回引同样的名字，
#: 所以 `proofregistry.REFUSED_*` 这个公开面一个字没变。

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
    """`## 证明` 那一节的 sha256（与 V 签盖的是同一把尺；全仓库唯一实现）。
    入参有两种形态 —— 一份手稿（有 `## 证明` 那一节）或
    一段证明正文（登记/重写那一笔直接把正文交进来，没有小节标题）。后者按
    `depsection.proof_body_or_whole` 的显式回退取整份正文（`fell_back=True`
    在那一格内部）。

    ## 两种形态各按什么字节算（"一把尺"的定义）

    - 一份手稿：取 `## 证明` 那一节的正文，去掉小节自带的首尾空行后算 sha。
      这与 V 签盖的是同一段字节（`vsigns.manuscript_proof_body` 同一处归一）。
    - 一段正文（`fell_back=True`）：逐字节就是它，不再做首尾空行归一。
      为什么不能顺手 `.strip("\\n")`：这一段正文在 V 那一侧是按原字节算的；
      多剥一个换行就等于给"同一段正文"造出第二个 sha，跨入口对拍时会变成
      "签不上"或"签错了也能过"。
     由此一条可查的后果：带首尾换行的一段正文，其 sha 与 strip 之后的值不同；
      盘上已有的历史行按它落盘时的原样对拍，本函数不会替它重新归一。

    ## 为什么这里允许"退而取全文"
    `proof_sha` 的入参在登记/重写路径上就是一段没有 markdown 标题的证明正文
    （`register_or_rewrite` 的 `proof_text`），把它当手稿切小节只会得到空串；
    而 sha 一旦变成空串的 sha，版本记录与 V 签的对拍会同时静默失真。
    所以这一处走显式回退，并且只在这一处用 `proof_body_or_whole`。

    ## 与 `verifications.text_sha` 的分工（两把尺，故意不同名）
    `verifications.text_sha` 是"给定文本的原样 sha"（逐字节，不切小节）—— 它服务
    "V 拿到的这一段，是不是稿里那一段"；本函数是"签的对拍尺"（手稿取小节）。
    两个语义不许合并：合并之后 `given != body` 那道闸会把整份手稿也算成"同一份"。
    本函数直接算 sha（`hashlib` 已为 `section_hashes` / 命题指纹引入，不新增依赖），
    不调用 verifications 的任何一个 sha。
    """
    raw = str(proof_text or "")
    reading = _DS.proof_body_or_whole(raw)
    if bool(reading.get("fell_back")):
        body = raw
    else:
        body = str(reading.get("body") or "").strip("\n")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 分节（切 / 换 / 哈希）

def _section_start_indices(lines: Sequence[str]) -> list[int]:
    """`## ` 标题里"是手稿一节"的那些行下标（同级自由小标题不算新的一节）。

    与 `depsection.section_lines` 同一份口径：
    证明正文里 `## 记号与约定` / `## 第一步` 这类同级小标题是节内内容，只有
    `## 依赖` 一类已知节名才开启下一节。按"任何 `## `"切会把 `## 证明` 那一节
    切成空的，分节哈希里于是出现 `## 记号` 这种并不存在的"节"。
    """
    return [i for i, line in enumerate(lines)
            if _SECTION_RE.match(line) and _DS.is_section_heading(line)]


def split_sections(text: Any) -> tuple[str, list[tuple[str, str]]]:
    """把手稿切成 `(头部, [(节名, 节内容), …])`；内容不含节标题那一行。

    节边界只认手稿的节（`depsection.SECTION_TITLES`）：`## 证明` 下面的
    `## 记号与约定` 一类同级小标题留在证明正文里，不再另起一节。

    只认框架节名；作者自己的 `##` 小标题属于上一节，不单独出键。将来需要"附录"这类
    新节，先把节名加进 `SECTION_TITLES`，不要改切节算法。
    """
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    starts = _section_start_indices(lines)
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
    """只换 `## <name>` 那一节的内容，其余字节原样（判据 i 的"只动那一块"）。

    节的起止与 :func:`split_sections` 同一份口径（同级自由小标题算节内内容）：
    替换 `## 证明` 时，它下面的 `## 记号` 一类小标题跟着旧证明一起被换掉，不会留在
    原地变成半截。
    """
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    starts = _section_start_indices(lines)
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

def replace_section(text: Any, name: str, body: Any) -> tuple[str, bool]:
    """只换 `## <name>` 那一节（对外写口；唯一实现仍是 `_replace_section`）。

    为什么要一个公开名：`propositionrewrite`（W2 的"未入册命题原位重写"写口）要换的
    正好是 `## 命题` 那一节 —— 它若自己再写一份切节/替换，两处口径迟早分家（"只动
    那一块"这条判据就管不住新写口了）。所以这里只转发，不另立判据。
    """
    return _replace_section(str(text or ""), str(name), str(body or ""))


def rewrite_proposition_head(text: Any, *, new_fp: str) -> str:
    """只改稿头的命题指纹那一行（`## 命题` 原位改写之后用，其余元信息一个字不动）。

    为什么不复用 `_head_for_new_version`：那个函数一次改七格（正文 sha / 指纹 / 标签 /
    命题类型 / 登记时刻 / 版本段 / 命题号），而这一笔只改了命题正文——正文 sha、版本段、
    登记时刻都不该动（动了就等于说"证明换了一版"，而它一个字节没变）。
    """
    raw = str(text or "")
    head_now = _head_of(raw)
    head_new = _rewrite_head(head_now, {FINGERPRINT_MARK: str(new_fp or "")})
    return head_new + raw[len(head_now):]


def _head_of(text: Any) -> str:
    """手稿头部（与 :func:`split_sections` 同一份切节口径，但不构造各节正文）。

    只要头部的两处（:func:`parse_entry` / :func:`_head_for_new_version`）不必为一段头部
    把整份稿切成一节一节、再把每一节 join 回来。
    """
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    starts = _section_start_indices(lines)
    return "\n".join(lines if not starts else lines[: starts[0]])


def parse_entry(text: Any) -> dict[str, Any]:
    """读手稿头的登记元信息（纯读；读不出来给空串，不猜）。

    稿里没有命题号（业主 2026-11-13 裁定逐字：「稿里没有命题号，任何稿里都没有命题
    号」）⇒ 新写的稿不再有 `- 命题号：` 那一行。本函数仍认盘上老稿里那一行（读兼容，
    与 `- 证明号：` 同法，业主点名保留），但新写的路径不再产生它，也没有任何判断
    依赖它 —— 见 `same_slot_reading` 的第一条（`manuscript_id` 是主键）。
    """
    head = _head_of(text)
    out: dict[str, Any] = {
        "statement_id": "", "plan_id": "", "sid": "", "label": "", "proof_no": 0,
        "sha256": "", "fingerprint": "", "kind": "", "kind_label": "",
        "registered_at": "", "versions": [], "checked": False, "problems": [],
        #: K6④：稿的族与产出者实例（老稿没有这两行 ⇒ 空串 = 未记，不猜）。
        "family": "", "producer": "",
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
            out["kind_label"] = "命题类型"
        elif raw.startswith(LEGACY_KIND_MARK):
            # 老盘旧名照认；两个名字同时出现时新名优先（旧行先读到也不许盖掉新名）。
            if str(out.get("kind_label") or "") != "命题类型":
                out["kind"] = raw[len(LEGACY_KIND_MARK):].strip()
                out["kind_label"] = "证据种类（老盘旧名）"
        elif raw.startswith(REGISTERED_AT_MARK):
            out["registered_at"] = raw[len(REGISTERED_AT_MARK):].strip()
        elif raw.startswith(FAMILY_MARK):
            out["family"] = raw[len(FAMILY_MARK):].strip()
        elif raw.startswith(OWNER_MARK):
            out["producer"] = raw[len(OWNER_MARK):].strip()
        elif raw.startswith(VERSION_MARK):
            payload = raw[len(VERSION_MARK):].strip()
            for item in payload.split(_VERSION_SEP):
                item = item.strip()
                if not item:
                    continue
                parts = item.split("@", 2)
                got = {"raw": item, "proof_no": 0, "at": "", "sha256": ""}
                # 两种格式（读侧都认；写侧只写后一种）：
                #   · 老盘 `p<N>@<时刻>@<sha>`（`proof_no` 在第 0 段）
                #   · 新写 `<时刻>@<sha>`（canonical 不写 `p1` —— 一稿一份之后它不携带身份）
                if len(parts) == 3:
                    try:
                        got["proof_no"] = int(parts[0].lstrip("pP") or 0)
                    except ValueError:
                        got["proof_no"] = 0
                    got["at"] = parts[1].strip()
                    got["sha256"] = parts[2].strip().lower()
                elif len(parts) == 2:
                    got["at"] = parts[0].strip()
                    got["sha256"] = parts[1].strip().lower()
                out["versions"].append(got)
    out["checked"] = bool(out["versions"] or out["sha256"] or out["fingerprint"])
    return out


def render_version(proof_no: Any, at: Any, sha: Any) -> str:
    """一版 ⇒ `- 版本：` 那一行里的一段（canonical 不写 `pN`）。

    「一个稿号就相当于是该稿的文件名，不再细分 version 几」⇒ 新写
    canonical（`N=1`）渲染成 `<时刻>@<sha>`，`proof_no` 不在写侧产生。显式 `N>=2`
    是老盘 `-pN` 的写侧兼容（旧读侧按号分组），照旧写 `p<N>@…` —— 新写路径不再
    产生这个 N，但盘上已有的那几份不能被一次重写改了身份。读侧两种格式都认
    （`parse_entry` 的 `- 版本：` 那一支）。
    """
    try:
        no = int(proof_no or 0)
    except (TypeError, ValueError):
        no = 0
    if no >= 2:
        return f"p{no}@{str(at or '')}@{str(sha or '')}"
    return f"{str(at or '')}@{str(sha or '')}"


def _rewrite_head(head: str, values: Mapping[str, str]) -> str:
    """就地改写头部的那几行（缺的插在头部最后一行之前）。

    `- 版本：` 与其他标记同样替换：`values[VERSION_MARK]` 已经是这一笔之后的完整清单
    （同一个证明号只留一格，见 `_versions_block`）。

    `- 证明号：` 不在 `values` 里 —— 新写的稿不再有这一行。
    老盘稿头若已经有它，本函数走"没命中 values ⇒ 原样保留"那条路：不改、不删，
    读侧（`parse_entry` / `depsection.manuscript_proof_no`）照旧读得出那个号。
    """
    lines = head.split("\n")
    order = [FAMILY_MARK, OWNER_MARK, SHA_MARK, FINGERPRINT_MARK, KIND_MARK,
             REGISTERED_AT_MARK, _MF.LABEL_MARK]
    touched: set[str] = set()
    out: list[str] = []
    for line in lines:
        raw = line.strip()
        hit = next((mark for mark in [*order, VERSION_MARK]
                    if raw.startswith(mark)), "")
        if not hit and raw.startswith(LEGACY_KIND_MARK):
            # 旧名与「命题类型」是同一格：重写时换成新名，不留第二行。
            hit = KIND_MARK
        if hit and hit in values and str(values[hit]) != "":
            if hit in touched:   # 同一格出现第二次（手写稿／旧格式）⇒ 只留一份
                continue
            touched.add(hit)
            out.append(f"{hit}{values[hit]}")
            continue
        out.append(line)
    missing = [mark for mark in [*order, VERSION_MARK]
               if mark in values and str(values[mark]) != "" and mark not in touched]
    if missing:
        # 头部最后一行之前（贴近稿头，不污染分节）：新稿没有 `- 证明号：` 可当锚点，与老稿同一规则。
        at = len(out)
        while at > 0 and not out[at - 1].strip():
            at -= 1
        for mark in reversed(missing):
            out.insert(at, f"{mark}{values[mark]}")
    return "\n".join(out)


def _versions_block(entry: Mapping[str, Any], *, proof_no: int, at: str,
                    sha: str) -> tuple[str, list[dict[str, Any]]]:
    """把这一版记进 `- 版本：` 那一行（同一个证明号就是同一份稿 ⇒ 就地替换那一格，不追加）。

    「同稿号多个版本是错误的，一个稿号就相当于是该稿的文件名，
    不再细分 version 几，应该在改正文时 edit 它」⇒ 新写路径的稿号只有一个证明号，
    重写就是就地改这一版：版本行只留当前那一格（恰好 1 条），不涨"版本"。

    老盘 `-pN`（N≥2）那几份各有自己的号：不同号仍各留一格（它们是各自独立的老文件，
    不是同一份的第 N 版）；同号重写只替换同号那一格，号与文件名一起保持身份。

    同一版重复写（号与 sha 都相同）⇒ 返回空串，调用方据此不动那一行（幂等）。
    """
    versions = [dict(v) for v in (entry.get("versions") or [])]
    if not versions and int(entry.get("proof_no") or 0) >= 1 and entry.get("sha256"):
        versions.append({"proof_no": int(entry["proof_no"]),
                         "at": str(entry.get("registered_at") or ""),
                         "sha256": str(entry.get("sha256") or "")})
    want = int(proof_no)

    def _vno(one: Mapping[str, Any]) -> int:
        """这一版是哪一号；新版 `- 版本：<时刻>@<sha>` 没有号段 ⇒ canonical（1）。

        canonical 的版本段不写 `p1@`，所以"缺省"必须读成 1 而不是 0
        —— 否则一次重写会把同一版当成"新的一版"再追加一格（版本历史重又涨起来）。
        """
        return int(one.get("proof_no") or 0) or 1

    if versions and _vno(versions[-1]) == want \
            and str(versions[-1].get("sha256") or "") == str(sha):
        return "", versions
    current = {"proof_no": want, "at": str(at), "sha256": str(sha)}
    if versions and _vno(versions[-1]) == want:
        versions[-1] = current           # 同一个证明号 ⇒ 就地改这一版，不涨"版本"
    else:
        versions.append(current)
    return _VERSION_SEP.join(render_version(v.get("proof_no"), v.get("at"), v.get("sha256"))
                            for v in versions), versions


# ---------------------------------------------------------------- 槽位识别（A1/A2）

def same_slot_reading(entry: Mapping[str, Any], *, statement_id: Any = "", plan_id: Any = "",
              sid: Any = "", label: Any = "") -> bool:
    """盘上这一条登记条目与这一笔要写的是不是「同一条命题的槽」。

    三种身份键，按优先级取第一个两边都有的：

    1. 命题号（`- 命题号：stmt:<号>`）：拿到号之后，号就是身份；
    2. `（计划号，子目标）`（`- 计划：<plan> · 子目标：<sid>`）：只读兼容老盘的
       `f-proof-plan-*` 登记条目。老盘上 F 还没有号时这是唯一稳定的槽位键 —— 计划稿
       的路径里没有子目标，光看路径会把同一计划下的不同子目标读成同一槽；F 不再新写
       计划名（只发六位稿号），新写路径不会走到这一支；
    3. `- 标签：`：只有前两样都缺时才用（旧稿 / 手写稿的兜底）。

    调用方必须先确认 `entry["checked"]`（有正文 sha / 命题指纹 / 版本记录）：
    手写稿可以给自己写一行 `- 标签：`，但它没有登记元信息，不是登记条目
    （A3 的判据 `test_a_handwritten_labelled_head_is_not_an_entry`）。

    为什么要有这一格：只看 label 时，生产路径先写的那份计划稿稿头没有 `- 标签：`
    （渲染时 `label=""`）⇒ 每一轮都读成"新命题" ⇒ 每轮重新登记（重复跑形态闸、
    证明号也不推进）。槽位从稿头元信息取，于是"传不传 `manuscript_text`"不再决定
    解耦成不成立。
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

def entry_relpath(*, family: Any, statement_id: Any = "", plan_id: Any = "",
                  manuscript_id: Any = "") -> str:
    """这一份手稿的落点（`manuscriptform.name_reading`；认不出 ⇒ 空串，不猜）。

    `manuscript_id` 是 F 自己的稿号：给了它，F 的稿只按
    `reports/f-proof-<稿号>.md` 命名；命题号 / 计划号不参与。`statement_id` / `plan_id`
    保留给 b-proof / e-proof 与老盘只读兼容。
    """
    got = _MF.name_reading(family, statement_id=statement_id, plan_id=plan_id,
                           manuscript_id=manuscript_id)
    return str(got.get("path") or "") if got.get("ok") else ""


def read_entry(root: Any, *, family: Any, statement_id: Any = "",
               plan_id: Any = "", manuscript_id: Any = "") -> dict[str, Any]:
    """读这一份手稿的登记条目（手稿 + 头部元信息）；稿不在 ⇒ `exists=False`。"""
    rel = entry_relpath(family=family, statement_id=statement_id, plan_id=plan_id,
                        manuscript_id=manuscript_id)
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

def _legacy_proof_no_of(rel: Any, entry: Mapping[str, Any]) -> int:
    """这一份稿的证明号：恒 1（一个稿号 = 一份文件 = 一份证明）。

    名字里不再有 `-pN`（解析侧也不认它），重写也不涨号；于是这一格只剩一个取值。
    函数名保留只为调用点不必改（它此前是"老盘 `-pN` 沿用 N"那一支的落点）。
    """
    return 1


# 头部改写实现住在 `proofoutcomes.head_for_new_version`（控本文件体量）。
_head_for_new_version = head_for_new_version
def register_or_rewrite(
    root: Any, *, family: Any, label: str, proposition: str, proof_text: str,
    dependency_rows: Sequence[Mapping[str, Any]] = (),
    statement_id: Any = "", plan_id: Any = "", sid: Any = "", title: Any = "",
    manuscript_id: Any = "",
    kind: Any = "", author: Any = "", at: Any = "", template: str = "",
    gate: Callable[..., Mapping[str, Any]] | None = None,
    task_id: Any = "", instance: Any = "", identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """登记一条新命题（过闸一次）／重写一条已登记命题的证明（不过闸、不登记）。

    `template` 是新命题那一档的底稿（调用方刚渲染并洗过的那一份手稿正文）：
    给了就用它当基稿（只补头部的登记元信息），于是洗稿元信息、依赖段一个字节都不丢；
    不给就按 `proposition` / `proof_text` / `dependency_rows` 现渲染。

    返回（键固定）：
    `{checked, ok, mode, statement_id, proof_no, manuscript_path, sha256, deps_rows,
      problems, refused, why, entry, section_hashes, gate, written, migrated}`。

    - `mode="registered"`：这一条第一次落成手稿（过闸；`gate` 读数的原文在 `gate`）；
    - `mode="rewritten"`：同一条命题的重写（`## 证明` 就地换；`proof_no` 恒 1，
      老盘 `-pN` 沿用 N —— 一个稿号一份文件一份证明）；
    - `ok=False` 时 `refused` 是受控码，盘上一个字节都不动（`written=False`）。
    """
    at_text = str(at or "") or _now()
    mid = str(manuscript_id or "").strip()
    rel = entry_relpath(family=family, statement_id=statement_id, plan_id=plan_id,
                        manuscript_id=mid)
    out: dict[str, Any] = {
        "checked": True, "ok": False, "mode": "", "statement_id": str(statement_id or ""),
        "manuscript_id": mid,
        "proof_no": 0, "manuscript_path": rel, "sha256": "", "deps_rows": [],
        "problems": [], "refused": "", "why": "", "entry": {}, "gate": {},
        "written": False, "section_hashes": {}, "migrated": False, "preserved": False,
        "relocated_from": "", "claim": {},
    }
    if not rel:
        out.update(refused=REFUSED_PATH,
                   why=(f"手稿落点认不出（family={family!r}、manuscript_id={mid!r}、"
                        f"statement_id={statement_id!r}、plan_id={plan_id!r}）"
                        "⇒ 不登记、不写盘"))
        return out
    # K5：落盘前核占用（改前重写支直接 `_atomic_write`，三个非属主实例重写过同一份稿）。
    _who = str(author or "").strip()
    _guard = claim_guard(root, rel, owner=author, role=family, task_id=task_id,
                         instance=instance, identity=identity)
    if not _guard.get("ok"):
        out.update(checked=(_guard.get("refused") == REFUSED_CLAIM_NOT_YOURS),
                   refused=str(_guard.get("refused") or ""),
                   why=str(_guard.get("why") or ""), claim=dict(_guard.get("claim") or {}))
        return out
    out["claim"] = dict(_guard.get("claim") or {})
    before = read_entry(root, family=family, statement_id=statement_id,
                        plan_id=plan_id, manuscript_id=mid)
    if not before.get("checked"):
        out.update(checked=False, refused=REFUSED_READ,
                   why=f"登记条目读不出来 ⇒ 没查成（不是「新命题」）：{before.get('why')}")
        return out
    old_text = str(before.get("text") or "")
    entry = dict(before.get("entry") or {})
    new_fp = proposition_fingerprint(proposition)
    # 槽位识别（A1）：规范路径优先；没有稿号时才去找同一槽的旧落点。
    same_slot = bool(before.get("exists") and entry.get("checked")
                     and (bool(mid)  # 稿号就是槽位：同一个号 = 同一份稿
                          or same_slot_reading(entry, statement_id=statement_id,
                                               plan_id=plan_id, sid=sid, label=label)))
    relocated_from = ""
    if not same_slot and not mid:
        # 有稿号时路径本身就是身份；去别处认领一份稿会是"别人的稿"。
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
        # 旧稿没有指纹行：这一笔是补登记元信息，不是改命题（权威判定在调用方）。
        _head, sections = split_sections(old_text)
        old_prop = next((body for name, body in sections if name == "命题"), "")
        entry["fingerprint"] = proposition_fingerprint(old_prop) if old_prop.strip() else ""
        migrated = True
    # ---- 同槽换了命题正文：只有「V 的 finding 触发 + 新表述过闸」才放行（裁定 6） ----
    # 业主 2026-11-16：「要根据finding改命题表述，……需要再过命题表述闸且不申请新稿号而是
    # 沿用稿号和稿并自动修改稿中命题描述为过闸的描述」。判据在 `statementamend`；放行时它
    # 带回改写好的整份稿（就是这一笔的基稿），否则照旧受控拒（受控码与文案不变）。
    if same_slot and old_fp and old_fp != new_fp:
        amend = amend_statement(root, out=out, entry=entry, rel=rel, old_text=old_text,
                                proposition=proposition, gate=gate, kind=kind,
                                label=label, proof_text=proof_text)
        if not amend.get("ok"):
            out.update(dict(amend.get("refusal") or {}))
            return out
        old_text = str(amend.get("text") or old_text)
    mode = MODE_REWRITTEN if same_slot else MODE_REGISTERED
    # 幂等：同一份正文再挂一次 ⇒ 一个字节都不动（版本号也不涨）。
    preserved = preserved_reading(
        entry, mode=mode, rewritten=(mode == MODE_REWRITTEN), new_fp=new_fp,
        proof_text=proof_text, old_text=old_text, dependency_rows=dependency_rows)
    if preserved is not None:
        out.update(preserved)
        return out
    # ---- 新命题：登记这一刻过 F 秘书的形态闸（只在这里跑；重写永不再跑） ----------
    if mode == MODE_REGISTERED and gate is not None:
        out["gate"], gate_refusal = form_gate_reading(
            gate, proposition=proposition, kind=kind, proof_text=proof_text,
            label=label, entry=entry)
        if gate_refusal is not None:
            out.update(gate_refusal)
            return out
    # ---- 渲染：新命题整份渲染；重写只换 `## 证明` 与它后面的 `## 依赖` -------------
    rows = [dict(r) for r in (dependency_rows or [])]
    deps_section = _DS.render_dependency_section(rows)
    new_sha = proof_sha(proof_text)
    # 一个稿号 = 一份文件 = 一份证明：重写不涨版本号；老盘 `-pN` 沿用文件名里的 N。
    if mode == MODE_REWRITTEN:
        proof_no = _legacy_proof_no_of(rel, entry)
    else:
        proof_no = 1
    if mode == MODE_REGISTERED:
        versions_line = render_version(1, at_text, new_sha)
        versions = [{"proof_no": 1, "at": at_text, "sha256": new_sha}]
        if str(template or "").strip():
            # 调用方刚渲染并洗过的那一份：拿它当基稿（洗稿行 / 依赖段原样保留）。
            text = str(template).replace("\r\n", "\n")
            # `## 证明` 的内容以参数为准：template 也可能是一份"骨架"（B 的改写拿
            # F 的稿当底稿时就是这样，正文必须换成 B 交来的那一份）。
            # `proof_body` 缺节 ⇒ 空串（不回退到依赖段 / 全文）⇒ 与参数正文的 sha 不同
            # ⇒ 走 `_replace_section`；基稿若没有那一节，下面会受控拒 / 整份重渲染
            # （`_replace_section` 的 `ok` 说了算）。左边那把尺 = 上面算好的 `new_sha`。
            if str(proof_text or "").strip() and new_sha != proof_sha(_DS.proof_body(text)):
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
    # 头部元信息就地更新（其余字节原样 —— 判据 i 的"只动那一块"）。
    from . import manuscriptids as _MID_HEAD

    text = _head_for_new_version(
        text, proof_no=proof_no, new_sha=new_sha, new_fp=new_fp, label=label,
        kind=kind, mode=mode, entry=entry, at_text=at_text, versions_line=versions_line,
        family=_MID_HEAD.family_of_rel(rel) or str(family or ""), author=_who)
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
    if not manuscript_artifact(out, root, rel=rel, family=family, mode=mode, author=author): return out
    out.update(ok=True, checked=True, mode=mode, proof_no=proof_no, sha256=new_sha,
               deps_rows=rows, written=True, migrated=migrated,
               #: 这一笔之后的登记条目（按盘上那一份读回来）：新写的稿没有
               #: `- 证明号：` 那一行，所以这里的 `proof_no` 读成 0；老盘重写时若稿头
               #: 本来就有那一行，照旧读出它的 N（读能力不删）。`versions` 同理 ——
               #: canonical 新写的版本段是 `<时刻>@<sha>`，读回来的 `proof_no` 是 0；
               #: 老盘 `-pN` 重写那一档仍是 `p<N>@…`。
               entry=parse_entry(text),
               section_hashes=section_hashes(text), why="")
    return out

# 收工读数（entries_on_disk / proof_revisions）与提示词那一句住在 `proofrevisions.py`
# （从本模块拆出的那一半）；这里在模块末尾回引，既有名字（`proofregistry.proof_revisions`
# 等）照旧可读。写入口仍在上面的 `register_or_rewrite`。
