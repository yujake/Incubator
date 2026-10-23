"""判据：十一个角色 + 秘书的提示词前缀真的进了上游缓存吗（2026-10-22 两档读数）。

这一组为什么"读一份读数"，而不是自己去发请求：上游的前缀缓存只有真机才有读数（`usage.prompt_cache_hit_tokens`）。让判据自己去发请求有两个后果，都会把这条判据变成贵而无用的东西：① 每次跑测试都花钱、
还必须联网（§7.4 离线确定性）；② 上游抽风时它红，而"上游抽风"与"提示词抖了"要分开处置。所以分工是：发请求的那一侧 = `scripts/warm_prompt_cache.py`（幂等、内置 $0.10 上限、
一次一个目标），它把读数写进 `tests/fixtures/prompt_cache_warm.json`；- 判据这一侧 = 本文件：只读那份读数，并且重算角色的提示词摘要
——于是"提示词改了而读数没重跑"这一档会当场红（读数不许悄悄烂掉）。

## 2026-10-22：从"一档"变成"两档"

`system_prompt` 在 Lean 开关的两档下渲染出的 system 不是同一段前缀（`_apply_no_lean_variant`），
所以一份"只落了一档"的读数回答不了"开关到底有没有影响渲染"。现在同一份读数容器里必须同时有
`lean_enabled=false` 与 `lean_enabled=true` 各一趟，且两趟各自 12 个目标（十一个角色 + 秘书）：
① 两档都存在、都新鲜（各自记的 `prompt_sha256` 等于今天按同一档重算的）；
② 两档的摘要必须不同（相同 ⇒ 开关没影响渲染，或只落了一档）；
③ 反真空：只留一档 ⇒ 红；两档摘要相同 ⇒ 红；
④ 目标全集是 12 个（含 L），且每趟的 `roles` 都点名这 12 个。

一条结构事实（不是遗漏）：`leanscope.LEAN_ONLY_ROLES` 里的 L 在 Lean 关着时按产品规则
不存在（`system_prompt("L")` 抛 `RoleHidden`）。所以关那一档里 L 的读数是 `kind=absent`
的受控缺席行 —— 判据要求它必须被显式记录，且今天重渲染仍然同样拒绝；L 被静默漏掉照样红，
L 在关档里被伪造一段摘要也照样红。

三条判据（本次任务的①②③）与它们各自的负控：每个目标都有缓存写记录（`write > 0` 或 `hit > 0`），逐角色一行；负控：把某个角色的行删掉 ⇒
同一个检查必须点名它。2. 第二次调用命中：同一角色再调一次，`hit > 0` 且 `hit/(hit+miss) > 0`（样本只挑 2 个 —— 省钱是这条判据的一部分，不是省略）。负控：把样本那一行的 `hit` 改成 0
⇒ 必须红。3. prompt 稳定：同一角色两次调用的 `prompt_sha256` 相同。正控用两次独立渲染（各自造一份注册表）逐字节比对；差异用`promptstability.first_difference` /
`dynamic_sections` 报到段名一级。负控：把 `budget_left` 塞回系统提示（改前那个形态）⇒ ③ 必须红 ——这一条证明它守的真的是"提示词不许抖"，而不是"两边都不是空的"。
一条硬口径：`write` 是推导量，`hit` 才是实证：上游没有"写"这个计数（请求体里没有 `cache_control`，也没有写缓存响应字段）。读数里的 `write` = 这一次被 miss 掉的那部分
token（`write_source="derived:miss"`）——它说的是"这部分被送去建索引了"，不是"下一次一定能命中"。真机上这两者会分开：改前 `secretary` 那一行连发两趟都是
`miss=175 / hit=0`（`2026-10-21` 实测，`--roles secretary --hit-sample secretary` ⇒ 退出码 1"第二次调用没命中的样本：['secretary']"，) ⇒
它那条 175 token 的前缀没有进索引（原因：整条提示词在 user 位、而材料每问一次都变 ⇒ 前缀从第一个字符起就不同）。所以本文件除了①那条"字面判据"，还有一条实证判据：十一个目标的同一份
`system` 必须真的被下一次命中（`hit > 0`）。

2026-10-21 之后秘书与角色同形（稳定头进 `system`、材料留 user），所以它也要过实证那一档 —— 判据见 `tests/test_secretary_system_carries_the_head.py`。

反真空：读数里 `runs` / `rows` / 目标数 / 每行的 token 数任何一个读不出来 ⇒ 当场红（"没读到"与"都合格"必须分得开）。本文件第一条判据就是那一层。
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
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

#: 两档 Lean 形式化开关（读数里那一格是布尔，`True` = 打开）。
TIERS: tuple[bool, ...] = (False, True)

#: 目标全集（十一个角色 + 秘书）。
TARGETS: tuple[str, ...] = tuple(W.WARM_TARGETS)

#: 十一个角色（能做实证命中的那一档；L 在 Lean 关着时按设计缺席）。
ROLES: tuple[str, ...] = tuple(W.ROLES)

#: 判据自己承认的角色全集。不直接取 `W.ROLES`：那条断言要能抓住"有人把 WARM_TARGETS 改窄"。
EXPECTED_ROLES: tuple[str, ...] = (
    "A", "B", "C", "D", "E", "F", "G", "H", "V", "M", "L")


# ---------------------------------------------------------------- 读读数


def _runs() -> list[dict[str, Any]]:
    assert _READINGS.is_file(), (
        f"读数不在盘上：{_READINGS} —— 跑两趟（先关后开）：\n"
        f"  python scripts/warm_prompt_cache.py --roles {','.join(TARGETS)}\n"
        f"  python scripts/warm_prompt_cache.py --lean on --hit-sample M,C,L "
        f"--roles {','.join(TARGETS)}")
    return W.load_readings(_READINGS)


def _tier_of(run: Mapping[str, Any]) -> bool | None:
    """这一趟是哪个 Lean 档（`None` = 那一格读不出来，不折成"关"）。"""
    value = run.get("lean_enabled")
    return None if value is None else bool(value)


def _tier_label(lean: bool) -> str:
    return "Lean 开" if lean else "Lean 关"


def _complete_run(runs: Sequence[Mapping[str, Any]], lean: bool) -> dict[str, Any] | None:
    """这一档最近一趟"点名了全部目标"的预热（没有 ⇒ `None`）。

    为什么要求 `roles` 覆盖全集，而不是"最近一趟"：`--roles` 本来就可以只点几个目标
    （诊断与省钱样本都这么跑）。若把"最近一趟"直接当成这一档的代表，一次只点 M 的
    探针就会把整档判成"缺 11 个目标"。所以只在"完整趟"里挑最近的那一趟 —— 而
    "一档里一趟完整的都没有"仍然如实是"没量"（`None`），不折成合格。
    """
    wanted = set(TARGETS)
    for run in reversed(list(runs)):
        if _tier_of(run) is not lean:
            continue
        if wanted <= {str(r) for r in (run.get("roles") or [])}:
            return dict(run)
    return None


def _rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """只取主判据那一档的行（`pass` 1/2）。

    诊断行（3 = 去掉工具面、4/5 = 换一趟活的 system）刻意排除：
    它们回答的是别的问题，混进来会让"这个角色的两次调用"变成三次四次。

    受控缺席行（`kind="absent"`，Lean 关时的 L）留在这里：它们必须能被看见 ——
    "这一档没有它"是读数，不是没读数。但凡是"读调用"的判据都先过 `_measured_rows`。
    """
    return [dict(r) for r in rows if int(r.get("pass") or 1) <= 2]


def _measured_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """只取真的发过请求（或被上游报过读数）的行 —— 受控缺席行不算量过。"""
    return [r for r in _rows(rows) if str(r.get("kind") or "") != "absent"]


def _absent_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """受控缺席行（这一档下这个目标按产品设计不存在）。"""
    return [r for r in _rows(rows) if str(r.get("kind") or "") == "absent"]


def _as_int(value: Any) -> int:
    return int(value or 0)


def _row_write_or_hit(row: Mapping[str, Any]) -> int:
    """一行里"被写进去"的证据量（`write` 是推导量，见模块 docstring）。"""
    cache = row.get("cache") or {}
    return _as_int(cache.get("write")) + _as_int(cache.get("hit"))


def _records_by_target(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in _measured_rows(rows):
        out.setdefault(str(row.get("role")), []).append(dict(row))
    return out


def _targets_without_write_record(targets: Sequence[str],
                                  rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """①的判据本体：这些目标里，哪些没有任何一行带 `write>0` 或 `hit>0`。"""
    scored = {t: False for t in targets}
    for row in _measured_rows(rows):
        role = str(row.get("role"))
        if role in scored and _row_write_or_hit(row) > 0:
            scored[role] = True
    return [t for t, ok in scored.items() if not ok]


def _targets_landed(targets: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> set[str]:
    """实证：这些目标里，哪些的同一份 prompt 真的被下一次命中过（`hit > 0`）。"""
    landed: set[str] = set()
    for row in _measured_rows(rows):
        if _as_int((row.get("cache") or {}).get("hit")) > 0:
            landed.add(str(row.get("role")))
    return {t for t in targets if t in landed}


def _second_call_readings(targets: Sequence[str],
                          rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """②的判据本体：每个样本角色第二次调用那一行的 `hit` / `miss` / `hit_rate`。"""
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
    """③的判据本体（读数面）：同一角色的每一行必须挂着同一个 `prompt_sha256`。

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


