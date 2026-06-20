# CHANGELOG — 变更日志

> 本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/) 格式。
>
> 版本号使用 [语义化版本](https://semver.org/lang/zh-CN/)：`MAJOR.MINOR.PATCH`。
>
> 分类：`Added`（新增）、`Changed`（变更）、`Deprecated`（弃用）、`Removed`（移除）、`Fixed`（修复）、`Security`（安全修复）。

---

## [Unreleased]

> 项目处于设计阶段，尚未开始编码。以下为初始化条目。

### Added
- 项目初始化：创建 ResearchMind 仓库
- 产品需求文档 [PRD.md](PRD.md)
- 架构设计文档 [ARCHITECTURE.md](ARCHITECTURE.md)
- 研究管线设计文档 [RESEARCH_PIPELINE.md](RESEARCH_PIPELINE.md)
- 接口文档 [API.md](API.md)
- 数据库设计文档 [DATABASE.md](DATABASE.md)
- 基础设施复用清单 [INFRASTRUCTURE_REUSE.md](INFRASTRUCTURE_REUSE.md)
- 版本演进路线 [ROADMAP.md](ROADMAP.md)
- 开发指南 [DEVELOPMENT.md](DEVELOPMENT.md)
- 项目入口 [README.md](../README.md)
- 前端交互设计文档 [FRONTEND.md](FRONTEND.md)
- 前端基础设施复用清单 [INFRASTRUCTURE_REUSE_FRONTEND.md](INFRASTRUCTURE_REUSE_FRONTEND.md)
- 前端 UI 样式规范 [UIDESIGN.md](UIDESIGN.md)（Design Token `--rm-*` 体系，提取自 `ai_studio_code.html` 静态原型）

### Fixed
- API.md §5.3：E3107 `recoverable` 从 `false` 修正为 `true`（与 RESEARCH_PIPELINE.md §8.7/§8.9 一致——Render 失败可复用 Evidence Graph 重渲）
- ARCHITECTURE.md line 77：API.md 交叉引用从 §2 修正为 §3（研究任务接口）
- ROADMAP.md line 20：API.md 交叉引用从 §2 修正为 §3（研究任务接口）
- ARCHITECTURE.md line 195：DATABASE.md 交叉引用从 §3 修正为 §2（表结构）

### Changed
- 无

### Deprecated
- 无

### Removed
- 无

### Security
- 无

---

## [0.1.0] — 2026-06-20（设计阶段）

### Added
- 完成全部 7 份设计文档初稿
- 确立文档驱动开发流程与归属矩阵
- 确立 Infrastructure Reuse 策略（从 DocMind 复用 Auth、LLM、异常体系、SSE 流式推送）
