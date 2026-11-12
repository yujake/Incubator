/*
 * 错误动作页：单独一页，不与首页挤同一屏。
 *
 * 这一页只做一件事：把 `components/RoleErrors` 那一栏摆在自己的路由上。
 *
 * 为什么不把它留在首页：锚点（`/#role-errors`）不改变 `matchRoute` 读到的路径 ——
 * 它读的是 `window.location.pathname`，锚点不在里面 —— 于是点进去仍然是首页，
 * 两格导航落在同一屏上，必然一模一样。独立成页之后，「错误动作」有自己的路径
 * （`/errors`，登记在 `main.tsx` 的 `ROUTES` 里），首页也不再渲染这一栏。
 *
 * 取数、三态与矩阵画法都在 `RoleErrors` 里：它是一次全量扫描加一个「重新读」按钮
 * （不挂 SSE，理由写在那个文件的头部）。这一页刻意保持薄 —— 它不该有自己的一份
 * 读数，否则两处口径迟早会对不上。
 */
import { RoleErrors } from "../components/RoleErrors";

export function RoleErrorsPage() {
  return <RoleErrors />;
}
