# ResearchMind

**Agentic Research System based on Phase-Locked ReAct.**

ResearchMind 不是「更好的 AI 搜索」，而是可追溯、可审计的结构化研究 Agent。

在 Perplexity、Gemini Deep Research 这类产品里，用户输入一个主题，等待几十秒，拿到一份答案——但你看不到答案是怎么来的，也无法审计每一个结论的证据是否可靠。ResearchMind 解决的是**研究过程的可信度问题**：LLM 在 **Phase-Locked ReAct Loop** 中通过 **Tool Calling** 自主决策调用 Planning、Search、Fetch、Rerank、Synthesis、Evidence Graph Build 等阶段工具，每一次推理、每一个动作、每一条观察都实时推送前端并持久化到工作记忆，最终报告的每一个结论都有明确的引用锚点和执行状态。

ResearchMind 基于 **Agentic DAG 执行模型** 构建：研究任务由 **Agent Runtime** 驱动，LLM 通过 Tool Calling 在 Phase-Locked ReAct Loop 中自主调度研究阶段，每个 Tool Call 拥有独立执行状态、输入输出契约和证据追踪链。它不是 Chat System、不是 QA System、不是传统 RAG System，也不是固定 Workflow，而是一个 **Agentic Research System**。

![研究运行态](resource/prototypes/running.png)

---

## 目录

