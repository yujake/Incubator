/*
 * 本机读数（`draft/74 §3.5` 逐行落）。
 *
 * 输入：`api.getMachine()` → `MachineView`（B 线的 `readers.machine_face`：
 * `toolchain.toolchain_report()` 的键 + 设置三段）。SSE：`state`。
 *
 * 三态纪律在这页上有三条硬要求：
 *
 * 1. 检查器那一栏**必须显示"从哪一档找到的"**（`provers.sources`）——
 *    "配了但找不到"与"没配"是两种不同的处置，读数上必须分得开；`checked=false`
 *    ⇒ 整面 `unreadable`（探测没跑完，不是"一个都没找到"）；
 * 2. 模型那一栏**只显"配没配" + `base_url` / `name`；永远没有 key 的值**
 *    （`settings.model.api_key` 恒为 `***`，这是后端 `ModelSpec.redacted()` 给的）；
 * 3. `lean_ready` / `can_do_formal` 与 `provers.checked` 一样是**三态**：
 *    `null` 渲染成 `unknown`，不许折成 `false`。
 *
 * 一处**已经接上的缺口**：`draft/74 §3.5` 第 6 行要的"活着的 loop / 进程"过去那一栏
 * 渲染成 `not_applicable` 并写明。
 * 现在 `GET /api/live`（在飞面）给了它，卡片改成指路「在飞」页 ——
 * 说明文与读数说同一件事，别留一句"没有端点"的旧话在页面上。
 */
import { useState } from "preact/hooks";

import { api, postSettings, whyOf } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConfirmButton } from "../components/ConfirmButton";
import { Table, cell } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace } from "../live";
import type { ActionRow, SettingsReading } from "../types";

/** 网页操作历史一页多少行（AUDIT F11；与 `readers.ACTIONS_PAGE_DEFAULT` 同一个数）。 */
const ACTIONS_PAGE = 20;

/** 设置窗口里的每一格（`段.键` 形状逐字对应后端 `handle_settings` 读的表单键）。 */
const FIELDS: ReadonlyArray<{ key: string; hint: string }> = [
  { key: "toolchain.lean_bin", hint: "Lean 可执行文件所在目录（例：_env/lean470/.../bin）" },
  { key: "toolchain.mathlib_root", hint: "Mathlib 检出的根目录" },
  { key: "toolchain.coq_bin", hint: "Coq 落点（没有就留空）" },
  { key: "toolchain.isabelle_bin", hint: "Isabelle 落点（没有就留空）" },
  { key: "toolchain.lean_enabled", hint: "true / false —— 缺省 false（省钱档）" },
  { key: "model.vendor", hint: "厂商名（留空 = 按 base_url/内置缺省；例：deepseek）" },
  { key: "model.api_key", hint: "只写不读；写进去之后回执里恒为 ***（后端 ModelSpec.redacted() 给的）" },
  { key: "model.base_url", hint: "留空 = 用内置缺省端点（给了 vendor 就按它选）" },
  { key: "model.name", hint: "留空 = 用内置缺省模型" },
  { key: "model.reasoning_effort", hint: "off / low / high / max" },
  { key: "secretary.api_key", hint: "所有角色的秘书共用这一把 key（留空 = 秘书沿用它本体那一档）" },
  { key: "secretary.vendor", hint: "秘书那一档的厂商（留空 = 跟随 base_url）" },
  { key: "secretary.base_url", hint: "秘书那一档的端点" },
  { key: "secretary.name", hint: "秘书那一档的模型名" },
  { key: "secretary.reasoning_effort", hint: "off / low / high / max" },
  { key: "workspace.projects_dir", hint: "默认项目目录（留空 = 工作区自己那一个）" },
];

/** 十个角色（`capabilities.CAPABILITIES` 的十个键，含主控 M；`models.<角色>.<键>` 是三段形状）。
 *
 * 别写成 `schema.ROLES`：那里只有 A–H、V 九个 —— 主控 M 在权限面（`CAPABILITIES` /
 * `ALLOWED_EDGES`）里，而"每个角色用哪把 key"这件事对 M 同样成立。 */
const ROLES: readonly string[] = ["A", "B", "C", "D", "E", "F", "G", "H", "V", "M"];

/** 按角色那一档要填的键（业主：「允许不同角色智能体用不同模型厂商的不同 api key」）。
 *
 * 只给"换厂商 / 换端点 / 换模型 / 换 key"四格：逐角色配全套等于让人在十个角色上抄五遍
 * 同一份配置，而梯子（`models.<角色>` → `models.default` → `model`）本来就是为"只改一格"
 * 设计的 —— 留空即沿用下一档。
 */
