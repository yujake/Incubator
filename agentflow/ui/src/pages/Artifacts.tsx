/*
 * 产物（`draft/74 §3.4` 逐行落）。
 *
 * 输入：`api.getArtifacts()` → `ArtifactsView`（B 线的 `readers.artifacts_face`）；
 * 「台账」那一张卡读共享快照（`api.getState()` 与 `Home` / `Run` 同一份读数）。
 * SSE：`state`。
 *
 * 本页共九张卡，每张自己一个三态（栏数、标题都数 `ARTIFACT_CARDS` 那张表，不另写数字）：
 *
 * 1. 产物台账 `ledger`：路径 / `producer` / 一致性 / `exit_code` / `kind`，
 * 2. 交接手稿 `handoffs`：`body` 截断显示（后端 `webui/state.py` 的 `CLIP=400`
 *    是同一口径，这里跟它对齐，长文不许把表格撑爆）；
 * 3. 验收表的机器可判行 `checks`；
 * 4. 报告体例 `style.sections`；
 * 5. 六件产物 `products`（裁定 J2：真机无样本 ⇒ 夹具造，页面标明"夹具样本"）；
 * 6. 任务产物 `tasks`（`out/tasks/t-*.json` 与 `tasks` 台账行对应）；
 * 7. 文献库 `library` —— 读 `GET /api/literature`
 *    （`api.getLibrary()` → `LibraryView`）：只算「正式入库」的那一档，每条带
 *    题名 / 作者 / DOI 或去重键 / 命中校验 / 认领与挖掘尝试 / 下载落地（与盘上的
 *    文件核过：在 / 不在 / 读不到）/ 被哪条命题、哪一份证明（`#pN`）用过。三种空态
 *    分三档显示：这条端点读不到、台账里 0 条、台账读不到 —— 它们不许被画成同一个样子；
 * 8. 台账对账 `ledger_verify`（台账钉住的那一份 vs 盘上现在这一份）；
 * 9. 实验产物的落点 `experiment_spots` 与 `code_exp` —— 第九张是它：
 *    `code/exp/` 下的脚本与 `out/experiments/<号>/{design,exhaustion}.md`；
 *    证据链那张实验表的「报告」列也链到这张卡。
 *
 * 另有一张「台账（第二个独立读数）」卡不在那张表里：它读的是共享快照
 * （`useLive().snapshot.ledger`，与首页 / 一趟详情的「台账」卡同一份），不是这一面的
 * 栏 —— 把它数进"栏数"会让"这一面有几栏"与"这一面读了几份盘"混成一件事。
 *
 * 数法（免得"九"与屏幕上数卡片对不上）：本页同时渲染十一张卡 —— 页头那张「产物」卡
 * ＋ 这一面的九栏 ＋ 一张台账镜子卡。源码里 `<Card` 出现十三处，是因为页头卡有一个
 * 「还没读到」的副本、「六件产物」按 `art.run_dir` 分两支（两支是同一栏）。
 *
 * ## 三条显示口径
 *
 * - sha 原文一律不上屏：台账那一格说"一致 / 不一致 / unknown（没得比）"，副标题写清
 *   比的是与哪一份；半截哈希（前 8 位）也不许出现 —— 它既不能核也不能读；
 * - `code/exp/` 与 `out/experiments/<号>/{design,exhaustion}.md` 的落点单列一栏
 *   （实验代码与两份读得懂的说明落在哪，盘上现在有没有）；
 * - 台账用 `upserts` / `commit_markers` 两格（与 `Home` / `Run` 同一句文案），
 *   不报"事件 N 条"那种总行数。
 */
import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";

import { api } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { Consistency } from "../components/Consistency";
import { PagedTable } from "../components/PagedTable";
import { blank, cell, plain } from "../components/Table";
import { formatUsd } from "../components/Money";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace, useLive } from "../live";
import type {
  AcceptanceCheck,
  ArtifactRow,
  ArtifactsView,
  LibrarySeed,
  LibraryView,
  LibraryWork,
} from "../types";

/** 这一栏**真实**有多少行（AUDIT F12 的分页读数：`rows_total[栏]`；全量档与数组等长）。 */
function totalOf(art: ArtifactsView, key: string, shown: number): number {
  const raw = art.rows_total[key];
  return typeof raw === "number" ? raw : shown;
}

/** 这一栏被首屏摘要切过时那一句（与 `Evidence.tsx` 同一口径，两页各留一份实现
 *  是因为它们读的是两个不同的视图类型；句子里的数字必须来自后端 `rows_total`）。 */
function rowsNote(art: ArtifactsView, key: string, shown: number): string {
  const total = totalOf(art, key, shown);
  if (total <= shown) {
    return "";
  }
  return `这一栏共 ${total} 行，首屏只画了前 ${shown} 行（摘要档）—— 点顶上那张「产物」卡里的「取全部」拉整表。`;
}

/** `rowsNote` 那一句的渲染（空串 ⇒ 什么都不画）。 */
function PartialRows(props: { note: string }) {
  return props.note === "" ? null : <div class="readings tri-reason">{props.note}</div>;
}

/** 长文截断（与后端 `webui/state.py` 的 `CLIP` 同一口径：两头留、中间省）。 */
const CLIP = 400;

/** 一条验收行的阈值读数（E4）：`min`（下限）/ `max`（上限）二选一，`na` 行两者都无。
 *
 * 为什么不能直接 `String(r.min)`：真机 99 份 `ACCEPTANCE-CHECKS.json` 里有 60 份含
 * `max`-only 行（`{"id": "C3", "kind": "unfinished_request_rows", "max": 0}` ——
 * 「剩下多少没做」那一档的达标线是 0，用 `min` 表达不出来），那一格读出来是
 * `undefined`，`String(undefined)` 会把字面量 `undefined` 印上屏。三档分开：
 *
 * - 这一行没声明这个方向的阈值 ⇒ `—`（不是 0、也不是 unknown：它压根没有这条线）；
 * - `na` 行 ⇒ `不适用`（`closing.py` 的第三档阈值，不是通过也不是失败）；
 * - 真给了数字 ⇒ 数字。
 */
