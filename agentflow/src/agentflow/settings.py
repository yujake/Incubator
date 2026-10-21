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
| `toolchain` | `lean_enabled` | 布尔：这台机器/这一趟要不要走 Lean 形式化这条路（缺省 `false`：无严苛要求时不烧形式化那笔钱；写 `true` 才按老套路走形式化） |
| `model` | `api_key` | 模型 API key（落盘这件事的代价与安全阀见下面「安全阀」一节） |
| `model` | `base_url` | OpenAI 兼容端点（缺省 `https://api.deepseek.com/v1`） |
| `model` | `name` | 模型名（缺省 `deepseek-flash`；2026-10-10 裁定 19乙 从 `deepseek-chat` 换过来） |
| `workspace` | `projects_dir` | `projects/` 的落点（`agentflow project` 与 M 的 `conductor.ensure_project` 的缺省落点） |

（`workspace` 这一段是同一个指示的第二半：那条写死的 `D:\Incubator\projects`
（`projects.DEFAULT_PROJECTS_DIR`）与工具链地址同族 —— 都是"机器相关的事实落在代码里"。
改后本机默认值逐字不变，只是它现在由"本包位置推出的工作区根 + `projects/`"算出来，
并且允许用设置文件覆盖。）

文件不存在 ⇒ 空 dict（`{}`）——这是「全用默认值」的正常形态，「不是错误」。
解析失败 ⇒ 报「真正的那个错误」：JSON 语法错就抛 `json.JSONDecodeError`
（连同行列号一起，路径附在消息里），而不是折成一句"格式不对"。
（教训出自 `cli.load_config`：它把 YAML 缩进错误折成 JSON 报错，
排查方向被彻底带偏 —— 报错的准确性是诊断能力的一部分。）
文件能解析但不是 JSON 对象（例如整个文件是一个数组）⇒ 那是「另一种」错
（形状错，抛 `ValueError` 并说清收到的是什么），与语法错分得开。
刻意不认 YAML：为一个设置文件引一门"缩进即语义"的方言不值得 ——
`json` 是标准库，且它的错误信息带行列号（上面那条教训要的正是这个）。
（注：`pyyaml` 从 2026-10-11 起是运行期依赖，但它是为预设层引入的
——业主裁定"就用 dsh 的格式"，见 `presets.py`。设置文件这一档刻意不跟着变：
同一个包对"哪一层用哪种方言"要有明确的边界，而不是"能解析就顺手解析"。）

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

from . import schema as S   # `ROLE_SLOTS` 从 `S.ROLES` 现取（角色名单只有一处）