const ROLE_FIELDS: ReadonlyArray<{ key: string; hint: string }> = [
  { key: "vendor", hint: "厂商名（例：deepseek；留空 = 沿用）" },
  { key: "api_key", hint: "这个角色自己的 key（只写不读；留空 = 沿用）" },
  { key: "base_url", hint: "端点（留空 = 沿用）" },
  { key: "name", hint: "模型名（留空 = 沿用）" },
];

/** 某一档的读数（`settings.models.<角色>`）—— **唯一一处**知道那一档形状的地方。 */
function roleCell(settings: SettingsReading, role: string): Record<string, unknown> {
  const models = (settings as unknown as Record<string, unknown>).models;
  if (models === undefined || models === null || typeof models !== "object") {
    return {};
  }
  const seg = (models as Record<string, unknown>)[role];
  if (seg === undefined || seg === null || typeof seg !== "object") {
    return {};
  }
  return seg as Record<string, unknown>;
}

/** 按角色那一档现读的值（`settings.models.<角色>.<键>`）。 */
function roleValue(settings: SettingsReading, role: string, key: string): string {
  if (key === "api_key") {
    // key 那一格不回填：读数里它是掩码（后端 MASKED_KEY），
    // 回填等于让人在输入框里看到一个假 key —— 动一下它就把掩码当 key 写回去。
    // 这一条与 `presetOf` 对 `model.api_key` 的例外是同一条纪律（key 只写不读）。
    return "";
  }
  const raw = roleCell(settings, role)[key];
  if (raw === undefined || raw === null) {
    return "";
  }
  return typeof raw === "string" ? raw : String(raw);
}

/** 从 `Record<string, unknown>` 里读一格：读不到 ⇒ `unknown`（不是空串、不是 false）。 */
function field(rec: Record<string, unknown>, key: string): string {
  return cell(rec[key]);
}

/** 设置文件里某一格现在的值（按 `段.键` 取；取不到 ⇒ 空串 = 盘上没设过）。
 *
 * 为什么要它（业主：「设置面板启动后应该同步设置文件里的参数，不然空空的就像
 * 啥都没设置过一样」）：这一格的读数后端早就在给（`GET /api/machine` 的 `settings` 三段），
 * 但输入框初值一直是空串 ⇒ 打开面板看到的永远是"没配"。
 *
 * ⚠️ 这里有一处**要命的**地方：不许走 `cell()`。`cell("")` 的口径是
 * `unknown`（那一套是给**读数表**用的），可这一格的返回值会直接进输入框的 `value` ——
 * 于是盘上没写的四格（`coq_bin` / `isabelle_bin` / `lean_enabled` / `projects_dir`）
 * 全被填上了字面量 `unknown`，用户一按「写这些设置」就把 `lean_enabled=unknown` 写进盘上：
 * `settings.lean_enabled()` 对词表外的值**抛错**，开关从此读不出来 ——
 * 业主报的「lean 开关网页上没法真的开关」正是这一条。
 * 所以这里读**原值**：缺席 ⇒ 空串（输入框空着、placeholder 说"盘上没设过"），
 * 「空串 = 这一格不动」这条口径也才成立。
 */
function currentOf(settings: SettingsReading, key: string): string {
  const parts = key.split(".");
  const part = parts[0] ?? "";
  const leaf = parts[1] ?? "";
  const seg = (settings as unknown as Record<string, Record<string, unknown>>)[part];
  if (seg === undefined || seg === null) {
    return "";
  }
  const raw = seg[leaf];
  if (raw === undefined || raw === null) {
    return "";
  }
  return typeof raw === "string" ? raw : String(raw);
}

/** 三态布尔：`null` / `undefined` ⇒ `unknown`（不折成 false）。 */
function triBool(value: unknown): string {
  return typeof value === "boolean" ? String(value) : "unknown";
}

/** 把"键值对"渲染成一张两列的表（设置三段与嵌套读数都用它）。
 *
 * `raw` 是原值：设置三段那一张要按"盘上写没写"读（空串 = 没写），不能在这里先被
 * `cell()` 折成 `unknown` —— 折过之后 `settingsCell()` 拿到的已经是词，回不去了。
 */
