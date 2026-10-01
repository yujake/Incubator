"""E 的工具：**数值实验与形式化验证**。

## 这一层要解决的根本问题

数学里"算对了"与"证完了"是天壤之别。一个能跑数值实验的系统，最大的危险
不是算错，而是把**算对了**说成**证明了** —— 因为这两句话在自然语言里
只差几个字，而在数学上是两个世界。

因此本模块的所有产出都强制带 :data:`agentflow.schema.EVIDENCE_KINDS` 等级，
并且计算类方法**在 schema 层就拿不到 `proof`**（见 `Experiment.validate`）。
这不是注释里的告诫，是写入时的硬约束。

## 为什么 "没有后端" 是一个必须显式表达的状态

`formal.check` 在环境里没有 Lean/Coq 时**必须**返回
`checked=False, reason="no_backend"`，而不是 `ok=False, verified=False`。
理由是本项目反复踩过的三态纪律：把"没做"和"做了但没成"折叠成同一个
`False`，下游就会把"我们没验证"读成"验证没过"，或者更糟——
把"没验证"当成"没问题"。

## 工具与智能体的分工（读了会少走弯路）

本模块的 `verify.run_experiment` / `verify.evidence_for` / `verify.list_experiments`
是本文件里**已有的三个纯函数**（`:func:`check_formal` 与另外两条查询）的薄封装：

- `run_experiment` 是一个**有副作用的动作**（跑子进程 + 写 experiments 表），
  它必须与 `AgentE.run_experiment` 是同一条实现。所以工具 handler 用**惰性
  导入**去调 `agentflow.agent_e`，而不是在这里再写一份。理由同 `agent_d` 对
  `interactions` 的委托：同一份判据写在两处必然漂移，而漂移是**静默**的
  —— "工具写进去的记录"与"AgentE 写进去的记录"字段口径不同，没有任何地方会报错。
- `evidence_for` / `list_experiments` 是纯查询，直接在这里实现，`AgentE` 转发过来。
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .. import schema as S
from ..store import StoreError
from .base import ParamError, ToolError, ToolResult, ToolRegistry, ToolSpec, fail, ok, tool

#: 本模块声明的角色。E 做实验，F 需要读实验结果来推进子目标，
#: G 需要引用实验作为证据，H 需要核对"证据等级有没有被夸大"。
#: **A/B/C/D 不在其中**：它们关心的是文献与关系，不是数值证据。
_ROLES = ("E", "F", "G", "H")

#: **写工具**（会跑子进程 + 写 `experiments` 表）单独声明角色：H 只读，
#: 不能拥有"跑实验并落库"的能力。声明正确 + `for_role` 的结构性拦截，
#: 两道一起上 —— 只靠其中一道都会在后续维护里被绕过。
_ROLES_WRITE = ("E", "F", "G")

#: 形式化检查器的候选可执行文件。**逐个探测，不猜**。
#: 猜"环境里应该有 lean"会让 `checked` 字段变成谎话。
_VERIFIER_CANDIDATES = (
    ("lean", "lean --version"),
    ("coqc", "coqc --version"),
    ("isabelle", "isabelle version"),
)

#: 证据力排序（弱 → 强）。用于 `best_evidence_kind`。
#:
#: ⚠️ **它不是"从 schema 推导出来的"**，而是本模块对 `EVIDENCE_KINDS` 的**运行期
#: 断言**：顺序一旦与 schema 的声明不符，导入期就炸。理由：`best_evidence_kind`
#: 的取值口径（"最强的那个"）如果与 schema 对证据等级的排序不一致，
#: 就会出现"报告说 proof、实验记录里只有 cross_check"这种**无人报错**的分歧。
#: 宁可在这里 fail-closed，也不要靠"两个地方恰好写对了"。
_EVIDENCE_ORDER = ("heuristic", "cross_check", "proof")
assert set(_EVIDENCE_ORDER) == set(S.EVIDENCE_KINDS), (
    f"_EVIDENCE_ORDER={_EVIDENCE_ORDER} 与 schema.EVIDENCE_KINDS={S.EVIDENCE_KINDS} 不一致 —— "
    "证据等级的排序口径必须只有一处定义"
)
#: 最强的证据等级。**从上面的排序里取末位**，而不是再写一遍字面量 "proof"。
_TOP_EVIDENCE = _EVIDENCE_ORDER[-1]


def code_hash(path: str | Path) -> str:
    """脚本内容的 sha256（前 16 位十六进制）。

    为什么实验记录里必须有它：`code_path` 只说明"当时跑的是哪个文件"，
    而文件**是可以被改的**。没有哈希，三个月后那条"可复现"的记录就指向了
    另一段代码 —— 而复现失败时你无法判断是结论错了还是脚本变了。
    """
    p = Path(path)
    if not p.is_file():
        raise ParamError(f"code_hash: 文件不存在：{p}")
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def detect_verifier() -> dict:
    """探测环境里有哪些证明检查器。

    返回 ``{"available": [...], "available_names": [...], "checked": True/False,
    "reason": str, "probe_errors": [...]}``。

    **`checked=False` 只表示"探测本身没做成"**（例如 PATH 不可读、`shutil.which`
    抛异常、二进制在但版本探测起不来），`available=[]` 才是"探测了，确实没有"。
    两者不能合并 —— 合并会把"我们不知道环境里有没有 Lean"读成
    "环境里确定没有 Lean"，而后者会让一条本该走形式化核验的命题
    悄悄停在 cross_check 上。

    ⚠️ 本函数曾经把 `checked` **硬编码成 True**（docstring 承诺了一个
    任何代码路径都返回不了的状态），且工具声明 ``side_effect="none"`` ——
    而它实际上会 `shutil.which` + `subprocess.run` 起外部二进制。
    现在的口径：探测有任何一步失败 ⇒ `checked=False` 并把失败逐条列进
    `probe_errors`；副作用等级由调用方声明为 ``read``（执行本地只读命令，
    `verify.detect_verifier` 的 ToolSpec 见文件末尾）。
    """
    import shutil
    import subprocess

    out: list[dict] = []
    probe_errors: list[str] = []
    for name, cmd in _VERIFIER_CANDIDATES:
        try:
            exe = shutil.which(name)
        except Exception as exc:  # noqa: BLE001 - PATH 不可读等
            probe_errors.append(f"{name}：which 失败（{type(exc).__name__}: {exc}）")
            continue
        if not exe:
            continue
        ver = ""
        try:
            r = subprocess.run(cmd.split(), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=10)
            ver = (r.stdout or r.stderr or "").strip().splitlines()[0] if (r.stdout or r.stderr) else ""
        except Exception as e:  # noqa: BLE001
            ver = f"(版本探测失败：{type(e).__name__}: {e})"
            # "二进制在 PATH 上"这个事实成立（仍记入 available），
            # 但"探测完成"不成立 ⇒ checked=False。两者的区别必须保留：
            # 前者让调用方知道有这个检查器，后者让它知道版本号不可信。
            probe_errors.append(f"{name}：版本探测失败（{type(e).__name__}: {e}）")
        out.append({"name": name, "path": exe, "version": ver})
    checked = not probe_errors
    return {
        "checked": checked,
        "available": out,
        "available_names": [x["name"] for x in out],
        "probe_errors": probe_errors,
        "reason": (
            (
                f"探测到 {len(out)} 个证明检查器：{'、'.join(x['name'] for x in out)}"
                if out
                else "探测完成：环境里**没有**任何受支持的证明检查器 ⇒ 本环境无法产出 proof 级证据"
            )
            if checked
            else f"探测**没做成**（{len(probe_errors)} 处失败）：{'；'.join(probe_errors)}"
            + (
                f"；已探到的检查器：{'、'.join(x['name'] for x in out)}" if out else ""
            )
        ),
    }


def check_formal(
    claim: str,
    *,
    script_path: str | None = None,
    source: str | None = None,
    checker_name: str | None = None,
    imports: Sequence[str] | None = None,
    timeout_sec: float | None = None,
    root: str | Path | None = None,
) -> ToolResult:
    """把一条命题交给 Lean 检查器真跑一次 —— 转发到 `agentflow.formalgw.check_lean`。

    ## 参数名是 `checker_name` 而不是 `name`（`C3`：撞名的代价是 TypeError）

    本工具层调用入口是 `ToolRegistry.call`，而它的**第一个形参就叫 `name`**
    （`tools/base.py` 的 `def call(self, name: str, args=None, *, role=None, ...)`）。
    调用方按名传参时，`name=` 会被 `call` 那一格吃掉，`spec.handler(**merged)`
    再把它交给 handler 的第二个 `name` ⇒ `TypeError: got multiple values for
    argument 'name'`。实测形态：`reg.call('verify.check_formal', role='E',
    claim='c', name='t')` 直接抛那个 TypeError，一个字都到不了本函数。

    所以本函数的声明名参数叫 `checker_name`。`ToolRegistry.call` 与它的
    docstring 一起点名了三个"会吞参数"的名字（`role` / `args` / `budget`），
    而 `name` 是这三个之外**真实存在的第四个**：工具自己声明 `name` 参数时
    无法按名传入。改调用方写法比改注册表便宜，也不会动 `tools/base.py`。

    残留（已于 F6a 处置，不再是残留）：`verify.check_formal` /
    `verify.run_experiment` 的 JSON schema 里曾同时留着旧名 `name` —— 那是
    `R2b-AN-1-A` 实测的假 bug 分类（`validate_params` 认它合法、而 handler
    的形参表里没有它 ⇒ `kind='unexpected'`）。父代理裁定删掉、不接受登记为
    残余，F6a 已删；声明名的唯一入口是 `checker_name` / `run_name`，通用判据在
    `tests/test_schema_handler_params.py`。

    ## 能力表的参数集与工具 schema 的参数集：既非相等也非包含（`R2b-AN-1-C`）

    这里把两套参数集**逐字**写出来（口径差别不许含糊过去）。参照三个层面：
    能力表（`capabilities.py`）、工具 schema（本节所在文件）、以及**方法层的
    真形参表**（`inspect.signature` 实测）。

    - `verify.check_formal`：能力表 `{claim, script_path, source, name, imports,
      timeout_sec}`；工具 schema `{claim, script_path, source, checker_name,
      imports, timeout_sec}`；方法层 `{self, claim, script_path, source, name,
      imports, timeout_sec}`。两个方向的差集都恰好是一个元素：能力表有而工具
      没有 `name`，工具有而能力表没有 `checker_name`。
    - `verify.run_experiment`：能力表 `{claim, claim_key, script_path, params,
      method, for_question_id, timeout, sleep}`；工具 schema `{claim, claim_key,
      script_path, params, method, for_question_id, timeout, run_name, imports}`；
      方法层 `{self, claim, claim_key, script_path, params, method,
      for_question_id, timeout, name, imports}`。能力表有而工具 schema 没有的
      只有 `sleep`；工具 schema 有而能力表没有的是 `run_name` 与 `imports`。
    - 三处口径差别的性质各不相同，不许压成一句"能力表漂了"：
      `checker_name` 是**避撞名**（`ToolRegistry.call` 的第一个形参就叫 `name`，
      工具层再声明 `name` 就永远无法按名传入；`agent_e.py` 里逐字做了一次
      `checker_name=name` 的翻译，所以工具层与能力表的名字不同、而**接线是通的**）；
      `name` 在方法层与能力表上**是对的**（`AgentE.check_formal` 的形参就叫
      `name`，它不经 `ToolRegistry.call`）；`sleep` 只活在能力表与替身夹具之间
      —— 实测 `AgentE.run_experiment` 的形参表里**没有** `sleep`，它**也不收**
      `**kw`，所以不许写成"方法层收得住它"（`capabilities.py` 的
      `E.run_experiment` 逐字登记了它为什么存在，那是另一回事）。
      `D-2` 之后这一格不再只由注释担保：它逐条登记在 `capabilities.PARAM_SEAMS`
      里（键含理由串），并由 `capabilities.assert_capabilities()` 第 [8] 条在导入期核
      —— 声明了而实现不收、又不登记，`import agentflow.capabilities` 直接失败。

    这两套集合今天各自被一条判据看着（`D-2` 窗口补上的；在此之前两套都没有机器判据）：
    能力表的参数集 ↔ 方法层真形参由 `capabilities.assert_capabilities()` 第 [8] 条
    在导入期核 —— 某个 property 声明了而实现不收、又没有登记进
    `capabilities.PARAM_SEAMS`，`import agentflow.capabilities` 直接失败；
    工具 schema 的参数集 ↔ handler 真形参由 `tools.base.check_param_seams` 在
    注册期核（`ToolRegistry.register`，台账 `N-5` 的工具侧落点）。

    仍然没有机器判据的是那个**跨层**的问题：能力表参数集与工具 schema 参数集
    既非相等、也非包含（上面逐字列出的两个差集）。这不是待补的洞，而是一个
    有意的取舍：把两者判成"必须相等或互为子集"会把上面两处合法形态
    （`checker_name` 的避撞名、`sleep` 的替身接缝）判红，于是那条判据的第一次
    运行就得靠"登记例外"放行 —— 而例外表一长，判据就退化成噪音。
    `capabilities.declaration_divergences()` 只比 `side_effect` / `external` 两根轴；
    `ActionSpec.params` 在 `to_dict()` 之外不参与调用期校验（参数合法性由工具
    schema 这边的 `validate_params` 承担）。`R2b-AN-1-C` 要求的是把事实逐字登记，
    这一节就是那处登记，并且它今天仍然是"跨层不做机器比对"这个决定的唯一下游；
    看着工具 schema 与工具 handler 的是 `tests/test_schema_handler_params.py`，
    它按定义只走工具层这一侧。


    ## 这一层只做三件事，判据一条都不重复

    1. 把调用方的四种输入形态归一（源码 / 工作区内的脚本路径 / 声明名 / imports 与超时）；
    2. 转发给 `formalgw.check_lean`，它是"什么算证明"的唯一定义处；
    3. 原样透传 `formalgw` 的受控状态，并按本工具既有的八键形态返回。

    判定顺序、sorry 判据、公理审计、声明名核对、超时归类、库不可得归类全部在
    `formalgw` 里，本函数不复制其中任何一条 —— 两处各写一份判据的漂移是静默的，
    而那正是桥接层最不能出的错（清单理由逐字："桥接层说谎 ⇒ proof 级证据是假的"）。

    ## `reason` 是原样透传的（不是"折成三态"）

    `reason` 取的就是 `formalgw` 报的那个状态（受控词表十值，外加本层自己的
    `no_script`），不做任何改名或折叠 —— 「把十值折成三态」是这一层曾经的
    文档说法，而实现从来是原样透传（`G-25③`：文档与实现不符时，改文档去贴实现）。
    调用方需要的那两个三态位各自独立地算：`checked` 直接读
    `formalgw.evidence_of` 的结论，`verified` 只对唯一那个通过状态为 True。
    （两栏同源的那一层见 `E-14`：`proved` 也读 `evidence_of`，本层不再用
    `status == PROOF_STATUS` 把"什么叫证明"重算一遍。）

    ## 三态纪律（与接线前的口径一致，只是现在真的会跑了）

    `formalgw.STATUSES` 的十个取值折成两问：`checked` = "这次查成了吗"，
    `verified` = "查成了、而且过了吗"：

    ==========================  =========  ==========  ==================================
    status                      checked    verified    含义
    ==========================  =========  ==========  ==================================
    `verified`                  True       True        proof 级证据（唯一的通过）
    `compile_error`             True       False       查了，没通过
    `uses_sorry`                True       False       查了，那份"证明"里有 sorry/admit
    `extra_axioms`              True       False       查了，用了允许集之外的公理
    `decl_mismatch`             True       False       查了，但声明名对不上
    `timeout`                   False      None        没查成（不是"证伪了"）
    `import_unavailable`        False      None        没查成（库不可得：编译根本没开始）
    `no_backend`                False      None        没查成（环境里没有后端）
    `tool_crashed`              False      None        没查成（桥接层自己出错）
    `source_unreadable`         False      None        没查成（`script_path` 给的源码读不到，`E-3`）
    ==========================  =========  ==========  ==================================

    `import_unavailable` 与 `compile_error` 的分界是这一层的三态纪律里最容易错的一处：
    库没装时检查器回 `unknown package 'X'`，编译**根本没开始**，所以它是"没查成"；
    把它读成"查了、没通过"会让一次环境配置问题看起来像一次数学结论。

    只有 `verified` 才给 `verified=True`：`checked=True + verified=False` 表示
    "跑过了、它不是证明"，而 `verified is None` 一律表示"本次没有验证结论"，
    绝不写成 `False`（那会读成"验证失败"）。`checked` 直接取自
    `formalgw.evidence_of` 的结论，而不是在这里再列一遍状态名。

    ## 调用方没给源码时

    留给 `formalgw.check_lean` 的 `source_path` 入口去读那个文件：读不到时它按
    "源码读不到"（`source_unreadable`，`E-3`）如实收口，于是"脚本写错了路径"
    与"后端不在"分得开，而两者都不会被读成通过 —— 尤其不会被读成
    `decl_mismatch`（"查了、声明名对不上"），那会让调用方去改数学而不是改路径。
    本函数不自己读文件，也不把读文件失败改成 `no_script` ——
    那会把一次可诊断的失败折叠成"调用方没给输入"。

    ## 探测没做成时是 `tool_crashed` 而不是 `no_backend`（`E-4`）

    `detect_verifier` 的 `checked=False` 与 `available == []` 是两条独立的事实：
    前者是"探测本身没做成"（`which` 抛了、PATH 读不出来），后者才是
    "探测完成：环境里确实没有"。此前本函数只看 `available`，于是把"我们不知道
    环境里有没有 Lean"报成 `no_backend`（一个有效结论），而
    `formalgw.detect_backend` 对同一输入报 `probe_failed` —— 同一个事实两种说法，
    且没有交叉断言。现在两支分得开：`checked=False` ⇒ `tool_crashed`；
    `checked=True 且 available == []` ⇒ `no_backend`（不变）。
    三态位也对齐：两支都是 `checked=False, verified=None`，都绝不写成
    `verified=False`（那是"查了、命题不成立"）。

    ## `root`：相对路径必须解析到工作区，而不是解析到进程的 CWD（`P-8` 接线时实测）

    `source_path` 的读发生在 `formalgw` 里（`Path(source_path).read_text()`），
    而那个读用的是进程当前目录。调用方给的是工作区内的相对路径
    （`AgentE.check_formal` 的契约就是如此），于是"工作区 ≠ 进程 CWD"时
    那个文件根本读不到：`E-3` 之前实测得到 `decl_mismatch`（一次路径解析问题
    被报成"你证的东西不在文件里"，而后者是数学结论层面的说法）；`E-3` 之后
    得到 `source_unreadable`（"没查成"，`checked=False, verified=None`），
    `detail` 里是 `FileNotFoundError: 'p8_probe.lean'`。

    所以 `root` 给定时，相对路径在这里就被解析成绝对路径（并拒绝越界），
    不再依赖调用进程的 CWD。`root` 由装配层（`register` 的 handler）与
    `AgentE` 显式给；不给时行为与接线前逐字相同（原样转发相对路径）。

    ## 副作用与**审批面**（`axes-4`：这三处说法此前互相矛盾）

    `source` 给的是内存里的源码时，`formalgw` 会写一份临时 `.lean` 文件（跑完即删）；
    `workdir` 为 None 时它建的是临时目录。脚本路径存在时源码仍从文件读。因此
    本工具的实际副作用是"起检查器子进程 + 写临时文件"，工具声明为 `read`
    （执行本地只读命令）—— 这与 `verify.detect_verifier` 同一口径：`none` 表示
    "什么都不做"，而它显然不是。

    **但"都不需要审批"只对 `detect_verifier` 成立**：

    | 工具 | 声明 | 沙箱未声明可用时 `needs_approval` |
    |---|---|---|
    | `verify.detect_verifier` | `read` + `external="none"` | `False`（不需要审批） |
    | `verify.check_formal` | `read` + `external="exec"` | **`True`（需要审批）** |

    `check_formal` 的第二根轴是 `exec`，因为"执行一个由调用方决定内容的程序"这件事
    **确实**发生在它身上（源码来自调用方）—— 而那正是 `NEEDS_APPROVAL` 的判据。
    旧版这段 docstring 逐字写着"两者都不需要审批，所以审批面没有变化"，
    与同一个文件的声明（`:751-752` 的注释也写了"它从此需要审批"）
    **给出两个相反结论**。按 docstring 读的人（含写审批面报告、
    写 `docs/ROLE-SPECS.md` 审批列的人）会把 `check_formal` 记成不需要审批。

    ⚠️ **不要为了让这句话成真去改声明**：把 `declared_external` 从 `exec` 改成 `none`
    会把"执行调用方给的程序"这件事从第二根轴上抹掉，回到"两根轴压成一档"的老形态。
    `.noai-paths` 给这个文件的登记理由逐字是"桥接层说谎 ⇒ proof 级证据是假的"。
    """
    det = detect_verifier()
    if not det["available"]:
        # `E-4`：`available` 与 `checked` 是两条独立的事实（见 `detect_verifier`
        # 的 docstring：`checked=False` 只表示"探测本身没做成"）。
        # 此前只看 `available`，于是"我们不知道环境里有没有 Lean"被说成
        # "环境里确定没有 Lean" —— 两者的处置相反（修探测 vs 接受没有形式化），
        # 而且 `formalgw.detect_backend` 对同一输入报的是 `probe_failed`，
        # 同一个事实在这里却有第二种说法。现在与它对齐：探测没做成 ⇒
        # `tool_crashed`（同样是"没查成"，绝不是"环境里没有检查器"）。
        if not det.get("checked", True):
            return ok(
                {
                    "checked": False,
                    "verified": None,
                    "claim": claim,
                    "reason": "tool_crashed",
                    "detail": (
                        "证明检查器探测没做成（不是'环境里没有检查器'）："
                        f"{det.get('reason') or ''}"
                        f"；probe_errors={list(det.get('probe_errors') or [])}"
                    ),
                    "verifier_output": "",
                    "missing_imports": [],
                    # 探测都没做成 ⇒ 没有任何检查器状态可透传（空串是诚实的值）。
                    "verifier_status": "",
                },
                note="未验证：探测本身没做成（不等于环境里没有检查器，也不等于验证失败）",
            )
        return ok(
            {
                "checked": False,
                "verified": None,
                "claim": claim,
                "reason": "no_backend",
                "detail": det["reason"],
                "verifier_output": "",
                "missing_imports": [],
                # `G-24①` 的透传字段：这一支是"探测不到检查器"，
                # 检查器一个字都没说 ⇒ 空串是诚实的值（"没有检查器状态可透传"）。
                "verifier_status": "",
            },
            # 注意：`note` 是产物文本（会被渲染给读者），所以它里面的强调标记
            # 与 R009 对注释/docstring 的判据无关，保持原样。
            note="未验证：环境无证明检查器。**这不等于验证失败**",
        )
    if not (source and source.strip()) and not script_path:
        return ok(
            {
                "checked": False,
                "verified": None,
                "claim": claim,
                "reason": "no_script",
                "detail": (
                    "环境里有检查器，但调用方既没有给 Lean 源码（source），"
                    "也没有给待检查的脚本路径（script_path）⇒ 没做验证"
                ),
                "verifier_output": "",
                "missing_imports": [],
                "verifier_status": "",
            }
        )

    # 惰性导入：本模块的顶层只依赖标准库，而 `formalgw` 会拉起检查器那一层。
    # 方向也是刻意的 —— `formalgw` 反向 import 本模块的 `detect_verifier`，
    # 顶层互引会成环。
    from ..formalgw import STATUSES, check_lean

    nm = str(checker_name or "")
    if source and source.strip():
        src = str(source)
        path_arg: str | None = None
    else:
        # 脚本路径转发给 `formalgw.check_lean` 的 `source_path` 入口 ——
        # 本层不自己读文件。理由：读不到时的收口方式（"文件里没有那条声明"）
        # 是与声明名核对同一处的判据，转发层再实现一遍就会长出第二份口径。
        #
        # 但"谁把相对路径变成能打开的东西"必须有一个确定的答案：`formalgw`
        # 用 `Path(source_path).read_text()` 打开它，那是进程 CWD 相对 ——
        # 而调用方给的是工作区内的相对路径。`root` 给定时在这里解析，
        # 越界即拒（判据与 `verify.code_hash` 的 `_resolve` 同一份）。
        src = ""
        cand = Path(str(script_path))
        if root is not None and not cand.is_absolute():
            base = Path(root).resolve()
            cand = (base / cand).resolve()
            try:
                cand.relative_to(base)
            except ValueError:
                raise ParamError(
                    f"check_formal：script_path 越出工作区：{script_path!r}（工作区={base}）"
                    "—— 读工作区外的文件不在这个工具的语义里"
                ) from None
        path_arg = str(cand)
        if not nm:
            nm = cand.stem

    if not nm:
        # 没有名字 ⇒ `#print axioms` 与声明名核对都无从谈起。刻意**不**回退成
        # 文件名：一个猜出来的名字会让"声明名核对"这条判据在无声中失效，
        # 而它正是拦住"声称证了 foo、文件里却没有 foo"的那一条。
        return fail(
            "check_formal：拿不到声明名 —— 源码里没有具名声明（只有 example 或全被注释），"
            "调用方也没有显式给 checker_name。声明名核对与公理审计都要求这个名字，"
            "猜一个名字等于把那条判据悄悄关掉。请显式给出 checker_name。"
            "（参数不叫 name 的理由见本函数的 docstring：name 与 ToolRegistry.call "
            "的第一个形参撞名，按名传入会 TypeError。）",
            kind="param_error",
            claim=claim,
            checker_name=str(checker_name or ""),
        )

    try:
        raw = check_lean(
            src,
            name=nm,
            imports=imports if imports is not None else ("Mathlib",),
            timeout_sec=float(timeout_sec) if timeout_sec is not None else 600,
            source_path=path_arg,
        )
    except ValueError as exc:
        # `check_lean` 对非法声明名 / 空源码参数抛 ValueError。它是调用方写错了
        # 参数，不是"验证没过"，因此必须停在 param_error 上。
        # 三条 fail 分支各自带上 `checker_name`：失败时 data 是 None（一个键都不给），
        # 声明名只在 meta 里留痕 —— 否则"是哪个名字出的错"在诊断时无从查起。
        return fail(
            f"check_formal：参数不合法：{exc}", kind="param_error", checker_name=nm
        )
    except Exception as exc:  # noqa: BLE001 - 桥接层的任何异常都只能落"没查成"
        return fail(
            f"check_formal：检查器桥接层出错（{type(exc).__name__}: {exc}）⇒ 没查成，"
            "既不是通过也不是证伪。",
            kind="check_failed",
            checker_name=nm,
        )

    # `evidence_of` 是"这次到了什么等级"的唯一定义处（`_conclude` 每次都算好），
    # 因此 `checked` 从它读，而不是在这里再列一遍"哪些状态算查了"。
    ev = raw.get("evidence") or {}
    status = str(raw.get("status") or "")
    checked = bool(ev.get("checked"))
    # `E-14`：`proved` 与 `checked` 同源 —— 都读 `formalgw.evidence_of` 的结论，
    # 而不是在这里用 `status == PROOF_STATUS` 把"什么叫证明"再算一遍。
    # 今天两者等价（`PROOF_STATUS` 是唯一算 proved 的状态），但 formalgw 若新增
    # 第二个算 proved 的路径（例如带证书的 exhaustive_search），这一层会与
    # `evidence_of` 静默分家 —— 判据只留一处定义。
    proved = bool(ev.get("proved"))
    return ok(
        {
            "checked": checked,
            "verified": True if proved else (False if checked else None),
            "claim": claim,
            "reason": status if status in STATUSES else "tool_crashed",
            "detail": raw.get("reason") or "",
            "verifier_output": (
                (str(raw.get("stdout") or "") + "\n" + str(raw.get("stderr") or "")).strip()
            ),
            # 哪个库不可得。空列表 = 没有这种抱怨（**不是**"库都在"：
            # 库都在的证据是 `verified`，而这个键只说"检查器没有抱怨找不到包"）。
            # 为什么它必须在这里有位置：`reason` 只回答"哪一类结局"，
            # 而 `import_unavailable` 的处置（装哪个库）要求知道包名。
            "missing_imports": [str(x) for x in (raw.get("missing_imports") or [])],
            # `G-24①` 的透传字段：检查器原样报的那个状态，逐字（不做归一）。
            # 它与 `reason` 今天逐字相同是**刻意**的 —— 收口与透传是两个不同的
            # 承诺：`reason` 承诺"值在受控词表里"（调用方可以穷举它），
            # `verifier_status` 承诺"这就是检查器说的那一个值"（哪怕上游换了名字）。
            # 把多值压成一个模糊值（`N-5`）在这两栏里都是禁止的。
            "verifier_status": status,
        },
        # 机器可读的留痕：受控词表之外的状态一个都不许被当成通过。
        status=status,
        checked_source=(raw.get("checked_source") or "")[:2000],
        axioms=raw.get("axioms"),
        sorry_count=raw.get("sorry_count"),
        decl_matches=raw.get("decl_matches"),
        declared_in_source=raw.get("declared_in_source"),
        source_sha256=raw.get("source_sha256"),
        source_path=raw.get("source_path"),
        ran=raw.get("ran"),
        backend_status=((raw.get("backend") or {}).get("status") if isinstance(raw.get("backend"), Mapping) else None),
        evidence_kind=ev.get("evidence_kind"),
    )


# ---------------------------------------------------------------- 证据查询（纯函数）
#
# 这两个函数**不接收 store 实例以外的东西**，也不做任何写入：它们是 E 的"读侧"，
# 被 AgentE 的方法与工具层同时使用（同一份实现）。


def evidence_for(
    store: Any,
    claim_key: str | None = None,
    *,
    for_question_id: str | None = None,
) -> dict:
    """按 ``claim_key`` 和/或 ``for_question_id`` 汇总已有实验证据。

    ## 三态纪律（本函数的核心）

    ================================  ==========================================
    调用方式                            返回
    ================================  ==========================================
    给了 claim_key / for_question_id    ``checked=True``，experiments 可能为空
    两个都不给                          ``checked=False``（**没查**）
    ================================  ==========================================

    "没查"与"查了、没有"必须分开：前者是调用方的问题（它不知道该查什么），
    后者是一个**有效结论**（"这条命题本地没有任何实验证据"）。

    ``proved`` 是三态（`errors-1`，登记在 `draft/28`）：
    **没查**时它是 ``None``，**查了**时才是 ``True``/``False``。
    旧版在"没查"那一支写 ``False`` —— 而那正是本文件 213-215 行明令禁止的折叠：
    "没查成时该位写 None、绝不写成 False"（`check_formal` 的 `verified` 就是这么做的）。
    只读 `proved` 的调用方旧版无法区分"没查"与"查了没有 proof 级证据"。
    """
    if claim_key is None and for_question_id is None:
        # 形状与"查了"那一支**完全一致**（含分档计数的零值）：调用方可以无条件地读
        # `result_counts`，而"这一支少了几个键"正是 4.5 类缺陷的温床 ——
        # 声明一套键、某些分支给另一套，会让调用方按 `.get()` 一路写下去，
        # 把结构性缺失读成"计数为零"。
        return {
            "checked": False,
            "experiments": [],
            "count": 0,
            "result_counts": {k: 0 for k in S.EXPERIMENT_RESULTS},
            "negation_counts": {k: 0 for k in S.NEGATION_KINDS},
            "best_evidence_kind": None,
            # 三态：**没查** ⇒ None（不是 False）。`checked=False` 与它一起表达同一件事。
            "proved": None,
            "reason": (
                "既没有 claim_key 也没有 for_question_id ⇒ **没查**"
                "（`proved` 为 None：不是'没有证据'，而是'没去查'）"
            ),
        }

    hits: list[dict] = []
    for row in store.rows("experiments"):
        if claim_key is not None and row.get("claim_key") != claim_key:
            continue
        if for_question_id is not None and row.get("for_question_id") != for_question_id:
            continue
        hits.append(row)
    hits.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("experiment_id") or "")))

    if not hits:
        scope = []
        if claim_key is not None:
            scope.append(f"claim_key={claim_key!r}")
        if for_question_id is not None:
            scope.append(f"for_question_id={for_question_id!r}")
        return {
            "checked": True,
            "experiments": [],
            "count": 0,
            "result_counts": {k: 0 for k in S.EXPERIMENT_RESULTS},
            "negation_counts": {k: 0 for k in S.NEGATION_KINDS},
            "best_evidence_kind": None,
            "proved": False,
            "reason": (
                f"已查（{' 且 '.join(scope)}）：**没有**任何登记在案的实验证据。"
                "这是'查了、没有'，不是'没查'"
            ),
        }

    kinds = [str(r.get("evidence_kind") or "") for r in hits]
    known = [k for k in kinds if k in _EVIDENCE_ORDER]
    best = max(known, key=_EVIDENCE_ORDER.index) if known else None
    proved = best == _TOP_EVIDENCE
    # FC-10：结果必须**分档计数**，不许只给一个"有证据/没证据"的布尔。
    # 只有布尔时，"算出来支持"与"脚本崩了"在调用方眼里长得一样。
    result_counts = {k: 0 for k in S.EXPERIMENT_RESULTS}
    negation_counts = {k: 0 for k in S.NEGATION_KINDS}
    for r in hits:
        res = str(r.get("result") or "")
        if res in result_counts:
            result_counts[res] += 1
        neg = r.get("negation_kind")
        if neg in negation_counts:
            negation_counts[str(neg)] += 1
    return {
        "checked": True,
        "experiments": hits,
        "count": len(hits),
        "result_counts": result_counts,
        "negation_counts": negation_counts,
        "best_evidence_kind": best,
        "proved": proved,
        "reason": (
            f"已查：{len(hits)} 条实验（{result_counts}），最强证据等级为 {best!r}"
            + ("（有 proof 级证据）" if proved else "（**没有** proof 级证据 ⇒ 未被证明）")
        ),
    }


def list_experiments(store: Any, *, claim_key: str | None = None, limit: int | None = None) -> dict:
    """按登记顺序列出实验记录（只读）。

    与 `evidence_for` 的分工：`evidence_for` 回答"这条命题被证明了吗"，
    本函数回答"E 到底做过哪些实验"。**少了后者，"没做过"就无法自证**。
    """
    lim = None if limit is None else max(0, int(limit))
    rows = [r for r in store.rows("experiments") if claim_key is None or r.get("claim_key") == claim_key]
    rows.sort(key=lambda r: (str(r.get("created_at") or ""), str(r.get("experiment_id") or "")))
    total = len(rows)
    if lim is not None:
        rows = rows[:lim]
    return {
        "checked": True,
        "total": total,
        "returned": len(rows),
        "truncated": bool(lim is not None and total > lim),
        "experiments": [
            {
                "experiment_id": r.get("experiment_id"),
                "claim_key": r.get("claim_key"),
                "method": r.get("method"),
                "evidence_kind": r.get("evidence_kind"),
                "result": r.get("result"),
                "negation_kind": r.get("negation_kind"),
                "exit_code": r.get("exit_code"),
                "code_path": r.get("code_path"),
                "code_hash": r.get("code_hash"),
                "for_question_id": r.get("for_question_id"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ],
        "reason": f"共 {total} 条实验记录，返回 {len(rows)} 条",
    }


def _resolve_root(root: str | Path | None) -> Path:
    """工作区根。``None`` ⇒ cwd（与外部 `root` 参数的既有默认一致）。"""
    return Path(root) if root else Path.cwd()


def _agent_for(store: Any, root: str | Path | None):
    """构造一个 AgentE。**惰性导入**：本模块被 agent_e 反向引用，模块级导入会成环。"""
    from ..agent_e import AgentE  # 惰性：避免 tools ↔ agent 的循环导入

    return AgentE(store, workspace_root=_resolve_root(root))


@tool(
    "verify.code_hash",
    "计算工作区内一个脚本文件的 sha256（前 16 位），用于实验记录的可复现性绑定",
    {
           "type": "object",
           "properties": {"path": {"type": "string", "description": "工作区内的相对路径"}},
           "required": ["path"],
           "additionalProperties": False,
           },
    side_effect="read",
    roles=_ROLES,
    returns=(
            "{'path': str, 'code_hash': str}；"
            "失败：ok=False + kind(io_error/param_error) + data=None。"
            "param_error = 路径越界（工作区参数守卫拒绝）；"
            "io_error = 工作区内这个文件读不到（不存在 / 是目录 / 被占用 / ACL 拒绝）"
            ),
    tags=("experiment", "reproducibility"),
)
def _verify_code_hash(_hash_of, path):
    """verify.code_hash 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_hash_of）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return _hash_of(path)

