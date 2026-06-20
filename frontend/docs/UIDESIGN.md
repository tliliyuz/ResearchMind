---
---

# ResearchMind UI 样式规范

| 属性 | 值 |
|:---|:---|
| 文档版本 | v1.0 |
| 最后更新 | 2026-06-20 |

> 用途: 面向 Agent 的 CSS 变量与组件样式参考。所有样式基于 Vue 3 + Element Plus 项目。Design Token 提取自 `ai_studio_code.html` 静态原型，前缀统一为 `--rm-*`。

---

## 1. CSS 变量定义（完整 Design Token）

以下变量必须放在项目全局样式文件的 `:root` 中：

```css
:root {
    /* ===== 品牌色（深泰尔绿系） ===== */
    --rm-primary: #0F766E;                /* teal-700 — 主按钮、选中态、链接 */
    --rm-primary-hover: #0D6D63;          /* teal-800 — hover 加深 */
    --rm-primary-dark: #115E59;           /* teal-800 → 最深色 */
    --rm-primary-light: #F0FDFA;          /* teal-50 — 浅色背景、选中卡片背景 */
    --rm-primary-border: rgba(15, 118, 110, 0.2);   /* 20% 透明度边框 */

    /* ===== 辅助品牌色（科技蓝） ===== */
    --rm-secondary: #2563EB;              /* blue-600 — 运行态、当前阶段高亮 */
    --rm-secondary-light: #EFF6FF;        /* blue-50 — 蓝色浅底 */

    /* ===== 语义色 ===== */
    --rm-success: #0D9488;                /* teal-600 — 完成标记 */
    --rm-success-light: #ECFDF5;          /* teal-50 同色系 */
    --rm-warning: #F59E0B;                /* amber-500 — checkpoint 提示 */
    --rm-warning-light: #FFFBEB;          /* amber-50 */
    --rm-danger: #E11D48;                 /* rose-600 — 失败/危险操作 */
    --rm-danger-light: #FEF2F2;           /* rose-50 */
    --rm-danger-border: rgba(225, 29, 72, 0.2);

    /* ===== 证据高亮标记（Report 内引用片段） ===== */
    --rm-evidence-highlight-bg: #CCFBF1;  /* teal-100 — 证据片段背景 */
    --rm-evidence-highlight-text: #0F766E;
    --rm-evidence-highlight-border: #99F6E4;  /* teal-200 */
    --rm-evidence-flash-bg: #FEF3C7;      /* amber-100 — 点击联动闪烁（右侧证据卡片高亮） */
    --rm-evidence-flash-border: #F59E0B;   /* amber-500 */

    /* ===== 中性色（黑白灰体系 — 偏冷 slate 系） ===== */
    --rm-bg-page: #F8FAFC;                /* slate-50 — 页面底色 */
    --rm-bg-sidebar: #0F172A;             /* slate-900 — 侧边栏深色背景 */
    --rm-bg-sidebar-hover: rgba(30, 41, 59, 0.5);  /* slate-800/50 — 侧边栏项 hover */
    --rm-bg-sidebar-active: #1E293B;      /* slate-800 — 侧边栏项激活 */
    --rm-bg-card: #FFFFFF;
    --rm-bg-input: #F8FAFC;               /* slate-50 */
    --rm-bg-elevated: #F1F5F9;            /* slate-100 — 次级底色 */
    --rm-bg-code: #0F172A;                /* slate-900 — 代码块/终端背景 */
    --rm-bg-dark-card: #020617;           /* slate-950 — 运行态顶部栏/终端面板 */
    --rm-text-primary: #0F172A;           /* slate-900 */
    --rm-text-secondary: #475569;         /* slate-600 */
    --rm-text-tertiary: #94A3B8;          /* slate-400 */
    --rm-text-inverse: #F8FAFC;           /* slate-50 — 深色背景上文字 */
    --rm-text-inverse-secondary: #CBD5E1; /* slate-300 — 深色背景上次级文字 */
    --rm-text-inverse-dim: #64748B;       /* slate-500 — 深色背景上辅助文字 */
    --rm-border: #E2E8F0;                 /* slate-200 */
    --rm-border-light: #F1F5F9;           /* slate-100 */
    --rm-border-dark: #1E293B;            /* slate-800 — 深色背景边框 */
    --rm-border-darker: #334155;          /* slate-700 */

    /* ===== 字体族 ===== */
    --rm-font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI",
                      Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif;
    --rm-font-mono: "SF Mono", "Fira Code", "JetBrains Mono", "Cascadia Code",
                    "Consolas", "Monaco", monospace;

    /* ===== 字号（Tailwind 参照值 + 高频定制） ===== */
    --rm-text-3xl: 30px;                  /* text-3xl — 页面大标题 */
    --rm-text-2xl: 24px;                  /* text-2xl — 创建态标题 */
    --rm-text-xl: 20px;                   /* text-xl */
    --rm-text-lg: 18px;                   /* text-lg — 报告章节标题 */
    --rm-text-base: 16px;                 /* text-base */
    --rm-text-sm: 14px;                   /* text-sm — 正文、表单标签 */
    --rm-text-xs: 12px;                   /* text-xs — 辅助信息、侧边栏项、卡片描述 */
    --rm-text-2xs: 11px;                  /* text-[11px] — 卡内元信息 */
    --rm-text-3xs: 10px;                  /* text-[10px] — 标签、徽标、分类标题 */

    /* ===== 字重 ===== */
    --rm-weight-bold: 700;
    --rm-weight-semibold: 600;
    --rm-weight-medium: 500;
    --rm-weight-normal: 400;
    --rm-weight-light: 300;

    /* ===== 行高 ===== */
    --rm-leading-title: 1.2;
    --rm-leading-body: 1.5;
    --rm-leading-relaxed: 1.625;

    /* ===== 间距（4px 基准，对齐 Tailwind 默认比例） ===== */
    --rm-space-1: 4px;
    --rm-space-1_5: 6px;
    --rm-space-2: 8px;
    --rm-space-2_5: 10px;
    --rm-space-3: 12px;
    --rm-space-3_5: 14px;
    --rm-space-4: 16px;
    --rm-space-5: 20px;
    --rm-space-6: 24px;
    --rm-space-8: 32px;
    --rm-space-10: 40px;
    --rm-space-12: 48px;

    /* ===== 圆角 ===== */
    --rm-radius-xs: 4px;                  /* rounded — 小标签、徽标 */
    --rm-radius-sm: 6px;                  /* rounded-md — 按钮、菜单项 */
    --rm-radius-md: 8px;                  /* rounded-lg — 卡片、输入框 */
    --rm-radius-lg: 12px;                 /* rounded-xl — 模态框、大卡片 */
    --rm-radius-xl: 16px;                 /* rounded-2xl — 仪表盘面板 */
    --rm-radius-full: 50%;

    /* ===== 阴影 ===== */
    --rm-shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
    --rm-shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1);
    --rm-shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1);
    --rm-shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
    --rm-shadow-2xl: 0 25px 50px -12px rgba(0, 0, 0, 0.25);  /* 模态框、终端面板 */
    --rm-shadow-inner: inset 0 2px 4px rgba(0, 0, 0, 0.05);

    /* ===== 布局 ===== */
    --rm-sidebar-width: 256px;            /* w-64 — 全展开侧边栏 */
    --rm-sidebar-width-collapsed: 64px;   /* w-16 — 收起侧边栏 */
    --rm-header-height: 56px;
    --rm-content-max-width: 672px;        /* max-w-2xl — 创建表单最大宽 */
    --rm-report-max-width: 768px;         /* max-w-3xl — 报告正文最大宽 */
    --rm-evidence-panel-width: 320px;     /* w-80 — 证据图谱面板宽 */
    --rm-section-nav-width: 240px;        /* w-60 — 章节目录宽 */
    --rm-input-height: 40px;

    /* ===== 过渡 ===== */
    --rm-transition-fast: 0.15s ease;
    --rm-transition-normal: 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    --rm-transition-slow: 0.3s ease;

    /* ===== 代码块 / 终端 ===== */
    --rm-bg-terminal: #0F172A;            /* slate-900 — 终端背景 */
    --rm-bg-terminal-header: #1E293B;     /* slate-800 — 终端顶栏 */
    --rm-text-code: #CBD5E1;              /* slate-300 — 终端正文 */
    --rm-text-code-dim: #64748B;          /* slate-500 — 终端次要信息 */
    --rm-code-copy-btn-bg: rgba(255, 255, 255, 0.1);
    --rm-code-copy-btn-hover-bg: rgba(255, 255, 255, 0.2);

    /* ===== 其他 ===== */
    --rm-welcome-icon-size: 56px;
    --rm-logo-size: 32px;
    --rm-avatar-size: 32px;
}
```

