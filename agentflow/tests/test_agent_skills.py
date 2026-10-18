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


def test_every_advertised_path_is_readable_through_the_fs_tool(tmp_path):
    """"现做现读"的**闭环**：索引里印出来的路径，用真的 `fs.read` 必须读得到。

    为什么这条是这一组里唯一端到端的一条：其余各条查的都是"目录自己自洽"
    （索引列全了每条、正文没进提示词、落盘幂等、盘点路径存在）。而"现做现读"
    这句话的落点是**三处拼在一起**才成立的：索引里那个路径、`materialize` 写的落点、
    以及 `fs.read` 解析路径用的根。三处各自自洽而拼不上，正是本项目最忌讳的形态 ——
    索引说 `skills/M/x.md`、正文写到别处、工具的根又是第三个地方，
    而**没有任何地方会报错**（模型只会读不到，然后把索引当摆设）。

    判据同时也是那条纪律的机器形态：提示词里那段索引是**给模型照抄的**，
    所以必须能用它逐字去读，不能只"看起来对"。
    """
    import re

    from agentflow.tools import build_registry

    AS.materialize(tmp_path)
    reg = build_registry(workspace_root=tmp_path).registry
    roles = ("M", "A", "B", "C", "D", "E", "F", "G", "H", "V")
    seen: list[tuple[str, str]] = []
    for role in roles:
        block = AS.index_block(role)
        # 只取**表格行**里那一格（行首是 `| ` 的那种）—— 索引开头那句
        # `skills/<角色>/<名字>.md` 是给人看的占位符，不是一条真路径。
        paths = re.findall(r"^\| `(skills/[^`]+\.md)`", block, re.M)
        assert paths, f"{role} 的索引表里一条路径都没有"
        for rel in paths:
            got = reg.call("fs.read", path=rel, role=role)
            assert got.ok, f"{role} 照自己索引里的路径读不到：{rel}（{got.error}）"
            owner = rel.split("/")[1]
            slug = rel.rsplit("/", 1)[1][: -len(".md")]
            want = next(s for s in AS.CATALOG[owner] if s.slug == slug)
            assert want.title in got.data, f"{role} 读到的不是那一份：{rel}"
            seen.append((role, rel))
    # 反真空：条数必须等于"每个角色读得到的那些"之和（少一条就说明索引漏了行）
    assert len(seen) == sum(len(AS.skills_for(r)) for r in roles), len(seen)
    # 负控：盘上没有的路径必须失败 —— 否则上面那些 ok 说明不了"读的就是那一份"
    assert not reg.call("fs.read", path=f"{AS.SKILLS_DIR}/M/不存在的.md", role="M").ok


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


def test_the_whole_source_directory_is_surveyed_not_just_five_per_role():
    """**并集必须覆盖全部 38 个来源**（R126 补）：只查"每格 ≥5"会漏掉整份来源。

    这一条是 2026-10-15 的现场读数逼出来的：`SURVEY` 里当时只出现 **35** 个名字，
    而记录（`draft/120` §三）写着"来源 38 条已逐条读完" —— 三份
    `-neural-network-functions` 变体一次都没被任何一岗记下。
    两条口径差在**方向**上：每格 ≥5 管的是"每个角色有没有看够"，
    覆盖 38 管的是"这份来源清单有没有被看完" —— 少查一条不会让前者变红。

    判据用集合（不是逐格）：一个来源被哪一岗记下由内容决定，不该由这条判据规定。
    """
    covered = {n for rows in AS.SURVEY.values() for n in rows}
    missing = sorted(set(AS.builtin_sources()) - covered)
    assert not missing, (
        f"这 {len(missing)} 个来源一次都没被任何一岗记下 ⇒ " "「38 条已逐条读完」这句话是假的："
        f"{missing}"
    )


