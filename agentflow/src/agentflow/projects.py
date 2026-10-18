"""项目工作区：一个项目一个文件夹，冷启动/热启动按"文件夹在不在"判定。

## 用户要的东西，逐条落在这里

1. 每个项目一个文件夹，都是 `projects/` 下的子文件夹（默认落点见
   `DEFAULT_PROJECTS_DIR`：本包位置推出的工作区根下的 `projects/`，
   也可用 `--projects-dir`、`AGENTFLOW_PROJECTS_DIR` 或设置文件的
   `workspace.projects_dir` 换）。
2. 默认命名 `project1` / `project2` / …：取"已有编号的最大值 + 1"，不重用已删掉的号
   （重用一个号会让两次不同的运行共用一个路径，历史就对不上了）。
3. 每次运行可选冷启动 / 热启动，判据就是那个项目的文件夹在不在：
   - `cold`：文件夹必须不存在（存在就报错并给出下一步，绝不替你删）；
   - `warm`：文件夹必须已存在且是一个初始化过的工作区；
   - `auto`（缺省）：在就在（热），不在就不在（冷）—— 这就是用户描述的那条判据。
4. 项目文件夹里放的东西：`data/`（store 的表）、`library/`（书）、`out/run-<n>/`
   （每次运行六件产物）、`project.json`（项目卡：建了什么、跑过几次、每次冷还是热）。

## 为什么"冷/热"必须显式说出来，而不是自己猜

"这次是第一次跑"与"这次是在上次的结果上继续"是两件不同的事，产物上的读法也不同
（前者没有历史可比，后者的增量才有意义）。让脚本自己猜"文件夹在就算热"会把
"我本想新建一个项目、但名字撞了"静默地变成"我在别人的项目里又跑了一遍"。
所以：`--start` 显式选，`auto` 只是把判据（文件夹在不在）自动化，
且两种显式选择在条件不满足时都报错，不互相顶替。

## 边界

- 本模块不删任何东西：`cold` 撞上已存在的文件夹时只报错。
- 本模块不改 `agentflow/` 下的任何字节：项目全在 `projects/` 里。
- 热启动的语义是"复用同一个工作区继续跑"，不是"跳过已经跑过的步骤"：
  哪些书已经登记由 `locallib` 按内容 hash 判（那一层是幂等的），
  而模型那一步每次都会重新调（它是付费动作，要花多少由 `--budget-usd` 说话）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import conceptrows as CR
from . import settings as SET
from .locallib import (
    ingest_directory,
    local_fetch_fn,
    memo_extract_fn,
    search_fn_for_store,
)
from .store import Store

__all__ = [
    "DEFAULT_PROJECTS_DIR",
    "ProjectRef",
    "RunRecord",
    "classify",
    "create_project",
    "list_projects",
    "next_name",
    "plan",
    "resolve",
    "run_project",
    "selftest",
]

#: 默认落点。刻意放在交付物外面（`agentflow/` 之外）：
#: 项目里的数据是会变的运行产物，而 `agentflow/` 是四道门逐字节快照的受审树 ——
#: 把运行数据写进受审树，等于每跑一次就让它"漂"一次。
#:
#: 2026-10-07 改：这里此前逐字写着一台机器的绝对路径（`D:\Incubator\projects`），
#: 换一台机器就是一句假话，而症状是"项目建到了别处"而不是一句报错。现在它由
#: 由本包位置推出的工作区根算出来（`settings.WORKSPACE_ROOT`，即 `src/` 的上两级），
#: 并且允许用设置文件的 `workspace.projects_dir` 覆盖（见 `projects_dir`）。
#: 本机读数：改前改后逐字相同（都是 `D:\Incubator\projects`）—— 判据在
#: `tests/test_settings.py::test_the_projects_dir_default_is_derived_not_written`。
DEFAULT_PROJECTS_DIR = SET.WORKSPACE_ROOT / "projects"

#: 环境变量兜底（给不想每次敲 `--projects-dir` 的用法）。
ENV_PROJECTS_DIR = "AGENTFLOW_PROJECTS_DIR"

_NAME_RE = re.compile(r"^project(\d+)$")

#: 已发出去的编号水位（单调递增）。为什么需要它：只看现有目录的话，
#: 删掉 `project2`（当时最大的那个）之后下一个名字又是 `project2` ——
#: 于是两次不同的运行共用一个路径，而"这个项目的历史"从此说不清。
#: 水位文件是唯一一处"记着曾经发到几号"的地方，`create_project` 负责推进它。
SEQUENCE_FILE = ".sequence"

#: 项目卡的字段（固定集合：零值也在场，读的人不用猜"没这一项是什么意思"）。
CARD_VERSION = 1


def projects_dir(explicit: str | Path | None = None) -> Path:
    """决定 `projects/` 在哪：显式参数 > 环境变量 > 设置文件 > 推导出的默认值。

    四档的取舍与工具链那一轴同一条口径（见 `agentflow.settings` 的模块 docstring）：
    环境变量压在最上面是为了 CI 与既有脚本不被设置文件静默改掉；
    设置文件是本机的正常落点；最后一档是"由本包位置推出来的工作区根下的
    `projects/`"（改前那一档是一个写死的绝对路径）。
    """
    if explicit:
        return Path(explicit)
    env = os.environ.get(ENV_PROJECTS_DIR, "").strip()
    if env:
        return Path(env)
    from_file = SET.workspace_settings().get("projects_dir", "")
    if from_file:
        # 相对路径相对工作区根解析（`settings.resolve_setting_path` 的口径，
        # 不相对进程 cwd —— 同一个设置文件在 CLI 与判据里必须是同一个落点）。
        return SET.resolve_setting_path(from_file)
    return DEFAULT_PROJECTS_DIR


def _sequence_high(root: Path) -> int:
    """读"已发到几号"的水位（读不到就当 0：宁可从现有目录重算，也不编一个数）。"""
    try:
        return int((Path(root) / SEQUENCE_FILE).read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def next_name(root: Path | str) -> str:
    """取下一个项目名：`已用过的最大号` 与 `水位` 取大者 + 1（已删掉的号不重用）。"""
    base = Path(root)
    used: set[int] = set()
    if base.is_dir():
        for child in base.iterdir():
            m = _NAME_RE.match(child.name)
            if m and child.is_dir():
                used.add(int(m.group(1)))
    high = max([_sequence_high(base), *used]) if used else _sequence_high(base)
    return f"project{high + 1}"


@dataclass(frozen=True)
class ProjectRef:
    """一个项目的解析结果：在哪、在不在、这次算冷还是热、为什么。"""

    name: str
    path: Path
    exists: bool
    mode: str
    reason: str
    requested: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        """落进项目卡 / 打印用的形状（含"这次算冷还是热"与理由）。"""
        return {
            "name": self.name, "path": str(self.path), "exists": self.exists,
            "mode": self.mode, "reason": self.reason, "requested": self.requested,
        }


def classify(path: Path | str) -> tuple[str, str]:
    """判定一个项目文件夹当前是什么状态。

    返回 `(状态, 理由)`，状态取值：
    - `absent`：文件夹不存在（冷启动的合法前提）；
    - `empty`：文件夹存在但是空的（当冷启动用：没有任何东西可毁）；
    - `workspace`：文件夹存在，且里面有初始化过的 store（热启动的合法前提）；
    - `not_a_project`：文件夹存在、不空，但它不是本框架的工作区。

    第四档必须单独存在：把"别人的目录"当成自己的工作区初始化进去，
    会在用户不知情的情况下往里面写一堆表文件。
    """
    base = Path(path)
    if not base.exists():
        return "absent", "文件夹不存在"
    if not base.is_dir():
        return "not_a_project", "同名的是一个文件，不是文件夹"
    entries = [p for p in base.iterdir()]
    if not entries:
        return "empty", "文件夹存在但是空的"
    if (base / "data" / "counters.json").is_file() or (base / ".agentflow-workspace").is_file():
        return "workspace", "文件夹存在且是一个初始化过的工作区"
    return "not_a_project", f"文件夹存在但不空、也不是本框架的工作区（里面有 {len(entries)} 项）"


def resolve(root: Path | str, name: str | None = None, *,
            start: str = "auto") -> ProjectRef:
    """解析这次要跑的项目。`start` 取 `auto` / `cold` / `warm`。

    三种选择的行为差异就是本功能的判据本身，所以每一条都在这里显式判、显式报错：
    显式 `cold` 撞上存在的文件夹 ⇒ 抛 `ProjectExists`；显式 `warm` 撞上不存在
    ⇒ 抛 `ProjectMissing`；`auto` 一律照文件夹在不在走，只有"存在但不是工作区"
    这一档才报错（那一档没有安全的默认动作）。
    """
    base = Path(root)
    chosen = name or next_name(base)
    path = base / chosen
    state, why = classify(path)

    if start not in ("auto", "cold", "warm"):
        raise ValueError(f"--start 只能是 auto/cold/warm，收到 {start!r}")

    if start == "cold":
        if state in ("workspace", "not_a_project"):
            raise ProjectExists(
                f"{path} 已经存在（{why}）⇒ 冷启动要一个干净的落点。"
                "换一个项目名（不写 --name 就是自动取下一个号），或显式 --start warm 复用它。"
                "我不会替你删这个文件夹。"
            )
        return ProjectRef(chosen, path, False, "cold", f"冷启动：{why}", start)

    if start == "warm":
        if state == "workspace":
            return ProjectRef(chosen, path, True, "warm", f"热启动：{why}", start)
        raise ProjectMissing(
            f"{path} 不能热启动（{why}）⇒ 热启动要求这个项目已经存在且初始化过。"
            "要新建一个就 --start cold（或干脆不写 --start，走 auto）。"
        )

    # auto
    if state == "workspace":
        return ProjectRef(chosen, path, True, "warm", f"热启动（auto）：{why}", start)
    if state in ("absent", "empty"):
        return ProjectRef(chosen, path, False, "cold", f"冷启动（auto）：{why}", start)
    raise ProjectNotAWorkspace(
        f"{path} 存在，但{why} ⇒ 既不能当冷启动的落点（它会毁掉里面的东西），"
        "也不能当热启动的工作区（里面没有本框架的表）。换一个项目名，或先用 "
        "--projects-dir 指到别处。"
    )


class ProjectExists(RuntimeError):
    """显式冷启动，但目标文件夹已经存在。"""


class ProjectMissing(RuntimeError):
    """显式热启动，但目标项目还不存在。"""


class ProjectNotAWorkspace(RuntimeError):
    """目标文件夹存在，但它既不是空的、也不是本框架的工作区。"""


@dataclass
class RunRecord:
    """一次项目运行的记账（写进 `project.json`，也是打印给用户的那份读数）。"""

    run_index: int
    mode: str
    topic: str
    out_dir: str
    started_at: str
    budget_usd: float
    max_calls: int
    books_dir: str
    ingest: dict = field(default_factory=dict)
    extraction: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """落进项目卡的形状（这一次运行的全部读数与备注）。"""
        return {
            "run_index": self.run_index, "mode": self.mode, "topic": self.topic,
            "out_dir": self.out_dir, "started_at": self.started_at,
            "budget_usd": self.budget_usd, "max_calls": self.max_calls,
            "books_dir": self.books_dir, "ingest": self.ingest,
            "extraction": self.extraction,
            "result": self.result, "notes": self.notes,
        }


def _load_card(path: Path) -> dict:
    card = path / "project.json"
    if card.is_file():
        try:
            data = json.loads(card.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            # 卡坏了不许当成"没有卡"：那会把历史静默抹掉。调用方按 `notes` 里
            # 这一条决定要不要人看一眼。
            return {"card_unreadable": True}
    return {}


def create_project(ref: ProjectRef, *, now: str | None = None,
                   force_nonempty: bool = False) -> dict:
    """按 `ref` 建/初始化工作区，并写一张项目卡。冷启动/收编才调用它。

    `force_nonempty=True` 只由 `adopt_project` 在"用户自己往文件夹里丢过东西"
    那一档传进来（业主 2026-10-13 的口径）；它只是对 `Store.init` 那道
    "外来目录"守卫开一次口子，**不**改变本函数对文件的任何行为。
    """
    from . import schema as S

    ref.path.mkdir(parents=True, exist_ok=True)
    store = Store(ref.path)
    store.init(force=bool(force_nonempty))
    # 推进编号水位：删掉中间的项目之后，那个号也不许被下一次自动命名捡回去。
    m = _NAME_RE.match(ref.name)
    if m:
        high = max(_sequence_high(ref.path.parent), int(m.group(1)))
        (ref.path.parent / SEQUENCE_FILE).write_text(str(high), encoding="utf-8", newline="\n")
    # 落一个显式标记：`classify` 靠它区分"本框架的工作区"与"恰好也有 data/ 的目录"。
    (ref.path / ".agentflow-workspace").write_text(
        f"agentflow project workspace\nname={ref.name}\ncreated_at={now or S.now_iso()}\n",
        encoding="utf-8", newline="\n")
    card = _load_card(ref.path)
    card.setdefault("name", ref.name)
    card.setdefault("created_at", now or S.now_iso())
    card["card_version"] = CARD_VERSION
    card["projects_dir_policy"] = "一个项目一个文件夹；默认命名 project1..N"
    runs = card.setdefault("runs", [])
    card["cold_runs"] = sum(1 for r in runs if r.get("mode") == "cold")
    (ref.path / "project.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    return card


def adopt_project(root: str | Path, *, name: str | None = None, now: str | None = None,
                  allow_nonempty: bool = True) -> dict[str, Any]:
    """把一个**用户自己建的、里面已经有东西的**文件夹收编成项目（业主 2026-10-13）。

    业主的原话：「要知道有时候用户会自己在 projects 里建文件夹，然后把几个文件丢进去，
    就用系统开始工作的。也就是项目中除了系统成体系的产出，其他内容不会是结构化的」。

    于是"正常的创建逻辑"必须分三种落点，一条都不许拿"不干净"当理由拒绝：

    ====================  ==================================================
    落点现状              动作
    ====================  ==================================================
    不存在 / 空的          普通冷启动（`create_project` 那套骨架）
    **不空、不是工作区**   **收编**：把原有条目逐条记进项目卡（`user_files`，
                          它们就是这一趟的输入材料），再铺骨架；**一个字节都不动**
    已经是工作区          热启动复用（不重铺、不报错）
    ====================  ==================================================

    "不动用户的文件"不是口号，是这一条的三处机械保证：① 只 `mkdir` 与写我们自己的
    三件（`data/`、`.agentflow-workspace`、`project.json`），从不删改别的路径；
    ② 原有条目**逐条记进项目卡**（`user_files`），事后能回答"哪些是用户带进来的"；
    ③ 返回的读数里逐条列出它们（`adopted`），而不是悄悄吞掉。

    `allow_nonempty=False` 时才回到旧口径（拒绝非空的外来目录）—— 那是给"我要一个干净落点"
    的调用方留的，不再是默认。
    """
    base = Path(root)
    chosen = name or next_name(base)
    path = base / chosen
    state, why = classify(path)
    if state == "not_a_project" and not allow_nonempty:
        raise ProjectNotAWorkspace(
            f"{path} 存在，但{why} ⇒ 这次调用要求一个干净的落点（allow_nonempty=False）。")
    before: list[str] = []
    if state == "not_a_project":
        before = sorted(p.name for p in path.iterdir())
    if state == "workspace":
        return {"project": ProjectRef(chosen, path, True, "warm",
                                      f"热启动：{why}", "auto").to_dict(),
                "card": _load_card(path), "adopted": [], "created": False}
    # 收编/冷启动：骨架照铺；`force=True` 这一处**只**为"非空"开（用户自己的文件不动）
    card = create_project(ProjectRef(chosen, path, False, "cold", f"收编：{why}", "auto"),
                          now=now, force_nonempty=_nonempty_ok(path, state))
    if before:
        card = _remember_user_files(path, before, now=now)
    return {"project": ProjectRef(chosen, path, True, "warm",
                                  f"收编完成：{why}", "auto").to_dict(),
            "card": card, "adopted": before, "created": True}


def _nonempty_ok(path: Path, state: str) -> bool:
    """要不要对 store 的"外来目录"守卫开口子：只有"用户自己丢过东西"这一档才开。"""
    return state == "not_a_project"


def _remember_user_files(project: Path, names: list[str], *, now: str | None = None) -> dict:
    """把用户原有的条目记进项目卡（`user_files`）—— 收编的**唯一**痕迹，不猜内容。"""
    import json as _json

    card = _load_card(project)
    card["user_files"] = [{"name": n, "at": now or _now()} for n in names]
    card["user_files_note"] = ("这些是收编之前就在文件夹里的东西（用户带进来的输入材料）："
                              "框架不解析、不改动、不删除它们；系统的产出另在 data/ 与 out/ 下")
    (project / "project.json").write_text(
        _json.dumps(card, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return card


def _now() -> str:
    from . import schema as S

    return S.now_iso()


def seed_source_paper(project: str | Path, *, paper: str | Path,
                      force: bool = False) -> dict[str, Any]:
    """把一篇外部论文铺进项目：`source/` = 只读基线，`out/paper/main.tex` = 可改副本。

    为什么要有这一条（业主 2026-10-13：「打通正常的创建项目逻辑」）：`create_project` 只铺
    工作区骨架，**没有任何受支持的路径把"那篇论文"放进项目** —— 于是 T1 的夹具是手搓的，
    而绕过守卫手抄（`init --force`）会留下一个没有项目卡、产物归属也接不上的文件夹。

    口径三条：
    1. **只读基线不许被覆盖**：`source/main.*` 已在盘上时拒绝（`force=True` 才覆盖）——
       它是"前后对比"的分母，覆盖它等于把这一趟的判据毁掉；
    2. **可改正文只从基线复制**：给了同目录的 `.tex` 就复制成 `out/paper/main.tex`；
       只给 PDF 时**不替它编正文**（如实说"可改正文还没写"），那是 G 的活；
    3. 返回读数 `{project, source, manuscript, note}` —— 铺了哪些、没铺什么、为什么。
    """
    import shutil

    proj = Path(project)
    if not proj.is_dir():
        raise ProjectMissing(f"项目目录不在盘上：{proj}")
    src = Path(paper)
    if not src.is_file():
        raise FileNotFoundError(f"论文不在盘上：{src}")
    src_dir = proj / "source"
    pkg_dir = proj / "out" / "paper"
    pdf_dst = src_dir / f"main{src.suffix.lower() or '.pdf'}"
    tex_src = src.with_suffix(".tex")
    tex_dst = src_dir / "main.tex"
    man_dst = pkg_dir / "main.tex"
    clashes = [p for p in (pdf_dst, tex_dst if tex_src.is_file() else None, man_dst)
               if p is not None and p.exists()]
    if clashes and not force:
        raise ProjectExists(
            "这些落点已在盘上 ⇒ 不覆盖（只读基线是判据的分母）："
            + ", ".join(str(p.relative_to(proj)) for p in clashes)
            + "。要覆盖就显式 force=True")
    src_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, pdf_dst)
    out: dict[str, Any] = {"project": str(proj), "source": [f"source/{pdf_dst.name}"],
                           "manuscript": "", "note": ""}
    if tex_src.is_file():
        pkg_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tex_src, tex_dst)
        shutil.copy2(tex_src, man_dst)
        out["source"].append("source/main.tex")
        out["manuscript"] = "out/paper/main.tex"
    else:
        out["note"] = ("给的是一份 PDF、同目录没有 .tex ⇒ 只铺了只读基线；"
                       "可改正文要由 G 自己写进 out/paper/main.tex（这一步不替它编正文）")
    return out


def create_review_project(root: str | Path, *, paper: str | Path,
                          name: str | None = None, now: str | None = None,
                          force: bool = False) -> dict[str, Any]:
    """**正常地**建一个审阅型项目：走 `resolve(start="cold")` 的守卫 + 骨架 + 铺那篇论文。

    与手抄的区别（这才是"打通"）：外来目录/已存在的目录在 `resolve` 那一层就被拒
    （不是靠 `init --force` 绕过去）；建出来的文件夹带 `.agentflow-workspace` 与 `project.json`，
    于是 `classify` / 产物归属 / `project list` 都认得它。
    """
    # 用户自己建的目录（里面已经有东西）也走这条路：`adopt_project` 收编它、
    # 把原有条目记进项目卡，再铺论文（业主 2026-10-13 的口径）。
    got = adopt_project(root, name=name, now=now)
    proj = Path(got["project"]["path"])
    seeded = seed_source_paper(proj, paper=paper, force=force)
    return {"project": got["project"], "card": got["card"],
            "seeded": seeded, "adopted": got["adopted"]}


def _next_run_index(path: Path) -> int:
    out = path / "out"
    if not out.is_dir():
        return 1
    used = [int(m.group(1)) for p in out.iterdir()
            if p.is_dir() and (m := re.match(r"^run-(\d+)$", p.name))]
    return max(used) + 1 if used else 1


def plan(root: Path | str, name: str | None = None, *, start: str = "auto",
         books_dir: str | Path | None = None, topic: str = "") -> dict:
    """只读地说明"这次会怎么跑"（不建目录、不写字节）。给 `project plan` 用。"""
    ref = resolve(root, name, start=start)
    return {
        "projects_dir": str(Path(root)),
        "project": ref.to_dict(),
        "run_index": _next_run_index(ref.path) if ref.exists else 1,
        "books_dir": str(books_dir) if books_dir else "",
        "topic": topic,
        "will_create": ref.mode == "cold",
        "will_ingest": bool(books_dir),
        "note": (
            "冷启动：会新建文件夹、初始化工作区、登记书；"
            "热启动：复用已有工作区（已登记的书按内容 hash 跳过），产物写进新的 out/run-N"
        ),
    }


def list_projects(root: Path | str) -> list[dict[str, Any]]:
    """列出现有项目（名字 / 状态 / 冷暖次数 / 上次模式）。只读。"""
    base = Path(root)
    out: list[dict[str, Any]] = []
    if not base.is_dir():
        return out
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        state, why = classify(child)
        card = _load_card(child)
        out.append({
            "name": child.name, "state": state, "why": why,
            "cold_runs": card.get("cold_runs"), "warm_runs": card.get("warm_runs"),
            "last_mode": card.get("last_mode"),
            "card_unreadable": bool(card.get("card_unreadable")),
        })
    return out


def _open_extract_task(store: Store, project_name: str, input_key: str = "") -> str:
    """为"模型读书"这一步开一条真台账号（`t-NNNN`）并写下 `running` 行。

    为什么要它：抽取的花销按 `task_id` 记进 `usage_ledger`，而花销必须挂得上一条
    任务行（`verify.verify_all` 的 `dangling_usage_task` 就是问这件事）。
    以前这里用的是 `f"{project_name}-extract"` —— 那既不是台账号格式（`t-NNNN`），
    台账里也没有对应行 ⇒ 用户跑完 `--extract` 再自查，会看到两条 error 加一条
    warning（"刚跑成功的那一跑，自查说不一致"）。现在按与主控同一套口径开行：
    `role=B`（抽取是 B 的职责）、`action=extract`、`called_by=M`、`depth=1`。

    `input_key` 也要给：它是循环检测的键（同一条 `(role, action, input_key)` 出现在
    祖先链上才算循环），留空会被 `verify_tasks` 报 `task_without_input_key`（warning）
    —— 实测漏第一次就撞到。取"这一跑读的是哪一架子书"（书架路径）比取项目名更贴近
    输入本身；没给书架就退回项目名。

    这里刻意不截断（与 `runflow._new_task_row` 把主题截到 120 字不同）：那条截断的
    理由是"主题是散文，长了对人没用"；而路径不是散文 —— 两个只有末尾不同的书架会在
    截断后得到同一个键，于是循环检测把一次合法召唤误判成循环（`cycle_detected`）。
    键的语义是"输入指纹"，截断它就等于让两个不同的输入共用一个指纹。
    """
    from . import schema as S
    from .interactions import next_prefixed_id

    key = str(input_key or "").strip() or project_name
    with store.tx("tasks", actor="cli") as tx:
        # 台账号的取法与 `Conductor._write_new_row` 同一套口径：`next_prefixed_id`
        # 取 max+1（它不是 `store.alloc_id` 的类别 —— `ID_COUNTERS` 里没有 `task`，
        # 实测踩过：写成 `tx.alloc_id("task")` 会得到"未知 ID 类别"，退出码 2）。
        tid = next_prefixed_id(tx.rows("tasks"), "task_id", "t")
        row = S.Task(task_id=tid, role="B", action="extract", called_by="M",
                     status="running", input_key=key,
                     detail=f"模型读书（项目 {project_name}）",
                     started_at=S.now_iso()).to_dict()
        tx.upsert("tasks", row)
    return tid


def _close_extract_task(store: Store, task_id: str, extraction: Mapping[str, Any]) -> None:
    """把那条 `running` 行收成终态，并把台账里那一笔花销抄回 `tasks`。

    三态：抽到东西 ⇒ `done/ok`；没 key / 一轮都没成功 ⇒ 仍然 `done`，但 `detail`
    里逐字写清"没抽到"与原因（抽取失败不是任务失败 —— 它的重试语义由 `last_mine_error`
    决定，下次还认这本书）。
    """
    from . import schema as S
    from .tokenmeter import TokenMeter

    meter = TokenMeter(store)
    tokens = int(meter.tokens_for(task_id) or 0)
    usd = float(meter.usd_for(task_id) or 0.0)
    got = int(extraction.get("concepts_created") or 0) + int(extraction.get("relations_added") or 0)
    err = str(extraction.get("error") or "")
    detail = (f"模型读书：概念 {extraction.get('concepts_created', 0)} / "
              f"关系 {extraction.get('relations_added', 0)} / "
              f"读懂 {extraction.get('processed', 0)} 本"
              + (f"；有轮次失败：{err[:200]}" if err else "")
              + ("（一条都没抽到）" if got == 0 and not err else ""))
    with store.tx("tasks", actor="cli") as tx:
        # 读取必须在锁内（`tx.rows` 而不是 `store.rows`）：`store.rows` 是无锁快照读，
        # 拿它读到的东西去写，中间就是一个窗口 —— 别的进程刚改过的那条行在这里看不见，
        # 于是这行会以旧内容被写回（`TokenMeter.charge_once` 的 docstring 逐字踩过同一个坑）。
        row = {str(r.get("task_id")): dict(r) for r in tx.rows("tasks")}.get(task_id)
        if row is None:
            return
        row.update(status="done", outcome="ok", ended_at=S.now_iso(),
                   detail=detail, tokens=tokens, usd=usd)
        tx.upsert("tasks", row)


def extract_with_model(store: Store, *, books_limit: int | None = None,
                       extractor: Any = None, extract_text_fn: Any = None,
                       max_rounds: int = 1, task_id: str = "") -> dict:
    """用模型把库里还没抽过的书读一遍（B 的职责），每条关系都要过逐字回验。

    ## 这一步为什么值钱

    `llm.LLMExtractor` 的契约是"问模型、但绝不相信它"：模型给出的每条关系的
    `quote` 都会被 `_ground_relations` 拿去原文里逐字找；找不到的当场剔除并计数
    （`relations_dropped` / `drop_reasons`）。而 `agent_b` 那一侧还会对每条关系再跑
    一次 `quoterify.check_quote`（带页码窗口）并把结果记进关系行。

    所以这一步的读数天然是三态的：抽到几条、剔除几条（为什么剔除）、回验通过几条。
    "模型读了这些书"因此不是一个说法，而是一组可复核的数字。

    `extractor=None` 时用真模型（`modelclient.client_from_env` + `LLMExtractor`）；
    没配 key 时 `ModelClient.complete` 抛 `ModelUnavailable`，`agent_b` 会把它记成
    `last_mine_error` 并且不置 processed（下次还能重试）—— 也就是说
    "没 key"不会污染库里的状态。
    """
    from .agent_b import AgentB
    from .llm import LLMExtractor
    from .modelclient import SCOPE_EXTRACT, client_from_env
    from .tokenmeter import TokenMeter

    if extractor is None:
        # `meter` 必须给：不给的话这一次抽取的花销一笔都进不了 `usage_ledger`，
        # 而 CLI 上会打出 0.0 USD —— 那正是"自报比事实好看"的形态。
        # 实测（2026-09-28）：第一次真跑打出的就是 `0.0 USD / 3 次调用`，
        # 钱花了、账上没有。归口用 `extract`（`schema.USAGE_SCOPES` 里的一档）。
        # `task_id=task_id or None`：给不出来就如实说"这一笔不挂在任何一次召唤上"。
        # 此前这里与 `host.b_extractor` 是同一类病：把 `None` 折成字符串 `"(未接线)"`。
        # 那个字符串不是 `t-NNNN` 契约里的号 ⇒ `verify.verify_all` 把它报成
        # `dangling_usage_task`(error)，而账本看起来"有个具体的任务号"（假读数比没读数更难发现）。
        # 透传 `None` 的语义与 `charged=False` 完全无关：前者是"这笔花销挂不上召唤"，
        # 后者是"这笔没有真的入账"（`uncharged()` 数的是后者）—— 两件事不许合并成一个标签。
        client = client_from_env(scope=SCOPE_EXTRACT, meter=TokenMeter(store),
                                task_id=task_id or None, role="B")
        # 输出额度**不再由我们设**（2026-10-15 业主裁定「我们不卡 token，只卡总花销的钱」）：
        # 这里曾写 `max_tokens=8192`，理由是"缺省 4096 会把长输出截在半句上"。
        # 真调用对照（2026-10-15）：请求体里不带 `max_tokens` 时上游回
        # `finish_reason=stop`、`tokens_out=14,015`（带上 32,768 反而只有 12,987）。
        extractor = LLMExtractor(client)
    else:
        client = None

    agent = AgentB(
        store,
        extractor=extractor,
        extract_text=extract_text_fn or memo_extract_fn(),
        # `quote_widen_pages=0`：页码由模型写在 JSON 里，扩大窗口会掩盖"页码记错"
        # 这件事（`E-11` 专门把那一档单列出来）。这里按最严的口径跑。
        config={"quote_widen_pages": 0, "allow_fulltext_quote_fallback": False},
        actor="agent-B(model)",
    )

    rounds: list[dict] = []
    for _ in range(max(1, int(max_rounds))):
        res = agent.run_once()
        payload = res.to_dict() if hasattr(res, "to_dict") else dict(res or {})
        processed = int(payload.get("processed") or 0)
        failed = int(payload.get("failed") or 0)
        if processed:
            # 只在这一轮真的处理了一篇时挂抽取器的报告：否则 `last_report`
            # 还是上一轮那份，打印出来会让人以为"这一轮又抽了一批"（真跑踩过）。
            report = getattr(extractor, "last_report", None)
            if report:
                payload["extractor_report"] = report
        rounds.append(payload)
        # 停止条件是"这一轮什么都没试"，不是"没处理成功"：
        # 抽取失败（`failed=1`、`processed=0`）本来就不置 `processed`（留给租约到期重试），
        # 把那种轮当成"队列空了"会让一次失败的抽取静默结束整轮循环 ——
        # 实测：7 本书只读了 2 本，而 CLI 上看起来"跑完了"。
        if processed == 0 and failed == 0:
            break

    # 抽取阶段就被剔除的关系（`LLMExtractor._ground_relations`：模型的 `quote` 在原文里
    # 逐字找不到 ⇒ 当场丢掉）。必须单独汇总出来：它此前只写进抽取器的 `last_report`，
    # 于是真跑时会出现"日志里有 7 行『剔除引文无法回验的关系』，而汇总框里
    # 『引文未过（已剔除）』读 0" —— 同一份输出里两个数互相矛盾，用户没法判断该信哪个。
    # 实测（2026-09-30，2 本书 87 页）：新增关系 13 / 抽取阶段剔除 7 ⇒ 模型一共提了 20 条。
    # 两档是两个阶段，不是同一件事的两种说法：这里是"引文在原文里根本找不到"，
    # 下面的 `quotes_failed` 是"活到落库那一步、但带页码窗口的回验没过"。
    dropped = 0
    drop_reasons: list[str] = []
    for r in rounds:
        rep = r.get("extractor_report") or {}
        dropped += int(rep.get("relations_dropped") or 0)
        drop_reasons.extend(str(x) for x in (rep.get("drop_reasons") or []))

    out: dict[str, Any] = {
        "rounds": rounds,
        "processed": sum(int(r.get("processed") or 0) for r in rounds),
        "failed": sum(int(r.get("failed") or 0) for r in rounds),
        "unreadable": sum(int(r.get("unreadable") or 0) for r in rounds),
        "concepts_created": sum(int(r.get("concepts_created") or 0) for r in rounds),
        "relations_added": sum(int(r.get("relations_added") or 0) for r in rounds),
        "quotes_verified": sum(int(r.get("quotes_verified") or 0) for r in rounds),
        "quotes_failed": sum(int(r.get("quotes_failed") or 0) for r in rounds),
        "quotes_unknown": sum(int(r.get("quotes_unknown") or 0) for r in rounds),
        # `relations_dropped` 是抽取阶段的剔除数（与 `quotes_failed` 是两个阶段）；
        # 两者相加才是"模型一共提了多少条关系"，而这个和必须能从输出里读出来。
        "relations_dropped": dropped,
        "drop_reasons": drop_reasons,
        # 失败原因必须逐条留下：只报"失败 1 本"读不出下一步该做什么。
        "errors": [d for r in rounds for d in (r.get("details") or [])
                   if d.get("error") or d.get("skipped")],
    }
    if client is not None:
        out["model"] = client.to_dict()
    # 概念数读合成视图（并表过渡期：老表 + 新标准 `kind="concept"`，同号去重）。
    # 读老表会在迁移之后读到 0，读新标准会在迁移之前读不到老行 —— 这个数字是给人看的
    # 读数，两种读法都会让它说谎。读不成时给 `None`（不是 0）："没读成"与"库里没有"
    # 必须分得开，并在同一个字典旁给一条 `store_counts_problems` 点名原因。
    _cv = CR.view(store)
    out["store_counts"] = {
        "literature_processed": sum(1 for r in store.rows("literature") if r.get("processed")),
        "concepts": (len(_cv["rows"]) if _cv["checked"] else None),
        "relations": len(store.rows("relations")),
    }
    if not _cv["checked"]:
        out["store_counts_problems"] = [f"概念数没读成：{_cv['reason']}"]
    _ = books_limit
    return out


def run_project(root: Path | str, *, name: str | None = None, start: str = "auto",
                topic: str, books_dir: str | Path | None = None, books_limit: int | None = None,
                budget_usd: float = 0.5, max_calls: int = 2,
                retrieval_limit: int = 7, fulltext: bool = True,
                extract: bool = False, extract_rounds: int = 1, lean: bool = False,
                now: str | None = None, transport: Any = None,
                text_store_dir: str | Path | None = None,
                run_topic_fn: Any = None) -> dict:
    """跑一个项目：解析工作区 → （冷启动则建）→ 登记本地书 → 端到端一次 → 记项目卡。

    `run_topic_fn` 是给测试用的接缝（不传就用真的 `runflow.run_topic`）。
    返回 `{"project", "run", "result"}`；`result` 就是 `run_topic` 的那份字典
    （含 `exit_code` / `reason` / `artifacts` / `spent_usd_this_run`）。
    """
    from . import schema as S
    from .modelgw import spec_from_env
    from . import fulltextstore

    ref = resolve(root, name, start=start)
    notes: list[str] = []
    if ref.mode == "cold":
        create_project(ref, now=now)
    else:
        card = _load_card(ref.path)
        if card.get("card_unreadable"):
            notes.append("project.json 读不了（内容坏了）⇒ 本次运行不会覆盖它，请人看一眼")
    card = _load_card(ref.path)

    store = Store(ref.path)
    ingest: dict[str, Any] = {}
    if books_dir:
        rep = ingest_directory(store, books_dir, limit=books_limit,
                               note=f"{ref.name} 登记本地藏书")
        ingest = rep.to_dict()

    # 运行号与产物目录只在真的要跑模型时才分配（`R-25`）。
    # 改前：不给 `--topic` 的那次调用也会占一个号、建出一个空的 `out/run-N/`，
    # 而它没有六件产物 —— 读到那个目录的人会问"它的产物呢"。
    # 数据本身没错（卡里 topic 空、result 空），但那是个可被误读的形态。
    topic_text = topic.strip()
    run_index = _next_run_index(ref.path) if topic_text else None
    out_dir = (ref.path / "out" / f"run-{run_index}") if run_index else None
    if not topic_text:
        notes.append("没给 --topic ⇒ 本次只做登记与冷/热启动，不跑模型、不分配运行号、"
                     "不建 out 目录（跑模型那一步需要主题）")

    # 模型读库这一步排在主题作答之前：先把概念/关系抽进库里，
    # 主题那一跑的材料才不只是"一页摘录"，而是有图可查的知识面。
    extraction: dict[str, Any] = {}
    if extract:
        # 抽取这一步也要有一条自己的 `tasks` 行（2026-09-30 修）。
        #
        # 为什么：`modelclient` 按 `task_id` 把花销记进 `usage_ledger`，而原来的
        # `task_id=f"{ref.name}-extract"`（例如 `first-extract`）既不是合法台账号
        # （`t-NNNN`），台账里也没有对应的行 ⇒ 用户跑完 `project run --extract` 再跑
        # `verify`，会看到两条 `dangling_usage_task`（error）加一条
        # `usage_task_total_mismatch`（warning）。实测就是这么撞到的：
        # 「刚跑成功的那一跑，自查说数据不一致」—— 那会直接毁掉用户对读数的信任。
        extract_task = _open_extract_task(store, ref.name,
                                          input_key=str(books_dir) if books_dir else "")
        try:
            extraction = extract_with_model(
                store, books_limit=books_limit, extract_text_fn=memo_extract_fn(),
                max_rounds=extract_rounds,
                task_id=extract_task,
            )
        except Exception as exc:  # noqa: BLE001 —— 抽取失败不该毁掉后面的主题那一跑
            extraction = {"error": f"{type(exc).__name__}: {exc}"}
            notes.append(f"模型抽取那一步失败了（{type(exc).__name__}）⇒ 库里没有新的概念/关系；"
                         "主题那一跑照旧，但材料只有摘录")
        finally:
            # 把台账号写进这一跑的结果里：用户看到"这一步花了 0.017 USD"之后，
            # 下一步一定会问"这笔钱挂在哪条任务上"。让卡里直接有这个号，
            # 比让人去 `tasks.json` 里按 role/action 反查可靠（并发下 role 会重复）。
            extraction.setdefault("task_id", extract_task)
            _close_extract_task(store, extract_task, extraction)

    spec = spec_from_env()
    if not spec.configured:
        notes.append(
            "环境里没有模型 key（AGENTFLOW_MODEL_API_KEY 与 agentflow/settings.json 的 "
            "model.api_key 都没有值）⇒ 这一次会以退出码 2（没查成）结束，"
            "六件产物照写，检索会被跳过（材料没有消费者）。"
        )

    # 检索与全文两条路共用同一个记忆化抽取器：给模型看的材料与回验比对的文本
    # 必须是同一份（理由见 `locallib.memo_extract_fn` 的 docstring）。
    extractor = memo_extract_fn()
    search_fn = search_fn_for_store(store, extract_fn=extractor) if topic_text else None
    fetch_fn = local_fetch_fn() if (topic_text and fulltext) else None

    runner = run_topic_fn
    if runner is None:
        from .runflow import run_topic as runner  # 延迟 import：runflow 依赖一长串模块

    result: dict[str, Any] = {}
    if topic_text:
        result = runner(
            store, topic=topic_text, budget_usd=float(budget_usd), out_dir=out_dir,
            transport=transport, max_calls=int(max_calls), now=now,
            search_fn={"localpdf": search_fn} if search_fn else None,
            fetch_fn=fetch_fn, extract_fn=extractor, fulltext=bool(fulltext),
            retrieval_limit=int(retrieval_limit),
            # `lean` 必须透传：它是"proof 级证据"那一档的唯一开关。此前 `project` 这个
            # 动词没有这个开关，于是本地书架这条主路径上永远拿不到 proof 级证据，
            # 每次运行的 `not_wired` 里都挂着 lean（实测 2026-09-28：`--lean` 直接报
            # `unrecognized arguments`）。口径与 `run` 那个动词一致：默认关，关着就如实
            # 把"没有任何形式化验证证据"写进未接线清单。
            lean=bool(lean),
            # 项目路径默认把逐页正文存进项目根的 `.fulltext/`（内容寻址、同一本书
            # 只存一份；依据 `draft/30` §T0-6 与 `draft/29` §10.6）。裸 `run` 那个动词
            # 没有项目根，所以它不默认开 —— 要开就显式 `--text-store-dir`。
            # 调用方给了 `text_store_dir` 就按它走（覆盖默认，供 CLI 与测试用）。
            text_store_dir=str(text_store_dir) if text_store_dir
            else str(ref.path / fulltextstore.STORE_DIR_NAME),
        )

    record = RunRecord(
        run_index=run_index, mode=ref.mode, topic=topic_text,
        # 没跑模型那一步时 `out_dir` 是 None ⇒ 卡里写空串（不写字符串 "None"：
        # 那会让读卡的人以为真有一个叫 None 的目录）。
        out_dir=str(out_dir) if out_dir else "",
        started_at=now or S.now_iso(), budget_usd=float(budget_usd),
        max_calls=int(max_calls), books_dir=str(books_dir) if books_dir else "",
        ingest=ingest, result=result, notes=notes,
    )
    if extraction:
        record.extraction = extraction
    runs = card.setdefault("runs", [])
    runs.append(record.to_dict())
    card["cold_runs"] = sum(1 for r in runs if r.get("mode") == "cold")
    card["warm_runs"] = sum(1 for r in runs if r.get("mode") == "warm")
    card["last_mode"] = ref.mode
    card["name"] = card.get("name") or ref.name
    (ref.path / "project.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")

    return {"project": ref.to_dict(), "run": record.to_dict(), "result": result}


# --------------------------------------------------------------------------- #
# 自检：`python -m agentflow.projects`（离线；临时目录里跑，不碰真 projects/）
# --------------------------------------------------------------------------- #


def selftest() -> int:
    """七条：默认命名递增 / 不重用已删号 / auto 冷热 / 显式 cold 撞车报错 /
    显式 warm 缺目录报错 / 存在但非工作区报错 / plan 不写字节。"""
    import tempfile

    print("=" * 72)
    print("projects 自检（离线；全在临时目录里）")
    problems: list[str] = []

    with tempfile.TemporaryDirectory(prefix="projects-selftest-") as td:
        root = Path(td) / "projects"

        if next_name(root) != "project1":
            problems.append(f"空目录下第一个项目名应当是 project1，得到 {next_name(root)}")
        ref1 = resolve(root, None, start="auto")
        print(f"[1] 空目录 auto -> name={ref1.name} mode={ref1.mode} exists={ref1.exists}")
        if (ref1.name, ref1.mode, ref1.exists) != ("project1", "cold", False):
            problems.append(f"空目录 auto 的解析不对：{ref1.to_dict()}")
        create_project(ref1, now="2026-01-01T00:00:00+08:00")
        if classify(ref1.path)[0] != "workspace":
            problems.append(f"建完之后应当是 workspace，得到 {classify(ref1.path)}")

        ref2 = resolve(root, None, start="auto")
        print(f"[2] 建了 project1 之后 auto -> name={ref2.name} mode={ref2.mode}")
        if (ref2.name, ref2.mode) != ("project2", "cold"):
            problems.append(f"下一个名字应当是 project2/cold：{ref2.to_dict()}")

        (root / "project2").mkdir()
        ref3 = resolve(root, "project2", start="auto")
        print(f"[3] 空的 project2 auto -> mode={ref3.mode} reason={ref3.reason}")
        if ref3.mode != "cold":
            problems.append(f"空文件夹应当按冷启动：{ref3.to_dict()}")

        ref4 = resolve(root, "project1", start="auto")
        print(f"[4] 已有的 project1 auto -> mode={ref4.mode}")
        if ref4.mode != "warm":
            problems.append(f"已初始化的工作区应当按热启动：{ref4.to_dict()}")

        try:
            resolve(root, "project1", start="cold")
            problems.append("显式 cold 撞上已有工作区时应当报错")
        except ProjectExists as exc:
            print(f"[5] 显式 cold 撞车 -> ProjectExists：{str(exc)[:60]}…")

        try:
            resolve(root, "project9", start="warm")
            problems.append("显式 warm 撞上不存在的项目时应当报错")
        except ProjectMissing as exc:
            print(f"[6] 显式 warm 缺目录 -> ProjectMissing：{str(exc)[:60]}…")

        junk = root / "project7"
        junk.mkdir()
        (junk / "别的东西.txt").write_text("x", encoding="utf-8")
        try:
            resolve(root, "project7", start="auto")
            problems.append("存在但不是工作区时应当报错")
        except ProjectNotAWorkspace as exc:
            print(f"[7] 存在但不是工作区 -> ProjectNotAWorkspace：{str(exc)[:60]}…")

        before = sorted(p.name for p in root.iterdir())
        p = plan(root, None, start="auto", books_dir="D:\\books", topic="谱不决定图")
        after = sorted(p.name for p in root.iterdir())
        print(f"[8] plan：{p['project']['name']} mode={p['project']['mode']} "
              f"run_index={p['run_index']} will_create={p['will_create']}")
        if before != after:
            problems.append(f"plan 不应当写字节：{before} -> {after}")

    print("=" * 72)
    if problems:
        for pr in problems:
            print(f"[!!] {pr}")
        return 1
    print("自检通过：8 条全过")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手跑入口
    raise SystemExit(selftest())
