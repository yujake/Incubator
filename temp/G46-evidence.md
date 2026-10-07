# `G-46`（新登记）：`noai_gate --paths` 的**逗号输入会被静默读成一条路径** ⇒ 假 clean

观测 2026-09-26T02:46:12（原始输出 `temp/noai-paths-format.txt`）
命令与退出码（**直跑、不接管道**）：

```
A) python scripts/noai_gate.py --paths "src/agentflow/schema.py,src/agentflow/verify.py"
   → [clean] required_approvals=0
     clean：1 条改动路径均未命中禁改区（清单 21 条）⇒ 无需额外人工批准。      exit=0   ← 假 clean

B) python scripts/noai_gate.py --paths "src/agentflow/schema.py" "src/agentflow/verify.py"
   → [requires_human] required_approvals=2
     命中：src/agentflow/schema.py, src/agentflow/verify.py                  exit=1   ← 正确

C) python scripts/noai_gate.py --paths "src/agentflow/schema.py"
   → [requires_human] required_approvals=2  （2 条命中：schema-migration / eval-criteria）
                                                                              exit=1   ← 正确
```

## 缺陷形态

`--paths` 是 `nargs="*"`（`scripts/noai_gate.py:1612`）⇒ **逗号不是分隔符**。
调用方把一堆路径用逗号拼起来（这是最常见的手写方式，我在本轮就**真的这么写了**）
时，整串被当成**一条**路径；它当然不匹配任何 glob ⇒ 报 `clean`、`required_approvals=0`、**exit 0**。

**为什么这是缺陷而不是"用错了参数"**：门自己的三态纪律写的是"没查成 ⇒ 2，绝不等于 clean"。
这里的情形是"**调用方想查 16 条，门只查了 1 条（而且那 1 条是拼错的字符串），却给出绿的结论**"。
它与 `G-38`（`--git` 可被提交绕过 / 看不见未跟踪文件）**同族**：
**门的输入管线能把"我查了 N 条"变成"我查了别的"，而结论照样是绿的。**

**波及面（如实说）**：
- 我实测的是手写 `--paths`；`release_check` 那边走的是 `--changed-file`（每行一条）+
  逐条 argv，**未受此影响**（本批不声称它受影响，也不排除 —— **未核实**）。
- 同理，`--paths` 里带**换行**的值（有人把一个文件的全文当一条参数塞进来）也会静默变成一条。

## 修法（主控口径）

**不许"自动按逗号切分"**：逗号在 Windows 文件名里是合法字符 ⇒ 切分会把一条真路径变成两条，
方向反过来同样是假话。正确处置是**如实报"没查成"**：

- 若任一 `--paths` 取值含 `,` 或换行 ⇒ 以 **`unknown(2)`** 结束，
  消息里给出正确用法（`--paths a b c` 多条空格分隔，或 `--changed-file <每行一条>`），
  并**原样回显那个可疑取值**（好让调用方一眼看出自己拼错了）。
- 保持：空格分隔的多条、`--changed-file`、`--stdin`、`--git` 四条通路**逐字不变**。

## 验收判据（成对）

- **负控一**：`--paths "a.py,b.py"` ⇒ **exit 2**、`[unknown]`，**不是** `clean(0)`（今天红）。
- **负控二**：`--paths "<含换行的字符串>"` ⇒ 同上（今天红）。
- **正控一**：`--paths "src/agentflow/schema.py" "src/agentflow/verify.py"` ⇒ 仍 `requires_human(1)`
  且命中两条（逐字与上面 B 行相同）。
- **正控二**：`--paths "src/agentflow/cli.py"`（非禁改区）⇒ 仍 `clean(0)`（不许把 clean 也弄红）。
- **正控三**：`--changed-file` 那条通路跑一次（`tools/release_all.py --since <ref>` 或
  `scripts/release_check.py --changed-file`）⇒ 行为不变（这一条用来证明"只有可疑输入形态被拒"）。

## 另一条**只登记不修**的观察（属于人裁决那一类，与 `G-43` 同族但面更大）

`scripts/noai_gate.py`（门本体）**不在** `.noai-paths` 清单里 ⇒ **"把门改宽"不需要任何人审**。
`draft/25` §10.1 的"候选（待裁决）"只点了 `scripts/lint_rules.py` / `tools/coverage_zero_test.py` /
`tools/run_each_test_file.py` / `tools/verify_role_specs.py`，**没点门本体**。
理由与代价：把它纳入清单会再增条目与签名债（今天是 16 条 / 欠 32），但它是**唯一一个
"改一行就能让所有门都失效"的文件**。⇒ 交人裁决，**我这一轮不动它**。