### Element Plus 主题覆盖

```css
:root {
    --el-color-primary: #0F766E;
    --el-color-primary-light-3: #14B8A6;
    --el-color-primary-light-5: #5EEAD4;
    --el-color-primary-light-7: #99F6E4;
    --el-color-primary-light-8: #CCFBF1;
    --el-color-primary-light-9: #F0FDFA;
    --el-border-radius-base: 8px;
    --el-font-size-base: 14px;
    --el-font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI",
                      Roboto, "Helvetica Neue", Arial, sans-serif;
    --el-bg-color: #FFFFFF;
    --el-bg-color-page: #F8FAFC;
    --el-text-color-primary: #0F172A;
    --el-text-color-regular: #475569;
    --el-text-color-secondary: #94A3B8;
    --el-border-color: #E2E8F0;
    --el-border-color-light: #F1F5F9;
    --el-fill-color-blank: #FFFFFF;
    --el-fill-color-light: #F8FAFC;
}
```

---

## 2. 全局样式

```css
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: var(--rm-font-family);
    background: var(--rm-bg-page);
    color: var(--rm-text-primary);
    height: 100vh;
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: #CBD5E1;                   /* slate-300 */
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: #94A3B8;                   /* slate-400 */
}
```

---

## 3. 布局规范

### 3.1 根布局

```css
#app {
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}
```

### 3.2 侧边栏（深色）

ResearchMind 侧边栏为深色背景（slate-900），与 DocMind 浅色侧边栏方案不同。

```css
.sidebar {
    width: var(--rm-sidebar-width);                /* 256px */
    background: var(--rm-bg-sidebar);              /* #0F172A */
    color: var(--rm-text-inverse-secondary);       /* #CBD5E1 */
    border-right: 1px solid var(--rm-border-dark);
    display: flex;
    flex-direction: column;
    z-index: 40;
    transition: width var(--rm-transition-normal);
    overflow-x: hidden;
    flex-shrink: 0;
    position: relative;
}
```

**展开态** (默认)：
- 宽度：`var(--rm-sidebar-width)` (256px)
- 显示 Logo 区块（图标 + 产品名 + 副标题）、新建研究按钮、历史任务列表、用户栏
- 历史任务标题显示"历史任务"分组标签
- 侧边栏折叠按钮位于右上角外侧（`right: -12px`），圆形 `w-6 h-6`，`bg-slate-800 border-slate-700`

**收起态** (`.sidebar.collapsed`)：
- 宽度：`var(--rm-sidebar-width-collapsed)` (64px)
- 仅显示：脑图标 Logo（居中）、新建按钮（仅 `+` 图标）、历史任务状态圆点、用户头像（居中）
- 隐藏：所有文字标签、分组标题、产品名/副标题、退出按钮
- 历史任务项仅显示状态图标（`fa-circle-check` / `fa-triangle-exclamation`），hover 显示 tooltip
- 折叠按钮图标变为 `fa-chevron-right`

### 3.3 主内容区

```css
.main-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    background: var(--rm-bg-card);
    overflow: hidden;
}

.page-header {
    height: var(--rm-header-height);               /* 56px */
    background: var(--rm-bg-card);
    border-bottom: 1px solid var(--rm-border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--rm-space-6);                  /* 24px */
    z-index: 5;
    flex-shrink: 0;
}

.content-scroll {
    flex: 1;
    overflow-y: auto;
    padding: var(--rm-space-6) var(--rm-space-8);  /* 24px 32px */
}
```

---

## 4. 组件样式规范

### 4.1 按钮 (Button)

#### 主按钮 (.btn-primary)

对应静态页面 `bg-teal-700 hover:bg-teal-600` 样式。

```css
.btn-primary {
    height: 38px;
    padding: 0 18px;
    background: var(--rm-primary);
    color: white;
    border: none;
    border-radius: var(--rm-radius-sm);            /* 6px */
    font-size: var(--rm-text-sm);                  /* 14px */
    font-weight: var(--rm-weight-semibold);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: var(--rm-space-2);                        /* 8px */
    transition: all var(--rm-transition-normal);
}

.btn-primary:hover:not(:disabled) {
    background: var(--rm-primary-hover);
    box-shadow: var(--rm-shadow-sm);
}

.btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
```

#### 提交按钮 (.submit-btn)

对应创建态「开始深度系统研究」按钮：`w-full bg-teal-700 hover:bg-teal-600 rounded-xl shadow`。

```css
.submit-btn {
    width: 100%;
    height: 48px;
    background: var(--rm-primary);
    color: white;
    border: none;
    border-radius: var(--rm-radius-lg);            /* 12px */
    font-size: var(--rm-text-sm);                  /* 14px */
    font-weight: var(--rm-weight-semibold);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--rm-space-2);
    transition: all var(--rm-transition-normal);
    box-shadow: var(--rm-shadow-md);
}

.submit-btn:hover:not(:disabled) {
    background: var(--rm-primary-hover);
}

.submit-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
```

