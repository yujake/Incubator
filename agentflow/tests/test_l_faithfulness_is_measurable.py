# -*- coding: utf-8 -*-
"""L 的"忠实复述 B 的证明链路"从文字义务变成机器读数：六条判据。

## 这一组为什么存在

审计里 L 唯一的硬缺口是这一条：动作 `formalize` 的职责句写着"把 B 登记的那条命题
与它的证明链路忠实搬进 Lean 源码"，而改前这一句话没有任何机器读数：

- `claim` 是一段自由文本 —— 钉不住"被形式化的是台账里哪一条"；
- 没有"`proof_text` 第 k 步 -> Lean 第 N 行"的对照产物；
- 机械层只核"声明名在源码里出现过"（`_declared_in_source`），不核每一步的落点；
- 于是 `verified` 只说明"检查器通过了我们写下的那份源码"，不说明"写下的是原文那条"。

## 六条判据与它们的改前红

| # | 判据 | 改前红（没有这一班的东西时它怎么红） |
|---|---|---|
| 1 | 12 步的证明、逐步映射 12/12 ⇒ 允许 verified（真 Lean 跑过，退出 0） | 改前没有 `coverage` 这一格 ⇒ 逐键断言当场红；也没有 `statement_id` 参数 ⇒ 传它就抛 TypeError |
| 2 | 故意漏一步（映射 11/12）⇒ 结论必须 unknown，且 `coverage.unmapped` 点名第几步 | 改前映射概念不存在 ⇒ 漏一步的源码照样报 verified（"看起来全对"） |
| 3 | 出现 `sorry` ⇒ unknown 且 `sorry_lines` 非空 | 改前 `sorry` 只有桥接层那一档（`uses_sorry` -> failed），没有"第几行有洞"的读数 |
| 4 | 缺 `statement_id` 或指向不存在的行 ⇒ 受控拒绝，盘上没有新 `.lean` | 改前不给编号也照样写盘 + 起检查器：拒绝这件事根本不存在 |
| 5 | `steps.jsonl` 每行都能在 `proof_text` 里找到对应片段（逐行断言，不许编造） | 改前没有这份文件 ⇒ 文件读不到即红 |
| 6 | 反真空：把 coverage 判据 monkeypatch 成恒 100% ⇒ 判据 2 必红 | 若判据 2 只在"读数说漏了一步"上成立，那它可能在读一句恒真的话；钉死读数之后它必须变红 |

## 零模型

全部用例只跑本机那一版真 Lean（绝对路径，不依赖 PATH）与直接构造的工作区，
一次模型调用都没有。工作区建在 `tmp_path` 下，`code/formal/` 里的产物随 tmp 一起
被清掉；判据自己不往仓库里写任何东西。

## 本机没有那一版 lean 时

需要真 Lean 的那几条断言的是另一档（结论 unknown 且带自检理由码），然后 skip ——
"跳过"不在选项里：跳过会把"没查成"读成"通过"。逐步对照这一格是纯文本读数，
与 Lean 在不在无关，所以 `steps_total` / `steps_mapped` 那几格在没有 Lean 时照样断言。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import schema as S
from agentflow.store import Store

#: 本机那一版真 Lean（与 `tests/test_l_formalizes_what_b_says.py` 同一口径）。
LEAN = pathlib.Path(r"D:\Incubator\_env\lean470\lean-4.7.0-windows\bin\lean.exe")
HAVE_LEAN = LEAN.is_file()

#: 台账里那条命题的编号（B 的 `stmt_id` 形态：六位数字）。
STMT_ID = "0007"

#: 证明的步数 - 1：第 1 步是 `n + 0 = n`，之后每一步多一个 `+ 0`，第 12 步收口。
LINKS = 11

#: 逐步对照的对照物：一条 12 步的证明（空行分段，见 `split_proof_steps` 的主口径）。
def proof_text() -> str:
    """12 步的 `proof_text`（一步一段；每步正文互不相同，好让引文可核）。"""
    steps = ["第 1 步：由自然数加法的定义，n + 0 与 n 是同一个项，故 n + 0 = n。"]
    for k in range(2, LINKS + 1):
        steps.append(
            f"第 {k} 步：把第 {k - 1} 步的等式代进左因子，得 n + 0（共 {k} 个）= n。")
    steps.append(f"第 {LINKS + 1} 步：第 {LINKS} 步的等式正是目标命题，故命题成立。")
    return "\n\n".join(steps)


#: 命题正文（与 Lean 里的定理逐字对应；台账里 `statement_full` 就是它）。
def body_text() -> str:
    """`statement_full`：对一切自然数 n，n + 0 + ... + 0 = n。"""
    return "对一切自然数 n，n" + " + 0" * LINKS + " = n。"


def lean_source(*, mapped_steps: set[int] | None = None, sorry_at_final: bool = False) -> str:
    """带 `-- step <k>` 落点标记的 Lean 源码（每一步一块，最后一步收口）。

    `mapped_steps`：哪些步留标记（缺的那一步就是"漏了一步"）；`sorry_at_final`：
    最后一步用 `sorry` 收口（含 sorry 的文件照样编译通过，退出码 0）。
    """
    mapped = set(range(1, LINKS + 2)) if mapped_steps is None else set(mapped_steps)
    out = ["import Init.Data.Nat.Basic", "", "namespace LFaithful", "",
           f"theorem faithful_chain (n : Nat) : n{' + 0' * LINKS} = n := by"]
    for k in range(1, LINKS + 1):
        if k in mapped:
            out.append(f"  -- step {k}")
        if k == 1:
            out.append("  have h1 : n + 0 = n := rfl")
        else:
            out.append(f"  have h{k} : n{' + 0' * k} = n := by rw [h{k - 1}]")
    if LINKS + 1 in mapped:
        out.append(f"  -- step {LINKS + 1}")
    out.append("  sorry" if sorry_at_final else f"  exact h{LINKS}")
    out.extend(["", "end LFaithful", ""])
    return "\n".join(out)


def _lean_env(mp: pytest.MonkeyPatch) -> None:
    """把这一趟的 Lean 落在本机那一版上（绝对路径），并清掉自检读数缓存。"""
    from agentflow import agent_prompts as AP
    from agentflow import leantoolchain as LT

    mp.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    if HAVE_LEAN:
        mp.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


@pytest.fixture()
def lean_env(monkeypatch: pytest.MonkeyPatch):
    """函数级的 Lean 环境（每条用例各自准备、各自清缓存）。"""
    from agentflow import agent_prompts as AP
    from agentflow import leantoolchain as LT

    _lean_env(monkeypatch)
    yield
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


def _make_ws(tmp_path: pathlib.Path, *, ledger: bool = True,
             proof: str | None = None, body: str | None = None) -> pathlib.Path:
    """造一个工作区：`data/statements.json` 里有（或没有）B 登记的那一条命题。"""
    ws = tmp_path / "ws"
    store = Store(ws)
    store.init()
    rows: list[dict] = []
    if ledger:
        text = body_text() if body is None else body
        rows.append({
            "stmt_id": STMT_ID,
            "statement_full": text,
            "statement_text": text,
            "proof_text": proof_text() if proof is None else proof,
            "kind": "theorem",
            "status": "active",
            "origin": "own_result",
        })
    (ws / "data" / "statements.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": rows}, ensure_ascii=False),
        encoding="utf-8")
    return ws


def _run(ws: pathlib.Path, *, source: str, statement_id: str | None = STMT_ID,
         claim: str | None = None) -> dict:
    """在工作区里跑一次 `AgentL.formalize`（真 Lean；零模型）。"""
    from agentflow.agent_l import AgentL

    agent = AgentL(Store(ws), workspace_root=ws)
    return agent.formalize(
        body_text() if claim is None else claim,
        source=source,
        statement_id=statement_id,
    )


def _lean_files(ws: pathlib.Path) -> list[str]:
    """工作区里现有的 `.lean`（用于"被拒时一个字节都不写"的断言）。"""
    return sorted(p.name for p in (ws / "code" / "formal").glob("*.lean"))


def _flat(text: object) -> str:
    """逐字比较用的口径（只压连续空白）。"""
    return " ".join(str(text or "").split())


@pytest.fixture(scope="module")
def mapped_run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """判据 1 / 5 共用的那一趟：12 步证明 + 逐步映射 12/12 + 真 Lean。"""
    ws = _make_ws(tmp_path_factory.mktemp("l-faithful"))
    with pytest.MonkeyPatch.context() as mp:
        _lean_env(mp)
        data = _run(ws, source=lean_source())
    return {"ws": ws, "data": data}


# ============================================================ 判据 1：12/12 ⇒ 允许 verified
def test_twelve_mapped_steps_allow_verified(mapped_run: dict) -> None:
    """12 步的证明、逐步映射 12/12 ⇒ 结论可以是 verified，且真 Lean 跑过（退出 0）。

    改前红：改前返回值里没有 `coverage` 这一格（`data["coverage"]` 直接 KeyError），
    也没有 `statement_id` 参数（传它就抛 `TypeError: unexpected keyword argument`）。

    读数的分工在这里第一次被钉住：`checker_status` 是检查器原话、`status` 是叠加了
    逐步对照之后的综合结论。两者都必须是 verified，但它们是两个格子（判据 2 会让
    它们分开，届时"检查器通过"与"这一趟算数"必须各自可读）。
    """
    data = mapped_run["data"]
    cov = dict(data.get("coverage") or {})
    assert str(data.get("statement_id")) == STMT_ID, data
    assert str(data.get("statement_source")) == "explicit", data
    assert data.get("refused") is False, data
    assert int(cov.get("steps_total") or 0) == LINKS + 1, cov
    assert int(cov.get("steps_mapped") or 0) == LINKS + 1, cov
    assert list(cov.get("unmapped") or []) == [], cov
    assert list(cov.get("sorry_lines") or []) == [], cov
    assert list(cov.get("extra_steps") or []) == [], cov
    assert str(data.get("faithfulness")) == "complete", data.get("faithfulness")
    assert str(data.get("steps_path")) == f"code/formal/faithful_chain.steps.jsonl", data
    assert (mapped_run["ws"] / str(data["steps_path"])).is_file(), "逐步对照没有落盘"
    assert data.get("written") is True, data

    if not HAVE_LEAN:
        assert data.get("status") == "unknown", data
        assert str(data.get("reason")) in ("lean_selfcheck_off", "lean_selfcheck_unusable",
                                          "lean_selfcheck_unknown"), data
        pytest.skip(f"本机没有 {LEAN} ⇒ 这一条只在 unknown 档上成立（逐步对照已断言）")
    assert data.get("status") == "verified", data
    assert str(data.get("checker_status")) == "verified", data
    assert data.get("exit_code") == 0, data
    assert "axioms" in str(data.get("verifier_output") or ""), data.get("verifier_output")


# ============================================================ 判据 2：漏一步 ⇒ unknown
def _criterion_two_violations(data: dict) -> list[str]:
    """判据 2 的判据本体（返回违反项；空清单 = 通过）。

    单独抽出来是因为判据 6 要复用它：反真空那一条打的正是"把 coverage 钉成恒 100%
    之后，这一条会不会红"。抽出来之后"必红"指的就是这个函数返回非空。
    """
    bad: list[str] = []
    cov = dict(data.get("coverage") or {})
    if str(data.get("status")) != "unknown":
        bad.append(f"漏一步时综合结论不是 unknown（status={data.get('status')!r}）")
    if str(data.get("reason")) != "faithfulness_incomplete":
        bad.append(f"理由码不是 faithfulness_incomplete（{data.get('reason')!r}）")
    if list(cov.get("unmapped") or []) != [LINKS + 1]:
        bad.append(f"coverage.unmapped 没有点名第 {LINKS + 1} 步（{cov.get('unmapped')}）")
    if int(cov.get("steps_total") or 0) != LINKS + 1:
        bad.append(f"steps_total 不是 {LINKS + 1}（{cov.get('steps_total')}）")
    if int(cov.get("steps_mapped") or 0) != LINKS:
        bad.append(f"steps_mapped 不是 {LINKS}（{cov.get('steps_mapped')}）")
    if str(data.get("faithfulness")) != "incomplete":
        bad.append(f"faithfulness 不是 incomplete（{data.get('faithfulness')!r}）")
    if HAVE_LEAN and str(data.get("checker_status")) != "verified":
        bad.append("检查器那一档没有留在 checker_status 里（两件事必须分开写）"
                   f"：{data.get('checker_status')!r}")
    return bad


def test_one_missing_step_forces_unknown_and_names_it(
        tmp_path: pathlib.Path, lean_env: None) -> None:
    """故意漏一步（映射 11/12）⇒ 结论必须 unknown，且 `coverage.unmapped` 点名第 12 步。

    改前红：改前没有任何逐步对照的概念 —— 同一份"漏了一步"的源码照样拿到
    `status="verified"`（检查器当然通过：漏的那一步是注释标记，不影响编译）。

    反真空的一半也在这里：`checker_status` 必须仍然是 verified（否则"unknown"不是
    忠实复述这一格压下来的，而是检查器没过 —— 那就证明不了硬规则真的在起作用）。
    """
    ws = _make_ws(tmp_path)
    data = _run(ws, source=lean_source(mapped_steps=set(range(1, LINKS + 1))))
    assert data.get("written") is True, data
    bad = _criterion_two_violations(data)
    assert bad == [], "判据 2 没通过：\n  - " + "\n  - ".join(bad)
    if HAVE_LEAN:
        assert str(data.get("checker_status")) == "verified", (
            "这一条的前提是检查器通过、只有逐步对照说不行："
            + json.dumps({k: data.get(k) for k in ("status", "reason", "checker_status")},
                         ensure_ascii=False))


def test_criterion_two_is_not_vacuous(
        tmp_path: pathlib.Path, lean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把 coverage 判据 monkeypatch 成"恒 100%" ⇒ 判据 2 必红。

    做法：只替换 `_Formalize._faithfulness_reading` 这一个方法（判据 2 读的就是它），
    让它把 steps_mapped 报成 steps_total、unmapped 报成空、how 全写成直接对应。
    源码与输入一个字都不动（还是那份漏了第 12 步标记的源码）。

    它红了才说明判据 2 真的在读这份读数，而不是在读一句恒真的话。
    """
    from agentflow.agent_l.formalize import _Formalize

    real = _Formalize._faithfulness_reading

    def lying(self, *, proof_text: str, source: str) -> dict:
        reading = real(self, proof_text=proof_text, source=source)
        cov = dict(reading.get("coverage") or {})
        cov.update({
            "steps_mapped": cov.get("steps_total"),
            "unmapped": [],
            "sorry_lines": [],
            "extra_steps": [],
            "verdict": "complete",
            "why": "",
        })
        rows = [dict(row, how="直接对应", lean_lines=row.get("lean_lines") or [1, 1])
                for row in (reading.get("rows") or [])]
        return {"coverage": cov, "rows": rows}

    # ---- 正控：不替换时判据 2 是绿的（否则下面的"红"说明不了什么）
    ws = _make_ws(tmp_path / "ok")
    good = _run(ws, source=lean_source(mapped_steps=set(range(1, LINKS + 1))))
    assert _criterion_two_violations(good) == [], "正控没成立：真读数下判据 2 本来就没过"

    # ---- 替换成恒 100% ⇒ 判据 2 必须红
    monkeypatch.setattr(_Formalize, "_faithfulness_reading", lying)
    ws2 = _make_ws(tmp_path / "lie")
    lied = _run(ws2, source=lean_source(mapped_steps=set(range(1, LINKS + 1))))
    bad = _criterion_two_violations(lied)
    assert bad, (
        "把 coverage 钉成恒 100% 之后判据 2 仍然全绿 ⇒ 判据 2 是真空的"
        "（它没有真的读那份读数）")
    print("\n[反真空] 钉成恒 100% 之后判据 2 报出的违反项：", bad)


