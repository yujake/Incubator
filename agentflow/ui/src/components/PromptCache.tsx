/*
 * 两档提示词缓存的两张面孔：顶部那条换 key 的提醒（`CacheBanner`），以及
 * 状态面板加两个预热按钮（`CachePanel`）。
 *
 * 业主 2026-10-23：「把两档缓存落地为用户使用系统时可调用的工具，并在网页端给按钮，
 * 给两档缓存是否落地是否可用的状态显示，且换 key 时自动提醒重落受影响智能体的缓存」。
 * 这一页就是那句话的台面落点，读的是 `GET /api/cache`（`cachectl.status()` 原样），
 * 按的是 `POST /api/cache/warm`（写面：回环来源 + CSRF + `--allow-writes` + `confirm=1`）。
 *
 * 三态纪律：
 * - 某一档 `tri !== "found"`（整档没有读数 / 读数读不出来）⇒ 那一档的四格画成
 *   `unknown` 并写出理由，不许画成"没预热"，更不许用另一档的数顶上来；
 * - `fresh === null`（没量过 / 没渲染出来）也一样是 `unknown`，不是 `false`；
 * - 面板的"没读到"（`face.problem`）与"没有缓存"是两句话。
 *
 * 钱：按钮上的二次确认（`ConfirmButton`）是硬要求，后端缺 `confirm=1` 会 400 拒绝。
 * "试算"那一个按钮走 `dry_run=1`：只算计划，零花费，所以不需要确认。
 */
import { useState } from "preact/hooks";

import { api, postCacheWarm, whyOf } from "../api";
import type { CacheActive, CacheTier, CacheView } from "../api";
import { useFace } from "../live";
import { Badge } from "./Badge";
import { Card } from "./Card";
import { ConfirmButton } from "./ConfirmButton";

/** 关掉横幅的落点。键里带 `dismiss_key`（指纹 + 模型）⇒ 换 key 之后横幅会再出现一次。 */
const DISMISS_STORE = "agentflow.cache.reminder.dismissed";

function dismissedBefore(): string {
  try {
    return window.localStorage.getItem(DISMISS_STORE) ?? "";
  } catch (exc) {
    void exc;
    return "";
  }
}

function rememberDismissed(key: string): void {
  try {
    window.localStorage.setItem(DISMISS_STORE, key);
  } catch (exc) {
    // 无痕模式 / 关掉本地存储：只关这一次，不假装记住了。
    void exc;
  }
}

/** 美元那一格：`null` 读成 `unknown`（不是 0）。 */
function usd(value: number | null): string {
  return value === null ? "unknown" : `$${value.toFixed(6)}`;
}

function listOf(items: string[]): string {
  return items.length === 0 ? "无" : items.join("、");
}

/**
 * 把后端那一行里的加粗标记画成粗体（`active.text` 是唯一真身）。
 *
 * 为什么文案不在前端拼：命令行 `cache status` 印的是同一个字符串（同一个函数出），
 * 两处各拼一份，"网页上说的档"与"命令行说的档"迟早会漂，而漂了没有任何地方会报错。
 */
function emphasized(text: string) {
  return text.split("**").map((part, index) =>
    index % 2 === 1 ? <b key={index}>{part}</b> : <span key={index}>{part}</span>,
  );
}

/** 当前使用的那一档：顶部横幅与状态面板都先画这一行（读不出来时是"没有可用缓存"）。 */
function ActiveReading(props: { active: CacheActive }) {
  const a = props.active;
  return (
    <div class={a.tri === "found" ? "readings" : "readings tri-reason"}>
      {emphasized(a.text)}
    </div>
  );
}

/** 那一档的徽标（档名由后端给；读不出来时只说"没有可用缓存"，与那一行同义）。 */
function activeBadge(active: CacheActive) {
  return (
    <Badge
      kind={active.tri === "found" ? "badge-pass" : "badge-unknown"}
      text={active.tri === "found" ? active.label : "没有可用缓存"}
    />
  );
}