function pairs(rec: Record<string, unknown>): Array<{ k: string; v: string; raw: unknown }> {
  return Object.keys(rec)
    .sort()
    .map((k) => ({ k, v: field(rec, k), raw: rec[k] }));
}

/** 设置文件里的一格怎么读（R90）。
 *
 * 为什么不用 `cell()` 的默认读法：它的口径是"空串 ⇒ `unknown`"（三态纪律：读不到 ≠ 空），
 * 可这一格读到的是一个**盘上没写**的键 —— 文件已经读出来了（这一卡只有在
 * `settings_tri` 不是 unreadable 时才渲染）。把"没写"显成 `unknown`，用户看到的就是
 * 「lean_enabled unknown」，像是开关读不出来 —— 业主就是这么读的
 * （原话：「lean 开关网页上没法真的开关」）。
 */
function settingsCell(value: unknown): string {
  if (value === "" || value === null || value === undefined) {
    return "（盘上没写）";
  }
  return cell(value);
}

/** 形式化开关的来源（`GET /api/machine` 的 `lean_enabled_source`）。 */
const SWITCH_SOURCES: Record<string, string> = {
  env: "环境变量 AGENTFLOW_LEAN_ENABLED",
  settings: "设置文件 toolchain.lean_enabled",
  "": "缺省（设置文件里没写这一格）",
};

/** 初值：设置文件里的现值；`api_key` 那几格例外（读数是掩码，回填等于写回它）。 */
function presetOf(settings: SettingsReading, key: string): string {
  if (key === "model.api_key" || key.endsWith(".api_key")) {
    // `model.api_key` 之外，`secretary.api_key` 与每个角色那一档的
    // `api_key` 也是掩码（后端 MASKED_KEY）—— 三处都是同一份读数里的掩码，
    // 所以按后缀一律不回填。
    return "";
  }
  return currentOf(settings, key);
}