#### 幽灵按钮 (.ghost-btn)

```css
.ghost-btn {
    height: 32px;
    padding: 0 14px;
    background: var(--rm-primary-light);
    color: var(--rm-primary);
    border: none;
    border-radius: var(--rm-radius-sm);
    font-size: var(--rm-text-xs);
    font-weight: var(--rm-weight-semibold);
    cursor: pointer;
    transition: background var(--rm-transition-fast);
}

.ghost-btn:hover {
    background: #CCFBF1;                           /* teal-100 */
}
```

#### 危险操作按钮 (.danger-btn)

对应运行态「取消研究」按钮：`bg-rose-950/40 border border-rose-800/60 text-rose-200`。

```css
.danger-btn {
    height: 32px;
    padding: 0 12px;
    background: rgba(159, 18, 57, 0.1);           /* rose-950/40 */
    color: #FECDD3;                                /* rose-200 */
    border: 1px solid rgba(136, 19, 55, 0.6);      /* rose-800/60 */
    border-radius: var(--rm-radius-md);            /* 8px */
    font-size: var(--rm-text-xs);                  /* 12px */
    font-weight: var(--rm-weight-medium);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: var(--rm-space-1);
    transition: all var(--rm-transition-fast);
    flex-shrink: 0;
}

.danger-btn:hover {
    background: rgba(136, 19, 55, 0.3);            /* rose-900/50 */
}
```

#### 恢复按钮 (.resume-btn)

对应失败态「断点续跑」按钮：`bg-teal-700 hover:bg-teal-600 shadow`。

同 `.submit-btn` 样式，高度可略低（42px）。

---

### 4.2 输入框 (Input)

#### 标准输入框 (.form-input)

```css
.form-input {
    width: 100%;
    height: 44px;
    padding: 0 14px;
    border: 1px solid var(--rm-border);
    border-radius: var(--rm-radius-lg);            /* 12px */
    font-size: var(--rm-text-sm);
    color: var(--rm-text-primary);
    background: var(--rm-bg-card);
    outline: none;
    transition: all var(--rm-transition-normal);
}

.form-input:focus {
    border-color: var(--rm-primary);
    box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.15);
}

.form-input::placeholder {
    color: var(--rm-text-tertiary);
}
```

#### 文本域 (.form-textarea)

对应创建态研究主题输入：`border-slate-200 focus:border-teal-500 focus:ring-1 focus:ring-teal-500 rounded-xl`。

```css
.form-textarea {
    width: 100%;
    padding: var(--rm-space-3);                    /* 12px */
    border: 1px solid var(--rm-border);
    border-radius: var(--rm-radius-lg);            /* 12px */
    font-size: var(--rm-text-sm);
    color: var(--rm-text-primary);
    background: var(--rm-bg-card);
    outline: none;
    resize: none;
    transition: all var(--rm-transition-normal);
    font-family: var(--rm-font-family);
    line-height: var(--rm-leading-body);
}

.form-textarea:focus {
    border-color: var(--rm-primary);
    box-shadow: 0 0 0 1px var(--rm-primary);
}
```

#### Element Plus 搜索框

```css
.search-box-container {
    width: 280px;
}
```

---

### 4.3 卡片 (Card)

#### 标准白色卡片

```css
.card {
    background: var(--rm-bg-card);
    border: 1px solid var(--rm-border);
    border-radius: var(--rm-radius-lg);            /* 12px */
    padding: var(--rm-space-5);                    /* 20px */
    transition: all var(--rm-transition-normal);
}

.card:hover {
    border-color: var(--rm-primary);
    box-shadow: var(--rm-shadow-md);
}
```

#### 可点选研究类型卡片

对应创建态三种研究类型选择卡片。选中态：`border-teal-600 bg-teal-50/40 ring-1 ring-teal-600`。

```css
.type-card {
    border: 1px solid var(--rm-border);
    border-radius: var(--rm-radius-lg);
    padding: var(--rm-space-4);
    cursor: pointer;
    transition: all var(--rm-transition-normal);
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 128px;                             /* h-32 */
}

.type-card:hover {
    border-color: #94A3B8;                        /* slate-300 */
}

.type-card.selected {
    border-color: var(--rm-primary);
    background: rgba(15, 118, 110, 0.08);          /* teal-50/40 */
    box-shadow: 0 0 0 1px var(--rm-primary);       /* ring-1 */
}

/* 选中勾标 — 右上角 */
.type-card .check-icon {
    position: absolute;
    top: var(--rm-space-2);
    right: var(--rm-space-2);
    color: var(--rm-primary);
    font-size: var(--rm-text-base);                /* 16px */
}

/* 类型图标 + 标题行 */
.type-card .type-header {
    display: flex;
    align-items: center;
    gap: var(--rm-space-2);
    color: var(--rm-primary);
    margin-bottom: var(--rm-space-1_5);
}
```

#### 快捷示例卡片

对应创建态推荐研究方向卡片：`border-slate-200 hover:border-teal-500/50 hover:bg-teal-50/20`。

```css
.example-card {
    border: 1px solid var(--rm-border);
    border-radius: var(--rm-radius-lg);
    padding: var(--rm-space-3_5);
    cursor: pointer;
    transition: all var(--rm-transition-fast);
    text-align: left;
}

.example-card:hover {
    border-color: rgba(15, 118, 110, 0.3);
    background: rgba(15, 118, 110, 0.05);
}
```

#### 统计卡片

```css
.stat-card {
    background: var(--rm-bg-card);
    border: 1px solid var(--rm-border);
    border-radius: var(--rm-radius-lg);
    padding: var(--rm-space-5);
    display: flex;
    align-items: center;
    gap: var(--rm-space-4);
    transition: box-shadow var(--rm-transition-fast);
}

.stat-card:hover {
    box-shadow: var(--rm-shadow-sm);
}

.stat-icon {
    width: 48px;
    height: 48px;
    border-radius: var(--rm-radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: var(--rm-text-lg);
    flex-shrink: 0;
}

.stat-icon.primary  { background: var(--rm-primary-light); color: var(--rm-primary); }
.stat-icon.success  { background: var(--rm-success-light);  color: var(--rm-success); }
.stat-icon.warning  { background: var(--rm-warning-light);  color: var(--rm-warning); }
.stat-icon.danger   { background: var(--rm-danger-light);   color: var(--rm-danger); }
.stat-icon.info     { background: var(--rm-secondary-light); color: var(--rm-secondary); }

.stat-value {
    font-size: var(--rm-text-xl);
    font-weight: var(--rm-weight-bold);
    color: var(--rm-text-primary);
}

.stat-label {
    font-size: var(--rm-text-xs);
    color: var(--rm-text-secondary);
    margin-top: var(--rm-space-1);
}
```

