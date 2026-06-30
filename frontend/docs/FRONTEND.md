# FRONTEND — 前端交互文档

| 属性 | 值 |
|:---|:---|
| 文档版本 | v1.0 |
| 最后更新 | 2026-06-29 |

> 本文档是 **前端页面交互流程、组件行为规范、SSE 事件处理状态机** 的唯一真理源。相关定义禁止在其他文档中重复，应使用交叉引用链接到本文档对应章节。CSS 变量与组件样式见 [UIDESIGN.md](UIDESIGN.md)，接口定义见 [API.md](API.md)，技术选型与架构见 [ARCHITECTURE.md](ARCHITECTURE.md)。

---

## 1. 全局交互架构

### 1.1 技术栈

| 层面 | 技术 | 用途 |
|:---|:---|:---|
| 框架 | Vue 3 | Composition API + `<script setup>` |
| 构建工具 | Vite | 开发服务器（端口 5173） |
| UI 组件库 | Element Plus | 表单、表格、弹窗、消息提示等 |
| 状态管理 | Pinia | 认证、研究任务、报告三个 store |
| 路由 | Vue Router | 三级路由守卫（公开/需登录/需管理员） |
| HTTP 客户端 | Axios | 请求/响应拦截器，自动处理 Token 和 401 |
| 图标 | Font Awesome 6 Free | 全站统一图标方案 |
| Markdown 渲染 | markdown-it + highlight.js | 研究报告正文渲染 + 代码高亮 |
| 图表 | ECharts 6 | 管理后台统计可视化 |

