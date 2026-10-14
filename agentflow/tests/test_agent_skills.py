# -*- coding: utf-8 -*-
"""skills 三条硬约束的判据（业主 2026-10-14）。

业主原话：「将面对不同类型任务应唤起的协作方式写成各智能体的 skills，以防止前置大量
提示词，**现做现读**……至少为每种智能体特地去找至少 5 个 skill 来综合考量……
定制 skill 时需保证**描述无歧义、准确适配角色、动作都可实现**……
**不能虚构我们系统不存在的动作**」。

## 这一组守四件事

1. **不虚构**：每条 skill 用到的 `角色.动作` 必须在 `capabilities` 里存在，
   且从"拥有这条 skill 的角色"出发**够得到**（自己的动作，或它出边上的角色能做）；
   用到的工具必须在工具面上（`agent_skills.validate()` 逐条查）。
2. **描述无歧义**：`summary` / `when` / `body` 三格都不许空；索引里必须有
   "什么时候读它"这一格（没有它，索引就退化成又一份长文档）。
3. **现做现读**：前置提示词里**只有索引**——正文一个字都不许出现在提示词里
   （这条是本组的反负控：把某条 skill 的正文塞进 `CATALOG` 的 `summary`，
   它必须当场红）。
4. **调研过**：`SURVEY` 每格 ≥5 条、名字都在来源清单（38 个）里 ——
   "每种智能体至少找 5 个来综合考量"这句话唯一能被机器核的形态。
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow import agent_skills as AS
from agentflow import agent_prompts as AP
from agentflow.tools import build_registry


def test_every_action_and_tool_in_the_catalog_really_exists():
    """正控：整本目录逐条过 `validate()` —— 动作存在、可达，工具在面上。"""
    problems = AS.validate()
    assert problems == [], "skills 里出现了做不到的指令：\n  - " + "\n  - ".join(problems)


def test_the_negative_control_catches_a_fabricated_action(monkeypatch):
    """反负控：塞一条**不存在的动作**进去 ⇒ 判据必须当场红。

    没有这一条，上面那条"全绿"说明不了任何事（它可能只是没查）。
    """
    bad = AS.Skill(slug="假的", title="假的", summary="一句话", when="任何时候",
                   body="正文", actions=("Z.fly_to_moon",))
    monkeypatch.setitem(AS.CATALOG, "M", AS.CATALOG["M"] + (bad,))
    problems = AS.validate()
    assert any("Z.fly_to_moon" in p for p in problems), problems


def test_the_negative_control_catches_an_unreachable_action(monkeypatch):
    """反负控之二：动作**真实存在**但那个角色不在本角色的出边里 ⇒ 也必须红。

    这一条挡的是"把别人的活写进我的操作手册"：M 派不动 F/V 的动作（那两条边不存在），
    写进 M 的 skill 就是一句做不到的指令。
    """
    bad = AS.Skill(slug="越权", title="越权", summary="一句话", when="任何时候",
                   body="正文", actions=("F.step",))
    monkeypatch.setitem(AS.CATALOG, "M", AS.CATALOG["M"] + (bad,))
    problems = AS.validate()
    assert any("F.step" in p and "出边" in p for p in problems), problems


def test_the_index_lists_every_skill_with_a_when_and_no_body():
    """索引：每条 skill 一行（路径 + 一句话 + 什么时候读它），且**不含正文**。"""
    for role in ("M", "B", "V"):
        block = AS.index_block(role)
        assert block, role
        for s in AS.skills_for(role):
            assert s.slug in block, (role, s.slug)
            assert s.when in block, (role, s.slug)
        # 反真空：索引里不许出现正文的第一句（那就是"前置全塞"又回来了）
        for s in AS.skills_for(role):
            first = next((ln.strip() for ln in s.body.splitlines()
                          if ln.strip() and not ln.strip().startswith("#")), "")
            if first:
                assert first not in block, (role, s.slug, first)


def test_the_prompt_carries_the_index_and_not_the_manual():
    """端到端：提示词里有索引那一段，而 skill 正文一个字都不在提示词里。"""
    reg = build_registry().registry
    text = AP.system_prompt("M", registry=reg)
    assert "你这一岗的 skills" in text, "提示词里没有 skills 索引那一段"
    for s in AS.skills_for("M"):
        assert s.slug in text, s.slug
        for line in s.body.splitlines():
            line = line.strip()
            if len(line) > 30 and not line.startswith("#"):
                assert line not in text, f"{s.slug} 的正文被塞进了前置提示词：{line[:40]}"


def test_the_skills_land_on_disk_so_they_can_be_read_on_demand(tmp_path):
    """`materialize` 真的把正文写到工作区里（角色才读得到），且幂等。"""
    written = AS.materialize(tmp_path)
    assert written, "一份都没写"
    for s in AS.skills_for("M"):
        owner = AS.SHARED if s in AS.CATALOG.get(AS.SHARED, ()) else "M"
        path = tmp_path / AS.SKILLS_DIR / owner / f"{s.slug}.md"
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert s.title in text and s.body.strip()[:40] in text, path
    assert AS.materialize(tmp_path) == [], "第二次跑还是重写了一遍（不幂等）"


def test_every_role_has_at_least_five_builtin_skills_surveyed():
    """业主那句"每种智能体至少找 5 个 skill 来综合考量"的机器形态。"""
    names = set(AS.builtin_sources())
    assert len(names) == 38, f"来源清单应当是那 38 个：{len(names)}"
    assert set(AS.SURVEY) >= {"shared", "M", "A", "B", "C", "D", "E", "F", "G", "H", "V"}, \
        sorted(AS.SURVEY)
    for role, rows in AS.SURVEY.items():
        assert len(rows) >= 5, (role, rows)
        assert len(set(rows)) == len(rows), (role, rows)
        unknown = [r for r in rows if r not in names]
        assert not unknown, f"{role} 的调研记录里有来源目录里不存在的名字：{unknown}"


def test_the_negative_control_catches_an_empty_when(monkeypatch):
    """反负控之三：`when` 空 ⇒ 红（描述无歧义那一条的最低门槛）。"""
    bad = AS.Skill(slug="没时候", title="没时候", summary="一句话", when="",
                   body="正文")
    monkeypatch.setitem(AS.CATALOG, "M", AS.CATALOG["M"] + (bad,))
    problems = AS.validate()
    assert any("when" in p for p in problems), problems


def test_the_negative_control_catches_a_tool_named_only_in_the_body(monkeypatch):
    """反负控之七：`tools` 那一格干净，但**正文里**点名了一件本角色没有的工具 ⇒ 红。

    为什么这一格要单独判（2026-10-14）：声明与正文是两样东西 ——
    `tools=("fs.read",)` 可以写得很干净，而正文第一句写"用 `fs.write` 把结果落盘"。
    声明那一格查得再严也管不到那句话，**而模型照做的对象是正文**。
    这一条是那一格判据的负控；正控是整本目录过 `validate()`。
    """
    bad = AS.Skill(slug="正文点名越面工具", title="x", summary="一句话", when="任何时候",
                   body="第 1 步：用 `fs.write` 把结论落盘，然后用 `fs.read` 读回来。",
                   tools=("fs.read",))
    monkeypatch.setitem(AS.CATALOG, "V", AS.CATALOG["V"] + (bad,))
    problems = AS.validate()
    assert any("fs.write" in p and "正文" in p for p in problems), problems


def test_the_body_scan_does_not_fire_on_actions_paths_or_filenames(monkeypatch):
    """反负控之八：正文里的 `D.propose_question` / `data/x.json` / `main.tex` 不报。

    这一条守的是上面那条判据的**另一半**：假阳性会把判据变成噪音，
    于是没人再看它。工具名的形状是"全小写组名.名"，而动作是"大写角色.动作"、
    路径与文件名带斜杠或以 `.json`/`.tex` 结尾 —— 三者机器分得开。
    """
    good = AS.Skill(slug="正文里的非工具点号", title="x", summary="一句话", when="任何时候",
                    body=("派 `D.propose_question`，读 `data/statements.json`、"
                          "`out/paper/main.tex` 与 `fs.read`。"),
                    tools=("fs.read",))
    monkeypatch.setitem(AS.CATALOG, "V", AS.CATALOG["V"] + (good,))
    problems = AS.validate()
    assert not [p for p in problems if "正文" in p], problems


def test_the_catalog_covers_every_role():
    """覆盖：`shared` 与**十个角色**每一格都有内容（少一格 = 那一岗没有按需材料）。

    为什么这条要单独判：`CATALOG` 是一个字典，少写一个键**不会**让任何别的东西变红 ——
    那一岗的索引就静默地只剩 `shared`，而"这一岗该怎么办"这件事没人发现它没写。
    """
    from agentflow import schema as S

    want = {"shared", "M"} | set(S.ROLES)
    assert set(AS.CATALOG) == want, f"少了 {sorted(want - set(AS.CATALOG))}，多了 {sorted(set(AS.CATALOG) - want)}"
    for owner, rows in AS.CATALOG.items():
        assert rows, f"{owner} 一格都没有"
    assert len(set(S.ROLES)) == 9, f"角色表变了：{sorted(S.ROLES)}"


def test_the_negative_control_catches_a_tool_that_exists_but_is_not_on_this_role_surface(monkeypatch):
    """反负控之四：工具**真在注册表里**，但这个角色拿不到 ⇒ 必须红。

    这一条挡的是判据本身的一种退化：把"注册表里有没有这个名字"当成"这个角色能不能用"。
    `fs.write` 在注册表里，而 C 是只读角色（`READ_ONLY_ROLES`），`for_role("C")` 里没有它 ——
    一条说"C 用 fs.write 落盘"的 skill 就是一句做不到的指令，而按旧口径它会被判绿。
    """
    reg = build_registry(workspace_root=pathlib.Path(".")).registry
    names = {s.name for s in reg.for_role("C")}
    assert "fs.write" not in names, "前提反了：C 的工具面里有 fs.write（只读约束松了？）"
    bad = AS.Skill(slug="越面", title="越面", summary="一句话", when="任何时候",
                   body="正文", tools=("fs.write",))
    monkeypatch.setitem(AS.CATALOG, "C", AS.CATALOG["C"] + (bad,))
    problems = AS.validate()
    assert any("fs.write" in p and "C" in p for p in problems), problems


def test_the_negative_control_catches_a_slug_that_cannot_be_a_filename(monkeypatch):
    """反负控之五：slug 里有空白 ⇒ 红。

    真机上出现过一条 slug 是 `" pessimistic-先找边界与反例"`（行首一个空格）：
    它不会让 `summary` / `when` / `body` / 动作 / 工具任何一格变红，而盘上会多出一个
    名字带首空格的文件、索引里两条的差异人眼看不出来。所以这一格必须是机器查的。
    """
    bad = AS.Skill(slug=" 先找边界", title="x", summary="一句话", when="任何时候", body="正文")
    monkeypatch.setitem(AS.CATALOG, "V", AS.CATALOG["V"] + (bad,))
    problems = AS.validate()
    assert any("空白" in p for p in problems), problems


def test_the_negative_control_catches_a_duplicated_slug(monkeypatch):
    """反负控之六：两条 skill 用同一个 slug ⇒ 红（索引里那两行分不开）。"""
    first = AS.CATALOG["V"][0]
    dup = AS.Skill(slug=first.slug, title="重名", summary="一句话", when="任何时候", body="正文")
    monkeypatch.setitem(AS.CATALOG, "V", AS.CATALOG["V"] + (dup,))
    problems = AS.validate()
    assert any("重了" in p for p in problems), problems


def test_every_role_index_is_generated_from_the_catalog():
    """索引：每个角色的索引块只列**它自己 + shared** 的那些条，一条不多一条不少。"""
    for role in AS.CATALOG:
        if role == AS.SHARED:
            continue
        block = AS.index_block(role)
        mine = AS.skills_for(role)
        for s in mine:
            assert f"{AS.SKILLS_DIR}/" in block and s.slug in block, (role, s.slug)
        # 别的角色独有的条目不进这一份索引
        others = {s.slug for r, rows in AS.CATALOG.items() if r not in (role, AS.SHARED)
                  for s in rows} - {s.slug for s in mine}
        for slug in others:
            assert slug not in block, f"{role} 的索引里混进了别人的条目：{slug}"


def test_the_conductor_skill_records_the_two_indirect_routes():
    """M 的"派给谁"那一条必须写着两条间接链的**现状**，而不是旧路线。

    与 `tests/test_the_conductor_does_not_directly_control_bfv.py` 同一条裁定的另一侧：
    权限面不许直接控制 F / V，那么"要 F / 要 V 派给谁"就必须在 M 的操作手册里写成链。
    这条判据刻意不写死整段文字，只钉住三件事：指明 F 在 M 的出边外、给出 `D → F`、
    以及"派 V 会被 `forbidden_edge` 拒"这个读数 —— 换一句话写仍然过。
    """
    route = next(s for s in AS.CATALOG["M"] if "按任务类型" in s.slug)
    body = route.body
    assert "D → F" in body and "F → V" in body, body[:200]
    assert "forbidden_edge" in body, "没写「被拒的读数长什么样」"
    assert "F" not in route.actions and "V" not in {a.split(".")[0] for a in route.actions}, \
        f"M 的条目里不许把 F / V 列成能直接派的：{route.actions}"
    assert "D.propose_question" in route.actions and "B.run_once" in route.actions, route.actions
