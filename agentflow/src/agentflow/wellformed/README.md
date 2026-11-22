# src/agentflow/wellformed —— 产物畸形的统一判据

> 一句话：**"这个工作区的产物有没有畸形"的唯一定义处**。它只回答、不修补、不当门的输入；
> 读写两侧共用同一批规则。

## 谁读

排查"盘上有东西坏了但 `verify` 没报"的人，以及写 `scripts/check_wellformed.py` 那条链的人。

## 三态（与仓库其它门同一条纪律）

- `ok` —— 该类产物查过了，没有畸形；
- `malformed` —— 查过了，有 Finding（每条带文件、位置、逐字读数、怎么改）；
- `unchecked` —— **没查成**（文件读不出来 / 交叉核对要用的表读不出来）。`unchecked` 绝不折成 `ok`。

## 文件

| 文件 | 是什么 |
|---|---|
| `driver.py` | 驱动：摊开文件清单 → 跑一类规则 → 三态合成；对外入口在这里 |
| `registry.py` | `RULES[kind][name]` 规则表（判据可以逐条打桩做反真空） |
| `states.py` | `ok` / `malformed` / `unchecked` 的取值、`Finding`、退出码 |
| `reader.py` / `predicates.py` | 读盘与共用谓词 |
| `acceptance.py` | 验收行（`out/paper/ACCEPTANCE-CHECKS.json`）的形状 |
| `artifacts.py` | `ARTIFACTS.jsonl` 的 sha 对拍与登记 |
| `candidates.py` | `lit_candidates`（待裁文献） |
| `ledger.py` | `data/*.json` 的行与列类型 |
| `literature.py` | `literature` 行与全文可得性 |
| `manuscripts.py` | 稿件与证明稿的稿头 |
| `proofs.py` | 证明台账 / 实验行 |
| `relations.py` | 关系行（"说回验通过却给不出区间"这一类） |
| `roster.py` | 名册与销号行（`out/roster/*-retired.jsonl`） |
| `sessions.py` | `sessions/*.jsonl` 的事件流 |
| `signs.py` | 签块与 `out/vsigns/<sha>.json` |
| `statements.py` | 命题行 |
| `tasks.py` | 任务行 |

## 怎么用

```powershell
# 查一个工作区（0 = 全 ok / 1 = 有畸形 / 2 = 没查成）
python scripts/check_wellformed.py --root D:\Incubator\temp\ws

# 只看某一类（kind 见 states.KINDS）
python scripts/check_wellformed.py --root D:\Incubator\temp\ws --kind statements --json
```

## 邻居

上游：`../schema.py` / `../evidencebits.py` / `../manuscriptfamily.py` 等**词表权威**（本目录
不另抄词表）。下游：`scripts/check_wellformed.py`、`closing.py` 的验收格、以及人读的排查报告。