# ============================================================ 判据 3：sorry ⇒ unknown
def test_sorry_forces_unknown_and_is_located(tmp_path: pathlib.Path, lean_env: None) -> None:
    """出现 `sorry` ⇒ 结论必须 unknown，且 `coverage.sorry_lines` 非空。

    改前红：改前含 `sorry` 的源码只有桥接层那一档（`uses_sorry`），而 L 把它折成
    `failed`；"这份证明里有几个洞、在第几行"没有任何读数。

    这条判据钉的是"含 sorry 的文件照样编译通过（退出码 0），那不是证明"：
    检查器那一档可能是 verified（源码里 sorry 被 `#print axioms` 记成 sorryAx
    时也可能先被判 uses_sorry），但综合结论只能是 unknown。
    """
    ws = _make_ws(tmp_path)
    data = _run(ws, source=lean_source(sorry_at_final=True))
    cov = dict(data.get("coverage") or {})
    assert list(cov.get("sorry_lines") or []), f"没有点名 sorry 在第几行：{cov}"
    assert str(data.get("status")) == "unknown", data
    assert str(data.get("faithfulness")) == "holes", data.get("faithfulness")
    if HAVE_LEAN:
        assert str(data.get("reason")) == "faithfulness_sorry", data
        assert int(data.get("exit_code") or 0) == 0, (
            "这一条的前提是『含 sorry 的文件编译通过了』：" + str(data.get("exit_code")))
        assert str(data.get("checker_status")) in ("verified", "failed"), data.get("checker_status")
    else:
        assert str(data.get("reason")) in ("lean_selfcheck_off", "lean_selfcheck_unusable",
                                          "lean_selfcheck_unknown"), data
    # 逐行核对：点名的行确实含 sorry（不是把别的行算进去）
    text = (ws / str(data["path"])).read_text(encoding="utf-8").split("\n")
    for line in cov["sorry_lines"]:
        assert "sorry" in text[int(line) - 1], (line, text[int(line) - 1])


