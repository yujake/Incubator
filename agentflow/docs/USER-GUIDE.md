# 用户手册：怎么把它跑起来、在哪看

> 读者是**用的人**，不是改它的人。下面的命令 2026-10-21 全部真机跑过。
> 权威口径永远是代码：`python -m agentflow.cli --help`、`python -m agentflow.cli web --help`。

---

## 0. 三分钟起步

```powershell
cd D:\Incubator\agentflow
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUTF8='1'; $env:PYTHONPATH='src'

# ① 建工作区（一个工作区 = 一个研究课题）
python -B -m agentflow.cli --root projects\my-topic init

# ② 起网页（这一格就是监控面板）
python -B -m agentflow.cli --root projects\my-topic web --port 52060 --open
```

浏览器会打开 `http://127.0.0.1:52060/`。**网页只读**（看得见、点不动写操作）；
要它跑活，用第 3 节的命令行。

> 没把 `agentflow` 装进 site-packages 的话，上面三行 `$env:` 必须先在**同一个窗口**里执行，
> 否则报 `No module named agentflow`。

---

## 1. 起网页：旗标与它们的真实行为

```powershell
python -B -m agentflow.cli --root <工作区> web [旗标...]
```

| 旗标 | 作用 | 注意 |
|---|---|---|
| `--port N` | 端口 | `--port 0` = 系统挑空闲端口（配 `--json`） |
| `--open` | 起来后用默认浏览器打开 | 最省事 |
| `--json` | 只打印一行 `{"url": "...", "root": "..."}` | **拿确切地址用它** |
| `--host` | 监听地址 | 缺省只听本机；`0.0.0.0` 才对外（别随手给） |
| `--token` | 访问口令 | 也可用环境变量 `AGENTFLOW_WEB_TOKEN` |
| `--allow-writes` | 打开写面 | **只管 `/api/` 下那六条写端点**；`POST /answer`（对话里回话）是既有写路径，缺省也放行 |
| `--no-settings-write` | 只关 `POST /api/settings` | 其它写面照旧 |

**`--root` 必须写在子命令前面**：`--root X web` 对；`web --root X` 会被 argparse 拒（退出码 2）。

### 1.1 后台起、拿地址

```powershell
$info = (python -B -m agentflow.cli --root projects\my-topic web --port 0 --json) | ConvertFrom-Json
$info.url        # http://127.0.0.1:52060/ 这样
```

### 1.2 关掉

前台 Ctrl-C；后台起的就杀那个进程：`Get-NetTCPConnection -LocalPort <端口>` 找到 pid 再 `Stop-Process`。

---

## 2. 网页有哪几页、各看什么

九页（导航八条，`/run/<sid>` 是第九页）：

| 页 | 看什么 | 读的端点 |
|---|---|---|
| 对话 Home | 这个工作区的来回：我问了什么、它答了什么 | `/api/state`、`/api/chat`、`/api/live` |
| 一趟详情 Run | 某次跑（一个 `sid`）的全过程与事件流 | `/api/run/<sid>`、`/api/run-index`、`/api/live` |
| 在飞 Live | 有没有在跑、状态报告、用量，**以及名册树** | `/api/live`、`/api/status-reports`、`/api/usage`、`/api/roster` |
| 预算 Budget | 总额度、已花、剩余（含"已越上限"） | `/api/budget` |
| 证据 Evidence | 断言与它们的证据档位/引文 | `/api/evidence` |
| 产物 Artifacts | 落盘了什么（含交付说明） | `/api/artifacts` |
| 验收 Acceptance | 五条判据 + 五种辅助读数 | `/api/acceptance` |
| 本机 Machine | provider/模型/开关（key 恒显示 `***`） | `/api/machine` |
| 说明 Help | 本手册的网页版 | — |

**名册面板**（在「在飞」页）：树形显示每个代理的**名册名 + 绝对编号 + 深度 + 子数 + 收件箱积压**。
真身是工作区里的 `out/roster/<父编号>.jsonl`（append-only）。三态：`ok` / `unknown`（读不到）/ 坏行。

---

## 3. 让它跑活：命令行