_RENDERED: dict[bool, dict[str, dict[str, Any]]] = {}


def _rendered(lean: bool) -> dict[str, dict[str, Any]]:
    """某一档下十一个角色 + 秘书的提示词（按当前盘上的代码重算一遍，模块内每档只算一次）。

    为什么必须按档分开算：`_apply_no_lean_variant` 在关着时改写 E / L 的文案，
    渲染出的 system 与开着时不是同一段前缀。两档各自重算，才能回答"这一档的读数
    还新鲜吗"；拿同一档的摘要去比另一档，红的原因就变成了"开关不一样"。

    切档的做法与 `tests/test_lean_switch.py` 同一手：改 env + 清 `agent_prompts`
    的两处 `lru_cache`（`reset_toolchain_readings`），算完还原并再清一次 ——
    否则后面直接调 `AP.system_prompt` 的判据会拿到这一档的缓存。
    """
    if lean not in _RENDERED:
        previous = os.environ.get("AGENTFLOW_LEAN_ENABLED")
        os.environ["AGENTFLOW_LEAN_ENABLED"] = "1" if lean else "0"
        AP.reset_toolchain_readings()
        try:
            _RENDERED[lean] = W.render_prompts(targets=TARGETS)
        finally:
            if previous is None:
                os.environ.pop("AGENTFLOW_LEAN_ENABLED", None)
            else:
                os.environ["AGENTFLOW_LEAN_ENABLED"] = previous
            AP.reset_toolchain_readings()
    return _RENDERED[lean]


