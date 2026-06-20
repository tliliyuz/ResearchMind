# ResearchMind — 可审计的 Agentic Research System

**ResearchMind** 不是「更好的 AI 搜索」，而是**可追溯、可审计的结构化研究引擎**——每一步 Planning 决策、每一次 Search 调用、每一条 Evidence 提取与排序、最终报告的每一个结论都有明确的引用锚点。

---

## 与 DocMind 的关系

ResearchMind 是**完全独立的项目**，不与 DocMind 共享数据库、代码或运行时。

| | DocMind | ResearchMind |
|:---|:---|:---|
| 知识来源 | 企业内部文档（PDF/DOCX） | 公开网络信息（Web Search） |
| 交互模式 | 同步问答（请求-流式响应） | 异步研究任务（提交-执行-完成） |
| 系统本质 | 检索增强生成（RAG） | Agentic DAG 编排（Agentic Workflow） |
| 输出 | 流式答案 + 源文档引用 | 结构化研究报告 + 段落级 URL 引用映射 |
| 核心链路 | 意图识别→双路检索→RRF→Rerank→LLM SSE | 任务规划→搜索→解析→证据排序→综合→证据图谱→报告渲染 |

ResearchMind 在工程结构（分层、表设计、Auth、错误码体例）上借鉴了 DocMind 的设计思路，但已全部内化为自有实现。详见 [PRD.md §1.1](docs/PRD.md#11-与-docmind-的关系) 和 [INFRASTRUCTURE_REUSE.md](docs/INFRASTRUCTURE_REUSE.md)。

---

## 技术栈

| 层面 | 技术 |
|:---|:---|
| 后端框架 | FastAPI（异步 Python，原生 SSE） |
| 异步任务 | Celery + Redis（任务编排 + 断点续跑） |
| LLM | deepseek-v4-pro（DeepSeek SDK，MVP 单一模型） |
| 搜索 | Tavily API（含内容提取） |
| Rerank | BM25 + LLM Rerank（粗筛 + 精排） |
| 数据库 | MySQL + aiomysql + SQLAlchemy 2.0 async |
| 迁移 | Alembic |
| 部署 | Docker Compose（4 服务：FastAPI + Celery Worker + Redis + MySQL） |
| 时区 | 四层 UTC 统一（MySQL → 后端 → API → 前端） |

详见 [ARCHITECTURE.md §1](docs/ARCHITECTURE.md#1-技术选型)。

---

## 快速开始

> **当前状态**：项目处于设计阶段，尚未开始编码。以下为启动后端开发的最小步骤（计划中）。

```bash
# 1. 克隆仓库
git clone <repo-url> && cd ResearchMind

# 2. 创建 Python 虚拟环境
python -m venv .venv && source .venv/Scripts/activate  # Windows
# 或 source .venv/bin/activate  # Linux/macOS

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 LLM_API_KEY、MYSQL_PASSWORD 等

# 5. 初始化数据库
alembic upgrade head

# 6. 启动后端
uvicorn app.main:app --reload --port 8000

# 7. 启动 Celery Worker（另一终端）
celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4
```

完整开发环境搭建见 [DEVELOPMENT.md](docs/DEVELOPMENT.md)。

---

## 文档索引

| 文档 | 用途 |
|:---|:---|
| [PRD.md](docs/PRD.md) | 产品需求真理源 — 做什么、为什么、给谁做、MVP 范围 |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构设计真理源 — 技术选型、分层、状态机、权限、非功能需求 |
| [RESEARCH_PIPELINE.md](docs/RESEARCH_PIPELINE.md) | 管线深度设计 — 7 阶段 Prompt 模板、算法策略、SSE 事件映射 |
| [API.md](docs/API.md) | 接口规范真理源 — REST 端点、SSE 协议、请求/响应模型、错误码 |
| [DATABASE.md](docs/DATABASE.md) | 数据库设计真理源 — 表结构、索引、外键、级联策略 |
| [INFRASTRUCTURE_REUSE.md](docs/INFRASTRUCTURE_REUSE.md) | 基础设施复用清单 — 从 DocMind 可复用的模块及适配说明 |
| [ROADMAP.md](docs/ROADMAP.md) | 版本演进路线 — v1.0 / v1.5 / v2.0 |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发环境搭建、项目结构、编码约定 |
| [CHANGELOG.md](docs/CHANGELOG.md) | 变更日志（Keep a Changelog 格式） |

---

## License

TBD