@tool(
    "verify.detect_verifier",
    "探测环境里可用的证明检查器（Lean/Coq/Isabelle）。返回的是事实，不是猜测",
    {"type": "object", "properties": {}, "additionalProperties": False},
    # read（**不是 none**）：它要 `shutil.which` + `subprocess.run` 起外部二进制
    # （`detect_verifier` 里逐条 `--version`）。声明 `none` 等于说"这个工具
    # 什么都不做" —— 而"不起进程"与"起了进程但只读"是两件不同的事。
    side_effect="read",
    roles=_ROLES,
    returns="{'checked','available','available_names','reason','probe_errors'}",
    tags=("experiment", "formal"),
)
def _verify_detect_verifier():
    """verify.detect_verifier 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（无）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return ok(detect_verifier())

@tool(
    "verify.check_formal",
    (
            "把一条命题（Lean 源码）交给检查器真跑一次：只有 verified 才给 proof 级证据；"
            "compile_error/uses_sorry/extra_axioms/decl_mismatch 是'查了没通过'；"
            "timeout/import_unavailable/no_backend/tool_crashed/source_unreadable 是'没查成'，"
            "绝不被读成通过或证伪（import_unavailable = 库不可得，编译根本没开始，"
            "missing_imports 里是检查器说找不到的包；source_unreadable = "
            "script_path 给的源码文件读不到）"
            ),
    {
           "type": "object",
           "properties": {
            "claim": {"type": "string"},
            "script_path": {
                "type": "string",
                "description": "工作区内待检查的 .lean 脚本；给了 source 时以 source 为准",
            },
            "source": {"type": "string", "description": "Lean 源码全文（与 script_path 二选一）"},
    # 注意：参数名是 checker_name，不是 name：ToolRegistry.call 的
    # 第一个形参就叫 name（tools/base.py），工具自己再声明一个 name
    # 就永远无法按名传入 —— 实测 reg.call('verify.check_formal',
    # name='t') 抛 TypeError: got multiple values for argument 'name'。
    # 详见 check_formal 的 docstring（C3）。
            "checker_name": {
                "type": "string",
                "description": "要核对的声明名（公理审计与声明名核对都要求它；不给时取文件名词干）",
            },
    # 这里没有旧名 `name`：`R2b-AN-1-A` 实测它是一条会把人
    # 引向假 bug 的声明 —— `validate_params` 认它合法、而 handler
    # 的形参表里没有它 ⇒ `spec.handler(**merged)` 抛 TypeError、
    # 被 base.py 兜成 kind='unexpected'（'库内部出错'那一类），
    # 于是调用方拿着 schema 的声明去写参数，拿回来的是一个
    # 会让人去查工具注册表的分类。父代理裁定删掉它，不接受
    # "登记为残余"；声明名的唯一入口是 `checker_name`。
    # 守住它的通用判据在 tests/test_schema_handler_params.py
    # （schema 的每个 property 都必须被 handler 签名接受）。
            "imports": {"type": "array", "items": {"type": "string"}},
            "timeout_sec": {"type": "number", "minimum": 1},
           },
           "required": ["claim"],
           "additionalProperties": False,
           },
    # 注意：handler 的形参名必须是 checker_name，不许为了省事沿用它原来的
    # 名字 name：`ToolRegistry.call` 会用关键字参数调用 handler，
    # 而它传进来的键名就是这里声明的属性名。名字对不上 ⇒ 每次调用都 TypeError。
    # 装配时的 root 是"工作区"在这里的唯一来源：相对 script_path
    # 必须解析到它，而不是解析到进程 CWD（见 `check_formal` 的 docstring）。
    # read + exec：它真的起检查器子进程（命令内容由调用方给），
    # 并可能写临时 .lean 文件；两者都如实声明，各占一根轴。
    # ⚠️ 字段名是 `declared_external`（**不是** `external` —— 后者是属性名，
    # 写进构造器会 `TypeError`，G-45 已登记）。
    #
    # `roles` 从 `_ROLES` 改成 `_ROLES_WRITE`，理由与 `verify.run_experiment`
    # 同族但更值得写下来：**声明本身必须正确**，不能靠 `for_role` 兜底。
    # `role_filter_notes` 的语义是"声明写错"的留痕，靠过滤兜底会让留痕
    # 变成常态噪音 —— 而噪音里会藏着真正的错误。
    # 行为变化（如实登记）：它从此需要审批（沙箱未声明时 `egress`/`exec`
    # 一律要签字），H 的工具面因此从 23 条变 22 条。
    side_effect="read",
    roles=_ROLES_WRITE,
    # `records` 声明的是 ok 分支的键集合（与同模块 `verify.code_hash`
    # 同一种写法：分号后面写失败分支的形态）。分号是刻意的：`C2` 之前这里
    # 写的是一个无条件的 8 键集合，而本工具有 3 条 `return fail(...)`
    # 分支（拿不到声明名 / 声明名参数不合法 / 桥接层抛异常）走的是
    # `ok=False` + `data=None`，一个键都不给 —— 声明逐字描述的是成功路径，
    # 却长得像在描述全部路径，于是读声明的人以为失败分支也给这 8 个键。
    #
    # `D2`：这个字符串不是"逐分支采样"的契约。`tests/test_tools_audit_fixes.py`
    # 的 `test_check_formal_return_shape_matches_its_declaration` 只采样 3 条
    # ok 分支（无后端 / 无脚本 / 声明名对不上），断言它们的键集合与这里逐字相同；
    # 3 条 fail 分支由本行的分号形态声明，目前没有逐分支采样用例。
    # 待办：给失败分支补逐分支采样 —— 由父代理（`tests/` 的归属方）在
    # C2 的失败分支口径定稿之后补进 tests/test_tools_audit_fixes.py；
    # 在那之前，"失败分支给什么键"只有这一行声明，没有判据钉着。
    #
    # `verifier_status`（`G-24①`）是第 8 个键：它是检查器原样报的那个状态
    # 的透传栏，与 `reason`（受控词表）成对存在。
    returns=(
            "{'checked','verified','claim','reason','detail','verifier_output','missing_imports','verifier_status'}"
            "；失败（拿不到声明名 / 声明名参数不合法 / 桥接层抛异常）：ok=False + kind(param_error/check_failed) + data=None"
            "（一个键都不给 —— 失败分支不承诺上面那套键）"
            ),
    tags=("experiment", "formal"),
    external="exec",
)
def _verify_check_formal(base, claim, script_path=None, source=None, checker_name=None, imports=None, timeout_sec=None):
    """verify.check_formal 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（base）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    check_formal(
               claim,
               script_path=script_path,
               source=source,
               checker_name=checker_name,
               imports=imports,
               timeout_sec=timeout_sec,
               # 装配时的 root 是"工作区"在这里的唯一来源：相对 script_path
               # 必须解析到它，而不是解析到进程 CWD（见 `check_formal` 的 docstring）。
               root=base,
               )
    )