def _tier_freshness_problems(
        loaded: Mapping[bool, Mapping[str, Any]],
        rendered: Mapping[bool, Mapping[str, Mapping[str, Any]]]) -> list[str]:
    """判据 ①：两档都由装载入口给出，且各自记的摘要等于今天按同一档重算的。

    读数从 `cache_readings(lean)` 取（唯一装载入口），不是自己从 `runs` 里挑：
    正是"换档时挑错版本"这件事要在这里被抓到 —— 挑错了的话，下面逐 target 的摘要
    会对不上（两档摘要本来就不同），而报出来的话是"这一档的读数不新鲜"，处置方向正确。

    受控缺席（Lean 关时的 L）也一起判：装载结果里它必须是 `state="absent"`，
    而今天的重渲染必须仍然给出 `kind="absent"`。L 被静默漏掉会红，L 被伪造一段摘要
    也会红，L 被记成"缺行"同样会红（那是这一趟没点到它，不是产品规则）。
    """
    problems: list[str] = []
    for lean in TIERS:
        label = _tier_label(lean)
        got = loaded.get(lean) or {}
        if got.get("tri") != "found" or got.get("run") is None:
            problems.append(
                f"{label}：装载入口没有给出这一档（tri={got.get('tri')!r}，"
                f"reason={got.get('reason')!r}）")
            continue
        if bool(got.get("lean_enabled")) is not lean:
            problems.append(f"{label}：装载入口给的是 lean_enabled={got.get('lean_enabled')!r}")
            continue
        targets = got.get("targets") or {}
        for target in TARGETS:
            entry = dict(targets.get(target) or {"state": "missing", "prompt_sha256": ""})
            item = rendered[lean].get(target)
            if item is None:
                problems.append(f"{target}：{label} 档今天渲染不出它（连缺席都判不了）")
                continue
            if str(item.get("kind")) == "absent":
                if entry.get("state") != "absent":
                    problems.append(
                        f"{target}：{label} 档里它按设计不存在，装载结果却是 "
                        f"{entry.get('state')!r} ⇒ 缺席没有被如实记录")
                continue
            if entry.get("state") == "absent":
                problems.append(f"{target}：{label} 档今天能渲染出它，装载结果却记成缺席")
                continue
            if entry.get("state") == "missing":
                problems.append(f"{target}：{label} 档的装载结果里没有它（这一趟没点到）")
                continue
            want = str(item.get("prompt_sha256") or "")
            have = str(entry.get("prompt_sha256") or "")
            if want != have:
                problems.append(
                    f"{target}：{label} 档盘上记的是 {have[:12]}，"
                    f"今天按同一档重算是 {want[:12]} ⇒ 提示词变了，这一档读数作废")
    return problems


