# -*- coding: utf-8 -*-
"""用户端的样式资产：DSH 的令牌整份照搬 + 我们自己的组件样式。

## 这是什么

两份 CSS 文本，被 :mod:`agentflow.webui` 直接内联进服务端渲染的 HTML：

- :data:`THEME_CSS` —— 「逐字照搬」DeepSeek Harness 的令牌层（两层色板 + 明暗两套 +
  字体/运动 + 滚动条 + 圆角签名）。来源是 DSH 抽好的四份原始 CSS
  （本机路径 `temp/dsh-css/theme/`，即 DSH 包 `dsh-client-ui-theme` 内侧内联的
  `design-platform.css.mjs` / `base.css.mjs` / `scrollbar.css.mjs` /
  `corner-shape.css.mjs` 的语义等价物）。DSH 是 MIT 许可
  （`AppData/Roaming/npm/node_modules/@deepseek-ai/dsh/**/LICENSE`），
  用户 2026-10-03 明确允许「复制人家的代码微调」，本项目照此办理并在此注明来源。
- :data:`APP_CSS` —— 我们自己的组件（页面骨架 / 卡片 / 行 / 徽标 / 按钮 / 输入框 /
  等宽读数）。它「只用第二层语义别名」`var(--dsw-alias-*)` 与运动/字体令牌，
  一个色值都不写死。

## 为什么是这两份、而不是一份

令牌与组件分开，是「换皮只换一层」的前提：将来 DSH 更新令牌，替换
:data:`THEME_CSS` 即可，组件不动；反过来，我们改版式也不会碰到令牌。
这也是为什么 :data:`THEME_CSS` 里的令牌名「一个字都没改」：改了名字，
升级就得靠肉眼比对。

## 设计依据

`docs/USER-END-DSH-STYLE.md`（§2 令牌体系、§3 界面纪律）。要点：

1. 组件只用第二层（`--dsw-alias-*`）。三态读数
   （`pass` / `fail` / `unknown`）正好落到 `state-success-*` /
   `state-error-*` / `state-warn-*` 上，语义与颜色一一对应；
2. id / 路径 / 读数一律用 `--ds-font-family-code`（与 DSH 的工具输出、代码块一致）；
3. 圆角是一个签名：照抄 `@supports (corner-shape:superellipse(1.5))` 那段，
   支持超椭圆的浏览器上圆角可辨，不支持就退回普通圆角，零成本；
4. 过渡用 `--ds-transition-duration` + `--ds-ease-in-out`。

## 判据在哪

- `tests/test_webui.py::test_app_css_uses_only_tokens` —— 【负控】用正则自查
  `APP_CSS` 里「不许」出现 `#` 加 3/6 位十六进制、也不许出现 `rgb(` / `hsl(`，
  并要求至少出现 8 个不同的 `--dsw-alias-` 令牌名；
- `tests/test_webui.py::test_theme_css_keeps_dsh_tokens` —— 【正控】两层令牌、
  明暗两套、运动/字体、圆角 `@supports` 都在，且选择器只从 `body` 改成 `:root`。
"""

from __future__ import annotations

__all__ = ["THEME_CSS", "APP_CSS", "STYLESHEET"]