@tool(
    "verify.run_experiment",
    (
            "在独立进程里跑一个工作区内的脚本并登记一条 Experiment 行（会写表 + 跑子进程）。"
            "脚本自报 evidence_kind='proof' 会被降级为 cross_check；崩溃一律记 inconclusive；"
            "method='formal' 时改走检查器（.lean 产物），只有检查器 verified 才登记 proof"
            ),
    {
           "type": "object",
           "properties": {
            "claim": {"type": "string"},
            "claim_key": {"type": "string"},
            "script_path": {"type": "string", "description": "工作区内的相对路径（formal 时必须是 .lean）"},
            "params": {"type": "object"},
            "method": {"type": "string", "enum": list(S.EXPERIMENT_METHODS)},
            "for_question_id": {"type": "string"},
            "timeout": {"type": "integer", "minimum": 1},
    # `P-8`：只对 method='formal' 有意义（`AgentE.run_experiment`
    # 对计算类方法收到它们时会拒绝，不是静默忽略）。
    #
    # 注意：参数名是 run_name，不是 name（`C3`）：`ToolRegistry.call`
    # 的第一个形参就叫 name，工具再声明一个 name 就永远无法按名传入
    # （实测 reg.call(..., name='t') 抛 TypeError: got multiple values
    # for argument 'name'）。理由与写法同 verify.check_formal。
            "run_name": {
                "type": "string",
                "description": "formal：要核对的声明名（不给时取 .lean 文件的名词干）",
            },
    # 这里没有旧名 `name`，理由与 verify.check_formal 逐字相同
    # （`R2b-AN-1-A`：schema 声明了 handler 收不下的参数
    # ⇒ kind='unexpected' 这个假 bug 分类）。声明名的唯一入口
    # 是 `run_name`，判据在 tests/test_schema_handler_params.py。
            "imports": {
                "type": "array",
                "items": {"type": "string"},
                "description": "formal：这次检查要加载的库（不给时用检查器的默认值）",
            },
           },
           "required": ["claim", "claim_key", "script_path"],
           "additionalProperties": False,
           },
    side_effect="write_local",
    # `P-6` + `P-20`（B3）：它执行调用方给的脚本，所以 `external="exec"` ——
    # 两根轴各说各的真话：`effect=write_local`（它写 experiments 表）、
    # `external=exec`（它跑我们不拥有的程序）。
    #
    # 这与上一版注释里"严格说应当是 network"是不同的判断：那版把两根轴压成一个
    # 遗留取值，于是"写盘"与"起进程"分不开。`exec` 更精确，而且行为不变：
    # 它与 `write_local` 一样需要审批（`NEEDS_APPROVAL`），而只读角色本来就拿不到它
    # （它是写工具）。所以这一次改的是声明的精度，不是权限面。
    # 必须与能力层同轮改（`capabilities.py` 的 `E.run_experiment` 也给了 `exec`）。
    # ⚠️ 字段名是 `declared_external`（`ToolSpec` 的字段），**不是** `external` ——
    # 后者是属性名，写进构造器会 `TypeError`（我实测踩过：30 个用例直接挂）。
    roles=_ROLES_WRITE,  # H 只读：不能拥有"跑实验并落库"的能力,
    # 键名从一个**真实跑通**的调用读出（`tests/test_tools_returns_declaration.py`
    # 用 `probes/honest.py` 探针脚本走的就是这一支）：观察到的 10 个键是
    # experiment_id/recorded/result/evidence_kind/negation_kind/exit_code/
    # reason/code_hash/runtime_sec/notes；后三个是**可选键**（取决于脚本与计时），
    # 所以键集合只写前 7 个。
    returns=(
            "{'experiment_id','recorded','result','evidence_kind','negation_kind','exit_code','reason'}"
            "（另有可选键 code_hash / runtime_sec / notes）"
            "；失败（未接线 / 参数与数据校验失败 / 脚本越界或超时 / IO 失败）：ok=False + "
            "kind(not_wired/validation_error/experiment_error/io_error) + data=None"
            "（失败分支不承诺上面那套键；meta 里留 script_path / claim_key）"
            ),
    tags=("experiment", "evidence"),
    external="exec",
)
def _verify_run_experiment(_need_store, _run_experiment_tool, claim, claim_key, script_path, params=None, method="numeric", for_question_id=None, timeout=600, run_name=None, imports=None):
    """verify.run_experiment 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_need_store, _run_experiment_tool）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _need_store("verify.run_experiment")
               or _run_experiment_tool(
                   claim=claim,
                   claim_key=claim_key,
                   script_path=script_path,
                   params=params,
                   method=method,
                   for_question_id=for_question_id,
                   timeout=timeout,
                   run_name=run_name,
                   imports=imports,
               )
    )

@tool(
    "verify.evidence_for",
    (
            "查一条命题（claim_key）或一个研究问题（for_question_id）已有的实验证据。"
            "两个参数都不给 ⇒ checked=False（**没查 ≠ 查了没有**）"
            ),
    {
           "type": "object",
           "properties": {
            "claim_key": {"type": "string"},
            "for_question_id": {"type": "string"},
           },
           "additionalProperties": False,
           },
    side_effect="read",
    roles=_ROLES,
    returns=(
            "{'checked','experiments','count','result_counts','negation_counts',"
            "'best_evidence_kind','proved','reason'}（FC-10：必须分档计数，不许只给一个布尔；"
            "三条返回路径的键集合**完全相同**，由 tests/test_tools_audit_fixes.py 逐字核对）"
            ),
    tags=("experiment", "evidence"),
)
def _verify_evidence_for(_need_store, _read_rows, store, claim_key=None, for_question_id=None):
    """verify.evidence_for 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_need_store, _read_rows, store）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _need_store("verify.evidence_for")
               or _read_rows(
                   "experiments", lambda: evidence_for(store, claim_key, for_question_id=for_question_id)
               )
    )

