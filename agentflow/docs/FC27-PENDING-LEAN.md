# FC-27 待批清单（Lean 对齐这一批）

> 生成时间：2026-10-17。**我（AI）不代签。** 按 `AGENTS.md` 的 FC-27，下面每一处都需要
> **2 名 reviewer 逐行走查后 approve**；机器读数用 `python scripts/noai_gate.py --git`
> （`required_approvals=2`，退出码 1 = `requires_human`）。
>
> 为什么单独出一份：这一批改动集中在 **Lean 开关**这条链上，跨了 `specs/*`（声明面）、
> `agent_prompts.py`（提示词面）、`toolchain/verify_tools`（桥接层）与冻结快照，
> 逐条核对比读一个大 diff 更可靠。

## 一、禁改区（必须 2 人批）

| 文件 | 改了什麼 | 类别 | 对应的审计条目 |
|---|---|---|---|
| `src/agentflow/specs/e.py` | ① policy 增 **S2 开时义务**（"至少要真的试一次 `method=formal`"）；② policy 增 **S7**（proof 必须留 `verifier_output` + `exit_code`） | auth-audit | S2 / S7 |
| `src/agentflow/specs/h.py` | boundary 增 **S5 第三档**（"开着但没有检查器"⇒ 按"没查"处置 ＋ findings 写环境缺口 ＋ 禁写"已形式化验证"） | auth-audit | S5 |
| `src/agentflow/specs/m.py` | policy 增 **S2 派活义务**（要求形式化时必须两步：`check_formal` → `run_experiment(formal)`；只做数值＝降级） | auth-audit | S2 |
| `tests/golden/agent_surface_snapshot.json` | 因 `PROMPT_VERSION p148→p150` 重冻（10 角色 / 61 动作） | eval-criteria | — |

## 二、非禁改区，但**行为面**有变化（建议一并走查）

| 文件 | 改了什麼 | 为什么要人看一眼 |
|---|---|---|
| `src/agentflow/agent_prompts.py` | **S1**：`TOOLCHAIN_FACTS` **第一行**改为开关状态（开时新增"**已开启**"）；**S4**：`_lean_switch` 的 `unreadable` 从 `True` 改 **`False`**（fail-closed）＋文案；**S6**：`profiles_markdown` 出口套 `_apply_no_lean_variant`；`FACULTY_LOCAL[("H","手")]` 措辞中性化；`PROMPT_VERSION="p150"` | 六处"看第一行"的指令靠它兑现；改错会让**开/关判断整体反向** |
| `src/agentflow/agent_skills.py` | **S6**：关着 Lean 时在技能索引末尾加一句"形式化那条读来也做不了" | 只加一句，但会出现在每个角色的技能索引里 |
| `src/agentflow/toolchain.py` | 删掉 `can_do_formal` 的**重复键**（原 `bool(lean) and enabled` 被 `bool(lean)` 覆盖） | `doctor` 的读数从此不再撒谎 |
| `src/agentflow/tools/verify_tools.py` | `detect_verifier` **新增** `lean_enabled` / `lean_enabled_source` / `can_do_formal` / `note`（不改老键语义） | 新增键，但下游若按 `**` 展开会多出字段 |
| `src/agentflow/verifications.py` | **S3**：`cold_start_prompt`（V 的**真实入口**）加开关状态 ＋ "成立**永远不构成** `proof`"＋"别写已形式化验证" | 这是 V 唯一的上下文来源；加了它 V 才会说"我不是 proof" |
| `settings.json` | `lean_bin` / `mathlib_root` **清空**（原值指向不存在的 `_env/...`） | 避免 `tool_crashed` 误导；**若真要开 Lean，必须重新填** |
| `docs/LEAN-MODES.md`（新） | 两模式矩阵（七节） | 规格文档 |
| `tests/test_lean_modes_matrix.py`（新） | **12 条**双模式行为判据 | 覆盖矩阵里可测的每一条 |

## 三、走查建议顺序（按风险）

1. **`agent_prompts.py` 的 S1/S4** —— 开/关判断的唯一来源；错了整条链反向（`test_lean_modes_matrix` 里有正反两条用例兜着）；
2. **`specs/{e,h,m}.py` 的三条义务** —— 它们决定"开着时到底会不会真去跑 formal"；
3. **`verifications.py` 的 S3** —— 决定 V 会不会再对自然语言证明签"成立"而不声明强度；
4. **`toolchain.py` 的重复键删除** —— 一处删除改变 `doctor` 的对外读数；
5. 快照重冻 —— 只应含 `PROMPT_VERSION` 与 E/H/M 三格摘要的变化。

## 四、复核命令

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'
python scripts/noai_gate.py --git            # 期望：requires_human，required_approvals=2
python -m pytest -q tests/test_lean_modes_matrix.py tests/test_lean_switch.py tests/test_agent_prompts.py
```
