## 1. 采用的方法
- 构建工具：Vite 8 + `@vitejs/plugin-react`，TS/JS 源码经 `tsc -b` 编译后由 Vite 打包。
- UI 运行时：React 19（函数组件 + JSX），**未引入任何可视化 UI 组件库**。依赖清单 `web/package.json` 仅列出 React、DOM、Tauri API，无任何 Tailwind、Ant Design、MUI、emotion、styled-components 等样式依赖。
- 样式引擎：纯原生 CSS（`.css` 文件），不使用 Sass/Less/Stylus/Tailwind，也没有 design token 文件或设计系统包。所有视觉表现直接写在普通 CSS 文件中。

## 2. 关键文件
- `web/src/index.css` — 全局根样式：通过 `:root` 定义字体 `'DM Sans', 'Segoe UI', sans-serif`、文本色 `#20221f`、背景 `#f5f6f2`；重置所有元素的 `box-sizing`、设置 body 最小宽度 `320px`；统一焦点可见态 `outline: 3px solid #c2d4b6; outline-offset: 2px` 和选区背景 `#dce8d5`。
- `web/src/App.css` — 应用主样式表：覆盖布局（sidebar/main/timeline-layout）、品牌标识、导航链接、按钮变体 (`primary`/`secondary`/`danger`/`text-button`)、面板 (`panel`/`hero-panel`)、表单控件、时间线条目、搜索过滤网格、组织管理视图、空状态等全部视图的视觉规则。
- `web/src/desktop.css` — Tauri 桌面壳专用样式，与 `App.css` 并列注入以适配桌面渲染差异（与浏览器端共享同一份页面）。

## 3. 架构与约定
- **三文件全局样式，按命名空间而非模块化组织**：入口 `main.tsx` 注入 `index.css`，`App.tsx` 同时注入 `App.css` 与 `desktop.css`。页面级/组件级样式使用 BEM-style class 名（如 `.sidebar .nav-link.active`、`.timeline-item`、`.search-filter-grid`）集中在这些文件中，没有采用 CSS Modules、CSS-in-JS、styled-components、Tailwind utility-first 或原子化方案。
- **色板为手工散落的 hex 值**，主色调为绿色系辅助色（强调色 `#647d59` / `#637c58` / `#74a068` / `#444a40`，辅助背景 `#eaf0e6`/`#edf2e9`，分割线 `#e8ebe4`/`#eff0ed`，次要文本 `#71766e`/`#8b9185`，错误用 `#a84b4a`）。没有集中 token 声明。
- **响应式策略基于 `clamp()` + `vw` 单位 + 固定侧栏**：例如标题字号用 `clamp(27px, 3vw, 36px)`，正文 padding 用 `clamp(24px, 5vw, 76px)`；侧边栏固定 `246px`，主内容区域通过 `margin-left: 246px; width: calc(100% - 246px)` 自适应，不依赖媒体查询栅格系统。
- **可访问性约定**：聚焦态统一走 `button:focus-visible, a:focus-visible, input:focus-visible, textarea:focus-visible` 的粗绿边框；字号使用相对单位；键盘快捷键用 `<kbd>` 标签展示。
- **图标与品牌**：没有第三方 icon 库，品牌标志通过 `.brand-mark` 内联网格加文字实现；其余图标直接用 emoji/文本字符配合小尺寸圆底容器表示。

## 4. 约定与约束
- 本仓库 Web 前端 **没有任何 CSS 预处理器、框架或可视化组件库依赖**。`web/package.json` 仅在 devDependencies 中包含 oxlint 作为 linter，未发现 stylelint、postcss、tailwind.config.* 等配置。
- 视觉规则集中存放在 `src/index.css` 与 `src/App.css`，并按需补充桌面端 `src/desktop.css`；没有按目录拆分组件样式模块，也未发现 SCSS/Less 文件。
- 主题变量以散落各处 CSS 中的 hex 值存在，不存在集中的 `:root { --xxx }` 设计令牌集合——因此换肤或暗色模式目前缺乏代码结构支撑（需要手动改写每个 selector）。
- 交互状态（hover/focus/disabled）直接在 CSS 中使用伪选择器表达，没有通过 CSS 变量派生颜色或阴影，构成“硬编码”的颜色与间距约定。