@tool(
    "verify.list_experiments",
    "按登记顺序列出实验记录（只读）：没有它就无法回答'这件事到底做过没有'",
    {
           "type": "object",
           "properties": {
            "claim_key": {"type": "string"},
            "limit": {"type": "integer", "minimum": 0},
           },
           "additionalProperties": False,
           },
    side_effect="read",
    roles=_ROLES,
    returns="{'checked','total','returned','truncated','experiments','reason'}",
    tags=("experiment",),
)
def _verify_list_experiments(_need_store, _read_rows, store, claim_key=None, limit=None):
    """verify.list_experiments 的工具体（`T-8`：从 `register` 里搬出来，判据一条没改）。

    注入值（_need_store, _read_rows, store）由装配期用 `partial` 绑定，
    所以模型看到的签名与搬移前逐字相同。
    """
    return (
    _need_store("verify.list_experiments")
               or _read_rows(
                   "experiments", lambda: list_experiments(store, claim_key=claim_key, limit=limit)
               )
    )

#: 装配清单（`T-8`）：`(工具体函数, 需要从装配期注入的名字)`。
#: 声明随函数走（`@tool` 写进 `fn.__tool_spec__`），这里只列装配要做的事。
_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (_verify_code_hash, ('_hash_of',)),
    (_verify_detect_verifier, ()),
    (_verify_check_formal, ('base',)),
    (_verify_run_experiment, ('_need_store', '_run_experiment_tool')),
    (_verify_evidence_for, ('_need_store', '_read_rows', 'store')),
    (_verify_list_experiments, ('_need_store', '_read_rows', 'store')),
)