def _tier_difference_problems(off: Mapping[str, Mapping[str, Any]],
                              on: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """判据 ②：两档的摘要必须不同（反真空：两档都不能是空的）。

    逐角色判十一个角色：每一个的两档摘要都必须不同。实测（2026-10-22，p187）：
    A–H / V / M 全不同，L 是"关档缺席 vs 开档有摘要"的不同。秘书是唯一的例外，
    且理由是结构性的：它的稳定头（`_judge_system`）里没有任何随 Lean 开关改写的段，
    两档摘要本来就该相同 —— 把秘书也判成"必须不同"会逼人去改它的文案。
    """
    problems: list[str] = []
    if not off or not on:
        return [f"有一档的渲染结果是空的（关 {len(off)} 项 / 开 {len(on)} 项）⇒ 反真空"]
    for role in ROLES:
        left, right = off.get(role), on.get(role)
        if left is None or right is None:
            problems.append(f"{role}：有一档里没有它的渲染结果")
            continue
        if str(left.get("prompt_sha256") or "") == str(right.get("prompt_sha256") or ""):
            problems.append(
                f"{role}：两档的 prompt_sha256 是同一个"
                f"（{str(left.get('prompt_sha256') or '')[:12]}）⇒ "
                "Lean 开关没有影响渲染，或只落了一档")
    shared = [t for t in TARGETS if t in off and t in on]
    if not any(str(off[t].get("prompt_sha256") or "") != str(on[t].get("prompt_sha256") or "")
               for t in shared):
        problems.append("两档的摘要全一样 ⇒ 开关没真的影响渲染，或只落了一档（反真空）")
    return problems


def _target_set_problems(targets: Sequence[str]) -> list[str]:
    """判据 ④：目标全集必须是十一个角色 + 秘书，且 L 必须在里面。"""
    problems: list[str] = []
    missing = [r for r in EXPECTED_ROLES if r not in targets]
    if missing:
        problems.append(f"目标全集少这些角色：{missing}（认 {list(EXPECTED_ROLES)}）")
    if W.SECRETARY not in targets:
        problems.append(f"目标全集少秘书：{W.SECRETARY}")
    extra = [t for t in targets if t not in EXPECTED_ROLES and t != W.SECRETARY]
    if extra:
        problems.append(f"目标全集有没登记的名字：{extra}")
    if len(set(targets)) != len(targets):
        problems.append(f"目标全集有重复：{list(targets)}")
    return problems


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


# 这里刻意没有"把形式化开关钉到读数里那一档"的 autouse 夹具（2026-10-22 起）。
#
# 改前只有一档读数（产品缺省 = 关着），而判据套件在 conftest 里把这一档钉成开着，
# 于是必须在本模块里改回去才能重算摘要。现在读数里两档都有：任何"钉死一档"的夹具
# 都会让另一档的重算变成假的"提示词变了"。切档只发生在 `_rendered(lean)` 里面
# （改 env + 清缓存 + 算完还原），其余直接调 `AP.system_prompt` 的判据仍跑在套件那一档
# （开着）—— 它们判的是"分离/稳定性"，与档位无关。


# ---------------------------------------------------------------- 0. 反真空


def test_the_readings_file_is_a_complete_per_role_table() -> None:
    """反真空：读数在盘上、形状对、两档都在、每个目标都有行 —— 缺一格都算"没查成"。

    这条先跑：后面几条判据都建立在"这份读数读得出来"之上。少一档、少一个角色、
    少一行、token 数是 0 ⇒ 那不是"合格"，是这一格没量到。
    """
    runs = _runs()
    assert len(runs) >= 2, (
        f"读数里只有 {len(runs)} 趟预热；这一组判据要两趟才说得清"
        "（Lean 关一趟、Lean 开一趟 —— 见模块 docstring 的①②）")
    for lean in TIERS:
        assert _complete_run(runs, lean) is not None, (
            f"{_tier_label(lean)}：读数里没有一趟点名全部 {len(TARGETS)} 个目标的预热 ⇒ "
            "这一档没量（不是合格）")
    rows = [row for run in runs for row in (run.get("rows") or [])]
    assert rows, "读数里一行都没有 ⇒ 这一格没查成"

    by_target = _records_by_target(rows)
    absent = {str(r.get("role")) for r in _absent_rows(rows)}
    missing = [t for t in TARGETS if t not in by_target and t not in absent]
    assert not missing, f"这些目标一行读数都没有：{missing}（认 {list(TARGETS)}）"

    problems = _target_set_problems(TARGETS)
    assert not problems, "；".join(problems)
    assert len(TARGETS) == 12, (
        f"目标数是 {len(TARGETS)}，十一个角色 + 秘书该是 12 —— 少一个就说明"
        "`WARM_TARGETS` 被人改窄了")
    assert W.ROLES[-1] == "L", W.ROLES
    for lean in TIERS:
        run = _complete_run(runs, lean)
        assert run is not None
        got = [str(r) for r in (run.get("roles") or [])]
        assert sorted(got) == sorted(TARGETS), (
            f"{_tier_label(lean)} 趟的 roles 是 {got}，不是 {list(TARGETS)} ⇒ "
            "这一趟没有点名全部目标")

    # 受控缺席只许出现在"这一档今天真的渲染不出它"的目标上（今天是 Lean 关时的 L）。
    wrong = sorted(absent - {t for lean in TIERS for t, item in _rendered(lean).items()
                             if str(item.get("kind")) == "absent"})
    assert not wrong, f"这些目标记成了缺席、但两档今天都渲染得出它们：{wrong}"

    zero = [str(r.get("role")) for r in _measured_rows(rows)
            if _as_int((r.get("cache") or {}).get("tokens_in")) <= 0]
    assert not zero, f"这些行 tokens_in=0（上游没报用量）⇒ 读数不可用：{zero}"

    # 每一趟的花费都必须在上限之内（钱的上限是判据的一部分，不是纪律口号）。
    #
    # 口径是"预检"：脚本在每次调用之前比一次（`spent >= cap` ⇒ 干净停下），
    # 所以最后那一次调用可能把总花费推过上限 —— 越过量最多是一次调用的代价。
    # 2026-10-21 实测：一趟 `--cap-usd 0.035` 跑 11 个目标，停在 0.038451
    # （末次调用 0.005813）。这不是"超支"，是预检闸的形状；真正的超支是
    # "花掉的钱比 cap + 单次代价还多"，那一条这里仍然判红。
    over = []
    for run in runs:
        cap = float(run.get("cap_usd") or 0.0)
        spent = float(run.get("spent_usd") or 0.0)
        worst = max((float(row.get("usd") or 0.0) for row in (run.get("rows") or [])),
                    default=0.0)
        if spent > cap + worst + 1e-9:
            over.append((run.get("at"), spent, cap, worst))
    assert not over, (
        "有趟预热超了自身上限**不止一次调用的代价**（(at, spent, cap, 单次最贵)）："
        f"{over}")
    caps = sorted({float(run.get("cap_usd") or 0.0) for run in runs})
    assert caps and max(caps) <= 0.10 + 1e-9, (
        f"读数的内置上限是 {caps} —— 任务给的是 0.10 美元；把它们抬上去"
        "就等于把「超了自停」这句话删掉了")
    print(f"（这几趟预热合计 {sum(float(run.get('spent_usd') or 0.0) for run in runs):.6f} "
          f"美元；上限 {max(caps):.2f}/趟）")


# ---------------------------------------------------------------- 1. ① 逐角色一行


def test_every_target_has_a_cache_write_record() -> None:
    """判据 ①：十一个角色 + 秘书，每个都有 `write>0` 或 `hit>0` 的记录。

    读数逐角色打一行（`role / write / hit / 是否实证 landed`）—— 这一行就是
    任务要的那张表，判据自己把它打出来，于是"表"与"判据"不会各说一套。

    受控缺席（Lean 关时的 L）不在这条里判：它这一档没有调用，也就没有写记录 ——
    但它在 Lean 开那一档有完整读数，所以"目标全集里有 L"这件事由 `write > 0` 证明。
    """
    rows = [row for run in _runs() for row in (run.get("rows") or [])]
    without = _targets_without_write_record(TARGETS, rows)
    landed = _targets_landed(TARGETS, rows)

    print(f"{'role':<11}{'write(推导)':>13}{'hit(实证)':>11}{'landed':>9}")
    for target in TARGETS:
        group = _measured_rows([r for r in rows if str(r.get("role")) == target])
        write = max((_as_int((r.get("cache") or {}).get("write")) for r in group), default=0)
        hit = max((_as_int((r.get("cache") or {}).get("hit")) for r in group), default=0)
        print(f"{target:<11}{write:>13}{hit:>11}{str(target in landed):>9}")

    assert not without, (
        "这些目标一条缓存写记录都没有（`write>0` 或 `hit>0` 都读不到）⇒ "
        f"它们的提示词前缀没进缓存：{without}")


def test_the_eleven_role_prompts_are_proven_to_land_in_the_cache() -> None:
    """判据 ①的实证那一半：十一个角色的同一份 prompt 必须真的被下一次命中（`hit>0`）。

    为什么"有 write 记录"还不够：`write` 是从 `miss` 推导出来的（上游没有写计数），
    它证明的是"这部分被送去建索引"，不是"索引留下了它"。真机上这两者会分开 ——
    改前秘书那一行 `write=175` 而 `hit` 恒 0（连发两趟都不中，见模块 docstring）。

    L 是这一条里最要紧的一格：它此前从未被量过（不在 `WARM_TARGETS` 里），
    所以 Lean 开那一趟把它加进了 `--hit-sample`（`M,C,L`）—— 只发一次只能证明
    "写进去了"，发了第二次才证明"索引留下了它"。

    秘书那一档现在也要过同一条实证（它的稳定头进了 system），但它的读数在
    `tests/test_secretary_system_carries_the_head.py` 里判 —— 这一条只判十一个角色，
    外加一条"`landed` 与读数一致"的自洽检查（防止有人把 `landed` 算宽）。
    """
    rows = [row for run in _runs() for row in (run.get("rows") or [])]
    landed = _targets_landed(TARGETS, rows)

    not_landed = [t for t in ROLES if t not in landed]
    assert not not_landed, (
        f"这些角色的 prompt 没有被第二次命中（hit=0）⇒ 前缀没真的进缓存：{not_landed}")

    # L 的实证必须来自"能渲染它的那一档"（Lean 开），不能是别的角色的读数凑的。
    on_run = _complete_run(_runs(), True)
    assert on_run is not None, "没有 Lean 开那一档的完整趟 ⇒ L 的实证没处来"
    on_roles = {str(r) for r in (on_run.get("roles") or [])}
    assert "L" in on_roles, on_roles
    assert "L" in landed, "L 从未被量过，这一趟必须让它的第二次调用命中（--hit-sample M,C,L）"

    # 自洽：秘书那一档的 `landed` 必须与读数一致（不要求它绿，要求它诚实）。
    secretary_rows = _measured_rows([r for r in rows if str(r.get("role")) == W.SECRETARY])
    assert secretary_rows, "秘书一行读数都没有 ⇒ 它那一档没量"
    secretary_hit = max((_as_int((r.get("cache") or {}).get("hit")) for r in secretary_rows),
                        default=0)
    assert (W.SECRETARY in landed) == (secretary_hit > 0), (
        "`landed` 与'有没有一行 hit>0'不一致 ⇒ 这一格在自说自话")

    # 负控：把一个已落地的角色从读数里删掉 ⇒ 同一个检查必须点名它。
    victim = next(t for t in ROLES if t in landed)
    pruned = [r for r in rows if str(r.get("role")) != victim]
    assert victim not in _targets_landed(TARGETS, pruned), (
        f"负控失败：把 {victim} 的行全删掉之后它还判「落地」⇒ 这条判据没有牙")


# ---------------------------------------------------------------- 2. ② 第二次调用命中


def test_a_second_call_hits() -> None:
    """判据 ②：样本角色的第二次调用 `hit > 0` 且命中比例 > 0（样本只有 2 个）。

    "只挑 2 个"是判据的一部分：省钱是这条设计里的取舍，不是偷懒 ——
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
    # 2026-10-21 口径修正：这条判据问的是"同一趟里同一角色两次调用是不是同一段前缀"，
    # 不是"跨趟也不许变" —— 跨趟会变正是我们要的（提示词改了、facts 挪了位置；
    # 2026-10-22 起两档的摘要本来就该不同）。所以按趟分组；跨趟的一致性由
    # `test_both_lean_tiers_are_recorded_and_fresh` 逐档守最新一趟。
    runs = _runs()
    rows = [row for run in runs for row in (run.get("rows") or [])]
    per_run = []
    for run in runs:
        group = list(run.get("rows") or [])
        if group:
            found = _digest_problems(TARGETS, group)
            per_run.extend(f'趟 {run.get("at")}：' + x for x in found)
    problems = per_run
    assert not problems, "；".join(problems)

    # 负控：在某一趟的读数里改一行的摘要 ⇒ 同一个函数必须看见。
    # 必须挑一个在这一趟里有两行的角色（`--hit-sample` 里的 M / C / L）：只改一行，
    # 两行的摘要就不一致了。挑只有一个 pass=1 行的角色时，改完仍然"自相一致" ——
    # 负控会空转（第一版就是这么写错的）。也不能跨趟改：两档摘要本来就不同，
    # 跨趟混着比会让负控无条件通过。
    run = _complete_run(runs, False) or _complete_run(runs, True)
    assert run is not None, "没有一趟完整的预热 ⇒ 负控没有素材"
    group = list(run.get("rows") or [])
    assert _digest_problems(TARGETS, group) == [], (
        f"趟 {run.get('at')} 内部本来就已经有摘要不一致：{_digest_problems(TARGETS, group)}")
    counts: dict[str, int] = {}
    for row in _measured_rows(group):
        role = str(row.get("role"))
        counts[role] = counts.get(role, 0) + 1
    victim_role = next(t for t, n in counts.items() if n >= 2 and t in ROLES)
    victim = next(r for r in _measured_rows(group) if str(r.get("role")) == victim_role)
    key = (str(victim.get("role")), int(victim.get("pass") or 1))
    poisoned: list[dict[str, Any]] = []
    done = False
    for row in group:
        copy = dict(row)
        if not done and (str(copy.get("role")), int(copy.get("pass") or 1)) == key:
            copy["prompt_sha256"] = "0" * 64
            done = True
        poisoned.append(copy)
    assert done, f"负控没改到任何一行（{key}）"
    assert _digest_problems(TARGETS, poisoned), (
        "负控失败：把一行的 prompt_sha256 换掉之后仍然判「一致」⇒ 这条判据没在读摘要")


def test_two_independent_renders_are_byte_identical(registry: Any) -> None:
    """判据 ③（渲染面）：同一角色两次独立渲染必须逐字节相同（十一个角色各判一遍）。

    这是"同一角色两次调用的 prefix 相同"的机械前提。正控用两次独立渲染
    （两次都过 `split_facts`）—— 它们共享的只有"静态事实"，而每步会变的两格
    已经被换成静态指路语（`promptstability.SYSTEM_PLACEHOLDERS`）。

    这一条跑在判据套件那一档（`conftest` 钉成开着）⇒ L 也渲染得出来，
    所以它必须和另外十个角色一样逐字节稳定。

    差异报告不是"变了"三个字：`stability_problem` 给出"从第几个字符起不同 + 前后各 80 字"，
    `dynamic_sections` 点名是哪一段变的。
    """
    ok: list[str] = []
    for role in ROLES:
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
    assert len(ok) == len(ROLES) == 11, ok


def _with_moved(role: str, registry: Any) -> dict[str, Any]:
    """改前的形态那份事实（两块原值进 system）—— 只给负控的段名报告用。"""
    facts = dict(W.CANONICAL_FACTS)
    facts["budget_left"] = ("0.400000 美元（上限 1.000000，已用 0.600000，读数来自 per_seam）")
    facts["notebook"] = "- [第 2 步] 记一笔：预算还剩一半"
    return facts


def test_putting_budget_left_back_into_the_system_makes_the_criterion_red(
        registry: Any) -> None:
    """负控（③ 的牙）：把 `budget_left` / `notebook` 塞回系统提示 ⇒ ③ 必须红。

    这就是改前那个形态（`agent_loop._system_at_step` 的前身每步把这两格重算进 system）：
    花销一变，`TASK_BUDGET` 那一段的字节就变 ⇒ 整条前缀作废。它必须让同一条判据红，
    并且点得出是哪一段变的、从第几个字符起不同。

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

        # 分离之后（今天的实现）同一对事实必须绿 —— 否则上面那条红就说明不了什么。
        ok_prev, ok_cur = _fact_pair(role, registry, split=True)
        assert _stability_problem(ok_prev, ok_cur) == "", (
            f"{role}：`split_facts` 之后 system 还不同 ⇒ 静态/动态分离没生效")
        checked.append(role)
    assert len(checked) == 2, checked


# ---------------------------------------------------------------- 4. 读数不许烂


def test_both_lean_tiers_are_recorded_and_fresh() -> None:
    """判据 ①：两档都能由装载入口取到，且各自记的摘要等于今天按同一档重算的。

    这一条守的是"读数会腐烂"：提示词一改（`agent_prompts.py` / `specs/*` / 预设），
    以前那份预热就作废了 —— 而 JSON 还在，命中率读数还很好看。红的时候不要改这里：
    按同一档重跑预热（两条命令写在 `docs/DEVELOPMENT-SPEC.md` §14.5）。

    读数一律从 `cache_readings(lean)` 取（唯一装载入口），不是自己从 `runs` 里挑：
    换档时挑错版本这件事，在这里表现为"这一档的摘要与今天重算的对不上"。

    受控缺席（Lean 关时的 L）也在这里判：装载结果里它必须是 `state="absent"`，
    而今天的重渲染必须仍然同样拒绝。L 被静默漏掉会红，L 被伪造一段摘要也会红。
    """
    rendered = {lean: _rendered(lean) for lean in TIERS}
    loaded = {lean: W.cache_readings(lean) for lean in TIERS}
    problems = _tier_freshness_problems(loaded, rendered)
    assert not problems, "；".join(problems)

    # 秘书那一档：两档的稳定头是同一份（它没有随开关改写的段），摘要就是进 system 的那段。
    prompt, _stable = W._secretary_head()
    for lean in TIERS:
        got = loaded[lean]["targets"][W.SECRETARY]
        assert got["prompt_sha256"] == _sha(prompt), (
            f"{_tier_label(lean)} 档秘书那一行的 prompt_sha256 与它进 system 的稳定头对不上")
        assert rendered[lean][W.SECRETARY]["system"].strip(), (
            "秘书的 system 是空的 ⇒ 稳定头没有进 system 位（改前那个形体）")
        assert rendered[lean][W.SECRETARY]["kind"] == "judge_system"


def test_the_two_lean_tiers_record_different_prompts() -> None:
    """判据 ②：两档记下来的摘要必须不同（相同 ⇒ 开关没影响渲染，或只落了一档）。

    实测（2026-10-22，p187）：A–H / V / M 十个角色两档摘要 10/10 不同；
    L 是"关档按设计缺席 vs 开档有摘要"的不同；秘书两档相同，且原因是结构性的
    （它的稳定头里没有随 Lean 开关改写的段）—— 判据逐角色判十一个角色，秘书不参与
    "必须不同"那一条，但"两档整体不能一模一样"那一条把它也算进去。
    """
    off = W.cache_readings(False)
    on = W.cache_readings(True)
    problems = _tier_difference_problems(off["targets"], on["targets"])
    assert not problems, "；".join(problems)
    print(f"{'target':<10}{'off_sha':<14}{'on_sha':<14}{'differ':>7}")
    for target in TARGETS:
        left = str(off["targets"][target].get("prompt_sha256") or "")[:12] or "(absent)"
        right = str(on["targets"][target].get("prompt_sha256") or "")[:12] or "(absent)"
        print(f"{target:<10}{left:<14}{right:<14}{str(left != right):>7}")


def test_dropping_one_tier_or_making_the_tiers_equal_makes_the_criteria_red(
        tmp_path: pathlib.Path) -> None:
    """判据 ③（反真空的两半）：只留一档 ⇒ 红；两档摘要相同 ⇒ 红。

    这两刀必须落在同一个装载入口与同一批纯函数上（`cache_readings` /
    `_tier_freshness_problems` / `_tier_difference_problems`）—— 判据本体与负控
    不是两套读法，否则"负控通过"证明不了"正控在读那个数"。
    """
    runs = [dict(run) for run in _runs()]
    rendered = {lean: _rendered(lean) for lean in TIERS}

    # 只留一档：把 Lean 开那一档从盘上的副本里全删掉。
    only_off = tmp_path / "dsh-only-off.json"
    W.save_readings(only_off, [run for run in runs if _tier_of(run) is not True])
    loaded = {lean: W.cache_readings(lean, path=only_off) for lean in TIERS}
    problems = _tier_freshness_problems(loaded, rendered)
    assert problems, "只留一档之后仍然判「两档都新鲜」⇒ 这条判据没有牙"
    assert any("Lean 开" in p for p in problems), problems
    assert loaded[True]["tri"] == "unknown", "开档装载没有报 unknown"
    assert loaded[False]["tri"] == "found", "只留关档时它的装载也坏了 ⇒ 上面的红说明不了什么"

    # 两档摘要相同：把开档那一档的主行摘要全换成关档的。
    off_digest = {t: str(rendered[False][t].get("prompt_sha256") or "") for t in TARGETS}
    poisoned: list[dict[str, Any]] = []
    for run in runs:
        copy = dict(run)
        if _tier_of(copy) is True:
            rows = []
            for row in (copy.get("rows") or []):
                row = dict(row)
                role = str(row.get("role"))
                if role in off_digest and int(row.get("pass") or 1) == 1:
                    row["prompt_sha256"] = off_digest[role]
                rows.append(row)
            copy["rows"] = rows
        poisoned.append(copy)
    same_path = tmp_path / "dsh-same-digests.json"
    W.save_readings(same_path, poisoned)
    same_loaded = {lean: W.cache_readings(lean, path=same_path) for lean in TIERS}
    assert _tier_freshness_problems(same_loaded, rendered), (
        "把开档的摘要换成关档的之后，新鲜度仍然判「对得上」⇒ 这一格在自说自话")
    problems = _tier_difference_problems(same_loaded[False]["targets"],
                                         same_loaded[True]["targets"])
    assert problems, "两档摘要改成一样之后仍判「不同」⇒ ② 没有牙"
    assert any("开关没有影响渲染" in p or "全一样" in p for p in problems), problems


# ---------------------------------------------------------------- 5. 装载（唯一入口）


def _load_under_env(lean: bool) -> dict[str, Any]:
    """把进程内的开关拨到某一档，再走装载入口的"按当前开关"那条路（lean=None）。

    收尾必须还原 env 并清 `agent_prompts` 的缓存：这两步是"不许缓存停在旧值"的
    另一半 —— 只改 env 不清缓存，`system_prompt` 还会按上一档渲染。
    """
    previous = os.environ.get("AGENTFLOW_LEAN_ENABLED")
    os.environ["AGENTFLOW_LEAN_ENABLED"] = "1" if lean else "0"
    AP.reset_toolchain_readings()
    try:
        return W.cache_readings()
    finally:
        if previous is None:
            os.environ.pop("AGENTFLOW_LEAN_ENABLED", None)
        else:
            os.environ["AGENTFLOW_LEAN_ENABLED"] = previous
        AP.reset_toolchain_readings()


def test_loading_the_cache_readings_picks_the_matching_lean_tier() -> None:
    """判据 ① / ②（装载面）：关档装载拿到关档那一趟、开档装载拿到开档那一趟。

    两档的 target 全集都是 12 个，但 L 的形态不同且必须如实区分：
    - 关档：`state="absent"`，理由来自 `RoleHidden`（不是"缺行"）；
    - 开档：`state="measured"`，且有 `write>0` 或 `hit>0` 的实证。

    这条同时钉住"最近一趟"：两档装载到的 `at` 必须不同（同一份文件里的两趟），
    否则很可能两档都读到了同一趟。
    """
    off = W.cache_readings(False)
    on = W.cache_readings(True)
    assert off["tri"] == "found", off
    assert on["tri"] == "found", on
    assert off["lean_enabled"] is False and on["lean_enabled"] is True
    assert off["prompt_version"] == AP.PROMPT_VERSION, off["prompt_version"]
    assert on["prompt_version"] == AP.PROMPT_VERSION, on["prompt_version"]
    assert off["at"] and on["at"] and off["at"] != on["at"], (off["at"], on["at"])

    assert set(off["targets"]) == set(TARGETS) == set(on["targets"])
    off_missing = [t for t, got in off["targets"].items() if got["state"] == "missing"]
    on_missing = [t for t, got in on["targets"].items() if got["state"] == "missing"]
    assert not off_missing, f"关档装载里这些 target 缺行：{off_missing}"
    assert not on_missing, f"开档装载里这些 target 缺行：{on_missing}"

    # L：关档缺席（RoleHidden），开档量过（write>0 或 hit>0）。
    assert off["targets"]["L"]["state"] == "absent", off["targets"]["L"]
    reason = off["targets"]["L"]["absent_reason"]
    assert "RoleHidden" in reason or "只在 Lean" in reason, reason
    assert on["targets"]["L"]["state"] == "measured", on["targets"]["L"]
    assert (on["targets"]["L"]["write"] > 0 or on["targets"]["L"]["hit"] > 0), (
        f"L 在开档装载里没有写/命中记录 ⇒ 它从未被真正量过：{on['targets']['L']}")

    for target in TARGETS:
        if target == "L":
            continue
        assert off["targets"][target]["state"] == "measured", (target, off["targets"][target])
        assert on["targets"][target]["state"] == "measured", (target, on["targets"][target])


def test_reloading_after_a_switch_flip_never_returns_the_stale_tier() -> None:
    """判据 ③（装载面）：同进程 关→开→关 三次装载，每次都换到对应版本。

    两次"关"必须逐格相等（同一趟、同一组 target 状态、同一组摘要）；"开"必须
    换到另一趟，且至少一个共享角色的摘要与关档不同 —— 否则"换到了"只是断言，
    没有读数作证。
    """
    first = _load_under_env(False)
    middle = _load_under_env(True)
    last = _load_under_env(False)

    assert first["tri"] == middle["tri"] == last["tri"] == "found", (first["tri"], middle["tri"], last["tri"])
    assert first["lean_enabled"] is False
    assert middle["lean_enabled"] is True
    assert last["lean_enabled"] is False

    assert first["at"] == last["at"], (first["at"], last["at"])
    assert first["targets"] == last["targets"], "两次关档装载逐格不相等 ⇒ 缓存停在了旧值"
    assert middle["at"] != first["at"], (middle["at"], first["at"])
    assert middle["targets"]["L"]["state"] == "measured"
    assert first["targets"]["L"]["state"] == "absent"
    assert (middle["targets"]["A"]["prompt_sha256"]
            != first["targets"]["A"]["prompt_sha256"]), (
        "同进程换档之后 A 的摘要没变 ⇒ 装载到的还是旧那一版")


def test_missing_tier_is_unknown_and_never_falls_back(tmp_path: pathlib.Path) -> None:
    """判据 ④（反真空）：删掉一档 ⇒ 该档装载报 unknown，且不回落到另一档。

    两刀都要落在同一个装载入口上：删掉开档只剩关档时，开档装载必须 `run is None`；
    删掉关档只剩开档时，关档装载同样。反方向也要有正控（另一档在同一个文件里读得到），
    否则"unknown"可能只是"文件读不到"。
    """
    runs = [dict(run) for run in W.load_readings(_READINGS)]
    for drop in (False, True):
        kept = [run for run in runs if _tier_of(run) is not drop]
        assert kept, f"删掉 {_tier_label(drop)} 之后什么都不剩 ⇒ 这条负控没有对照"
        path = tmp_path / f"only-{'on' if drop is False else 'off'}.json"
        W.save_readings(path, kept)
        got = W.cache_readings(drop, path=path)
        assert got["tri"] == "unknown", got["tri"]
        assert got["reason"] == W.CACHE_MISSING_FOR_LEAN_STATE, got["reason"]
        assert got["run"] is None, "找不到匹配那一档时返回了一趟 ⇒ 静默回落到另一版了"
        other = W.cache_readings(not drop, path=path)
        assert other["tri"] == "found", (drop, other["tri"])
        assert all(v["state"] != "missing" for v in other["targets"].values()), (
            f"{_tier_label(not drop)} 的对照趟本身就有缺行 ⇒ 上面那条 unknown 说明不了什么")


def test_unreadable_readings_are_unknown_not_found(tmp_path: pathlib.Path) -> None:
    """三态纪律的第三刀：文件读不到 ⇒ unknown（理由与"这一档没有"分开）。"""
    got = W.cache_readings(False, path=tmp_path / "dsh-no-such-readings.json")
    assert got["tri"] == "unknown", got["tri"]
    assert got["reason"] == W.CACHE_READINGS_UNREADABLE, got["reason"]
    assert got["run"] is None


def test_the_two_diagnostic_readings_say_what_they_measured() -> None:
    """两条诊断读数必须与文档 §14 的两句话一致（否则改的是文档，不是读数）。

    - 工具面不在缓存前缀里：同一份 system，带工具面预热过之后去掉工具面
    再发一次仍然命中（`tools_in_prefix=False`，实测 hit 11,904 / 12,126）；
    - 换一趟活也命中（2026-10-21 之后的口径）：另一份 system（不同 `task` /
    `task_id` / `depth` / `workspace_root`）在 system 里逐字节等于原来那一份（跨 run 会变的十格已经挪进 user 消息）⇒ `cross_run_hit` 的两行都该
    ≥90%。改前那两行是 `0 / 满`，那正是"预热只买到同一份前缀的第二次"的读数。

    这两条决定了"预热到底买到了什么"：改前买到的是"同一份前缀的第二次调用能省"；现在还包括"另一趟活能用同一段前缀"。`cross_run_prefix_chars`（离线算的字符数）因此必须等于整份 system 的长度
    —— 这是同一条判据的另一半。
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
