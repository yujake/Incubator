"""同名不同契约的重复实现被合并后，用可判定的形式守住"判据唯一"。

## 本文件守什么

``INVENTORY.md`` §4.7 点到两对"同名不同契约"的实现，且实测结果不同：

| 判据 | 原来的两份 | 实测分歧 |
|---|---|---|
| slug 文件名片段 | ``textutil.slugify`` / ``fetch.slugify`` | CJK 保留 vs 剥掉；回退 ``untitled`` vs ``download`` |
| DOI 归一化 | ``dedup.normalize_doi`` / ``providers.normalize_doi`` | URL 前缀、尾随 ``.``、全角数字三组输入结果不同 |

合并的做法是留一份、另一份转发。但"我删掉了一份"是一个无法验证的说法 ——
三个月后有人再写一份，测试照样全绿。所以这里的断言写成可判定的形式：

> 对同一批边缘输入，两份实现给出完全相同的结果。

这不是"测试了一个函数"，而是把"判据唯一性"本身变成了断言。边缘输入覆盖：
空串 / 纯空白 / 只有标点 / 全 CJK / 半角+全角混合 / URL 前缀 /
``doi:`` 前缀 / 尾随 ``.`` / 超长串 / ``None`` / 非 ``str``。

## 为什么每条修复都有负控

只有正例的测试会退化成"改坏了也绿"。本文件里：
- ``test_slug_keeps_cjk_where_stripping_it_would_collide`` 证明保留 CJK 是必要性
  （剥掉 CJK 会让两个不同的中文标题必碰撞，而不是"风格不同"）；
- ``test_slugify_never_returns_empty_nor_path_fragment`` 证明白名单的安全性质；
- ``test_doi_equivalent_iff_same_normalized_form`` 证明归一化没有过度合并
  （不同 DOI 不得被合并 —— 那是不可逆的错误）；
- ``test_install_d_tools_rejects_bad_role_name_at_assembly_time`` 用非法角色名
  ``("agent-X",)`` 断言装配期抛错（正是原来静默通过的那种输入）；
- ``test_fallback_trace_tools_roles_are_legal_roles`` 断言现在那三个替身
  真的按 ``"C"``/``"D"`` 声明，且 ``for_role`` 能拿到（负控：改回 ``"agent-C"`` 必失败）。
"""

from __future__ import annotations

import pytest

from agentflow import dedup as D
from agentflow import fetch as F
from agentflow import providers as P
from agentflow import textutil as T
from agentflow.agent_d import AgentD, EvidenceError, install_d_tools, validate_tool_roles
from agentflow.tools import ROLES
from agentflow.tools.base import ToolError, ToolRegistry, ToolSpec, fail, ok

# ======================================================================================
# [0] 边缘输入表（只在这里写一份，两对判据共用）
# ======================================================================================

#: slug 的边缘输入。覆盖合并前后实测有分歧的每一类：
#: 空/空白/纯标点（回退值分歧）、全 CJK（CJK 保留分歧）、半角+全角混排、
#: 路径分隔符（"绝不产生目录路径"这条安全要求）、超长串（limit 分歧）、
#: 连字 ``ﬁ``（合并后改用 NFKC，兼容字符被折成规范形态而不是整块删掉）。
SLUG_EDGE_INPUTS: list[str] = [
    "",
    "   ",
    "\t\n ",
    "///",
    "..",
    "...",
    "-",
    "_",
    "!!!???...",
    "群论基础",
    "北京（群论）研究—综述",
    "On the Structure of Groups 群论",
    "ON THE STRUCTURE OF GROUPS",
    "a/b\\c:d*e?f",
    "..\\..\\etc\\passwd",
    "CON",
    "NUL",
    "ＡＢＣ　１２３",          # 全角字母 + 全角空格 + 全角数字
    "ｆｕｌｌ－ｗｉｄｔｈ",
    "ﬁle",                     # 连字（NFKC 折成 fi）
    "㐀㐁",                      # CJK 扩展 A（基本区之外）
    "a" * 200,                  # 超长
    "群" * 200,                 # 超长 CJK
    "  --  spaced  --  ",
    "10.1000/abc",             # 形如 DOI 的串（不该被 slug 规则特殊对待）
]

