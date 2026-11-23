# -*- coding: utf-8 -*-
"""产物登记：谁在哪个路径产出了什么。

## 这一层补的是什么

`tasks.artifacts` 记的是"这次召唤产出了哪些引用"（`table:id` 或 `file:<相对路径>`），
`documents.markdown_path` 记的是"G 渲染的那一份稿件"。两者都只回答单个对象自己的
产出面。没有任何地方回答"这个路径归谁"：同一个路径可能是两个角色的产物，而
"我要写的这个路径是不是另一个角色的产物"在事前无法判断；也没有"构建产物"这个
对象类型，产出的读数没有可核的来源。

本模块不去改 `schema.py`（那是 FC-27 禁改区，且"新表"要人裁），而是把这件事做成
工作区级文件台账（与 `signatures` 的 `DOC-SIGNATURES.jsonl`、`sessions` 的
`sessions/*.jsonl` 同一形态）：`<工作区根>/ARTIFACTS.jsonl`，一行一条。

## 一条记录里有什么

```text
at         产出时刻（ISO，本地时区）
path       工作区相对路径（posix 分隔符；绝对路径与越界路径一律拒收）
sha256     产出时磁盘内容的 sha256（字节级，不做归一化）
bytes      字节数
producer   生产者（角色名 / 工具名 / "M"）
kind       产物类别（受控词表 `ARTIFACT_KINDS`；词表外的新写照落但记 `kind_unknown=true`）
task_id    这次产出属于哪一次召唤（可空）
exit_code  产生它的那次执行的退出码（可空；"没跑过"就不许填 0）
note       人读的补充（可空）
```

## 三态（不许折平）

- 文件找不到 ⇒ `record` 拒收（fail-closed）。理由：一条"钉不住内容"的登记
  不是弱证据，是假证据 —— 它让"这个路径有归属"这件事看起来成立。
- 路径越出工作区 ⇒ 拒收。理由与 `agent_e._resolve` 的 `script_path` 闸相同：
  越界写/读不留痕是框架层的红线。
- 台账里的 sha256 与盘上不一致 ⇒ `verify_entries` 报 `changed`（不是 ok）；
  读不出来报 `unreadable`（不是 missing）；不在了报 `missing`。
  三种状态各有各的处置，合成一个"有问题"就没人知道该干什么。

## 它不是判据的执行者

本模块只登记与核对；"这个产物该不该存在""这份读数可不可信"由各自的判据回答。
`unowned()` 是唯一的判断：给一组路径，答"哪些没有归属登记"。
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from . import manuscriptfamily as MF
from . import sysguard as SG
from .jsonlfile import read_jsonl

#: 台账文件名（工作区根下）。与 `signatures.LEDGER_NAME` 同一层次。
LEDGER_NAME = "ARTIFACTS.jsonl"

#: 一条记录的字段全集（写侧逐字用；读侧容忍缺字段但会在 `verify_entries` 里如实报）。
#:
#: `instance` / `identity_conflict`（K1/K2）：`producer` 之外再记一格「实例标签」与
#: 「未归因的原因」。老行没有这两格照旧读（读侧容忍缺字段）；新行有它，于是
#: 「两个人同一角色各产了一件」在台账上按 `instance` 分得开，而不是只剩 `producer=角色`。
FIELDS: tuple[str, ...] = (
    "at", "path", "sha256", "bytes", "producer", "kind", "kind_unknown", "task_id",
    "exit_code", "note", "instance", "identity_conflict", "family",
)

#: `ARTIFACTS.jsonl` 的 `kind` 受控词表（2026-11-22 B2d）。
#:
#: ## 它凭什么长这样
#:
#: 基线不是拍脑袋：`projects/*` 的 34 个真机工作区、5,249 行台账的真实并集是 17 个取值
#: （`paper` 2,985 / `task-result` 832 / `e-num-manuscript` 444 / `f-proof-manuscript` 262 /
#: `experiment-log` 222 / `note` 218 / `script` 105 / `b-proof-manuscript` 58 /
#: `research-report` 50 / `document-note` 20 / `status-report` 13 / `status-report-readout` 13 /
#: `review-report` 10 / `report` 7 / `analysis-report-gaps` 6 / `analysis-report-hottest` 3 /
#: `analysis-report-cold` 1）。词表在此之上补进"代码里已经声明、历史只是还没跑到"的取值
#: （`paper-pdf` / `experiment-report` / `e-proof-manuscript` / 泛化的 `manuscript` /
#: 其余 `analysis-report-*` 与 `document-*`）—— 还没落过不等于自造。
#:
#: ## 分档只为人读，不是第二套判据
#:
#: 判据只有"在不在 `ARTIFACT_KINDS` 里"一条。分组回答"这个取值属于哪一类产物"，
#: 供文档与读数分栏；它不参与任何校验（把分组也写成判据，等于同一件事两处实现）。
#:
#: ## 不合并的三对（证据）
#:
#: - `report` ≠ `review-report`：`report`（7 行）的 `path` 全是 `out/SCRIPTS.md`、
#:   `producer=M`、`note` 逐字「A4/R-52：把 artifacts report 台账渲染」—— 它是台账自身的
#:   渲染表；`review-report`（10 行）是 H 的 `out/report/<doc>-review.md` 审校报告。
#: - `paper` ≠ `paper-pdf`：`paper`（2,985 行）由外部 `paper-generator` 逐文件登记
#:   （同一工作区里 `out/package/` 下每个文件各一行）；`paper-pdf` 是 `papercompile` 对
#:   编出来的那一份 PDF 的登记。一个是"包里的每个文件"，一个是"编译产物本身"。
#: - `note` ≠ `document-note`：`note` 是 `notes/<角色>.md`（`agent_loop.write_note` 的草稿本）；
#:   `document-note` 是 `documents` 表 `kind=note` 那一行指向的 markdown 成稿
#:   （`doc_tools` 渲染后登记）。前者是过程笔记，后者是交付物。
ARTIFACT_KIND_GROUPS: dict[str, tuple[str, ...]] = {
    #: 框架自己落的系统产物（任务结果 / 状态报告 / 台账渲染）。
    "system": ("task-result", "status-report", "status-report-readout", "report"),
    #: 手稿（`manuscriptfamily.FAMILY_ORDER` 四族 + 无族时的泛称）。
    #:
    #: 族那一半从 `manuscriptfamily` 现派生（`<族前缀>manuscript`）：族 / 前缀的
    #: 唯一真身是那张表（`prefix_of`），这里不写第二份 —— 否则表里改一个前缀、
    #: 台账的 `kind` 仍收旧名，而两处都不会报错。
    "manuscript": ("manuscript",) + tuple(
        f"{MF.prefix_of(family)}manuscript" for family in MF.FAMILY_ORDER),
    #: 报告与成稿文档（C 的分析报告按 `schema.REPORT_KINDS` 派生；
    #: documents 的 markdown 按 `schema.DOC_KINDS` 派生）。
    "report": ("research-report", "review-report", "experiment-report",
               "analysis-report-hottest", "analysis-report-paths", "analysis-report-cold",
               "analysis-report-gaps", "analysis-report-proof_chain",
               "document-survey", "document-paper", "document-note"),
    #: 运行日志。
    "log": ("experiment-log",),
    #: 其它：过程笔记 / 外部论文包里的文件 / 代码脚本 / 缺省值。
    "other": ("note", "paper", "paper-pdf", "script", "file"),
}

#: 全部受控取值（由分组派生；加值只改上面那一张表）。
ARTIFACT_KINDS: tuple[str, ...] = tuple(
    kind for kinds in ARTIFACT_KIND_GROUPS.values() for kind in kinds)

#: `kind` 的三态（读侧）。三态不许折平：
#:
#: - `canonical`：取值在词表里；
#: - `legacy`：取值不在词表里，且这一行没有 `kind_unknown` 这一格 —— 词表生效前
#:   落的历史行。读侧照读，不许判成畸形；
#: - `unknown`：取值不在词表里，且这一行有 `kind_unknown` 这一格 —— 词表生效后的
#:   新写。它照旧落盘（产物不许因为"类别没登记"就消失），但行上带着受控标记、读数里点名。
KIND_STATES: tuple[str, ...] = ("canonical", "legacy", "unknown")

#: `verify_entries` 的四种状态。刻意不是布尔：`missing`（不在了）与 `unreadable`
#: （还在但读不出来）的处置完全不同，`changed`（被改过）又是第三种。
STATUSES: tuple[str, ...] = ("ok", "changed", "missing", "unreadable", "not_a_file")

#: `changed` 那一条为什么变了（读侧的第三根轴；`status` 一个字不动）。
#:
#: 为什么必须把它分开：`changed` 是个布尔，而盘上至少有两种完全不同的情形 ——
#: ① 台账后面还有一条同路径的登记、且它钉的就是盘上现版（这条旧登记被顶替了，
#: 那是正常的追加登记，不是"被改过"）；② 登记之后落了签块（手稿在被登记之后才被
#: 收方秘书盖章，签块会改文件字节 —— MALFORM 普查里 77 条"最后一条 sha 不符"中有
#: 38 条属这一档）。两档都是"可解释"，处置是"不用管"；剩下的 `rewritten_after_
#: registration` 才是"登记之后有人改了内容"，那一档要人看。
#:
#: 三态不折平：分不出原因时给 `rewritten_after_registration`（保守侧），
#: `explained=False` —— 那是"没找到解释"，不是"确认被改"。
CHANGE_REASONS: tuple[str, ...] = (
    "superseded_by_later_registration",
    "signed_after_registration",
    "rewritten_after_registration",
)


class ArtifactError(RuntimeError):
    """登记或核对不成立（越界路径 / 文件不存在 / 不是普通文件）。"""


def ledger_path(root: Any) -> pathlib.Path:
    """`<工作区根>/ARTIFACTS.jsonl`（只算路径，不建文件）。"""
    return pathlib.Path(str(root)) / LEDGER_NAME


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rel_path(root: Any, path: Any) -> str:
    """把 `path` 归一成工作区相对路径（posix 分隔符）；越界则抛 `ArtifactError`。

    为什么要归一：台账是给人比对的（"这个路径归谁"），绝对路径会随工作区搬家
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


