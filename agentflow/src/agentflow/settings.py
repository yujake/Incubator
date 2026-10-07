# -*- coding: utf-8 -*-
"""机器级设置文件：这台机器上工具链在哪、用哪个模型 —— 「一处定义」。

## 为什么要有它（2026-10-07 所有者指示）

改前的事实：这台机器上 Lean/Mathlib 装在哪，是「写死在代码与文档里的字符串」
（`toolchain.py` 的模块 docstring 里逐字写着一台机器的绝对路径，
`formalgw.py` 的注释里写着仓库临时区里的那个 Mathlib 目录名），而模型 API key
只能从环境变量读（`modelgw.spec_from_env`）。两件事于是各有一个"机器相关的事实"
落在两个地方，且其中一件（路径）是硬编码的。

现在两件事合并到同一个文件里：`settings.json`。它是「机器级」的设置，
与每个工作区自己的 `config.yaml`（`cli.load_config` 读的那一份）是两件不同的
东西 —— 后者随工作区走，前者随机器走，不许混成一个。

## 落点与键名（逐字）

落点：

1. `load_settings(path=...)` 给了就用它（判据的注入接缝）；
2. 否则读环境变量 `AGENTFLOW_SETTINGS=<路径>`（指到别处）；
3. 否则是默认落点 `agentflow/settings.json`（「工作区根相对」；本模块按
   `__file__` 定位工程根 `src/` 的上一级，不依赖进程 cwd —— 判据与 CLI 的
   cwd 不一定相同）。

键（全部可选，缺哪个哪个走默认）：

| 段落 | 键 | 含义 |
|---|---|---|
| `toolchain` | `lean_bin` | Lean 可执行文件「或它所在的目录」（"指向安装目录"是人最自然的写法） |
| `toolchain` | `mathlib_root` | Mathlib 工程根（同时含 `lakefile.lean` 与 `lean-toolchain` 的那个目录） |
| `toolchain` | `coq_bin` | Coq 的 `coqc`（同上：文件或目录） |
| `toolchain` | `isabelle_bin` | Isabelle 的 `isabelle`（同上：文件或目录） |
| `model` | `api_key` | 模型 API key（落盘这件事的代价与安全阀见下面「安全阀」一节） |
| `model` | `base_url` | OpenAI 兼容端点（缺省 `https://api.deepseek.com/v1`） |
| `model` | `name` | 模型名（缺省 `deepseek-chat`） |

文件不存在 ⇒ 空 dict（`{}`）——这是「全用默认值」的正常形态，「不是错误」。
解析失败 ⇒ 报「真正的那个错误」：JSON 语法错就抛 `json.JSONDecodeError`
（连同行列号一起，路径附在消息里），而不是折成一句"格式不对"。
（教训出自 `cli.load_config`：它把 YAML 缩进错误折成 JSON 报错，
排查方向被彻底带偏 —— 报错的准确性是诊断能力的一部分。）
文件能解析但不是 JSON 对象（例如整个文件是一个数组）⇒ 那是「另一种」错
（形状错，抛 `ValueError` 并说清收到的是什么），与语法错分得开。
刻意不认 YAML：本包运行期依赖只有 `filelock`，为一个设置文件引一门
"缩进即语义"的方言不值得；`json` 是标准库，且它的错误信息带行列号。

## 优先级（逐字，唯一口径）

    环境变量 > 设置文件 > 内置默认/自动探测

三档的含义与理由：

1. 「环境变量」最高：CI 与既有脚本全靠它（`AGENTFLOW_LEAN_BIN`、
   `AGENTFLOW_PROVER_PATH`、`AGENTFLOW_MATHLIB_ROOT`、`AGENTFLOW_MODEL_API_KEY` …）。
   把设置文件摆在它前面，会让一台机器上的 `settings.json` 静默改掉
   CI 里显式传的那些值 —— 那正是"这次改动把既有脚本弄坏"的形态。
   空串（或纯空白）视为「未设置」，不遮住下一档。
2. 「设置文件」次之：本机路径与 key 的正常落点（也是这次新增的那一档）。
3. 「内置默认/自动探测」最后：`DEFAULT_BASE_URL` / `DEFAULT_MODEL`、
   `AGENTFLOW_PROVER_PATH` 之后按 PATH `which`、Mathlib 的常见位置探测。
   它是"兜底"，不是"配置" —— 三态纪律照旧：配了却找不到要记成配置问题
   （fail-closed），不许读成"这台机器没有"。

这一条优先级只有一个实现（本模块的 :func:`env_or_setting`）：调用方
（`toolchain.resolve_checker` / `formalgw.find_mathlib_root` /
`modelgw.spec_from_env`）都只许从它取值，各写一份的话，
"哪个来源赢"会有两个答案，而漂移的症状是"同一台机器上探测与调用各说各话"。

## 注入接缝（判据为什么不会读到本机的 settings.json）

`env is not None` 时只认这份映射：设置文件路径只从 `env[AGENTFLOW_SETTINGS]` 取，
「不再去探默认落点」。理由与 `toolchain._env` 是同一句："给了 `env` 就用它"——
判据要能在确定的环境里跑，本机的设置文件不许渗进来。
要连设置文件一起注入，就在那份映射里给 `AGENTFLOW_SETTINGS`。

## 安全阀（`api_key` 落盘这件事的代价怎么被堵住）

把 key 挪进一个文件，换来的代价是"密钥一旦落盘就会进版本库与备份"
（`modelgw` 的旧 docstring 逐字记过这一条）。代价由三道阀门一起承担：

1. 真正的 `agentflow/settings.json` 在 `.gitignore` 里（理由逐字写在那一条）；
2. 入库的是示例 `agentflow/settings.example.json`，其中 `api_key` 是空串；
3. 任何打印/读数都不回显 key（照 `ModelSpec.redacted` 的先例：
   台面只给 `api_key: "***"` 或"配没配"这一格）。

判据在 `tests/test_settings.py`：这三条各有正控与负控。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "DEFAULT_SETTINGS_REL",
    "ENV_SETTINGS",
    "MODEL_KEYS",
    "PROJECT_ROOT",
    "TOOLCHAIN_KEYS",
    "WORKSPACE_ROOT",
    "env_or_setting",
    "load_settings",
    "model_settings",
    "resolve_setting_path",
    "settings_path",
    "toolchain_settings",
]

#: 默认落点名（相对工程根；相对工作区根就是 `agentflow/settings.json`）。
DEFAULT_SETTINGS_REL = "settings.json"
#: 工程根（`src/` 的上一级）。按 `__file__` 定位：判据与 CLI 的 cwd 不一定相同。
#: 装了 wheel 的场合这里是包的上一级 —— 那种场合请用 `AGENTFLOW_SETTINGS` 显式指路。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
#: 工作区根（工程根的上一级）：设置文件里「相对路径」的解析基准
#: （见 :func:`resolve_setting_path`）。
WORKSPACE_ROOT = PROJECT_ROOT.parent
#: 指到别处的环境变量（优先级最高的一档，见模块 docstring）。
ENV_SETTINGS = "AGENTFLOW_SETTINGS"
#: `toolchain` 段认识的键（顺序即文档顺序）。
TOOLCHAIN_KEYS: tuple[str, ...] = ("lean_bin", "mathlib_root", "coq_bin", "isabelle_bin")
#: `model` 段认识的键（顺序即文档顺序）。
MODEL_KEYS: tuple[str, ...] = ("api_key", "base_url", "name")


def settings_path(path: str | Path | None = None, *,
                  env: Mapping[str, str] | None = None) -> Path | None:
    """设置文件在哪。返回 `None` 表示"本次不读文件"（注入环境的场合，见模块 docstring）。

    三档同模块 docstring：显式 `path` → `env[ENV_SETTINGS]` → 默认落点。
    刻意把"不读"表示成 `None` 而不是"一个不存在的路径"：后者会让
    "没打算读文件"与"文件恰好不在"长得一样，而这两件事的处置不同。
    """
    if path is not None:
        return Path(path)
    src = dict(os.environ if env is None else env)
    raw = str(src.get(ENV_SETTINGS) or "").strip()
    if raw:
        return Path(raw)
    if env is not None:
        # 注入环境且没给 ENV_SETTINGS ⇒ 本次不落磁盘（判据要与本机解耦）。
        return None
    return PROJECT_ROOT / DEFAULT_SETTINGS_REL


def load_settings(path: str | Path | None = None, *,
                  env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """读设置文件。文件不存在或"本次不读文件" ⇒ `{}`（全用默认值的正常形态）。

    解析失败报真正的那个错误，两档分得开：
    语法错 ⇒ `json.JSONDecodeError` 原样抛出（路径附在消息里，行列号保留）；
    形状错（合法 JSON 但不是对象）⇒ `ValueError`，消息里写清收到的是什么类型。
    不说"格式不对"这种把两种成因折叠成一句话的措辞 —— 它们要改的地方不同。
    """
    p = settings_path(path, env=env)
    if p is None or not p.is_file():
        # 不读文件与文件不在，都是"全用默认值"这一种正常形态（不是错误，
        # 也不是"没查成"：调用方拿到 {} 之后走的是各自的默认档）。
        return {}
    text = p.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # 报真正的那个错误：语法错就是语法错（类型不变，行列号保留），
        # 只在消息前面补上"是哪个文件"。折成"格式不对"会让排查方向跑偏。
        raise json.JSONDecodeError(f"设置文件 {p}：{exc.msg}", exc.doc, exc.pos) from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"设置文件 {p} 必须是一个 JSON 对象（收到 {type(data).__name__}）—— "
            "这是形状错，不是语法错；两种错的改法不同，所以不许报成同一句话"
        )
    return data


def _section(name: str, keys: tuple[str, ...], path: str | Path | None,
             env: Mapping[str, str] | None) -> dict[str, str]:
    """取一段（`toolchain` / `model`）：只认登记过的键，值统一成去空白的字符串。

    为什么"值统一成字符串 + 缺的键补空串"：调用方（三处）都只做
    "非空就用"这一件事，键集合固定它们的 `.get()` 才不会有第二套默认值。
    非字符串的值（数字 / 列表）一律折成空串（=未设置）而不是 `str(value)`：
    把一个 `123` 悄悄当路径用，比"当作没配"更难查。
    """
    raw = load_settings(path, env=env)
    seg = raw.get(name)
    seg = seg if isinstance(seg, Mapping) else {}
    return {k: (seg.get(k).strip() if isinstance(seg.get(k), str) else "") for k in keys}


def toolchain_settings(path: str | Path | None = None, *,
                       env: Mapping[str, str] | None = None) -> dict[str, str]:
    """`toolchain` 段：`lean_bin` / `mathlib_root` / `coq_bin` / `isabelle_bin`（缺的补空串）。

    四个键「总是在」返回里（空串 = 未设置）。调用方据此做"非空就用"，
    不需要在三个地方各写一份 `.get(key, "")`。
    """
    return _section("toolchain", TOOLCHAIN_KEYS, path, env)


def model_settings(path: str | Path | None = None, *,
                   env: Mapping[str, str] | None = None) -> dict[str, str]:
    """`model` 段：`api_key` / `base_url` / `name`（缺的补空串）。

    这一口只负责「取值」，不负责脱敏也不负责判定：回显 key 的地方一律走
    `ModelSpec.redacted()`（见模块 docstring 的「安全阀」）。
    """
    return _section("model", MODEL_KEYS, path, env)


def env_or_setting(env_name: str, setting_value: Any, *,
                   env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """按唯一口径取一个值：环境变量 > 设置文件 > 空串。返回 `(值, 来源)`。

    `来源` 取值 `"env"` / `"settings"` / `""`（都没有）：
    "是从哪一档找到的"必须能被回传（`toolchain` 的 `source` 就是这么来的）——
    只回一个值的话，"没配"与"配了这一档但值是空的"分不开。

    空串与纯空白视为「未设置」（与 `toolchain.resolve_checker` 既有的
    `(src.get(var) or "").strip()` 同一条口径）：否则一个空的环境变量会
    静默遮住设置文件，而"设了个空值"与"没设"在用户眼里是同一件事。
    """
    src = dict(os.environ if env is None else env)
    raw = str(src.get(env_name) or "").strip()
    if raw:
        return raw, "env"
    value = setting_value.strip() if isinstance(setting_value, str) else ""
    if value:
        return value, "settings"
    return "", ""


def resolve_setting_path(raw: str | Path) -> Path:
    """设置文件里的一个路径值 → 路径对象（相对路径按下面的口径补全）。

    绝对路径原样用；相对路径「相对工作区根」（工程根的上一级，即
    `agentflow/settings.json` 所在仓库的那一级）解析。为什么不相对进程 cwd：
    cwd 随调用方式变（CLI 在 `agentflow/` 下跑、判据在临时目录里跑、
    别的工具在仓库根跑），让"同一个设置文件在两处解析成不同的目录"是静默的错 ——
    而症状会是一句"配置的路径不存在"，排查的人只会去怀疑设置文件写错了。

    跨工作树（`temp/` 下另有一份 checkout）或工具链装在别处时，
    请用 `AGENTFLOW_SETTINGS` 指路或在设置文件里直接写绝对路径。
    """
    p = Path(raw)
    return p if p.is_absolute() else (WORKSPACE_ROOT / p)
