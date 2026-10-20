"""判据：十个角色 + 秘书的提示词前缀**真的进了上游缓存**吗（2026-10-21 真机读数）。

## 这一组为什么"读一份读数"，而不是自己去发请求

上游的前缀缓存只有真机才有读数（`usage.prompt_cache_hit_tokens`）。让判据自己去发请求
有两个后果，都会把这条判据变成贵而无用的东西：① 每次跑测试都花钱、还必须联网
（§7.4 离线确定性）；② 上游抽风时它红，而"上游抽风"与"提示词抖了"要分开处置。

所以分工是：

- **发请求的那一侧** = `scripts/warm_prompt_cache.py`（幂等、内置 $0.10 上限、
  一次一个目标），它把读数写进 `tests/fixtures/prompt_cache_warm.json`；
- **判据这一侧** = 本文件：只读那份读数，并且**重算**十个角色的提示词摘要 ——
  于是"提示词改了而读数没重跑"这一档会当场红（读数不许悄悄烂掉）。

## 三条判据（本次任务的①②③）与它们各自的负控

1. **每个目标都有缓存写记录**（`write > 0` 或 `hit > 0`），逐角色一行；
   负控：把某个角色的行删掉 ⇒ 同一个检查必须点名它。
2. **第二次调用命中**：同一角色再调一次，`hit > 0` 且 `hit/(hit+miss) > 0`
   （样本只挑 2 个 —— 省钱是这条判据的一部分，不是省略）。
   负控：把样本那一行的 `hit` 改成 0 ⇒ 必须红。
3. **prompt 稳定**：同一角色两次调用的 `prompt_sha256` 相同。
   正控用**两次独立渲染**（各自造一份注册表）逐字节比对；差异用
   `promptstability.first_difference` / `dynamic_sections` 报到段名一级。
   **负控：把 `budget_left` 塞回系统提示**（改前那个形态）⇒ ③ 必须红 ——
   这一条证明它守的真的是"提示词不许抖"，而不是"两边都不是空的"。

## 一条硬口径：`write` 是推导量，`hit` 才是实证

上游没有"写"这个计数（请求体里没有 `cache_control`，也没有写缓存响应字段）。
读数里的 `write` = 这一次被 miss 掉的那部分 token（`write_source="derived:miss"`）——
它说的是"这部分被送去建索引了"，**不是**"下一次一定能命中"。

真机上这两者会分开：改前 `secretary` 那一行连发两趟都是 `miss=175 / hit=0`
（`2026-10-21` 实测，`--roles secretary --hit-sample secretary` ⇒ 退出码 1
"第二次调用没命中的样本：['secretary']"，) ⇒ 它那条 175 token 的前缀**没有**进索引
（原因：整条提示词在 **user** 位、而材料每问一次都变 ⇒ 前缀从第一个字符起就不同）。
所以本文件除了①那条"字面判据"，还有一条**实证**判据：
十一个目标的同一份 `system` 必须**真的被下一次命中**（`hit > 0`）。

2026-10-21 之后秘书与十个角色**同形**（稳定头进 `system`、材料留 user），
所以它也要过实证那一档 —— 判据见 `tests/test_secretary_system_carries_the_head.py`。

## 反真空

读数里 `runs` / `rows` / 目标数 / 每行的 token 数任何一个读不出来 ⇒ 当场红
（"没读到"与"都合格"必须分得开）。本文件第一条判据就是那一层。
"""

from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import sys
from typing import Any, Iterable, Mapping, Sequence

import pytest

from agentflow import agent_prompts as AP
from agentflow import promptstability as PSTAB

_REPO = pathlib.Path(__file__).resolve().parents[1]
_READINGS = _REPO / "tests" / "fixtures" / "prompt_cache_warm.json"