# ============================================================ 判据 4：受控拒绝，一个字节都不写
def test_a_missing_or_unknown_statement_is_refused_without_writing(
        tmp_path: pathlib.Path, lean_env: None) -> None:
    """缺 `statement_id` 且认不出来源、或指向不存在的行 ⇒ 受控拒绝，盘上没有新 `.lean`。

    改前红：改前 `formalize` 连 `statement_id` 这个形参都没有（传它抛 TypeError），
    而没有编号的调用会径直写盘并起检查器 —— "拒绝"这件事根本不存在。

    三种拒绝各一格（理由码不同，处置也不同）：
    - 编号指向不存在的行 ⇒ `statement_not_found`；
    - 不给编号、claim 又是转述（与台账正文不同）⇒ `statement_not_found`（认不出来源）；
    - 行在、正文在，但 `proof_text` 是空的（概念行就是这种）⇒ `statement_without_proof`。
    """
    ws = _make_ws(tmp_path)
    assert _lean_files(ws) == [], "前提：这个工作区里还没有 .lean"

    # ---- ① 编号指向不存在的行
    missing = _run(ws, source=lean_source(), statement_id="9999")
    assert missing.get("refused") is True, missing
    assert str(missing.get("reason")) == "statement_not_found", missing
    assert missing.get("written") is False, missing
    assert str(missing.get("path")) == "", missing
    assert _lean_files(ws) == [], f"被拒了却写下了 .lean：{_lean_files(ws)}"

    # ---- ② 不给编号 + claim 是转述（台账里有行，但认不出来是哪一条）
    paraphrased = _run(ws, source=lean_source(), statement_id=None,
                       claim="自然数加零不变")
    assert paraphrased.get("refused") is True, paraphrased
    assert str(paraphrased.get("reason")) == "statement_not_found", paraphrased
    assert paraphrased.get("written") is False, paraphrased
    assert _lean_files(ws) == [], f"被拒了却写下了 .lean：{_lean_files(ws)}"

    # ---- ③ 行在、正文在，但证明是空的
    ws2 = _make_ws(tmp_path / "noproof", proof="")
    noproof = _run(ws2, source=lean_source())
    assert noproof.get("refused") is True, noproof
    assert str(noproof.get("reason")) == "statement_without_proof", noproof
    assert noproof.get("written") is False, noproof
    assert _lean_files(ws2) == [], f"被拒了却写下了 .lean：{_lean_files(ws2)}"

    # ---- 改前红的正面证据：改前这几个调用一个都不会被拒（连参数都没有）
    import inspect

    from agentflow.agent_l import AgentL

    assert "statement_id" in inspect.signature(AgentL.formalize).parameters, (
        "AgentL.formalize 没有 statement_id 形参 ⇒ 这一组判据的输入面没接上")