def test_the_negative_control_catches_a_source_that_no_role_surveyed(monkeypatch):
    """反负控：把一条来源从所有格子里摘掉 ⇒ 覆盖判据必须红（否则它是真空的）。

    摘的是**唯一**提到它的那一格 —— 这一支正是漏掉那 3 个来源时的形态。
    """
    victim = "direct-proving-neural-network-functions"
    owners = [k for k, rows in AS.SURVEY.items() if victim in rows]
    assert len(owners) == 1, f"装置前提：这条来源应当只被一岗记下，实得 {owners}"
    monkeypatch.setitem(
        AS.SURVEY, owners[0], tuple(n for n in AS.SURVEY[owners[0]] if n != victim))
    covered = {n for rows in AS.SURVEY.values() for n in rows}
    assert victim not in covered, "装置自控失败：摘掉之后它还在覆盖集里"
    assert set(AS.builtin_sources()) - covered == {victim}, (
        "摘掉一条来源之后覆盖判据必须正好报出它 —— 报不出来说明这条判据是真空的")


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
    """反负控之八：正文里的 `F.step` / `data/x.json` / `main.tex` / `fs.read` 不报。

    这一条守的是上面那条判据的**另一半**：假阳性会把判据变成噪音，
    于是没人再看它。工具名的形状是"全小写组名.名"，动作是"大写角色.动作"、
    路径与文件名带斜杠或以 `.json`/`.tex` 结尾 —— 三者机器分得开。

    这里举的动作取 `F.step`（V 的出边就是 F）：**动作那一格也有判据**
    （存在 + 够得到），所以"举一个不报的例子"必须同时是一个够得到的动作，
    否则这一条会与那一条判据互相打架。
    """
    good = AS.Skill(slug="正文里的非工具点号", title="x", summary="一句话", when="任何时候",
                    body=("派 `F.step` 推进，读 `data/statements.json`、"
                          "`out/paper/main.tex` 与 `fs.read`。"),
                    tools=("fs.read",))
    monkeypatch.setitem(AS.CATALOG, "V", AS.CATALOG["V"] + (good,))
    problems = AS.validate()
    assert not [p for p in problems if "正文" in p], problems


def test_the_negative_control_catches_a_fabricated_action_only_in_the_body(monkeypatch):
    """反负控之九：**正文里**出现一个不存在的动作 ⇒ 红（业主 ④ 的正文那一半）。

    `actions` 那一格早就有这条判据了；正文没有。而模型照做的对象是正文 ——
    一句"然后调 `Z.fly_to_moon`"写在正文里，声明那一格永远看不见它。
    """
    bad = AS.Skill(slug="正文虚构动作", title="x", summary="一句话", when="任何时候",
                   body="第 1 步：调 `Z.fly_to_moon` 把结论搬过去。")
    monkeypatch.setitem(AS.CATALOG, "V", AS.CATALOG["V"] + (bad,))
    problems = AS.validate()
    assert any("Z.fly_to_moon" in p and "正文" in p for p in problems), problems


def test_the_negative_control_catches_an_unreachable_action_only_in_the_body(monkeypatch):
    """反负控之十：正文里的动作**真实存在**、但这个角色够不到 ⇒ 红。

    这一条挡的是"把别人的活写进我的操作手册"的**正文版**：
    V 的出边只有 F，正文里写"你自己去调 `A.run_once`"就是一句做不到的指令 ——
    而动作是真动作，所以只查存在性的判据会放过它。
    """
    bad = AS.Skill(slug="正文越权动作", title="x", summary="一句话", when="任何时候",
                   body="第 1 步：调 `A.run_once` 自己去检索一遍。")
    monkeypatch.setitem(AS.CATALOG, "V", AS.CATALOG["V"] + (bad,))
    problems = AS.validate()
    assert any("A.run_once" in p and "出边" in p for p in problems), problems