```powershell
python -B -m agentflow.cli --root projects\my-topic run-agent M --task "<题目>" `
  --attack-reasoning --semantic-review --provider crossref,doaj,europepmc,openalex `
  --budget-usd 5 --sid my-1 --stop-file projects\my-topic\.agentflow-stop
```

| 参数 | 含义 |
|---|---|
| `--task "<文本>"` | 题目；也可以是"继续上一趟"的话 |
| `--budget-usd N` | **累计**上限：不传 = 无限制；传 5 就是"一共花到 5 美元" |
| `--sid` | 会话名（台账按它分片；`--resume` 也认它） |
| `--max-steps N` | 步数上限（不传 = 不设） |
| `--stop-file <路径>` | 优雅停的旗标文件：写它 = 让整棵树停下来收尾 |
| `--attack-reasoning` | 打开 F（多轮攻坚） |
| `--semantic-review` | 打开 H（语义审校） |
| `--experiment-reasoning` | 打开 E（实验/形式化） |
| `--provider a,b,c` | 检索走哪些源 |

**停**：`python -B -m agentflow.cli --root <ws> stop --reason "<一句>"`（`--force` 强停）。

---

## 4. 钱怎么算（最容易被误解的一格）

- 额度落 `<ws>/budget.json`：`total_usd` + append-only 的 `added[]`（谁加、多少、为什么）。
- **`--budget-usd` 是累计上限**，不是"这次再给"。**不传 = 无限制**（网页显示 `source=unlimited`）。
- `budget.json` 坏了 ⇒ 退回命令行上限并**显示原因**，不会静默变无限制。
- 可以略微越界（最后一步已发出的费用收不回），网页会显示"已越上限"。

```powershell
python -B -m agentflow.cli --root <ws> budget --status
python -B -m agentflow.cli --root <ws> budget --add 5 --reason "第二批"
```

---

## 5. 退出码六档（别把 1 当"正常结束"）

| 码 | 含义 |
|---|---|
| 0 | 正常结束，有 `final` |
| 1 | **行为异常**（没登记的 stop_reason 也归这一档） |
| 2 | 研究启动失败（参数/环境，还没真正开始） |
| 3 | 等你（`waiting_for_user`）—— 去网页「对话」页看它在问什么 |
| 4 | 正常中途停：用户叫停 / 父叫停 / 预算耗尽 |
| 5 | 正常自停但没有 `final`（没进展了 / 升级给人） |

---

## 6. 出问题先看这三处

```powershell
# ① 这一趟到底发生了什么
Get-Content projects\<ws>\runs\<sid>\events.jsonl -Tail 30

# ② 台账真的落了东西吗（不是"它说落了"）
python -c "import json,pathlib;d=pathlib.Path(r'projects\<ws>\data');print({t:len(json.loads((d/f'{t}.json').read_text(encoding='utf-8'))['rows']) for t in ('statements','tasks','documents','experiments')})"

# ③ 收工门八格 + 非平凡性读数
python -B -m agentflow.cli --root projects\<ws> closing
```

`closing` 逐格印 `paper / contradictions / load_bearing / report_shape / user_pending / substance / acceptance / artifact_ledger`，
再印 `非平凡性：T1 x / T2 y / T3 z / T4 w / 未判 n`，以及论文侧缺铺垫与 T4 缺造梯子记录（`[warning]` 行）。

---

## 7. 这次测试要盯的两件事

1. **格式是否规范**：产出的 `theorem/lemma/proof` 环境齐不齐、`\cite` 带不带页码、
   正文有没有内部编号（`exp:`/`stmt:` 之类只许出现在附录 index）。
2. **宏大的定理有没有被派"搭梯子 / 拆分"**：
   - 「在飞」页的名册树看派活结构（谁派的、派给谁、绝对编号）；
   - `closing` 的「非平凡性」那一行看档位分布（T3/T4 就是"宏大"的那几条）；
   - 出现 `[warning] nontriviality：T4 缺造梯子记录` ⇒ 研究侧没接这个信号；
   - 论文里 `definition` 环境数应当随 T4 的处理**上升**（"造梯子"的可见形态）。

---

## 8. 一句话

**网页用来看，命令行用来跑**；钱按累计算、不传就是不设限；退出码 1 不是正常结束。
