# -*- coding: utf-8 -*-
"""判据：秘书的**稳定头**进 `system`（2026-10-21，事务一）。

## 改前是什么

`Secretary.judge` 此前调的是 `seam.ask_json(_judge_prompt(kind, context))` ——
**不带 `system`**（`LlmSeam.ask` 的 `system` 缺省 `""`）。于是那 175 token 的稳定头
（抬头 + 这一类自己的问题）与"材料"挤在同一条 **user** 消息里，而材料每问一次都变。
真机读数（`2026-10-21` 改前，`--roles secretary --hit-sample secretary`）：
连发两趟都是 `hit=0 / miss=175`。

## 改法

稳定头走 `system=`（`llmseam` 早就有的通道：`LlmSeam.ask(system=…)` →
`ModelGateway.complete(system=…)` → `messages[0]` 的 `system` 位），材料留在 user。
**没有新造通道** —— 十个角色的循环走的就是同一个参数。

## ⚠️ 改完之后的实测：**`hit` 仍然是 0**，而且原因不在"头放在哪一位"

改后的读数（`python scripts/warm_prompt_cache.py --roles <十一个> --hit-sample M,C,secretary`）：

    十一个目标：A…M 的 `hit` 都在 98.9%–99.6%（前缀里有几万 token）；
    secretary：pass1 `miss=176 / hit=0`、pass2 `miss=176 / hit=0`（1 秒内连发两趟，逐字节相同）。

把同一份稳定头放进**不同长度的前缀**里再连发两次（本机 `2026-10-21` 实测，探针跑完即删）：

    前缀 176 token（生产形状，就是稳定头本身）：两次都 hit=0，隔 8s / 15s 再发仍是 0；
    前缀 407 token（稳定头 + 填充）：第一次 hit=128，第二次 hit=256；
    前缀 752 token：第一次 hit=384，第二次 hit=512；
    前缀 1557 token：第一次 hit=640，第二次 hit=1408。

⇒ **上游对"可缓存前缀"有一个长度下限**（实测落在 176 与 407 token 之间），
而秘书这一趟的整条提示词只有 176 token ⇒ 它一个可报告的命中都不会有。
这条判据能诚实断言的是**结构**那三件（下面 1–3），"第二次 hit>0" 在今天的
生产形状下**做不到**，读数里如实是 0 —— 所以本文件不把它写成判据（写了就是假绿：
把 `hit` 改成 1 也能过）。要让它命中，得让前缀越过那个下限，那是提示词体量的取舍。

## 判据（三条，每条带负控）

1. **稳定头真的走 `system` 位**：真机读数里 secretary 每一行的 `system_sha256` 非空、
   等于 `prompt_sha256`（被预热的那段就是发出去的 system），且**两趟同一个值**；
   `system_chars` 等于今天代码里那一段的长度（读数不许腐烂）。
   负控：把 `system_sha256` 清空（改前那个形态）⇒ 红。
2. **稳定头与可变部分分离**（渲染面）：材料变了，`system_sha256` 不变、`prompt_sha256` 变；
   两条合起来逐字节等于改前那条整提示词（只换了位置、没改一个字）。
   负控：把稳定头塞回 user（重放改前那一行）⇒ 两次调用的"前缀身份"必然不同 ⇒ 红。
3. 反真空：稳定头不是空串，且**真的**是"那个类别的问题"（逐字带那一类的词表）。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from typing import Any, Iterable, Mapping

import pytest

from agentflow import secretary as SEC

_REPO = pathlib.Path(__file__).resolve().parents[1]
_READINGS = _REPO / "tests" / "fixtures" / "prompt_cache_warm.json"


class _RecordingSeam:
    """替身缝：把**两条消息**分别记下来，并按剧本回一份合法结论。

    形状与 `LlmSeam.ask_json(prompt, *, system=…, task_id=…, note=…)` 一致 ——
    `Secretary.judge` 只会这么调它（多一个参数、少一个参数都会在这里 TypeError，
    而"它有没有真的走 system 位"正是这一组判据要问的）。
    """

    class _Call:
        def __init__(self, ok: bool) -> None:
            self.ok = ok
            self.problem = ""
            self.detail = ""
            self.recorded = ""
            self.prompt_sha256 = ""
            self.system_sha256 = ""

    def __init__(self, reply: Mapping[str, Any] | None = None) -> None:
        self.reply = dict(reply or {"decision": "可派", "reason": "照派", "basis": ["specs/"]})
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def ask_json(self, prompt, **kw):
        self.prompts.append(str(prompt))
        self.systems.append(str(kw.get("system") or ""))
        return dict(self.reply), self._Call(True)


def _secretary(tmp_path: pathlib.Path, seam: Any, *, role: str = "M") -> SEC.Secretary:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    return SEC.Secretary(role, root=root, seam=seam, enable_model=True)


# ---------------------------------------------------------------- 2. 分离（渲染面）

def test_the_stable_head_goes_into_system_and_the_material_stays_in_the_user_message(
        tmp_path: pathlib.Path) -> None:
    """正控（判据 ②）：材料变了 ⇒ `system_sha256` 一个字不变、`prompt_sha256` 变。

    "分离"这件事只有这两条读数能证明：只判"system 非空"时，把**整条**提示词复制一份
    进 system 也能过（那等于材料也进了前缀，第二次照样不命中）。
    """
    seam = _RecordingSeam()
    sec = _secretary(tmp_path, seam)
    first = sec.judge("duplicate_retry", {"input_key": "k-1", "rows": ["a"]})
    second = sec.judge("duplicate_retry", {"input_key": "k-2", "rows": ["b"]})
    assert first["checked"] is True and second["checked"] is True, (first, second)
    assert len(seam.systems) == 2 and len(seam.prompts) == 2, (seam.systems, seam.prompts)

    head_a, head_b = seam.systems
    user_a, user_b = seam.prompts
    # ① 稳定头：两次逐字节相同，且**非空**（反真空：不许是"没有 system"）。
    assert head_a.strip(), "秘书的 system 是空的 ⇒ 稳定头没有进 system 位"
    assert head_a == head_b, (head_a, head_b)
    # ② 可变部分：两次不同（材料真的换了）。
    assert user_a != user_b, "两份不同的材料渲染出了同一条 user 消息 ⇒ 这条判据没测到分离"
    # ③ 材料**不在** system 里（否则等于没分离）。
    for marker in ("k-1", "k-2"):
        assert marker not in head_a, (marker, head_a)
    # ④ 稳定头**不在** user 里（否则同一条提示词被发了两遍 = 前缀还是被材料绑住）。
    assert head_a.strip() not in user_a, user_a
    # ⑤ 两条合起来逐字节等于改前那条整提示词（"只换了位置、没改一个字"）。
    assert head_a + user_a == SEC._judge_prompt("duplicate_retry",
                                                {"input_key": "k-1", "rows": ["a"]}), (
        "system + user 与 `_judge_prompt` 的整条文本不同 ⇒ 拆分改了字节，那不是'挪位置'")


def test_the_head_is_the_one_of_that_kind_not_a_placeholder() -> None:
    """反真空：稳定头里逐字带着**这一类自己的词表**（不是一句占位语）。

    为什么单列：`judge()` 的校验按类别取词表（`JUDGE_VERDICTS[kind]`），
    而提示词若只写"按规矩回 JSON"，模型给出的结论会被校验层判成词表外 ⇒ 全都不采信。
    """
    for kind, verdicts in SEC.JUDGE_VERDICTS.items():
        head = SEC._judge_system(kind)
        assert kind in head, (kind, head[:120])
        for word in verdicts:
            assert word in head, (kind, word, head[:200])
        # 别的类别的词表不许整张混进来（同一根轴的词混进来就是"两处两个词表"）。
        others = [w for k, vs in SEC.JUDGE_VERDICTS.items() if k != kind for w in vs]
        unique = [w for w in others if w not in verdicts]
        leaked = [w for w in unique if w in head]
        assert not leaked, (kind, leaked, head[:200])


# ---------------------------------------------------------------- 1. 读数面（真机）

def _load_warm() -> Any:
    spec = importlib.util.spec_from_file_location(
        "_warm_prompt_cache_secretary", _REPO / "scripts" / "warm_prompt_cache.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _secretary_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """读数里秘书那一档的全部行（`pass=1` 冷写 / `pass=2` 第二次调用）。"""
    return [dict(r) for r in rows if str(r.get("role")) == "secretary"]


def _head_carried_problem(rows: Iterable[Mapping[str, Any]]) -> str:
    """判据 ①的本体：真机读数里秘书那一档**真的**把稳定头放在 system 位吗（空串 = 合格）。

    四件事，逐条对应一种"看起来做了、其实没做"的形态：

    1. 有读数（`pass=1` 与 `pass=2` 各一行 —— 没有就没有"第二次"这件事可谈）；
    2. `system_sha256` **非空**（空 = 改前那个形态：整条提示词在 user 位）；
    3. `system_sha256 == prompt_sha256`（被预热的那一段就是真正发出去的 system 本身，
       不是另抄一份摘要骗读数）；
    4. 两趟**同一个** `system_sha256`（同一份稳定头；不同 = 每问一次换一段前缀）。

    另外钉住"读数不许腐烂"：`system_chars` 必须等于**今天**代码里那段稳定头的长度。
    """
    hr = _secretary_rows(rows)
    passes = {int(r.get("pass") or 1) for r in hr}
    if not {1, 2} <= passes:
        return f"秘书那一档缺读数（pass={sorted(passes)}）⇒ 第二次调用这一格没量"
    digests = {str(r.get("system_sha256") or "") for r in hr}
    if "" in digests:
        return "秘书的读数里有 `system_sha256` 为空的行 ⇒ 稳定头不在 system 位（改前那个形态）"
    if len(digests) > 1:
        return f"秘书的读数里 `system_sha256` 有 {len(digests)} 种 ⇒ 两趟不是同一份稳定头"
    for row in hr:
        if str(row.get("system_sha256")) != str(row.get("prompt_sha256")):
            return (f"秘书那一行 `system_sha256` != `prompt_sha256` ⇒ "
                    f"被预热的那段提示词不是发出去的 system：{row}")
    want = len(SEC._judge_system("duplicate_retry"))
    bad = sorted({int(r.get("system_chars") or 0) for r in hr
                  if int(r.get("system_chars") or 0) != want})
    if bad:
        return (f"读数里的 `system_chars` {bad} 与今天代码里的稳定头 {want} 字对不上 ⇒ "
                "读数腐烂了（重跑 `python scripts/warm_prompt_cache.py`）")
    return ""


def test_the_recorded_secretary_calls_carry_the_head_in_system() -> None:
    """判据 ①（读数面）：真机上秘书那两趟**都是**"稳定头在 system 位"。

    这一条能诚实断言的是**结构**：`system_sha256` 非空、等于 `prompt_sha256`、两趟相同，
    且长度与今天的代码逐字一致。它**不**断言 `hit>0` —— 为什么见模块 docstring：
    上游对可缓存前缀有长度下限，而秘书整条提示词只有 176 token，实测三趟（0s / 8s / 15s）
    都是 `hit=0`；把 `hit` 写成判据就是假绿（把 0 改成 1 也能过）。

    实测数字照样打出来（回报里要贴的就是它，也是这条判据的读者最先看的那两个数）。
    """
    if not _READINGS.is_file():
        pytest.skip(f"读数不在盘上：{_READINGS}")
    runs = _load_warm().load_readings(_READINGS)
    rows = [row for run in runs for row in (run.get("rows") or [])]
    problem = _head_carried_problem(rows)
    assert problem == "", problem
    hr = _secretary_rows(rows)
    second = [r for r in hr if int(r.get("pass") or 1) == 2][-1]
    cache = dict(second.get("cache") or {})
    print(f"（秘书第二次调用：hit {cache.get('hit')} / miss {cache.get('miss')} token；"
          f"system {second.get('system_chars')} 字 / tokens_in {cache.get('tokens_in')}；"
          f"system_sha256 {str(second.get('system_sha256'))[:12]}；"
          f"两次命中率 {cache.get('hit_rate')}）")
    # 读数自洽（三态纪律的另一面）：上游给了两格时，它们相加必须等于 prompt_tokens。
    assert (int(cache.get("hit") or 0) + int(cache.get("miss") or 0)
            == int(cache.get("tokens_in") or 0)), cache


def test_clearing_the_system_digest_makes_the_criterion_red() -> None:
    """负控（① 的牙）：把 `system_sha256` 清空（= 稳定头塞回 user 的改前形态）⇒ 必红。

    为什么这一刀而不是"把 hit 改成 0"：改前的读数**本来就是** `hit=0`，改它证明不了什么；
    改前与改后**结构上**唯一的分界是"稳定头在不在 system 位"，而它由 `system_sha256`
    回答。清空它 = 退回改前那个形态。
    """
    if not _READINGS.is_file():
        pytest.skip(f"读数不在盘上：{_READINGS}")
    runs = _load_warm().load_readings(_READINGS)
    rows = [row for run in runs for row in (run.get("rows") or [])]
    assert _head_carried_problem(rows) == "", _head_carried_problem(rows)
    cleared: list[dict[str, Any]] = []
    for row in rows:
        copy = dict(row)
        if str(copy.get("role")) == "secretary":
            copy["system_sha256"] = ""
        cleared.append(copy)
    problem = _head_carried_problem(cleared)
    assert problem and "system 位" in problem, (
        f"清空 system_sha256 之后仍判合格 ⇒ 这条判据没在读那一格：{problem!r}")
    # 同一个负控的第二档：两趟的 system_sha256 不同（= 每问一次换一段前缀）也要红。
    mixed: list[dict[str, Any]] = []
    seen = False
    for row in rows:
        copy = dict(row)
        if str(copy.get("role")) == "secretary" and int(copy.get("pass") or 1) == 2:
            copy["system_sha256"] = "0" * 64
            seen = True
        mixed.append(copy)
    assert seen, "负控没改到秘书那一行的第二次调用"
    assert _head_carried_problem(mixed), "两趟的 system_sha256 不同却仍判合格 ⇒ 判据没在读摘要"


# ---------------------------------------------------------------- 负控：塞回 user

def test_putting_the_head_back_into_the_user_message_makes_the_criterion_red(
        tmp_path: pathlib.Path) -> None:
    """负控（判据 ② 的反面 ⇒ ① 红）：把稳定头塞回 user ⇒ 两次调用的前缀身份不同。

    怎么造"改前那个形态"：`ask_json(_judge_prompt(kind, ctx))`（**不带** system）。
    那正是 `judge()` 改前的那一行。于是：
    - `system_sha256` 是空 ⇒ 稳定头一个字节都没落在 system 位；
    - 两次的 `prompt_sha256` 不同（材料在第一行就变）⇒ 上游的前缀从第一个字符起就不同,
      "同一份稳定头的第二次"在结构上不可能命中（实测就是 `hit=0/miss=175`）。
    """
    seam = _RecordingSeam()
    sec = _secretary(tmp_path / "new", seam)
    sec.judge("duplicate_retry", {"input_key": "k-1", "rows": ["a"]})
    sec.judge("duplicate_retry", {"input_key": "k-2", "rows": ["b"]})

    class _OldShape(_RecordingSeam):
        """把稳定头塞回 user 的那种调用 —— **逐字重放改前那一行**：

            self.seam.ask_json(_judge_prompt(kind, context), task_id=…, note=…)

        注意：这里**不**走今天 `judge()`（它已经改成两条消息了），否则"旧形态"里
        录到的还是新形态的两条消息 —— 负控会空转（第一版就是这么写错的）。
        """

        def replay_old(self, kind: str, context: Mapping[str, Any]) -> None:
            self.ask_json(SEC._judge_prompt(kind, context))

    old = _OldShape()
    old.replay_old("duplicate_retry", {"input_key": "k-1", "rows": ["a"]})
    old.replay_old("duplicate_retry", {"input_key": "k-2", "rows": ["b"]})

    def _prefix_identity(seam_like: Any) -> list[str]:
        """两次调用的"前缀身份"：system（若空则退回 user 的开头）的摘要。"""
        out: list[str] = []
        for system, prompt in zip(seam_like.systems, seam_like.prompts):
            import hashlib

            material = system if system.strip() else prompt
            out.append(hashlib.sha256(material.encode("utf-8")).hexdigest())
        return out

    new_ids = _prefix_identity(seam)
    old_ids = _prefix_identity(old)
    # 正控：新形态两次的前缀身份相同（第二次能命中）。
    assert new_ids[0] == new_ids[1], (new_ids, seam.systems)
    # 负控：旧形态两次的前缀身份**不同** ⇒ 判据 ① 必红（这条断言就是"红"的读数）。
    assert old_ids[0] != old_ids[1], (
        "把稳定头塞回 user 之后两次的前缀身份仍然相同 ⇒ 这条负控是空转"
        "（材料必须在第一行就不同）")
    assert not old.systems[0].strip(), old.systems[0]


@pytest.mark.parametrize("kind", sorted(SEC.JUDGE_VERDICTS))
def test_every_kind_has_a_non_empty_and_stable_head(kind: str) -> None:
    """反真空（逐类别）：每一类的稳定头都非空，且**与材料无关**（调两次逐字节相同）。"""
    head = SEC._judge_system(kind)
    assert head.strip(), kind
    assert SEC._judge_system(kind) == head, kind
    # 材料变了，头不变（这一条是"它真的只取决于 kind"的机械证明）。
    a = SEC._judge_material({"input_key": "x"})
    b = SEC._judge_material({"input_key": "y"})
    assert a != b, (a, b)
    assert SEC._judge_prompt(kind, {"input_key": "x"}) == head + a, kind
    # 整条里仍然只有一个 JSON 契约（契约不许被拆成两份、各说一句）。
    assert head.count("只回一个 JSON 对象") == 1, head
    assert json.dumps({"decision": "可派"}, ensure_ascii=False)  # 只是让 json 进 import 面