def test_the_cross_reference_registry_cannot_rot(monkeypatch):
    """反负控之十一：`_BODY_CROSS_REFS` 里登记的"指到别人"不成立 ⇒ 红。

    "指到别人"（"由 H 做"这类）必须在正文判据里豁免，否则判据变成噪音
    （实测真有这样的句子）。但豁免**具名**之后就会腐烂：那一句正文被删了、
    或者出边变了让它变得够得到 —— 那时这条登记就成了"看起来还在挡着什么"。
    所以登记本身也在判据里：不成立就报出来（与本仓 R010 那张假阳性表的纪律同源）。
    """
    monkeypatch.setitem(AS._BODY_CROSS_REFS, ("V", "复核-三态并指到那一步", "A.run_once"),
                        "（负面夹具）这一条不成立：那一句正文里没有它")
    problems = AS.validate()
    assert any("_BODY_CROSS_REFS" in p and "已经不成立" in p for p in problems), problems


def test_the_manuscript_path_is_named_identically_in_the_spec_and_the_skill():
    """业主 2026-10-14 第 1 / 2 条那两个落点：**两处必须写得一模一样**。

    研究手稿 `reports/RESEARCH.md`（D 的）与攻坚台账 `reports/attack-<plan_id>.md`（F 的）
    各出现在两个地方：角色的**声明**（`specs/<角色>.py` 的 policy，进前置提示词 ——
    因为它必须每一趟都生效）与那份**按需读**的 skill（写细节）。

    两处写岔的表现是最难查的那一种：提示词说 `reports/RESEARCH.md`、
    skill 说 `reports/research.md`，而**两边都自洽**（模型读哪个都可能），
    盘上于是出现两份手稿、各自都"像是对的"。
    """
    import re

    from agentflow import specs as SP

    pairs = (
        ("D", "手稿-研究记忆就这一份", "reports/RESEARCH.md"),
        ("F", "推进-中间成果一处一条", "reports/attack-<plan_id>.md"),
    )
    #: 这一族里**允许**出现的落点：手稿、攻坚台账、D 的自动渲染工作稿。
    #: 别的拼法（大小写不同、多了个横线）一律报 —— 那正是"盘上出现两份手稿"的开端。
    allowed = {"reports/RESEARCH.md", "reports/attack-<plan_id>.md", "reports/<qid>-research.md"}
    found_re = re.compile(r"reports/[A-Za-z0-9_<>\-]+\.md")
    specs = SP.builtin_specs()
    for role, slug, path in pairs:
        skill = next(s for s in AS.CATALOG[role] if s.slug == slug)
        policy = "\n".join(specs[role].brief.policy)
        assert path in policy, f"{role} 的声明里没有那个落点：{path}"
        assert path in skill.body, f"{role}/{slug} 的正文里没有那个落点：{path}"
        for label, text in (("声明", policy), ("skill 正文", skill.body)):
            found = set(found_re.findall(text))
            extra = found - allowed
            assert not extra, f"{role}/{slug} 的{label}里出现了没登记的落点：{sorted(extra)}"


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


def test_the_negative_control_catches_a_path_under_no_registered_root(monkeypatch):
    """反负控之十二：正文点名一个**没人写的落点** ⇒ 红。

    缺陷形态：一条 skill 说"去 `foo/report.md` 读结论"，而**没有任何东西会产出那个文件** ——
    读的人找不到，写的人也没错，两边都不报错。所以落点必须落在登记过的根下
    （`WORKSPACE_PATH_ROOTS` / `REPO_PATH_ROOTS`），加新落点时同时加进那张表。
    """
    bad = AS.Skill(slug="点名野落点", title="x", summary="一句话", when="任何时候",
                   body="第 1 步：去 `foo/report.md` 读上一趟的结论。", tools=("fs.read",))
    monkeypatch.setitem(AS.CATALOG, "V", AS.CATALOG["V"] + (bad,))
    problems = AS.validate()
    assert any("foo/report.md" in p and "根下" in p for p in problems), problems