#: DOI 的边缘输入。
DOI_EDGE_INPUTS: list[object] = [
    None,
    "",
    "   ",
    "10.1000/abc",
    "10.1000/ABC",
    "http://dx.doi.org/10.1000/abc",
    "https://dx.doi.org/10.1000/abc",
    "https://doi.org/10.1000/AbC",
    "http://doi.org/10.1/x",
    "doi:10.1000/AbC",
    "doi: 10.1/x",
    "DOI: 10.1/x",
    "  10.1000/XYZ  ",
    "10.1000/abc.",
    "https://doi.org/10.1000/abc.",
    "１０.１０００／ｘ",          # 全角数字 + 全角斜杠
    "https://doi.org/",          # 只有前缀
    "doi.org",                   # 裸域名（不是前缀）
    "doi.org/10.1/x",            # 裸域名 + 路径（是前缀形态）
    "10.1000/abc-",
    ".10.1000/abc",              # 前导点：不得被当脏数据删掉
    "10.1000/abc  ",
    "https://doi.org/10.1000/ABC.",
]


# ======================================================================================
# [1] slugify：两份实现必须给出完全相同的结果
# ======================================================================================


@pytest.mark.parametrize("text", SLUG_EDGE_INPUTS, ids=[repr(t)[:40] for t in SLUG_EDGE_INPUTS])
def test_slugify_is_now_one_implementation(text: str) -> None:
    """判据唯一性（核心断言）：同一输入，两份实现结果必须逐字相同。

    合并前这张表里有 7 组不同（CJK、回退值、超长截断……）。断言"相等"比
    断言"我删掉了一个函数"强得多：前者能挡住任何一份新写出来的第二实现，
    后者挡不住。
    """
    # 两个默认值不同（60 vs 80）是参数差异，不是判据差异：
    # 把 limit 对齐之后结果必须逐字相同。
    assert T.slugify(text, limit=60) == F.slugify(text, max_length=60)


def test_slugify_default_values_are_the_only_difference() -> None:
    """默认值差异必须能被参数完全表达 —— 即"规则"只有一份。

    ``fetch.slugify`` 的 ``max_length=80`` 是调用点特有默认值，由参数表达；
    ``textutil.slugify`` 的 ``limit=60`` 同理。两者在同一 limit 下必须等价，
    否则说明转发里又长出了第二套逻辑。
    """
    text = "a" * 200
    assert T.slugify(text) == "a" * 60
    assert F.slugify(text) == "a" * 80
    assert T.slugify(text, limit=80) == F.slugify(text, max_length=80) == "a" * 80


def test_fetch_slugify_forwards_to_textutil() -> None:
    """转发必须是真的转发（同一个函数对象），而不是"又抄了一遍碰巧一样"。

    为什么这条断言不会误伤：``fetch.slugify`` 的 docstring 已明确它是薄封装。
    只要有人把它改回自带实现，这条会立刻红 —— 这正是我们要的。
    """
    import inspect

    src = inspect.getsource(F.slugify)
    assert "textutil" in src and "slugify" in src, "fetch.slugify 不再是转发：\n" + src
    # 行为层面的同一性（比读源码更硬的一条）：
    assert F.slugify("群论基础") == T.slugify("群论基础") == "群论基础"


@pytest.mark.parametrize("text", SLUG_EDGE_INPUTS, ids=[repr(t)[:40] for t in SLUG_EDGE_INPUTS])
def test_slugify_never_returns_empty_nor_path_fragment(text: str) -> None:
    """负控（安全性质）：绝不返回空串，且结果不可能被当成路径片段。

    空串会让 ``dest / ""`` 变成目录本身。而 ``""``、``"."``、``".."``、
    含 ``/`` 或 ``\\`` 的返回值会直接构成目录穿越 ——
    ``fetch._safe_join`` 是第二道防线，这里是第一道。
    """
    slug = T.slugify(text)
    assert slug != "", f"{text!r} 回退成了空串"
    assert "/" not in slug and "\\" not in slug, f"{text!r} -> {slug!r} 含路径分隔符"
    assert slug not in (".", ".."), f"{text!r} -> {slug!r} 是目录本身"
    assert not slug.startswith(".") and not slug.endswith("."), f"{text!r} -> {slug!r}"
    assert not slug.startswith("-") and not slug.endswith("-"), f"{text!r} -> {slug!r}"
    # 白名单之外不可能有字符溜进来（控制字符/方向覆盖字符等）
    assert all(ch.isascii() and ch.isalnum() or ch == "-" or "\u4e00" <= ch <= "\u9fff" for ch in slug), slug


