---
name: CloudBrief Admin Console
description: Visual identity for the CloudBrief 支持副驾 /admin management console. Built on Next.js + Tailwind CSS + lucide-react; this DESIGN.md defines the brand layer and component tokens.
status: final
colors:
  primary: '#2563EB'
  primary-foreground: '#FFFFFF'
  primary-dark: '#3B82F6'
  primary-foreground-dark: '#0F172A'
  accent: '#F59E0B'
  accent-foreground: '#1A1208'
  accent-dark: '#FBC470'
  accent-foreground-dark: '#1A1208'
  success: '#10B981'
  success-foreground: '#FFFFFF'
  warning: '#F59E0B'
  warning-foreground: '#1A1208'
  destructive: '#EF4444'
  destructive-foreground: '#FFFFFF'
  background: '#F8FAFC'
  foreground: '#0F172A'
  card: '#FFFFFF'
  card-foreground: '#0F172A'
  muted: '#F1F5F9'
  muted-foreground: '#64748B'
  border: '#E2E8F0'
  input: '#E2E8F0'
  ring: '#2563EB'
  background-dark: '#0F172A'
  foreground-dark: '#F8FAFC'
  card-dark: '#1E293B'
  card-foreground-dark: '#F8FAFC'
  muted-dark: '#334155'
  muted-foreground-dark: '#94A3B8'
  border-dark: '#334155'
  input-dark: '#334155'
typography:
  display:
    fontFamily: 'Inter, system-ui, sans-serif'
    fontSize: '28px'
    fontWeight: '600'
    lineHeight: '1.25'
    letterSpacing: '-0.02em'
  display-sm:
    fontFamily: 'Inter, system-ui, sans-serif'
    fontSize: '20px'
    fontWeight: '600'
    lineHeight: '1.3'
    letterSpacing: '-0.01em'
  body:
    fontFamily: 'Inter, system-ui, sans-serif'
    fontSize: '14px'
    fontWeight: '400'
    lineHeight: '1.5'
  label:
    fontFamily: 'Inter, system-ui, sans-serif'
    fontSize: '12px'
    fontWeight: '500'
    lineHeight: '1.4'
    letterSpacing: '0.01em'
  code:
    fontFamily: 'JetBrains Mono, ui-monospace, monospace'
    fontSize: '12px'
    fontWeight: '400'
    lineHeight: '1.5'
rounded:
  sm: '4px'
  md: '6px'
  lg: '8px'
  xl: '12px'
  full: '9999px'
spacing:
  xs: '4px'
  sm: '8px'
  md: '16px'
  lg: '24px'
  xl: '32px'
  2xl: '48px'
components:
  button-primary:
    background: '{colors.primary}'
    foreground: '{colors.primary-foreground}'
    radius: '{rounded.md}'
    padding: '8px 16px'
    font: '{typography.label}'
  button-secondary:
    background: '{colors.muted}'
    foreground: '{colors.foreground}'
    radius: '{rounded.md}'
    border: '1px solid {colors.border}'
  button-ghost:
    background: 'transparent'
    foreground: '{colors.muted-foreground}'
    hover-background: '{colors.muted}'
  sidebar:
    width: '240px'
    background: '{colors.card}'
    border-right: '1px solid {colors.border}'
    active-background: '{colors.muted}'
    active-foreground: '{colors.primary}'
  topbar:
    height: '56px'
    background: '{colors.card}'
    border-bottom: '1px solid {colors.border}'
  card:
    background: '{colors.card}'
    foreground: '{colors.card-foreground}'
    border: '1px solid {colors.border}'
    radius: '{rounded.lg}'
    shadow: '0 1px 3px rgba(0,0,0,0.05)'
  table:
    header-background: '{colors.muted}'
    header-foreground: '{colors.muted-foreground}'
    row-hover: '{colors.muted}'
    border: '1px solid {colors.border}'
  status-badge:
    radius: '{rounded.full}'
    padding: '2px 10px'
    font: '{typography.label}'
  toast:
    background: '{colors.card}'
    foreground: '{colors.foreground}'
    border: '1px solid {colors.border}'
    radius: '{rounded.lg}'
    shadow: '0 4px 12px rgba(0,0,0,0.1)'
---

## Brand & Style

CloudBrief 支持副驾是一个面向内部技术支持人员的 Enterprise RAG 问答系统。管理后台的气质是**专业、可信、工具感强**——它不是一个消费级产品，而是支持人员和管理员每天依赖的生产力界面。

品牌表达遵循以下原则：
- **克制**：颜色少、层次清晰，信息密度高但不拥挤。
- **可信**：蓝色作为主色传递稳定与专业；琥珀色仅用于警告和"需关注"状态。
- **高效**：左侧固定导航、右侧内容区、表格为主的数据展示、明确的操作反馈。
- **中性**：不追求个性化插图或庆祝动画；空状态和提示以文字和图标为主。

本设计基于 Tailwind CSS 默认 token 体系，定义品牌层覆盖。未显式覆盖的 token 使用 Tailwind 默认值。

## Colors

### 品牌色

- **Primary Blue (`#2563EB`)**：主交互色。用于主按钮、活动导航项、链接、焦点环、关键数据高亮。
- **Primary Dark (`#3B82F6`)**：深色模式下的主色。

### 语义色