| 序号 | 主题 | 描述 |
|:---|:---|:---|
| 1 | [核心特性](#核心特性) | Phase-Locked ReAct、Tool Calling、Evidence Graph、断点续跑、Worker 崩溃恢复 |
| 2 | [系统架构](#系统架构) | 核心引擎与表达层分层、Agent Runtime、三层状态模型 |
| 3 | [技术栈](#技术栈) | 后端、Agent Runtime、AI、检索、存储、前端、部署各层技术选型 |
| 4 | [规模量化](#规模量化) | 代码、测试、文档的实测规模数据 |
| 5 | [核心链路](#核心链路) | 研究任务从提交到报告渲染的端到端流程 |
| 6 | [界面预览](#界面预览) | 登录、研究创建、运行态、历史列表、报告页截图 |
| 7 | [快速开始](#快速开始) | Docker Compose 部署与本地开发环境指引 |
| 8 | [项目结构](#项目结构) | 后端、Pipeline、Agent Runtime、前端、测试目录树 |
| 9 | [质量保障](#质量保障) | 测试金字塔、评估指标、回归通过率 |
| 10 | [设计文档](#设计文档) | PRD / 架构 / 管线 / 数据库 / API / 前端 / UI 文档索引 |
| 11 | [常见问题](#常见问题) | 研究类型、证据引用、断点续跑、私有化部署问答 |
| 12 | [License](#license) | 开源协议 |

---

## 核心特性

**Phase-Locked ReAct Agent Runtime**：研究执行引擎由 `AgentRuntime` 驱动，LLM 按 Planning → Search → Fetch → Rerank → Synthesis → Evidence Graph Build 的固定阶段顺序推进，但在每个 phase 内可基于当前上下文多次调用允许的 Tool。这种「ReAct 推理 + Phase 阶段锁」的混合架构既保留 Agent 的灵活性，又保证七阶段业务语义和可审计性。

**Tool Calling + Tool Registry**：所有研究阶段均被抽象为 `Tool`（`ToolResult` / `ToolCall` / `ToolContext`），由 `ToolRegistry` 按 name/phase 管理并生成 OpenAI Function Calling schema。既有 phase handler 通过 `PhaseHandlerTool` 薄适配层包装为 Tool，新增全局辅助 Tool（`finish_tool`、`memory_tool`）控制循环结束与工作记忆读写。

**Working Memory（工作记忆）**：内存级 ReAct Trace，容量 `AGENT_WORKING_MEMORY_MAX_ENTRIES=20`，并逐条持久化到 `agent_memory_entries` 表。支持断点续跑、审计 Agent 推理链、为下一轮 LLM 调用提供完整上下文。

**Evidence Graph（结构化认知资产）**：核心产物不是报告本身，而是段落 → 证据 → 来源的结构化图谱。证据条目 `evidence_items` 与报告章节 `report_sections` 通过 `section_evidence` 多对多关联，确保每个结论都可追溯到具体 URL 片段。

**断点续跑**：基于 Execution Context + Trace 合并，任意 Phase 失败后可以从断点恢复。已完成阶段的 Token / Cost 数据持久化，恢复后不丢失、不重复计算；前端提供一键「断点续跑」按钮与 SSE 重连恢复。

**Worker 崩溃自动恢复**：任务级租约锁（TTL 20s + 10s 续期）+ 超时监察者（5s 扫描 / 10s 超时判定）+ 启动时/Worker-ready 双入口恢复，覆盖 SIGKILL、OOM、断电等场景。

**三类研究任务类型**：对比型（comparison）、解释型（explainer）、影响分析型（analysis）。不同 task_type 驱动 Planner 拆解策略、Rerank 排序维度与 Report 模板选择。

**agent.* SSE 实时研究过程**：18 种 SSE 事件类型（task.* / phase.* / step.* / checkpoint.* / agent.*）实时推送，包含 Agent 思考、Tool 调用、观察结果。客户端断线后重连可立即获得完整状态快照，并基于 `seq` 序号丢弃乱序事件。

**私有化部署**：Docker Compose 4 服务编排（FastAPI + Celery Worker + Redis + MySQL），环境变量与配置完全自持，适合本地或内网部署。

---

## 系统架构

ResearchMind 架构分为两层：**核心引擎由 Agent Runtime 驱动，产出 Evidence Graph，表达层将其渲染为不同形态的报告**。

```
┌─────────────────────────────────────────────┐
│            Presentation Layer               │
│  Report Render（Markdown + 引用锚点）        │
├─────────────────────────────────────────────┤
│            Core Research Engine             │
│                                             │
│         ┌───────────────────┐               │
│         │   AgentRuntime    │               │
│         │  Phase-Locked     │               │
│         │    ReAct Loop     │               │
│         └─────────┬─────────┘               │
│                   │                         │
│    ┌──────────────┼──────────────┐          │
│    ▼              ▼              ▼          │
│  Planning → Search → Fetch → Rerank →       │
│  Synthesis → Evidence Graph Build           │
│                                             │
│  核心产物：Evidence Graph                    │
│  (结构化认知资产，独立于任何报告格式)          │
└─────────────────────────────────────────────┘
```

**为什么要分层？**

| 混在一起 | 分开 |
|:---|:---|
| Synthesis 和 Report 耦合，换模板需重跑全 Pipeline | Evidence Graph 是稳定中间产物，Report Render 可单独重跑 |
| 无法支持同一研究产出多份报告 | 一个 Graph → 多模板渲染 |
| 报告格式变更侵入核心引擎 | 表达层独立演进 |

Agent Runtime 详细设计见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 技术栈

### 通用技术栈

| 层面 | 技术 | 说明 |
|:---|:---|:---|
| 后端框架 | FastAPI | 异步 Python，原生 SSE |
| 异步任务 | Celery + Redis | 任务编排 + 断点续跑 |
| LLM | deepseek-v4-pro (DeepSeek SDK) | MVP 单一模型，后续分级 |
| 搜索 | Tavily API | 含内容提取 |
| Rerank | BM25 + LLM Rerank | 粗筛 + 精排 |
| 关系数据库 | MySQL + aiomysql + SQLAlchemy 2.0 async | 所有业务数据 |
| 迁移 | Alembic | 所有 schema 变更走迁移脚本 |
| 部署 | Docker Compose | 4 服务：FastAPI + Celery Worker + Redis + MySQL |
| 时区 | 四层 UTC 统一 | MySQL → 后端 → API → 前端全链路 UTC |

### Agent Runtime 技术栈

详见 [ARCHITECTURE.md §1](docs/ARCHITECTURE.md#1-技术选型)，核心组件包括：

| 层面 | 技术 / 模式 | 说明 |
|:---|:---|:---|
| Agent 架构模式 | Phase-Locked ReAct Loop | LLM 推理 → Tool 调用 → Observation 反馈 → 下一轮 |
| Agent 调度器 | `AgentRuntime` | 负责任务生命周期、Step 创建/完成/失败、checkpoint 持久化 |
| Phase 锁定 | `PhaseController` | 固定 7 phase 顺序，每 phase 内可多次 Tool Call |
| 工作记忆 | `WorkingMemory` + `agent_memory_entries` | 内存级 ReAct Trace + 持久化，容量 20 条 |
| Agent 上下文 | `AgentContext` | 记录 current_phase、iteration、finished 等 |
| Tool 抽象 | Tool Protocol / `ToolResult` / `ToolCall` / `ToolContext` | 统一 Tool 接口与参数校验 |
| Tool 注册中心 | `ToolRegistry` | 按 name/phase 管理 Tool，生成 OpenAI Function Calling schema |
| LLM 调用 | DeepSeek API（OpenAI 兼容） | 返回 `reasoning_content + tool_calls` |
| Agent SSE 事件 | `agent.thought` / `agent.action` / `agent.observation` | 实时推送 Agent 推理链 |
| 循环控制 | 配置驱动 | `MAX_AGENT_ITERATIONS=30`，防止无限循环 |

### 前端技术栈

| 层面 | 技术 | 说明 |
|:---|:---|:---|
| 前端框架 | Vue 3 + Vite | Composition API + `<script setup>` |
| UI 组件库 | Element Plus | 主题色通过 `--rm-*` Design Token 覆盖 |
| 状态管理 | Pinia | Vue 3 官方推荐 |
| Markdown | markdown-it + highlight.js | 报告正文渲染 + 代码块高亮 |
| 图表 | ECharts 6 | 管理后台统计可视化 |

---

## 规模量化

| 维度 | 数量 | 说明 |
|:---|:---|:---|
| 后端应用代码 | 75 文件 / 13,745 行 Python | `app/` 目录 |
| 后端测试代码 | 55 文件 / 17,054 行 | `tests/` 目录 |
| 前端代码 | 39 文件 / 7,859 行 | Vue SFC + JS |
| 前端测试代码 | 22 文件 / 4,676 行 | `frontend/tests/` |
| 设计文档 | 10+ 份 Markdown | PRD / 架构 / 管线 / 数据库 / API / 排期 / 前端 / UI / 开发 |
| 架构决策记录 | `docs/decisions/` | 随版本迭代持续补充 |

---

## 核心链路

**单次研究任务链路**：

```
用户提交研究主题
    ↓
Agent Runtime 启动 Phase-Locked ReAct Loop
    ↓
Planning：LLM 拆解为子问题
    ↓
Search：Tavily 检索每个子问题，获取 URL / 标题 / 摘要
    ↓
Fetch：抓取网页正文并截断
    ↓
Rerank：BM25 粗筛 + LLM 精排，按相关性+信息量排序
    ↓
Synthesis：LLM 跨源综合、冲突识别、观点聚类
    ↓
Evidence Graph Build：构建段落 → 证据 → 来源映射
    ↓
Report Render：按 task_type 渲染 Markdown + [来源N] 引用锚点
    ↓
用户查看报告，点击引用锚点联动 Evidence Graph 面板
```

Agent Runtime、Tool System、Working Memory 的详细设计见 [ARCHITECTURE.md §2.3](docs/ARCHITECTURE.md#23-agent-runtime-核心机制)，Pipeline 各阶段输入/输出数据结构、Prompt 模板、失败策略、SSE 事件映射详见 [RESEARCH_PIPELINE.md](docs/RESEARCH_PIPELINE.md)。

---

## 界面预览

### 登录

ResearchMind 入口，支持普通用户与管理员角色登录。

| 页面 | 截图 |
|:---|:---|
| 登录 | ![登录页](resource/prototypes/login.png) |

### 研究创建

核心交互起点：输入研究主题、选择任务类型、配置深度与来源数量。

| 页面 | 截图 |
|:---|:---|
| 研究创建 | ![研究创建页](resource/prototypes/research_create.png) |
| 高级选项展开 | ![研究创建页-高级选项](resource/prototypes/research_create_2.png) |

### 研究运行

Pipeline 七阶段进度条、Step 实时日志、Agent 思考/调用/观察事件、已耗时与取消操作。

| 页面 | 截图 |
|:---|:---|
| 运行态 | ![运行态](resource/prototypes/running.png) |

### 历史任务

状态筛选、主题搜索、任务表格、分页与删除。

| 页面 | 截图 |
|:---|:---|
| 历史列表 | ![历史列表](resource/prototypes/history.png) |

### 研究报告

章节导航 + Markdown 正文 + 来源图谱三栏联动。

| 页面 | 截图 |
|:---|:---|
| 报告页 | ![报告页](resource/prototypes/report.png) |

---

## 快速开始

### Docker Compose 部署（推荐）

前置要求：Docker 20.10+ 和 Docker Compose 2.0+。

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY、MYSQL_PASSWORD、JWT_SECRET_KEY 等

# 2. 构建并启动全部服务（FastAPI + Celery Worker + Redis + MySQL）
docker-compose up -d --build

# 3. 执行数据库迁移
docker-compose exec api alembic upgrade head

# 4. 访问
#    前端页面：http://localhost
#    后端 API：http://localhost/api
```

生产环境务必修改 `.env` 中的 `JWT_SECRET_KEY`（64 字符随机字符串）、`MYSQL_PASSWORD`、`LLM_API_KEY` 等敏感配置，并确认 `DEBUG=false`。

### 本地开发

前置要求：Python 3.11+、Node.js 18+、MySQL 8.0+、Redis 7.0+。

**后端**：

```bash
# 项目根目录即为后端工作目录
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 创建 .env，填入实际凭证（参考 resource/docs/DEVELOPMENT.md §4）

alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 另开终端启动 Celery Worker
# Linux/Mac:
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4
# Windows（必须加 --pool=solo）:
celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
```

**前端**：

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173，/api 自动代理到后端 8000 端口
```

详细环境变量、依赖清单、编码约定见 [DEVELOPMENT.md](resource/docs/DEVELOPMENT.md)。

---

## 项目结构

```
ResearchMind/
├── app/                         # 后端源码（项目根目录，无 backend/ 子目录）
│   ├── agent/                   # Agent Runtime（Phase-Locked ReAct Loop）
│   │   ├── loop.py              # AgentLoop：ReAct 循环控制
│   │   ├── runtime.py           # AgentRuntime：任务生命周期与状态流转
│   │   ├── state.py             # PhaseController：phase 推进
│   │   ├── memory.py            # WorkingMemory：ReAct Trace 工作记忆
│   │   ├── context.py           # AgentContext：Agent 上下文
│   │   └── prompts.py           # 动态 system prompt + phase instruction
│   ├── api/                     # 路由层（仅参数校验 + 调 service）
│   │   └── auth / research
│   ├── core/                    # 基础设施（database / exceptions / llm / redis / security / sse / trace_recorder / task_state_resolver / ...）
│   ├── middleware/              # JWT 认证 / 限流 / Request ID
│   ├── models/                  # SQLAlchemy ORM 模型（User / ResearchTask / ResearchStep / ResearchSource / EvidenceItem / ReportSection / AgentMemoryEntry / RefreshToken + UTCDateTime）
│   ├── pipeline/                # 7 阶段研究管线独立模块
│   │   ├── planner.py           # Planning：主题拆解
│   │   ├── searcher.py          # Search：Tavily 检索
│   │   ├── fetcher.py           # Fetch：网页抓取
│   │   ├── reranker.py          # Rerank：BM25 + LLM 精排
│   │   ├── synthesizer.py       # Synthesis：跨源综合
│   │   ├── evidence_graph.py    # Evidence Graph Build：结构化证据映射
│   │   ├── renderer.py          # Report Render：Markdown + 引用锚点
│   │   ├── bm25.py / fusion.py / sentence_matcher.py / types.py
│   │   └── sse_bridge.py        # Pipeline / Agent 事件 → SSE 事件桥接
│   ├── schemas/                 # Pydantic 请求/响应模型
│   ├── services/                # 业务逻辑层
│   │   ├── auth_service.py
│   │   ├── research_service.py
│   │   ├── agent_memory_service.py
│   │   └── pipeline_orchestrator.py  # DEPRECATED：旧 Workflow 编排，保留供历史参考
│   ├── tasks/                   # Celery 异步任务（celery_app / research_task / lock / recovery / watcher）
│   ├── tools/                   # Tool System
│   │   ├── base.py              # Tool Protocol / ToolResult / ToolCall / ToolContext / PhaseHandlerTool
│   │   ├── registry.py          # ToolRegistry：Tool 注册与 schema 生成
│   │   ├── finish_tool.py       # 显式结束 Agent Loop
│   │   └── memory_tool.py       # 读写 Working Memory
│   ├── evaluation/              # 离线评估（search / fetch / rerank / system / manual / aggregator）
│   └── main.py                  # FastAPI 入口 + lifespan（启动恢复）
├── alembic/                     # 数据库迁移脚本
├── docs/                        # 公用设计文档
│   ├── ARCHITECTURE.md          # 架构设计
│   ├── DATABASE.md              # 数据库设计
│   ├── RESEARCH_PIPELINE.md     # 研究管线深度设计
│   ├── CHANGELOG.md             # 变更日志
│   └── decisions/               # 架构决策记录（ADR）
├── resource/
│   ├── docs/                    # 后端/产品相关设计文档（PRD / API / ROADMAP / DEVELOPMENT）
│   └── prototypes/              # 产品原型图
├── frontend/
│   ├── docs/                    # 前端设计文档（FRONTEND.md / UIDESIGN.md）
│   ├── src/
│   │   ├── views/               # 页面（LoginPage / ResearchPage / HistoryPage / ReportPage / Admin 管理后台）
│   │   ├── components/          # 组件
│   │   ├── stores/              # Pinia 状态管理
│   │   ├── api/                 # HTTP 请求封装
│   │   ├── router/              # Vue Router
│   │   ├── composables/         # useECharts 等组合式函数
│   │   ├── styles/              # Design Token（--rm-* CSS 变量）
│   │   └── utils/               # SSE 解析 / Markdown 渲染 / 格式化
│   └── tests/                   # 前端测试（vitest）
├── tests/                       # 后端测试（pytest）
│   ├── unit/                    # 单元测试
│   ├── integration/             # 集成测试
│   └── regression/              # 回归测试
├── docker-compose.yml           # 4 服务编排
├── Dockerfile.backend           # 后端镜像
├── Dockerfile.frontend          # 前端镜像
└── nginx.server.conf            # 反向代理 + SSE 支持 + SPA fallback
```

---

## 质量保障

| 指标 | 目标 | 当前 |
|:---|:---|:---|
| 后端单元测试 | 全部通过 | 800+ 用例，100% 通过 |
| 后端集成测试 | 全部通过 | Agent Runtime + Pipeline 全链路覆盖 |
| 回归测试通过率 | 100% | Worker 崩溃恢复、断点续跑、Retry/Cancel |
| 前端测试 | 全部通过 | 组件 + Store + Util 覆盖 |
| 离线评估 | 持续监控 | Search / Fetch / Rerank / System 多维度评估 |

测试覆盖 5 个层次：单元测试、接口测试、前端组件测试、离线检索评估、回归测试。完整测试策略见 [TESTING_STRATEGY.md](tests/TESTING_STRATEGY.md)。

---

## 设计文档

| 文档 | 说明 |
|:---|:---|
| [PRD.md](resource/docs/PRD.md) | 产品需求文档 — 业务场景、研究任务类型、MVP 范围、验收标准 |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构设计文档 — 技术选型、Agent Runtime、三层状态模型、权限模型 |
| [RESEARCH_PIPELINE.md](docs/RESEARCH_PIPELINE.md) | 研究管线深度设计 — Prompt 模板、算法策略、SSE 事件映射、失败策略 |
| [DATABASE.md](docs/DATABASE.md) | 数据库设计文档 — ER 关系、表 DDL、索引、外键级联策略 |
| [API.md](resource/docs/API.md) | 接口文档 — REST 端点、SSE 协议、请求/响应模型、错误码 |
| [DEVELOPMENT.md](resource/docs/DEVELOPMENT.md) | 开发指南 — 环境配置、依赖清单、本地启动、Docker 部署 |
| [ROADMAP.md](resource/docs/ROADMAP.md) | 版本演进路线 — v1.0 / v1.5 / v2.0 |
| [TESTING_STRATEGY.md](tests/TESTING_STRATEGY.md) | 测试策略 — 测试金字塔、Mock 策略、覆盖率目标、离线评估 |
| [FRONTEND.md](frontend/docs/FRONTEND.md) | 前端交互文档 — 页面布局、三态状态机、SSE 处理、组件行为 |
| [UIDESIGN.md](frontend/docs/UIDESIGN.md) | UI 设计规范 — Design Token（CSS 变量）、组件样式、布局尺寸 |
| [CHANGELOG.md](docs/CHANGELOG.md) | 变更日志 — 遵循 Keep a Changelog 格式 |
| [docs/decisions/](docs/decisions/) | 架构决策记录（ADR） |

---

## 常见问题

**Q: ResearchMind 适合做什么类型的研究？**
当前支持三类任务类型：对比型（如向量数据库选型对比）、解释型（如 Transformer 注意力机制改进方向）、影响分析型（如量子计算对密码学的影响）。不同类型会触发不同的 Planner 策略和报告模板。

**Q: ResearchMind 与 Perplexity / Gemini Deep Research 的区别是什么？**
Perplexity 是实时搜索 + 单轮摘要，无多步骤规划和证据链；Gemini/OpenAI Deep Research 是端到端黑盒，过程不可审计。ResearchMind 是 **可审计的 Agentic Research System**：LLM 在 Phase-Locked ReAct Loop 中通过 Tool Calling 自主执行每个研究阶段，每一次推理、动作、观察都实时可见，最终结论可通过 Evidence Graph 追溯到原始来源。

**Q: 报告中的 `[来源N]` 引用是怎么生成的？**
Pipeline 在 Evidence Graph Build 阶段建立 `章节 → 证据 → 来源` 的映射，Report Render 阶段按模板输出 `[来源N]` 锚点。点击锚点会展开 Evidence 面板并滚动到对应证据条目，展示原始 URL 与片段。

**Q: 断点续跑是什么意思？**
每个 Step 完成后，系统会把当前阶段、已完成 Step、执行指针、进度、Agent Context、Working Memory 等写入 `execution_context`。如果 Worker 崩溃或任务失败，用户可以点击「断点续跑」，系统会从最后一个完成 Step 的下一个 Step 继续执行，而不是从头开始。

**Q: 可以私有化部署吗？**
可以。ResearchMind 提供 Docker Compose 4 服务编排，数据完全存储在自有 MySQL 中，LLM 通过配置接入 DeepSeek 或其他 OpenAI 兼容接口，搜索使用 Tavily API。

**Q: Worker 崩溃后任务会丢失吗？**
不会。系统通过 `acks_late=True`、任务级租约锁、超时监察者和启动恢复机制，确保崩溃任务在租约过期后自动重新入队并恢复执行。

---

## License

TBD
