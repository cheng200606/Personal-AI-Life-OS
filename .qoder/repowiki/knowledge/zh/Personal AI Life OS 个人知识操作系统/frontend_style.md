## 1. 采用的方法
- 构建工具：Vite 8 + `@vitejs/plugin-react`，TS/JS 源码经 `tsc -b` 编译后由 Vite 打包。
- UI 运行时：React 19（函数组件 + JSX），**未引入任何可视化 UI 组件库**（没有 Ant Design、MUI、Chakra、shadcn 等依赖）。
- 样式引擎：纯原生 CSS（`.css` 文件），不使用 Sass/Less/Stylus/Tailwind，也没有 design token 文件或设计系统包。所有视觉表现直接写在 CSS 文件中。

## 2. 关键文件
- `web/src/index.css` — 全局根样式：定义 `:root` 字体 (`'DM Sans', 'Segoe UI', sans-serif`)、文本色 `#20221f`、背景 `#f5f6f2`、全局 `box-sizing`、最小宽度 320px、焦点可见轮廓 `#c2d4b6`、选区背景 `#dce8d5` 等基线。
- `web/src/App.css` — 应用主样式表，覆盖布局（sidebar/main/timeline-layout）、侧边栏品牌标识、导航链接、按钮 (`primary`/`secondary`/`danger`/`text-button`)、面板 (`panel`/`hero-panel`)、表单、时间线条目、搜索过滤、组织管理、空状态等全部视图的视觉规则。
- `web/src/desktop.css` — Tauri 桌面壳与浏览器壳共用样式，与 `App.css` 并列注入以适配桌面渲染差异。

## 3. 架构与约定
- **单文件全局样式 + CSS Modules 命名约定**：页面级/组件级样式通过 BEM-style class 名（如 `.sidebar .nav-link.active`、`.timeline-item`、`.search-filter-grid`）组织在同一份 `.css` 中，而非模块化；组件 TSX 通过类名与对应 CSS 关联，没有采用 CSS-in-JS、styled-components、Tailwind utility-first 或原子化 CSS 方案。
- **色板为手工散落的 hex 值**，主要色系是绿色调辅助色（强调色 `#647d59` / `#637c58` / `#74a068` / `#444a40`，辅助背景 `#eaf0e6`/`#edf2e9`，分割线 `#e8ebe4`/`#eff0ed`，次要文本 `#71766e`/`#8b9185`，错误用 `#a84b4a`）。没有集中 token 声明。
- **响应式采用 clamp() + vw 单位 + 固定 sidebar 宽度**：例如标题使用 `clamp(27px, 3vw, 36px)`，正文区 padding 使用 `clamp(24px, 5vw, 76px)`；侧边栏固定 `246px`，主内容 `margin-left: 246px` + `width: calc(100% - 246px)`，不依赖媒体查询栅格。
- **可访问性约定**：聚焦态统一用 `outline: 3px solid #c2d4b6; outline-offset: 2px`，字号使用相对单位，键盘快捷键以 `<kbd>` 标签展示。
- **图标与品牌**：无第三方 icon 库，品牌标志通过 `.brand-mark` 内联网格加文字实现；其他图标直接用 emoji/文本字符 + 小尺寸圆底容器表示。

## 4. 约定与约束
- 本仓库的 Web 前端 **没有任何 CSS 预处理器、框架或组件库依赖**。依赖清单 `web/package.json` 仅列出 React、DOM、Tauri API、Playwright、Vite、oxlint、TypeScript；无任何 `tailwind*`、`@mui/*`、`antd`、`emotion`、`styled-components` 包。
- 视觉规则集中在 `src/App.css` 和 `src/index.css`（以及桌面用的 `desktop.css`），没有按目录拆分组件样式模块，也未发现 `tailwind.config.*`、`postcss.config.js`、`stylelint` 配置文件。
- 主题变量以散落在各处 CSS 中的 `background`/`color` hex 值形式存在，无 `:root { --xxx }` 设计令牌集合——因此换肤或暗色模式目前不存在代码结构支撑（除非手动改写每个 selector）。
- 交互状态（hover/focus/disabled）直接在 CSS 中使用伪选择器表达，没有状态钩子或 CSS 变量派生，构成“硬编码”的样式约定。