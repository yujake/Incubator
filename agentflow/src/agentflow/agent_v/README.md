# agent_v —— V：证明级验证（只读角色）

**职责（声明原文）**：证明级验证 —— 把交进来的证明按写成后的样子整体重读，逐条查硬禁令与
同段依据，给两态结论（成立 / 有毛病）。**发签的判定与写盘是两件事**：签只由 V 这一侧颁发；
在册档够不够门槛由框架按这一趟的台账现数，落签由收方秘书。
**典型误根**：把已看见的缺陷写成"成立"—— 漏报与通过是两件事，台账上它们只差一个字。

- 声明在 [`../specs/v.py`](../specs/v.py)：3 个动作、**出边为空**、**写集为空**、
  `read_only=True`。实现类 `agent_v:AgentV`（`core.py` 一个文件，判据散在 `../v_*.py`）。
- **谁读**：改验证规则的人。改 V 的行为通常改的是包外的 `v_*.py` 系列，不是本目录。

## 文件

| 文件 | 是什么 |
|---|---|
| `core.py` | `AgentV` 全部实现：`verify_proof` / `list_verifications` / `read_proof` 三个动作与校验骨架 |
| `__init__.py` | 导出 `AgentV` |
| `__main__.py` | `python -m agentflow.agent_v` 的自检入口 |

三份相关的判据不在本目录：`../v_defect.py`（缺陷步）、`../v_grades.py`（等级）、
`../v_sign.py`（发签）等 `v_*.py` 是 V 的判据件，被 V 与秘书两侧共用。

## 怎么用

```powershell
python -m agentflow.agent_v        # 零模型自检
# 验证台账在 <ws>/verifications/<命题号>.jsonl；未在册档的签发信封在 <ws>/out/vsigns/

# 本目录声明的动作数（现算；本文件开头写的那个数字就是它的输出）
python -c "import sys;sys.path.insert(0,'src');from agentflow import specs;print(len(specs.builtin_specs()['V'].actions))"
```

## 邻居

上游：送审方 **F / E / B**。下游：**B**（收录时读这一行与稿上的签）。
结论只有两态：`成立` 时 findings 必须为空；`有毛病` 时每条 findings 都要带步号与
`defect_step`。**V 不写任何台账表行**（写集为空）：`verify_proof` 落的是
`verifications/<命题号>.jsonl` 侧文件；未在册档的签发信封落 `<ws>/out/vsigns/<sha>.json`；
而"在册档够不够门槛、签落在稿上"由收方秘书按这一趟的台账现数、由它落。