> **技术栈说明**：ResearchMind 前端技术栈为 Vue 3 + Vite + Pinia + Element Plus + Axios + Font Awesome。工程脚手架、Auth 体系、Design Token 系统各模块锚点见 [§1.4 共享工具模块](#14-共享工具模块)。

### 1.2 状态管理总览

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  auth.js    │  │  task.js    │  │  report.js  │
│  认证状态    │  │ 任务状态     │  │  报告状态    │
├─────────────┤  ├─────────────┤  ├─────────────┤
│ • user      │  │ • taskList  │  │ • report    │
│ • token     │  │ • current   │  │ • loading   │
│ • isAdmin   │  │ • sseStatus │  │ • sections  │
│ • login()   │  │ • progress  │  │ • evidence  │
│ • logout()  │  │ • create()  │  │ • trace     │
│ • refresh() │  │ • fetch()   │  │ • fetch()   │
│             │  │ • cancel()  │  │             │
│             │  │ • retry()   │  │             │
│             │  │ • poll()    │  │             │
└─────────────┘  └─────────────┘  └─────────────┘
```

> `authStore` 的 `refresh()` action 调 `POST /api/auth/refresh` 换取新 token 对，配合 `scheduleRefresh()` 定时器在 access_token 到期前 1 分钟自动刷新。`refresh_token` 通过 `localStorage` 持久化，页面刷新后仍可用。
>
> **taskStore**：管理研究任务的完整生命周期——列表、创建、SSE 进度追踪、取消、重试。`current` 保存当前聚焦的任务详情（含 pipeline 阶段、步骤进度）。`sseStatus` 追踪 SSE 连接状态（`disconnected` / `connecting` / `connected` / `reconnecting` / `error`）。`retryTask(taskId)` 调用 `api/research.retryTask()` 后乐观更新状态为 `running`，清除错误字段，重置运行时状态，**立即建立 SSE 连接**（不调用 `fetchDetail`，避免事件丢失窗口期）。
>
> **reportStore**：管理已完成任务的研究报告——章节列表、Evidence Graph、Trace 摘要。报告数据通过 `GET /api/research/{task_id}/report` 获取，前端负责 Markdown 渲染 + 引用锚点滚动联动。

**规则**：组件内不直接调用 axios，所有请求走 `api/` 目录封装；状态提升到 Pinia，不用 props 透传超过两层。

### 1.3 全局错误处理

| 场景 | 前端行为 |
|:---|:---|
| HTTP 401 + `code=E1003`（Token 过期） | Axios 响应拦截器自动调 `authStore.refresh()` → 重放原请求。刷新成功用户无感，刷新失败（refresh_token 也过期/吊销）→ 清除 token → 跳转 `/login` |
| HTTP 401 + 其他 code（E1004/E1006/E1007/E1008/E1009/E1010） | 清除 token，跳转 `/login`（已在登录页则不动） |
| HTTP 403 | Element Plus `ElMessage.error('无权限执行此操作')` |
| HTTP 409 + `code=E2003`（状态冲突） | 根据 `detail.current_status` 和 `detail.allowed_statuses` 显示具体错误提示 |
| HTTP 422 | 提取后端返回的字段级错误，聚焦到对应表单项 |
| HTTP 429 + `code=E9004`（限流） | `ElMessage.warning('操作过于频繁，请稍后重试')` |
| HTTP 500/503 | `ElMessage.error('服务暂不可用，请稍后重试')` |
| 网络中断 | 请求超时 30s，提示 `网络异常，请检查连接` |

#### 1.3.1 Axios 拦截器自动刷新流程

```
请求发起
   ↓
请求拦截器：附加 Authorization: Bearer <access_token>
   ↓
发送请求
   ↓
收到 401 + code=E1003（Token 过期）
   ↓
响应拦截器：
  ├─ 检查 refresh_token 是否存在且未过期
  │   ├─ 有 → 调 POST /api/auth/refresh { refresh_token }
  │   │       ├─ 成功 → 存储新 token 对 → 重放原请求
  │   │       └─ 失败（E1006/E1007/E1008/E1009）→ 清除全部 token → 跳转 /login
  │   └─ 无 → 清除 token → 跳转 /login
  └─ 其他 401 → 清除 token → 跳转 /login
```

> **防并发刷新**：拦截器需维护 `isRefreshing` 标志位。当多个请求同时收到 401 时，仅第一个触发刷新，其余排队等待刷新完成后统一重放。避免短时间多次调 refresh 接口导致 Rotation 冲突。
>
> **scheduleRefresh 定时器**：登录/刷新成功后启动定时器（`setTimeout`），在 access_token 到期前 1 分钟（`expires_in - 60s`）自动调 `authStore.refresh()`。页面卸载时 `clearTimeout`。
>
> **SSE 连接无需 Token 刷新**：SSE 连接在建立时携带当前 access_token，连接期间 token 过期不影响已建立的 SSE 流。重连时使用最新 token。

### 1.4 共享工具模块

| 模块 | 路径 | 主要导出 | 来源 |
|:---|:---|:---|:---|
| 格式化工具 | `utils/format.js` | `formatDateTime()` / `formatBytes()` / `formatRelativeTime()` / `formatNumber()` / `formatDuration()` | ResearchMind 实现，含 `formatNumber`/`formatDuration` |
| Markdown 渲染 | `utils/markdown.js` | `renderMarkdown()` / `wrapCodeBlocks()` + `[来源N]` 引用锚点 plugin | ResearchMind 实现，含引用锚点解析 |
| SSE 解析 | `utils/sse.js` | fetch + ReadableStream + 18 种事件解析（v1.0）+ 2 种预留 [v2] + 5 态连接状态机（Phase 2+ 实现） | ResearchMind SSE 解析框架，18 种事件处理器 |
| ECharts 封装 | `composables/useECharts.js` | `useECharts()` — 响应式 resize + dispose + `setOption` 暂存 | ResearchMind 实现，零改动 |

---

## 2. 路由与页面结构

### 2.1 路由表

> **权限模型**：后端 API 区分两种视角——user 管理自己的研究任务，admin 跨用户管理全部任务。前端路由对齐此模型。

**用户视角路由**（所有登录用户可访问）：

| 路径 | 页面 | 权限 | 说明 |
|:---|:---|:---|:---|
| `/` | → `/research` | 公开 | 根路径重定向到研究页 |
| `/login` | LoginPage | 公开 | 已登录者访问自动重定向到 `/research` |
| `/research` | ResearchPage | 需登录 | 核心研究页：任务创建 + 进度追踪 + 报告查看，默认首页 |
| `/history` | HistoryPage | 需登录 | 研究任务历史列表（分页、按状态筛选） |

**管理员视角路由**（仅 admin 可访问，使用独立 AdminLayout 布局）：

| 路径 | 页面 | 权限 | 说明 |
|:---|:---|:---|:---|
| `/admin` | 重定向到 `/admin/stats` | 需管理员 | 管理后台默认页 |
| `/admin/stats` | AdminStats | 需管理员 | 系统统计（数据总览 + ECharts 图表） |
| `/admin/tasks` | AdminTaskList | 需管理员 | 全部研究任务（跨用户），可查看/删除/取消 |
| `/admin/tasks/:task_id` | AdminTaskDetail | 需管理员 | 任务详情（Pipeline 阶段 + Steps + Trace） |
| `/admin/users` | AdminUserList | 需管理员 | 用户管理列表（筛选+操作菜单） |
| `/admin/users/:user_id` | AdminUserDetail | 需管理员 | 用户详情（统计+快捷操作） |

> **布局说明**：Admin 路由使用独立的 `AdminLayout.vue` 布局，拥有专用的 Admin 侧边栏，与用户主侧边栏完全分离。Admin 通过用户菜单 →「管理后台」入口进入。

**兜底**：

| `*` | → `/research` | - | 兜底重定向 |

### 2.2 路由守卫逻辑

```
用户访问某个路径
    ↓
已登录且访问 /login → 重定向 /research
    ↓
未登录且访问需认证页 → 重定向 /login
    ↓
非 admin 访问 admin/* → 重定向 /research
    ↓
正常放行
```

### 2.3 ResearchMind 路由结构

| 维度 | 说明 |
|:---|:---|
| 核心页面 | ResearchPage（任务提交+进度+报告） |
| 资源管理 | HistoryPage（任务历史列表） |
| 嵌套路由 | 无（ResearchPage 通过内部 Tab/状态切换） |
| 公共资源 | 无（v1.0 MVP 无此概念） |
| 管理后台 | 任务管理 / 用户管理 / 统计 |

---

## 3. 登录/注册页（LoginPage）

### 3.1 页面布局

| 区域 | 交互说明 |
|:---|:---|
| 页面背景 | 深色渐变（slate-900 → slate-800 → slate-900），135° 对角线方向，与侧边栏 `--rm-bg-sidebar`（#0F172A）同色系 |
| 品牌区 | Logo（teal-700 纯色方块 + 显微镜图标）+ 标题「ResearchMind」+ 副标题「可审计的结构化研究引擎」 |
| Tab 切换 | 登录/注册 两段式切换，带动画高亮 |
| 表单区 | 用户名 + 密码输入框，带图标前缀 |
| 错误提示 | 校验失败或 API 错误时，红色提示条出现 |
| 提交按钮 | loading 时禁用并显示旋转图标 |
| 底部链接 | 「还没有账号？立即注册」互转 |

### 3.2 交互流程

**登录流程**：
```
用户输入用户名、密码
    ↓
点击「登录」→ 前端校验（用户名非空、密码≥6位）
    ↓
调用 authStore.login() → POST /api/auth/login
    ↓
成功：ElMessage.success('登录成功') → 存储 access_token + refresh_token → 解析 JWT 用户信息 → 启动 scheduleRefresh 定时器 → 跳转 /research
失败：显示后端错误消息（如「用户名或密码错误」）
```

**注册流程**：
```
用户输入用户名、密码
    ↓
点击「注册」→ 前端校验
    ↓
调用 authStore.register() → POST /api/auth/register
    ↓
成功：自动切换回登录模式，清空密码框，用户需手动登录
失败：显示错误（如「用户名已存在」）
```

### 3.3 表单校验规则

| 字段 | 规则 | 错误提示 |
|:---|:---|:---|
| 用户名 | 非空，长度 ≥ 2 | 请输入用户名 / 用户名至少 2 个字符 |
| 密码 | 长度 ≥ 6 | 密码至少 6 个字符 |

> **实现说明**：LoginPage 的交互流程、表单校验规则为 ResearchMind 自有实现。视觉层面使用深色渐变页面背景（slate-900 系，与侧边栏同色系），品牌区标题/副标题文案为 ResearchMind 专属文案。详见 [UIDESIGN.md §登录页](UIDESIGN.md)。

---

## 4. 研究页（ResearchPage）— 核心交互

ResearchPage 是 ResearchMind 的核心页面，承载三个主要状态：**任务创建** → **进度追踪** → **报告查看**，采用「提交-等待-查看」的异步任务模式。

### 4.1 页面布局

```
┌─────────────────────────────────────────────────────────────┐
│  Sidebar (256px/64px收起)      │  Main Content               │
│  ─────────────────────────────┤  ─────────────────────────  │
│  Logo + 新建研究               │  状态栏：当前任务标题 + 状态   │
│  ─────────────────────────────┤  ─────────────────────────  │
│  历史任务列表                   │                             │
│  • 按时间分组（今天/昨天/…）     │  ┌─ 创建态 ──────────────┐  │
│  • 状态图标（✅/❌/⏳/⚠️）    │  │ 研究主题输入 + 配置表 │  │
│  • 点击加载历史任务             │  │ + 提交按钮            │  │
│  ─────────────────────────────┤  └──────────────────────┘  │
│  [所有用户] 历史任务             │                             │
│  • 点击进入 /history           │  ┌─ 运行态 ──────────────┐  │
│  ─────────────────────────────┤  │ Pipeline 阶段进度条    │  │
│  [admin] 管理后台              │  │ Step 实时日志流        │  │
│  • 系统统计 / 任务管理 / …     │  │ 取消按钮               │  │
│  ─────────────────────────────┤  └──────────────────────┘  │
│  用户头像 + 退出按钮             │                             │
│                                  │  ┌─ 完成态 ──────────────┐  │
│                                  │  │ 报告标题 + 摘要       │  │
│                                  │  │ 章节导航（侧栏）      │  │
│                                  │  │ Markdown 报告正文     │  │
│                                  │  │ 来源图谱面板   │  │
│                                  │  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 三种页面状态

ResearchPage 根据 `taskStore.current.status` 切换三种 UI 状态：

| 状态 | 触发条件 | UI |
|:---|:---|:---|
| **创建态** | `current === null`（无活跃任务） | 任务创建表单 |
| **运行态** | `current.status` 为 `pending` / `running` | Pipeline 进度视图 + SSE 实时日志 |
| **完成态** | `current.status` 为 `completed` / `partially_completed` / `failed` / `canceled` | 报告查看视图 |

**状态切换流程**：
```
创建态 ──[提交任务]──→ 运行态 ──[SSE task.completed]──→ 完成态
                          │
                          └──[SSE task.failed]──→ 完成态（错误视图）
                          │
                          └──[用户取消]──→ 完成态（取消视图）
```

### 4.3 创建态：任务提交表单

#### 4.3.1 表单布局

```
┌─────────────────────────────────────────────────────────────┐
│                                                              │
│         🔬 开始一项新的研究                                    │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  研究主题                                            │    │
│  │  ┌─────────────────────────────────────────────────┐│    │
│  │  │ 输入你想研究的问题、对比或分析主题…                ││    │
│  │  │                                                 ││    │
│  │  └─────────────────────────────────────────────────┘│    │
│  │  ≤ 500 字符                                         │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─ 研究类型 ─────────────────────────────────────────┐     │
│  │  ○ 对比型研究   ○ 解释型研究   ○ 影响分析型          │     │
│  │   (comparison)   (explainer)    (analysis)          │     │
│  └────────────────────────────────────────────────────┘     │
│                                                              │
│  ┌─ 高级选项（可折叠）─────────────────────────────────┐     │
│  │  信息源数量：[━━━━━●━━━━] 10                        │     │
│  │             (1-50)                                  │     │
│  │  报告语言：  [中文 ▼]                               │     │
│  │  研究深度：  quick（MVP 固定值，不可选）              │     │
│  └────────────────────────────────────────────────────┘     │
│                                                              │
│            [🔬 开始研究]                                     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

#### 4.3.2 表单字段

| 字段 | 组件 | 必填 | 校验规则 |
|:---|:---|:---|:---|
| 研究主题 (topic) | `el-input type="textarea" rows="4"` | 是 | 非空，≤ 500 字符，实时字数统计 |
| 研究类型 (task_type) | `el-radio-group` 或三张可选卡片 | 是 | 必须选中一个 |
| 信息源数量 (max_sources) | `el-slider` | 是 | 1-50，默认 10 |
| 报告语言 (language) | `el-select` | 是 | `zh` / `en`，默认 `zh` |
| 研究深度 (depth) | 固定值 | 是 | MVP 固定 `quick`，灰显 |

#### 4.3.3 研究类型选择卡片

三种研究类型使用可选卡片（非普通 radio），帮助用户理解各类型的适用场景：

| 类型 | 图标 | 标题 | 描述 | 示例 |
|:---|:---|:---|:---|:---|
| `comparison` | `fa-balance-scale` | 对比型研究 | 结构化对比、多源属性提取、维度对齐 | "2025年主流向量数据库对比" |
| `explainer` | `fa-lightbulb` | 解释型研究 | 观点聚类、弱结构输入、综合性强 | "Transformer 注意力机制的最新改进方向" |
| `analysis` | `fa-chart-line` | 影响分析型 | 因果推理、跨域综合、前瞻推断 | "量子计算对密码学体系的影响" |

**交互**：点击卡片选中（高亮边框 + 浅色背景），再次点击取消选中。三选一，不可多选。

#### 4.3.4 提交流程

```
用户填写 topic + 选择 task_type + 配置选项
    ↓
点击「开始研究」
    ↓
前端校验：
  - topic 非空 + ≤ 500 字符
  - task_type 已选中
  - max_sources 在 1-50 范围
    ↓
taskStore 乐观进入运行态（current.status='running'，立即显示 Pipeline 进度视图）
    ↓
POST /api/research { topic, requirements: { task_type, depth: "quick", max_sources, language } }
    ↓
成功 (201) → 用真实 task_id/status 覆盖乐观占位 → 自动连接 SSE
失败 → 回滚到创建态并显示错误提示
```

> **[Deviation/修复]** 原实现中点击「开始研究」后需等待 `POST /api/research` 返回才会切换到运行态，期间创建表单保持可见 2-3 秒，用户感知为无响应。修复后参考 `retryTask()` 的乐观更新策略：`createTask()` 在 API 调用前即将 `current` 置为 `running` 并渲染运行态；API 成功后以真实响应覆盖占位，API 失败时调用 `clearCurrent()` 回滚到创建态。`ResearchPage.handleCancel()` 增加 `task_id` 空值保护，避免乐观占位期间触发取消。

#### 4.3.5 快捷示例

表单下方提供 3 个快捷示例卡片（与 WelcomeScreen 类似），点击自动填入 topic + 选中对应 task_type：

| 示例 | topic | task_type |
|:---|:---|:---|
| "2025年主流向量数据库对比：Milvus vs Qdrant vs Weaviate" | 自动填入 | `comparison` |
| "Transformer 注意力机制的最新改进方向" | 自动填入 | `explainer` |
| "量子计算对现有密码学体系的影响及应对方案" | 自动填入 | `analysis` |

---

### 4.4 运行态：Pipeline 进度追踪

#### 4.4.1 页面布局

```
┌─────────────────────────────────────────────────────────────┐
│  🔬 量子计算对现有密码学体系的影响                    [取消研究]│
│  状态：运行中 · 当前阶段：搜索中 · 已用时 00:42              │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Pipeline 阶段进度条                                          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Planning ──→ Search ──→ Fetch ──→ Rerank ──→ ...   │    │
│  │    ✅         🔄         ⏳          ⏳        ⏳     │    │
│  │   1.2s      进行中                                    │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  整体进度                                                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ ████████████████░░░░░░░░░░░░░░░░  58% (7/12 Steps)  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  Step 实时日志                                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ ✅ 2026-06-19 10:00:05  任务已创建                    │    │
│  │ ✅ 2026-06-19 10:00:06  进入 Planning 阶段              │    │
│  │ ✅ 2026-06-19 10:00:07  Planning 完成，拆解为 4 个子问题  │    │
│  │ ✅ 2026-06-19 10:00:08  进入 Search 阶段                │    │
│  │ 🔄 2026-06-19 10:00:09  正在搜索子问题 1：NIST PQC...     │    │
│  │ 🔄 2026-06-19 10:00:15  搜索子问题 1 完成，找到 15 条结果  │    │
│  │ ⏳ 2026-06-19 10:00:16  正在搜索子问题 2：量子密钥分发...   │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─ 断点续跑提示（checkpoint.saved 后显示）────────────┐     │
│  │ 💾 已保存进度 · 若中断可从当前阶段恢复                  │     │
│  └────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

#### 4.4.2 Pipeline 阶段进度条

七阶段横向进度条，根据 SSE 事件实时更新：

| 阶段 | SSE 事件 | 图标 | 说明 |
|:---|:---|:---|:---|
| Planning | `phase.started` → `phase.completed` | `fa-brain` | LLM 拆解研究主题 |
| Search | `phase.started` → `phase.completed` | `fa-search` | Tavily API 搜索 |
| Fetch | `phase.started` → `phase.completed` | `fa-download` | 网页内容抓取 |
| Rerank | `phase.started` → `phase.completed` | `fa-sort-amount-down` | BM25 + LLM 重排 |
| Synthesis | `phase.started` → `phase.completed` | `fa-project-diagram` | LLM 跨源综合 |
| 来源图谱 | `phase.started` → `phase.completed` | `fa-sitemap` | 构建来源图谱 |
| Render | `phase.started` → `phase.completed` | `fa-file-alt` | 报告渲染 |

**状态映射**：

| 阶段状态 | 视觉 |
|:---|:---|
| 未开始 | 灰色图标 + 灰色文字 |
| 进行中 | 蓝色旋转动画 + 脉冲高亮 |
| 已完成 | 绿色勾 + 耗时标注 |
| 跳过（降级） | 灰色勾 + 虚线边框 |

**Planning 阶段特殊展示**：[Deviation] 当 Planning 阶段进行中（`phaseStates.planning === 'running'`）时，整体进度文本区仅显示「任务规划中…」，不显示 `completed_steps/total_steps`。Planning 完成后恢复正常百分比与步骤数。
>
> **[Deviation/修复]** 验收时发现进度条分母会随 Search/Fetch 子 step 创建而同步增长，导致 `3/3 → 3/6 → 6/6` 这类分母跳变与 100% → 33% 的回退。修复后：`searcher.py` / `fetcher.py` 创建子 ResearchStep 时不再递增 `task.total_steps`；前端 `task.js` 在 `step.completed` 事件中不再本地累加 `progress.completed_steps`。
>
> **[Deviation/修复]** 第三轮验收时发现任务刚创建即显示 `100%（1/1 步骤）`，且执行到 Render 阶段仍出现 `20%（6/30 步骤）`。修复后：`research_service.create_task()` 初始化 `task.total_steps = len(PHASE_ORDER)`（固定为 7）；`PipelineOrchestrator._create_step()` 不再递增 `task.total_steps`；前端 `PipelineProgress.vue` 直接以 7 作为固定分母，`completed_steps` 每完成一个大阶段 +1，显示进度从 `1/7` 单调增长到 `7/7`，彻底消除分母跳变。

#### 4.4.3 Step 实时日志

日志条目由 SSE 事件驱动，实时追加到可滚动日志面板：

| SSE 事件 | 日志条目 | 图标 |
|:---|:---|:---|
| `task.created` | `任务已创建，开始执行` | `fa-play` |
| `phase.started` | `进入 {phase} 阶段` | `fa-arrow-right` |
| `phase.completed` | `{phase} 阶段完成（耗时 {duration_ms}）` | `fa-check-circle` |
| `step.started` | `{label}` | `fa-spinner fa-spin` |
| `step.progress` | `{label} — {results_found} 条结果` 或 `{label} — {progress}%` | `fa-spinner fa-spin` |
| `step.completed` | `{label} — 完成` | `fa-check` |

**进度标签展示规则**：`step.progress` 事件若携带人类可读 `label`，日志行优先展示 `label`（如「正在对 12 条来源进行跨源综合…」）；否则 fallback 到 `results_found` 或 `progress` 数值。后端 Rerank/Synthesis/来源图谱/Render 阶段均会在子步骤边界发送带 `label` 的 `step.progress` 事件。
>
> **[Deviation/修复]** 验收时发现 step 类型日志消息为空、切出页面再切回后日志丢失。修复内容：
> - `taskStore.buildLogsFromSnapshot()` 使用后端快照实际字段 `step_id` / `step_type` / `label` / `status` / `duration_ms` / `error_code` / `error_message`，并为每条日志生成 `message: label || step_type`。
> - `step.started` / `step.failed` / `step.skipped` 事件在 `upsertStepLog` / `updateStepLog` 时同步写入 `message` 字段。
> - `StepLog.vue` 渲染消息兜底：`{{ log.message || log.label || log.stepType }}`。
> - `ResearchPage.vue` 在 `onMounted` 中检测 `current.status` 为 `'running'` **或 `'pending'`** 且 `sseStatus === 'disconnected'` 时自动调用 `connectSSE(task_id)`，恢复实时流并继续追加日志。`pending` 状态覆盖是断点续跑场景必需的（retry 后 Worker 拾取前存在 `pending` 窗口期）。
>
> **[Deviation/修复]** 第三轮验收时发现切页恢复后的日志没有时间戳、细化内容（如「正文提取为空」）变少。修复内容：
> - 后端 `_build_snapshot()` 在 steps 摘要中增加 `started_at` 与 `progress_label`（从 step.output 提取 search 结果数 / fetch 错误摘要）。
> - 前端 `buildLogsFromSnapshot()` 映射 `timestamp` / `icon` / `progress.label`，完整恢复日志外观。
> - `upsertStepLog()` / `updateStepLog()` 为没有 `timestamp` 的日志补充当前客户端时间。
> - `StepLog.vue` 对 completed/skipped/failed 状态的日志也展示 `progress.label`。
> - 后端 `step.started` SSE 事件携带 `timestamp`，运行态日志与快照恢复日志时间来源一致。
| `step.failed` | `{label} — 失败：{error_type}` | `fa-exclamation-triangle` |
| `step.skipped` | `{label} — 已跳过：{reason}` | `fa-fast-forward` |
| `agent.thought` | `思考：{thought}`（内容过长时截断，hover 显示完整） | `fa-brain` |
| `agent.action` | `调用 {tool_name}({arguments})` | `fa-terminal` |
| `agent.observation` | `{tool_name} 结果：{observation}` | `fa-eye` |
| `checkpoint.saved` | `已保存进度` | `fa-save` |
| `task.warning` | `警告：{error_description}` | `fa-exclamation-triangle` |
| `task.completed` | `研究完成！共 18 个参考来源` | `fa-trophy` |
| `task.failed` | `研究失败：{error_description}` | `fa-times-circle` |
| `task.canceled` | `研究已取消` | `fa-ban` |

日志面板自动滚动到底部，用户手动上滚时显示「↓ 最新」浮动按钮。

**Agent 事件说明**：`agent.thought` / `agent.action` / `agent.observation` 由 Agent Runtime 在 ReAct Loop 中发布，仅追加到运行态日志，不修改 `current.status`、不推进 `phaseStates`、不影响 `progress`。`agent.thought` 的 `thought` 字段可能较长，前端存储 `fullContent` 供 tooltip 展示，日志行展示截断后的摘要。

#### 4.4.4 取消研究

```
用户点击「取消研究」
    ↓
ElMessageBox.confirm('确定要取消当前研究吗？已完成的部分将保留。')
    ↓
确认 → POST /api/research/{task_id}/cancel
    ↓
成功 → SSE 收到 task.canceled → 切换到完成态（取消视图）
失败（如已终态）→ ElMessage.error 显示原因
```

---

### 4.5 完成态：报告查看

#### 4.5.1 成功视图（status = completed / partially_completed）

```
┌────────────────────────────────────────────────────────────────────┐
│  📄 量子计算对现有密码学体系的影响分析                 [返回研究页] │
│  完成时间：2026-06-19 10:02:30 · 18 个参考来源                       │
├────────────────────────────────────────────────────────────────────┤
│ 章节导航 │ 报告正文                                  │ Evidence + Trace │
│ (160px)  │ （展开 620px / 收起 800px）                │ （展开 184px / 收起 194px） │
│ ┌──────┐ │ ┌──────────────────────────────────────┐ │ ┌──────────────┐ │
│ │ 1. … │ │ │                                      │ │ │ 来源 0       │ │
│ │ 2. … │ │ │  (Markdown 渲染的报告正文)            │ │ │ example.com  │ │
│ │ 3. … │ │ │                                      │ │ │ 相关度 92%   │ │
│ │ 4. … │ │ │  正文中包含 [来源N] 引用锚点          │ │ │ 章节 1       │ │
│ │ 5. … │ │ │  点击锚点 → 右侧面板滚动到对应条目    │ │ │              │ │
│ └──────┘ │ │                                      │ │ │ 来源 1       │ │
│          │ └──────────────────────────────────────┘ │ │ ...          │ │
│          │                                           │ │              │ │
│          │                                           │ │ Trace 摘要    │ │
│          │                                           │ │ Planning 1.2s │ │
│          │                                           │ │ ...           │ │
└──────────┴───────────────────────────────────────────┴───────────────┘
```

**布局说明**：[Deviation] 原设计将来源图谱 / Trace 摘要作为报告底部可折叠面板，实际实现为三栏布局：左侧章节导航 + 中间报告正文 + 右侧来源/Trace 面板。侧边栏展开时：报告正文 `620px`、右面板 `184px`；侧边栏收起（`body.sidebar-collapsed`）时：报告正文加宽至 `800px`、右面板加宽至 `194px`，以释放更多横向空间给主内容区。左面板固定 `160px`。最小适配宽度仍为 `1280px`。
>
> **[Deviation/修复]** 验收时发现通过缩小 SectionNav / EvidencePanel 字号来适配窄栏导致不可读。修复后保持字号可读（标题 12px、章节 14px、badge 12px），通过压缩内边距（SectionNav `8px 6px`、ReportArticle `24px 16px`、右侧面板 `12px`）和给来源卡片加 `width:100% / min-width:0 / overflow:hidden` + `line-clamp:5` 来避免横向溢出，实现「窄而长」的卡片。
>
> **[Deviation/修复]** 第三轮验收时发现来源图谱在展开态内容偏右隐藏、收起态右面板又变宽导致内容右偏。修复后：`EvidencePanel.vue` 与 `ReportViewer.vue` 的 `:deep(.evidence-panel)` 统一为 `width: 100%` 由 grid 列宽控制，禁止 `width: auto` 导致内容撑开面板；`body.sidebar-collapsed` 下右面板调整为 `--rm-evidence-panel-width: 194px`，报告正文加宽至 `--rm-report-article-width: 800px`，章节导航保持 `160px`，以在收起态释放更多主内容区空间。
>
> **[Deviation/修复]** 第四轮验收时发现来源条目过多时，右侧面板整体高度超过报告正文，Trace 摘要被压到面板最底部，页面呈现「左中空白、右满」的不平衡状态。修复后：`ResearchPage.vue` 为 `.research-page` 增加 `height: 100%` 贯通高度链，使 `.completed-state` / `.report-viewer` / `.report-body` 的百分比与 flex 高度有确定参照；`ReportViewer.vue` 将 `.report-side-panel` 改为 `overflow: hidden` 并给 `EvidencePanel` / `TracePanel` 分配固定 flex 分区；`EvidencePanel.vue` 移除 `flex-shrink: 0` 与 `justify-content: space-between`，增加 `min-height: 0`，使来源列表在侧栏上半部分内部滚动，Trace 摘要始终固定在侧栏底部可见。

#### 4.5.2 章节导航

- 左侧固定 160px 章节导航栏，根据 `report.sections[].heading` 渲染层级列表
- 当前阅读章节高亮
- 点击章节标题 → 报告正文平滑滚动到对应位置
- 每个章节标题右侧显示引用来源数量 badge

#### 4.5.3 报告正文渲染

- 使用 `markdown-it` + `highlight.js` 渲染报告 Markdown 内容
- 自动识别 `[来源N]` 引用锚点，渲染为可点击链接
- 点击引用锚点 → 来源图谱面板展开并滚动到对应条目
- 支持代码块一键复制
- 支持表格、列表、标题层级渲染

> **实现模块**：`utils/markdown.js` — markdown-it + highlight.js（github-dark 主题）+ 自定义 `[来源N]` 引用锚点 plugin（正则匹配 → `<a class="citation-link" data-evidence-index="N">`）。[Deviation] 多索引时 `data-evidence-index` 使用空格分隔（如 `"0 1"`），支持精确 CSS 选择器 `[data-evidence-index~="N"]`；原逗号分隔方案在实际联动中发现无法精确匹配单条 Evidence，故调整。ResearchMind 扩展引用锚点解析。

#### 4.5.4 来源图谱面板

- 右侧固定面板的上半部分，与 Trace 摘要上下排列
- 按 `index` 排序展示所有来源条目，在固定高度区域内独立滚动，不挤占 Trace 摘要空间
- 每条显示：`来源 N` 编号 + 可点击的来源标题/域名（点击后新标签页打开 URL）+ 内容摘要 + 相关度分数 + 所属章节 badge
- 点击条目 → 高亮报告中所有引用该来源的锚点
- 支持按章节筛选（点击章节 badge 过滤）

#### 4.5.5 Trace 摘要面板

- 右侧固定面板的下半部分，固定在侧栏底部，默认折叠
- 七阶段耗时列表，带进度条比例
- 总耗时汇总
- [Deviation] 后端 `/report` 返回的 `trace` 为嵌套结构（`{ phases, phase_durations_ms, total_duration_ms, ... }`），前端在 `reportStore.normalize()` 中将其扁平化为 `TracePanel` 期望的 `{ [phase]: { duration_ms, ... } }` 格式。
- **[Deviation/修复]** 验收时 Search / Fetch / 来源图谱 阶段 Trace 显示 "--"。修复后 `PipelineOrchestrator._complete_step` 为这三个阶段调用 `TraceRecorder.record_search` / `record_fetch` / `record_evidence_graph`；`TracePanel.stageDetail()` 字段与后端对齐：search 显示 `success_count/total_results`，fetch 显示 `success_count/total_urls`，rerank 显示 `bm25_candidates→llm_reranked`，evidence_graph 显示 `evidence_count`，render 显示 `sections_count/citations_count`。

#### 4.5.6 失败视图（status = failed）

```
┌─────────────────────────────────────────────────────────────┐
│                                                              │
│                    ❌                                        │
│              研究执行失败                                     │
│                                                              │
│      {error_description}                                     │
│                                                              │
│  失败阶段：{phase}                                            │
│                                                              │
│  ┌─ recoverable = true 时 ─────────────────────────┐        │
│  │  [🔄 断点续跑]                                     │        │
│  │  已完成的阶段不会丢失，从失败阶段继续执行                │        │
│  └────────────────────────────────────────────────┘        │
│                                                              │
│  ┌─ recoverable = false 时 ────────────────────────┐        │
│  │  该错误无法恢复，请尝试修改研究主题后重新提交            │        │
│  └────────────────────────────────────────────────┘        │
│                                                              │
│           [↩ 返回新建研究]                                    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Retry 流程**：
```
用户点击「断点续跑」
    ↓
ElMessageBox.confirm('将从上次保存的断点继续执行，是否继续？')
    ↓
确认 → emit('retry') → ResearchPage.handleRetry()
    ↓
taskStore.retryTask(taskId)
    ↓
立即乐观更新本地状态为 running（清除 error_code/error_message/recoverable）
    ↓
api/research.retryTask(taskId) → POST /api/research/{task_id}/retry
    ↓
成功 (202) → 重置运行时状态 → 立即建立 SSE 连接（不调用 fetchDetail，避免事件丢失窗口期）
           → 自动切换到运行态
    ↓
失败（409/其他）→ 回滚本地状态到失败前状态
              → ElMessage.error 显示后端 detail.error_description（兜底"当前状态不支持断点续跑"）
```

> **[Deviation/修复]** 原实现中 `retryTask()` 调用 `fetchDetail()` 获取状态后再建立 SSE 连接，但续跑 API 提交后 DB 状态仍为 `pending`（Worker 尚未拾取），导致 SSE 连接被跳过。此外 `fetchDetail()` 的网络延迟期间 Worker 已开始发布事件，SSE 未就绪则事件永久丢失。修复后：`retryTask()` 在 API 调用前即乐观更新本地状态为 running，API 成功后**立即**建立 SSE 连接，`task.status.snapshot` 提供权威状态恢复；API 失败时回滚到原状态，避免用户停留在失败态期间重复点击。
>
> **断点续跑按钮状态**：`recoverable=true` 时按钮可点击（`cursor: pointer`），二次确认后触发续跑；loading 时按钮显示旋转图标（`fa-spinner fa-spin`）并禁用，文案切换为「正在恢复…」；`recoverable=false` 时不显示续跑按钮。

**错误信息展示**：[Deviation] 后端 `task.error_message` 可能为包含 JSON 的字符串（如 `500: {'code': 'E3111', 'message': '...', 'detail': {...}}`），`FailedView.vue` 的 `displayMessage` 负责提取可读文本。
>
> **[Deviation/修复]** 第二轮验收时 `displayMessage` 已支持去掉 HTTP 前缀、解析单引号 JSON、提取 `message` / `error_description` / `detail.message`。
>
> **[Deviation/修复]** 第三轮验收时发现嵌套单引号 JSON（如 `detail.error_description` 内部仍包含 `{'error': {'message': ...}}`）会导致全局替换单引号为双引号后嵌套引号冲突，`JSON.parse` 失败并外露整串 JSON。修复后改为正则优先提取最外层 `message` / `error_description` 字段，避免依赖完整 JSON 解析。

#### 4.5.7 取消视图（status = canceled）

显示取消状态 + 已完成阶段摘要 +「返回新建研究」按钮。

---

### 4.6 侧边栏导航行为

#### 4.6.1 历史任务区域

| 操作 | 行为 |
|:---|:---|
| 点击「新建研究」| 切换到创建态，清空当前任务 |
| 点击历史任务 | 加载该任务详情（GET `/api/research/{task_id}`）并根据状态切换到运行态或完成态 |
| 任务状态图标 | ✅ completed / ⚠️ partially_completed / ❌ failed / 🚫 canceled / ⏳ running / 🔄 pending |
| 任务分组 | 按时间分组：今天 / 昨天 / 近 7 天 / 更早。分组依据字段为 `created_at` |
| 列表加载 | 首次挂载加载第 1 页 `page_size = 20`，按 `created_at` 倒序；滚动到底部时自动加载下一页，直至没有更多数据 |
| 滚动触发 | `.history-section-scroll` 滚动至距底部 `≥ 40px` 且当前未在加载中、仍有更多数据时，调用 `taskStore.fetchMore()` |
| 加载提示 | 底部显示「加载中…」或「没有更多任务了」；加载中时不允许重复触发 |
| 新建任务后 | `taskStore.createTask()` 成功后调用 `fetchList({ page: 1, page_size: 20 })`，重置列表并回到顶部 |
| 删除任务后 | 本地 `filter` 移除并 `total--`；若全部任务被删空，显示「暂无任务」空态 |

#### 4.6.2 导航链接

| 操作 | 行为 |
|:---|:---|
| 点击「历史任务」| 跳转 `/history`，查看全部历史任务分页列表 |
| 高亮状态 | 当路由在 `/history` 时，「历史任务」高亮；当路由在 `/research` 时无高亮 |

#### 4.6.3 管理后台入口（仅 admin 可见）

> **设计原则**：管理后台使用独立的 `AdminLayout` 布局，不与用户侧边栏混用。入口位于用户菜单卡片中（头像 → 用户菜单 → 「管理后台」）。

| 操作 | 行为 |
|:---|:---|
| 菜单中出现「管理后台」选项（仅 `isAdmin` 可见）| 位于「修改密码」和「退出登录」之间，图标 `fa-shield-alt` |
| 点击「管理后台」| 关闭卡片 → 跳转 `/admin`（默认 `/admin/stats`），进入独立 Admin 布局 |
| Admin 侧边栏点击「← 返回研究」| 返回 `/research`，恢复用户侧边栏 |

#### 4.6.4 用户栏行为

| 操作 | 行为 |
|:---|:---|
| 点击头像/用户名 | 弹出用户菜单卡片（修改密码 / 管理后台[admin] / 退出登录）。收起态仅有头像，`title` 提示「用户菜单」 |
| 用户菜单 → 修改密码 | 关闭卡片 → 弹出修改密码对话框 |
| 用户菜单 → 退出登录 | 关闭卡片 → 调 `POST /api/auth/logout` 吊销 refresh_token → `ElMessage.success('已退出登录')` → 清除 access_token + refresh_token → 停止 scheduleRefresh 定时器 → 跳转 `/login` |

#### 4.6.5 侧边栏展开/收起

- **切换按钮**：侧边栏顶部右侧，`fa-chevron-left`（展开态）/ `fa-chevron-right`（收起态）
- **展开态**（256px）：Logo 图标 + 副标题 + 新建研究按钮（含文字）+ 导航项（图标 + 文字）+ 用户信息（头像 + 用户名 + 角色，点击弹出用户菜单）
- **收起态**（64px）：Logo 图标居中 + 新建研究「+」图标按钮 + 导航项（仅图标，hover 显示 `title` tooltip）+ 用户头像居中
- **过渡动画**：`width var(--rm-transition-normal)`（0.2s ease）
- **状态管理**：`Sidebar.vue` 本地 `ref`，不持久化（刷新恢复展开）

#### 4.6.6 用户菜单卡片

点击头像/用户名弹出用户菜单：修改密码 + 退出登录 + 管理后台（admin）三个菜单项。布局、定位、动画、关闭行为见 §4.6.6。

---

### 4.7 修改密码对话框

弹窗布局、表单字段（当前密码/新密码/确认新密码）、校验规则、交互流程见 §4.7。调用 `PUT /api/auth/password`。

---

## 5. 历史任务页（HistoryPage — `/history`）

> **权限**：所有登录用户。用户只能看到自己的研究任务。
> **对应后端**：`GET /api/research`（分页列表）

### 5.1 页面布局

```
┌─────────────────────────────────────────────────────────────┐
│  研究历史                                                    │
│  [状态筛选▼] [搜索主题...]                        [新建研究] │
├─────────────────────────────────────────────────────────────┤
│  表格：                                                      │
│  研究主题 | 类型 | 状态 | 来源数 | 创建时间 | 操作   │
│  量子计…  | 影响 | ✅  | 18    | 2h前    | [查看]  │
│  向量数…  | 对比 | ⚠️  | 12    | 昨天    | [查看]  │
├─────────────────────────────────────────────────────────────┤
│  分页器                                                      │
└─────────────────────────────────────────────────────────────┘
```

> [Deviation] 历史页列表状态使用本地状态（`historyList` / `historyTotal` / `historyLoading`），不写入 `taskStore.taskList`。这样历史页的筛选/搜索不会影响侧边栏「最近任务」的展示；侧边栏最近任务仅由 Sidebar 自身挂载加载和新建任务成功后刷新。

### 5.2 表格列

| 列 | 说明 |
|:---|:---|
| 研究主题 | `topic`，截取前 40 字符 + tooltip 全量 |
| 类型 | `task_type` 标签（comparison=蓝 / explainer=绿 / analysis=紫） |
| 状态 | 状态标签（见 §5.3） |
| 来源数 | `total_evidence`（面向用户的「来源」即内部 Evidence Graph 的「证据」） |
| 创建时间 | `created_at` 格式化 |
| 操作 | 查看 / 删除 |

### 5.3 任务状态标签

| 状态 | 标签样式 | 图标 | 说明 |
|:---|:---|:---|:---|
| `pending` | 灰色 | `fa-clock` | 排队等待中 |
| `running` | 蓝色 + 脉冲动画 | `fa-spinner fa-spin` | 执行中 |
| `completed` | 绿色 | `fa-check-circle` | 已完成 |
| `partially_completed` | 橙色 | `fa-exclamation-triangle` | 部分完成（有降级/失败） |
| `failed` | 红色 | `fa-times-circle` | 失败 |
| `canceled` | 灰色 | `fa-ban` | 已取消 |
| `paused` [v2] | 黄色 | `fa-pause-circle` | 已暂停 |

### 5.4 交互

| 操作 | 行为 |
|:---|:---|
| 点击「新建研究」| 调用 `taskStore.clearCurrent()` 清空当前任务，再跳转 `/research` |
| 点击行 / 「查看」按钮 | 切换到 ResearchPage 并加载该任务（根据状态显示运行态或完成态） |
| 删除 | `ElMessageBox.confirm`（危险色）→ DELETE → 本地 `historyList` 移除 + `historyTotal--` |
| 筛选变更 | 重新请求列表 + 重置 `currentPage = 1`，仅更新本地历史列表 |
| 排序 | 按 `created_at` 倒序（默认） |

### 5.5 空状态

无历史任务时显示：
- 图标 + 「暂无研究任务」
- 「开始第一次研究」引导按钮 → 跳转 `/research`

---

## 6. 管理后台交互（admin 专属）

> **实现状态**：Phase 6 实现。Admin 使用独立 `AdminLayout.vue` 布局，通过用户菜单 →「管理后台」进入。

### 6.1 AdminLayout 布局

```
┌──────────────────────────────────────────────┐
│ Admin 侧边栏 (240px)    │ 主内容区            │
│ ┌──────────────────────┐ │ ┌────────────────┐ │
│ │ 🛡 管理后台          │ │ │ Header: 页标题 │ │
│ │ ResearchMind Admin   │ │ ├────────────────┤ │
│ ├──────────────────────┤ │ │                │ │
│ │ 📊 系统统计          │ │ │                │ │
│ │ 📋 任务管理          │ │ │ <slot />       │ │
│ │ 👥 用户管理          │ │ │                │ │
│ ├──────────────────────┤ │ │                │ │
│ │ ← 返回研究           │ │ │                │ │
│ └──────────────────────┘ │ └────────────────┘ │
└──────────────────────────────────────────────┘
```

### 6.2 系统统计页（`/admin/stats`）

> **后端接口**：`GET /api/admin/stats`（Phase 6）

统计卡片：用户总数、任务总数、完成任务数、失败任务数、来源总数。ECharts 图表：任务量趋势（折线图）、任务耗时分布（柱状图）、研究类型分布（饼图）。

> **实现模块**：`composables/useECharts.js` — ECharts 响应式组合式函数：自动 init/dispose + ResizeObserver 监听容器尺寸 + `setOption()` 暂存机制（解决 onMounted 前调用问题）。ResearchMind 自有实现，零改动。

### 6.3 任务管理页（`/admin/tasks`）

> **后端接口**：`GET /api/admin/tasks`（Phase 6）

跨用户查看全部研究任务，含 `username` 列。可按 `user_id`、`status`、`task_type` 筛选。可查看详情 / 取消运行中任务 / 删除（违规清理）。

### 6.4 用户管理页（`/admin/users`）

> **后端接口**：`GET /api/admin/users`（Phase 6）

管理后台用户管理功能：用户列表（筛选+分页+操作菜单）、禁用/启用、重置密码、用户详情页（统计卡片+快捷操作）。

---

## 7. 组件交互规范

### 7.1 按钮状态

| 状态 | 视觉 | 交互 |
|:---|:---|:---|
| 默认 | 主色背景 | 可点击 |
| hover | 背景加深 + 阴影 | 手型光标 |
| loading | 禁用 + 旋转图标 | 不可点击，不重复提交 |
| disabled | 透明度 0.4-0.6 | 不可点击 |

### 7.2 表单反馈

| 场景 | 反馈方式 |
|:---|:---|
| 前端校验失败 | 表单项红色边框 + 下方文字提示 |
| 提交成功 | `ElMessage.success('操作成功')` |
| 提交失败 | `ElMessage.error(msg)` 或表单内错误提示 |
| 异步操作 | 按钮 loading，操作完成后 toast 提示 |
| 退出登录 | 调 `POST /api/auth/logout` 吊销 refresh_token → `ElMessage.success('已退出登录')` → 清除 token → 停止定时器 → 跳转登录页 |
| 登录成功 | `ElMessage.success('登录成功')` → 跳转 /research |

### 7.3 加载状态

| 场景 | 加载方式 |
|:---|:---|
| 页面初始化 | 骨架屏或 spinning 全屏遮罩 |
| 表格数据 | 表格内 `v-loading` |
| 任务提交 | 按钮 loading |
| SSE 连接中 | 阶段进度条骨架屏 + 日志区 spinning |
| 报告加载 | 章节导航骨架屏 + 正文区 spinning |

### 7.4 确认操作

所有危险操作（删除任务、取消研究、删除用户、禁用用户、重置密码等）使用 `ElMessageBox.confirm` 二次确认：

```
标题：与操作语义匹配（"确认删除？"/"确认取消？"/"确认禁用？"）
内容：说明影响范围（如 "删除后不可恢复，是否继续？"）
确认按钮：危险色（el-button--danger）
取消按钮：默认
```

### 7.5 危险操作统一规范

适用操作：删除（任务）、取消（运行中任务）、禁用/启用用户、重置密码。

**统一流程**：

1. `ElMessageBox.confirm` 二次确认
2. 确认后立即启动反馈：
   - **删除类（不可逆）**：`ElLoading.service({ fullscreen: true, text: '正在删除…', background: 'rgba(0,0,0,0.5)' })`
   - **状态变更类（可逆，如取消任务）**：按钮 `:loading` 绑定
   - **表单内操作（如重置密码）**：对话框内按钮 `:loading`
3. API 成功后的列表更新策略见 §7.6
4. API 失败：关闭 loading → `ElMessage.error(msg)` → 列表状态不变
5. **`loadingInstance.close()` 必须在 `finally` 块中调用**，避免卡死

### 7.6 列表刷新策略

原则：**用户操作后优先本地更新，最小化网络请求。**

| 场景 | 策略 | 理由 |
|:---|:---|:---|
| 删除单条记录 | `list.filter()` + `total--` | 删除结果确定，无需服务端确认 |
| 取消运行中任务 | `loadList()` | 任务状态由服务端计算 |
| 批量操作 | `loadList()` | 多条记录可能影响分页和排序 |

**删除后空页回退**：如果删除当前页最后一条记录且 `currentPage > 1`，自动回退到上一页。

### 7.7 前台与后台交互差异

两个域共享 §7.1–7.6 的基础规范，以下差异允许存在：

| 维度 | 前台（用户域） | 后台（管理域） |
|:---|:---|:---|
| 数据层 | Pinia store 封装 API + 状态 | 组件内 ref + 直接 API 调用 |
| 删除后导航 | 可跳转（如删当前任务后回创建态） | 保持当前页，不移除路由 |
| SSE 连接 | 有（运行态实时追踪） | 无 |
| 操作对象 | 仅当前用户自己的任务 | 所有用户的任务 |

**禁止的差异**：

- 危险操作的确认 + loading 流程（§7.5）必须一致
- `ElMessage` 成功/失败提示格式必须一致
- 列表刷新策略（§7.6）的取舍原则必须一致

### 7.8 Admin 页面交互约定

**7.8.1 表格操作列**：单条操作使用 `el-dropdown` 或操作按钮组，每项带 icon。危险操作（删除、禁用）使用红色文字或 danger 类型按钮。

**7.8.2 筛选联动**：筛选条件变化时自动触发 `loadList()` 并重置 `currentPage = 1`。筛选期间表格显示 `v-loading`。

**7.8.3 空状态**：表格无数据时展示 `el-empty`，文案「暂无数据」；筛选无结果时文案「未找到匹配的数据」。

**7.8.4 分页**：使用 `el-pagination`，layout 包含 `total, sizes, prev, pager, next, jumper`。页码变化触发 `loadList()`。

---

## 8. SSE 流式事件交互细节

### 8.1 连接管理

前端使用 `fetch` + `ReadableStream` 读取 SSE 流（`utils/sse.js` 解析框架）。

**连接流程**：
- 任务创建成功后自动连接：`GET /api/research/{task_id}/stream`
- 通过 `response.body.getReader()` 逐块读取 SSE 数据
- 按 `\n\n` 分割事件，保留未完成的尾部片段到 buffer
- 手动断开（离开页面/取消任务）：`reader.cancel()`

**重连机制**：
- SSE 意外断开时自动重连（指数退避：1s / 2s / 4s，最多 3 次）
- 重连后收到 `task.status.snapshot` 事件 → 恢复完整进度 UI
- 用户主动取消任务时不重连
- **页面刷新自动重连**：`ResearchPage.vue` 在 `onMounted` 中检测 `current.status` 为 `running` **或 `pending`** 且 `sseStatus === 'disconnected'` 时自动调用 `connectSSE(task_id)`。`pending` 状态覆盖是断点续跑场景必需的——retry 后 Worker 拾取前存在 `pending` 窗口期，需要 SSE 连接以接收后续事件

> **[Deviation/修复]** 原 `onMounted` 自动重连仅覆盖 `running` 状态，断点续跑刷新页面后 SSE 未连接导致日志和进度事件丢失。扩展为 `running || pending` 后覆盖 retry → Worker 拾取前的窗口期。

### 8.2 SSE 心跳处理

> **权威定义**：SSE 心跳机制（15s 间隔、`: ping\n\n` 格式）见 [API.md §4](API.md#4-sse-事件协议)。

前端解析时直接跳过注释帧（以 `:` 开头的行 → `if (line.startsWith(':')) continue`）。

### 8.3 事件处理状态机

```
[idle] --创建任务--> [connecting]
[connecting] --收到 task.created / task.status.snapshot--> [streaming]
[streaming] --收到 task.completed / task.failed / task.canceled--> [idle]
[streaming] --用户取消--> [idle]
[streaming] --连接断开--> [reconnecting]
[reconnecting] --重连成功--> [streaming]
[reconnecting] --重试耗尽--> [error]
```

### 8.4 事件处理详情

| 事件类型 | 触发条件 | 前端处理 |
|:---|:---|:---|
| `task.created` | Worker 拾取任务 | 切换到运行态，初始化进度 UI |
| `task.status.snapshot` | 首次连接 / 断连重连 | 用快照数据恢复完整进度 UI（阶段状态 + Step 列表 + 进度条）。断点续跑场景下 `current_phase` 为 null 时，从已完成 `steps` 数组重建 `phaseStates`，使已完成阶段显示 ✅ 图标而非全部灰色 |
| `agent.thought` | LLM 返回 reasoning_content | 追加 Agent 思考日志，`message` 截断为 200 字符并追加省略号，完整内容存入 `fullContent` 供 tooltip 展示；不修改任务状态与进度 |
| `agent.action` | LLM 发起 Tool 调用 | 追加 Agent 动作日志：`调用 {tool_name}({arguments})`；`tool_name` / `arguments` 同时存入日志对象供组件展示 |
| `agent.observation` | Tool 执行完成并返回 observation | 追加 Agent 观察日志：`{tool_name} 结果：{observation}`；`success=false` 时日志 level 为 `warning`，否则为 `info` |
| `phase.started` | 进入新 Pipeline 阶段 | 阶段进度条：当前阶段高亮（蓝色脉冲），已完成阶段标记 ✅ |
| `phase.completed` | 当前阶段所有 Step 完成 | 阶段进度条：当前阶段标记 ✅ + 标注耗时 |
| `step.started` | Step 开始执行 | 日志区追加条目（蓝色图标 `fa-spinner fa-spin`） |
| `step.progress` | Step 有进度可报告 | 更新对应日志条目的进度信息（如 `results_found`） |
| `step.completed` | Step 执行完成 | 日志条目图标变为 ✅ |
| `step.failed` | Step 执行失败 | 日志条目图标变为 ⚠️，显示错误信息 |
| `step.skipped` | Step 被跳过 | 日志条目图标变为 ⏭️，显示跳过原因 |
| `task.progress` | 全局进度更新 | 更新整体进度条（`completed_steps / total_steps`） |
| `checkpoint.saved` | 保存了可恢复状态 | 显示「已保存进度」提示条，启用 Retry 按钮 |
| `task.warning` | 可降级失败 | 日志区追加黄色警告条目 |
| `task.completed` | 任务完成 | 关闭 SSE → 自动调 `GET /api/research/{task_id}/report` → 切换到完成态（成功视图） |
| `task.failed` | 任务致命失败 | 关闭 SSE → 切换到完成态（失败视图），显示错误信息和 Retry 按钮（`recoverable: true` 时） |
| `task.canceled` | 任务已取消 | 关闭 SSE → 切换到完成态（取消视图） |
| (注释帧) | 每 15s | `: ping\n\n`，解析时跳过，用户不可见 |

#### 8.4.1 SSE error_type 到标准 E 码映射

`taskStore` 维护 `ERROR_TYPE_TO_CODE` 常量映射表，`normalizeErrorCode()` 在接收到 SSE `task.failed` 事件时，优先将后端 `detail.error_type` 字符串转换为标准 E 码，使 SSE 路径与详情接口路径的 `error_code` 一致：

| error_type | E 码 |
|:---|:---|
| `PlanningFailed` | E3101 |
| `SearchFailed` | E3102 |
| `InsufficientEvidence` | E3103 |
| `SynthesisFailed` | E3104 |
| `RerankFailed` | E3105 |
| `EvidenceGraphFailed` | E3106 |
| `RenderFailed` | E3107 |
| `LLMTimeout` | E3108 |
| `LLMRateLimit` | E3109 |
| `LLMAuthFailed` | E3110 |
| `LLMUnknown` | E3111 |
| `CeleryWorkerLost` | E3112 |
| `CeleryWorkerNotPickedUp` | E3113 |
| `UnknownInternal` | E3999 |

> **[Deviation/修复]** 后端 SSE 发送的是 `detail.error_type`（如 `"RerankFailed"`），而详情接口返回 `error_code`（如 `"E3105"`）。首次运行态切失败态时前端将 `"RerankFailed"` 直接写入 `current.error_code`，`FailedView` 又将其下沉到「详细原因」区域，导致该区块首次渲染时错位。新增映射表后 SSE 路径与详情路径的 `error_code` 统一。未知 `error_type` 保留原始值不被清空。

### 8.5 SSE 事件设计

| 维度 | ResearchMind |
|:---|:---|
| 事件数量 | 20 种 + 注释帧 |
| 核心事件 | `phase.* / step.* / task.* / checkpoint.* / agent.*` |
| 数据方向 | Pipeline 阶段进度事件流 |
| 完成事件 | `task.completed`（含 trace 摘要） → 前端再调 report API |
| 失败事件 | `task.failed`（含 recoverable + last_checkpoint） |
| 重连 | 支持断线重连 + `task.status.snapshot` 快照恢复 |

> **权威定义**：SSE 事件的 wire format、字段表、发送规则详见 [API.md §4](../../resource/docs/API.md#4-sse-事件协议)。

---

## 9. 响应式设计边界

当前版本为桌面端优先，最小适配宽度 **1280px**。以下布局在不同宽度下的行为：

| 宽度 | 行为 |
|:---|:---|
| ≥ 1280px | 完整双栏布局（Sidebar + 主内容） |
| < 1280px | Sidebar 可收起为图标栏（64px），仅显示图标 |
| < 768px | 当前版本不做适配，提示「请使用桌面端访问」 |

---

## 10. 前端实现总结

| 维度 | ResearchMind |
|:---|:---|
| 技术栈 | Vue 3 + Vite + Pinia + Element Plus |
| Auth 体系 | 登录/注册/Token 刷新/路由守卫 |
| 布局框架 | AppLayout + AdminLayout + Sidebar |
| 设计系统 | `--rm-*` CSS 变量 |
| 核心页面 | ResearchPage（任务提交+进度+报告） |
| SSE 协议 | 18 种事件 v1.0 + 2 种预留 [v2]（Pipeline 进度流 + Agent ReAct 事件） |
| 状态管理 | auth / task / report |
| 管理后台 | 任务/用户管理 + 统计 |
| Markdown 渲染 | 研究报告渲染 |
| 图标方案 | Font Awesome 6 Free |

> **实现说明**：Auth 体系 / 布局框架 / Design Token / Markdown 渲染器 / SSE 解析框架 / ECharts composable 为 ResearchMind 自有实现，各模块锚点见 [§1.4 共享工具模块](#14-共享工具模块)。

---

## 11. 实现状态

| 模块 | 当前状态 | 实现 Phase |
|:---|:---|:---|
| 项目脚手架 | ✅ 已完成 | Phase 1 |
| Design Token 系统 | ✅ 已完成 | Phase 1 |
| Auth 体系 | ✅ 已完成 | Phase 1 |
| AppLayout + Sidebar | ✅ 已完成 | Phase 1 |
| ResearchPage（创建态） | ✅ 已完成 | Phase 2 |
| ResearchPage（运行态） | ✅ 已完成 | Phase 2 |
| ResearchPage（完成态） | ✅ 已完成 | Phase 3 |
| HistoryPage | ✅ 已完成 | Phase 2 |
| AdminLayout | ✅ 已完成 | Phase 5 |
| StatsPage | ✅ 已完成 | Phase 5 |
| AdminTaskList | ✅ 已完成 | Phase 5 |
| AdminUserList | ✅ 已完成 | Phase 5 |
| SSE 解析器 | ✅ 已完成 | Phase 2 |
| Markdown 渲染器 | ✅ 已完成 | Phase 1 |
| 响应式适配 | ✅ 已完成 | Phase 3 |

---

## 12. 相关文档

- [产品需求文档](PRD.md)
- [架构设计文档](ARCHITECTURE.md)
- [接口文档](API.md)
- [数据库设计文档](DATABASE.md)
- [研究管线深度设计](RESEARCH_PIPELINE.md)
- [开发排期](ROADMAP.md)
- [前端共享工具模块](#14-共享工具模块)