def test_the_path_scan_does_not_fire_on_vocabulary_or_bare_filenames(monkeypatch):
    """反负控之十三：`heuristic/inconclusive`（词表取值）与裸文件名**不**报。

    这一条守的是上面那条判据的**另一半**（R120 实测踩到的假阳性）：
    第一版只按"带目录"判，于是证据等级的词表取值 `heuristic/inconclusive` 被报成"野落点" ——
    而它根本不是路径。假阳性会让判据变成噪音，然后没人再看它。
    口径因此收成"**带已知后缀**或**结尾是 `/`**"，并配这条负控守着。
    """
    good = AS.Skill(slug="词表与裸名", title="x", summary="一句话", when="任何时候",
                    body=("证据等级落在 `heuristic/inconclusive` 那一档；"
                          "产物是 `out/paper/main.tex` 与同一目录下的 `main.pdf`。"),
                    tools=("fs.read",))
    monkeypatch.setitem(AS.CATALOG, "V", AS.CATALOG["V"] + (good,))
    problems = AS.validate()
    assert not [p for p in problems if "根下" in p], problems


def test_the_registered_roots_cover_the_paths_we_actually_name():
    """反真空：那张根表不是摆设 —— 现算一遍"文本里到底点了哪些落点"，逐个都在表里。

    没有这一条，"根表"可以是一张只写着 `out/` 的空表而判据照样绿：
    判据查的是"点名的路径在不在表里"，表越小、能点名的就越少，但那不说明覆盖到了我们的真实落点。
    """
    import re as _re

    pat = _re.compile(r"`([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.<>*\-]+)+/?)`")
    seen: list[str] = []
    for rows in AS.CATALOG.values():
        for s in rows:
            seen += [t for t in set(pat.findall(s.body)) if AS._looks_like_a_path(t)]
    from agentflow import specs as SP

    for role, spec in SP.builtin_specs().items():
        brief = spec.brief
        text = "\n".join(brief.policy) + "\n" + "\n".join(brief.boundary) + "\n" + str(brief.deliverable)
        seen += [t for t in set(pat.findall(text)) if AS._looks_like_a_path(t)]
    assert len(set(seen)) >= 15, f"只认得出 {len(set(seen))} 个落点 ⇒ 判据的扫描面可能坏了"
    outside = sorted({t for t in seen if not t.startswith(tuple(AS.PATH_ROOTS))})
    assert not outside, f"这些落点不在根表里：{outside}"
    # 表本身就是两张子表的并集（不许有人另写第三张）
    assert set(AS.PATH_ROOTS) == set(AS.WORKSPACE_PATH_ROOTS) | set(AS.REPO_PATH_ROOTS)


def test_the_index_says_to_read_it_now_and_says_why():
    """索引里必须有一句**祈使**（"对上了就现在读"）与**理由**（手册给的是步骤与反面形态）。

    为什么判这一句（2026-10-14 真机读数）：两次真跑（3 次与 16 次模型调用）里，
    索引在提示词里、`skills/` 也落了盘，而**正文一次都没被读过** ——
    模型凭提示词里的口径就把活干完了。行为判不了（那是模型的自由），
    但"有没有把这个选择讲清楚"判得了：提示词只给口径（每一格都要成立），
    手册给的是**这一档的具体步骤与反面形态** —— 这一句就是把那个差别说出来。

    与它配对的那条判据（索引里不许出现正文）仍然守着另一头：
    这一句是**祈使**，不是把正文抄进来。
    """
    block = AS.index_block("M")
    assert "对上了就现在读" in block, block[:300]
    assert "具体步骤" in block and "反面形态" in block, block[:300]
    # 反真空：每个角色的索引里都有这一句（不是只给 M 开了小灶）
    for role in ("A", "B", "C", "D", "E", "F", "G", "H", "M", "V"):
        assert "对上了就现在读" in AS.index_block(role), role