__all__ = [
    "BOOL_KEYS",
    "DEFAULT_LEAN_ENABLED",
    "DEFAULT_SETTINGS_REL",
    "ENV_LEAN_ENABLED",
    "ENV_SETTINGS",
    "LEAN_ENABLED_KEY",
    "MASKED_KEY",
    "MODEL_KEYS",
    "PROJECT_ROOT",
    "TOOLCHAIN_KEYS",
    "WORKSPACE_KEYS",
    "WORKSPACE_ROOT",
    "env_or_setting",
    "lean_enabled",
    "load_settings",
    "model_settings",
    "resolve_setting_path",
    "settings_path",
    "toolchain_settings",
    "workspace_settings",
    "write_settings",
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
TOOLCHAIN_KEYS: tuple[str, ...] = ("lean_bin", "mathlib_root", "coq_bin", "isabelle_bin",
                                   "lean_enabled")
#: `toolchain` 段里那个布尔开关的键名（业主 2026-10-12 口径：机器上有没有 Lean
#: 环境由用户设一个 bool，全流程涉及 Lean 的都要跟着它的状态走）。
#:
#: ## 为什么它不走 `_section` 那条"非字符串 ⇒ 空串"的路
#:
#: 那一条是给路径定的（写进来一个 `123` 当路径用比"当作没配"更难查）。
#: 而这一格正经的值就是一个 JSON 布尔 `false` —— 按那条口径折成空串，
#: 等于把用户关掉的开关又打开（而且是在机器面上看不出来的那种）。
#: 所以它由 :func:`_bool_cell` 归一：`false` / `"false"` / `"off"` 一律 ⇒ `"false"`。
LEAN_ENABLED_KEY = "lean_enabled"
#: 环境变量档（优先级最高的一档，与其余键同一条梯子）。
ENV_LEAN_ENABLED = "AGENTFLOW_LEAN_ENABLED"
#: 缺省：`True` —— 不设它时行为与 2026-10-12 之前逐字相同。
#:
#: 为什么缺省是"开"而不是"按探测自动决定"：这一格的语义是许可，不是读数。
#: 本机的探测读数（`toolchain.probe_checkers` / `formalgw.detect_backend`）本来就如实
#: 报"没装 Lean"，那条路不需要开关；它要回答的是「这一趟值不值得为形式化花钱」：
#: 形式化的每一次尝试都要真起 Lean 子进程（`import Mathlib` 一次 ~25–30 秒），而多数趟次
#: 拿不到 proof 行 —— 真机读数里 T1 三趟的 $6.1553 有一大半花在这条线上。
#:
#: 缺省是关（业主 2026-10-12 的口径逐字：「默认设置中 Lean 关闭帮用户在无严苛要求时省钱」）：
#: 要形式化就显式写 `true`（或 `AGENTFLOW_LEAN_ENABLED=1`），那时全流程回到老套路、
#: 一个字都不变（`tests/test_lean_switch.py` 的负控逐条钉这一点）。
#: 把"探测不到"折进这一格仍然不允许 —— 那会让"我关了它"与"机器上没装"在读数上长得一样。
DEFAULT_LEAN_ENABLED = False
#: 认得的真/假写法（大小写不敏感）。不认得的写法不静默按缺省跑（见 :func:`lean_enabled`）。
_TRUE_WORDS: tuple[str, ...] = ("1", "true", "yes", "on", "y", "t")
_FALSE_WORDS: tuple[str, ...] = ("0", "false", "no", "off", "n", "f")
#: 值可能是 JSON 布尔（而不只是字符串）的那几格。
BOOL_KEYS: tuple[str, ...] = (LEAN_ENABLED_KEY,)
#: `model` 段认识的键（顺序即文档顺序）。
#:
#: `reasoning_effort` 是 2026-10-10 加的（所有者裁定逐字：「所有智能体都要能 thinking，
#: 且开默认到 High」）。它的取值词表不在这里：唯一来源是
#: `modelgw.REASONING_EFFORTS` —— 本模块按设计不认识业务词表（它只管"取到一个字符串"），
#: 在这里再写一份就是同一个词表的第二个定义点。词表外的取值由
#: `modelgw.ModelSpec` 构造时当场拒绝（拼错一个字母会报错，不会静默按缺省跑）。
MODEL_KEYS: tuple[str, ...] = ("vendor", "api_key", "base_url", "name", "reasoning_effort")
#: `models` 段（按角色覆盖，业主 2026-10-14：「允许不同角色智能体用不同模型厂商的
#: 不同 api key」）：键是角色名（`A`–`H` / `V` / `M`）或 `default`，值是那一段
#: `MODEL_KEYS` 的子集。取缝时的梯子是：`models.<角色>` → `models.default` → `model`
#: → 环境变量 → 缺省（唯一实现 `modelgw.spec_for`）。
MODELS_SECTION = "models"
#: `models` 段里那个"谁都兜底"的角色名。
DEFAULT_MODEL_SLOT = "default"
#: `secretary` 段：所有角色的秘书共用的那一档（业主同一条裁定的后半句：
#: 「所有智能体的秘书另外共用一个 api key」）。形状与 `model` 段逐字相同。
SECRETARY_SECTION = "secretary"
#: `workspace` 段认识的键（顺序即文档顺序）。
WORKSPACE_KEYS: tuple[str, ...] = ("projects_dir",)


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


def _bool_cell(key: str, value: Any) -> Any:
    """把"可能是布尔"的那几格归一成 `"true"` / `"false"`；其余键原样返回。

    - JSON 布尔 `True`/`False` ⇒ `"true"`/`"false"`（不许折成空串：空串是"没配"，
      而"配了 false"与"没配"处置相反 —— 前者是用户关掉了形式化，后者是走缺省）；
    - 认得的字符串写法（`true/false/yes/no/on/off/1/0/y/n/t/f`，大小写不敏感）
      归一成同一对字面值；
    - 认不出的字符串原样留着：读侧（:func:`lean_enabled`）要拿它报错，
      在这里折成空串就等于把一个配置错误静默成"没配"。
    """
    if key not in BOOL_KEYS:
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        low = value.strip().lower()
        if low in _TRUE_WORDS:
            return "true"
        if low in _FALSE_WORDS:
            return "false"
        return value.strip()
    return value


def _section(name: str, keys: tuple[str, ...], path: str | Path | None,
             env: Mapping[str, str] | None) -> dict[str, str]:
    """取一段（`toolchain` / `model`）：只认登记过的键，值统一成去空白的字符串。

    为什么"值统一成字符串 + 缺的键补空串"：调用方（三处）都只做
    "非空就用"这一件事，键集合固定它们的 `.get()` 才不会有第二套默认值。
    非字符串的值（数字 / 列表）一律折成空串（=未设置）而不是 `str(value)`：
    把一个 `123` 悄悄当路径用，比"当作没配"更难查。
    例外只有 :data:`BOOL_KEYS` 那几格：它们先过 :func:`_bool_cell`
    （JSON 布尔是它们的正常写法，折成空串会把关掉的开关又打开）。
    """
    raw = load_settings(path, env=env)
    seg = raw.get(name)
    seg = seg if isinstance(seg, Mapping) else {}
    out: dict[str, str] = {}
    for k in keys:
        v = _bool_cell(k, seg.get(k))
        out[k] = v.strip() if isinstance(v, str) else ""
    return out


def toolchain_settings(path: str | Path | None = None, *,
                       env: Mapping[str, str] | None = None) -> dict[str, str]:
    """`toolchain` 段：`lean_bin` / `mathlib_root` / `coq_bin` / `isabelle_bin` /
    `lean_enabled`（缺的补空串）。

    键「总是在」返回里（空串 = 未设置）。调用方据此做"非空就用"，
    不需要在三个地方各写一份 `.get(key, "")`。
    `lean_enabled` 那一格出来的是归一后的 `"true"`/`"false"`（JSON 布尔也认，
    见 :func:`_bool_cell`）；读它请走 :func:`lean_enabled`，那一口还会判
    "读不懂"，并把"这个值是哪一档给的"一起回传。
    """
    return _section("toolchain", TOOLCHAIN_KEYS, path, env)


def lean_enabled(path: str | Path | None = None, *,
                 env: Mapping[str, str] | None = None) -> tuple[bool, str]:
    """这一趟走不走 Lean 形式化 —— 一个布尔，按唯一梯子取。返回 `(值, 来源)`。

    来源取值 `"env"` / `"settings"` / `""`（= 用了缺省 `True`）——
    与 :func:`env_or_setting` 同一条口径："这个值是用户设的还是缺省给的"
    必须能被读出来，否则"我明明关了"与"我没设过"在读数上长得一样。

    取值梯子（唯一口径，见模块 docstring）：环境变量 `AGENTFLOW_LEAN_ENABLED`
    > 设置文件 `toolchain` 段的 `lean_enabled` > :data:`DEFAULT_LEAN_ENABLED`（`True`）。

    ## 读不懂的值必须当场报错（fail-closed）

    写 `"maybe"` / `2` / `"flase"` 这类值时抛 `ValueError`，不静默按缺省跑。
    理由与 `modelgw.normalize_reasoning_effort` 逐字同族：静默按缺省跑会让
    "我关掉了形式化"与"我以为我关掉了"在读数上分不开 —— 而这一次分不开的代价
    是一套 proof 级证据：模型会照旧去派 `check_formal`，或者反过来，
    用户以为形式化开着、实际全趟都没跑。
    错误信息里回显收到的原文（它不是密钥，可以回显）。
    """
    src = dict(os.environ if env is None else env)
    raw = str(src.get(ENV_LEAN_ENABLED) or "").strip()
    if raw:
        return _parse_switch(raw, where=f"环境变量 {ENV_LEAN_ENABLED}"), "env"
    cell = toolchain_settings(path, env=env).get(LEAN_ENABLED_KEY) or ""
    if cell:
        where = f"设置文件 {DEFAULT_SETTINGS_REL} 的 toolchain.{LEAN_ENABLED_KEY}"
        return _parse_switch(cell, where=where), "settings"
    return DEFAULT_LEAN_ENABLED, ""


def _parse_switch(raw: str, *, where: str) -> bool:
    """`"true"`/`"false"`（及认得的那几种写法）⇒ 布尔；认不出 ⇒ `ValueError`。"""
    low = str(raw).strip().lower()
    if low in _TRUE_WORDS:
        return True
    if low in _FALSE_WORDS:
        return False
    raise ValueError(
        f"{where} 读不懂：{raw!r} —— 只认真值 {list(_TRUE_WORDS)} 与假值 "
        f"{list(_FALSE_WORDS)}（大小写不敏感），或者 JSON 的 true/false。"
        "这一个值不静默按缺省跑（缺省是 true）："
        "'我关掉了形式化'与'我以为我关掉了'分不开的代价是一整套 proof 级证据 —— "
        "该跑的没跑，或者该停的没停"
    )


def model_settings(path: str | Path | None = None, *,
                   env: Mapping[str, str] | None = None) -> dict[str, str]:
    """`model` 段：`vendor` / `api_key` / `base_url` / `name` / `reasoning_effort`（缺的补空串）。

    这一口只负责「取值」，不负责脱敏也不负责判定：回显 key 的地方一律走
    `ModelSpec.redacted()`（见模块 docstring 的「安全阀」）。
    `reasoning_effort` 空串 = 未设置 = 用缺省（`modelgw.DEFAULT_REASONING_EFFORT`，High）；
    它的词表外取值也不在这里判（见 `MODEL_KEYS` 上面那段理由）。

    它是默认档：按角色取缝走 :func:`model_settings_for`（那一口把 `models.<角色>`
    与 `models.default` 叠在上面）；`model` 段本身仍然有效（向后兼容：只配过它的
    工作区/机器行为逐字不变）。
    """
    return _section("model", MODEL_KEYS, path, env)


def _models_section(path: str | Path | None = None, *,
                    env: Mapping[str, str] | None = None) -> dict[str, dict[str, str]]:
    """`models` 段原文：`{角色: {键: 值}}`（只认 `MODEL_KEYS`，缺的补空串）。

    形状不合法（不是对象 / 某个槽不是对象）时跳过那一格并在
    :func:`models_reading` 里如实报出来 —— 不清空别人的配置，也不假装读过。
    """
    raw = load_settings(path, env=env)
    seg = raw.get(MODELS_SECTION)
    seg = seg if isinstance(seg, Mapping) else {}
    out: dict[str, dict[str, str]] = {}
    for slot, body in seg.items():
        if not isinstance(body, Mapping):
            continue
        out[str(slot)] = {k: (str(body.get(k)).strip() if isinstance(body.get(k), str) else "")
                          for k in MODEL_KEYS}
    return out


def model_settings_for(role: str, path: str | Path | None = None, *,
                       env: Mapping[str, str] | None = None) -> tuple[dict[str, str], str]:
    """某个角色该用哪一档模型：返回 `(值, 来源)`。

    梯子（唯一口径，唯一实现在这里；`modelgw.spec_for` 直接调它）：

        `models.<角色>`（逐键取非空） → `models.default` → `model` 段 → 空串

    为什么是逐键取而不是"整段覆盖"：运维最常见的写法是"只给 A 换一把 key、
    其余沿用默认档" —— 整段覆盖会把 `base_url` / `name` 一起清空，
    症状是"A 那一路突然按缺省端点跑"，而那不会有任何报错。

    `来源` 记的是这一档的出处（`role:A` / `models.default` / `model` / 空串 =
    什么都没有，调用方接着走环境变量与缺省）。它进读数：出了事要能回答
    "这把 key 是从哪一格来的"。
    """
    base = model_settings(path, env=env)
    slots = _models_section(path, env=env)
    merged = dict(base)
    source = "model" if any(str(v or "").strip() for v in base.values()) else ""
    if DEFAULT_MODEL_SLOT in slots:
        for k, v in slots[DEFAULT_MODEL_SLOT].items():
            if str(v or "").strip():
                merged[k] = v
        if any(str(v or "").strip() for v in slots[DEFAULT_MODEL_SLOT].values()):
            source = f"{MODELS_SECTION}.{DEFAULT_MODEL_SLOT}"
    mine = slots.get(str(role)) or {}
    for k, v in mine.items():
        if str(v or "").strip():
            merged[k] = v
    if any(str(v or "").strip() for v in mine.values()):
        source = f"{MODELS_SECTION}.{role}"
    return merged, source


def secretary_settings(path: str | Path | None = None, *,
                       env: Mapping[str, str] | None = None) -> tuple[dict[str, str], str]:
    """所有角色的秘书共用的那一档模型（业主 2026-10-14 的后半句）。

    梯子与 :func:`model_settings_for` 同形，只是第一格换成 `secretary` 段：
    `secretary` → `models.default` → `model` → 空串。

    为什么秘书要单独一档：秘书的模型调用是"判断类"（`Secretary.judge`），
    与本体那些"干活类"调用在成本与用途上都不是一回事；共用一把 key 才能单独
    限额、单独看账（`usage_ledger` 的 `by_role` 里它们记在各自的 `by_role` 上）。
    """
    base = model_settings(path, env=env)
    slots = _models_section(path, env=env)
    merged = dict(base)
    source = "model" if any(str(v or "").strip() for v in base.values()) else ""
    if DEFAULT_MODEL_SLOT in slots:
        for k, v in slots[DEFAULT_MODEL_SLOT].items():
            if str(v or "").strip():
                merged[k] = v
    own = _section(SECRETARY_SECTION, MODEL_KEYS, path, env)
    for k, v in own.items():
        if str(v or "").strip():
            merged[k] = v
    if any(str(v or "").strip() for v in own.values()):
        source = SECRETARY_SECTION
    return merged, source


def workspace_settings(path: str | Path | None = None, *,
                       env: Mapping[str, str] | None = None) -> dict[str, str]:
    """`workspace` 段：`projects_dir`（缺的补空串）。

    为什么"数据面落点"也算设置：它与工具链地址同族 —— 都是"这台机器上东西放哪"。
    改前 `projects.DEFAULT_PROJECTS_DIR` 里逐字写着一台机器的绝对路径，
    换一台机器就是一句假话（症状是"项目建到了别处"，而不是一句报错）。
    取值顺序由调用方拼（`projects.projects_dir`）：显式参数 > `AGENTFLOW_PROJECTS_DIR`
    > 本段 > 由本包位置推出的工作区根下的 `projects/`。
    """
    return _section("workspace", WORKSPACE_KEYS, path, env)


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


# ====================================================================== 写设置（W4 / 裁定 E1）
#
# 这是新增的一条把密钥写到磁盘的路径，所以它把代价逐条写在明面上：
#
# 1. 只写不读：本函数的返回里 `model.api_key` 恒为 `MASKED_KEY`（真 key 一个字
#    都不回显，也永不回填表单）。要真值请用 `model_settings()` —— 那一口的调用方
#    （`modelgw`）本来就该拿到真值，而"台面"这一侧不该有第二条通路。
# 2. 原子写：先写同目录下的临时文件，再 `os.replace` 换上去。写一半失败时盘上那份
#    逐字节不变（判据 `test_webui_settings_write.py` 有一条负控钉它）。
# 3. 权限尽力收紧：POSIX 上 `chmod 0600` 并回读校验；Windows 上 POSIX 模式位
#    管不到 ACL（回读会如实报告 `mode_enforced=False`）—— 返回值里给的是实测读数，
#    不是"应该是什么"。理由与 `draft/76` 题 E 的代价栏同一条。
# 4. 没配/没装/读不出来 ⇒ 返回 `tri="unknown"` 而不是抛异常：写设置这件事不许把
#    "没查成"折叠成"改成功了"，也不许让一个坏掉的文件把调用方炸掉。

#: `model.api_key` 在返回里恒为它（与 `ModelSpec.redacted` 的占位逐字相同）。
MASKED_KEY = "***"


def _write_sections() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """三段与各自认的键（顺序即文档顺序）—— 写入口与读入口共用同一批常量。"""
    return (("toolchain", TOOLCHAIN_KEYS), ("model", MODEL_KEYS),
            ("workspace", WORKSPACE_KEYS))


def _nested_write_sections() -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    """嵌套的那两段：`models`（槽 → 键）与 `secretary`（平的一段）。

    为什么单列一张表而不是把 `_write_sections` 改成嵌套形状：平的那三段被
    `_section()` / `_masked_section()` / 面板 `/api/machine` 三处按「段→键」读，
    把它们的形状改掉等于同时改三处的契约；嵌套只影响新增的这两段。
    """
    return ((MODELS_SECTION, MODEL_KEYS, ROLE_SLOTS), (SECRETARY_SECTION, MODEL_KEYS, ()))


#: `models` 段允许的槽：十个角色 + `default`。
#:
#: 它从 `schema.ROLES` 现取（不另写名单）：角色名是跨模块约定，
#: 手抄一份会在加角色时静默漏掉那一格。
ROLE_SLOTS: tuple[str, ...] = (DEFAULT_MODEL_SLOT,) + tuple(S.ROLES)


def _clean_write_values(values: Mapping[str, Any]) -> tuple[dict[str, dict[str, str]], str]:
    """把要写进去的东西整理成 `{段: {键: 字面值}}`；不合法 ⇒ `(空, 理由)`。

    两条纪律：

    - 未知段落/未知键直接拒（不悄悄写进去）：一个拼错的键被静默落盘，
      表现是"我明明配了，怎么还是没生效" —— 而设置文件里躺着一行没人读的东西；
    - 值统一成字符串（数字 / 列表折成空串之外的东西一律拒）：`_section()` 那一侧的
      读法是"非字符串当未设置"，写进来一个 `123` 等于写了一条永远读不到的配置。

    空串是合法的值：它是「清掉这一格」的写法（读侧把空串当未设置）。
    """
    known = dict(_write_sections())
    nested = {name: keys for name, keys, _slots in _nested_write_sections()}
    slots_of = {name: slots for name, _keys, slots in _nested_write_sections()}
    out: dict[str, Any] = {}
    for raw_section, raw_seg in (values or {}).items():
        section = str(raw_section)
        if section in nested:
            # 嵌套那两段：`models`（槽 → 键）与 `secretary`（平的一段）。
            if not isinstance(raw_seg, Mapping):
                return {}, f"{section} 段必须是一个对象（收到 {type(raw_seg).__name__}）"
            allowed_slots = slots_of[section]
            if allowed_slots:
                body: dict[str, dict[str, str]] = {}
                for raw_slot, raw_cell in raw_seg.items():
                    slot = str(raw_slot)
                    if slot not in allowed_slots:
                        return {}, (f"不认 {section} 段的这个槽：{slot!r}"
                                    f"（只认 {list(allowed_slots)}）—— 角色名从 "
                                    "`schema.ROLES` 现取，拼错一律拒，免得写进一格没人读的配置")
                    seg, why = _clean_flat(section, slot, raw_cell, nested[section])
                    if why:
                        return {}, why
                    body[slot] = seg
                out[section] = body
            else:
                seg, why = _clean_flat(section, "", raw_seg, nested[section])
                if why:
                    return {}, why
                out[section] = seg
            continue
        if section not in known:
            return {}, (f"不认这段设置：{section!r}（只认 {sorted(known)}）—— "
                        "未知段一律拒，不悄悄写进去")
        seg, why = _clean_flat(section, "", raw_seg, known[section])
        if why:
            return {}, why
        out[section] = seg
    return out, ""


def _clean_flat(section: str, slot: str, raw_seg: Any,
                keys: tuple[str, ...]) -> tuple[dict[str, str], str]:
    """把一段（或 `models` 里的一个槽）整理成 `{键: 字面值}`；不合法 ⇒ `(空, 理由)`。"""
    where = f"{section}.{slot}" if slot else section
    who = f"{section} 段" if not slot else f"{section}.{slot}"
    if not isinstance(raw_seg, Mapping):
        return {}, f"{where} 必须是一个对象（收到 {type(raw_seg).__name__}）"
    seg: dict[str, str] = {}
    for raw_key, raw_value in raw_seg.items():
        key = str(raw_key)
        if key not in keys:
            # 平的那几段沿用原措辞（判据逐字钉它）；嵌套那两段点名 `段.槽`。
            head = f"不认 {who} 的这个键" if slot else f"不认 {who}的这个键"
            return {}, (f"{head}：{key!r}（只认 {list(keys)}）")
        if raw_value is None:
            seg[key] = ""
        elif key in BOOL_KEYS:
            # `lean_enabled` 是布尔键：真布尔与认得的字符串都收，
            # 归一成 `"true"`/`"false"` 落盘（读侧两条写法都认）。
            # 认不出的字符串在这里就拒 —— 写进去一条永远读不懂的配置，
            # 症状是"我配了，运行的时候却报错/却按缺省跑"，那比当场拒更贵。
            cell = _bool_cell(key, raw_value)
            if not isinstance(cell, str) or cell not in ("true", "false", ""):
                return {}, (f"{where}.{key} 只认真布尔或 'true'/'false'"
                            f"（收到 {raw_value!r}）—— 其余写法一律拒，"
                            "免得写进一条读侧读不懂的配置")
            seg[key] = cell
        elif isinstance(raw_value, str):
            seg[key] = raw_value.strip()
        else:
            return {}, (f"{where}.{key} 的值必须是字符串（收到 "
                        f"{type(raw_value).__name__}）—— 非字符串一律拒，"
                        "免得写进一条读侧永远读不到的配置")
    return seg, ""


def _masked_model_cell(seg: Mapping[str, Any]) -> dict[str, str]:
    """一档模型配置的回显形态（`MODEL_KEYS` 的键 + `api_key` 掩码）。

    它同时服务三处：`model` 段、`models` 的每个槽、`secretary` 段 ——
    三处形状逐字相同，掩码规则也就只能有一份（漏一处就是把那把 key 回显出来）。
    """
    out: dict[str, str] = {}
    for k in MODEL_KEYS:
        v = seg.get(k)
        out[k] = v.strip() if isinstance(v, str) else ""
    if out.get("api_key"):
        out["api_key"] = MASKED_KEY
    return out


def _masked_section(section: str, seg: Mapping[str, Any]) -> dict[str, str]:
    """一段的回显形态：`api_key` 换成 `MASKED_KEY`，其余原样。

    key 只写不读那条裁定的落点就是这一个函数（判据的负控把它改成恒等函数，
    正控必须当场红 —— 否则"不回显"这句话没有任何机器读数）。
    """
    if section in ("model", SECRETARY_SECTION):
        return _masked_model_cell(seg)
    out = {}
    for k in dict(_write_sections()).get(section, ()):
        v = _bool_cell(k, seg.get(k))
        out[k] = v if isinstance(v, str) else ""
    return out


def _masked_models(seg: Mapping[str, Any]) -> dict[str, Any]:
    """`models` 段的回显形态：每一个槽的 `api_key` 都换成掩码。

    只掩 `model` 段那一处是最容易写漏的地方（判据 `test_role_models` 里有一条
    负控专门盯它）：按角色配 key 之后，一个漏掩的槽就等于把那把 key 回显出来了。
    """
    out: dict[str, Any] = {}
    raw = seg if isinstance(seg, Mapping) else {}
    for slot, body in raw.items():
        out[str(slot)] = _masked_model_cell(body if isinstance(body, Mapping) else {})
    return out


def _masked_all(merged: Mapping[str, Any]) -> dict[str, Any]:
    """整份设置的回显形态（面板那一侧读它）：平的三段 + `models` + `secretary`。"""
    out: dict[str, Any] = {name: _masked_section(name, merged.get(name) or {})
                           for name, _keys in _write_sections()}
    out[MODELS_SECTION] = _masked_models(merged.get(MODELS_SECTION) or {})
    out[SECRETARY_SECTION] = _masked_section(SECRETARY_SECTION,
                                             merged.get(SECRETARY_SECTION) or {})
    return out


def _tighten(path: Path) -> dict[str, Any]:
    """把权限收紧到"只有本用户能读写"，并如实回报实测读数。

    返回 `{mode, mode_enforced, platform, note}`：

    - POSIX：`chmod 0600` 之后回读 `st_mode & 0o777`，等于 `0o600` 才记
      `mode_enforced=True`；
    - Windows：`chmod` 只影响只读位，管不到 ACL，所以回读通常是 `0o666`
      ⇒ 如实记 `mode_enforced=False` 并把原因写进 `note`。这里刻意不伪造一个
      `0o600` —— "写了个 0600 的读数"与"真的是 0600"是两件事
      （本仓库的三态纪律：没做到的要说出口）。
    """
    plat = os.name
    note = ""
    try:
        os.chmod(path, 0o600)
    except OSError as exc:  # noqa: BLE001 - 收紧失败不该带走这次写入
        return {"mode": "", "mode_enforced": False, "platform": plat,
                "note": f"chmod 失败：{type(exc).__name__}: {exc}"}
    try:
        mode = path.stat().st_mode & 0o777
    except OSError as exc:  # noqa: BLE001
        return {"mode": "", "mode_enforced": False, "platform": plat,
                "note": f"回读权限失败：{type(exc).__name__}: {exc}"}
    enforced = mode == 0o600
    if not enforced and plat == "nt":
        note = ("Windows 上 POSIX 模式位管不到 ACL：这一格是实测读数，"
                "真正的权限面由文件所在目录继承来的 ACL 决定")
    elif not enforced:
        note = "chmod 0600 之后回读的不是 0600（文件系统可能不支持）"
    return {"mode": f"0o{mode:o}", "mode_enforced": enforced, "platform": plat,
            "note": note}


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> str:
    """原子写一个 JSON 文件；返回空串表示写成，否则是问题说明。

    "原子"在这里是可验证的：临时文件与目标同目录（同一次 `os.replace` 才
    谈得上原子），先写完再替换 ⇒ 崩在中间时盘上那份逐字节不变。
    """
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False, default=str) + "\n"
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            # 临时文件删不掉可以忽略：它是个点开头的半成品，目标文件一个字节没动，
            # 而这次调用的结局已经如实记成 unknown（下面那行返回）—— 掩盖不了什么。
            pass
        return f"{type(exc).__name__}: {exc}"
    return ""


