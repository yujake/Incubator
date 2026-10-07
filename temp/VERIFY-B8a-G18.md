# `G-18` 的**独立**验收（主控自己打，真 Lean 后端）

工具：`temp/_verify_g18.py`（我写的四条成对控制）；原始输出 `temp/verify-g18.txt`；
另有一次模块自检：`temp/verify-g18-selftest.txt`（离线）与 `temp/verify-g18-selftest-lean.txt`（**Lean 在 PATH**）。
观测：**2026-09-26T04:0x**，后端 = `Lean (version 4.7.0, …, commit 6fce8f7d5cd1, Release)`。

```
=== fail=0 ===
```

## 四条控制（我用**真后端**逐条打，不是看实现者的摘要）

| # | 情形 | 期望 | 实测（`status` / `missing_imports` / `evidence_of` 派生的三态） |
|---|---|---|---|
| ① | `imports=("Mathlib",)`（裸 lean 无 lake 上下文） | 库不可得 ⇒ **没查成** | `import_unavailable` / `['Mathlib']` / `checked=False, proved=False`，reason 逐字"检查器说找不到这些包…**这次检查根本没发生（编译没开始）**" ✅ |
| ② | **注入语法错**（`imports=()`，源码缺证明项） | **必须仍是 `compile_error`** | `compile_error` / `[]` / `checked=True, proved=False` ✅ ⭐ **核心负控成立：新判据没有把"真编译错"吞成"库不可得"** |
| ③ | `imports=("Nonexistent.Pkg",)` | 库不可得 | `import_unavailable` / `['Nonexistent']` / `checked=False` ✅ |
| ④ | 内核级真命题（`Nat.add_comm`，`imports=()`） | 证明通过 | `verified` / `[]` / `checked=True, proved=True, evidence_kind='proof'` ✅ |

模块自检（`formalgw.selftest()`）在 **Lean 在 PATH** 时也 exit 0，并打印
`真实运行：status=verified exit_code=0 axioms=[]`；其中"负控④：库不可得必须归 `import_unavailable`
且必须带包名"是真后端上跑的（`formalgw.py` 的 `selftest` 内）。

## ⚠️ 我在这条探针上自己错了两次（累计 9 次，全部由成对控制抓出）

| # | 我写错的判据 | 真因 | 抓住它的那一半 |
|---|---|---|---|
| 6 | 在 `check_lean()` 的返回里找 `checked`/`verified` | **判据看错了层**：三态是由 `evidence_of()` 派生的（`formalgw.py:923-932`） | 读数全是 `None` ⇒ 与"应该有位"矛盾 |
| 7 | 用键名 `verified` | `evidence_of()` 用的是 **`proved`**；`verified` 是**工具层契约**里的键 | ②④ 两条的实测值明显是对的、判据却红 |
| 8 | 要求"没查成时 `proved` 必须是 `None`" | 三态是**一对** `(checked, proved)`，`(False,False)` 与 `(True,False)` 已可区分 | ① 红而 ②④ 绿 ⇒ 说明判据把两种情形混了 |

⭐ **一个值得登记的小观察（`G-45`/`G-47` 同族，我作为 API 消费者真的踩了）**：
`evidence_of()` 用 `proved`，而 `verify.check_formal` 的**契约字符串**用 `verified`
（`{'checked','verified','claim','reason','detail','verifier_output',…}`）——
**同一个概念跨两层两个名字**。它不是缺陷（两层的读者不同），但**是一个真实的陷阱**：
我在第一次写探针时按工具层的名字去读底层返回值，当场读成 `None`。
⇒ 建议：在一处（`formalgw.evidence_of` 的 docstring 或 `DEVELOPMENT.md`）写清
"`evidence_of` 的 `proved` ↔ 工具层契约的 `verified` 是同一个量"，**避免下一个消费者再踩**。
（这条已交给 B6/登记册，编号待它们给。）