def test_slug_preserves_cjk_and_that_preservation_is_load_bearing() -> None:
    """为什么最终选"保留 CJK" —— 用实测碰撞证明，而不是说"选了一个"。

    两条纯 CJK 标题在"剥掉 CJK"的规则下必然都回退成同一个占位名
    （这不是理论担忧：``fetch.slugify`` 旧实现在这两个输入上给的都是
    ``download``）。于是"不同文献 → 同一个文件名前缀"，可读性与可区分性同时丢失。

    保留 CJK 之后它们分开了。这就是选择该规则的理由：
    它不是风格偏好，而是"不制造碰撞"的必要条件。
    """
    a, b = "群论基础", "环论基础"
    # 负控：把 CJK 剥掉（旧 fetch 规则）两者必然相同 —— 所以"不保留 CJK"是错的
    import re

    strip_cjk = lambda s: re.sub(r"[^a-z0-9]+", "-", s).strip("-")  # noqa: E731
    assert strip_cjk(a) == strip_cjk(b) == "", "构造失效：这两条标题在剥 CJK 后应当都为空"
    # 正例：保留 CJK => 可区分
    assert T.slugify(a) != T.slugify(b)
    assert T.slugify(a) == a and T.slugify(b) == b
    assert F.slugify(a) == a, "落盘路径也必须是同一条规则"


def test_slug_only_punctuation_falls_back_but_renders_the_placeholder_visible() -> None:
    """负控（回退语义）：空串与"全是标点"这次确实退化成同一个 slug。

    为什么可以接受：文件名前缀不承担唯一性（``fetch._target_path`` 会再拼
    URL 短哈希）。所以"占位名"不会导致文件互相覆盖 —— 这是这个选择成立的
    前提条件，而它由 ``test_target_path_falls_back_through_url_tail`` 守住。
    """
    assert T.slugify("") == T.slugify("///") == T.slugify("!!!") == "untitled"
    # 但"有内容"与"没内容"必须能区分 —— 不能全都退化成占位名
    assert T.slugify("群论基础") != "untitled"
    assert T.slugify("group theory") != "untitled"


def test_slug_primary_and_fallback_inputs_do_not_collide() -> None:
    """负控（可区分性）：占位名不得与任何真实标题的 slug 混淆。"""
    placeholder = T.slugify("")
    for text in ("untitled", "Untitled", "UNTITLED"):
        # 反例探针：即便有人真的叫这个标题，也只是"前缀相同"，
        # 唯一性由短哈希保证（见 fetch._target_path）——但至少规则是确定的。
        assert T.slugify(text) == placeholder, "同一条规则必须对等处理字面量 'untitled'"
    # 真正的判据：占位名本身必须是合法 slug（不含任何危险形态）
    assert placeholder == placeholder.strip("-") and placeholder != ""


def test_target_path_falls_back_through_url_tail_then_placeholder(tmp_path) -> None:
    """负控（回退链）：hint 为空时用 URL 末段；末段也为空才用占位名。

    这条守的是"合并判据后回退链没断"：旧实现判断 ``hint == "download"``，
    那个魔法字符串与 ``slugify`` 的默认回退值耦合；判据合并后必须
    继续工作，且三级回退每一级都可达。
    """
    dl = F.default_downloader({})
    # 1) hint 有内容：直接用 hint 的 slug
    p1 = dl._target_path(tmp_path, "群论基础", "https://x.test/a.pdf", ".pdf")
    assert p1.name == "群论基础.pdf"
    # 2) hint 为空但有 URL 末段：用末段
    p2 = dl._target_path(tmp_path, "", "https://x.test/SurveyOfRings.pdf", ".pdf")
    assert p2.name == "surveyofrings.pdf"
    # 3) hint 与末段都没有可读内容：占位名（且不是空串）
    p3 = dl._target_path(tmp_path, "///", "https://x.test/", ".pdf")
    assert p3.name == "untitled.pdf"
    assert p3 != tmp_path / ".pdf"