/** 一档的"新鲜"那一格（`true` / `false` / `null` 三档，不许折平）。 */
function freshCell(tier: CacheTier) {
  if (tier.tri !== "found" || tier.fresh === null) {
    return <Badge kind="badge-unknown" text="unknown" />;
  }
  return tier.fresh ? (
    <Badge kind="badge-pass" text="已是最新" />
  ) : (
    <Badge kind="badge-fail" text="不新鲜" />
  );
}

/** 一档的"落地"那一格。 */
function landedCell(tier: CacheTier) {
  if (tier.tri !== "found") {
    return <Badge kind="badge-unknown" text="unknown" />;
  }
  return <Badge kind="badge-pass" text="已落地" />;
}

/**
 * 顶部横幅：先说"当前在用哪一档"，再说换 key 那条提醒（可关掉）。
 *
 * 业主 2026-10-23 晚的补单：开网页监控时第一眼要看的是"当前使用哪一档缓存"，所以
 * 这一行即使在没有任何提醒时也必须画出来（原先是"没提醒就整块不渲染"）。
 *
 * 关掉只关提醒，不关这一行：`dismiss_key` 是当前 key 指纹 + 模型，换了 key 它就不一样，
 * 于是被关掉的提醒自己再出现 —— 不需要谁记得"上次关过要清一下"。
 */
export function CacheBanner() {
  const face = useFace<CacheView>(() => api.getCache());
  const [dismissed, setDismissed] = useState<string>(dismissedBefore);
  if (face.problem !== "") {
    return (
      <div class="card problem">
        <div class="card-head">
          <Badge kind="badge-unknown" text="缓存读数没读出来" />
        </div>
        <div class="readings">{face.problem}</div>
      </div>
    );
  }
  if (face.data === null) {
    return null;
  }
  const data = face.data;
  const reminder = data.reminder;
  const showReminder = reminder.active && reminder.dismiss_key !== dismissed;
  const stale = reminder.tri === "stale";
  return (
    <div class={showReminder && stale ? "card problem" : "card"}>
      <div class="card-head">
        {activeBadge(data.active)}
        {showReminder ? (
          <Badge
            kind={stale ? "badge-fail" : "badge-unknown"}
            text={stale ? "换了 key：这一档缓存要重落" : "换没换过 key：不可判定"}
          />
        ) : null}
        {showReminder ? (
          <span class="card-right">
            <button
              class="btn"
              type="button"
              onClick={() => {
                rememberDismissed(reminder.dismiss_key);
                setDismissed(reminder.dismiss_key);
              }}
            >
              知道了，先关掉
            </button>
          </span>
        ) : null}
      </div>
      <ActiveReading active={data.active} />
      {showReminder ? <div class="readings">{reminder.text}</div> : null}
      {showReminder && reminder.affected.length > 0 ? (
        <div class="readings">
          受影响的智能体：<span class="mono">{listOf(reminder.affected)}</span>
          （按这一档重新预热就能把它们的新前缀写进缓存）
        </div>
      ) : null}
    </div>
  );
}