#: DSH 的令牌层，逐字照搬。微调只有一处：选择器 `body` / `body[data-ds-dark-theme]`
#: 改成 `:root` / `:root[data-ds-dark-theme]`（我们的页面没有 `body` 之外的挂载点，
#: 令牌挂在根上才能被所有元素继承；暗色主题靠 `<html data-ds-dark-theme>` 开）。
#: 唯一的例外是滚动条那段 `@supports not selector(::-webkit-scrollbar)` 里的
#: `body,body *`：它设的是 `scrollbar-width` / `scrollbar-color` 两个「元素属性」；
#: 必须落在真正滚动的元素上，改成 `:root` 会让它失效，所以留 `body`。
THEME_CSS = '''
    :root{
      --dsw-static-amber-100:#fef5e7;
      --dsw-static-amber-400:#f7ad31;
      --dsw-static-amber-500:#f59e0b;
      --dsw-static-amber-600:#dd8629;
      --dsw-static-amber-900:#27241f;
      --dsw-static-blue-100:#dbeafe;
      --dsw-static-blue-300:#93c5fd;
      --dsw-static-blue-400:#60a5fa;
      --dsw-static-blue-450:#4d93f8;
      --dsw-static-blue-500:#3b82f6;
      --dsw-static-blue-50:#eff6ff;
      --dsw-static-blue-50p:#eaf3ff;
      --dsw-static-blue-600:#2563eb;
      --dsw-static-blue-75:#e5f0ff;
      --dsw-static-blue-800:#1e40af;
      --dsw-static-blue-900:#0e3074;
      --dsw-static-blue-950:#172554;
      --dsw-static-deepseek-100:#e4edfd;
      --dsw-static-deepseek-200:#d3e2ff;
      --dsw-static-deepseek-300:#b7c8fe;
      --dsw-static-deepseek-400:#679efe;
      --dsw-static-deepseek-450:#5686fe;
      --dsw-static-deepseek-500:#4176e6;
      --dsw-static-deepseek-50:#edf3fe;
      --dsw-static-deepseek-600:#4868b2;
      --dsw-static-deepseek-700-delete:#2f4c8f;
      --dsw-static-deepseek-800:#34415b;
      --dsw-static-deepseek-900:#283142;
      --dsw-static-green-100:#e6faed;
      --dsw-static-green-400:#4ed17e;
      --dsw-static-green-500:#22c55e;
      --dsw-static-green-900:#233c2c;
      --dsw-static-neutral-00:#fff;
      --dsw-static-neutral-1000:#000;
      --dsw-static-neutral-100:#f5f5f5;
      --dsw-static-neutral-150:#ededed;
      --dsw-static-neutral-200:#e5e5e5;
      --dsw-static-neutral-250:#dcdcdc;
      --dsw-static-neutral-300:#d4d4d4;
      --dsw-static-neutral-400:#a2a4a6;
      --dsw-static-neutral-500:#7f8287;
      --dsw-static-neutral-50:#fafafa;
      --dsw-static-neutral-550:#65676b;
      --dsw-static-neutral-600:#545557;
      --dsw-static-neutral-700:#3c3c3d;
      --dsw-static-neutral-800:#292929;
      --dsw-static-neutral-850:#212123;
      --dsw-static-neutral-900:#0f0f0f;
      --dsw-static-neutral-bluish-00:#fff;
      --dsw-static-neutral-bluish-1000:#0f1115;
      --dsw-static-neutral-bluish-100:#ebeef2;
      --dsw-static-neutral-bluish-150:#e9ecf2;
      --dsw-static-neutral-bluish-200:#e1e5ee;
      --dsw-static-neutral-bluish-300:#cfd3d6;
      --dsw-static-neutral-bluish-400:#adb2b8;
      --dsw-static-neutral-bluish-500:#979da6;
      --dsw-static-neutral-bluish-50:#f9fafb;
      --dsw-static-neutral-bluish-600:#81858c;
      --dsw-static-neutral-bluish-60:#f5f6f7;
      --dsw-static-neutral-bluish-700:#61666b;
      --dsw-static-neutral-bluish-750:#43454a;
      --dsw-static-neutral-bluish-75:#f1f3f5;
      --dsw-static-neutral-bluish-800:#353638;
      --dsw-static-neutral-bluish-850:#2c2c2e;
      --dsw-static-neutral-bluish-875:#232324;
      --dsw-static-neutral-bluish-900:#1b1b1c;
      --dsw-static-neutral-bluish-950:#151517;
      --dsw-static-red-100:#fee2e2;
      --dsw-static-red-400:#f25a5a;
      --dsw-static-red-500:#ef4444;
      --dsw-static-red-50:#fef2f2;
      --dsw-static-red-600:#ec1313;
      --dsw-static-red-900:#570c0c;
    }
    :root[data-ds-dark-theme]{
      --dsw-static-amber-100:#fef5e7;
      --dsw-static-amber-400:#f7ad31;
      --dsw-static-amber-500:#f59e0b;
      --dsw-static-amber-600:#dd8629;
      --dsw-static-amber-900:#27241f;
      --dsw-static-blue-100:#dbeafe;
      --dsw-static-blue-300:#93c5fd;
      --dsw-static-blue-400:#60a5fa;
      --dsw-static-blue-450:#4d93f8;
      --dsw-static-blue-500:#3b82f6;
      --dsw-static-blue-50:#eff6ff;
      --dsw-static-blue-50p:#eaf3ff;
      --dsw-static-blue-600:#2563eb;
      --dsw-static-blue-75:#e5f0ff;
      --dsw-static-blue-800:#1e40af;
      --dsw-static-blue-900:#0e3074;
      --dsw-static-blue-950:#172554;
      --dsw-static-deepseek-100:#e4edfd;
      --dsw-static-deepseek-200:#d3e2ff;
      --dsw-static-deepseek-300:#b7c8fe;
      --dsw-static-deepseek-400:#679efe;
      --dsw-static-deepseek-450:#5686fe;
      --dsw-static-deepseek-500:#4176e6;
      --dsw-static-deepseek-50:#edf3fe;
      --dsw-static-deepseek-600:#4868b2;
      --dsw-static-deepseek-700-delete:#2f4c8f;
      --dsw-static-deepseek-800:#34415b;
      --dsw-static-deepseek-900:#283142;
      --dsw-static-green-100:#e6faed;
      --dsw-static-green-400:#4ed17e;
      --dsw-static-green-500:#22c55e;
      --dsw-static-green-900:#233c2c;
      --dsw-static-neutral-00:#fff;
      --dsw-static-neutral-1000:#000;
      --dsw-static-neutral-100:#f5f5f5;
      --dsw-static-neutral-150:#ededed;
      --dsw-static-neutral-200:#e5e5e5;
      --dsw-static-neutral-250:#dcdcdc;
      --dsw-static-neutral-300:#d4d4d4;
      --dsw-static-neutral-400:#a2a4a6;
      --dsw-static-neutral-500:#7f8287;
      --dsw-static-neutral-50:#fafafa;
      --dsw-static-neutral-550:#65676b;
      --dsw-static-neutral-600:#545557;
      --dsw-static-neutral-700:#3c3c3d;
      --dsw-static-neutral-800:#292929;
      --dsw-static-neutral-850:#212123;
      --dsw-static-neutral-900:#0f0f0f;
      --dsw-static-neutral-bluish-00:#fff;
      --dsw-static-neutral-bluish-1000:#0f1115;
      --dsw-static-neutral-bluish-100:#ebeef2;
      --dsw-static-neutral-bluish-150:#e9ecf2;
      --dsw-static-neutral-bluish-200:#e1e5ee;
      --dsw-static-neutral-bluish-300:#cfd3d6;
      --dsw-static-neutral-bluish-400:#adb2b8;
      --dsw-static-neutral-bluish-500:#979da6;
      --dsw-static-neutral-bluish-50:#f9fafb;
      --dsw-static-neutral-bluish-600:#81858c;
      --dsw-static-neutral-bluish-60:#f9fafb;
      --dsw-static-neutral-bluish-700:#61666b;
      --dsw-static-neutral-bluish-750:#43454a;
      --dsw-static-neutral-bluish-75:#f1f3f5;
      --dsw-static-neutral-bluish-800:#353638;
      --dsw-static-neutral-bluish-850:#2c2c2e;
      --dsw-static-neutral-bluish-875:#232324;
      --dsw-static-neutral-bluish-900:#1b1b1c;
      --dsw-static-neutral-bluish-950:#151517;
      --dsw-static-red-100:#fee2e2;
      --dsw-static-red-400:#f25a5a;
      --dsw-static-red-500:#ef4444;
      --dsw-static-red-50:#fef2f2;
      --dsw-static-red-600:#ec1313;
      --dsw-static-red-900:#570c0c;
    }
    :root{
      --dsw-alias-bg-base:var(--dsw-static-neutral-bluish-00);
      --dsw-alias-bg-layer-1:var(--dsw-static-neutral-bluish-00);
      --dsw-alias-bg-layer-2:var(--dsw-static-neutral-bluish-00);
      --dsw-alias-bg-layer-3:var(--dsw-static-neutral-bluish-00);
      --dsw-alias-bg-mask-1:#0000003d;
      --dsw-alias-bg-mask-2:#0000001f;
      --dsw-alias-bg-mask-3:#0000007a;
      --dsw-alias-bg-mask-photo:#000000e0;
      --dsw-alias-bg-mask-drop:#ffffffb3;
      --dsw-alias-bg-module-platform:var(--dsw-static-neutral-bluish-60);
      --dsw-alias-bg-multi-select:var(--dsw-static-neutral-bluish-60);
      --dsw-alias-bg-overlay:var(--dsw-static-neutral-bluish-150);
      --dsw-alias-bg-skeleton:#0000000a;
      --dsw-alias-border-inverted2:#0000;
      --dsw-alias-border-inverted:#0000;
      --dsw-alias-border-l1:#0000000a;
      --dsw-alias-border-l2-darkmode-thin:#0000001a;
      --dsw-alias-border-l2:#0000001a;
      --dsw-alias-border-l3:#0000001f;
      --dsw-alias-border-l4:#00000029;
      --dsw-alias-brand-primary-invert:var(--dsw-static-neutral-bluish-1000);
      --dsw-alias-brand-primary-new-colorprimary-new-color:#4176e6;
      --dsw-alias-brand-primary:var(--dsw-static-neutral-bluish-1000);
      --dsw-alias-brand-text:var(--dsw-static-neutral-bluish-1000);
      --dsw-alias-button-contrast-fill:var(--dsw-static-neutral-bluish-700);
      --dsw-alias-button-elevated-fill:var(--dsw-static-neutral-bluish-00);
      --dsw-alias-button-floating-fill:var(--dsw-static-neutral-bluish-00);
      --dsw-alias-button-floating-hover:var(--dsw-static-neutral-bluish-75);
      --dsw-alias-button-ghost-active-border:var(--dsw-static-neutral-bluish-500);
      --dsw-alias-button-ghost-active-fill:var(--dsw-static-neutral-bluish-100);
      --dsw-alias-button-ghost-active-hover:var(--dsw-static-neutral-bluish-150);
      --dsw-alias-button-info-fill:var(--dsw-static-deepseek-500);
      --dsw-alias-button-info-hover:var(--dsw-static-deepseek-400);
      --dsw-alias-button-primary-dimmed:var(--dsw-static-neutral-bluish-100);
      --dsw-alias-button-primary-fill:var(--dsw-alias-brand-primary);
      --dsw-alias-button-primary-hover:var(--dsw-static-neutral-bluish-750);
      --dsw-alias-button-tool-bar-fill-invisible:#1f1f1f5c;
      --dsw-alias-button-tool-bar-fill:#54555780;
      --dsw-alias-button-tool-bar-hover:#54555799;
      --dsw-alias-interactive-bg-active:#2631481a;
      --dsw-alias-interactive-bg-hover-accent:#26314824;
      --dsw-alias-interactive-bg-hover-danger:#ec13130d;
      --dsw-alias-interactive-bg-hover-solid:var(--dsw-static-neutral-bluish-75);
      --dsw-alias-interactive-bg-hover:#2631480f;
      --dsw-alias-label-caption:var(--dsw-static-neutral-bluish-400);
      --dsw-alias-label-dimmed:var(--dsw-static-neutral-bluish-200);
      --dsw-alias-label-primary-bluish:var(--dsw-static-blue-900);
      --dsw-alias-label-primary-dimmed:var(--dsw-static-neutral-bluish-950);
      --dsw-alias-label-primary-foreground:var(--dsw-static-neutral-bluish-00);
      --dsw-alias-label-primary-inverted:var(--dsw-static-neutral-bluish-00);
      --dsw-alias-label-primary:var(--dsw-static-neutral-bluish-1000);
      --dsw-alias-label-secondary:var(--dsw-static-neutral-bluish-700);
      --dsw-alias-label-tertiary:var(--dsw-static-neutral-bluish-600);
      --dsw-alias-link:var(--dsw-static-deepseek-500);
      --dsw-alias-markdown-citation:var(--dsw-static-neutral-bluish-100);
      --dsw-alias-markdown-code-block-banner:var(--dsw-static-neutral-bluish-50);
      --dsw-alias-markdown-code-block:var(--dsw-static-neutral-bluish-50);
      --dsw-alias-markdown-code-segment-selected:var(--dsw-static-neutral-bluish-00);
      --dsw-alias-markdown-code-segment-unselected:var(--dsw-static-neutral-bluish-75);
      --dsw-alias-markdown-inline-code:var(--dsw-static-neutral-50);
      --dsw-alias-markdown-placeholder:var(--dsw-static-neutral-bluish-60);
      --dsw-alias-markdown-tag:var(--dsw-static-neutral-bluish-75);
      --dsw-alias-scrollbar-bg-l1:var(--dsw-static-neutral-200);
      --dsw-alias-scrollbar-bg-l2:var(--dsw-static-neutral-200);
      --dsw-alias-scrollbar-hover-l1:var(--dsw-static-neutral-300);
      --dsw-alias-scrollbar-hover-l2:var(--dsw-static-neutral-300);
      --dsw-alias-state-business-primary:var(--dsw-static-deepseek-500);
      --dsw-alias-state-business-tertiary:var(--dsw-static-deepseek-100);
      --dsw-alias-state-error-primary:var(--dsw-static-red-600);
      --dsw-alias-state-error-secondary:var(--dsw-static-red-400);
      --dsw-alias-state-success-primary:var(--dsw-static-green-500);
      --dsw-alias-state-success-secondary:var(--dsw-static-green-400);
      --dsw-alias-state-success-tertiary:var(--dsw-static-green-100);
      --dsw-alias-state-warn-label:var(--dsw-static-amber-600);
      --dsw-alias-state-warn-primary:var(--dsw-static-amber-500);
      --dsw-alias-state-warn-secondary:var(--dsw-static-amber-400);
      --dsw-alias-state-warn-tertiary:var(--dsw-static-amber-100);
      --dsw-alias-toast-bg:var(--dsw-static-neutral-bluish-800);
      --dsw-alias-tooltip-bg:var(--dsw-static-neutral-bluish-850);
      --dsw-specific-bubble-highlight:var(--dsw-static-deepseek-200);
      --dsw-specific-bubble:var(--dsw-static-deepseek-50);
      --dsw-specific-input-major:var(--dsw-static-neutral-bluish-00);
      --dsw-specific-login-input:var(--dsw-static-neutral-bluish-50);
      --dsw-specific-menu:var(--dsw-alias-bg-layer-3);
      --dsw-specific-selector:var(--dsw-static-neutral-bluish-60);
      --dsw-specific-sidebar-fill:var(--dsw-static-neutral-bluish-50);
      --dsw-specific-sidebar-nav-item-active-accent:var(--dsw-static-deepseek-100);
      --dsw-specific-sidebar-nav-item-active:var(--dsw-static-neutral-bluish-100);
      --dsw-specific-sidebar-nav-item-hover:var(--dsw-static-neutral-bluish-75);
      --dsw-specific-tip:var(--dsw-static-neutral-bluish-60);
    }
    :root[data-ds-dark-theme]{
      --dsw-alias-bg-base:var(--dsw-static-neutral-bluish-950);
      --dsw-alias-bg-layer-1:var(--dsw-static-neutral-bluish-875);
      --dsw-alias-bg-layer-2:var(--dsw-static-neutral-bluish-850);
      --dsw-alias-bg-layer-3:var(--dsw-static-neutral-bluish-800);
      --dsw-alias-bg-mask-1:#00000080;
      --dsw-alias-bg-mask-2:#0003;
      --dsw-alias-bg-mask-3:#0000007a;
      --dsw-alias-bg-mask-photo:#000000e0;
      --dsw-alias-bg-mask-drop:#272730b3;
      --dsw-alias-bg-module-platform:var(--dsw-static-neutral-bluish-800);
      --dsw-alias-bg-multi-select:var(--dsw-static-neutral-850);
      --dsw-alias-bg-overlay:var(--dsw-static-neutral-bluish-700);
      --dsw-alias-bg-skeleton:#ffffff14;
      --dsw-alias-border-inverted2:#ffffff14;
      --dsw-alias-border-inverted:#ffffff0f;
      --dsw-alias-border-l1:#ffffff0f;
      --dsw-alias-border-l2-darkmode-thin:#ffffff0f;
      --dsw-alias-border-l2:#ffffff1f;
      --dsw-alias-border-l3:#ffffff29;
      --dsw-alias-border-l4:#fff3;
      --dsw-alias-brand-primary-invert:var(--dsw-static-neutral-bluish-50);
      --dsw-alias-brand-primary-new-colorprimary-new-color:var(--dsw-static-deepseek-450);
      --dsw-alias-brand-primary:var(--dsw-static-neutral-bluish-50);
      --dsw-alias-brand-text:var(--dsw-static-neutral-bluish-50);
      --dsw-alias-button-contrast-fill:var(--dsw-static-neutral-bluish-50);
      --dsw-alias-button-elevated-fill:var(--dsw-static-neutral-bluish-750);
      --dsw-alias-button-floating-fill:var(--dsw-static-neutral-bluish-850);
      --dsw-alias-button-floating-hover:var(--dsw-static-neutral-bluish-800);
      --dsw-alias-button-ghost-active-border:var(--dsw-static-neutral-bluish-600);
      --dsw-alias-button-ghost-active-fill:var(--dsw-static-neutral-bluish-750);
      --dsw-alias-button-ghost-active-hover:var(--dsw-static-neutral-bluish-700);
      --dsw-alias-button-info-fill:var(--dsw-static-deepseek-400);
      --dsw-alias-button-info-hover:var(--dsw-static-deepseek-500);
      --dsw-alias-button-primary-dimmed:var(--dsw-static-neutral-bluish-750);
      --dsw-alias-button-primary-fill:var(--dsw-alias-brand-primary);
      --dsw-alias-button-primary-hover:var(--dsw-static-neutral-bluish-100);
      --dsw-alias-button-tool-bar-fill-invisible:#1f1f1f5c;
      --dsw-alias-button-tool-bar-fill:#54555780;
      --dsw-alias-button-tool-bar-hover:#54555799;
      --dsw-alias-interactive-bg-active:#ffffff24;
      --dsw-alias-interactive-bg-hover-accent:#ffffff3d;
      --dsw-alias-interactive-bg-hover-danger:#f25a5a26;
      --dsw-alias-interactive-bg-hover-solid:var(--dsw-static-neutral-bluish-800);
      --dsw-alias-interactive-bg-hover:#ffffff14;
      --dsw-alias-label-caption:var(--dsw-static-neutral-bluish-600);
      --dsw-alias-label-dimmed:var(--dsw-static-neutral-bluish-750);
      --dsw-alias-label-primary-bluish:var(--dsw-static-neutral-bluish-50);
      --dsw-alias-label-primary-dimmed:var(--dsw-static-neutral-bluish-100);
      --dsw-alias-label-primary-foreground:var(--dsw-static-neutral-bluish-1000);
      --dsw-alias-label-primary-inverted:var(--dsw-static-neutral-bluish-800);
      --dsw-alias-label-primary:var(--dsw-static-neutral-bluish-50);
      --dsw-alias-label-secondary:var(--dsw-static-neutral-bluish-300);
      --dsw-alias-label-tertiary:var(--dsw-static-neutral-bluish-400);
      --dsw-alias-link:var(--dsw-static-deepseek-400);
      --dsw-alias-markdown-citation:var(--dsw-static-neutral-bluish-800);
      --dsw-alias-markdown-code-block-banner:var(--dsw-static-neutral-bluish-850);
      --dsw-alias-markdown-code-block:var(--dsw-static-neutral-bluish-900);
      --dsw-alias-markdown-code-segment-selected:var(--dsw-static-neutral-bluish-800);
      --dsw-alias-markdown-code-segment-unselected:var(--dsw-static-neutral-bluish-900);
      --dsw-alias-markdown-inline-code:var(--dsw-static-neutral-800);
      --dsw-alias-markdown-placeholder:var(--dsw-static-neutral-bluish-850);
      --dsw-alias-markdown-tag:var(--dsw-static-neutral-bluish-850);
      --dsw-alias-scrollbar-bg-l1:var(--dsw-static-neutral-700);
      --dsw-alias-scrollbar-bg-l2:var(--dsw-static-neutral-600);
      --dsw-alias-scrollbar-hover-l1:var(--dsw-static-neutral-600);
      --dsw-alias-scrollbar-hover-l2:var(--dsw-static-neutral-550);
      --dsw-alias-state-business-primary:var(--dsw-static-deepseek-400);
      --dsw-alias-state-business-tertiary:var(--dsw-static-deepseek-800);
      --dsw-alias-state-error-primary:var(--dsw-static-red-400);
      --dsw-alias-state-error-secondary:var(--dsw-static-red-400);
      --dsw-alias-state-success-primary:var(--dsw-static-green-500);
      --dsw-alias-state-success-secondary:var(--dsw-static-green-400);
      --dsw-alias-state-success-tertiary:var(--dsw-static-green-900);
      --dsw-alias-state-warn-label:var(--dsw-static-amber-600);
      --dsw-alias-state-warn-primary:var(--dsw-static-amber-500);
      --dsw-alias-state-warn-secondary:var(--dsw-static-amber-400);
      --dsw-alias-state-warn-tertiary:var(--dsw-static-amber-900);
      --dsw-alias-toast-bg:var(--dsw-static-neutral-bluish-750);
      --dsw-alias-tooltip-bg:var(--dsw-static-neutral-bluish-750);
      --dsw-specific-bubble-highlight:var(--dsw-static-neutral-bluish-750);
      --dsw-specific-bubble:var(--dsw-static-neutral-bluish-850);
      --dsw-specific-input-major:var(--dsw-static-neutral-bluish-850);
      --dsw-specific-login-input:var(--dsw-static-neutral-bluish-900);
      --dsw-specific-menu:var(--dsw-alias-bg-layer-3);
      --dsw-specific-selector:var(--dsw-static-neutral-bluish-800);
      --dsw-specific-sidebar-fill:var(--dsw-static-neutral-bluish-900);
      --dsw-specific-sidebar-nav-item-active-accent:var(--dsw-static-neutral-bluish-800);
      --dsw-specific-sidebar-nav-item-active:var(--dsw-static-neutral-bluish-750);
      --dsw-specific-sidebar-nav-item-hover:var(--dsw-static-neutral-bluish-850);
      --dsw-specific-tip:var(--dsw-static-neutral-bluish-800);
    }
    :root{
      --dsw-font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Helvetica, Arial, sans-serif;
      --ds-font-family-code:"SF Mono", "JetBrains Mono", "Fira Code", Consolas, "Liberation Mono", Menlo, Courier, "PingFang SC", "Microsoft YaHei";
      --ds-ease-in-out:cubic-bezier(.4, 0, .2, 1);
      --ds-transition-duration:.2s;
      --ds-transition-duration-fast:.1s;
      --ds-transition-duration-slow:.3s;
    }
    :root{
      --dsh-scrollbar-thumb:var(--dsw-alias-scrollbar-bg-l1);
      --dsh-scrollbar-thumb-hover:var(--dsw-alias-scrollbar-hover-l1);
      --dsh-scrollbar-width:8px;
    }
    @supports not selector(::-webkit-scrollbar){
      body,body *{
        scrollbar-width:thin;
        scrollbar-color:var(--dsh-scrollbar-thumb) transparent;
      }
    }
    ::-webkit-scrollbar{
      width:8px;
      height:8px;
    }
    ::-webkit-scrollbar-track{
      background:0 0;
    }
    ::-webkit-scrollbar-thumb{
      background:var(--dsh-scrollbar-thumb);
      border-radius:4px;
    }
    ::-webkit-scrollbar-thumb:hover{
      background:var(--dsh-scrollbar-thumb-hover);
    }
    ::-webkit-scrollbar-corner{
      background:0 0;
    }
    @supports (corner-shape:superellipse(1.5)){
      :root{
        --dsw-corner-shape:superellipse(1.5);
      }
      *,:before,:after{
        corner-shape:var(--dsw-corner-shape);
      }
    }
    '''

