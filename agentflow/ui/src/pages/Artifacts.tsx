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
 * 7. 文献库 `library` —— 2026-10-24（D-57）起读 `GET /api/literature`
 *    （`api.getLibrary()` → `LibraryView`）：只算「正式入库」的那一档，每条带
 *    题名 / 作者 / DOI 或去重键 / 命中校验 / 认领与挖掘尝试 / 下载落地（与盘上的
 *    文件核过：在 / 不在 / 读不到）/ 被哪条命题、第几份证明用过。三种空态分三档
 *    显示：这条端点读不到、台账里 0 条、台账读不到 —— 它们不许被画成同一个样子；
 * 8. 台账对账 `ledger_verify`（台账钉住的那一份 vs 盘上现在这一份；2026-10-23 前
 *    它只在台账那一卡里并排显示）；
 * 9. 实验产物的落点 `experiment_spots` 与 `code_exp` —— 第九张是它（2026-10-23 补：
 *    `code/exp/` 下的脚本与 `out/experiments/<号>/{design,exhaustion}.md`；
 *    证据链那张实验表的「报告」列也链到这张卡）。
 *
 * 另有一张「台账（第二个独立读数）」卡不在那张表里：它读的是共享快照
 * （`useLive().snapshot.ledger`，与首页 / 一趟详情的「台账」卡同一份），不是这一面的
 * 栏 —— 把它数进"栏数"会让"这一面有几栏"与"这一面读了几份盘"混成一件事。
 *
 * 数法（免得"九"与屏幕上数卡片对不上）：本页同时渲染十一张卡 —— 页头那张「产物」卡
 * ＋ 这一面的九栏 ＋ 一张台账镜子卡。源码里 `<Card` 出现十三处，是因为页头卡有一个
 * 「还没读到」的副本、「六件产物」按 `art.run_dir` 分两支（两支是同一栏）。
 *
 * ## 2026-10-23（业主：这一页的显示格式略有过时）
 *
 * - sha 原文一律不上屏（「对于 sha 值用户并不关心，只用显示是否一致即可」）：
 *   台账那一格说"一致 / 不一致 / unknown（没得比）"，副标题写清比的是与哪一份；
 *   半截哈希那种写法（前 8 位）也不许出现 —— 它既不能核也不能读；
 * - 补 `code/exp/` 与 `out/experiments/<号>/{design,exhaustion}.md` 的落点那一栏
 *   （实验代码与两份读得懂的说明落在哪，盘上现在有没有）；
 * - 台账改成 `upserts` / `commit_markers` 两格（与 `Home` / `Run` 同一句文案），
 *   不再有"事件 N 条"那种总行数口径。
 */
import type { ComponentChildren } from "preact";

import { api } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { Consistency } from "../components/Consistency";
import { Table, cell, plain } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace, useLive } from "../live";
import type { LibraryView, LibraryWork } from "../types";

/** 长文截断（与后端 `webui/state.py` 的 `CLIP` 同一口径：两头留、中间省）。 */
const CLIP = 400;