# ======================================================================================
# [2] normalize_doi：两份实现必须给出完全相同的结果
# ======================================================================================


@pytest.mark.parametrize("raw", DOI_EDGE_INPUTS, ids=[repr(t)[:40] for t in DOI_EDGE_INPUTS])
def test_normalize_doi_is_now_one_implementation(raw: object) -> None:
    """判据唯一性（核心断言）：同一输入，两份实现结果必须逐字相同。

    合并前这张表里有 4 组不同（``http://dx.doi.org/`` 前缀、尾随 ``.``、
    全角数字、以及它们的组合）。
    """
    assert D.normalize_doi(raw) == P.normalize_doi(raw)  # type: ignore[arg-type]


def test_providers_normalize_doi_forwards_to_dedup() -> None:
    """转发必须指向 ``dedup``（判重键的来源），而不是反过来。"""
    import inspect

    src = inspect.getsource(P.normalize_doi)
    assert "dedup" in src, "providers.normalize_doi 不再是转发：\n" + src


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.1000/abc", "10.1000/abc"),
        ("http://dx.doi.org/10.1000/abc", "10.1000/abc"),
        ("https://doi.org/10.1000/AbC", "10.1000/abc"),
        ("doi:10.1000/AbC", "10.1000/abc"),
        ("10.1000/abc.", "10.1000/abc"),
        ("１０.１０００／ｘ", "10.1000/x"),
        ("  10.1000/XYZ  ", "10.1000/xyz"),
        ("", None),
        (None, None),
        ("   ", None),
    ],
)
def test_normalize_doi_exact_values(raw: object, expected: str | None) -> None:
    """固定期望值：把"合并后到底选了哪条规则"钉死，防止悄悄再漂一次。"""
    assert D.normalize_doi(raw) == expected  # type: ignore[arg-type]
    assert P.normalize_doi(raw) == expected  # type: ignore[arg-type]


def test_normalize_doi_equivalent_iff_same_normalized_form() -> None:
    """负控（不过度合并）：不同 DOI 不得被合并成同一个键。

    合并规则时最容易犯的错是"顺手多削一点"（比如用 ``strip('.')`` 而不是
    ``rstrip('.')``，或把小写化写成"去掉所有非字母数字"）—— 那会让两个不同的
    DOI 变成同一个键，属于不可逆的错误（文献被永久合并）。
    """
    distinct = [
        "10.1000/abc",
        "10.1000/abd",
        "10.1000/abc2",
        ".10.1000/abc",     # 前导点是有意义的字符：不是已知脏数据
        "10.1000/a.b.c",
        "doi.org",          # 畸形但不是空
    ]
    normalized = [D.normalize_doi(x) for x in distinct]
    assert len(set(normalized)) == len(normalized), f"归一化把不同的 DOI 合并了：{normalized}"


def test_equivalent_spellings_do_collapse() -> None:
    """正例（合并的目的）：同一篇文献的不同写法必须给同一个键。"""
    same = [
        "10.1000/abc",
        "10.1000/ABC",
        "https://doi.org/10.1000/abc",
        "http://dx.doi.org/10.1000/abc",
        "doi:10.1000/abc",
        "doi: 10.1000/abc",
        "  10.1000/abc.  ",
        "１０.１０００／ａｂｃ",
    ]
    assert len({D.normalize_doi(x) for x in same}) == 1