#: 我们自己的组件样式。只用令牌，不写色值。
APP_CSS = '''
    /* ------------------------------------------------------------ 骨架 */
    *{box-sizing:border-box}
    body{
      margin:0;
      background:var(--dsw-alias-bg-base);
      color:var(--dsw-alias-label-primary);
      font-family:var(--dsw-font-family);
      font-size:14px;
      line-height:1.6;
      transition:background var(--ds-transition-duration) var(--ds-ease-in-out),
                 color var(--ds-transition-duration) var(--ds-ease-in-out);
    }
    a{color:var(--dsw-alias-link);text-decoration:none}
    a:hover{text-decoration:underline}
    .top{
      position:sticky;top:0;z-index:2;
      background:var(--dsw-alias-bg-layer-1);
      border-bottom:1px solid var(--dsw-alias-border-l1);
      padding:12px 20px;
    }
    .brand{font-weight:600}
    .top .sub{color:var(--dsw-alias-label-secondary);font-size:12px;margin-top:2px}
    .wrap{max-width:980px;margin:0 auto;padding:20px 16px 64px}
    .stack{display:flex;flex-direction:column;gap:12px}
    .cols{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}
    .col-main{flex:1 1 520px;min-width:320px}
    .col-side{flex:0 1 320px;min-width:260px}
    .sec-title{font-size:16px;font-weight:600;margin:22px 0 10px}
    .muted{color:var(--dsw-alias-label-secondary)}
    .caption{
      color:var(--dsw-alias-label-caption);
      font-size:12px;
      letter-spacing:.02em;
      text-transform:uppercase;
    }
    .mono{font-family:var(--ds-font-family-code);font-size:12px}
    .note{
      color:var(--dsw-alias-label-secondary);
      background:var(--dsw-alias-bg-layer-2);
      border:1px solid var(--dsw-alias-border-l1);
      border-radius:10px;padding:8px 10px;font-size:12px;
    }
    .problem{
      color:var(--dsw-alias-state-error-primary);
      border-color:var(--dsw-alias-state-error-primary);
      background:var(--dsw-alias-bg-layer-2);
    }

    /* ------------------------------------------------------------ 卡片 */
    .card{
      background:var(--dsw-alias-bg-layer-1);
      border:1px solid var(--dsw-alias-border-l1);
      border-radius:12px;
      padding:14px 16px;
      transition:background var(--ds-transition-duration) var(--ds-ease-in-out),
                 border-color var(--ds-transition-duration) var(--ds-ease-in-out);
    }
    .card:hover{background:var(--dsw-alias-interactive-bg-hover)}
    .card-ask{border-left:2px solid var(--dsw-alias-state-warn-primary)}
    .card-head{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
    .card-head .spacer{flex:1 1 auto}
    .title{font-size:15px;font-weight:600}
    .question{white-space:pre-wrap;margin:8px 0 10px}
    .opts{display:flex;flex-direction:column;gap:6px;margin:0 0 10px}
    .opt{
      display:flex;gap:8px;align-items:flex-start;
      border:1px solid var(--dsw-alias-border-l1);
      border-radius:10px;padding:8px 10px;
      transition:background var(--ds-transition-duration) var(--ds-ease-in-out);
    }
    .opt:hover{background:var(--dsw-alias-interactive-bg-hover)}
    .opt .label{font-weight:600}
    .opt .desc{color:var(--dsw-alias-label-secondary);font-size:12px}
    .mark{font-weight:400;color:var(--dsw-alias-label-caption);font-size:12px}

    /* ------------------------------------------------------------ 行 */
    .row{
      display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;
      padding:8px 10px;
      border-bottom:1px solid var(--dsw-alias-border-l1);
      transition:background var(--ds-transition-duration) var(--ds-ease-in-out);
    }
    .row:last-child{border-bottom:0}
    .row:hover{background:var(--dsw-alias-interactive-bg-hover)}
    .row .spacer{flex:1 1 auto}
    .readings{color:var(--dsw-alias-label-caption);font-size:12px}
    .kv{display:flex;gap:8px;flex-wrap:wrap}

    /* ------------------------------------------------------------ 徽标 */
    .badge{
      display:inline-block;border-radius:6px;padding:1px 7px;
      font-size:12px;line-height:1.5;white-space:nowrap;
      border:1px solid var(--dsw-alias-border-l1);
    }
    .badge-pass{
      color:var(--dsw-alias-state-success-tertiary);
      background:var(--dsw-alias-state-success-primary);
      border-color:var(--dsw-alias-state-success-secondary);
    }
    .badge-fail{
      color:var(--dsw-alias-label-primary-foreground);
      background:var(--dsw-alias-state-error-primary);
      border-color:var(--dsw-alias-state-error-secondary);
    }
    .badge-unknown{
      color:var(--dsw-alias-state-warn-label);
      background:var(--dsw-alias-state-warn-primary);
      border-color:var(--dsw-alias-state-warn-secondary);
    }
    .badge-pending{
      color:var(--dsw-alias-label-tertiary);
      background:var(--dsw-alias-bg-layer-2);
      border-color:var(--dsw-alias-border-l2);
    }
    .badge-plain{
      color:var(--dsw-alias-label-secondary);
      background:var(--dsw-alias-bg-layer-2);
      border-color:var(--dsw-alias-border-l1);
    }

    /* ------------------------------------------------------------ 表单 */
    form.answer{margin:0;display:flex;flex-direction:column;gap:8px}
    input[type=text],textarea,select{
      width:100%;
      background:var(--dsw-alias-bg-base);
      color:var(--dsw-alias-label-primary);
      border:1px solid var(--dsw-alias-border-l2);
      border-radius:8px;
      padding:7px 9px;
      font-family:inherit;font-size:13px;
    }
    textarea{font-family:var(--ds-font-family-code);min-height:56px;resize:vertical}
    input[type=text]:focus,textarea:focus,select:focus{
      outline:none;border-color:var(--dsw-alias-border-l4);
    }
    .btn{
      display:inline-block;cursor:pointer;
      border-radius:999px;padding:6px 14px;
      font-size:13px;font-family:inherit;
      transition:background var(--ds-transition-duration) var(--ds-ease-in-out),
                 color var(--ds-transition-duration) var(--ds-ease-in-out);
    }
    .btn-primary{
      background:var(--dsw-alias-button-primary-fill);
      color:var(--dsw-alias-label-primary-foreground);
      border:1px solid var(--dsw-alias-button-primary-fill);
    }
    .btn-primary:hover{background:var(--dsw-alias-button-primary-hover)}
    .btn-primary:disabled{
      background:var(--dsw-alias-button-primary-dimmed);
      border-color:var(--dsw-alias-button-primary-dimmed);
    }
    .btn-secondary{
      background:var(--dsw-alias-button-elevated-fill);
      color:var(--dsw-alias-label-primary);
      border:1px solid var(--dsw-alias-border-l2);
    }
    .btn-secondary:hover{background:var(--dsw-alias-interactive-bg-hover)}
    .btn-ghost{
      background:var(--dsw-alias-button-ghost-active-fill);
      color:var(--dsw-alias-label-secondary);
      border:1px solid var(--dsw-alias-button-ghost-active-border);
    }
    .btn-ghost:hover{
      background:var(--dsw-alias-button-ghost-active-hover);
      color:var(--dsw-alias-label-primary);
    }
    .actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}

    /* ------------------------------------------------------------ 代码 / 报告 */
    pre{
      font-family:var(--ds-font-family-code);font-size:12px;
      background:var(--dsw-alias-markdown-code-block);
      border:1px solid var(--dsw-alias-border-l1);
      border-radius:10px;
      padding:12px;
      overflow:auto;max-height:70vh;
      white-space:pre-wrap;word-break:break-word;
      margin:0;
    }
    code{font-family:var(--ds-font-family-code);font-size:12px}
    .clip{
      color:var(--dsw-alias-label-secondary);
      white-space:pre-wrap;word-break:break-word;
      margin:6px 0 0;
    }
'''

#: 两份合起来发给浏览器（一次请求，零外部依赖、零 CDN）。
STYLESHEET = THEME_CSS + APP_CSS