function bound(row: AcceptanceCheck, which: "min" | "max"): string {
  if (row.na === true) {
    return "不适用";
  }
  const value = which === "min" ? row.min : row.max;
  return typeof value === "number" ? String(value) : "—";
}

/** 判据类型那一格：读数**正名**在前，盘上写下的旧名（若有）并列在后。
 *
 * B3（2026-11-22）：交接手稿那一档的读数键正名是 `handoff_rows`；老表的
 * `manuscript_rows` 是它的旧名（deprecated，同值）。两个名字的映射只有一处真身
 * （`closing.LEG_KIND_RENAMES`），后端已经算在 `kind_reading` / `kind_deprecated` 里，
 * 页面不另写一份 —— 否则改一次名要改两处，迟早一处漂。
 */
function kindText(row: AcceptanceCheck): ComponentChildren {
  const word = row.kind_reading === undefined || row.kind_reading === ""
    ? row.kind
    : row.kind_reading;
  if (row.kind_deprecated === undefined || row.kind_deprecated === "") {
    return <span class="mono">{word}</span>;
  }
  return (
    <span class="mono" title={`${row.kind_deprecated}（盘上写的是旧名：${row.kind}）`}>
      {word}（旧名 {row.kind}）
    </span>
  );
}

/** 验收表在盘上的位置（`ArtifactsView.checks_path`：后端从
 *  `closing.ACCEPTANCE_TARGETS_NAME` 读、印工作区相对路径）。
 *
 * 为什么页面不写死字面量：这一份 2026-11-22 刚从 `out/paper/` 挪到 `out/package/` ——
 * 页面抄一份就会在改名当天变成假话。空串只在后端没读到位置时出现（那是"没读到"，
 * 不是"没有这份表"），所以给它一句能读的话，而不是留空。 */
function checksPath(art: ArtifactsView): string {
  return art.checks_path === "" ? "（验收表落点没读到）" : art.checks_path;
}

/** 台账那一行的类别（B2d，2026-11-22）：`kind` 是盘上原值，`kind_state` 是读侧三态。
 *
 * 三档的处置刻意不同，颜色也跟着不同：
 * - `canonical`：取值在 `ARTIFACT_KINDS` 词表里 —— 只印类别，不加徽标；
 * - `legacy`：词表生效前落的老行（**照读**，不是缺陷）⇒ 灰色虚线徽标，没有待办；
 * - `unknown`：词表生效后新写、行上带 `kind_unknown=true` ⇒ 红色徽标：写侧用了
 *   词表外的取值，是要人看的那一档。
 * 判据只有 `artifacts.kind_state` 一处（后端算好放进 `kind_state`），页面不按取值猜。
 */
function kindBadge(row: ArtifactRow): ComponentChildren {
  const word = row.kind === "" ? "(空)" : row.kind;
  if (row.kind_state === "unknown") {
    return (
      <Badge
        kind="badge-fail"
        text={`${word}（词表外）`}
        title="词表（ARTIFACT_KINDS）之外的类别，且这一行带 kind_unknown 标记 ⇒ 词表生效后的新写用了自造取值：台账照写，但这一档要人看"
      />
    );
  }
  if (row.kind_state === "legacy") {
    return (
      <Badge
        kind="badge-na"
        text={`${word}（历史行）`}
        title="词表生效前落的老行（行上没有 kind_unknown 这一格）⇒ 照读，不是缺陷、没有待办"
      />
    );
  }
  return <span class="mono">{word}</span>;
}

/** 台账类别三态的那一句（B2d）：三个数分别来自后端现算的 `kind_states`。
 *
 * 为什么要单列一句：三态徽标只在行上、一屏几十行里看不到"这张表里有几行是词表外
 * 的新写"；而"词表外新写"是唯一要人动的那一档（历史行照读、不欠任何动作）。
 */
function kindStatesNote(art: ArtifactsView): ComponentChildren {
  const canonical = art.kind_states["canonical"] ?? 0;
  const legacy = art.kind_states["legacy"] ?? 0;
  const unknown = art.kind_states["unknown"] ?? 0;
  const odd = Object.entries(art.unknown_kinds)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([kind, n]) => `${kind === "" ? "(空)" : kind}×${n}`)
    .join("、");
  return (
    <div class="readings">
      类别三态：词表内 <span class="mono">{canonical}</span> 行 · 历史行（词表生效前，
      照读）<span class="mono">{legacy}</span> 行 · 词表外新写{" "}
      <span class="mono">{unknown}</span> 行
      {unknown > 0 ? "（要人看：写侧用了 ARTIFACT_KINDS 之外的取值）" : ""}
      {art.kind_flag_mismatch > 0 ? (
        <>
          {" "}
          · 标记与取值不一致{" "}
          <span class="mono">{art.kind_flag_mismatch}</span> 行（写了 kind_unknown=false
          却不在词表里）
        </>
      ) : null}
      {odd === "" ? null : (
        <>
          {" "}
          · 词表外的取值：<span class="mono">{odd}</span>
        </>
      )}
    </div>
  );
}