# ============================================================ 判据 5：每条引文都能回到原文
def test_every_steps_line_quotes_the_proof_text(mapped_run: dict) -> None:
    """`steps.jsonl` 的每一行都能在 `proof_text` 里找到对应片段（逐行断言，不许编造）。

    改前红：改前没有这份文件（`data["steps_path"]` 那一格不存在，文件也读不到）。

    四件事逐行核：
    - 行数 = 步数、`proof_step` 从 1 连续到 12（没有跳号、没有补造）；
    - `quote` 非空且逐字出现在 `proof_text` 里（这是"不许编造"的机器形态）；
    - `how` 在四档词表里；
    - 映射过的步骤，`lean_lines[0]` 那一行真的是 `-- step <k>`（引文与落点都指得回去）。
    """
    from agentflow.agent_l.formalize import HOW_VALUES, QUOTE_CHARS, STEP_ROW_KEYS

    ws = mapped_run["ws"]
    data = mapped_run["data"]
    rel = str(data.get("steps_path") or "")
    assert rel, "返回值里没有 steps_path"
    path = ws / rel
    assert path.is_file(), f"逐步对照没有落盘：{path}"
    raw = path.read_bytes()
    assert b"\r\n" not in raw, "落盘的行尾必须是 \\n"
    lines = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    assert len(lines) == LINKS + 1, f"对照表有 {len(lines)} 行，证明有 {LINKS + 1} 步"
    text = _flat(proof_text())
    lean_lines = (ws / str(data["path"])).read_text(encoding="utf-8").split("\n")
    for index, row in enumerate(lines, 1):
        assert set(row) == set(STEP_ROW_KEYS), row
        assert row["proof_step"] == index, (index, row)
        quote = str(row["quote"] or "")
        assert quote, f"第 {index} 步的引文是空的"
        assert len(quote) <= QUOTE_CHARS, (index, len(quote))
        assert quote in text, f"第 {index} 步的引文在 proof_text 里找不到：{quote!r}"
        assert str(row["how"]) in HOW_VALUES, (index, row["how"])
        spans = list(row["lean_lines"] or [])
        if str(row["how"]) == "未映射":
            assert spans == [], (index, spans)
            continue
        assert len(spans) == 2 and 1 <= spans[0] <= spans[1] <= len(lean_lines), (index, spans)
        assert lean_lines[spans[0] - 1].strip() == f"-- step {index}", (
            f"第 {index} 步的落点不是它自己的标记行：{lean_lines[spans[0] - 1]!r}")