def _load_warm():
    """按路径导入 `scripts/warm_prompt_cache.py`（`scripts/` 不是包，不能普通 import）。"""
    spec = importlib.util.spec_from_file_location(
        "_warm_prompt_cache_under_test", _REPO / "scripts" / "warm_prompt_cache.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


W = _load_warm()

#: 本次预热的目标全集（十个角色 + 秘书）。
TARGETS: tuple[str, ...] = tuple(W.WARM_TARGETS)

#: 十个角色（能做实证命中的那一档）。
TEN_ROLES: tuple[str, ...] = tuple(W.ROLES)


# ---------------------------------------------------------------- 读读数


def _runs() -> list[dict[str, Any]]:
    assert _READINGS.is_file(), (
        f"读数不在盘上：{_READINGS} —— 跑一次 "
        "`python scripts/warm_prompt_cache.py --roles A,B,C,D,E,F,G,H,V,M,secretary`")
    return W.load_readings(_READINGS)


def _rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """只取**主判据**那一档的行（`pass` 1/2）。

    诊断行（3 = 去掉工具面、4/5 = 换一趟活的 system）刻意排除：
    它们回答的是别的问题，混进来会让"这个角色的两次调用"变成三次四次。
    """
    return [dict(r) for r in rows if int(r.get("pass") or 1) <= 2]


def _as_int(value: Any) -> int:
    return int(value or 0)


def _row_write_or_hit(row: Mapping[str, Any]) -> int:
    """一行里"被写进去"的证据量（`write` 是推导量，见模块 docstring）。"""
    cache = row.get("cache") or {}
    return _as_int(cache.get("write")) + _as_int(cache.get("hit"))


def _records_by_target(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in _rows(rows):
        out.setdefault(str(row.get("role")), []).append(dict(row))
    return out


def _targets_without_write_record(targets: Sequence[str],
                                  rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """①的判据本体：这些目标里，哪些**没有**任何一行带 `write>0` 或 `hit>0`。"""
    scored = {t: False for t in targets}
    for row in _rows(rows):
        role = str(row.get("role"))
        if role in scored and _row_write_or_hit(row) > 0:
            scored[role] = True
    return [t for t, ok in scored.items() if not ok]


def _targets_landed(targets: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> set[str]:
    """实证：这些目标里，哪些的同一份 prompt **真的被下一次命中过**（`hit > 0`）。"""
    landed: set[str] = set()
    for row in _rows(rows):
        if _as_int((row.get("cache") or {}).get("hit")) > 0:
            landed.add(str(row.get("role")))
    return {t for t in targets if t in landed}


def _second_call_readings(targets: Sequence[str],
                          rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """②的判据本体：每个样本角色**第二次**调用那一行的 `hit` / `miss` / `hit_rate`。"""
    out: dict[str, dict[str, Any]] = {}
    for row in _rows(rows):
        if int(row.get("pass") or 1) != 2:
            continue
        role = str(row.get("role"))
        if role not in targets:
            continue
        cache = row.get("cache") or {}
        hit, miss = _as_int(cache.get("hit")), _as_int(cache.get("miss"))
        out[role] = {
            "hit": hit,
            "miss": miss,
            "hit_rate": (hit / (hit + miss)) if (hit + miss) else 0.0,
            "prompt_sha256": str(row.get("prompt_sha256") or ""),
        }
    return out


def _digest_problems(targets: Sequence[str],
                     rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """③的判据本体（读数面）：同一角色的每一行必须挂着**同一个** `prompt_sha256`。

    这正是"同一角色两次调用的 prompt_sha256 相同"那句话 —— 只不过它比一句话硬：
    行数可以是 1、2 或更多，每一行都得对得上。
    """
    problems: list[str] = []
    for target, group in sorted(_records_by_target(rows).items()):
        if target not in targets:
            continue
        digests = sorted({str(r.get("prompt_sha256") or "") for r in group})
        if len(digests) > 1:
            problems.append(f"{target}：{len(group)} 行的 prompt_sha256 有 {len(digests)} 种 "
                            f"{[d[:12] for d in digests]} ⇒ 同一角色两次调用的不是同一段前缀")
        if any(not d for d in digests):
            problems.append(f"{target}：有一行没有 prompt_sha256（读不到摘要 = 这一格没查成）")
    return problems


# ---------------------------------------------------------------- 渲染（重算摘要）


_RENDERED: dict[str, dict[str, Any]] = {}


def _rendered() -> dict[str, dict[str, Any]]:
    """十个角色 + 秘书的提示词（按当前盘上的代码重算一遍）。模块内只算一次。"""
    if not _RENDERED:
        _RENDERED.update(W.render_prompts(targets=TARGETS))
    return _RENDERED


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fact_pair(role: str, registry: Any, *, split: bool) -> tuple[str, str]:
    """同一角色的两份 system：只让"每步会变的那两格"不同。

    `split=True` 是今天的实现（两格被换成正静态指路语，`split_facts`）；
    `split=False` 是改前的形态（两格原值进 system）—— 它就是③的负控。
    """
    prev = dict(W.CANONICAL_FACTS)
    cur = dict(prev)
    cur["budget_left"] = "0.400000 美元（上限 1.000000，已用 0.600000，读数来自 per_seam）"
    cur["notebook"] = "- [第 2 步] 记一笔：预算还剩一半"
    if split:
        return (W._render_system(role, registry, prev), W._render_system(role, registry, cur))
    return (AP.system_prompt(role, registry=registry, **prev),
            AP.system_prompt(role, registry=registry, **cur))


def _stability_problem(prev: str, cur: str) -> str:
    """③的正控/负控共用的那一句结论（空串 = 同一段前缀）。"""
    return PSTAB.stability_problem(prev, cur)


@pytest.fixture(scope="module")
def registry() -> Any:
    import tempfile

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="warm-test-reg-"))
    try:
        yield W._registry(tmp)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="module", autouse=True)
def _recorded_lean_mode() -> Any:
    """把形式化开关钉到**读数里记着的那一档**（预热是在那一档渲染的）。

    为什么必须有这一步：`system_prompt` 在"形式化关着"那一档会把 Lean 相关的段
    整段换掉（`_apply_no_lean_variant`），于是同一份代码在两档下渲染出的 system
    **不是同一段前缀**。而判据套件在 `conftest` 里把这一档钉成**开着**（那是产品缺省的
    反面，为的是让形式化那条路有判据可测）。预热跑在**产品口径**（关着）——
    两个口径本身都对，混在一起就变成了假的"提示词变了"。

    钉法与 `tests/test_lean_switch.py` 同一手：改 env + 清 `agent_prompts` 的两处
    `lru_cache`（`reset_toolchain_readings`），收尾时还原。
    """
    import os

    runs = _runs()
    modes = {bool(r.get("lean_enabled")) for r in runs if r.get("lean_enabled") is not None}
    assert len(modes) <= 1, (
        f"读数里的几趟预热不在同一档形式化开关下（{sorted(modes)}）⇒ "
        "它们的 prompt_sha256 本来就该不同，混读会把'开关变了'判成'提示词抖了'")
    if not modes:
        yield
        return
    want = modes.pop()
    previous = os.environ.get("AGENTFLOW_LEAN_ENABLED")
    os.environ["AGENTFLOW_LEAN_ENABLED"] = "1" if want else "0"
    AP.reset_toolchain_readings()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AGENTFLOW_LEAN_ENABLED", None)
        else:
            os.environ["AGENTFLOW_LEAN_ENABLED"] = previous
        AP.reset_toolchain_readings()


# ---------------------------------------------------------------- 0. 反真空


def test_the_readings_file_is_a_complete_per_role_table() -> None:
    """反真空：读数在盘上、形状对、每个目标都有行 —— 缺一格都算"没查成"。

    这条先跑：后面三条判据都建立在"这份读数读得出来"之上。少一个角色、少一行、
    token 数是 0 ⇒ 那不是"合格"，是这一格没量到。
    """
    runs = _runs()
    assert len(runs) >= 2, (
        f"读数里只有 {len(runs)} 趟预热；这一组判据要**两趟**才说得清"
        "（第一趟是冷写，第二趟是重落 —— 见模块 docstring 的①②）")
    rows = [row for run in runs for row in (run.get("rows") or [])]
    assert rows, "读数里一行都没有 ⇒ 这一格没查成"

    by_target = _records_by_target(rows)
    missing = [t for t in TARGETS if t not in by_target]
    assert not missing, f"这些目标一行读数都没有：{missing}（认 {list(TARGETS)}）"
    assert len(TARGETS) == 11, (
        f"目标数是 {len(TARGETS)}，十个角色 + 秘书该是 11 —— 少一个就说明"
        "`WARM_TARGETS` 被人改窄了")

    zero = [str(r.get("role")) for r in _rows(rows)
            if _as_int((r.get("cache") or {}).get("tokens_in")) <= 0]
    assert not zero, f"这些行 tokens_in=0（上游没报用量）⇒ 读数不可用：{zero}"

    # 每一趟的花费都必须在上限之内（钱的上限是判据的一部分，不是纪律口号）。
    over = [(run.get("at"), run.get("spent_usd"), run.get("cap_usd")) for run in runs
            if float(run.get("spent_usd") or 0.0) > float(run.get("cap_usd") or 0.0)]
    assert not over, f"有趟预热超了自身上限：{over}"
    caps = sorted({float(run.get("cap_usd") or 0.0) for run in runs})
    assert caps and max(caps) <= 0.10 + 1e-9, (
        f"读数的内置上限是 {caps} —— 任务给的是 0.10 美元；把它们抬上去"
        "就等于把「超了自停」这句话删掉了")
    print(f"（这几趟预热合计 {sum(float(run.get('spent_usd') or 0.0) for run in runs):.6f} "
          f"美元；上限 {max(caps):.2f}/趟）")


# ---------------------------------------------------------------- 1. ① 逐角色一行


def test_every_target_has_a_cache_write_record() -> None:
    """判据 ①：十个角色 + 秘书，**每个**都有 `write>0` 或 `hit>0` 的记录。

    读数逐角色打一行（`role / write / hit / 是否实证 landed`）—— 这一行就是
    任务要的那张表，判据自己把它打出来，于是"表"与"判据"不会各说一套。
    """
    rows = [row for run in _runs() for row in (run.get("rows") or [])]
    without = _targets_without_write_record(TARGETS, rows)
    landed = _targets_landed(TARGETS, rows)

    print(f"{'role':<11}{'write(推导)':>13}{'hit(实证)':>11}{'landed':>9}")
    for target in TARGETS:
        group = _rows([r for r in rows if str(r.get("role")) == target])
        write = max((_as_int((r.get("cache") or {}).get("write")) for r in group), default=0)
        hit = max((_as_int((r.get("cache") or {}).get("hit")) for r in group), default=0)
        print(f"{target:<11}{write:>13}{hit:>11}{str(target in landed):>9}")

    assert not without, (
        "这些目标一条缓存写记录都没有（`write>0` 或 `hit>0` 都读不到）⇒ "
        f"它们的提示词前缀**没进缓存**：{without}")


def test_the_ten_role_prompts_are_proven_to_land_in_the_cache() -> None:
    """判据 ①的实证那一半：十个角色的同一份 prompt 必须**真的被下一次命中**（`hit>0`）。

    为什么"有 write 记录"还不够：`write` 是从 `miss` **推导**出来的（上游没有写计数），
    它证明的是"这部分被送去建索引"，不是"索引留下了它"。真机上这两者会分开 ——
    改前秘书那一行 `write=175` 而 `hit` 恒 0（连发两趟都不中，见模块 docstring）。

    秘书那一档现在也要过同一条实证（它的稳定头进了 system），但它的读数在
    `tests/test_secretary_system_carries_the_head.py` 里判 —— 这一条只判十个角色，
    外加一条"`landed` 与读数一致"的自洽检查（防止有人把 `landed` 算宽）。
    """
    rows = [row for run in _runs() for row in (run.get("rows") or [])]
    landed = _targets_landed(TARGETS, rows)

    not_landed = [t for t in TEN_ROLES if t not in landed]
    assert not not_landed, (
        f"这些角色的 prompt **没有被第二次命中**（hit=0）⇒ 前缀没真的进缓存：{not_landed}")

    # 自洽：秘书那一档的 `landed` 必须与读数一致（不要求它绿，要求它诚实）。
    secretary_rows = _rows([r for r in rows if str(r.get("role")) == W.SECRETARY])
    assert secretary_rows, "秘书一行读数都没有 ⇒ 它那一档没量"
    secretary_hit = max((_as_int((r.get("cache") or {}).get("hit")) for r in secretary_rows),
                        default=0)
    assert (W.SECRETARY in landed) == (secretary_hit > 0), (
        "`landed` 与'有没有一行 hit>0'不一致 ⇒ 这一格在自说自话")

    # 负控：把一个已落地的角色从读数里删掉 ⇒ 同一个检查必须点名它。
    victim = next(t for t in TEN_ROLES if t in landed)
    pruned = [r for r in rows if str(r.get("role")) != victim]
    assert victim not in _targets_landed(TARGETS, pruned), (
        f"负控失败：把 {victim} 的行全删掉之后它还判「落地」⇒ 这条判据没有牙")


# ---------------------------------------------------------------- 2. ② 第二次调用命中


def test_a_second_call_hits() -> None:
    """判据 ②：样本角色的第二次调用 `hit > 0` 且命中比例 > 0（样本只有 2 个）。

    "只挑 2 个"是**判据的一部分**：省钱是这条设计里的取舍，不是偷懒 ——
    所以这里连"样本数不许超过 2"一起判（超了就是有人把一条便宜的判据变成了贵的）。
    """
    rows = [row for run in _runs() for row in (run.get("rows") or [])]
    sample = tuple(W.DEFAULT_HIT_SAMPLE)
    assert len(sample) == 2, f"样本该是 2 个（省钱），实际 {len(sample)} 个：{sample}"

    readings = _second_call_readings(sample, rows)
    missing = [t for t in sample if t not in readings]
    assert not missing, f"这些样本没有第二次调用的读数：{missing}"
    for target in sample:
        got = readings[target]
        assert got["hit"] > 0, f"{target} 的第二次调用 hit=0（miss={got['miss']}）⇒ 没命中"
        assert got["hit_rate"] > 0, f"{target} 的命中比例是 0：{got}"

    # 负控：把样本那一行的 hit 改成 0 ⇒ 同一个取值必须红。
    poisoned = []
    for row in rows:
        copy = dict(row)
        if int(copy.get("pass") or 1) == 2 and str(copy.get("role")) in sample:
            copy["cache"] = {**(copy.get("cache") or {}), "hit": 0}
        poisoned.append(copy)
    bad = _second_call_readings(sample, poisoned)
    assert all(bad[t]["hit"] == 0 for t in sample if t in bad), (
        "负控失败：把 hit 改成 0 之后仍然读到命中 ⇒ 这条判据读的不是那个数")


# ---------------------------------------------------------------- 3. ③ prompt 稳定


def test_the_prompt_digest_does_not_move_between_calls() -> None:
    """判据 ③（读数面）：同一角色每一行的 `prompt_sha256` 必须相同。

    负控：把某一行的摘要改一个字符 ⇒ 必须红，且报出"有几种摘要"。
    """
    # 2026-10-21 口径修正：这条判据问的是"**同一趟**里同一角色两次调用是不是同一段前缀"，
    # 不是"跨趟也不许变" —— 跨趟会变正是我们要的（提示词改了、facts 挪了位置）。
    # 旧写法把所有趟的行混在一起比，于是"提示词真的改过一次"会被读成"同一角色两次调用不一致"。
    # 所以按 `at`（趟）分组；跨趟一致性由 `test_the_recorded_digests_still_match_the_rendered_prompts` 守最新一趟。
    rows = [row for run in _runs() for row in (run.get("rows") or [])]
    per_run = []
    for run in _runs():
        group = list(run.get("rows") or [])
        if group:
            per_run.extend(_digest_problems(TARGETS, group) and [f'趟 {run.get("at")}：' + x
                                                             for x in _digest_problems(TARGETS, group)] or [])
    problems = per_run
    assert not problems, "；".join(problems)

    # 负控：改**一行**的摘要 ⇒ 同一个函数必须看见。
    # 只改一行（不是"把同角色同 pass 的行全改掉"）：那个角色每一趟都有一行 pass=1，
    # 全改掉之后它们仍然彼此一致 —— 负控会因此空转（第一版就是这么写错的）。
    victim = next(r for r in _rows(rows) if str(r.get("role")) in TEN_ROLES)
    key = (str(victim.get("role")), int(victim.get("pass") or 1))
    poisoned: list[dict[str, Any]] = []
    done = False
    for row in rows:
        copy = dict(row)
        if not done and (str(copy.get("role")), int(copy.get("pass") or 1)) == key:
            copy["prompt_sha256"] = "0" * 64
            done = True
        poisoned.append(copy)
    assert done, f"负控没改到任何一行（{key}）"
    assert _digest_problems(TARGETS, poisoned), (
        "负控失败：把一行的 prompt_sha256 换掉之后仍然判「一致」⇒ 这条判据没在读摘要")


def test_two_independent_renders_are_byte_identical(registry: Any) -> None:
    """判据 ③（渲染面）：同一角色两次**独立渲染**必须逐字节相同（十个角色各判一遍）。

    这是"同一角色两次调用的 prefix 相同"的机械前提。正控用两次独立渲染
    （两次都过 `split_facts`）—— 它们共享的只有"静态事实"，而每步会变的两格
    已经被换成静态指路语（`promptstability.SYSTEM_PLACEHOLDERS`）。

    差异报告不是"变了"三个字：`stability_problem` 给出"从第几个字符起不同 + 前后各 80 字"，
    `dynamic_sections` 点名是哪一段变的。
    """
    ok: list[str] = []
    for role in TEN_ROLES:
        prev, cur = _fact_pair(role, registry, split=True)
        assert len(prev) > 20_000, f"{role} 的 system 只有 {len(prev)} 字 ⇒ 反真空（太短了）"
        problem = _stability_problem(prev, cur)
        if problem:
            changed = PSTAB.dynamic_sections(
                AP.role_prompt_registry(role, registry=registry, **W.CANONICAL_FACTS)
                .assemble(AP.Scope(role=role)),
                AP.role_prompt_registry(role, registry=registry,
                                        **_with_moved(role, registry))
                .assemble(AP.Scope(role=role)))
            raise AssertionError(f"{role}：分离之后 system 还在抖（变了这些段：{changed}）\n{problem}")
        ok.append(role)
    assert len(ok) == len(TEN_ROLES) == 10, ok


def _with_moved(role: str, registry: Any) -> dict[str, Any]:
    """改前的形态那份事实（两块原值进 system）—— 只给负控的段名报告用。"""
    facts = dict(W.CANONICAL_FACTS)
    facts["budget_left"] = ("0.400000 美元（上限 1.000000，已用 0.600000，读数来自 per_seam）")
    facts["notebook"] = "- [第 2 步] 记一笔：预算还剩一半"
    return facts


def test_putting_budget_left_back_into_the_system_makes_the_criterion_red(
        registry: Any) -> None:
    """负控（③ 的牙）：把 `budget_left` / `notebook` **塞回系统提示** ⇒ ③ 必须红。

    这就是改前那个形态（`agent_loop._system_at_step` 的前身每步把这两格重算进 system）：
    花销一变，`TASK_BUDGET` 那一段的字节就变 ⇒ 整条前缀作废。它必须让同一条判据红，
    并且**点得出**是哪一段变的、从第几个字符起不同。

    这一条是"③ 真的在守提示词不许抖"的唯一证据：没有它，③ 只是"两边都不是空的"。
    """
    checked: list[str] = []
    for role in ("M", "A"):
        prev, cur = _fact_pair(role, registry, split=False)
        problem = _stability_problem(prev, cur)
        assert problem, (
            f"{role}：把 budget_left 塞回 system 之后两次渲染仍然逐字节相同 ⇒ "
            "这条负控是空转（③ 什么也没守）")
        assert "从第" in problem and "个字符起不同" in problem, problem
        assert "美元" in problem, (
            f"{role}：报出来的差异里看不到预算那一段的原文 ⇒ 定位不到该改哪儿：{problem}")

        changed = PSTAB.dynamic_sections(
            AP.role_prompt_registry(role, registry=registry, **W.CANONICAL_FACTS)
            .assemble(AP.Scope(role=role)),
            AP.role_prompt_registry(role, registry=registry, **_with_moved(role, registry))
            .assemble(AP.Scope(role=role)))
        assert "TASK_BUDGET" in changed and "TASK_NOTEBOOK" in changed, (
            f"{role}：段级判据没点名 TASK_BUDGET / TASK_NOTEBOOK，而是 {changed} ⇒ "
            "红了也读不出该改哪一段")

        # 分离之后（今天的实现）同一对事实必须**绿** —— 否则上面那条红就说明不了什么。
        ok_prev, ok_cur = _fact_pair(role, registry, split=True)
        assert _stability_problem(ok_prev, ok_cur) == "", (
            f"{role}：`split_facts` 之后 system 还不同 ⇒ 静态/动态分离没生效")
        checked.append(role)
    assert len(checked) == 2, checked


# ---------------------------------------------------------------- 4. 读数不许烂


def test_the_recorded_digests_still_match_the_rendered_prompts() -> None:
    """读数的新鲜度：盘上记的 `prompt_sha256` 必须等于**今天**重算的摘要。

    这一条守的是"读数会腐烂"：提示词一改（`agent_prompts.py` / `specs/*` / 预设），
    以前那份预热就作废了 —— 而 JSON 还在，命中率读数还很好看。
    红的时候**不要**改这里：重跑一次预热（一条命令写在 `docs/DEVELOPMENT-SPEC.md` §14）。
    """
    rendered = _rendered()
    latest = _runs()[-1]
    problems: list[str] = []
    for target in TARGETS:
        recorded = {str(r.get("prompt_sha256") or "")
                    for r in (latest.get("rows") or [])
                    if str(r.get("role")) == target and int(r.get("pass") or 1) == 1}
        want = str(rendered[target]["prompt_sha256"])
        if not recorded:
            problems.append(f"{target}：最新那一趟里没有它的主行读数")
            continue
        if want not in recorded:
            problems.append(f"{target}：盘上记的是 {sorted(d[:12] for d in recorded)}，"
                            f"今天重算是 {want[:12]} ⇒ 提示词变了，读数作废（重跑预热）")
    assert not problems, "；".join(problems)

    # 秘书那一档（2026-10-21 起与十个角色同形）：摘要就是它进 `system` 的**稳定头** ——
    # 不是那条整提示词（材料在 user 位，每问一次都变）。口径不许含糊。
    prompt, _stable = W._secretary_head()
    assert rendered[W.SECRETARY]["prompt_sha256"] == _sha(prompt), (
        "秘书那一行的 prompt_sha256 与它进 system 的稳定头对不上")
    assert rendered[W.SECRETARY]["system"].strip(), (
        "秘书的 system 是空的 ⇒ 稳定头没有进 system 位（改前那个形体）")
    assert rendered[W.SECRETARY]["kind"] == "judge_system", rendered[W.SECRETARY]["kind"]


def test_the_two_diagnostic_readings_say_what_they_measured() -> None:
    """两条诊断读数必须与文档 §14 的两句话一致（否则改的是文档，不是读数）。

    - **工具面不在缓存前缀里**：同一份 system，带工具面预热过之后**去掉工具面**
      再发一次仍然命中（`tools_in_prefix=False`，实测 hit 11,904 / 12,126）；
    - **换一趟活也命中**（2026-10-21 之后的口径）：另一份 system（不同 `task` /
      `task_id` / `depth` / `workspace_root`）在 system 里**逐字节等于**原来那一份
      （跨 run 会变的十格已经挪进 user 消息）⇒ `cross_run_hit` 的两行**都该 ≥90%**。
      改前那两行是 `0 / 满`，那正是"预热只买到同一份前缀的第二次"的读数。

    这两条决定了"预热到底买到了什么"：改前买到的是"同一份前缀的第二次调用能省"；
    现在还包括"另一趟活能用同一段前缀"。`cross_run_prefix_chars`（离线算的字符数）
    因此必须等于整份 system 的长度 —— 这是同一条判据的另一半。
    """
    runs_with_probe = [run for run in _runs() if run.get("tools_in_prefix") is not None]
    assert runs_with_probe, (
        "读数里没有一次带 `--probe-no-tools` 的诊断 ⇒ '工具面在不在前缀里'这一格没量")
    run = runs_with_probe[-1]
    probe = [r for r in (run.get("rows") or []) if int(r.get("pass") or 1) == 3]
    assert probe, "`tools_in_prefix` 有值却没有 pass=3 那一行 ⇒ 读数自相矛盾"
    assert probe[0]["cache"]["hit"] > 0, (
        "去掉工具面之后仍应命中 system 那一段（实测 11,904 token）；"
        f"读数是 {probe[0]['cache']}")
    assert run["tools_in_prefix"] is False, run["tools_in_prefix"]

    cross = run.get("cross_run_hit")
    assert cross and len(cross) == 2, cross
    first, second = cross[0], cross[1]
    assert first["pass"] == 4 and second["pass"] == 5, cross
    # 口径（2026-10-21）：两行都是"另一趟活"的 system，两行都该命中。
    # 改前：第一行 `hit=0`（另一份 system 从第 95 个字符起就不同）。
    for tag, got in (("第一次见", first), ("第二次见", second)):
        assert got["hit"] > 0, (
            f"另一趟活的 system {tag}没有命中（hit=0，tokens_in={got['tokens_in']}）⇒ "
            "前缀里还有跨 run 会变的东西（登记表见 `promptstability.STEP_VOLATILE_FACTS`）")
        rate = got["hit"] / got["tokens_in"]
        assert rate >= 0.90, (
            f"另一趟活的 system {tag}只命中 {rate * 100:.1f}%（hit {got['hit']} / "
            f"{got['tokens_in']} token）⇒ 与'跨 run 同一份前缀'对不上：{got}")
    # 离线那一格：跨 run 可复用的前缀 == 整份 system（一格都没断）。
    rows = [r for r in (run.get("rows") or []) if int(r.get("pass") or 1) in (4, 5)]
    assert rows, run.get("rows")
    for row in rows:
        assert int(row["cross_run_prefix_chars"]) == int(row["system_chars"]), (
            f"跨 run 可复用前缀只有 {row['cross_run_prefix_chars']} / 整份 "
            f"{row['system_chars']} 字符 ⇒ system 里还有跨 run 会变的东西")