def _fingerprint(path: pathlib.Path) -> tuple[str, int]:
    """一次读盘同时算出 `(sha256, 字节数)`。

    为什么合成一次读：台账里的 `sha256` 与 `bytes` 必须描述同一批字节。分两次取
    （先 `sha256_of` 再 `stat`）时，中间被另一个写者换掉的文件会让两格各描述一版，
    而读侧按 `sha256` 对拍永远看不出 `bytes` 已经不对（SIGNMAL 的同族形态：
    框架自己写进台账的两格，落盘时没人保证它们说的是同一份内容）。
    """
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def sha256_of(path: pathlib.Path) -> str:
    """磁盘当前内容的 sha256（十六进制小写）。字节级，不做任何归一化。"""
    return _fingerprint(path)[0]


#: 台账里框架自己算出来的那几格的形状判据（空串 = 合格）。
#:
#: 为什么在写口再判一遍：这些格没有一个是模型填的（`at` / `sha256` / `bytes` 都由
#: 本模块现算），所以它们坏了就是框架坏了。此前 `record` 把它们原样写进去 ——
#: 一个空 sha 或负数 `bytes` 会静静地留在台账里，而读侧只在对拍时看到"changed"。
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def entry_problems(entry: Mapping[str, Any]) -> list[str]:
    """一条即将落盘的登记：框架自己写的那几格是不是都成形成实（空表 = 合格）。"""
    out: list[str] = []
    if not _SHA_RE.match(str(entry.get("sha256") or "")):
        out.append(f"sha256 读到 {entry.get('sha256')!r}，不是 64 位小写十六进制")
    size = entry.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        out.append(f"bytes 读到 {size!r}，必须是非负整数")
    rel = str(entry.get("path") or "")
    if not rel:
        out.append("path 是空的")
    elif pathlib.PurePosixPath(rel).is_absolute() or ".." in pathlib.PurePosixPath(rel).parts:
        out.append(f"path 读到 {rel!r}，不是工作区相对路径")
    at = str(entry.get("at") or "")
    try:
        datetime.fromisoformat(at)
    except ValueError:
        out.append(f"at 读到 {at!r}，不是可解析的 ISO 时刻")
    return out