- **Success Green (`#10B981`)**：完成、成功、在线状态。
- **Warning Amber (`#F59E0B`)**：警告、时效提示、需要注意的状态。
- **Destructive Red (`#EF4444`)**：删除、失败、错误。

### 中性色

- **Background (`#F8FAFC`)**：页面背景，浅灰让白色卡片浮出。
- **Card (`#FFFFFF`)**：卡片、侧边栏、顶部栏背景。
- **Muted (`#F1F5F9`)**：表头、hover 背景、次级区域。
- **Border (`#E2E8F0`)**：分隔线、输入框边框、卡片边框。
- **Foreground (`#0F172A`)**：主文字。
- **Muted Foreground (`#64748B`)**：次级文字、描述、时间戳。

深色模式映射与浅色模式对应，确保对比度满足 WCAG 2.2 AA。

## Typography

全部使用 **Inter**（无衬线）作为界面字体，`JetBrains Mono` 用于代码/JSON/文件路径等等宽场景。

- **Display (28px, 600)**：页面标题，如"Dashboard"、"用户管理"。
- **Display-sm (20px, 600)**：卡片标题、区段标题、对话框标题。
- **Body (14px, 400)**：正文、表格内容、表单标签。
- **Label (12px, 500)**：按钮文字、徽章、小标题、标签。
- **Code (12px, 400)**：任务 ID、文件路径、JSON 片段。

## Layout & Spacing

采用**左侧固定侧边栏 + 右侧滚动内容区**的经典管理后台布局。

- 侧边栏宽度：`240px`
- 顶部栏高度：`56px`
- 内容区内边距：`24px`
- 卡片内边距：`16px` 或 `24px`
- 栅格：内容区使用 CSS Grid / Flexbox；列表页使用单列或双列卡片布局。

间距基于 4px 倍数：`4, 8, 12, 16, 20, 24, 32, 48`。

内容区最大宽度不做硬性限制（管理后台需要宽表格），但关键表单和详情页建议 `max-w-2xl` 以保持可读性。

## Elevation & Depth

- 侧边栏和顶部栏：无阴影，仅靠背景色和边框与内容区分。
- 卡片：轻微阴影 `0 1px 3px rgba(0,0,0,0.05)`，配合边框。
- 悬浮操作（Dropdown、Popover、Toast）：`0 4px 12px rgba(0,0,0,0.1)`。
- 模态对话框：带遮罩 `bg-black/50`，对话框本身带阴影。

## Shapes

- 按钮、卡片、输入框：`rounded-md` (6px)
- 大卡片、面板：`rounded-lg` (8px)
- 徽章、标签、头像：`rounded-full`
- 表格单元格：直角，仅表格整体使用 `rounded-lg`

## Components

### Button

- **Primary**：`{colors.primary}` 填充，白色文字，用于主操作（保存、创建、重建索引）。
- **Secondary**：浅灰填充，深色文字，用于次要操作（取消、返回）。
- **Ghost**：透明背景，悬停显示浅灰背景，用于工具栏、图标按钮。
- **Destructive**：红色填充，用于删除操作，需配合二次确认。

### Sidebar

- 固定左侧，宽度 `240px`。
- 菜单项图标 + 文字，活动项左侧显示 `2px` 主色竖线，背景变为 `{colors.muted}`。
- 底部显示当前用户头像/名称和"退出登录"。
- 根据角色动态显示菜单：普通 `user` 不显示"用户管理"、"系统设置"。

### Topbar

- 顶部固定，显示当前页面标题、面包屑（可选）、用户头像下拉菜单。
- 移动端替代侧边栏，显示汉堡菜单按钮。

### Card

- 白色背景、浅边框、圆角 `8px`。
- 用于 Dashboard 指标、设置表单、详情页区块。
- 卡片标题使用 `display-sm`，副标题使用 `muted-foreground` body 文字。

### Table

- 表头浅灰背景，文字使用 `muted-foreground`。
- 行 hover 变浅灰。
- 操作列使用图标按钮（编辑、删除），删除用红色。
- 支持分页器，位于表格右下角。

### Status Badge

- 胶囊形状小标签。
- `success`（已完成/在线）、`warning`（运行中/待注意）、`destructive`（失败）、`default`（其他）。

### Toast

- 右上角弹出，4 秒后自动消失。
- 成功（绿）、错误（红）、警告（琥珀）、信息（蓝）。
- 包含标题和简短描述。

### Form

- 输入框：浅边框，聚焦时 `{colors.ring}` 环。
- 标签使用 `label` 样式，必填项标注红色星号。
- 错误提示使用 `destructive` 颜色小号文字。

## Do's and Don'ts

| Do | Don't |
|---|---|
| 使用 `{colors.primary}` 作为唯一主品牌色 | 在品牌层之外引入额外强调色 |
| 用 `{colors.accent}` 仅表示"警告/需关注" | 用琥珀色作为装饰或成功状态 |
| 保持高信息密度，管理后台以效率为先 | 使用大间距、空泛的视觉留白 |
| 所有删除操作都需要二次确认 | 直接删除，没有确认对话框 |
| 表格行 hover 提供视觉反馈 | 让表格看起来像静态文本 |
| 深色模式保持与浅色模式一致的语义映射 | 在深色模式下使用高饱和颜色 |
| 图标统一使用 lucide-react | 混用多个图标库风格 |
