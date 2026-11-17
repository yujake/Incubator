# -*- coding: utf-8 -*-
"""保留路径：F 的证明手稿 / D 的研究手稿只许经框架动作生成（不许手写）。

## 改前是什么形态（真机读数，业主已看过）

```text
F 用 fs.write 直接写了 reports/f-proof-sylow1.md（自由格式、无三列依赖表、无洗稿元信息）
D 手写 reports/RESEARCH.md（没有携带单）
⇒ 框架的「渲染手稿 / 秘书洗稿 / D 携带」整条链没有入口
⇒ B 只登记 1 条 conjecture、dependencies 0 行
```

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a F 写 `reports/f-proof-x.md` | 受控拒绝 `reserved_framework_artifact`，盘上零写入 | 改前写得进去 |
| b D 写 `reports/RESEARCH.md` / `reports/0001-research.md` | 2026-11-04 补充裁定：`reports/RESEARCH.md` 是 D 的研究手稿（既有交付物）⇒ 允许；`reports/0001-research.md`（`write_report` 渲染的每问题工作稿，携带单在同一处生成）仍拒。D 在 RESEARCH.md 里自己写 `## 证明` 节那一档由 `tests/test_d_does_not_land_the_proof.py` 钉 | 改前两条都拒（2026-11-01 审计 D-08 的口径）；改后期望如上 |
| c F 写 `notes/x.md`（正控） | 放行 —— 保留表不许扩成"谁都不许写文件" | —— |
| d 反真空 | 把保留表打桩成空 ⇒ a/b 必红（于是 a/b 的绿来自那张表） | —— |
| e `fs.edit` 同一条闸 | 改正文等于绕过同一条保留表 ⇒ 也拒（且盘上那一份逐字未动） | 改前改得进去 |
| m-a M 写 `reports/f-proof-x.md` | 拒（业主 2026-10-27 裁定：主控更不该绕过框架） | 改前写得进去（实测 `start --mode research` 那一趟就是 M 写的） |
| m-b M 写 `reports/RESEARCH.md` | 拒（同上） | 改前写得进去 |
| m-c M 写 `notes/m-plan.md` / `reports/m-review.md`（正控） | 放行 —— 别把主控的正常产出也堵了 | —— |
| m-d 反真空 | 把表里 M 那三行摘掉 ⇒ m-a/m-b 必红 | —— |
| n-a F 写 `notes/f-proof-x.md`（任何目录） | 拒 `reserved_framework_artifact`、零写入 | 改前写得进去：真机 `projects/mp3-r2/notes/f-proof-S1-stmt000008.md` 7595 B / 54 行就是这么进盘的 |
| n-b `reports/` 那一档不回退 | 拒（与 a/b 同一个受控码）；D 的 `notes/0001-research.md` 也在同一道闸下。2026-11-04 补充裁定：D 的 `RESEARCH.md`（研究手稿）在哪个目录都允许 —— 那不是"框架渲染的产物"，内容闸只看里面有没有自己写的 `## 证明` 节 | —— |
| n-c `notes/x.md`（正控） | 放行 —— "任何目录"不等于"任何文件名" | —— |
| n-d 反真空 | 把文件名规则打桩成"一条都不命中" ⇒ n-a/n-b 必红（于是它们的绿来自文件名规则，不是别的路径判据） | —— |

表上三个角色各有各的理由（F 写证明内容 / D 写研究手稿但不落证明稿 / M 是主控，
三类都不许手写框架渲染的产物）；G/L 的排版产物与 M 的其它报告不在表上（c、m-c 与
"G 写 reports/ 下的 `f-proof-*.md` 放行"一起钉住"别扩大"）。

## 2026-11-04（补充裁定）：D 的研究手稿回到"既有形式"

改前（2026-11-01 审计 D-08）D 的 `reports/RESEARCH.md` 与 `*-research.md` 一起被拒；
业主 2026-11-04 的补充裁定把它分开：研究手稿是 D 的既有交付物（收录 F/E 侧成果、
交 B 时随稿带携带单），而证明的落稿与拿签归 F。于是本表的 D 行收成两类：
证明稿形状（`D_PROOF_PATH_RULES`）与每问题工作稿（`suffix:-research.md`，携带单由
`write_report` 生成）；研究手稿那一档改由内容闸判（自己写的 `## 证明` 节才拒），
判据在 `tests/test_d_does_not_land_the_proof.py`。

## 2026-10-27（D6）：目录不再是豁免条件
改前那条闸要求"路径在 `reports/` 下 且 规则命中文件名"。真机发现只要换个目录（`notes/`）
文件名一个字不改就整条绕过 —— n-a 钉的就是这一格；n-b 钉"既有那一路没有回退"，n-c 钉
"别把 `notes/` 整个封掉"，n-d 钉"n-a/n-b 的绿来自文件名规则本身"。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import fs_tools as FT

#: 逐字要求的那句拒信（前半句）。
MESSAGE = "这一份是框架渲染的产物（证明手稿 / 研究手稿），不许手写"
#: 受控码。
KIND = "reserved_framework_artifact"


def _ws(path: pathlib.Path):
    root = path / "ws"
    store = Store(root)
    store.init()
    reg = build_registry(store=store, workspace_root=root).registry
    return root, reg


def _call(reg, role: str, tool: str, **params):
    """按某个角色的身份调一次工具（"我是谁"由 `calling_as` 挂上，与真机同一条路）。"""
    with calling_as("t-probe", role):
        return reg.call(tool, role=role, **params)


def test_a_f_cannot_hand_write_his_proof_manuscript(tmp_path: pathlib.Path) -> None:
    """a 判据：F 用 `fs.write` 写 `reports/f-proof-*.md` ⇒ 拒、零写入。

    两个时刻都不许写：登记前的 `f-proof-plan-<plan>.md` 与登记后的 `f-proof-<号>.md`
    （它们是同一件东西的两个名字）。
    """
    root, reg = _ws(tmp_path)
    for rel in ("reports/f-proof-x.md", "reports/f-proof-plan-000000.md"):
        res = _call(reg, "F", "fs.write", path=rel, content="手写的证明稿")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert MESSAGE in str(res.error or ""), (rel, res.error)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"


def test_b_d_can_write_the_research_manuscript_but_not_the_working_paper(
        tmp_path: pathlib.Path) -> None:
    """b 判据：D 的研究手稿（`reports/RESEARCH.md`）可写；每问题工作稿仍拒。

    2026-11-01 审计 D-08 曾按「`RESEARCH.md` 没有渲染器」把两条都收进保留表；
    2026-11-04 的补充裁定把它翻了回来（「D 侧落的研究手稿就是既有指定形式的那种
    （收录 F、E 侧成果以及其他一些东西）」）⇒ 研究手稿是 D 的既有交付物。
    仍拒的是 `reports/000001-research.md`：它由 `D.write_report` 渲染，携带单
    （F 的证明稿 + 文件 sha256）就在同一处生成，手写它等于把携带单跳过。

    研究手稿里"自己写一节 `## 证明`"那一档在
    `tests/test_d_does_not_land_the_proof.py::test_a_*` 里（内容闸，不在这张路径表上）。
    """
    root, reg = _ws(tmp_path)
    # 既有交付物：允许（改前的期望是"拒"；见 docstring 里那条 2026-11-04 的翻转）
    res = _call(reg, "D", "fs.write", path="reports/RESEARCH.md", content="手写的研究手稿")
    assert res.ok is True, ("D 的研究手稿 `reports/RESEARCH.md` 被拒了 —— 它是既有交付物", res)
    assert (root / "reports" / "RESEARCH.md").is_file()

    # 工作稿仍走 write_report（携带单不许被手写跳过）
    res = _call(reg, "D", "fs.write", path="reports/000001-research.md", content="手写的每问题工作稿")
    assert res.ok is False, res
    assert res.meta.get("kind") == KIND, res.meta
    assert not (root / "reports" / "000001-research.md").exists(), "被拒了却仍落盘"


def test_c_other_paths_are_not_touched(tmp_path: pathlib.Path) -> None:
    """c 判据（正控）：保留表不许扩成"谁都不许写文件"。

    三件事一起钉：F 写 `notes/x.md` 放行；D 写别处的报告放行；
    L 写 `reports/RESEARCH.md`（不是任何人的手稿族名）也放行 —— 表只对表上那些
    "角色 × 族"负责。

    2026-11-17（AU2b 甲类）：改前这里还有一条 `G` 写 `reports/f-proof-g.md` 放行。
    那是缺口本身（G 不该能手写 F 的证明稿族），已按甲类收窄 —— 现在 G 写它受控拒，
    正控换成 G 自己的排版产物（`out/paper/main.tex`），判据见
    `tests/test_fs_other_roles_cannot_hand_write_manuscripts.py`。
    """
    root, reg = _ws(tmp_path)
    res = _call(reg, "F", "fs.write", path="notes/x.md", content="自由笔记")
    assert res.ok is True, res
    assert (root / "notes" / "x.md").is_file()

    res = _call(reg, "D", "fs.write", path="notes/d-scratch.md", content="草稿")
    assert res.ok is True, res

    res = _call(reg, "G", "fs.write", path="out/paper/main.tex", content="G 的论文正文")
    assert res.ok is True, ("G 的排版产物被误伤了", res)

    res = _call(reg, "L", "fs.write", path="reports/RESEARCH.md", content="L 的排版产物")
    assert res.ok is True, ("L 的排版产物被误伤了", res)



def test_m_a_m_cannot_hand_write_the_proof_manuscript(tmp_path: pathlib.Path) -> None:
    """m-a 判据：M 写 `reports/f-proof-*.md` ⇒ 拒、零写入。

    业主 2026-10-27 裁定逐字：「把 M 也纳入保留表 …… 它是主控，更不该绕过框架」。
    改前红：实测 `start --mode research` 那一趟（M→F 不是允许边）就是 M 自己用
    `fs.write` 把 `reports/f-proof-cli.md` 写进了盘 —— 这一条判据把它关掉。
    """
    root, reg = _ws(tmp_path)
    for rel in ("reports/f-proof-x.md", "reports/f-proof-plan-000000.md"):
        res = _call(reg, "M", "fs.write", path=rel, content="主控手写的证明稿")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert res.meta.get("role") == "M", (rel, res.meta)
        assert MESSAGE in str(res.error or ""), (rel, res.error)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"


def test_m_b_m_cannot_hand_write_the_research_manuscript(tmp_path: pathlib.Path) -> None:
    """m-b 判据：M 写研究手稿那几条命名 ⇒ 拒（与 D 同一张表、同一个受控码）。"""
    root, reg = _ws(tmp_path)
    for rel in ("reports/RESEARCH.md", "reports/000001-research.md"):
        res = _call(reg, "M", "fs.write", path=rel, content="主控手写的研究报告")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"
    # `fs.edit` 也是同一条闸（能改正文就等于绕过它）
    rel = "reports/RESEARCH.md"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / rel).write_text("# 原件\n\n原来的正文\n", encoding="utf-8")
    res = _call(reg, "M", "fs.edit", path=rel, old_string="原来的正文", new_string="改过的")
    assert res.ok is False and res.meta.get("kind") == KIND, res
    assert (root / rel).read_text(encoding="utf-8") == "# 原件\n\n原来的正文\n"


def test_m_c_m_other_outputs_are_not_touched(tmp_path: pathlib.Path) -> None:
    """m-c 判据（正控）：别把主控的正常产出也堵了。

    M 的日常产出（计划、评审、汇总）不在保留表上：`notes/m-plan.md` 与
    `reports/m-review.md` 都必须写得进去 —— 表只认"证明手稿 / 研究手稿"两类文件名。
    """
    root, reg = _ws(tmp_path)
    res = _call(reg, "M", "fs.write", path="notes/m-plan.md", content="主控的计划")
    assert res.ok is True, ("M 的正常产出被误伤了", res)
    assert (root / "notes" / "m-plan.md").is_file()

    res = _call(reg, "M", "fs.write", path="reports/m-review.md", content="主控的评审摘要")
    assert res.ok is True, ("M 写 reports/ 下的其它报告被误伤了", res)
    assert (root / "reports" / "m-review.md").is_file()

    res = _call(reg, "M", "fs.write", path="reports/summary.md", content="主控的汇总")
    assert res.ok is True, ("M 写 reports/summary.md 被误伤了", res)


def test_m_d_dropping_the_m_rows_turns_m_a_and_m_b_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """m-d 判据（反真空）：把表里 M 那三行摘掉 ⇒ m-a/m-b 必红。

    打桩点还是那张表（只留 F/D 那三行 = 裁定前的状态）：同一条路径必须写得进去 ——
    于是 "M 被拒绝" 这件事的来源是表上 M 那三行，而不是别处顺手写的判断。
    """
    only_fd = tuple(row for row in FT.RESERVED_ARTIFACT_TABLE if row[0] in ("F", "D"))
    assert only_fd, "表里连 F/D 都没有 ⇒ 这条反真空打桩点在核一个空表"
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", only_fd)
    root, reg = _ws(tmp_path)
    res = _call(reg, "M", "fs.write", path="reports/f-proof-x.md", content="主控手写稿")
    assert res.ok is True, ("M 那几行被摘掉了却还是拒绝 ⇒ m-a 的绿不来自那几行", res)
    res = _call(reg, "M", "fs.write", path="reports/RESEARCH.md", content="主控手写报告")
    assert res.ok is True, ("M 那几行被摘掉了却还是拒绝 ⇒ m-b 的绿不来自那几行", res)


def test_d_stubbing_the_reserved_table_out_turns_a_and_b_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """d 判据（反真空）：把保留表打桩成空 ⇒ a/b 必红。

    打桩点就是那张表（`fs_tools.RESERVED_ARTIFACT_TABLE`）：清空它之后同一条路径
    必须写得进去 —— 于是"保留路径被拒绝"这件事的来源是那张表，而不是别处顺手写的
    某个判断。
    """
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", ())
    root, reg = _ws(tmp_path)
    res = _call(reg, "F", "fs.write", path="reports/f-proof-x.md", content="手写稿")
    assert res.ok is True, ("表被清空了却还是拒绝 ⇒ a 的绿不来自那张表", res)
    res = _call(reg, "D", "fs.write", path="reports/RESEARCH.md", content="手写报告")
    assert res.ok is True, ("表被清空了却还是拒绝 ⇒ b 的绿不来自那张表", res)


def test_e_fs_edit_is_the_same_gate(tmp_path: pathlib.Path) -> None:
    """e 判据：`fs.edit` 也是同一条闸（能改正文就等于能绕过保留表），且零改动。"""
    root, reg = _ws(tmp_path)
    rel = "reports/f-proof-y.md"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / rel).write_text("# 手写稿\n\n原来的正文\n", encoding="utf-8")
    res = _call(reg, "F", "fs.edit", path=rel,
                old_string="原来的正文", new_string="被改过的正文")
    assert res.ok is False, res
    assert res.meta.get("kind") == KIND, res.meta
    assert (root / rel).read_text(encoding="utf-8") == "# 手写稿\n\n原来的正文\n", (
        "被拒了却改了盘上那一份")


# ============================================================ A/B：手稿写权限收窄（2026-11-07）


#: A3 那一组路径：F/B/E 三族的框架证明稿（A 与 B 都不许手写）。
OTHER_ROLE_PROOF_PATHS = (
    "reports/f-proof-000001.md",
    "reports/f-proof-plan-000000.md",
    "reports/b-proof-000001.md",
    "reports/e-proof-000001.md",
)


def test_a3_a_and_b_cannot_hand_write_a_proof_manuscript(tmp_path: pathlib.Path) -> None:
    """A3 判据：A / B 写 `reports/f-proof-*`（及同族的 b/e-稿）⇒ 受控拒、零写入。

    改前实测（a02d4682）：保留表只登记了 F / D / M，于是
    `fs.write("reports/f-proof-000001.md")` 以 A、B 身份调用都是 `ok=True`
    —— 一份"看起来是 F 登记条目"的稿可以由别的角色手写进盘，而 B 的收录按 sha
    认领时会把它当成真稿。收窄之后：这一类落点只有框架（登记条目渲染）能写；
    F / D / M 的既有口径一个字没改（a / b / m-a / n-a 照旧）。
    """
    root, reg = _ws(tmp_path)
    for role in ("A", "B"):
        for rel in OTHER_ROLE_PROOF_PATHS:
            res = _call(reg, role, "fs.write", path=rel, content="别的角色手写的证明稿")
            assert res.ok is False, (role, rel, res)
            assert res.meta.get("kind") == KIND, (role, rel, res.meta)
            assert MESSAGE in str(res.error or ""), (role, rel, res.error)
            assert not (root / rel).exists(), f"{role} 写 {rel} 被拒了却仍落盘"
    # 正控：同一批角色写普通笔记仍然放行（"收窄手稿"不等于"封掉 A/B 的写口"）
    res = _call(reg, "B", "fs.write", path="notes/b-notes.md", content="B 的笔记")
    assert res.ok is True, ("B 的正常笔记被误伤了", res)


def test_a3_dropping_the_a_b_rows_turns_the_criterion_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """A3 反真空：把表里 A / B 那几行摘掉 ⇒ 上一条必红。

    打桩点就是那张表（只留 F / D / M = 改前状态）⇒ 同一批路径必须写得进去，
    于是"A/B 被拒"这件事的来源是表上新增的那几行，而不是别处顺手写的判断。
    """
    before = tuple(row for row in FT.RESERVED_ARTIFACT_TABLE if row[0] in ("F", "D", "M"))
    assert before, "表里连 F/D/M 都没有 ⇒ 这条反真空打桩点在核一个空表"
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", before)
    root, reg = _ws(tmp_path)
    for role, rel in (("A", "reports/f-proof-000001.md"),
                      ("B", "reports/f-proof-000002.md")):
        res = _call(reg, role, "fs.write", path=rel, content="改前状态：写得进去")
        assert res.ok is True, (
            f"A/B 那几行被摘掉了却还是拒绝（{role}/{rel}）⇒ A3 的绿不来自它们", res)


def test_the_table_names_match_the_one_definition(tmp_path: pathlib.Path) -> None:
    """漂移判据：保留表里的名字必须与 `depsection` 那套约定同源（不是两份字面量）。

    `depsection` 是手稿路径的唯一权威（`MANUSCRIPT_STMT_PREFIX` / `D_REPORT_NAMES` /
    `D_WORKING_SUFFIX`）：这里一旦改名而保留表没跟，2 那条闸就会对新名字静默失效 ——
    而那种失效的形态是"写得进去、没人报错"。
    """
    rules = " ".join(rule for _role, rule in FT.RESERVED_ARTIFACT_TABLE)
    assert DS.MANUSCRIPT_STMT_PREFIX in rules, rules
    assert DS.MANUSCRIPT_DIR == FT._RESERVED_DIR, (DS.MANUSCRIPT_DIR, FT._RESERVED_DIR)
    assert DS.D_REPORT_NAMES[0].casefold() in rules.casefold(), rules
    assert DS.D_WORKING_SUFFIX in rules, rules


# ============================================================ n：目录不再是豁免条件（D6）


#: n-a 那一组路径：换目录（含子目录、含工作区根）之后同一个文件名。
#: 工作区根也一起列 —— "任何目录"里最容易被漏掉的就是根，而它恰好是"少写一个 `../`"
#: 时最可能出现的落点。
OUTSIDE_REPORTS = (
    "notes/f-proof-x.md",
    "notes/deep/dir/f-proof-plan-000000.md",
    "f-proof-x.md",
)


def test_n_a_the_proof_manuscript_is_refused_outside_reports(tmp_path: pathlib.Path) -> None:
    """n-a 判据：F 用 `fs.write` 写 `notes/f-proof-*.md` ⇒ 拒、零写入。

    改前红（真机，`projects/mp3-r2`）：F 把 7595 B / 54 行的证明手稿写进了
    `notes/f-proof-S1-stmt000008.md` —— 文件名一个字没改，只是不在 `reports/` 下，
    于是改前那条闸（路径必须在 `reports/` 下）整条没生效，手写稿在盘上看起来就是
    F 的手稿，而"框架渲染 → 秘书洗稿 → D 携带 → B 读稿"一次都没走过。
    """
    root, reg = _ws(tmp_path)
    for rel in OUTSIDE_REPORTS:
        res = _call(reg, "F", "fs.write", path=rel, content="换个目录手写的证明稿")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert MESSAGE in str(res.error or ""), (rel, res.error)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"


def test_n_b_the_reports_directory_still_refuses(tmp_path: pathlib.Path) -> None:
    """n-b 判据：`reports/` 那一路（证明稿 + 每问题工作稿）一个字都没放宽。

    三件事一起钉：① F 写 `reports/f-proof-x.md` 仍拒；② D 的每问题工作稿
    （`reports/…-research.md` / `notes/…-research.md`）仍拒 —— 它由 `write_report`
    渲染、携带单在同一处生成；③ M 的证明稿仍拒（目录不是豁免条件）。

    2026-11-04 补充裁定之后，D 的研究手稿（`RESEARCH.md` 这一族名字）不再受这张
    路径表管：它在 `reports/` 与 `notes/` 都允许（正控在下面最后一段）—— 改前它也在
    这一批"应拒"的清单里，那是 2026-11-01 的口径；见 `test_b_*` 的 docstring。
    """
    root, reg = _ws(tmp_path)
    for role, rel in (("F", "reports/f-proof-x.md"),
                      ("D", "reports/000001-research.md"),
                      ("D", "notes/000001-research.md"),
                      ("M", "notes/f-proof-cli.md")):
        res = _call(reg, role, "fs.write", path=rel, content="手写的框架产物")
        assert res.ok is False, (role, rel, res)
        assert res.meta.get("kind") == KIND, (role, rel, res.meta)
        assert not (root / rel).exists(), f"{role} 写 {rel} 被拒了却仍落盘"

    # 正控（2026-11-04 补充裁定）：D 的研究手稿换个目录也允许 —— 它不是"框架渲染的产物"，
    # 内容闸只看里面有没有 D 自己写的 `## 证明` 节（不在本文件的射程里）。
    for rel in ("notes/RESEARCH.md", "reports/RESEARCH.md"):
        res = _call(reg, "D", "fs.write", path=rel, content="D 的研究手稿（七节）")
        assert res.ok is True, (f"D 的研究手稿 {rel} 被误伤了", res)


def test_n_c_notes_are_still_writable_for_other_names(tmp_path: pathlib.Path) -> None:
    """n-c 判据（正控）：`notes/` 不是禁区，"任何目录"不等于"任何文件名"。

    F 的自由笔记（`notes/x.md` / `notes/f-notes.md`）与 D 的草稿必须写得进去 ——
    这条闸只认"证明手稿 / 研究手稿"两类文件名，把整个 `notes/` 封掉是另一种坏
    （它会逼模型把手稿换个更像笔记的名字，绕过口反而更难查）。
    """
    root, reg = _ws(tmp_path)
    for role, rel in (("F", "notes/x.md"),
                      ("F", "notes/f-notes.md"),
                      ("F", "notes/attack-scratch.md"),
                      ("D", "notes/d-scratch.md"),
                      ("M", "notes/m-plan.md")):
        res = _call(reg, role, "fs.write", path=rel, content="自由笔记")
        assert res.ok is True, (role, rel, res)
        assert (root / rel).is_file(), (role, rel)


def test_n_d_stubbing_the_filename_rule_out_turns_a_and_b_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """n-d 判据（反真空）：把文件名规则打桩成"一条都不命中" ⇒ n-a/n-b 必红。

    打桩点是 `_rule_matches`（文件名规则的唯一实现）：它恒 False 之后，同一批路径
    必须写得进去 —— 于是 "`notes/f-proof-x.md` 被拒" 这件事的来源是文件名规则本身，
    而不是某个顺手的目录判断、也不是保留表之外的另一处。
    """
    monkeypatch.setattr(FT, "_rule_matches", lambda rule, name: False)
    root, reg = _ws(tmp_path)
    for role, rel in (("F", "notes/f-proof-x.md"),
                      ("F", "reports/f-proof-x.md"),
                      ("D", "notes/RESEARCH.md")):
        res = _call(reg, role, "fs.write", path=rel, content="规则被打桩成空之后")
        assert res.ok is True, (
            f"文件名规则被打桩成空了却还是拒绝（{role} / {rel}）⇒ n-a/n-b 的绿不来自它", res)
        assert (root / rel).is_file(), (role, rel)