#: 逐条登记的已知外部生产者（写入期口径）。
#:
#: ## 它不是"允许名单"
#:
#: 未登记的名字照写台账 —— 外部脚本的产出不许因为"框架没登记这个名字"就消失：
#: 台账少一行 = 下游读不到那份产物，那是不可逆的信息损失（比"多一根分面轴"贵得多）。
#: 这张表的作用是让常见的外部生产者有名字、有理由（人读得懂"这是谁"），
#: 而"出现了一个没登记的生产者"这件事由 `summarize()["unregistered"]` 如实报出来。
#: 一句话：写入期可见，不是写入期否决。
REGISTERED_EXTERNAL_PRODUCERS: dict[str, str] = {
    "paper-generator": (
        "外部论文打包脚本（不是框架角色）：真机 Incubator 根 2985 行 `ARTIFACTS.jsonl` "
        "的 `producer` 全是它 ⇒ 登记成「已知的外部生产者」，人读得出这是谁"
    ),
}

#: `producer` 的形态上限：超过它的一律当坏输入（不是"未登记的外部名"）。
PRODUCER_MAX_CHARS = 120


def producer_problem(producer: str) -> str:
    """畸形输入的判据（空串 = 合格）。

    这一层只拦"坏输入"：空 / 纯空白 / 含换行 / 超长（`PRODUCER_MAX_CHARS`）。
    "未登记"不是畸形 —— 未登记的外部生产者照写台账（见
    `REGISTERED_EXTERNAL_PRODUCERS` 的 docstring：外部产出不许因为框架没登记就消失），
    它的可见性由 `summarize()["unregistered"]` 与 `producer_is_known()` 提供。
    """
    name = str(producer or "").strip()
    if not name:
        return "producer 不能为空：不知道是谁产的，这条登记没有归属可言"
    if "\n" in str(producer) or "\r" in str(producer):
        return "producer 里不能有换行：台账一行一条，换行会把一行拆成两条"
    if len(name) > PRODUCER_MAX_CHARS:
        return (f"producer 太长了（{len(name)} 字符 > {PRODUCER_MAX_CHARS}）—— "
                "它应当是一个名字，不是一段说明；说明写进 `note`")
    return ""