/** 种子那一行（SEEDFIX，2026-11-22）：种子投 `reference/`，`library/` 只放已登记的。
 *
 * 三个数各自三态，绝不折平：
 * - `count` 是 `reference/` 里那批种子的份数（0 = 还没投过，合法初态）；
 * - `library_unregistered` 是 `library/` 里**没有** `literature` 行引用的文件：
 *   非空 ⇒ 书架结构异常（黄色，要人看）；`[]` ⇒ 干净；`null` ⇒ 台账读不出来（没查成）。
 */
function seedLine(seed: LibrarySeed): ComponentChildren {
  return (
    <div class="readings">
      种子：<span class="mono">{seed.destination}</span> 里{" "}
      <span class="mono">{seed.count}</span> 份
      {seed.count > 0 ? `（${seed.bytes} 字节）` : "（还没投过种子）"}
      {seed.landed ? "" : " · 标记文件不在盘上"} · 已登记书架{" "}
      <span class="mono">library/</span>：{" "}
      {seed.library_unregistered === null ? (
        <Badge kind="badge-unknown" text="未登记文件：没查成（不是「干净」）" />
      ) : seed.library_unregistered.length === 0 ? (
        <Badge kind="badge-pass" text="没有未登记的文件" />
      ) : (
        <Badge
          kind="badge-pending"
          text={`${seed.library_unregistered.length} 份未登记`}
          title={`library/ 里这些文件没有任何 literature 行引用：${seed.library_unregistered.join("、")}`}
        />
      )}
      {seed.legacy_root_marker ? " · 根上还有改前的 SEED-README.md" : ""}
      {seed.reason === "" ? "" : ` · ${seed.reason}`}
    </div>
  );
}

/** 这一面读数的九张卡：栏序 = `draft/74 §3.4` 那七栏 + 后来补的两栏，标题的唯一来源。
 *
 * 标题与数字都数这张表（`CARD_COUNT`）：加一张卡忘了登记、或文件头那个中文数字忘了
 * 改，`tests/test_webui_readings_format.py` 的判据⑩ 会红 —— 手写一个数字就会漂，
 * 而文件头与屏幕各说各的没有任何地方会报错。
 *
 * 第九张是「实验产物的落点」；第八张是「台账对账」。
 */
export const ARTIFACT_CARDS = {
  ledger: "产物台账",
  handoffs: "交接手稿 / 账本",
  checks: "验收表的机器可判行",
  style: "报告体例兑现",
  products: "六件产物",
  tasks: "任务产物",
  library: "文献库（只算正式入库）",
  verify: "台账对账（台账钉住的那一份 vs 盘上现在这一份）",
  spots: "实验产物的落点",
} as const;

/** 这一面读数卡的张数（文件头那句与页面副标题都数它，不另写一个数）。 */
const CARD_COUNT = Object.keys(ARTIFACT_CARDS).length;

function clip(text: string): string {
  if (text.length <= CLIP) {
    return text === "" ? "unknown" : text;
  }
  return `${text.slice(0, CLIP - 40)} …（共 ${text.length} 字，已截断）`;
}

/** 台账那一行在盘上还对得上吗（`artifacts.STATUSES` 的五档词，一个都不折成布尔）。 */
function verifyBadge(status: string): ComponentChildren {
  if (status === "ok") {
    return <Badge kind="badge-pass" text="对得上" />;
  }
  if (status === "missing") {
    return <Badge kind="badge-na" text="文件不在盘上" />;
  }
  if (status === "changed") {
    return <Badge kind="badge-fail" text="盘上已改版" />;
  }
  if (status === "not_a_file") {
    return <Badge kind="badge-fail" text="台账指的是一个目录" />;
  }
  if (status === "unreadable") {
    return <Badge kind="badge-unknown" text="读不出来（没查成）" />;
  }
  return <Badge kind="badge-unknown" text={status === "" ? "unknown" : status} />;
}

/** 下载落地那一格的三档（后端 `download_state`：present / absent / unreadable）。
 *
 * 为什么不是一个勾：`download.status` 是写侧的自报（"那次下载当时成功了"），而文件
 * 可以被删、被换、被挪。后端去盘上核过一次，这一格印的就是那次核对的结论 ——
 * "读不到"与"不在"也要分得开（前者是没核成，后者是核过了、确实没有）。
 */
function downloadBadge(work: LibraryWork): ComponentChildren {
  if (work.download_state === "present") {
    return (
      <Badge
        kind="badge-pass"
        text={work.download_bytes === null ? "在" : `在（${work.download_bytes} 字节）`}
      />
    );
  }
  if (work.download_state === "absent") {
    return <Badge kind="badge-na" text="不在" />;
  }
  return <Badge kind="badge-unknown" text="读不到" />;
}

/** 「被谁用过」那一格：命题号 + 证明号（`stmt_id` 空的是非命题使用点，照原样印）。
 *
 * 用法那一路没查成时印 `unknown`，绝不印"没有" —— 那是把"没查"折成"没有"。
 */
function useText(work: LibraryWork, usesTri: string): string {
  if (work.uses.length === 0) {
    return usesTri === "computed" ? "没有（0 条命题或证明用它）" : "unknown（用法读数没查成）";
  }
  return work.uses
    .map((use) => (use.stmt_id === "" ? use.used_by : `${use.stmt_id}#p${use.proof_no}`))
    .join("、");
}

/**
 * 文献库那一格：三种空态必须分三档。
 *
 * 1. `view === null` ⇒ 这条端点根本没读到（没有 `/api/literature`、或请求失败）；
 * 2. `state === "unknown"` ⇒ 端点在，但台账没读成（表不在盘上 / 坏 JSON）；
 * 3. `rows_total === 0` ⇒ 台账读到了，里面 0 条（合法初态）。
 *
 * 三档画成同一个"什么都没有"，读的人就分不出"没接"与"没写"与"没有"了。
 */