/** 这一面读数的九张卡：栏序 = `draft/74 §3.4` 那七栏 + 后来补的两栏，标题的唯一来源。
 *
 * 2026-10-23（业主：文件头写"七栏"而实际已是九张卡）：改前那个数字是手写的，
 * 加了卡它不会动 —— 于是文件头与屏幕各说各的。现在标题与数字都数这张表
 * （`CARD_COUNT`），加一张卡忘了登记、或文件头那个中文数字忘了改，
 * `tests/test_webui_readings_format.py` 的判据⑩ 会红。
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
 * 文献库那一格：三种空态必须分三档（业主 2026-10-24 的 D-57）。
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
      <Table
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
            render: (w) =>
              w.last_mine_error === ""
                ? String(w.mine_attempts)
                : `${w.mine_attempts} · 上次：${clip(w.last_mine_error)}`,
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
  const face = useFace(() => api.getArtifacts());
  // 文献库是第二条端点（D-57）：它与产物面是两份盘上的事实，各有各的三态 ——
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
          <span class="mono">out/paper/ACCEPTANCE-CHECKS.json</span> · 体例{" "}
          <span class="mono">out/review/REPORT-STYLE.json</span> · 秘书{" "}
          <span class="mono">out/secretary/</span> 下的 <span class="mono">*.jsonl</span>
          {" "}· 实验落点 <span class="mono">out/experiments/&lt;号&gt;/</span> 与{" "}
          <span class="mono">code/exp/</span>
        </div>
        <div class="readings">
          张数数的是 <span class="mono">ARTIFACT_CARDS</span> 那张表（标题与数字同一来源）：
          <span class="mono">draft/74 §3.4</span> 原有的那七栏 + 第八张「台账对账」、
          第九张「实验产物的落点」。另有一张「台账（第二个独立读数）」读的是共享快照
          （与首页同一份），不是这一面的栏。
        </div>
      </Card>

      <Card
        title={ARTIFACT_CARDS.ledger}
        subtitle={`${art.ledger.length} 行 · 一致性比的是与「台账对账」那一栏同一路径的核对行`}
        right={<TriState tri={art.ledger_tri} label="ledger" />}
      >
        {isUnreadable(art.ledger_tri) ? (
          <span class="empty">这一栏没查成（不是"0 行"）。</span>
        ) : (
          <Table
            rows={art.ledger}
            empty="暂无产物台账行。"
            columns={[
              { key: "path", title: "路径" },
              { key: "producer", title: "谁产出的" },
              { key: "kind", title: "类别" },
              {
                // 2026-10-23（业主：sha 原文不显示）：这一格取同一路径的核对行读数，
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
                render: (r) => String(r.bytes),
              },
              { key: "task_id", title: "任务" },
              { key: "at", title: "登记时间", render: (r) => cell(r.at) },
              // R93 体检：这里原来还有一列「退出码」。台账的格式里有 `exit_code`
              // 这一栏（`artifacts.FIELDS`），但真机上登记的都是 `out/tasks/` 下那些
              // "任务结果文件"——那种东西没有退出码，于是整列恒 `unknown`
              // （本机实测：t1-review-2 的 6 行全是）。退出码真正的落点是「证据链 →
              // 实验」那一张表（`experiments.exit_code`，那里是真读数），所以这一列撤掉。
            ]}
          />
        )}
      </Card>

      <Card
        title={ARTIFACT_CARDS.verify}
        subtitle={`${art.ledger_verify.length} 行 · sha 原文不上屏，只报一致 / 不一致 / unknown`}
        right={<TriState tri={art.ledger_verify_tri} label="verify_entries" />}
      >
        {isUnreadable(art.ledger_verify_tri) ? (
          <span class="empty">这一栏没查成（不是"全部对得上"）。</span>
        ) : (
          <Table
            rows={art.ledger_verify}
            empty="没有可对账的台账行（台账是空的）。"
            columns={[
              { key: "path", title: "路径" },
              {
                // 2026-10-23：原来的两列（台账里的 sha / 盘上现在的 sha）合成一列。
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

      <Card title="台账（第二个独立读数）" subtitle="写入笔数与 commit 标记分两格">
        {ledger === null ? (
          <TriState tri="unreadable" label="台账" reason="共享快照还没读到" />
        ) : (
          <>
            {/* D21（与 Home 的「台账」卡、Run 的「台账」卡同一个口径）：`events` 不再是
                events.jsonl 的总行数，它是写入笔数（`upserts`）；其中的 commit 标记行数
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
              <span class="mono">{ledger.tables === null ? "unknown" : ledger.tables}</span> · 落点{" "}
              <span class="mono">{ledger.path}</span>
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
        subtitle={`${art.handoffs.length} 条 · 正文 sha 不再显示（没有第二份可比，业主不关心原文）`}
        right={<TriState tri={art.handoffs_tri} label="handoffs" />}
      >
        {isUnreadable(art.handoffs_tri) ? (
          <span class="empty">这一栏没查成（不是"0 条"）。</span>
        ) : (
          <Table
            rows={art.handoffs}
            empty="交接台账 0 条（读到了，里面是空的）。"
            columns={[
              { key: "id", title: "编号" },
              { key: "sender", title: "发" },
              { key: "to", title: "收" },
              { key: "summary", title: "摘要", render: (r) => plain(r.summary) },
              { key: "refs", title: "引用" },
              { key: "sid", title: "会话", render: (r) => cell(r.sid) },
              { key: "task_id", title: "任务", render: (r) => cell(r.task_id) },
              { key: "format", title: "格式" },
              {
                key: "bytes",
                title: "字节",
                render: (r) => String(r.bytes),
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
        {/* R93 体检：这张卡原先在"没有这份文件"时照样铺满一张表（每格 `不适用`），
            读者看到的是"一屏不适用"，而不是"这一趟没走到这一步"。现在按三态分档：
            没这份表 ⇒ 一句话说清它是谁写的、什么时候会有；有才画表。 */}
        {isUnreadable(art.checks_tri) ? (
          <span class="empty">这一栏没查成（不是"0 行"）。</span>
        ) : art.checks.length === 0 ? (
          <span class="readings">
            这一趟没有 <span class="mono">out/paper/ACCEPTANCE-CHECKS.json</span> ——
            它是收工那一步（G 的收工门 / `closing`）写给论文包看的机器可判行，
            还没走到那一步就没有它（不是"0 行"，也不是没查成）。
          </span>
        ) : (
          <Table
            rows={art.checks}
            empty="验收表还没写（合法初态：这一趟还没声明机器可判行）。"
            columns={[
              { key: "id", title: "编号" },
              { key: "name", title: "名字" },
              { key: "kind", title: "判据类型" },
              {
                key: "min",
                title: "下限",
                render: (r) => String(r.min),
              },
              { key: "note", title: "备注" },
            ]}
          />
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
        {/* 体例是 M 在收工前自己声明的那一份（`out/review/REPORT-STYLE.json`）。
            它缺席 = "M 还没声明"，不是"没读到"—— 这一档要在页面上说出来。 */}
        {isUnreadable(art.style_tri) ? (
          <span class="empty">这一栏没查成（不是"0 节"）。</span>
        ) : art.style.sections.length === 0 ? (
          <span class="readings">
            M 还没声明交付说明的体例（<span class="mono">out/review/REPORT-STYLE.json</span>
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

      {/* R93 体检：原来这里还有一张「六件产物」卡（`run-manifest.json` /
          `model-transcript.jsonl` / `evidence.json` / `claims.json` / `cost.json` /
          `report.md`）。那六件属于 **`agentflow project run` 那条流水线**
          （`out/run-N/` 下的运行产物），审阅型项目里一张都不会有 ⇒ 整卡恒 `不适用`
          （本机实测：t1-review-2 六件全是 not_applicable）。所以整卡改成一句导引；
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
            <span class="mono">out/paper/</span>。
          </div>
        </Card>
      ) : (
        <Card
          title={ARTIFACT_CARDS.products}
          subtitle={`${art.run_dir} · 这六件只有盘上这一份，没有第二份可比 ⇒ 不显示 sha`}
          right={<TriState tri={art.products_tri} label="products" />}
        >
          {isUnreadable(art.products_tri) ? (
            <span class="empty">这一栏没查成（不是"六件都不在"）。</span>
          ) : (
            <Table
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
                // 2026-10-23（业主：sha 原文不显示）：这一列撤掉。六件产物只有盘上这
                // 一份，没有第二份可比 —— 印一列"unknown（没得比）"不如在副标题里
                // 说清这件事（下面那句就是它）。台账钉过的文件在上面两栏里有一致性读数。
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
        {/* 2026-10-23（业主：产物页要补这两处落点）：数值实验的产出分三处 ——
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
          <Table
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
        subtitle={`${art.tasks.length} 行`}
        right={<TriState tri={art.tasks_tri} label="tasks" />}
      >
        {isUnreadable(art.tasks_tri) ? (
          <span class="empty">这一栏没查成（不是"0 行"）。</span>
        ) : (
          <Table
            rows={art.tasks}
            empty="tasks 台账为空。"
            columns={[
              { key: "task_id", title: "任务号" },
              { key: "role", title: "角色" },
              { key: "action", title: "动作" },
              { key: "called_by", title: "谁调的" },
              { key: "status", title: "状态" },
              { key: "outcome", title: "结局", render: (r) => cell(r.outcome) },
              {
                key: "usd",
                title: "花销",
                render: (r) => (r.usd === null ? "unknown" : `${r.usd.toFixed(6)} USD`),
              },
              { key: "detail", title: "说明", render: (r) => clip(r.detail) },
            ]}
          />
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
      </Card>
    </>
  );
}