def producer_is_known(producer: str) -> bool:
    """这个名字是不是已知的生产者（角色 / 实例级 actor / 主控 / `tool:<名>` / 外部生产者）。

    「实例级 actor」（`agent-<角色>` / `agent-<角色>-<实例>`）算已知：它是
    `identity.actor_for` 的形态（K1/K2），不是没登记的外部名字。判据与
    `identity.split_actor` 同一张角色表（`schema.ROLES`），不另写一份角色名单。
    """
    from . import schema as S

    name = str(producer or "").strip()
    if not name:
        return True                     # 空名由 `producer_problem` 拒，这里不重复判
    if name in set(S.ROLES) or name == S.CONDUCTOR_ROLE:
        return True
    if name in REGISTERED_EXTERNAL_PRODUCERS:
        return True
    if name.startswith("agent-"):
        # `agent-F`（角色级）或 `agent-F-<实例>`：拆出来看角色那一段在不在表里。
        rest = name[len("agent-"):]
        role = rest.split("-", 1)[0]
        if role in set(S.ROLES) or role == S.CONDUCTOR_ROLE:
            return True
    return name.startswith(("tool:", "agentflow."))


def kind_is_known(kind: Any) -> bool:
    """这个取值在 `ARTIFACT_KINDS` 里吗（写侧唯一判据；词表外不拒收）。"""
    return str(kind or "") in ARTIFACT_KINDS


