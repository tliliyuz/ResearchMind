# PRD — ResearchMind 产品需求文档

| 属性 | 值 |
|:---|:---|
| 文档版本 | v1.0 |
| 最后更新 | 2026-06-19 |

> 本文档为 ResearchMind 的产品需求真理源，仅描述「做什么 / 为什么 / 给谁做 / 做到什么范围」。架构决策见 [ARCHITECTURE.md](../../docs/ARCHITECTURE.md)，管线详设见 [RESEARCH_PIPELINE.md](../../docs/RESEARCH_PIPELINE.md)，接口详设见 [API.md](API.md)，表结构细节见 [DATABASE.md](../../docs/DATABASE.md)，版本排期见 [ROADMAP.md](ROADMAP.md)——上述文档通过交叉引用链接到本文档对应章节。

---

## 1. 项目概述

**ResearchMind** — 面向结构化研究任务的**可审计 Agentic Research System**。

与市面上「回答问题」的 AI 搜索产品（Perplexity、Gemini Deep Research、OpenAI Deep Research）不同，ResearchMind 的核心价值不是**答案本身**，而是**可追溯的研究过程**：每一步 Planning 决策、每一次 Search 调用、每一条 Evidence 提取与排序、最终报告的每一个结论都有明确的引用锚点。用户不是在「相信一个黑盒」，而是在「审阅一份研究」。

**系统本质**：ResearchMind is built on an **agentic DAG execution model** — 研究任务被分解为可并行执行的子步骤，每个步骤拥有独立执行状态、输入输出契约和证据追踪链。它不是 Chat System、不是 QA System、不是 RAG System，而是一个 **Workflow Engine + LLM System**。

### 1.1 用户入口

ResearchMind 入口支持普通用户与管理员角色登录，登录后可创建研究任务、查看历史记录、管理系统任务。

| 原型图 | 对应页面 | 说明 |
|:---|:---|:---|
| ![登录页](../prototypes/login.png) | 登录 / 注册 | 品牌区 + Tab 切换 + 用户名/密码表单 + 提交反馈 |

### 1.2 不可替代性锚点

为什么用户有了 Perplexity / Gemini Deep Research 还需要 ResearchMind？

| 竞品 | 本质 | ResearchMind 的差异 |
|:---|:---|:---|
| Perplexity | 实时搜索 + 单轮 LLM 摘要 | ❌ 无多步骤规划，无结构化报告，无证据链 |
| Gemini/OpenAI Deep Research | 端到端黑盒，输入→等待→输出 | ❌ 过程不透明，用户无法审阅中间推理、无法审计引用、无法干预流程 |
| **ResearchMind** | **可审计的 Agentic DAG 研究引擎** | ✅ 每步状态可追踪、每个结论有引用锚点、报告结构可自证 |

**一句话**：ResearchMind 不是在卖「更好的答案」，而是在卖「令人信服的研究过程」。

### 1.3 MVP 范围（v1.0）

**Single-shot Deep Research Lite** — 一次输入 → 一次完整 Research Run → 一份结构化报告。

| MVP 做 | MVP 不做 |
|:---|:---|
| ✅ 单次研究主题输入 | ❌ 多轮追问 Refinement |
| ✅ 线性 DAG 编排（Tree 结构） | ❌ 递归分解（Recursive Decomposition） |
| ✅ 1-3 分钟快速研究，5-15 信息源，2-5 页报告 | ❌ Long-running Research Graph（10-30 分钟，30+ 源） |
| ✅ 结构化报告 + Section 级引用映射 | ❌ 用户干预 Planning（Human-in-the-loop） |
| ✅ SSE 实时流式研究过程展示 | ❌ Agent Workflow Editor / 可视化编排 |

> **架构预留**：数据库状态机、Celery Pipeline、DAG 节点定义均按深度研究设计，MVP 仅实现最简单执行路径。完整的版本演进（v1.0 / v1.5 / v2.0）见 [ROADMAP.md](ROADMAP.md)。

v1.0 运行态通过 SSE 实时展示 Pipeline 七阶段进度、Step 日志与取消操作，页面原型如下：

| 原型图 | 对应页面 | 说明 |
|:---|:---|:---|
| ![运行态](../prototypes/running.png) | 研究执行中 | Pipeline 七阶段进度条、Step 实时日志、已用时与取消操作 |

### 1.4 研究任务类型

ResearchMind 面向三类 Research Intent，而非特定用户角色：

| 任务类型 | 特征 | 示例输入 |
|:---|:---|:---|
| **对比型研究** (comparison) | 结构化对比、多源属性提取、维度对齐 | "2025年主流向量数据库对比：Milvus vs Qdrant vs Weaviate" |
| **解释型研究** (explainer) | 观点聚类、弱结构输入、综合性强 | "Transformer 注意力机制的最新改进方向" |
| **影响分析型** (analysis) | 因果推理、跨域综合、前瞻推断 | "量子计算对现有密码学体系的影响及应对方案" |

> 三种任务类型映射到不同的 Planner 策略、Reranker 排序维度、Report 模板。各类型的 Pipeline 策略映射见 [ARCHITECTURE.md §2.2](../../docs/ARCHITECTURE.md#22-pipeline-七阶段定义) 和 [RESEARCH_PIPELINE.md §2.4](../../docs/RESEARCH_PIPELINE.md#24-planner-策略按-task_type)。

### 1.5 创建任务流程

用户登录后进入研究创建页，输入主题、选择任务类型、配置高级选项后提交任务。创建页与高级选项展开态原型如下：

| 原型图 | 对应页面 | 说明 |
|:---|:---|:---|
| ![研究创建页](../prototypes/research_create.png) | 研究任务创建 | 主题输入区、研究类型三选一卡片、快捷示例 |
| ![研究创建页-高级选项](../prototypes/research_create_2.png) | 研究任务创建（高级选项展开） | max_sources 滑块、language 选择、depth 配置 |

创建任务的具体字段、校验规则、前端状态机见 [FRONTEND.md §3](../../frontend/docs/FRONTEND.md#3-researchpage-三态状态机)。

### 1.6 任务与历史管理

用户可在历史任务列表查看所有研究任务，支持按状态筛选、主题搜索、分页浏览、单条删除与取消操作。

| 原型图 | 对应页面 | 说明 |
|:---|:---|:---|
| ![历史列表](../prototypes/history.png) | 历史任务 | 状态筛选、主题搜索、任务表格、分页与删除 |

### 1.7 研究成果输出

研究完成后进入报告页，呈现章节导航 + Markdown 正文 + Evidence 图谱三栏联动布局。点击 `[来源N]` 锚点可展开 Evidence 面板并定位到对应证据条目。

| 原型图 | 对应页面 | 说明 |
|:---|:---|:---|
| ![报告页](../prototypes/report.png) | 研究报告查看 | 章节导航 + Markdown 正文 + 来源图谱三栏联动 |

报告渲染与 Evidence Graph 面板的交互规则见 [FRONTEND.md §5](../../frontend/docs/FRONTEND.md#5-reportpage-报告页)。

---

## 2. 相关文档

- [架构设计文档](../../docs/ARCHITECTURE.md)
- [研究管线设计文档](../../docs/RESEARCH_PIPELINE.md)
- [接口文档](API.md)
- [数据库设计文档](../../docs/DATABASE.md)
- [前端交互设计文档](../../frontend/docs/FRONTEND.md)
- [开发排期](ROADMAP.md)