def test_the_manuscript_sections_are_enumerated_once_and_identically():
    """研究手稿的分节**只许有一处枚举**：D 的声明与 skill 里那七个名字必须一模一样。

    2026-10-14 真机读数：两趟真跑里，一趟手稿以 `## 成果概述` 开头，另一趟直接从
    「定义与已知」开头。原因在**两处枚举不一致** —— 声明里正文写着「六个分节」并逐个列名
    （不含成果概述），而「开头要有成果概述」另起一句写在后面；模型两次各采用了一个。
    现在两处都是七节、成果概述在第一位，这条判据守着它不再分岔。
    """
    from agentflow import specs as SP

    NAMES = ("成果概述", "定义与已知", "已确定的结论", "尝试与失败", "例子与反例",
             "未解问题", "下一步")
    policy = "\n".join(SP.builtin_specs()["D"].brief.policy)
    skill = next(s for s in AS.CATALOG["D"] if s.slug == "手稿-研究记忆就这一份")
    for label, text in (("声明", policy), ("skill 正文", skill.body)):
        missing = [n for n in NAMES if n not in text]
        assert not missing, f"D 的{label}里少了这些节：{missing}"
    assert "七节" in policy or "七节" in skill.body, "没有一处写明是七节 ⇒ 数不出来"
    # 反真空：声明里不许再出现"六个分节"这种旧枚举（那正是分岔的来源）
    assert "六个分节" not in policy, "声明里还留着旧的「六个分节」枚举"


def test_the_skills_tool_surface_equals_the_surface_the_prompt_renders() -> None:
    """**两个工具面必须是同一个**（2026-10-16 复查十个协作面时发现的一处不一致）。

    ## 发现（为什么值得单独一条判据）

    `_role_tool_surface()` 是 `validate()` 第三条硬约束的基准面（"一条 skill 正文里点名的工具
    必须在本角色的工具面上"）。它原先建注册表时给了 `workspace_root` 却**没给 `store`** ——
    而它自己的 docstring 第 1 点**正引着** `secretary.py` 那条读数（"**不带 `store`** 出 68 件、
    `fs.read` 不在里面；带上出 81 件、在里面"）。也就是说：**文档知道 store 要紧，实现漏了它。**

    实测差异（同一台机、同一份代码，逐角色比对）：

    | 角色 | 技能模块的面 | 提示词渲染的面 |
    |---|---|---|
    | 其余九格 | 相同 | 相同 |
    | **D** | **36** | **41** |

    差的 5 件逐字是 `research.list_gaps` / `research.poll_waiting` / `research.set_status` /
    `research.submit_gap` / `research.write_note`（全是只有 D 用的那些）。

    ## 为什么这是缺陷而不是"更严一点"

    模型看到的是**带 store 的那一面**（`tools_lines(role, registry)` 读宿主的注册器）。
    判据查另一个面 ⇒ 一条 D 的手册只要正经点名 `research.set_status`，就会被报成
    "不在你的工具面上" —— **假阳性**，而假阳性会让人开始不信这份判据（与 docstring 第 1 点
    的论证同型）。今天没有手册提到 `research.*`，所以它是**潜伏**的；这条判据让它不再潜伏。

    ## 反真空

    两侧都必须非空且**件数 ≥ 10**：两个空表也会"相等"，而那是"没查成"。
    """
    from agentflow.store import Store
    from agentflow.tools import build_registry

    problems: list[str] = []
    skills_surface = AS._role_tool_surface(problems)
    assert not problems, f"技能模块的工具面这一格没查成：{problems}"

    root = tmp_path_root()
    store = Store(root)
    store.init()
    registry = build_registry(store=store, workspace_root=root).registry

    checked = 0
    for role, names in sorted(skills_surface.items()):
        rendered = {spec.name for spec in registry.for_role(role)}
        assert len(names) >= 10 and len(rendered) >= 10, (
            f"{role} 的工具面太小（技能面 {len(names)} / 渲染面 {len(rendered)}）⇒ "
            "先解释清楚是不是装配坏了，再改这条下限"
        )
        assert names == rendered, (
            f"{role} 的两个工具面不是同一个：只有技能面有 {sorted(names - rendered)}；"
            f"只有渲染面有 {sorted(rendered - names)} —— 判据查的面必须与模型看到的面相同"
        )
        checked += 1
    assert checked >= 10, f"只比了 {checked} 个角色（下限 10）"


def tmp_path_root():
    """给上面那条判据造一个干净的工作区根（`Store` 要一个能写的目录）。"""
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp(prefix="agentflow-skills-surface-test-"))