# ============================================================ 附加：how 的四个取值都要能出现
def test_the_how_vocabulary_is_actually_produced() -> None:
    """`how` 的四档是活的：补假设 / 自足定义 / 直接对应 / 未映射 都能被产出。

    改前红：改前根本没有 `how` 这一格。

    这一条只跑纯文本读数（不跑 Lean）：它判的是"分类器接上了"，不是"Lean 接受了"。
    所以下面几份源码只要行内形态对就行，不必编译通过。
    """
    from agentflow.agent_l.formalize import HOW_VALUES, faithfulness_reading

    # 第 1 步：直接对应（块里只有 have）；第 2 步：补假设（块里有 -- assume）；
    # 第 3 步：直接对应。`def` 在定理之前（不在任何一步的落点里）⇒ 不该被算进任何一步。
    source = "\n".join([
        "import Init.Data.Nat.Basic", "", "namespace LFaithful", "",
        "def zeroOf (n : Nat) : Nat := 0", "",
        "theorem probe (n : Nat) : n + 0 = n := by",
        "  -- step 1",
        "  have h1 : n + 0 = n := rfl",
        "  -- step 2",
        "  -- assume 这里是原文隐含的假设 n >= 0",
        "  exact h1",
        "  -- step 3",
        "  exact h1",
        "",
        "end LFaithful", "",
    ])
    reading = faithfulness_reading(proof_text="甲。乙。丙。", source=source)
    how = [row["how"] for row in reading["rows"]]
    assert how == ["直接对应", "补假设", "直接对应"], how
    added = reading["coverage"]["assumptions_added"]
    assert [item["proof_step"] for item in added] == [2], added
    assert "n >= 0" in str(added[0]["text"]), added

    # 未映射：把第 3 步的标记去掉
    without = faithfulness_reading(
        proof_text="甲。乙。丙。",
        source=source.replace("  -- step 3\n", ""))
    assert [row["how"] for row in without["rows"]][2] == "未映射", without["rows"]

    # 自足定义：这一步的落点里有一行 `def`（原文用了私有定义，这边换成自足定义）
    defined = "\n".join([
        "theorem probe2 (n : Nat) : n + 0 = n := by",
        "  -- step 1",
        "  def helperZero : Nat := 0",
        "  exact rfl",
        "",
    ])
    got = faithfulness_reading(proof_text="甲。", source=defined)
    assert [row["how"] for row in got["rows"]] == ["自足定义"], got["rows"]

    produced = set(how) | {"未映射", "自足定义"}
    assert produced == set(HOW_VALUES), (produced, HOW_VALUES)


