# data/ —— 默认工作区的空台账（入库）

> `agentflow/` 本身就是 CLI 的**默认工作区**（`cli.DEFAULT_ROOT`）：不给 `--root` 时，
> 台账就落在这里。这些文件是 `init` 写出来的**空台账**，入库是为了让"在检出目录里
> 直接跑"这件事成立 —— 不是种子数据，也不是演示数据。

## 谁读

要用默认工作区跑一次的人；以及要确认"一份空台账长什么样"的人。

## 里面是什么

| 文件 | 是什么 |
|---|---|
| `*.json`（每张表一份） | 表的快照。空表形状是 `{"schema_version": 2, "rows": []}`；`counters.json` 是 `{"schema_version": 2, "counters": {}}` |
| `events.jsonl` | 追加式事件日志（空台账时是 0 字节）。每次写表都会追加一行；`Store.rebuild()` 可以从它重放出全部快照 |

表清单与列定义以 `src/agentflow/schema.py` 的 `TABLES` 为准（别在这份 README 里抄表名清单，
加表时会漂）。

## 怎么用

```powershell
# 读这张台账（空表也打印得出逐表行数）
python -m agentflow.cli --root . status

# 不要随手 `init` 覆盖它：init 会拒绝往非空目录里建工作区；
# 真要在默认工作区起一趟，直接给 --root（缺省就是这里）跑 start/run-agent。
```

## 边界

- 跑一趟就会在这里落真实数据。**提交前先看 `git status`**：`data/*.json` 是入库文件，
  真机数据不该被顺手带进提交。
- `.locks/` 是本目录里被忽略的运行期锁文件（`filelock` 用完即删），不进版本库。
- 想隔离实验用别的目录当工作区：`--root <别的目录>`，本目录就保持空。