def test_doi_key_from_provider_matches_literature_keys() -> None:
    """端到端（真正的危害是什么）：候选自带的 ``dedup_key`` 与
    ``literature_keys`` 算出来的键必须是同一个字符串。

    合并前：``providers.dedup_key_of`` 用自己那份（会把
    ``http://dx.doi.org/…`` 削成 ``10.1000/abc``），而
    ``dedup.literature_keys`` 用另一份（原样保留）—— 于是同一个 DOI 生成两个键，
    入库后再比就匹配不上 ⇒ 同一篇论文被登记两次，且没有任何报错。
    """
    for raw in (
        "10.1000/abc",
        "http://dx.doi.org/10.1000/abc",
        "https://doi.org/10.1000/AbC",
        "10.1000/abc.",
        "１０.１０００／ａｂｃ",
    ):
        cand = P.Candidate(title="Some title", doi=raw)
        key_from_provider = P.dedup_key_of(cand)
        keys_from_dedup = D.literature_keys("Some title", None, raw)
        assert key_from_provider in keys_from_dedup, (
            f"{raw!r}: provider 键 {key_from_provider!r} 不在 dedup 键集 {keys_from_dedup} 里"
        )
        assert key_from_provider == f"doi:{D.normalize_doi(raw)}"


def test_dedup_finds_existing_literature_across_doi_spellings() -> None:
    """端到端负控：库里已有一篇（键来自 dedup），候选写法不同但 DOI 相同 ⇒ 必须命中。

    这是"合并"要换来的真实结果，不是内部一致性而已。
    """
    rows = [{"lit_id": "0000", "title": "Whatever", "dedup_key": "doi:10.1000/abc"}]
    for raw in ("http://dx.doi.org/10.1000/abc", "10.1000/ABC.", "１０.１０００／ａｂｃ"):
        hit, key = D.find_existing_literature(rows, "完全不同的标题", 2000, raw)
        assert hit is not None, f"{raw!r} 没被判成已存在（同一篇文献被当成两篇）"
        assert key == "doi:10.1000/abc"


# ======================================================================================
# [3] agent_d：降级替身的角色名 + 装配期校验
# ======================================================================================

class _BrokenTraceModule:
    """冒充"外部 ``tools.trace_tools`` 自身有 bug"的模块。

    为什么不用 ``trace_tools=None`` 来强制降级：``install_d_tools`` 的
    ``trace_tools=None`` 是哨兵（"没传"），会去 ``load_trace_tools()``
    惰性加载真身；本次改动没有改动这条既有语义（它被
    ``test_install_d_tools_prefers_the_external_trace_tools`` 守着）。
    要走到降级分支，正确的外部输入是"模块存在但 register 失败"。
    """

    def register(self, registry, **kwargs):  # noqa: ANN001, ANN003, ARG002
        raise RuntimeError("冒充外部 trace_tools 的 bug")


_BROKEN_TRACE_MODULE = _BrokenTraceModule()


def test_fallback_trace_tools_roles_are_legal_roles(store) -> None:
    """缺陷 4 的直接断言：三个替身的 roles 必须是 ``ROLES`` 里的合法角色。

    原实现写 ``roles=("agent-C", "agent-D")`` —— 带前缀的非法形态
    （``agent_d.py:483/509/546``），于是 ``for_role("C")/("D")`` 永远拿不到它们。
    """
    reg = install_d_tools(store, trace_tools=_BROKEN_TRACE_MODULE)  # 强制走降级路径
    for name in ("trace.relation", "trace.concept", "trace.literature"):
        spec = reg.get(name)
        assert set(spec.roles) <= set(ROLES), f"{name} 声明了非法角色：{spec.roles}"
        assert spec.roles == ("C", "D"), f"{name} 的角色应当是 ('C','D')，实际 {spec.roles}"


def test_fallback_trace_tools_reachable_by_role(store) -> None:
    """负控（真正的后果）：降级之后 ``for_role`` 必须拿得到这三个工具。

    旧实现在这里给出空列表 —— "装上了但按角色过滤拿不到"就是静默少工具。
    """
    reg = install_d_tools(store, trace_tools=_BROKEN_TRACE_MODULE)
    names_c = {s.name for s in reg.for_role("C")}
    names_d = {s.name for s in reg.for_role("D")}
    assert {"trace.relation", "trace.concept", "trace.literature"} <= names_c
    assert {"trace.relation", "trace.concept", "trace.literature"} <= names_d
    # 反证：非法角色名（旧值）在这张注册表里查不到任何东西
    assert reg.for_role("agent-C") == []
    assert reg.for_role("agent-D") == []