# ============================================================ 附加：台账为空时那一档
def test_an_empty_ledger_is_reported_as_unknown_not_as_passed(
        tmp_path: pathlib.Path, lean_env: None) -> None:
    """台账里一行命题都没有 ⇒ 忠实复述这一格是 unknown（"没有对象"），不是"通过"。

    这一档必须显式可见：它是本班唯一一条"允许在没有原文的情况下继续"的路径
    （老判据 `test_l_formalizes_what_b_says.py` 的那几趟就是在没有台账的工作区里跑的），
    所以它必须有自己的一格读数 —— 否则"没有可对照的原文"与"逐步对照全对上"在
    返回值里长得一模一样。

    改前红：改前没有 `coverage` / `faithfulness` 这两格，这一档根本无处可报。
    """
    ws = _make_ws(tmp_path, ledger=False)
    data = _run(ws, source=lean_source(), statement_id=None)
    cov = dict(data.get("coverage") or {})
    assert str(data.get("statement_source")) == "no_ledger", data.get("statement_source")
    assert str(data.get("statement_id")) == "", data.get("statement_id")
    assert str(data.get("faithfulness")) == "unknown", data.get("faithfulness")
    assert int(cov.get("steps_total") or 0) == 0, cov
    assert int(cov.get("steps_mapped") or 0) == 0, cov
    assert "没有对象" in str(cov.get("why") or ""), cov
    assert str(data.get("steps_path")) == "", data