export function Machine() {
  const face = useFace(() => api.getMachine());
  const [values, setValues] = useState<Record<string, string>>({});
  const [writeResult, setWriteResult] = useState("");
  const [switchResult, setSwitchResult] = useState("");
  // 网页操作台账（AUDIT F11）：分页窗口是这一页的状态；`useFace` 只按"流里来过事件"
  // 重取，所以翻页之后要显式 `reload()`（与 Home 切会话同一条纪律）。
  const [actionsOffset, setActionsOffset] = useState(0);
  const actions = useFace(() => api.getActions({ limit: ACTIONS_PAGE, offset: actionsOffset }));

  if (face.data === null) {
    return (
      <Card
        title="本机"
        tone={face.problem === "" ? "plain" : "problem"}
        right={face.problem === "" ? null : <TriState tri="unreadable" reason={face.problem} label="本机面" />}
      >
        <span class="readings">{face.problem === "" ? "正在读盘……" : face.problem}</span>
      </Card>
    );
  }

  const m = face.data;
  const settings = m.settings;
  const provers = m.provers;
  const mathlib = m.mathlib;
  const serving = m.serving;
  /** 翻操作历史的一页（`offset` 由后端钳，`has_more` 说清还有没有下一页）。 */
  const html5ActionsGoto = (next: number): void => {
    setActionsOffset(Math.max(0, next));
    actions.reload();
  };
  /** 台账一行的参数摘要：只印键名与 sha 的一小截 —— 台账是摘要，不是正文备份。 */
  const paramKeys = (row: ActionRow): string => {
    const keys = Object.keys(row.params ?? {}).sort();
    return keys.length === 0 ? "（没有参数）" : keys.join(" / ");
  };
  // 开关的读数（三态）：`null` = 这一格没读成，不许折成"关"。
  const leanOn: boolean | null = typeof m.lean_enabled === "boolean" ? m.lean_enabled : null;
  // 「填了几格」这一格要问三处：impact 那一句、按钮的 `disabled`、note 那一句。
  // 改前每处各 `Object.values(...)` 一遍（连临时数组一起新建三遍）；这里算一次、三处共用。
  // `every((v) => v === "")` 与「填了值的格数为 0」是同一件事，所以按钮点不动的时机不变。
  const filledCount = Object.values(values).filter((one) => one !== "").length;
  const nothingFilled = filledCount === 0;

  /** 翻这个开关：写 `toolchain.lean_enabled` 那一格（`postSettings` 自带 `confirm=1`）。 */
  const flipLean = (want: boolean): void => {
    setSwitchResult("");
    postSettings({ "toolchain.lean_enabled": want ? "true" : "false" })
      .then((got) => {
        setSwitchResult(
          `${got.ok ? "成了" : "没成"}（tri=${got.tri}）：${got.reason}` +
            (got.ok ? " —— 新起的循环按新开关走；正在跑的那一趟按它自己那份跑。" : ""));
        face.reload();
      })
      .catch((exc: unknown) => {
        setSwitchResult(`写请求失败：${whyOf(exc)}`);
      });
  };

  return (
    <>
      <Card
        title="本机"
        subtitle={`整面 tri=${m.tri}`}
        tone={isUnreadable(m.tri) ? "problem" : "plain"}
        right={<TriState tri={m.tri} label="本机面" reason={m.reason} />}
      >
        <div class="readings">
          一处定义：工具链在哪、用哪个模型 —— 都来自机器级设置文件（
          <span class="mono">{settings.path === "" ? "unknown（落点没读到）" : settings.path}</span>
          ，在盘上 <span class="mono">{String(settings.exists)}</span>）。
        </div>
      </Card>

      <Card
        title="服务与工作区"
        subtitle="这一个服务在服务哪个工作区 —— 以及「换不了」这件事"
      >
        {/* AUDIT F8 的裁定：先取证页面上有没有切换入口 ⇒ 没有（ui/src 里没有任何
            切换工作区的按钮/下拉/链接，见 temp/webfix3 的报告）。裁定是"没有入口就
            不新增功能"，所以这里不摆控件，只把四件事实说清 —— 根是哪、谁钉的、
            换不了、真要换怎么换。`serving.switch_in_page=false` 是这条裁定的机器读数。 */}
        <div class="readings">
          工作区根 <span class="mono">{serving.root === "" ? "unknown（没读到）" : serving.root}</span>
        </div>
        <div class="readings">
          钉死{" "}
          <span class="mono">{String(serving.pinned)}</span> · 钉在{" "}
          <span class="mono">{serving.pinned_by}</span> · 页面里有切换入口{" "}
          <span class="mono">{String(serving.switch_in_page)}</span>
        </div>
        <div class="readings">{serving.switch_how}</div>
      </Card>

      <Card
        title="库表档案（已退役 / 未启用）"
        subtitle="这一档今天该怎么读 —— 不是「这个工作区里有什么」"
        right={<TriState tri={m.tables.checked ? "computed" : "unreadable"} label="库表档案" reason={m.tables.reason} />}
      >
        {/* DATAHYGIENE（2026-11-22）：两档登记面都住在 `schema`（单一落点），
            这一页只印它们的读数。为什么要上屏：
            · `eval_results` 已**退役**（全仓 0 个写点、51 个工作区全 0 行）——
              若把它当空表读，「没有评测」会被读成「评测 0 行」；
            · `reprocess_requests` **未启用**（写点/消费点/闸都在，只是从没有一条
              请求跑过）—— 收工门 `unfinished_request_rows`（上限 0）于是永远是 0，
              那是「这条队列没启用」，不是「闭环做完了」。
            两档颜色不同：退役 = 灰（不用管），未启用 = 黄（要人决定启用或整条退役）。 */}
        {m.tables.checked !== true ? (
          <div class="empty">
            {m.tables.reason === "" ? "库表档案没读成（不是「没有退役表」）" : m.tables.reason}
          </div>
        ) : (
          <>
            {m.tables.retired.length === 0 ? (
              <div class="readings">没有已退役的表。</div>
            ) : (
              <Table
                rows={m.tables.retired}
                empty="没有已退役的表。"
                columns={[
                  {
                    key: "name",
                    title: "表",
                    render: (r) => (
                      <span>
                        <span class="mono">{r.name}</span>{" "}
                        <Badge
                          kind="badge-na"
                          text="已退役"
                          title="写侧一律拒；历史工作区里的那份文件仍按 RETIRED_TABLES 认得出、行照读 —— 它不再产出，所以「0 行」不是「评测过 0 条」"
                        />
                      </span>
                    ),
                  },
                  { key: "file", title: "文件", render: (r) => <span class="mono">{r.file}</span> },
                  { key: "retired_at", title: "退役于" },
                  { key: "why", title: "为什么退", render: (r) => r.why },
                  { key: "how", title: "历史文件怎么读", render: (r) => r.how },
                ]}
              />
            )}
            {m.tables.not_enabled.length === 0 ? (
              <div class="readings">没有「已登记、未启用」的表。</div>
            ) : (
              <Table
                rows={m.tables.not_enabled}
                empty="没有「已登记、未启用」的表。"
                columns={[
                  {
                    key: "name",
                    title: "表",
                    render: (r) => (
                      <span>
                        <span class="mono">{r.name}</span>{" "}
                        <Badge
                          kind="badge-pending"
                          text="未启用（0 行 ≠ 做完了）"
                          title="写点与消费点都在、闸也在，只是从来没有一条请求真的跑过 ⇒ 这一档的 0 是「没启用」，不是「全做完了」"
                        />
                      </span>
                    ),
                  },
                  { key: "since", title: "判于" },
                  { key: "producers", title: "谁会写它", render: (r) => r.producers.join("、") },
                  { key: "consumers", title: "谁会读它", render: (r) => r.consumers.join("、") },
                  { key: "evidence", title: "证据" },
                  { key: "to_enable", title: "要启用怎么做" },
                ]}
              />
            )}
          </>
        )}
      </Card>

      <Card
        title="证明检查器"
        subtitle={`checked=${field(provers, "checked")}`}
        tone={provers.checked === false ? "problem" : "plain"}
      >
        <div class="readings">
          探测结论：<span class="mono">{field(provers, "reason")}</span> · 找到的：
          <span class="mono">{field(provers, "available_names")}</span>
        </div>
        <div class="readings">
          从哪一档找到的（这一栏是"配了找不到"与"没配"的分水岭）：
        </div>
        <Table
          rows={pairs(provers)}
          empty="探测读数里一格都没有（读到了空对象 —— 不是「没查成」）。"
          columns={[
            { key: "k", title: "键" },
            { key: "v", title: "值", render: (r) => <span class="mono">{r.v}</span> },
          ]}
        />
        <div class="readings">
 checked=false ⇒ 上面那些是"探测没跑完"：整面记 unreadable，
          不是"一个检查器都没找到"。
        </div>
      </Card>

      <Card
        title="Lean / Mathlib"
        subtitle={`lean_ready=${triBool(m.lean_ready)} · can_do_formal=${triBool(m.can_do_formal)}`}
      >
        {/* 开关那一行（R90）：业主「lean 开关网页上没法真的开关」。
            只有 `lean_ready`（这台机器装没装 Lean）与 `can_do_formal`（装了能不能用）
            时，页面上看不出 `lean_enabled`（用户设的开关）是开是关，改它只能去下面
            那个自由文本框里手打 true/false。两条事实必须同框（`readers.py` 里写过
            同一句：只看后者会把"关掉了"读成"没装"）。 */}
        <div class="readings">
          形式化开关{" "}
          <b>{leanOn === null ? "unknown（这一格没查成）" : leanOn ? "开" : "关"}</b>
          {" "}· 来源 <span class="mono">
            {SWITCH_SOURCES[m.lean_enabled_source] ?? m.lean_enabled_source}
          </span>
          {" "}· 当前模式 <span class="mono">{m.formal_mode === "" ? "unknown" : m.formal_mode}</span>
        </div>
        <div class="readings">
          关掉时全员不做形式化：证明核验走 V 的自然语言逐行走查（`verifications` 表签「成立」），
          检查器如实回 `lean_disabled` —— 它不是"这台机器上没有 Lean"，也不是"证明没过"。
          {/* 环境变量压着设置文件时，写文件不生效 —— 这件事必须在页面上说出来，
              否则用户改了设置文件、读数不动，只会以为"这个开关坏了"。 */}
          {m.lean_enabled_source === "env" ? (
            <span class="tri-reason">
              {" "}注意：现在压着它的是环境变量，改设置文件不会改变这一档 ——
              要么去掉那个环境变量再起服务，要么就按它跑。
            </span>
          ) : null}
        </div>
        <div class="readings">
          <ConfirmButton
            action="打开形式化"
            impact="会把设置文件 toolchain.lean_enabled 写成 true（下一趟起按它走）"
            onConfirm={() => {
              flipLean(true);
            }}
            disabled={leanOn !== false}
            note={
              leanOn === null
                ? "开关读数没查成 —— 先解决上面那条 reason，别蒙着写"
                : leanOn
                  ? "已经是开的"
                  : "写面没开（agentflow web --allow-writes）时后端回 403，回执如实显示"
            }
          />
        </div>
        <div class="readings">
          <ConfirmButton
            action="关闭形式化"
            impact="会把设置文件 toolchain.lean_enabled 写成 false（省钱档；证明核验改走 V 逐行走查）"
            onConfirm={() => {
              flipLean(false);
            }}
            disabled={leanOn !== true}
            note={
              leanOn === null
                ? "开关读数没查成 —— 先解决上面那条 reason，别蒙着写"
                : leanOn
                  ? "写面没开（agentflow web --allow-writes）时后端回 403，回执如实显示"
                  : "已经是关的（缺省就是关）"
            }
          />
        </div>
        {switchResult === "" ? null : <div class="readings">{switchResult}</div>}
        <div class="readings">
          lean 落点 <span class="mono">{m.lean_path === "" ? "unknown（没读到）" : m.lean_path}</span> ·
          版本 <span class="mono">{m.lean_version === "" ? "unknown（没读到）" : m.lean_version}</span>
        </div>
        <Table
          rows={pairs(mathlib)}
          empty="Mathlib 读数里一格都没有（读到了空对象）。"
          columns={[
            { key: "k", title: "键" },
            { key: "v", title: "值", render: (r) => <span class="mono">{r.v}</span> },
          ]}
        />
      </Card>

      <Card
        title="模型 key（只显配没配）"
        right={
          <Badge
            kind={settings.model.configured ? "badge-pass" : "badge-na"}
            text={settings.model.configured ? "配了" : "没配"}
          />
        }
      >
        <div class="readings">
          vendor <span class="mono">{settings.model.vendor === "" ? "unknown（没配）" : settings.model.vendor}</span> ·
          base_url <span class="mono">{settings.model.base_url === "" ? "unknown（没配）" : settings.model.base_url}</span> ·
          name <span class="mono">{settings.model.name === "" ? "unknown（没配）" : settings.model.name}</span> ·
          api_key <span class="mono">{settings.model.api_key === "" ? "（空）" : settings.model.api_key}</span>
        </div>
        <div class="readings">
          推理强度 <span class="mono">{settings.model.reasoning_effort}</span>（所有智能体都按这一档 thinking；
 settings.json 的 model.reasoning_effort 留空 = 内置默认 High）·
          key 来源 <span class="mono">{settings.model.key_source === ""
            ? "没取到（环境变量与设置文件都没有）"
            : settings.model.key_source}</span>
          {settings.model.key_source === "settings"
            ? "（从 config 取到的）"
            : settings.model.key_source === "env"
              ? "（一个环境变量盖住了 config —— 写错了也不会有人发现）"
              : ""}
        </div>
        <div class="readings">
 这一页永远不显示 key 的值：后端 ModelSpec.redacted() 给的就是 *
          （裁定 E1：key 只写不读）。这里是同一句话的机器读数。
        </div>
      </Card>

      <Card
        title="设置三段"
        subtitle={`落点在盘上：${String(settings.exists)}`}
        right={<TriState tri={m.settings_tri} label="设置" reason={m.settings_reason} />}
      >
        {isUnreadable(m.settings_tri) ? (
          <span class="empty">设置没查成（不是"什么都没配"）。</span>
        ) : (
          <>
            <div class="readings">
              盘上见过的顶层键：<span class="mono">{cell(settings.raw_keys)}</span>
            </div>
            <Table
              rows={[
                ...pairs(settings.toolchain).map((p) => ({ ...p, part: "toolchain" })),
                ...pairs(settings.model as unknown as Record<string, unknown>).map((p) => ({
                  ...p,
                  part: "model",
                })),
                ...pairs(settings.workspace).map((p) => ({ ...p, part: "workspace" })),
              ]}
              empty="三段里一个键都没有（读到了空对象）。"
              columns={[
                { key: "part", title: "段" },
                { key: "k", title: "键" },
                { key: "v", title: "值", render: (r) => <span class="mono">{settingsCell(r.raw)}</span> },
              ]}
            />
          </>
        )}
      </Card>

      <Card title="设置窗口（写设置）">
        <div class="readings">
 写的是机器级设置文件（上面那一格里的路径）。每一格的初值就是设置文件里的现值（打开即可见；model.api_key 只写不读，
 所以那一格不回填）。逐格改，清空某一格表示"这一格不动"
 （settings.write_settings 的口径是只写给了值的键）。model.api_key 落盘、
 回执里恒为 ***（key 只写不读）。lean_enabled 那一格是业主的
 省钱开关，取值只认 true / false；缺省是关。
        </div>
        <div class="readings">
          {FIELDS.map((field) => (
            <label class="opt" key={field.key}>
              <span class="mono">{field.key}</span>
              <input
                type={field.key === "model.api_key" ? "password" : "text"}
                placeholder={
                  field.key === "model.api_key"
                    ? field.hint
                    : currentOf(settings, field.key) === ""
                      ? `${field.hint}（盘上没设过）`
                      : field.hint
                }
                value={values[field.key] ?? presetOf(settings, field.key)}
                onInput={(ev) => {
                  const v = ev.currentTarget.value;
                  setValues((old) => ({ ...old, [field.key]: v }));
                }}
              />
            </label>
          ))}
        </div>
        {/* 按角色那一档（业主）：十个角色各四格，留空 = 沿用下一档。
            表单键是三段的 `models.<角色>.<键>` —— 后端 `handle_settings` 对
            `models` 那段再切一刀（`writes.py`），其余段仍是两段。 */}
        <div class="readings">
          按角色配模型（留空 = 沿用 `models.default` / `model` 那两档；号与键都由后端现取）
        </div>
        {ROLES.map((role) => {
          // 那一档"配了没配 + 从哪一档取到的"现算（读数由后端给：
          // `settings.models.<角色>.configured` / `.source`）。为什么要显出来：
          // 不显的话，只有点开每一格才知道哪个角色真的配了自己的 key ——
          // 而"哪个角色在用哪一把"正是这一页要回答的问题。
          // 名字叫 `slot` 而不是 `cell`：`cell` 是从
          // `components/Table` 导进来的那个读数渲染函数，这里一个局部变量把同名
          // 函数遮住 —— 今天没错用（对象不可调用，`tsc` 会红），但它是定时炸弹。
          const slot = roleCell(settings, role);
          const configured = slot["configured"] === true;
          const src = typeof slot["source"] === "string" ? (slot["source"] as string) : "";
          return (
            <div class="readings" key={role}>
              <span class="mono">models.{role}</span>
              <Badge
                kind={configured ? "badge-pass" : "badge-na"}
                text={configured ? `配了（${src === "" ? "来源没读到" : src}）` : "沿用下一档"}
              />
              {ROLE_FIELDS.map((rf) => {
                // 这一格盘上的现值要问两处（placeholder 里那句"盘上没设过"、输入框的初值）。
                // 改前每处各 roleValue 一次（每次都要 roleCell 一遍），这里算一次、两处共用 ——
                // 两处的判据都是"现值是不是空串"，所以渲染结果不变。
                const preset = roleValue(settings, role, rf.key);
                return (
                  <label class="opt" key={rf.key}>
                    <span class="mono">{rf.key}</span>
                    <input
                      type={rf.key === "api_key" ? "password" : "text"}
                      placeholder={
                        preset === ""
                          ? `${rf.hint}（盘上没设过）`
                          : rf.hint
                      }
                      value={values[`models.${role}.${rf.key}`] ?? preset}
                      onInput={(ev) => {
                        const v = ev.currentTarget.value;
                        setValues((old) => ({ ...old, [`models.${role}.${rf.key}`]: v }));
                      }}
                    />
                  </label>
                );
              })}
            </div>
          );
        })}
        <ConfirmButton
          action="写这些设置"
          impact={`会改盘上那份设置文件（${settings.path === "" ? "落点没读到" : settings.path}）：
            只写填了值的 ${filledCount} 格`}
          onConfirm={() => {
            postSettings(values)
              .then((got) => {
                setWriteResult(`${got.ok ? "成了" : "没成"}（tri=${got.tri}）：${got.reason}`);
                face.reload();
              })
              .catch((exc: unknown) => {
                setWriteResult(`写请求失败：${whyOf(exc)}`);
              });
          }}
          disabled={nothingFilled}
          note={
            nothingFilled
              ? "一格都没填 —— 按钮点不动（不假装成功）"
 : "写面没开（agentflow web --allow-writes）时后端会回 403，回执如实显示"
          }
        />
        {writeResult === "" ? null : <div class="readings">{writeResult}</div>}
      </Card>

      <Card
        title="网页操作历史"
        subtitle={
          actions.data === null
            ? "（还没读到）"
            : `${actions.data.path === "" ? "落点没读到" : actions.data.path} · 共 ${actions.data.total} 行 · 最新的在最上面`
        }
        tone={actions.data !== null && isUnreadable(actions.data.tri) ? "problem" : "plain"}
        right={
          actions.data === null ? (
            <TriState
              tri="unreadable"
              reason={actions.problem || "操作历史还没读到"}
              label="操作历史"
            />
          ) : (
            <TriState tri={actions.data.tri} label="操作历史" reason={actions.data.reason} />
          )
        }
      >
        {/* AUDIT F11：台账（`<工作区>/web-actions.jsonl`）从 W3 起就有人在写 ——
            每一笔网页写操作一行，被拒的尝试也留一行 —— 但全仓没有读侧，于是
            `writes.py` 与 `audit.py` 两处 docstring 都写着的「网页上那一栏操作历史」
            一直没有落地。这一栏读的是 `GET /api/actions`（只读；最新在前；分页）。 */}
        <div class="readings">
          读 <span class="mono">GET /api/actions</span> → 工作区根下那本
          <span class="mono">web-actions.jsonl</span>：每一条都记了
          <span class="mono">at</span> / <span class="mono">source</span> /
          <span class="mono">endpoint</span> / <span class="mono">result</span> /
          <span class="mono">http</span>，参数只留脱敏摘要（密钥一族的键值一律
          <span class="mono">***</span>）。
        </div>
        {actions.data === null ? (
          <span class="readings">{actions.problem === "" ? "正在读盘……" : actions.problem}</span>
        ) : (
          <>
            {isUnreadable(actions.data.tri) ? (
              <span class="empty">
                台账读不出来（不是「没有操作」）：{actions.data.reason}
              </span>
            ) : (
              <Table
                rows={actions.data.rows}
                empty="还没有一条网页操作（读到了 0 行：这个工作区一次都没从网页上动过手，合法初态）。"
                columns={[
                  { key: "at", title: "时间", render: (r) => <span class="mono">{cell(r.at)}</span> },
                  { key: "source", title: "谁（来源）", render: (r) => <span class="mono">{cell(r.source)}</span> },
                  { key: "endpoint", title: "动作（端点）", render: (r) => <span class="mono">{cell(r.endpoint)}</span> },
                  {
                    key: "http",
                    title: "HTTP",
                    render: (r) => (
                      <span class="mono">
                        {cell(r.http)}{" "}
                        <Badge
                          kind={r.ok ? "badge-pass" : "badge-fail"}
                          text={r.ok ? "成了" : "没成"}
                        />
                      </span>
                    ),
                  },
                  { key: "result", title: "结果", render: (r) => <span class="mono">{cell(r.result)}</span> },
                  {
                    key: "params",
                    title: "参数摘要（键名）",
                    render: (r) => <span class="mono">{paramKeys(r)}</span>,
                  },
                  { key: "tri", title: "三态", render: (r) => <span class="mono">{cell(r.tri)}</span> },
                ]}
              />
            )}
            {actions.data.problems.length === 0 ? null : (
              <div class="readings">
                台账里有读不出来的行（不是静默跳过）：
                {actions.data.problems.map((p, i) => (
                  <div class="mono tri-reason" key={i}>{p}</div>
                ))}
              </div>
            )}
            <div class="readings">
              <button
                class="btn"
                type="button"
                disabled={actionsOffset === 0}
                onClick={() => {
                  html5ActionsGoto(actionsOffset - ACTIONS_PAGE);
                }}
              >
                上一页
              </button>{" "}
              <button
                class="btn"
                type="button"
                disabled={!actions.data.has_more}
                onClick={() => {
                  html5ActionsGoto(actionsOffset + ACTIONS_PAGE);
                }}
              >
                下一页
              </button>{" "}
              <span class="mono">
                第 {actions.data.total === 0 ? 0 : actionsOffset + 1}–
                {actionsOffset + actions.data.rows.length} 行 / 共 {actions.data.total} 行
              </span>
              {" · "}
              <span class="tri-reason">
                `has_more={String(actions.data.has_more)}`（后端说的"还有没有下一页"，
                不是页面拿 offset 猜的）
              </span>
            </div>
          </>
        )}
      </Card>

      <Card
        title="停机 / 进程"
        right={<Badge kind="badge-pass" text="已接线：见「在飞」页" />}
      >
        <div class="readings">
          活着的循环与进程、停机开关与历史、状态报告、用量拆解、名册树 —— 都在
          <a class="nav-link" href="/live">
            「在飞」
          </a>
 那一页（GET /api/live / /api/status-reports / /api/usage / /api/roster 四条只读端点）。
        </div>
      </Card>
    </>
  );
}