def write_settings(values: Mapping[str, Any], path: str | Path | None = None, *,
                   env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """合并写入机器级设置文件（`agentflow/settings.json`）；返回一份回执。

    落点与读侧同一条三档口径（:func:`settings_path`）：显式 `path` →
    `env[AGENTFLOW_SETTINGS]` → 默认落点。`AGENTFLOW_SETTINGS` 指到别处时就写别处，
    所以判据可以在一份临时文件上跑，不碰本机的真设置。

    返回形状（`draft/73` §2.6：与 `load_settings` 同族，但 key 只写不读）：

        {"ok": bool, "tri": "written" | "refused" | "unknown", "reason": str,
         "path": str, "values": {段: {键: 值}}, "permissions": {...}}

    `tri` 是"写设置"这件事的词表（`draft/73` §2.5 给 `/api/settings` 定的那一套），
    不是 `Tri`（`computed/unreadable/not_applicable`）—— 两套字符串不许互相顶替
    （裁定 N1）。HTTP 那一层做映射：`written→computed` · `refused→not_applicable` ·
    `unknown→unreadable`，并把本词原样带进回执的 `extra`。

    `values` 是回显：`model.api_key` 恒为 `MASKED_KEY`。文件里是真值，
    返回里是掩码 —— 这两件事必须能同时成立（判据 `test_webui_settings_write.py`
    的正控逐字钉它，负控把 :func:`_masked_section` 改成恒等函数后必须红）。
    """
    target = settings_path(path, env=env)
    if target is None:
        # "本次没有落点"（注入环境且没给 AGENTFLOW_SETTINGS）⇒ unknown。它不是失败，
        # 但更不是成功：什么都没写这件事必须说得出口。
        return {"ok": False, "tri": "unknown", "path": "", "values": {},
                "permissions": {},
                "reason": ("这次没有设置文件的落点（给了 env 注入而里面没有 "
                           f"{ENV_SETTINGS}）⇒ 什么都没写")}
    clean, why = _clean_write_values(values)
    if why:
        return {"ok": False, "tri": "refused", "path": str(target), "values": _masked_all({}),
                "permissions": {}, "reason": why}
    try:
        current = load_settings(target, env=env)
    except (json.JSONDecodeError, ValueError) as exc:
        # 盘上那份读不出来：不许覆盖它（那会把一个可修的文件变成不可修），
        # 也不许崩 —— 如实记成 unknown 并把真正的那个错误原样带出去。
        return {"ok": False, "tri": "unknown", "path": str(target), "values": {},
                "permissions": {},
                "reason": (f"盘上那份设置文件读不出来，本次什么都没写："
                           f"{type(exc).__name__}: {exc}")}
    merged: dict[str, Any] = dict(current)
    for section, seg in clean.items():
        if section == MODELS_SECTION:
            # 槽级合并：只改点到的那些槽，别的槽一个字节不动
            # （整段覆盖会把"没提过的角色"的配置一次抹掉）。
            base = merged.get(section)
            base = dict(base) if isinstance(base, Mapping) else {}
            for slot, cell in seg.items():
                old = base.get(slot)
                base[slot] = {**(dict(old) if isinstance(old, Mapping) else {}), **cell}
            merged[section] = base
            continue
        base = merged.get(section)
        base = dict(base) if isinstance(base, Mapping) else {}
        base.update(seg)
        merged[section] = base
    problem = _atomic_write_json(Path(target), merged)
    if problem:
        return {"ok": False, "tri": "unknown", "path": str(target), "values": {},
                "permissions": {},
                "reason": f"写设置文件失败（盘上那份没被动过）：{problem}"}
    perms = _tighten(Path(target))
    # 回显按盘上合并后的那一份算（而不是按调用方给的那一份）：这样"写进去的"
    # 与"回报的"是同一件事，漏掉一个键会当场看出来。
    masked = _masked_all(merged)
    # 理由里只写"改了哪几格"的键名，绝不带值 —— 这一句是要进回执与审计的，
    # 带上值就等于让 key 从另一条路回显出来。
    touched = sorted(_touched_names(clean))
    return {"ok": True, "tri": "written", "path": str(target), "values": masked,
            "permissions": perms,
            "reason": f"已写入 {target}（只改了这几格：{touched}）"}


def _touched_names(clean: Mapping[str, Any]) -> list[str]:
    """回执里那句"只改了这几格"的键名（嵌套段展开成 `models.A.api_key` 这种）。"""
    out: list[str] = []
    for section, seg in clean.items():
        if not isinstance(seg, Mapping):
            continue
        if section == MODELS_SECTION:
            for slot, cell in seg.items():
                out.extend(f"{section}.{slot}.{k}" for k in cell)
        else:
            out.extend(f"{section}.{k}" for k in seg)
    return out