def register(
    registry: ToolRegistry,
    *,
    store: Any = None,
    root: str | Path | None = None,
    **_: Any,
) -> None:
    """装配 E/F/G/H 可见的实验工具。

    ⚠️ ``store`` 为 None 时 `verify.run_experiment` / `evidence_for` /
    `list_experiments` **照样注册**，调用时返回 ``ok=False, kind="not_wired"``
    （FC-08：未接线必须显式失败，**不得静默降级为空**）。
    """
    base = _resolve_root(root)

    def _resolve(rel: str) -> Path:
        """把工具参数里的相对路径解析到工作区内，并**拒绝**越界。

        与 `Store.library_path` 同样的思路：路径穿越的最后一道闸必须在
        真正 open 文件之前，而不是靠调用方自觉。
        """
        p = (base / rel).resolve()
        try:
            p.relative_to(base.resolve())
        except ValueError:
            raise ParamError(f"路径越出工作区：{rel!r}") from None
        return p

    def _need_store(tool: str) -> ToolResult | None:
        """未接线时返回**结构化失败**（不是空数据）。"""
        if store is None:
            return fail(
                f"{tool} 未接线：装配时没有提供 store。"
                "**未接线不等于'没有任何实验结果'** —— 后者会让下游把'我们没查'读成'查了没有'",
                kind="not_wired",
            )
        return None

    def _hash_of(rel: str) -> ToolResult:
        """`verify.code_hash` 的实现。**任何一步失败都要变成结构化失败**。

        ⚠️ 这里此前是 `lambda path: ok({...: code_hash(_resolve(path))})`：
        `code_hash` 只保证"不是普通文件就抛 ParamError"，而 `open(p,"rb")` 的
        `OSError`/`PermissionError`（文件被占用、ACL 拒绝、路径是设备）会
        **逃出工具层**，被 `base.ToolRegistry.call` 的 `except Exception` 兜底
        折成没有类型信息的 `kind="unexpected"`。
        "读不了这个文件"与"工具内部出了 bug"必须能分开。

        这里刻意只写**符号名**、不写行号：行号在本仓库的并行开发下几十分钟就会漂
        （`.noai-paths` 的理由栏自己写了这条纪律），而符号名不会。
        `D1` 登记的正是这处：旧写法引的那个 `base.py` 行号在改动之后指向的是
        `ToolSpec.__post_init__` 的 `side_effect` 词表校验，差了六百多行 ——
        读者按它去看「unexpected 兜底」，看到的是另一段代码。

        ## `C1`：`returns=` 的失败词表必须与实测逐值相同

        声明写的是 ``kind(io_error/param_error)``，而 `code_hash` 与 `_resolve`
        抛的都是 `ParamError`（`ToolError` 的子类）⇒ 走到 `base.ToolRegistry.call`
        的 `except ToolError` 那一支，调用方实测拿到的是泛化的
        `kind="tool_error"`：**声明里那两个 kind 一个都不会出现**，而这两个分支
        恰恰是"最可能的失败"（路径越界、工作区内文件不存在）。所以这里把两类
        失败各自显式收成声明里的那一档（越界 ⇒ `param_error`，读不到文件 ⇒
        `io_error`），让**实现产出的就是声明承诺的那两个 kind**。
        交叉断言见 `tests/test_tools_audit_fixes.py` 的
        `test_code_hash_failure_kinds_match_its_declaration_every_branch`：
        它逐分支把实测 kind 与 `returns=` 抽出的词表对齐，任一侧漂了就红。
        """
        try:
            target = _resolve(rel)
        except ToolError as exc:
            # 路径守卫拒绝（越界）⇒ 声明里的 `param_error`：这是调用方给的参数不对，
            # 不是"文件读不了"。两者都不许逃成泛化的 `tool_error`（`C1`）。
            return fail(
                f"code_hash：{exc}",
                kind="param_error",
                path=rel,
            )
        try:
            return ok({"path": rel, "code_hash": code_hash(target)})
        except (ToolError, OSError) as exc:
            # `code_hash` 拒绝"不是普通文件"（文件不存在 / 是目录 / 是设备）或
            # `open()` 抛 OSError（被占用 / ACL 拒绝）⇒ 声明里的 `io_error`：
            # 这条路径上文件确实读不到。
            return fail(
                f"code_hash：读不了 {rel!r}（{type(exc).__name__}: {exc}）。"
                "注意哈希算不出来时**不能**把这条实验记成'可复现'——"
                "代码绑定是复现的前提，缺了它三个月后无法判断是结论错了还是脚本变了。",
                kind="io_error",
                path=rel,
            )

    def _run_experiment_tool(**kw: Any) -> ToolResult:
        """`verify.run_experiment` 的实现。把子进程/实验侧的异常变成结构化失败。

        ⚠️ 这条路径**从不**抛 `ToolError`：`AgentE.run_experiment` 会抛
        `ExperimentError`（`RuntimeError`，如脚本越界、超时、脚本自报非法等级）
        与 `Experiment.validate` 的 `ValueError`。它们此前直接逃出工具层，
        于是"脚本路径越界"和"工具层有 bug"在下游长得一模一样。
        """
        agent = _agent_for(store, root)
        try:
            return ok(
                agent.run_experiment(
                    kw["claim"],
                    kw["claim_key"],
                    kw["script_path"],
                    params=kw.get("params"),
                    method=kw.get("method", "numeric"),
                    for_question_id=kw.get("for_question_id"),
                    timeout=kw.get("timeout", 600),
                    # `P-8`：形式化路径的两个参数（声明名 / 要加载的库）。
                    # 计算类方法收到它们时 `AgentE.run_experiment` 会拒绝
                    # （不是静默忽略）—— 这里只是把通道接上。
                    # 本层的工具参数叫 run_name（撞名理由见该 ToolSpec 的属性注释），
                    # 但 `AgentE.run_experiment` 这一侧的关键字就是 name：
                    # 它是 agent 层的方法，不受 ToolRegistry.call 的形参影响。
                    # 名字翻译只发生在这三行里，别在别处再抄一遍。
                    name=kw.get("run_name"),
                    imports=kw.get("imports"),
                )
            )
        except ToolError:
            raise
        except ValueError as exc:
            return fail(
                f"run_experiment：参数/数据校验失败：{exc}（**没有落库**）",
                kind="validation_error",
                script_path=kw.get("script_path"),
            )
        except RuntimeError as exc:
            # ExperimentError 在这里：脚本越界 / 超时 / 实验本身出错。
            return fail(
                f"run_experiment：实验执行失败（{type(exc).__name__}: {exc}）⇒ **没做成**。"
                "这不是'实验做出来一个否定结论'，别把它读成 result=refutes。",
                kind="experiment_error",
                script_path=kw.get("script_path"),
                claim_key=kw.get("claim_key"),
            )
        except OSError as exc:
            return fail(
                f"run_experiment：IO 失败（{type(exc).__name__}: {exc}）⇒ **没做成**。",
                kind="io_error",
                script_path=kw.get("script_path"),
            )

    def _read_rows(table: str, build: Any) -> ToolResult:
        """只读表工具的公共守卫：`store.rows` 的 `StoreError` 不许逃出工具层。"""
        try:
            return ok(build())
        except StoreError as exc:
            return fail(
                f"读 {table} 表失败（{type(exc).__name__}: {exc}）⇒ **没查成**"
                "（不是'没有记录'）。请先修复/重建该表。",
                kind="store_error",
            )

    _bound: dict[str, Any] = {}
    _bound['_hash_of'] = _hash_of
    _bound['base'] = base
    _bound['_need_store'] = _need_store
    _bound['_run_experiment_tool'] = _run_experiment_tool
    _bound['_read_rows'] = _read_rows
    _bound['store'] = store
    for _fn, _deps in _TOOL_FUNCTIONS:
        registry.register(replace(_fn.__tool_spec__,
                                  handler=partial(_fn, *[_bound[k] for k in _deps])))