---

### 4.4 Logo 组件

#### 欢迎页大图标

对应创建态顶部 `bg-teal-50 text-teal-700 rounded-2xl`。

```css
.welcome-icon {
    width: var(--rm-welcome-icon-size);            /* 56px */
    height: var(--rm-welcome-icon-size);
    background: var(--rm-primary-light);
    border-radius: var(--rm-radius-xl);            /* 16px */
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--rm-primary);
    font-size: var(--rm-text-2xl);                 /* 24px */
}
```

#### 侧边栏小 Logo

对应侧边栏 `w-8 h-8 rounded-lg bg-teal-600`。

```css
.sidebar-logo-icon {
    width: var(--rm-logo-size);                    /* 32px */
    height: var(--rm-logo-size);
    background: #0D9488;                           /* teal-600 — 比 --rm-primary 亮一档 */
    border-radius: var(--rm-radius-md);            /* 8px */
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: var(--rm-text-base);                /* 16px */
    flex-shrink: 0;
}
```

#### Logo 文字

```css
.logo-title {
    font-size: var(--rm-text-sm);                  /* 14px */
    font-weight: var(--rm-weight-bold);
    color: white;
    letter-spacing: 0.025em;                       /* tracking-wide */
    white-space: nowrap;
}

.logo-subtitle {
    font-size: var(--rm-text-3xs);                 /* 10px */
    color: var(--rm-text-inverse-dim);             /* #64748B */
}
```

---

### 4.5 侧边栏导航与列表

#### 导航项（历史任务列表项）

对应侧边栏任务项：默认 `text-slate-400 hover:bg-slate-800/50`，激活 `bg-slate-800 text-white`。

```css
.nav-item {
    display: flex;
    align-items: center;
    gap: var(--rm-space-2_5);                      /* 10px */
    padding: var(--rm-space-2) var(--rm-space-3);  /* 8px 12px */
    border-radius: var(--rm-radius-sm);            /* 6px */
    cursor: pointer;
    transition: all var(--rm-transition-fast);
    font-size: var(--rm-text-xs);                  /* 12px */
    color: var(--rm-text-inverse-secondary);
}

.nav-item:hover {
    background: var(--rm-bg-sidebar-hover);
    color: var(--rm-text-inverse);
}

.nav-item.active {
    background: var(--rm-bg-sidebar-active);
    color: white;
}
```

#### 分组标签

```css
.nav-group-label {
    font-size: var(--rm-text-3xs);                 /* 10px */
    font-weight: var(--rm-weight-bold);
    color: var(--rm-text-inverse-dim);             /* #64748B */
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0 var(--rm-space-2);                  /* 0 8px */
}
```

#### 管理后台入口按钮

对应侧边栏底部 `text-amber-500` admin 按钮。

```css
.nav-item.admin-entry {
    color: #F59E0B;                                /* amber-500 */
}

.nav-item.admin-entry:hover {
    background: var(--rm-bg-sidebar-hover);
    color: #FBBF24;                                /* amber-400 */
}
```

---

### 4.6 新建研究按钮（侧边栏）

对应 `bg-teal-700 hover:bg-teal-600 rounded-md` 全宽按钮。

```css
.new-research-btn {
    width: 100%;
    background: var(--rm-primary-hover);           /* teal-800 / #0D6D63 */
    color: white;
    border: none;
    border-radius: var(--rm-radius-sm);            /* 6px */
    padding: var(--rm-space-2) var(--rm-space-3);  /* 8px 12px */
    font-size: var(--rm-text-sm);                  /* 14px */
    font-weight: var(--rm-weight-medium);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--rm-space-2);
    transition: background var(--rm-transition-fast);
}

.new-research-btn:hover {
    background: #0D9488;                           /* teal-600 */
}
```

---

### 4.7 状态标签 (Status Tag)

```css
.status-tag {
    padding: 4px 10px;
    border-radius: var(--rm-radius-xs);
    font-size: var(--rm-text-2xs);
    font-weight: var(--rm-weight-semibold);
    white-space: nowrap;
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

/* 任务状态 — 运行中 */
.status-tag.pending    { background: var(--rm-secondary-light); color: var(--rm-secondary); }
.status-tag.running    { background: var(--rm-secondary-light); color: var(--rm-secondary); }

/* 任务状态 — 终态 */
.status-tag.completed  { background: var(--rm-success-light);  color: var(--rm-success); }
.status-tag.failed     { background: var(--rm-danger-light);   color: var(--rm-danger); }
.status-tag.canceled   { background: var(--rm-bg-elevated);    color: var(--rm-text-secondary); }
```

---

### 4.8 状态指示点 (Status Dot)

用于侧边栏历史任务列表的状态圆点和 Pipeline 阶段节点。

```css
.status-dot {
    width: 8px;
    height: 8px;
    border-radius: var(--rm-radius-full);
    flex-shrink: 0;
}

.status-dot.completed  { background: var(--rm-success); }
.status-dot.running    { background: var(--rm-secondary); }
.status-dot.pending    { background: var(--rm-text-tertiary); }
.status-dot.failed     { background: var(--rm-danger); }
```

---

### 4.9 Pipeline 阶段进度条

对应运行态七阶段节点指示器。每个阶段为圆形节点（`w-8 h-8 rounded-full border-2`）。

