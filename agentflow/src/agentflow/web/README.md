# src/agentflow/web —— 用户端的样式令牌与两份生成器

> 前端源码在仓库的 `ui/`；**构建产物**落在本目录的 `static/`（入库）。
> 本目录只放"给前端消费的样式令牌 + 把令牌/类型写成文件"的生成器。

## 谁读

改主题、改前端类型、或要重建 `static/` 的人。改页面的人读 `ui/README-DEV.md`。

## 文件

| 文件 | 是什么 | 谁生成 |
|---|---|---|
| `assets.py` | `THEME_CSS`：令牌层的**唯一来源**（逐字照搬 DSH，来源与许可见它自己的 docstring） | 人 |
| `emit_theme.py` | 把 `THEME_CSS` 写成 `ui/src/theme/generated/theme.css` | 生成器 |
| `emit_types.py` | 把 `webui/{state,readers,writes}.type_decls()` 拼成 `ui/src/types.ts` | 生成器 |
| `static/index.html` | SPA 外壳（`__CSRF__` 占位符由服务端换真令牌） | `pnpm -C ui build` |
| `static/assets/index.<hash>.{js,css}` | 打包产物（内容哈希命名 ⇒ 可 `immutable` 缓存） | `pnpm -C ui build` |
| `__init__.py` | 包标记 | 人 |

## 怎么用

```powershell
# 重建产物（在 agentflow/ 下；需要 node + pnpm）
pnpm -C ui install
pnpm -C ui build

# 只重生成两份源文件
python -m agentflow.web.emit_theme
python -m agentflow.web.emit_types

# 新鲜度判据：手改生成物、或改了 ui 没重建 ⇒ 红
python -m pytest -q tests/test_webui_contracts.py tests/test_webui_static.py
```

## 邻居

上游：`ui/`（前端源码）与 `webui/`（类型声明的来源）。下游：`webui/server.py` 把 `static/`
当 SPA 外壳发出去。**`static/` 是生成物**：不要手改；改了 `ui/` 就要重建并提交。

## 已知边界

- 没有 node 的环境里 `pnpm build` 会 `spawn EPERM`（esbuild 起不来）。那不是"通过"：
  发布门里这一步记 `unknown`，产物本身入库所以不影响 `agentflow web`。
- 产物里不许出现真令牌：外壳只放 `__CSRF__`，服务端吐它时才替换。