def kind_state(entry: Mapping[str, Any]) -> str:
    """读侧三态：`canonical` / `legacy` / `unknown`（定义见 :data:`KIND_STATES`）。

    判据只有两条：取值在不在词表里、这一行有没有 `kind_unknown` 这一格。
    `kind_unknown` 的值不参与判态（标记与取值不一致时由
    `summarize()["kind_flag_mismatch"]` 点名，不在这里悄悄改读法）。
    """
    kind = str(entry.get("kind") or "")
    if kind_is_known(kind):
        return "canonical"
    return "unknown" if "kind_unknown" in entry else "legacy"


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
    instance: str = "",
    identity_conflict: str = "",
    family: str = "",
) -> dict:
    """登记一条产物；返回写进去的那条记录。

    先核文件再写台账：文件不存在 / 不是普通文件 ⇒ `ArtifactError`，一个字节都不写。
    （"先记账、后产出"的顺序会让台账成为一份愿望清单 —— 而它唯一的用途是核对。）

    `producer` 走写入期口径 `producer_problem`：只拦畸形输入（空 / 换行 / 超长）。
    未登记的合法名字照写台账 —— 外部生产者（如 `paper-generator`）的产出不许因为
    "框架没登记这个名字"就消失；它的可见性由
    `producer_is_known()` / `summarize()["unregistered"]` 提供
    （"写入期可见，不是写入期否决"）。
    """
    problem = producer_problem(producer)
    if problem:
        raise ArtifactError(problem)
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
        "sha256": "",
        "bytes": 0,
        "producer": str(producer),
        "kind": str(kind or "file"),
        #: 受控标记（B2d）：词表外的类别照旧落盘（外部产出不许因为"类别没登记"就
        #: 从台账里消失），但行上必须留下这个受控标记，且 `summarize()` 进读数。
        #: 它与 `producer` 的"未登记是可见、不是否决"同一条纪律；区别只在
        #: `kind` 是数据契约里的一格，而 producer 是自由的外部名字。
        "kind_unknown": not kind_is_known(kind or "file"),
        "task_id": str(task_id or ""),
        # 本模块其余坏输入走 `ArtifactError`；这一格也只经 `_exit_code_of` 收成 int，
        # 不静默吞坏值。
        "exit_code": exit_code if exit_code is None else _exit_code_of(exit_code),
        "note": str(note or ""),
        # 实例身份（K1/K2）：`producer` 已经是实例级 actor 时，这一格是拆出来的标签；
        # `identity_conflict` 非空 = 这一笔没归因成功（写的人要在读数里看见它）。
        "instance": str(instance or ""),
        "identity_conflict": str(identity_conflict or ""),
        #: K6④（2026-11-18）：稿的族（`f-proof` / `b-proof` / `e-proof` / `e-num`）。
        #: 台账按族筛产物时不必再从路径现拼；非稿产物的这一格是空串。
        "family": str(family or ""),
    }
    # 写点即算：sha 与 bytes 从同一次读盘得出（见 `_fingerprint` 的 docstring）。
    entry["sha256"], entry["bytes"] = _fingerprint(full)
    problems = entry_problems(entry)
    if problems:
        SG.record_reading(root, SG.refused(
            "artifacts.record", code="artifact_entry_bad",
            where=f"{LEDGER_NAME}#{rel}",
            detail="；".join(problems),
            how_to_fix=("这一条登记的三个派生格（sha256 / bytes / at）都由本模块现算，"
                        "坏了说明算它们的那一处坏了：先修算的那一处，不要绕过它手写台账")))
        raise ArtifactError("这一条登记自己不成形 ⇒ 一个字节都没写："
                            + "；".join(problems))
    p = ledger_path(root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    except OSError as e:
        raise ArtifactError(f"台账写不进去（{type(e).__name__}: {e}）") from e
    return entry


def record_or_problem(root: Any, **kwargs: Any) -> tuple[dict, str]:
    """登记一条产物；返回 `(记录, 问题)` —— 问题非空 = 没登记成（不抛异常）。

    为什么留一个不抛的口子：这些调用点都是"产物已经落盘之后"补记归属，而它们
    各自已经有一份读数形状（`problems` / `refused` / 返回里的 `why`）。登记失败
    若直接抛，会被读成"产物没写成"（那不是事实）；返回空字典又不留话，等于把
    "盘上有产物、台账里没有"这件事吞掉 —— 这正是这条纪律要禁止的形态。
    所以把失败收成一句话交回调用方：调用方必须把它带进自己的读数
    （`problems` 里出现，或让这次落盘失败），不许不理。

    它不改变 :func:`record` 的判据：路径越界 / 文件不存在 / 台账写不进去照样是
    失败，只是失败在这里被收成读数而不是异常。
    """
    try:
        return record(root, **kwargs), ""
    except Exception as exc:  # noqa: BLE001 —— 登记失败是读数，由调用方点名
        return {}, f"产物归属没登记成（{type(exc).__name__}: {exc}）"


def read_ledger(root: Any) -> tuple[list[dict], list[str]]:
    """读台账；返回 `(记录, 坏行说明)`。

    JSONL 的读法只有一份实现：:func:`jsonlfile.read_jsonl`。坏行的定义只能有一个
    落点：各自写一份同形的循环，改一处另两处不会跟着变。
    """
    return read_jsonl(ledger_path(root))


def _parse_at(value: Any) -> datetime | None:
    """登记行的 `at` 解析成可比较的时刻；解析不出 ⇒ `None`（不猜）。"""
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def _sign_block_at(path: pathlib.Path) -> dict[str, Any] | None:
    """这一份稿是签载体时，签块的 `{signed, at}`；不是 / 读不出 ⇒ `None`。

    判据只借 :func:`agentflow.vsigns.manuscript_sign_reading`（签块的唯一读法），
    这里不再写第二份格式解析：签块的正文格式一改，两处解析必然分家。
    """
    if path.suffix != ".md" or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        from . import vsigns as VS

        reading = VS.manuscript_sign_reading(text, manuscript_path=path.name)
    except Exception:  # noqa: BLE001 —— 读法本身炸了 ⇒ 这一档没解释，不是"确认被改"
        return None
    if not reading.get("found"):
        return None
    return {"signed": bool(reading.get("signed")), "at": _parse_at(reading.get("at"))}


def changed_reason(root: Any, entry: Mapping[str, Any], *, digest: str = "",
                   later: Sequence[Mapping[str, Any]] = ()) -> tuple[str, bool]:
    """一条 `changed` 登记的读侧分类：返回 `(理由码, 是否可解释)`。

    `digest` 是盘上现版的 sha（调用方已经算过，这里不重读）；`later` 是台账里排在它
    后面的那些登记（同一路径的追加登记就是"这条被顶替"的证据）。三个理由码见
    :data:`CHANGE_REASONS`；`explained=True` 的两档处置是"不用管"，第三档才是
    "登记之后有人改了内容"。
    """
    rel = str(entry.get("path") or "")
    for row in later:
        if str(row.get("path") or "") != rel:
            continue
        if digest and str(row.get("sha256") or "") == digest:
            return "superseded_by_later_registration", True
    at = _parse_at(entry.get("at"))
    if at is not None and rel:
        block = _sign_block_at(pathlib.Path(str(root)).resolve() / rel)
        if block and block.get("signed") and block.get("at") is not None \
                and block["at"] > at:
            return "signed_after_registration", True
    return "rewritten_after_registration", False


def verify_entries(root: Any, records: Sequence[Mapping[str, Any]] | None = None) -> list[dict]:
    """逐条核对：台账钉的 sha256 与盘上现在这一版是不是同一版。

    返回每条的 `{path, status, sha256, sha256_now, producer, at, note, reason, explained}`；
    `status` 取 :data:`STATUSES` 之一（没有布尔：`missing` 与 `unreadable` 与
    `changed` 是三种不同的处置）。`reason` / `explained` 只对 `changed` 那一档有内容
    （见 :data:`CHANGE_REASONS`）：它是"为什么变了"的读侧分类，不改变 `status`。
    """
    if records is None:
        records, _bad = read_ledger(root)
    rows = [dict(r) for r in records]
    root_p = pathlib.Path(str(root)).resolve()
    out: list[dict] = []
    for i, r in enumerate(rows):
        rel = str(r.get("path") or "")
        full = root_p / rel
        row = {"path": rel, "sha256": str(r.get("sha256") or ""),
               "producer": str(r.get("producer") or ""), "at": str(r.get("at") or ""),
               "sha256_now": "", "status": "missing", "reason": "", "explained": False}
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
        if row["status"] == "changed":
            reason, explained = changed_reason(root_p, r, digest=row["sha256_now"],
                                               later=rows[i + 1:])
            row["reason"], row["explained"] = reason, explained
        out.append(row)
    return out


def owners_of(root: Any, path: Any) -> list[dict]:
    """这个路径在台账里的全部归属记录（按时间序）。空列表 = 没有归属登记。

    为什么返回全部而不是最后一条：同一个路径被两个生产者登记过（同义不同物的两份
    台账）本身就是一条发现，只给最后一条会把它抹掉。
    """
    rel = rel_path(root, path)
    records, _bad = read_ledger(root)
    return [dict(r) for r in records if str(r.get("path") or "") == rel]


def unowned(root: Any, paths: Iterable[Any]) -> list[str]:
    """给定的路径里，没有归属登记的（工作区相对路径，排序）。

    这是本模块唯一的判断：它把"不在可审计对象图里"从一句人肉比对变成可查的读数。
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
    """台账汇总：条数 / 生产者计数 / 未登记的生产者 / 类别计数 / 三类 kind 状态 / 坏行数 / 四态计数。

    `unregistered` 是读数（不是闸门）：台账里出现过、但既不是角色/主控、
    也不是 `tool:<名>`/`agentflow.<模块>`、也不在 `REGISTERED_EXTERNAL_PRODUCERS` 里的
    生产者名 —— 各几条。它让"出现了一个没人登记的生产者"当场看得见；否则那种名字
    只会让 `by_producer` 悄悄多一根分面轴。

    `kind_states` / `unknown_kinds` / `kind_flag_mismatch` 是同一形态的读数：
    词表外的类别照旧写（不许丢行），但"这一类没登记"必须在汇总里看得见，
    并分得清是历史行（`legacy`，读侧照读）还是新写（`unknown`，行上带受控标记）。
    """
    records, bad = read_ledger(root)
    by_producer: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    kind_states: dict[str, int] = {state: 0 for state in KIND_STATES}
    unknown_kinds: dict[str, int] = {}
    kind_flag_mismatch = 0
    for r in records:
        by_producer[str(r.get("producer") or "")] = by_producer.get(str(r.get("producer") or ""), 0) + 1
        by_kind[str(r.get("kind") or "")] = by_kind.get(str(r.get("kind") or ""), 0) + 1
        state = kind_state(r)
        kind_states[state] = kind_states.get(state, 0) + 1
        if state != "canonical":
            odd = str(r.get("kind") or "")
            unknown_kinds[odd] = unknown_kinds.get(odd, 0) + 1
        #: 标记与取值不一致（写了 `kind_unknown=false` 却又不在词表里）：读法不变，
        #: 但要有人看见写侧那一笔标记算错了。
        if state == "unknown" and r.get("kind_unknown") is not True:
            kind_flag_mismatch += 1
    status: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for v in verify_entries(root, records):
        status[v["status"]] = status.get(v["status"], 0) + 1
        if v["status"] == "changed":
            key = str(v.get("reason") or "")
            reasons[key] = reasons.get(key, 0) + 1
    unregistered = {name: n for name, n in by_producer.items() if not producer_is_known(name)}
    return {"entries": len(records), "bad_lines": len(bad), "by_producer": by_producer,
            "unregistered": unregistered,
            "by_kind": by_kind, "kind_states": kind_states,
            "unknown_kinds": unknown_kinds, "kind_flag_mismatch": kind_flag_mismatch,
            "status": status, "changed_reasons": reasons,
            "problems": list(bad)}


def render_markdown(root: Any, entries: Sequence[Mapping[str, Any]] | None = None) -> str:
    """把台账渲染成一份可进包的表。

    逐条给：路径 / 生产者 / 类别 / 召唤号 / 退出码 / 字节 / sha256（前 16 位）/
    现在的状态。状态列不许省：一份只列 sha256 的表会让读者以为"列出来就是对的"。
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
                  "`ok` / `changed` / `missing` / `unreadable` / `not_a_file`）。"]
    odd = [(kind_state(e), str(e.get("kind") or "")) for e in entries
           if kind_state(e) != "canonical"]
    if odd:
        lines.append("")
        lines.append("**词表外的类别**（`ARTIFACT_KINDS` 之外）："
                     + "；".join(f"{state}: `{kind}`" for state, kind in odd[:20])
                     + ("（另有更多，见 `summarize()['unknown_kinds']`）" if len(odd) > 20 else ""))
    lines.append("")
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
    f.write_text("内容一", encoding="utf-8", newline="\n")
    e = record(base, path="out/r.md", producer="G", kind="report", task_id="t-0001")
    check("登记成功且哈希是盘上的", e["sha256"] == sha256_of(f), e["sha256"][:16])
    check("核对为 ok", [v["status"] for v in verify_entries(base)] == ["ok"])
    check("归属查询给出生产者", [o["producer"] for o in owners_of(base, "out/r.md")] == ["G"])

    f.write_text("内容二", encoding="utf-8", newline="\n")
    check("篡改后报 changed（不是 ok）", [v["status"] for v in verify_entries(base)] == ["changed"])
    f.unlink()
    check("删除后报 missing（不是 changed）", [v["status"] for v in verify_entries(base)] == ["missing"])

    for bad_path, tag in ((base / "out" / "不存在.md", "文件不存在"), (pathlib.Path("..") / "越界.md", "越界")):
        try:
            record(base, path=bad_path, producer="G")
            check(f"拒收：{tag}", False, "竟然写进去了")
        except ArtifactError as exc:
            check(f"拒收：{tag}", "文件不存在" in str(exc) or "越出工作区" in str(exc), str(exc)[:60])

    with ledger_path(base).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("{这不是 JSON\n")
    recs, bad = read_ledger(base)
    check("坏行逐条报出", len(recs) == 1 and len(bad) == 1, str(bad))
    check("unowned 能认出没登记的路径",
          unowned(base, [base / "out" / "另一个.md"]) == ["out/另一个.md"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())


def _exit_code_of(value: Any) -> int:
    """`exit_code` 收成 int；坏值抛 `ArtifactError`（与模块其余入口同一口径）。"""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ArtifactError(f"exit_code 必须是整数，收到 {value!r}") from exc