> **权威定义**：七阶段名称、图标、SSE 事件映射见 [FRONTEND.md §4.4.2](FRONTEND.md#442-pipeline-阶段进度条)。

| 序号 | 阶段 | 显示名称 | 图标 |
|:---|:---|:---|:---|
| 1 | `planning` | Planning | `fa-brain` |
| 2 | `searching` | Search | `fa-search` |
| 3 | `fetching` | Fetch | `fa-download` |
| 4 | `reranking` | Rerank | `fa-sort-amount-down` |
| 5 | `synthesizing` | Synthesis | `fa-project-diagram` |
| 6 | `building_evidence_graph` | Evidence Graph | `fa-sitemap` |
| 7 | `rendering` | Render | `fa-file-alt` |

```css
/* 阶段节点 */
.phase-node {
    width: 32px;
    height: 32px;
    border-radius: var(--rm-radius-full);
    border: 2px solid;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: var(--rm-text-3xs);                 /* 10px */
    font-weight: var(--rm-weight-bold);
    transition: all 0.3s ease;
position: relative;
    z-index: 10;
}

/* 已完成 */
.phase-node.done {
    background: #0D9488;                           /* teal-600 */
    border-color: #14B8A6;                         /* teal-500 */
    color: white;
}

/* 当前进行中 */
.phase-node.current {
    background: var(--rm-secondary);               /* blue-600 */
    border-color: #3B82F6;                         /* blue-500 */
    color: white;
    animation: pulse-blue 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

/* 待执行 */
.phase-node.pending {
    background: var(--rm-bg-sidebar-active);       /* slate-800 */
    border-color: var(--rm-border-darker);         /* slate-700 */
    color: var(--rm-text-inverse-dim);             /* slate-500 */
}

/* 阶段标签 */
.phase-label {
    font-size: var(--rm-text-3xs);                 /* 10px */
    font-weight: var(--rm-weight-medium);
    margin-top: var(--rm-space-2);
    text-align: center;
    white-space: nowrap;
}

.phase-label.done    { color: var(--rm-success); }
.phase-label.current { color: #60A5FA; font-weight: var(--rm-weight-bold); }  /* blue-400 */
.phase-label.pending { color: var(--rm-text-inverse-dim); }
```

#### Pipeline 总体进度条

```css
.pipeline-progress-bar {
    width: 100%;
    height: 8px;
    background: var(--rm-bg-sidebar-active);       /* slate-800 */
    border-radius: 9999px;
    overflow: hidden;
}

.pipeline-progress-fill {
    height: 100%;
    background: linear-gradient(to right, #14B8A6, #3B82F6);  /* teal-500 → blue-500 */
    border-radius: 9999px;
    transition: width 0.3s ease;
}
```

---

### 4.10 SSE 实时日志终端

对应运行态终端面板：深色背景 `bg-slate-950 border border-slate-800 rounded-2xl`。

```css
.terminal-panel {
    background: var(--rm-bg-dark-card);            /* #020617 */
    border: 1px solid var(--rm-border-dark);
    border-radius: var(--rm-radius-xl);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: var(--rm-shadow-2xl);
}

/* 终端顶栏 */
.terminal-header {
    background: #1E293B;                           /* slate-800 → terminal header */
    padding: var(--rm-space-2) var(--rm-space-4);
    border-bottom: 1px solid var(--rm-border-dark);
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
}

.terminal-title {
    font-family: var(--rm-font-mono);
    font-size: var(--rm-text-xs);
    color: var(--rm-text-inverse-secondary);
}

/* 连接状态指示 */
.terminal-status {
    display: flex;
    align-items: center;
    gap: var(--rm-space-1_5);
    font-size: var(--rm-text-3xs);
    font-family: var(--rm-font-mono);
}

.terminal-status .live-dot {
    width: 10px;
    height: 10px;
    border-radius: var(--rm-radius-full);
    background: var(--rm-success);
    animation: ping 1s cubic-bezier(0, 0, 0.2, 1) infinite;
}

@keyframes ping {
    75%, 100% { transform: scale(2); opacity: 0; }
}

/* 终端日志内容 */
.terminal-body {
    flex: 1;
    overflow-y: auto;
    padding: var(--rm-space-4);
    font-family: var(--rm-font-mono);
    font-size: var(--rm-text-xs);
    background: var(--rm-bg-dark-card);
}

/* 单条日志 */
.terminal-log-line {
    display: flex;
    align-items: flex-start;
    gap: var(--rm-space-2);
    line-height: 1.625;
    margin-bottom: var(--rm-space-2);
}

.terminal-log-time {
    color: var(--rm-text-inverse-dim);
    flex-shrink: 0;
    user-select: none;
}
```

**日志类型颜色**（SSE 事件 → 终端显示色）：

| 事件类型 | 图标色 | 文字色 | 图标 |
|:---|:---|:---|:---|
| 阶段开始 (phase.started) | `#3B82F6` (blue-500) | `#60A5FA` (blue-400) bold | `fa-circle-right` |
| 步骤完成 (step.completed) | `#14B8A6` (teal-500) | `#CBD5E1` (slate-300) | `fa-check` |
| Checkpoint 保存 | `#F59E0B` (amber-500) | `#FBBF24` (amber-400) bold | `fa-floppy-disk` |
| 任务启动 | `#10B981` (emerald-500) | `#E2E8F0` (slate-200) | `fa-play` |
| 任务完成 | `#10B981` (emerald-500) | `#34D399` (emerald-400) bold | `fa-trophy` |
| 任务失败 | `#E11D48` (rose-500) | `#FB7185` (rose-400) bold | `fa-ban` |
| 普通信息 | `var(--rm-text-inverse-dim)` | `var(--rm-text-inverse-dim)` | `fa-spinner fa-spin` |

---

### 4.11 Checkpoint 保存提示横幅

对应运行态中部断点提示：`bg-teal-950/30 border border-teal-800/40 text-teal-300`。失败态中也使用此组件。

```css
.checkpoint-banner {
    background: rgba(15, 118, 110, 0.05);          /* teal-950/30 — 极浅 teal */
    border: 1px solid rgba(15, 118, 110, 0.2);     /* teal-800/40 */
    border-radius: var(--rm-radius-lg);
    padding: var(--rm-space-3);
    display: flex;
    align-items: center;
    gap: var(--rm-space-2_5);
    font-size: var(--rm-text-xs);
    color: #5EEAD4;                                /* teal-300 */
}

.checkpoint-banner .icon {
    color: #2DD4BF;                                /* teal-400 */
}
```

---

### 4.12 报告查看器组件

#### 报告章节导航（左侧目录树）

```css
.section-nav {
    width: var(--rm-section-nav-width);            /* 240px */
    background: var(--rm-bg-card);
    border-right: 1px solid var(--rm-border);
    overflow-y: auto;
    flex-shrink: 0;
    padding: var(--rm-space-4);
}

.section-nav-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    text-align: left;
    padding: var(--rm-space-2) var(--rm-space-2_5);
    border-radius: var(--rm-radius-sm);
    border-left: 2px solid transparent;
    font-size: var(--rm-text-xs);
    color: var(--rm-text-secondary);
    cursor: pointer;
    transition: all var(--rm-transition-fast);
}

.section-nav-item:hover {
    background: var(--rm-bg-elevated);
}

.section-nav-item.active {
    background: var(--rm-primary-light);
    color: var(--rm-primary);
    font-weight: var(--rm-weight-semibold);
    border-left-color: var(--rm-primary);
}

/* 引用计数徽标 */
.section-citation-count {
    background: var(--rm-bg-elevated);
    color: var(--rm-text-tertiary);
    font-size: var(--rm-text-3xs);                 /* 9px — 更小 */
    padding: 2px 6px;
    border-radius: 9999px;
}
```

#### 报告正文区

```css
.report-article {
    flex: 1;
    overflow-y: auto;
    padding: var(--rm-space-8) var(--rm-space-8);
    background: var(--rm-bg-card);
    line-height: var(--rm-leading-relaxed);
}

.report-article .max-width-prose {
    max-width: var(--rm-report-max-width);         /* 768px */
    margin: 0 auto;
}
```

#### 证据片段内联引用

对应报告正文中可点击的来源标记：`bg-teal-50 hover:bg-teal-100 text-teal-800 border-teal-200`。

```css
.evidence-inline-ref {
    display: inline-block;
    background: var(--rm-evidence-highlight-bg);
    color: var(--rm-evidence-highlight-text);
    font-size: var(--rm-text-xs);
    padding: 2px 6px;
    border-radius: var(--rm-radius-xs);
    font-family: var(--rm-font-mono);
    font-weight: var(--rm-weight-semibold);
    border: 1px solid var(--rm-evidence-highlight-border);
    cursor: pointer;
    margin: 0 2px;
    transition: all var(--rm-transition-fast);
}

.evidence-inline-ref:hover {
    background: #99F6E4;                           /* teal-200 */
}
```

#### 证据图谱面板（右侧）

```css
.evidence-panel {
    width: var(--rm-evidence-panel-width);         /* 320px */
    background: var(--rm-bg-page);
    border-left: 1px solid var(--rm-border);
    overflow-y: auto;
    flex-shrink: 0;
    padding: var(--rm-space-4);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
}
```

#### 证据卡片

```css
.evidence-card {
    background: var(--rm-bg-card);
    border: 1px solid var(--rm-border);
    border-radius: var(--rm-radius-lg);
    padding: var(--rm-space-3);
    font-size: var(--rm-text-xs);
    transition: all 0.3s ease;
    position: relative;
}

/* 与正文联动高亮 — 点击引用后右侧卡片闪烁 */
.evidence-card.flash {
    border-color: var(--rm-evidence-flash-border);
    background: #FFFBEB;                           /* amber-50/70 */
    box-shadow: 0 0 0 2px var(--rm-evidence-flash-border);
}

/* 证据标签 */
.evidence-tag {
    background: var(--rm-primary-hover);
    color: white;
    font-family: var(--rm-font-mono);
    font-size: 9px;
    padding: 2px 6px;
    border-radius: var(--rm-radius-xs);
    font-weight: var(--rm-weight-bold);
}

/* 相似度评分 */
.evidence-score {
    font-size: var(--rm-text-3xs);                 /* 10px */
    color: var(--rm-warning);
    font-weight: var(--rm-weight-bold);
}

/* 证据元信息 */
.evidence-meta {
    font-size: 9px;
    color: var(--rm-text-tertiary);
    border-top: 1px solid var(--rm-border-light);
    padding-top: var(--rm-space-1_5);
    display: flex;
    justify-content: space-between;
}
```

#### Trace 执行摘要（折叠面板）

```css
.trace-panel {
    background: var(--rm-bg-code);                 /* slate-900 */
    color: var(--rm-text-inverse-secondary);       /* slate-300 */
    border-radius: var(--rm-radius-md);
    padding: var(--rm-space-3);
    font-size: var(--rm-text-3xs);                 /* 10px */
    font-family: var(--rm-font-mono);
    box-shadow: var(--rm-shadow-inner);
}

.trace-row {
    display: flex;
    justify-content: space-between;
    padding: 2px 0;
}

.trace-row .stage-name { color: var(--rm-text-inverse-dim); }
.trace-row .stage-time { color: #2DD4BF; }        /* teal-400 */

.trace-total {
    border-top: 1px solid var(--rm-border-dark);
    padding-top: var(--rm-space-1);
    margin-top: var(--rm-space-1);
    font-weight: var(--rm-weight-bold);
    color: var(--rm-text-inverse);
}

.trace-total .value { color: #5EEAD4; }           /* teal-300 */
```

---

### 4.13 运行态头部栏

对应深色背景下的任务信息栏：`bg-slate-950 border-b border-slate-800`。

```css
.running-header {
    background: var(--rm-bg-dark-card);            /* #020617 */
    border-bottom: 1px solid var(--rm-border-dark);
    padding: var(--rm-space-4);
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
}

.running-header .task-info {
    display: flex;
    align-items: center;
    gap: var(--rm-space-3);
    overflow: hidden;
}

.running-header .spinner-icon {
    width: 36px;
    height: 36px;
    background: rgba(20, 184, 166, 0.1);           /* teal-500/10 */
    border: 1px solid rgba(20, 184, 166, 0.2);
    color: #2DD4BF;                                /* teal-400 */
    border-radius: var(--rm-radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

.running-header .task-title {
    font-size: var(--rm-text-sm);
    font-weight: var(--rm-weight-bold);
    color: white;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.running-header .task-meta {
    font-size: var(--rm-text-2xs);
    color: var(--rm-text-inverse-secondary);
}

.running-header .elapsed-time {
    color: #5EEAD4;                                /* teal-300 */
    font-family: var(--rm-font-mono);
    font-weight: var(--rm-weight-semibold);
}
```

---

### 4.14 失败状态卡片

对应中断态中央展示卡片。

```css
.failed-card {
    max-width: 448px;                              /* max-w-md */
    background: var(--rm-bg-card);
    border: 1px solid var(--rm-border);
    border-radius: var(--rm-radius-xl);
    padding: var(--rm-space-8);
    text-align: center;
    box-shadow: var(--rm-shadow-sm);
}

.failed-icon {
    width: 64px;
    height: 64px;
    background: var(--rm-danger-light);
    color: var(--rm-danger);
    border-radius: var(--rm-radius-full);
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto;
    font-size: 24px;
}

.failed-error-code {
    background: var(--rm-danger-light);
    color: #BE123C;                                /* rose-700 */
    font-family: var(--rm-font-mono);
    font-size: var(--rm-text-3xs);
    font-weight: var(--rm-weight-semibold);
    padding: 2px 6px;
    border-radius: var(--rm-radius-xs);
    display: inline-block;
}
```

---

### 4.15 用户信息栏 (User Bar)

位于侧边栏底部，深色背景。点击头像/用户名弹出用户菜单卡片（§4.18）。

```css
.user-bar {
    display: flex;
    align-items: center;
    gap: var(--rm-space-3);
    padding: var(--rm-space-3);
    border-top: 1px solid var(--rm-border-dark);
    background: rgba(2, 6, 23, 0.4);               /* slate-950/40 */
    position: relative;
}

.user-avatar {
    width: var(--rm-avatar-size);                  /* 32px */
    height: var(--rm-avatar-size);
    border-radius: var(--rm-radius-full);
    background: #115E59;                           /* teal-800 */
    border: 1px solid #0D9488;                     /* teal-600 */
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: var(--rm-text-xs);
    font-weight: var(--rm-weight-bold);
    flex-shrink: 0;
    cursor: pointer;
}

.user-name {
    font-size: var(--rm-text-xs);
    font-weight: var(--rm-weight-semibold);
    color: #E2E8F0;                                /* slate-200 */
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.user-role {
    font-size: var(--rm-text-3xs);
    color: var(--rm-success);                      /* teal-500 — 角色标识 */
}
```

**收起态**：仅显示用户头像，居中，`title="用户菜单"`。

---

### 4.16 用户菜单卡片 (User Menu Card)

从用户栏上方弹出，深色背景卡片。

```css
.user-menu-card {
    position: absolute;
    bottom: 100%;
    left: var(--rm-space-4);
    right: var(--rm-space-4);
    margin-bottom: var(--rm-space-2);
    background: var(--rm-bg-sidebar-active);       /* #1E293B */
    border: 1px solid var(--rm-border-darker);     /* #334155 */
    border-radius: var(--rm-radius-md);
    box-shadow: var(--rm-shadow-xl);
    overflow: hidden;
    z-index: 50;
    font-size: var(--rm-text-xs);
    animation: menuSlideUp var(--rm-transition-normal) ease;
}

.user-menu-divider {
    height: 1px;
    background: var(--rm-border-darker);
    margin: 0;
}

.user-menu-item {
    display: flex;
    align-items: center;
    gap: var(--rm-space-2);
    padding: var(--rm-space-1_5) var(--rm-space-2_5);
    color: var(--rm-text-inverse-secondary);
    cursor: pointer;
    transition: background var(--rm-transition-fast);
    border: none;
    background: transparent;
    width: 100%;
    text-align: left;
    font-size: var(--rm-text-xs);
}

.user-menu-item:hover {
    background: var(--rm-bg-sidebar-hover);
}

.user-menu-item.danger {
    color: #FDA4AF;                                /* rose-300 */
}

.user-menu-item.danger:hover {
    background: rgba(159, 18, 57, 0.25);           /* rose-900/40 */
}
```

**菜单项**：

| 选项 | 图标 | 样式 | 行为 |
|:---|:---|:---|:---|
| 用户设置（分组标题） | — | 灰色文字 | 不可点击 |
| 修改密码 | `fa-key` | `.user-menu-item` | 打开修改密码弹窗 |
| 进入管理端 | `fa-gears` | `.user-menu-item` (amber 色) | 仅 admin 可见 |
| 退出登录 | `fa-right-from-bracket` | `.user-menu-item.danger` | 清除 Token 跳转 `/login` |

---

### 4.17 修改密码对话框

使用 Element Plus `el-dialog` + `el-form`。

| 属性 | 值 |
|:---|:---|
| width | 420px |
| close-on-click-modal | false |
| destroy-on-close | true |

**表单**（`label-position="top"`，`size="default"`）：
- 标签字号：`var(--rm-text-xs)`，颜色 `var(--rm-text-secondary)`，字重 `var(--rm-weight-medium)`
- 输入框高度：`var(--rm-input-height)` (40px)
- 三个字段：当前密码、新密码、确认新密码

**按钮区**：
- 取消：默认 `el-button`
- 确认：`el-button type="primary"`

---

### 4.18 页面标题

```css
.page-title {
    font-size: var(--rm-text-2xl);                 /* 24px */
    font-weight: var(--rm-weight-bold);
    color: var(--rm-text-primary);
    letter-spacing: -0.025em;                      /* tracking-tight */
}

.section-title {
    font-size: var(--rm-text-base);                /* 16px */
    font-weight: var(--rm-weight-bold);
    color: var(--rm-text-primary);
}
```

---

### 4.19 高级配置折叠区

对应创建态中可折叠高级选项。

```css
.advanced-toggle {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    color: var(--rm-text-secondary);
    font-size: var(--rm-text-xs);
    font-weight: var(--rm-weight-semibold);
    padding: var(--rm-space-1) 0;
    cursor: pointer;
    border: none;
    background: transparent;
}

.advanced-toggle:hover {
    color: var(--rm-text-primary);
}

.advanced-panel {
    background: var(--rm-bg-page);
    border: 1px solid var(--rm-border-light);
    border-radius: var(--rm-radius-lg);
    padding: var(--rm-space-4);
}
```

#### 范围滑块 (Range Slider)

```css
input[type="range"].styled-slider {
    width: 100%;
    accent-color: var(--rm-primary);
    height: 6px;
    background: var(--rm-border);
    border-radius: var(--rm-radius-md);
    cursor: pointer;
    -webkit-appearance: none;
    appearance: none;
}

input[type="range"].styled-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 16px;
    height: 16px;
    border-radius: var(--rm-radius-full);
    background: var(--rm-primary);
    cursor: pointer;
}
```

---

### 4.20 空状态 (Empty State)

```css
.empty-state {
    text-align: center;
    padding: var(--rm-space-12) var(--rm-space-5);
    color: var(--rm-text-tertiary);
}

.empty-icon {
    font-size: 48px;
    margin-bottom: var(--rm-space-4);
    opacity: 0.5;
}

.empty-title {
    font-size: var(--rm-text-base);
    font-weight: var(--rm-weight-semibold);
    color: var(--rm-text-primary);
    margin-bottom: var(--rm-space-2);
}

.empty-desc {
    font-size: var(--rm-text-sm);
    color: var(--rm-text-secondary);
}
```

---

### 4.21 加载动画

#### 脉冲动画（当前阶段节点）

```css
@keyframes pulse-blue {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%      { opacity: 0.6; transform: scale(1.05); }
}

.animate-pulse-blue {
    animation: pulse-blue 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}
```

#### 连接指示点动画

```css
@keyframes ping {
    75%, 100% { transform: scale(2); opacity: 0; }
}

.animate-ping {
    animation: ping 1s cubic-bezier(0, 0, 0.2, 1) infinite;
}
```

#### 旋转加载

使用 Font Awesome 的 `fa-spin` 类（`fa-spinner fa-spin`），不自定义。

---

## 5. 动画与过渡

### 5.1 过渡时长（Design Token）

| Token | 值 | 适用场景 |
|:---|:---|:---|
| `--rm-transition-fast` | 0.15s ease | 颜色/背景变化、hover 效果 |
| `--rm-transition-normal` | 0.2s cubic-bezier(0.4, 0, 0.2, 1) | Sidebar 展开/收起、边框变化、输入框聚焦 |
| `--rm-transition-slow` | 0.3s ease | Pipeline 阶段切换、证据联动闪烁消退 |

### 5.2 关键帧动画

| 动画名 | 时长 | 组件 | 用途 |
|:---|:---|:---|:---|
| `pulse-blue` | 2s infinite | Pipeline 当前阶段节点 | 缩放脉冲（opacity + scale 1→1.05） |
| `ping` | 1s infinite | SSE 连接状态指示点 | 扩散消退 |
| `menuSlideUp` | `var(--rm-transition-normal)` ease | 用户菜单卡片 | 从下方滑入（opacity + translateY 6px） |
| `sidebar-transition` | 0.2s cubic-bezier(0.4, 0, 0.2, 1) | Sidebar | 宽度过渡（由 §3.2 的 `transition` 属性控制） |

```css
@keyframes menuSlideUp {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
}
```

### 5.3 Vue Transition 类名

```css
.fade-enter-active,
.fade-leave-active { transition: opacity var(--rm-transition-fast); }
.fade-enter-from,
.fade-leave-to { opacity: 0; }
```

---

## 6. 图标规范

### 6.1 图标方案

使用 **Font Awesome 6 Free**（Solid 风格，`fas` 前缀）。尺寸由 CSS 上下文控制，不使用 FA 尺寸修饰类。`fa-spin` 是唯一使用的辅助类。`fa-regular` 用于部分文档类图标（如 `fa-file-lines`）。

### 6.2 尺寸基准

| 场景 | 尺寸 | 实现方式 |
|:---|:---|:---|
| 内联图标 | 继承父元素 font-size | 通常 12-14px |
| 侧边栏导航图标 | 14-16px | 父容器设定 |
| 按钮内图标 | 12-14px | 父容器设定 |
| 卡片头部图标 | 16-20px | 父容器设定 |
| Pipeline 阶段节点内图标 | 10px | `text-[10px]` |
| Logo 图标 | 16px（侧边栏）/ 24px（欢迎页） | Design Token |
| 失败态大图标 | 24px | 父容器设定 |
| 空状态图标 | 24-48px | `.empty-icon` 类 |

### 6.3 图标功能域分类

| 功能域 | 包含图标 |
|:---|:---|
| 导航/操作 | `fa-microscope` `fa-plus` `fa-arrow-left` `fa-search` `fa-bars` `fa-chevron-left` `fa-chevron-right` `fa-chevron-up` `fa-chevron-down` |
| 状态指示 | `fa-spinner fa-spin` `fa-check` `fa-circle-check` `fa-triangle-exclamation` `fa-circle-check` |
| 研究/Pipeline | `fa-brain` `fa-magnifying-glass` `fa-download` `fa-filter` `fa-feather-pointed` `fa-sitemap` `fa-file-invoice` `fa-seedling` `fa-wand-magic-sparkles` `fa-project-diagram` `fa-scale-balanced` `fa-lightbulb` `fa-chart-line` |
| 用户/权限 | `fa-user` `fa-key` `fa-shield-alt` `fa-gears` `fa-right-from-bracket` |
| 数据/操作 | `fa-terminal` `fa-floppy-disk` `fa-rotate` `fa-rotate-left` `fa-ban` `fa-play` `fa-trophy` `fa-star` `fa-arrow-up-right-from-square` `fa-sliders` `fa-clock-rotate-left` |
| 文档/报告 | `fa-file-lines` `fa-regular fa-file-lines` `fa-list-check` `fa-circle-info` |
| UI 控制 | `fa-times` `fa-circle-check`（选中勾） |

### 6.4 图标对齐

- 内联图标 + 文字：`display: inline-flex; align-items: center; gap: var(--rm-space-2)`
- 按钮内图标：同上
- 侧边栏项图标：`flex-shrink: 0`，固定宽度容器
- Pipeline 节点内图标：`display: flex; align-items: center; justify-content: center`

---

## 7. 报告 Markdown 渲染样式

### 7.1 渲染引擎配置

使用 `markdown-it` + `highlight.js`（`github-dark` 主题）。

| 配置项 | 值 | 说明 |
|:---|:---|:---|
| `html` | `false` | 禁用 raw HTML，防 XSS |
| `linkify` | `true` | 自动识别链接 |
| `breaks` | `true` | 换行转 `<br>` |
| `highlight` | highlight.js | 代码块语法高亮 |

### 7.2 报告正文元素样式

报告中 `.report-body` 内的 Markdown 元素样式：

| 元素 | 样式 | Token 引用 |
|:---|:---|:---|
| h1 | `font-size: 20px; font-weight: 700` | `--rm-text-xl` `--rm-weight-bold` |
| h2 | `font-size: 18px; font-weight: 700; border-bottom: 1px solid` | `--rm-text-lg` `--rm-border-light` |
| h3 | `font-size: 16px; font-weight: 600` | `--rm-text-base` `--rm-weight-semibold` |
| p | `margin: 12px 0; line-height: 1.625` | `--rm-leading-relaxed` |
| strong | `font-weight: 600; color:` | `--rm-text-primary` |
| code（行内） | `background: rgba(0,0,0,0.05); padding: 2px 6px; border-radius: 4px; font-family: monospace` | `--rm-font-mono` |
| pre > code | `background: #0F172A; color: #CBD5E1; padding: 16px; border-radius: 8px` | `--rm-bg-code` `--rm-text-code` |
| blockquote | `border-left: 3px solid; padding: 8px 16px; background:` | `--rm-primary` `--rm-primary-light` |
| ul/ol | `margin: 8px 0; padding-left: 24px` | — |
| li | `margin: 4px 0; line-height: 1.625` | `--rm-leading-relaxed` |
| a | `color: var(--rm-primary); text-decoration: none` | — |
| a:hover | `text-decoration: underline` | — |
| table | `width: 100%; border-collapse: collapse; font-size: 12px` | `--rm-text-xs` |
| th | `text-align: left; font-weight: 600; border-bottom: 1px solid` | `--rm-border` |
| td | `padding: 6px 0; border-bottom: 1px solid` | `--rm-border-light` |

---

## 8. Element Plus 主题覆盖

```css
/* styles/element-override.css */
:root {
    --el-color-primary: #0F766E;
    --el-color-primary-light-3: #14B8A6;
    --el-color-primary-light-5: #5EEAD4;
    --el-color-primary-light-7: #99F6E4;
    --el-color-primary-light-8: #CCFBF1;
    --el-color-primary-light-9: #F0FDFA;
    --el-border-radius-base: 8px;
    --el-font-size-base: 14px;
    --el-font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI",
                      Roboto, "Helvetica Neue", Arial, sans-serif;
}
```

### 使用方式

```js
// main.js
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/element-override.css'

const app = createApp(App)
app.use(ElementPlus)
```

---

## 9. 相关文档

- [产品需求文档](PRD.md)
- [架构设计文档](ARCHITECTURE.md)
- [接口文档](API.md)
- [前端交互文档](FRONTEND.md)
- [前端基础设施复用](INFRASTRUCTURE_REUSE_FRONTEND.md)
- [排期](ROADMAP.md)

> **权威定义**：本文档是 ResearchMind 前端样式领域的唯一真理源。所有 CSS 变量、组件样式、布局规范以本文档为准。Vue 组件中禁止硬编码颜色/字号/间距值，必须引用 `--rm-*` Design Token。