function libraryBody(view: LibraryView | null, problem: string): ComponentChildren {
  if (view === null) {
    return (
      <div class="empty">
        {problem === ""
          ? "正在读盘……"
          : `这条端点读不到（/api/literature 不在，或请求失败）：${problem} —— 这是「没有这个端点」那一档，不是「台账里 0 条」`}
      </div>
    );
  }
  const data = view.data;
  if (view.checked !== true || view.state === "unknown") {
    return (
      <div class="empty">
        这一面读不到：{view.reason === "" ? "没给理由" : view.reason} ——
        「读不到」不等于「一篇都没有」。
      </div>
    );
  }
  if ((data.rows_total ?? 0) === 0) {
    return <div class="empty">台账里 0 条（已读出，合法初态：还没有一篇文献入库）。</div>;
  }
  if ((data.count ?? 0) === 0) {
    return (
      <div class="empty">
        台账里 {data.rows_total} 条，但没有一条判得出「正式入库」（待入库与判不出的都不显示；
        判不出的在下面留了痕）。
      </div>
    );
  }
  return (
    <>
      <PagedTable
        rows={data.works}
        empty="没有入库文献。"
        columns={[
          { key: "lit_id", title: "编号" },
          { key: "title", title: "题名", render: (w) => clip(w.title) },
          {
            key: "authors",
            title: "作者",
            render: (w) => (w.authors.length === 0 ? "unknown" : w.authors.join("、")),
          },
          {
            key: "doi",
            title: "DOI / 去重键",
            render: (w) => {
              const key =
                w.doi !== "" ? w.doi : w.dedup_key !== "" ? `去重键 ${w.dedup_key}` : "unknown";
              return w.pages === "" ? key : `${key} · pp. ${w.pages}`;
            },
          },
          { key: "matched", title: "命中校验", render: (w) => cell(w.matched) },
          {
            key: "claimed_by",
            title: "认领者",
            render: (w) => (w.claimed_by === "" ? "未认领" : w.claimed_by),
          },
          {
            key: "mine_attempts",
            title: "挖掘尝试",
            // 两处都走取值器：`String(w.mine_attempts)` 与模板里的
            // `${w.mine_attempts}` 都是同一件事 —— 这一格没有时印字面量 `undefined`。
            render: (w) =>
              w.last_mine_error === ""
                ? cell(w.mine_attempts)
                : `${cell(w.mine_attempts)} · 上次：${clip(w.last_mine_error)}`,
          },
          {
            key: "download_state",
            title: "下载落地",
            render: (w) => (
              <span>
                {downloadBadge(w)}
                {w.download_reason === "" ? null : (
                  <div class="readings">{w.download_reason}</div>
                )}
              </span>
            ),
          },
          { key: "uses", title: "被谁用过", render: (w) => useText(w, data.uses_tri) },
        ]}
      />
      {data.uses_tri === "computed" ? null : (
        <div class="readings">「被谁用过」那一栏没查成：{data.uses_reason}</div>
      )}
      {view.problems.length === 0 ? null : (
        <div class="readings">
          {view.problems.map((p) => (
            <div key={p.code}>
              <span class="mono">{p.code}</span>：{p.detail}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export function Artifacts() {
  // 首屏摘要 vs 整表（AUDIT F12）：`false` ⇒ `?summary=1`（每栏前
  // `readers.SUMMARY_ROWS` 行，字段 compact）；`true` ⇒ `?full=1`（全量行 + 全字段）。
  // 三态一个都没删；省了/截了哪些字段由后端 `rows_omitted` / `rows_clipped` 点名。
  const [full, setFull] = useState(false);
  const face = useFace(() => api.getArtifacts(full ? { full: true } : { summary: true }));
  // 文献库是第二条端点：它与产物面是两份盘上的事实，各有各的三态 ——
  // 把它塞进 `ArtifactsView` 会让"产物面读不成"连带把文献库也画成没查成。
  const library = useFace(() => api.getLibrary());
  const live = useLive();
  const ledger = live.snapshot === null ? null : live.snapshot.ledger;

  if (face.data === null) {
    return (
      <Card
        title="产物"
        tone={face.problem === "" ? "plain" : "problem"}
        right={face.problem === "" ? null : <TriState tri="unreadable" reason={face.problem} label="产物面" />}
      >
        <span class="readings">{face.problem === "" ? "正在读盘……" : face.problem}</span>
      </Card>
    );
  }

  const art = face.data;
  // 哪些栏被首屏摘要切过（按真实总行数与数组长度比，不按 `rows_mode` 猜）。
  const cutColumns: string[] = [
    ["台账", art.ledger.length, totalOf(art, "ledger", art.ledger.length)],
    ["对账", art.ledger_verify.length, totalOf(art, "ledger_verify", art.ledger_verify.length)],
    ["交接", art.handoffs.length, totalOf(art, "handoffs", art.handoffs.length)],
    ["验收", art.checks.length, totalOf(art, "checks", art.checks.length)],
    ["产物", art.products.length, totalOf(art, "products", art.products.length)],
    ["落点", art.experiment_spots.length,
     totalOf(art, "experiment_spots", art.experiment_spots.length)],
    ["任务", art.tasks.length, totalOf(art, "tasks", art.tasks.length)],
  ]
    .filter(([, shown, total]) => Number(total) > Number(shown))
    .map(([name]) => String(name));

  return (
    <>
      <Card
        title="产物"
        subtitle={`${CARD_COUNT} 张卡 · 整面 tri=${art.tri}`}
        tone={isUnreadable(art.tri) ? "problem" : "plain"}
        right={<TriState tri={art.tri} label="产物面" reason={art.reason} />}
      >
        <div class="readings">
          台账 <span class="mono">ARTIFACTS.jsonl</span> · 交接{" "}
          <span class="mono">manuscripts/handoffs.jsonl</span> · 验收表{" "}
          <span class="mono">{checksPath(art)}</span> · 体例{" "}
          <span class="mono">out/report/REPORT-STYLE.json</span> · 秘书{" "}
          <span class="mono">out/secretary/</span> 下的 <span class="mono">*.jsonl</span>
          {" "}· 实验落点 <span class="mono">out/experiments/&lt;号&gt;/</span> 与{" "}
          <span class="mono">code/exp/</span>
        </div>
        <div class="readings">
          张数数的是 <span class="mono">ARTIFACT_CARDS</span> 那张表（标题与数字同一来源）：
          <span class="mono">draft/74 §3.4</span> 原有的那些栏目 + 第八张「台账对账」、
          第九张「实验产物的落点」。另有一张「台账（第二个独立读数）」读的是共享快照
          （与首页同一份），不是这一面的栏。
        </div>
        {/* 首屏摘要（AUDIT F12）：这一格说清"这一份是全量还是摘要、一共多少行" ——
            否则"任务产物 40 行"会把真实总数读没。四格读数全来自后端的
            `rows_mode` / `rows_limit` / `rows_offset` / `rows_total`。 */}
        <div class="readings">
          读数档 <span class="mono">{art.rows_mode}</span>（每栏 {art.rows_offset} 起，最多{" "}
          <span class="mono">{art.rows_limit === 0 ? "全部" : art.rows_limit}</span> 行）·{" "}
          字段档 <span class="mono">{art.rows_fields}</span>
          {art.rows_fields === "compact"
            ? "（长字段省掉/截断：省了哪些见 rows_omitted，截了哪些见 rows_clipped；要全文点「取全部」）"
            : "（全字段）"} ·{" "}
          {cutColumns.length === 0 ? (
            <span>这一份是全量：每一栏给全了。</span>
          ) : (
            <span>
              首屏摘要切过这几栏：<span class="mono">{cutColumns.join(" / ")}</span>
              （每栏下面的「共 N 行」是真实总数）
            </span>
          )}{" "}
          {full ? (
            <button
              class="btn"
              type="button"
              onClick={() => {
                setFull(false);
                face.reload();
              }}
            >
              回到首屏摘要（快）
            </button>
          ) : (
            <button
              class="btn"
              type="button"
              onClick={() => {
                setFull(true);
                face.reload();
              }}
            >
              取全部（整表，慢）
            </button>
          )}
        </div>
      </Card>

      <Card
        title={ARTIFACT_CARDS.ledger}
        subtitle={`${art.ledger.length} / 共 ${totalOf(art, "ledger", art.ledger.length)} 行 · 一致性比的是与「台账对账」那一栏同一路径的核对行`}
        right={<TriState tri={art.ledger_tri} label="ledger" />}
      >
        <PartialRows note={rowsNote(art, "ledger", art.ledger.length)} />
        {isUnreadable(art.ledger_tri) ? (
          <span class="empty">这一栏没查成（不是"0 行"）。</span>
        ) : art.ledger_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <>
            <PagedTable
              rows={art.ledger}
              empty="暂无产物台账行。"
              columns={[
                { key: "path", title: "路径" },
                { key: "producer", title: "谁产出的" },
                // 类别那一格带三态徽标（`kind_state`：canonical / legacy / unknown）——
                // 后端判、页面印；判据见 `artifacts.kind_state`，这里不按取值猜。
                { key: "kind", title: "类别", render: (r) => kindBadge(r) },
                {
                  // 这一格取同一路径的核对行读数，
                  // 没有对应核对行 ⇒ unknown（没得比），不是"不一致"。
                  key: "sha_consistency",
                  title: "与盘上这一份",
                  render: (r) => (
                    <Consistency
                      value={r.sha_consistency}
                      note="台账钉住的那一份与盘上现在这一份（这一路径没有核对行 ⇒ 没得比）"
                    />
                  ),
                },
                {
                  key: "bytes",
                  title: "字节",
                  // 走取值器：有值时逐字不变（`cell(number)` 就是 `String(number)`），
                  // 这一格没有时才从字面量 `undefined` 变成 `unknown`。
                  render: (r) => cell(r.bytes),
                },
                {
                  // 归属三档（`by_task_id_tri`）：
                  // - `row`：台账行自己记了 task_id（写入时落下的，最硬）；
                  // - `event`：行上没记，按路径反查事件反查到；
                  // - `not_recorded`：这一档写入方没记归属（框架的笔记 / 手稿骨架那几行）。
                  // 这一档写「这一档没有归属」，不写「缺任务号」——后者听起来像该有却没有。
                  key: "task_id",
                  title: "任务",
                  render: (r) =>
                    r.by_task_id_tri === "not_recorded" ? (
                      <span class="tri-reason">这一档没有归属</span>
                    ) : (
                      cell(r.by_task_id === "" ? r.task_id : r.by_task_id)
                    ),
                },
                { key: "at", title: "登记时间", render: (r) => cell(r.at) },
                // 这里不列「退出码」：台账的格式里有 `exit_code`
                // 这一栏（`artifacts.FIELDS`），但真机上登记的都是 `out/tasks/` 下那些
                // "任务结果文件"——那种东西没有退出码，整列恒 `unknown`
                // （本机实测：t1-review-2 的 6 行全是）。退出码真正的落点是「证据链 →
                // 实验」那一张表（`experiments.exit_code`，那里是真读数）。
              ]}
            />
            {kindStatesNote(art)}
          </>
        )}
      </Card>

      <Card
        title={ARTIFACT_CARDS.verify}
        subtitle={`${art.ledger_verify.length} / 共 ${totalOf(art, "ledger_verify", art.ledger_verify.length)} 行 · sha 原文不上屏，只报一致 / 不一致 / unknown`}
        right={<TriState tri={art.ledger_verify_tri} label="verify_entries" />}
      >
        <PartialRows note={rowsNote(art, "ledger_verify", art.ledger_verify.length)} />
        {isUnreadable(art.ledger_verify_tri) ? (
          <span class="empty">这一栏没查成（不是"全部对得上"）。</span>
        ) : art.ledger_verify_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <PagedTable
            rows={art.ledger_verify}
            empty="没有可对账的台账行（台账是空的）。"
            columns={[
              { key: "path", title: "路径" },
              {
                // 这一格只印"一致 / 不一致 / unknown（没得比）"—— 两份都拿不到时是
                // 没得比，不是"不一致"（那一档由下面 `status` 的五档自己说清）。
                key: "sha_consistency",
                title: "一致吗",
                render: (r) => (
                  <Consistency
                    value={r.sha_consistency}
                    note="台账钉住的那一份与盘上现在这一份（盘上这一份取不到哈希、或台账指的是目录 ⇒ 没得比）"
                  />
                ),
              },
              { key: "status", title: "核对结论", render: (r) => verifyBadge(r.status) },
              { key: "producer", title: "谁产出的" },
            ]}
          />
        )}
      </Card>

      <Card title="台账（第二个独立读数）" subtitle="写入笔数与 commit 标记分开摆">
        {ledger === null ? (
          <TriState tri="unreadable" label="台账" reason="共享快照还没读到" />
        ) : (
          <>
            {/* D21（与 Home 的「台账」卡、Run 的「台账」卡同一个口径）：`events` 是
                写入笔数（`upserts`），不是 events.jsonl 的总行数；其中的 commit 标记行数
                单列。两次事务写两行 ⇒ 只报总行数会把"写了多少笔"翻倍地回答。 */}
            <div class="readings">
              台账写入{" "}
              <span class="mono">
                {ledger.upserts === null ? "unknown" : ledger.upserts}
              </span>{" "}
              笔（其中 commit 标记{" "}
              <span class="mono">
                {ledger.commit_markers === null ? "unknown" : ledger.commit_markers}
              </span>{" "}
              行）· tasks 行数{" "}
              <span class="mono">{ledger.tables === null ? "unknown" : ledger.tables}</span> ·
              读不出的行{" "}
              <span class="mono">{ledger.corrupt_rows === null ? "unknown" : ledger.corrupt_rows}</span> 行
              （坏行不计进「写入」那一格）· 落点 <span class="mono">{ledger.path}</span>
            </div>
            {ledger.events_note === "" ? null : (
              <div class="readings">{ledger.events_note}</div>
            )}
            {ledger.tables_note === "" ? null : (
              <div class="readings">{ledger.tables_note}</div>
            )}
            {ledger.note === "" ? null : <div class="readings">{ledger.note}</div>}
          </>
        )}
      </Card>

      <Card
        title={ARTIFACT_CARDS.handoffs}
        subtitle={`${art.handoffs.length} / 共 ${totalOf(art, "handoffs", art.handoffs.length)} 条 · 正文 sha 不再显示（没有第二份可比，业主不关心原文）`}
        right={<TriState tri={art.handoffs_tri} label="handoffs" />}
      >
        <PartialRows note={rowsNote(art, "handoffs", art.handoffs.length)} />
        {isUnreadable(art.handoffs_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : art.handoffs_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <PagedTable
            rows={art.handoffs}
            empty="交接台账 0 条（读到了，里面是空的）。"
            columns={[
              { key: "id", title: "编号" },
              // 这两列印读侧算好的 `sender_label` / `to_label`
              // （`M（t-000001）` / `A（t-000002）`；旧行是 `（旧账无号）`），
              // 不直接印 `sender` / `to` 那种只有角色名的裸值 ——
              // 角色名与编号各占一格，页面只负责显示，不自己拼编号。
              { key: "sender", title: "发", render: (r) => plain(r.sender_label) },
              { key: "to", title: "收", render: (r) => plain(r.to_label) },
              { key: "summary", title: "摘要", render: (r) => plain(r.summary) },
              { key: "refs", title: "引用" },
              { key: "sid", title: "会话", render: (r) => cell(r.sid) },
              { key: "task_id", title: "任务", render: (r) => cell(r.task_id) },
              { key: "format", title: "格式" },
              {
                key: "bytes",
                title: "字节",
                render: (r) => cell(r.bytes),
              },
              { key: "body", title: "正文（截断）", render: (r) => plain(clip(r.body)) },
            ]}
          />
        )}
      </Card>

      <Card
        title={ARTIFACT_CARDS.checks}
        subtitle={
          art.checks_tri === "not_applicable"
            ? "这一趟没有这份表"
            : `${art.checks.length} 行`
        }
        right={<TriState tri={art.checks_tri} label="checks" />}
      >
        <PartialRows note={rowsNote(art, "checks", art.checks.length)} />
        {/* 这张卡按三态分档：
            没这份表 ⇒ 一句话说清它是谁写的、什么时候会有；有才画表 ——
            否则读者看到的是一屏"不适用"，而不是"这一趟没走到这一步"。 */}
        {isUnreadable(art.checks_tri) ? (
          <span class="empty">这一栏没查成（不是"0 行"）。</span>
        ) : art.checks.length === 0 ? (
          <span class="readings">
            这一趟没有 <span class="mono">{checksPath(art)}</span> ——
            它是收工那一步（G 的收工门 / `closing`）写给论文包看的机器可判行，
            还没走到那一步就没有它（不是"0 行"，也不是没查成）。
          </span>
        ) : (
          <>
            {/* B3：这一栏的判据类型是**读数键**，交接手稿那一档的正名是 handoff_rows。
                老表的 manuscript_rows 是旧名（deprecated，同值）—— 它数的是
                `manuscripts/handoffs.jsonl` 的行数，不是论文手稿份数。 */}
            <div class="readings">
              读数键：「交接手稿份数」那一档的正名是 <span class="mono">handoff_rows</span>；
              盘上老表里的 <span class="mono">manuscript_rows</span> 是它的旧名
              （deprecated，同值；数的是 <span class="mono">manuscripts/handoffs.jsonl</span>
              的行数，不是论文手稿份数）。
            </div>
            <PagedTable
              rows={art.checks}
              empty="验收表还没写（合法初态：这一趟还没声明机器可判行）。"
              columns={[
                { key: "id", title: "编号" },
                { key: "name", title: "名字" },
                { key: "kind", title: "判据类型", render: (r) => kindText(r) },
                {
                  key: "min",
                  title: "下限",
                  render: (r) => bound(r, "min"),
                },
                {
                  key: "max",
                  title: "上限",
                  render: (r) => bound(r, "max"),
                },
                { key: "note", title: "备注" },
              ]}
            />
          </>
        )}
      </Card>

      <Card
        title={ARTIFACT_CARDS.style}
        subtitle={
          art.style_tri === "not_applicable"
            ? "M 还没声明体例"
            : `${art.style.sections.length} 节`
        }
        right={<TriState tri={art.style_tri} label="REPORT-STYLE" />}
      >
        {/* 体例是 M 在收工前自己声明的那一份（`out/report/REPORT-STYLE.json`）。
            它缺席 = "M 还没声明"，不是"没读到"—— 这一档要在页面上说出来。 */}
        {isUnreadable(art.style_tri) ? (
          <span class="empty">这一栏没查成（不是"0 节"）。</span>
        ) : art.style.sections.length === 0 ? (
          <span class="readings">
            M 还没声明交付说明的体例（<span class="mono">out/report/REPORT-STYLE.json</span>
            不在盘上）。它在收工前由主控写；写完这一栏会逐节列出来。
          </span>
        ) : (
          <ol class="list">
            {art.style.sections.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        )}
      </Card>

      {/* 「六件产物」属于 **`agentflow project run` 那条流水线**
          （`run-manifest.json` / `model-transcript.jsonl` / `evidence.json` /
          `claims.json` / `cost.json` / `report.md` 落在 `out/run-N/` 下），
          审阅型项目里一张都不会有 ⇒ 没有那个目录时整卡只给一句导引；
          真有那个目录时（`project run` 跑过的项目）照旧画表。 */}
      {art.run_dir === "" ? (
        <Card title={ARTIFACT_CARDS.products} subtitle="属于另一条流水线">
          <div class="readings">
            六件产物（<span class="mono">run-manifest.json</span> /
            <span class="mono">model-transcript.jsonl</span> /
            <span class="mono">evidence.json</span> / <span class="mono">claims.json</span> /
            <span class="mono">cost.json</span> / <span class="mono">report.md</span>）
            是 <span class="mono">agentflow project run</span> 那条流水线落在
            <span class="mono">out/run-N/</span> 下的运行产物。本项目是审阅型，
            没有那个目录 —— 这一趟的产物看上面的台账、交接手稿与
            <span class="mono">out/package/</span>。
          </div>
        </Card>
      ) : (
        <Card
          title={ARTIFACT_CARDS.products}
          subtitle={`${art.run_dir} · 这六件只有盘上这一份，没有第二份可比 ⇒ 不显示 sha`}
          right={<TriState tri={art.products_tri} label="products" />}
        >
          <PartialRows note={rowsNote(art, "products", art.products.length)} />
          {isUnreadable(art.products_tri) ? (
            <span class="empty">这一栏没查成（不是"六件都不在"）。</span>
          ) : art.products_tri === "not_applicable" ? (
            <span class="empty">还没有这张表（这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
          ) : (
            <PagedTable
              rows={art.products}
              empty="六件产物一件都没有（读到了，里面是空的）。"
              columns={[
                { key: "name", title: "名字" },
                {
                  key: "exists",
                  title: "在不在",
                  render: (r) => (
                    <Badge
                      kind={r.exists ? "badge-pass" : "badge-na"}
                      text={r.exists ? "在" : "不在"}
                    />
                  ),
                },
                {
                  key: "bytes",
                  title: "字节",
                  render: (r) => (r.bytes === null ? "unknown" : String(r.bytes)),
                },
                {
                  key: "lines",
                  title: "行数",
                  render: (r) =>
                    r.lines === null ? "unknown（非 JSONL，按设计没有行数）" : String(r.lines),
                },
                // 这里不印 sha：六件产物只有盘上这一份，没有第二份可比 ——
                // 一列"unknown（没得比）"不如在副标题里说清这件事。
                // 台账钉过的文件在上面两栏里有一致性读数。
                { key: "tri", title: "三态", render: (r) => <TriState tri={r.tri} /> },
              ]}
            />
          )}
        </Card>
      )}

      <Card
        title={ARTIFACT_CARDS.spots}
        id="experiment-spots"
        subtitle={`${art.experiment_spots.length} 个落点 · ${art.code_exp.length} 个实验脚本 · code/exp/ 与 out/experiments/<号>/`}
        right={<TriState tri={art.experiment_spots_tri} label="experiment_spots" />}
      >
        <PartialRows note={rowsNote(art, "experiment_spots", art.experiment_spots.length)} />
        {/* 数值实验的产出分三处 ——
            `code/exp/` 下的脚本、`out/experiments/<号>/design.md`（这一步打算怎么验）、
            `out/experiments/<号>/exhaustion.md`（程序 / 程序设计 / 穷举论证三块，V 会审它）。
            这一栏只报盘上真有什么；没有就直说"还没跑过实验"，不铺一屏"不在"。 */}
        {isUnreadable(art.experiment_spots_tri) ? (
          <span class="empty">这一栏没查成（不是"一个落点都没有"）。</span>
        ) : art.experiment_spots.length === 0 ? (
          <div class="readings">
            {art.experiment_spots_reason === ""
              ? "这一趟还没有实验产物（out/experiments/ 下没有 <实验号>/ 目录）。"
              : art.experiment_spots_reason}
          </div>
        ) : (
          <PagedTable
            rows={art.experiment_spots}
            empty="这一趟还没有实验产物。"
            columns={[
              { key: "path", title: "落点" },
              { key: "kind", title: "哪一份" },
              {
                key: "exists",
                title: "在不在",
                render: (r) => (
                  <Badge
                    kind={r.exists ? "badge-pass" : "badge-na"}
                    text={r.exists ? "在" : "不在"}
                  />
                ),
              },
              {
                key: "bytes",
                title: "字节",
                render: (r) => (r.bytes === null ? "unknown" : String(r.bytes)),
              },
              { key: "tri", title: "三态", render: (r) => <TriState tri={r.tri} /> },
            ]}
          />
        )}
        {art.code_exp.length === 0 ? null : (
          <div class="readings">
            <span class="mono">code/exp/</span> 下的脚本：
            {art.code_exp.map((f) => ` ${f.path}（${f.bytes === null ? "unknown" : f.bytes} 字节）`)}
          </div>
        )}
      </Card>

      <Card
        title={ARTIFACT_CARDS.tasks}
        subtitle={`${art.tasks.length} / 共 ${totalOf(art, "tasks", art.tasks.length)} 行`}
        right={<TriState tri={art.tasks_tri} label="tasks" />}
      >
        <PartialRows note={rowsNote(art, "tasks", art.tasks.length)} />
        {isUnreadable(art.tasks_tri) ? (
          <span class="empty">这一栏没查成（不是"0 行"）。</span>
        ) : art.tasks_tri === "not_applicable" ? (
          <span class="empty">还没有这张表（这一栏一次都没落过盘） —— 不是"读到了、里面是 0 行"。</span>
        ) : (
          <PagedTable
            rows={art.tasks}
            empty="tasks 台账为空。"
            columns={[
              { key: "task_id", title: "任务号" },
              { key: "role", title: "角色" },
              // 实例身份（`identity.py` 的规范实例标签，落点是 `tasks.instance`）：
              // 两个 F 一起干活时只有这一列分得开谁是谁；空串 = 这一行没有实例身份
              // （直调 / 老行），页面写「—」，不拿角色名冒充实例。
              {
                key: "instance",
                title: "实例",
                render: (r) => (
                  <span class="mono">
                    {r.instance === "" ? "—（没有实例身份）" : r.instance}
                  </span>
                ),
              },
              { key: "action", title: "动作" },
              { key: "called_by", title: "谁调的" },
              // `seen_step`：这一行第一次被看到时主控在第几步（台账里没有"步"这一列，
              // 只有这一格读数；读不到 ⇒ —，不是 0）。
              { key: "seen_step", title: "看到它的步", render: (r) => blank(r.seen_step) },
              // 状态列读后端现算的 `status_reading`（D12 ②）：板项行
              // （`kind` 非空）的 `status` 在台账里恒为 `pending`（那是"这一行是板项"
              // 的类型标记），真正的收口在 `item_state`/`item_close`。直接印 `status`
              // 会把 71 条 `item_state=done` 的 notice 全显示成 pending。
              // 投影与 `.md` 状态报告是同一个函数（`statusreport.tasks_row_reading`）。
              { key: "status", title: "状态", render: (r) => cell(r.status_reading) },
              { key: "outcome", title: "结局", render: (r) => cell(r.outcome) },
              {
                key: "usd",
                title: "花销",
                render: (r) => formatUsd(r.usd),
              },
              { key: "detail", title: "说明", render: (r) => clip(r.detail) },
            ]}
          />
        )}
        {isUnreadable(art.tasks_tri) ? null : (
          <div class="readings">
            板项行（kind 非空）的「状态」按 item_state/item_close 投影：它们在台账里的
            status 恒为 pending（那是"这一行是板项"的类型标记，不是没收口）——
            投影与状态报告是同一个函数，盘上那一格一个字都没改。
          </div>
        )}
      </Card>

      <Card
        title={ARTIFACT_CARDS.library}
        subtitle={
          library.data === null
            ? "这一面还没读到"
            : `入库 ${library.data.data.count ?? "unknown"} 条 · 台账 ${library.data.data.rows_total ?? "unknown"} 行 · ${library.data.data.table}`
        }
        tone={library.data !== null && library.data.state === "unknown" ? "problem" : "plain"}
        right={
          <TriState
            tri={
              library.data === null || library.data.state === "unknown" ? "unknown" : "computed"
            }
            label="文献库"
            reason={library.data === null ? library.problem : library.data.reason}
          />
        }
      >
        {libraryBody(library.data, library.problem)}
        {/* SEEDFIX：种子与"已登记书架"两个读数。放在 `libraryBody` 之后是因为
            那三档空态会提前 return —— 而"文献库 0 条"恰恰是最该看见 seed 的时候
            （真机那次 25 份未登记种子铺在 library/ 根，页面照样只显示"0 条"）。 */}
        {library.data === null ? null : seedLine(library.data.data.seed)}
      </Card>
    </>
  );
}