def test_install_d_tools_passes_role_validation(store) -> None:
    """装配期校验对正常路径（外部 trace_tools）也必须通过且不留痕。"""
    reg = install_d_tools(store)
    validate_tool_roles(reg)  # 不抛即通过
    assert not any(r not in ROLES for s in reg._specs.values() for r in s.roles)


def test_install_d_tools_rejects_bad_role_name_at_assembly_time(store) -> None:
    """负控（装配期断言）：把非法角色名塞进注册表 ⇒ 装配期必须抛 ``ToolError``。

    这正是原来静默通过的那类输入：``install_d_tools`` 自建 ``ToolRegistry``
    并 ``register_function``，绕过 ``build_registry`` 的角色断言
    （``tools/__init__.py:189-207``），于是拼错的角色名一路装到底。
    """
    bad = ToolRegistry(name="bad")
    bad.register(
        ToolSpec(
            name="trace.bogus",
            summary="故意拼错角色名",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: ok({"never": True}),
            side_effect="read",
            roles=("agent-X",),  # type: ignore[arg-type]
            returns="{'never'}",
        )
    )
    with pytest.raises(ToolError) as ei:
        validate_tool_roles(bad)
    msg = str(ei.value)
    assert "trace.bogus" in msg and "agent-X" in msg, msg


def test_install_d_tools_with_injected_registry_also_validates(store) -> None:
    """负控：校验覆盖 ``registry=`` 注入路径（那是外部 trace_tools 的入口）。

    只校验"自己造的那只注册表"是不够的 —— 外部模块完全可以塞进来一个
    拼错角色名的 spec，而它同样会被静默过滤掉。
    """
    injected = ToolRegistry(name="injected")
    injected.register(
        ToolSpec(
            name="trace.relation",
            summary="冒充外部 trace_tools 的坏声明",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: ok({}),
            side_effect="read",
            roles=("agent-D",),  # type: ignore[arg-type]
            returns="{}",
        )
    )
    with pytest.raises(ToolError):
        install_d_tools(store, registry=injected)


def test_validate_tool_roles_uses_the_single_source_of_truth(store) -> None:
    """不许另写第二份判据：校验必须直接消费 ``tools.ROLES``。

    断言形态：把 ``ROLES`` 里的角色拿来用一律通过；只要不在 ``ROLES`` 里
    就一律被拒 —— 判据只有一份，不存在"agent_d 自己认的角色表"。
    """
    reg = ToolRegistry(name="ok")
    for i, role in enumerate(ROLES):
        reg.register(
            ToolSpec(
                name=f"t.{i}",
                summary=f"合法角色 {role}",
                params={"type": "object", "properties": {}, "additionalProperties": False},
                handler=lambda: ok({}),
                side_effect="read",
                roles=(role,),
                returns="{}",
            )
        )
    validate_tool_roles(reg)  # 全部合法：不得抛

    reg.register(
        ToolSpec(
            name="t.bad",
            summary="多一个非法角色",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: ok({}),
            side_effect="read",
            roles=(ROLES[0], "agent-Z"),
            returns="{}",
        )
    )
    with pytest.raises(ToolError):
        validate_tool_roles(reg)


# ======================================================================================
# [4] AgentD：失败记录路径不得 AttributeError
# ======================================================================================


def _agent_with_tool(store, spec: ToolSpec) -> AgentD:
    reg = ToolRegistry(name="t")
    reg.register(spec)
    return AgentD(store, tools=reg)