/** 一档那一段：四格读数 + 最后一趟 + 两个按钮（真预热要二次确认，试算不花钱）。 */
function TierBlock(props: {
  tier: CacheTier;
  busy: boolean;
  onWarm: () => void;
  onPlan: () => void;
}) {
  const t = props.tier;
  const present = t.total - t.absent.length;
  const disabled = t.tri === "found" && t.fresh === true;
  const note =
    t.tri !== "found"
      ? `这一档还没有可用的读数（${t.reason || "unknown"}）—— 可以先试算，再真预热`
      : disabled
        ? "已是最新（提示词没变、key 没变），不用重落"
        : `不新鲜：${listOf(t.not_fresh)}`;
  return (
    <div class="row">
      <div class="readings">
        <b>{t.label}</b>
        <span class="tri-reason"> 这一档的 </span>
        <span class="mono">{present}</span>
        <span class="tri-reason"> 个目标（L 在关档是受控缺席）</span>
      </div>
      <div class="readings">
        落地 {landedCell(t)} · 新鲜 {freshCell(t)} · 覆盖{" "}
        <span class="mono">
          {t.covered}/{t.total}
        </span>{" "}
        · 缺谁 <span class="mono">{listOf(t.missing)}</span>
        {t.absent.length === 0 ? null : (
          <span class="tri-reason">（受控缺席：{listOf(t.absent)}）</span>
        )}
      </div>
      {t.tri !== "found" ? (
        <div class="readings">这一档没查成：{t.reason}</div>
      ) : (
        <div class="readings">
          最后一趟 <span class="mono">{t.at || "（没有时间）"}</span> · prompt_version{" "}
          <span class="mono">{t.readings_prompt_version || "（空）"}</span> · 花费{" "}
          <span class="mono">{usd(t.spent_usd)}</span>
          {t.fresh_reason === "" ? null : <span class="tri-reason"> · {t.fresh_reason}</span>}
        </div>
      )}
      {t.key.tri === "same" ? null : (
        <div class="readings">
          {t.key.tri === "stale" ? "key 变了：" : "key 不可判定："}
          {t.key.text || t.key.reason}
        </div>
      )}
      <div class="readings">
        <ConfirmButton
          action={`真预热 ${t.label}`}
          impact={
            `这一下会真的向上游发请求、花真钱：这一档 ${present} 个目标各发一次` +
            `（另有命中样本两次）；上一趟花了 ${usd(t.spent_usd)}，本趟上限 0.10 美元。` +
            "跑完刷新本页看读数。"
          }
          disabled={disabled || props.busy}
          note={props.busy ? "正在发送…" : note}
          onConfirm={props.onWarm}
        />{" "}
        <button class="btn" type="button" disabled={props.busy} onClick={props.onPlan}>
          试算（不花钱）
        </button>
      </div>
    </div>
  );
}

/**
 * 状态面板：两档 × 四格 + 最后一趟的 `prompt_version` / `spent_usd` + 两个按钮。
 *
 * 按按钮之后只做两件事：把回执（`WriteResult.reason`）印出来，然后重取读数。
 * 真预热是 detached 子进程，所以它跑完之前读数不会变 —— 回执照实说这件事。
 */
export function CachePanel() {
  const face = useFace<CacheView>(() => api.getCache());
  const [busy, setBusy] = useState<string>("");
  const [note, setNote] = useState<string>("");
  const data = face.data;

  const press = (tier: CacheTier, dry: boolean): void => {
    setBusy(tier.tier);
    setNote(`${dry ? "试算" : "起预热"} ${tier.label}…`);
    postCacheWarm({ lean: tier.tier === "on" ? "on" : "off", dryRun: dry })
      .then((got) => {
        setNote(`${got.ok ? "收下" : "没成"}（tri=${got.tri}）：${got.reason}`);
        if (!dry) {
          face.reload();
        }
      })
      .catch((exc: unknown) => {
        setNote(`没成：${whyOf(exc)}`);
      })
      .finally(() => {
        setBusy("");
      });
  };

  return (
    <Card
      title="提示词缓存（两档）"
      subtitle={
        data === null
          ? "读数还没取到"
          : `当前开关 ${data.lean_now ? "Lean 开" : "Lean 关"} · 提示词版本 ${data.prompt_version}`
      }
      tone={face.problem === "" ? "plain" : "problem"}
      right={
        <button class="btn" type="button" onClick={face.reload}>
          重取读数
        </button>
      }
    >
      {face.problem === "" ? null : <div class="readings">{face.problem}</div>}
      {data === null ? (
        <div class="readings">还没有读数（不是"没有缓存"）</div>
      ) : (
        <>
          <ActiveReading active={data.active} />
          {Object.values(data.tiers).map((tier) => (
            <TierBlock
              key={tier.tier}
              tier={tier}
              busy={busy === tier.tier}
              onWarm={() => {
                press(tier, false);
              }}
              onPlan={() => {
                press(tier, true);
              }}
            />
          ))}
        </>
      )}
      {note === "" ? null : <div class="readings">{note}</div>}
      <div class="readings tri-reason">
        口径：落地＝读数文件里这一档有那一趟；新鲜＝现渲染的 prompt_sha256 与读数一致；
        换 key 之后旧那一片缓存作废，所以要按档重落。真预热会花钱（上限 0.10 美元 / 趟）。
      </div>
    </Card>
  );
}