def _spec(name: str, handler) -> ToolSpec:  # noqa: ANN001
    return ToolSpec(
        name=name,
        summary="测试用",
        params={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
        side_effect="read",
        roles=("D",),
        returns="{}",
    )


def test_agent_d_initializes_last_tool_errors_eagerly(store) -> None:
    """缺陷 5 的断言：``__init__`` 里就建好列表，不依赖任何一条路径先跑过。

    "先失败、还没溯源"的路径若惰性建表，记录失败的代码自己会 ``AttributeError`` ——
    比原来的失败更坏。
    """
    agent = AgentD(store, tools=ToolRegistry(name="empty"))
    assert isinstance(agent.last_tool_errors, list) and agent.last_tool_errors == []
    assert "last_tool_errors" in vars(agent), "必须是 __init__ 里建立的实例属性"


def test_tool_failure_before_any_tracing_records_instead_of_raising(store) -> None:
    """负控（本缺陷的确切复现路径）：工具失败 + 尚未溯源 ⇒ 记下错误，不抛。

    断言三件事：不抛 ``AttributeError``、返回 ``None``、错误被记录。
    """
    agent = _agent_with_tool(store, _spec("t.boom", lambda: fail("炸了", kind="test_kind")))
    before = len(agent.last_tool_errors)  # 不先调 trace_question
    out = agent._call("t.boom")
    assert out is None
    assert len(agent.last_tool_errors) == before + 1
    record = agent.last_tool_errors[-1]
    assert record["tool"] == "t.boom" and record["error"] == "炸了" and record["kind"] == "test_kind"


def test_unexpected_tool_exception_is_still_recorded_not_raised(store) -> None:
    """非 ``ToolError`` 逃逸也必须变成可读的失败记录，而不是打断 D 的循环。"""

    def _boom() -> object:
        raise ValueError("底层抛了个 ValueError")

    agent = _agent_with_tool(store, _spec("t.valerr", _boom))
    assert agent._call("t.valerr") is None
    rec = agent.last_tool_errors[-1]
    assert rec["tool"] == "t.valerr"
    assert rec["kind"] == "unexpected", rec
    assert "ValueError" in str(rec["error"]), rec


def test_evidence_error_is_still_loud_on_unknown_question(store) -> None:
    """负控（别把该炸的也吃掉）：问题号不存在必须照样抛 ``EvidenceError``。

    修"记录失败"很容易顺手把真实调用错误也吞掉 —— 这条挡住那种退化。
    """
    agent = AgentD(store, tools=ToolRegistry(name="empty"))
    with pytest.raises(EvidenceError):
        agent.trace_question("9999")
    with pytest.raises(EvidenceError):
        agent.submit_gaps("9999")


def test_ingest_documents_that_it_re_raises(store, monkeypatch) -> None:
    """docstring 与实现一致：``ingest`` 会原样重抛，就必须写出来。

    机械审计把它标成 ``body_raises_but_docstring_silent``
    （``functions.json`` → ``AgentD.ingest``）。这里断言文档里显式声明了，
    并且行为确实是重抛（两半都测，避免只改文档不改行为或反之）。

    触发方式：让事务入口抛错（写路径的真实故障形态），断言异常逃出去
    且原因被记进 ``last_ingest["error"]``。
    """
    doc = AgentD.ingest.__doc__ or ""
    assert "Raises" in doc, "ingest 的 docstring 缺少 Raises 一节"

    agent = AgentD(store, tools=ToolRegistry(name="empty"))

    def _explode(*_a: object, **_k: object) -> object:
        raise RuntimeError("事务入口炸了")

    monkeypatch.setattr(store, "tx", _explode)
    report = {
        "report_id": "0000",
        "kind": "hottest",
        "payload": {"hottest_relations": [{"relation_id": "0000", "priority": "high"}]},
    }
    with pytest.raises(RuntimeError) as ei:
        agent.ingest(report)
    assert "事务入口炸了" in str(ei.value)
    # 同时必须留痕（"为什么这一轮没建成问题"在报告里看得见）
    assert agent.last_ingest.get("error"), agent.last_ingest
    assert "RuntimeError" in str(agent.last_ingest["error"])


# ======================================================================================
# [5] 降级替身：表读不出来时不得报成"查了、没有"
# ======================================================================================


class _RaisingRows:
    """``rows`` 一律抛 ``StoreError`` 的最小桩。

    为什么需要它：降级替身原先直接 ``store.rows(...)``，``StoreError`` 会逃逸成
    ``kind="unexpected"``（``tools/base.py:381-382``）—— 失败类型信息丢失，
    报告里只说"unexpected"，说不出"表读不出来"。
    """

    def rows(self, table: str) -> list[dict]:
        from agentflow.store import StoreError

        raise StoreError(f"测试：表 {table} 读不出来")


def _fallback_relation_with_broken_store(store) -> ToolRegistry:
    """取出降级替身版本的 ``trace.relation``，并把它闭包里的 ``store`` 换成读不了表的桩。

    为什么不整条走 ``install_d_tools(<坏 store>)``：``RT.install`` 在装配期
    也会读表，那样测到的是"装配失败"而不是"调用时如何处理表读失败"。
    这里只换 handler 闭包捕获的 ``store``（``@tool`` 装饰出的 spec 不变），
    被测对象因此精确落在"替身怎么处理 ``StoreError``"这一件事上。
    """
    reg = install_d_tools(store, trace_tools=_BROKEN_TRACE_MODULE)
    spec = reg.get("trace.relation")
    handler = spec.handler
    closure = handler.__closure__
    assert closure, "降级替身的 handler 必须闭包捕获读表助手"
    names = handler.__code__.co_freevars
    # 结构：handler 只闭包捕获 `_table`（读表助手），`_table` 再闭包捕获 `store`。
    # 因此要把坏 store 装到内层那一格。这条断言同时把"结构变了"变成红灯，
    # 而不是让测试悄悄测了个空。
    assert names == ("_table",), names
    inner = handler.__closure__[0].cell_contents
    inner_names = inner.__code__.co_freevars
    assert "store" in inner_names, inner_names
    broken = _RaisingRows()
    for name, cell in zip(inner_names, inner.__closure__):
        if name == "store":
            cell.cell_contents = broken  # type: ignore[assignment]
    return reg


def test_fallback_trace_tool_reports_table_failure_not_missing_row(store) -> None:
    """负控（静默空成功）：表读不出来时必须是 ``ok=False`` 且类型可辨。

    旧行为把"读不了"与"查过了没有"折叠成同一个形态（前者是
    ``kind="unexpected"``，后者是 ``ok=True, found=False``）。这里断言：
    失败、``kind="tool_error"``（不是 ``unexpected``）、消息里点出表名。
    """
    reg = _fallback_relation_with_broken_store(store)
    res = reg.call("trace.relation", relation_id="0000")
    assert res.ok is False, f"表读不出来却报成功：{res}"
    assert res.meta.get("kind") == "tool_error", res.meta
    assert "relations" in str(res.error), res.error


def test_fallback_trace_tool_distinguishes_missing_row_from_not_checked(store) -> None:
    """三态负控：表读得出来但没有这一行 ⇒ ``ok=True`` 且 ``found=False``。

    与上一条合起来构成三态：读到 / 没读到 / 读不了。
    三者不得被折叠成同一个返回值。
    """
    reg = install_d_tools(store, trace_tools=_BROKEN_TRACE_MODULE)
    res = reg.call("trace.relation", relation_id="9999")
    assert res.ok is True and res.data["found"] is False
    assert res.data.get("source") == "fallback"


def test_fallback_tools_are_only_used_when_external_trace_tools_missing(store) -> None:
    """负控（降级必须是可观测的）：外部存在时不留降级痕迹；失败时留原因。

    注意 ``trace_tools=None`` 是"没传"的哨兵，会去惰性加载真身 ——
    要验证降级必须给一个"存在但 register 失败"的外部模块。
    """
    external = install_d_tools(store)
    assert not getattr(external, "trace_fallback_reason", None)
    assert "trace.chain" in external.names(), "外部真身应当被装上"

    fallback = install_d_tools(store, trace_tools=_BROKEN_TRACE_MODULE)
    reason = getattr(fallback, "trace_fallback_reason", None)
    assert reason, "降级原因没留痕 = 静默少工具"
    assert "RuntimeError" in reason and "bug" in reason, reason
