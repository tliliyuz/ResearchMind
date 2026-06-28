# API — 接口文档

| 属性 | 值 |
|:---|:---|
| 文档版本 | v1.0 |
| 最后更新 | 2026-06-28 |

> 本文档是 **REST API 端点、请求/响应模型、SSE 事件协议、错误码体系** 的唯一真理源。相关定义禁止在其他文档中重复，应使用交叉引用链接到本文档对应章节。研究任务的输入输出数据契约、状态机语义见 [ARCHITECTURE.md](ARCHITECTURE.md)，Pipeline 各阶段深度设计见 [RESEARCH_PIPELINE.md](RESEARCH_PIPELINE.md)，表结构（持久化的请求/响应字段）见 [DATABASE.md](DATABASE.md)，产品需求见 [PRD.md](PRD.md)。

---

## 1. 通用约定

### 1.1 基础信息

| 项目 | 值 |
|:---|:---|
| Base URL | `http://localhost:8000/api` |
| 认证方式 | Bearer Token（JWT），登录后携带 `Authorization: Bearer <token>` |
| Content-Type | `application/json` |
| 字符编码 | UTF-8 |
| 时间字段 | ISO 8601 + `+00:00`（UTC，详见 [DATABASE.md §0 时区约定](DATABASE.md#0-时区约定)） |

### 1.2 通用响应格式

> **`code` 字段类型约定**：`code` 字段**统一为字符串类型**。成功时 `"0"`，错误时 `"E2001"` 等错误码字符串。前端解析时勿作整数类型判断。
>
> **[Deviation]** ResearchMind 的 `detail` 为**结构化 JSON 对象**（`error_type` + `error_description` + 可选 `recoverable`/`retry_after_ms`），与 docmind 基类 `AppException.detail: str`（扁平字符串）不同。实现时需扩展 `AppException` 构造函数，支持 `detail: dict | str` 并据此序列化响应。

**成功响应：**

```json
{
  "code": "0",
  "message": "ok",
  "data": { /* 业务数据 */ }
}
```

**错误响应：**

```json
{
  "code": "E2001",
  "message": "任务不存在",
  "detail": {
    "error_type": "TaskNotFound",
    "error_description": "task_id 不存在或已被删除",
    "recoverable": false
  }
}
```

> 研究执行类错误（E3xxx）的 `detail` 还可携带 `retry_after_ms`、`last_checkpoint` 等可恢复语义字段，详见 §5。

### 1.3 时间字段约定

所有 datetime 字段统一返回 ISO 8601 格式的 UTC 时间。

示例：

```json
{
  "created_at": "2026-06-19T10:00:00+00:00",
  "completed_at": "2026-06-19T10:02:30+00:00"
}
```

说明：
- `+00:00` 表示 UTC 时区
- `Z` 与 `+00:00` 在语义上等价
- 前端应使用标准 `Date` API 解析，不应手动补时区后缀

### 1.4 统一错误码

#### 认证与权限错误（E1xxx）

> **[Deviation]** 认证错误码段从 docmind 的 E5xxx（E5001-E5010）重新编号为 E1xxx（E1001-E1011）。`PasswordSameAsCurrentException` 从 E7004 移入 E1011。错误码语义与 HTTP 状态码保持一致，编号规则为 ResearchMind 自行设计。

| 错误码 | HTTP 状态码 | 说明 |
|:---|:---|:---|
| E1001 | 409 | 用户名已存在 |
| E1002 | 401 | 用户名或密码错误 |
| E1003 | 401 | Token 已过期 |
| E1004 | 401 | Token 无效或格式错误 |
| E1005 | 403 | 无权限执行此操作 |
| E1006 | 401 | Refresh Token 已过期 |
| E1007 | 401 | Refresh Token 已吊销 |
| E1008 | 401 | Refresh Token 无效或格式错误 |
| E1009 | 401 | Token 疑似泄露（Rotation 检测到旧 token 被重用，已吊销全部会话） |
| E1010 | 401 | 用户已被禁用（status=disabled） |
| E1011 | 400 | 新密码不能与原密码相同 |
| E1012 | 429 | 登录频率超限 |

#### 研究任务错误（E2xxx）

| 错误码 | HTTP 状态码 | 说明 |
|:---|:---|:---|
| E2001 | 404 | 任务不存在 |
| E2002 | 403 | 无权访问该任务（非 owner 且非 admin） |
| E2003 | 409 | 当前任务状态不支持该操作 |
| E2004 | 400 | 任务已被取消，无法继续 |
| E2005 | 400 | 研究主题超过 500 字符 |
| E2006 | 400 | task_type 不在 comparison / explainer / analysis 之内 |
| E2007 | 400 | depth 取值非法（MVP 仅支持 quick） |
| E2008 | 400 | requirements 字段缺失或非法 |
| E2009 | 403 | 该操作需要管理员权限 |

#### 研究执行错误（E3xxx）

> **完整定义**：[§5.3 研究执行错误](API.md#53-研究执行错误e3xxx) — 包含 `recoverable`、`retry_after_ms`、重试次数等可恢复语义字段。

| 错误码 | HTTP 状态码 | 说明 |
|:---|:---|:---|
| E3101 | 500 | LLM 无法拆解研究主题（Planning 重试耗尽） |
| E3102 | 503 | Tavily API 完全不可用（重试耗尽） |
| E3103 | 500 | 证据量不满足最小阈值 |
| E3104 | 500 | LLM 综合失败（Synthesis 重试耗尽） |
| E3105 | 500 | Rerank 输入格式错误或计算失败 |
| E3106 | 500 | Evidence Graph 构建失败 |
| E3107 | 500 | 报告渲染失败 |
| E3108 | 502 | LLM 调用超时（重试耗尽） |
| E3109 | 429 | LLM API 限流（指数退避后仍失败） |
| E3110 | 401 | LLM 认证失败（重试无意义） |
| E3111 | 500 | LLM 调用返回未预期错误 |
| E3112 | 500 | Celery Worker 崩溃/丢失（可断点续跑） |
| E3999 | 500 | 未预期的内部错误（Worker 兜底） |

#### 系统通用错误（E9xxx）

| 错误码 | HTTP 状态码 | 说明 |
|:---|:---|:---|
| E9001 | 500 | 服务器内部错误 |
| E9002 | 503 | 服务暂不可用 |
| E9003 | 422 | 请求参数校验失败 |
| E9004 | 429 | 请求频率超限 |

> **错误码分段规则**：`E1xxx` = 认证与权限；`E2xxx` = 研究任务；`E3xxx` = 研究执行（Pipeline 各阶段）；`E9xxx` = 系统通用。完整错误码表（含 `recoverable`、`error_type`、重试策略等字段）见 §5。
>
> **限流配置**：创建任务 5 次/分钟/用户（→ E9004），登录 10 次/分钟（→ E1012），全局默认 120 次/分钟（→ E9004）。详见 [ARCHITECTURE.md §5.2](ARCHITECTURE.md#52-并发与系统容量)。

### 1.5 工程约定

| 约束 | 说明 |
|:---|:---|
| JWT Bearer Token 鉴权 | 通过 `current_user` 依赖注入获取当前用户 |
| SSE 事件流 | 全 Pipeline 事件实时推送，事件协议见 §4 |
| 所有时间戳 ISO 8601 + `+00:00` | 四层 UTC 统一 |

---

## 2. 认证接口

> ResearchMind 是独立系统，自建用户体系与 JWT 鉴权。`access_token` 15 分钟短有效期降低泄露风险；`refresh_token` 7 天长有效期避免频繁登录。
>
> Refresh Token 持久化至 `refresh_tokens` 表（MySQL），支持 Rotation 与泄露检测。表结构将在 [DATABASE.md](DATABASE.md) 中补充。

### POST `/api/auth/register`

**权限**：公开

注册新用户。

**请求**：

```json
{
  "username": "zhangsan",
  "password": "mypassword123"
}
```

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| username | string | 是 | 用户名（3-64 字符，唯一） |
| password | string | 是 | 密码（≥ 6 字符） |

**响应** (201)：

```json
{
  "code": "0",
  "message": "注册成功",
  "data": {
    "id": 1,
    "username": "zhangsan",
    "role": "user",
    "created_at": "2026-06-19T10:00:00+00:00"
  }
}
```

**错误响应**：

| 场景 | 错误码 | HTTP 码 |
|:---|:---|:---|
| 用户名已存在 | E1001 | 409 |
| 参数校验失败 | E9003 | 422 |

---

### POST `/api/auth/login`

**权限**：公开

登录并获取 token 对。

**请求**：

```json
{
  "username": "zhangsan",
  "password": "mypassword123"
}
```

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| username | string | 是 | 用户名 |
| password | string | 是 | 密码 |

**响应** (200)：

```json
{
  "code": "0",
  "message": "登录成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 900
  }
}
```

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| access_token | string | JWT 访问令牌，有效期 15 分钟 |
| refresh_token | string | JWT 刷新令牌，有效期 7 天（MySQL 持久化，支持 Rotation） |
| token_type | string | 固定 `bearer` |
| expires_in | int | access_token 有效期（秒），900 = 15 分钟 |

**错误响应**：

| 场景 | 错误码 | HTTP 码 |
|:---|:---|:---|
| 用户名或密码错误 | E1002 | 401 |
| 用户已被禁用 | E1010 | 401 |

---

### POST `/api/auth/refresh`

**权限**：公开（携带 refresh_token）

用 refresh_token 换取新的 token 对。每次刷新后旧 refresh_token 立即失效（Rotation）。

**请求**：

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| refresh_token | string | 是 | 有效的 refresh_token |

**响应** (200)：

```json
{
  "code": "0",
  "message": "Token 刷新成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 900
  }
}
```

**错误响应**：

| 场景 | 错误码 | HTTP 码 |
|:---|:---|:---|
| refresh_token 已过期（> 7 天） | E1006 | 401 |
| refresh_token 已被吊销 | E1007 | 401 |
| refresh_token 格式无效 | E1008 | 401 |
| 使用已吊销的旧 token 请求刷新（疑似泄露） | E1009 | 401 |
| 用户已被禁用 | E1010 | 401 |

> **泄露检测（E1009）**：当用户正常刷新后攻击者仍使用旧 refresh_token 请求刷新，说明 token 可能已泄露。此时系统吊销该用户所有 refresh_token，强制全部设备重新登录。

---

### POST `/api/auth/logout`

**权限**：user（需登录）

吊销当前 refresh_token，access_token 在短有效期后自然过期。

**请求**：

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| refresh_token | string | 是 | 需吊销的 refresh_token |

**响应** (200)：

```json
{
  "code": "0",
  "message": "已退出登录",
  "data": null
}
```

---

### PUT `/api/auth/password`

**权限**：user（需登录）

修改密码后吊销该用户全部 refresh_token，强制所有设备重新登录。

**请求**：

```json
{
  "old_password": "mypassword123",
  "new_password": "newpassword456"
}
```

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| old_password | string | 是 | 当前密码 |
| new_password | string | 是 | 新密码（≥ 6 字符） |

**响应** (200)：

```json
{
  "code": "0",
  "message": "密码修改成功，所有设备已下线",
  "data": null
}
```

**错误响应**：

| 场景 | 错误码 | HTTP 码 |
|:---|:---|:---|
| 旧密码错误 | E1002 | 401 |
| 新密码与原密码相同 | E1011 | 400 |

> **安全机制**：改密后吊销全部 refresh_token，防止密码被篡改后攻击者通过未过期的 refresh_token 继续访问。

---

## 3. 研究任务接口

### 3.1 任务生命周期

#### POST `/api/research`

**权限**：user（需登录）

创建研究任务。任务创建后立即返回，Celery Worker 异步拾取执行。通过 SSE（§4）或轮询 `/state` 端点跟踪进度。

**请求**：

```json
{
  "topic": "量子计算对现有密码学体系的影响",
  "requirements": {
    "task_type": "analysis",
    "depth": "quick",
    "max_sources": 10,
    "language": "zh"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| topic | string | 是 | 研究主题（≤ 500 字符） |
| requirements | object | 是 | 研究要求配置 |
| requirements.task_type | string | 是 | `comparison` / `explainer` / `analysis`（必填，决定 Planner 策略、Rerank 维度、Report 模板） |
| requirements.depth | string | 是 | 研究深度，MVP 仅支持 `quick` |
| requirements.max_sources | int | 是 | 信息源数量上限（1-50） |
| requirements.language | string | 是 | 报告语言，如 `zh` / `en` |

> **`task_type` 为什么必填？** 它直接决定 Planner 的拆解策略、Rerank 的排序维度、Report Render 的模板选择，不能用「LLM 自己猜」替代。各 task_type 对应的阶段策略见 [ARCHITECTURE.md §2.2](ARCHITECTURE.md#22-pipeline-七阶段定义)。
>
> **[Planned: v1.5+]** `requirements` 将扩展 `focus_areas`、`exclude_domains`、`time_range`、`must_include_sources` 字段。

**响应** (201)：

```json
{
  "code": "0",
  "message": "研究任务已创建",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "pending",
    "created_at": "2026-06-19T10:00:00+00:00"
  }
}
```

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| task_id | string (UUID) | 任务唯一标识 |
| status | string | 初始状态为 `pending` |
| created_at | string | 创建时间（ISO 8601 UTC） |

**错误响应**：

| 场景 | 错误码 | HTTP 码 |
|:---|:---|:---|
| topic 超过 500 字符 | E2005 | 400 |
| task_type 非法 | E2006 | 400 |
| depth 非法 | E2007 | 400 |
| requirements 缺失或非法 | E2008 | 400 |
| 参数校验失败 | E9003 | 422 |
| 请求频率超限（5 次/分钟/用户） | E9004 | 429 |

---

#### GET `/api/research`

**权限**：user（需登录）

获取当前用户的研究任务历史列表（分页），按 `created_at` 倒序。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页条数，默认 20，最大 100 |
| status | string | 否 | 按状态过滤（`pending` / `running` / `completed` / `partially_completed` / `failed` / `canceled` / `paused [v2]`） |
| keyword | string | 否 | 按主题关键字模糊搜索（`ILIKE` 匹配） |

**响应** (200)：

```json
{
  "code": "0",
  "message": "ok",
  "data": {
    "total": 8,
    "page": 1,
    "page_size": 20,
    "items": [
      {
        "task_id": "550e8400-e29b-41d4-a716-446655440000",
        "topic": "量子计算对现有密码学体系的影响",
        "status": "completed",
        "task_type": "analysis",
        "total_sources": 10,
        "total_evidence": 18,
        "created_at": "2026-06-19T10:00:00+00:00",
        "completed_at": "2026-06-19T10:02:30+00:00"
      }
    ]
  }
}
```

---

#### GET `/api/research/{task_id}`

**权限**：user（需登录，仅 owner 或 admin）

查询单个任务的状态与摘要信息。

**路径参数**：

| 参数 | 类型 | 说明 |
|:---|:---|:---|
| task_id | string (UUID) | 任务 ID |

**响应** (200)：

```json
{
  "code": "0",
  "message": "ok",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "topic": "量子计算对现有密码学体系的影响",
    "status": "running",
    "current_phase": "fetching",
    "requirements": {
      "task_type": "analysis",
      "depth": "quick",
      "max_sources": 10,
      "language": "zh"
    },
    "progress": {
      "completed_steps": 7,
      "total_steps": 12,
      "progress": 0.58
    },
    "created_at": "2026-06-19T10:00:00+00:00",
    "started_at": "2026-06-19T10:00:05+00:00"
  }
}
```

> **`progress` 字段映射**：API 响应中的 `progress` 对象是顶层便利字段，其数据来源为数据库 `research_tasks.execution_context` JSON 列中的 `progress` 子对象。前端不应直接访问 `execution_context`（该字段为内部实现细节），统一使用 `progress` 即可。`execution_context` 的完整结构见 [ARCHITECTURE.md §3.3](ARCHITECTURE.md#33-execution-context断点续跑的核心)。

**错误响应**：

| 场景 | 错误码 | HTTP 码 |
|:---|:---|:---|
| 任务不存在 | E2001 | 404 |
| 无权访问 | E2002 | 403 |

---

#### DELETE `/api/research/{task_id}`

**权限**：user（需登录，仅 owner 或 admin）

删除研究任务及其全部派生数据（Steps、Sources、Evidence、Report Sections）。通过 FK `ON DELETE CASCADE` 级联清理。

**路径参数**：

| 参数 | 类型 | 说明 |
|:---|:---|:---|
| task_id | string (UUID) | 任务 ID |

**响应** (200)：

```json
{
  "code": "0",
  "message": "研究任务已删除",
  "data": null
}
```

**错误响应**：

| 场景 | 错误码 | HTTP 码 |
|:---|:---|:---|
| 任务不存在 | E2001 | 404 |
| 无权访问 | E2002 | 403 |

---

### 3.2 执行控制

#### POST `/api/research/{task_id}/cancel`

**权限**：user（需登录，仅 owner 或 admin）

取消正在运行的任务。Worker 收到中断信号后保存当前 checkpoint 并停止执行。

**路径参数**：

| 参数 | 类型 | 说明 |
|:---|:---|:---|
| task_id | string (UUID) | 任务 ID |

**响应** (200)：

```json
{
  "code": "0",
  "message": "任务已取消",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "canceled"
  }
}
```

**错误响应**：

| 场景 | 错误码 | HTTP 码 |
|:---|:---|:---|
| 任务不存在 | E2001 | 404 |
| 无权访问 | E2002 | 403 |
| 任务已处于终态，无法取消 | E2003 | 409 |

> 仅 `pending` / `running` / `paused [v2]` 状态可取消。已处于终态（`completed` / `failed` / `partially_completed` / `canceled`）时返回 E2003。

---

#### POST `/api/research/{task_id}/retry`

**权限**：user（需登录，仅 owner 或 admin）

从最后 checkpoint 断点续跑。已完成的 Step 结果复用，不重新执行。

**前置条件**：`task.status` 必须为 `failed`、`partially_completed` 或 `canceled`，且 `recoverable = true`。

**路径参数**：

| 参数 | 类型 | 说明 |
|:---|:---|:---|
| task_id | string (UUID) | 任务 ID |

**响应** (202)：

```json
{
  "code": "0",
  "message": "断点续跑已启动",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "running",
    "resume_from": {
      "phase": "fetching",
      "last_completed_step_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "next_step_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901"
    }
  }
}
```

**错误响应**：

| 场景 | 错误码 | HTTP 码 |
|:---|:---|:---|
| 任务不存在 | E2001 | 404 |
| 无权访问 | E2002 | 403 |
| 当前状态不支持 retry（如 `running`） | E2003 | 409 |

```json
{
  "code": "E2003",
  "message": "当前任务状态不支持该操作",
  "detail": {
    "error_type": "InvalidTaskState",
    "error_description": "任务当前状态为 running，不支持 retry 操作",
    "current_status": "running",
    "allowed_statuses": ["failed", "partially_completed", "canceled"]
  }
}
```

---

### 3.3 结果获取

#### GET `/api/research/{task_id}/report`

**权限**：user（需登录，仅 owner 或 admin）

获取完整的结构化研究报告（含 Evidence Graph 与 Trace）。

**路径参数**：

| 参数 | 类型 | 说明 |
|:---|:---|:---|
| task_id | string (UUID) | 任务 ID |

**响应** (200)：

```json
{
  "code": "0",
  "message": "ok",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "completed",
    "report": {
      "title": "量子计算对现有密码学体系的影响分析",
      "generated_at": "2026-06-19T10:02:30+00:00",
      "sections": [
        {
          "heading": "1. 量子计算威胁概述",
          "content": "Markdown 正文...",
          "sources": [
            {"id": 1, "evidence_index": 0},
            {"id": 2, "evidence_index": 1}
          ]
        }
      ],
      "sources": [
        {
          "id": 1,
          "url": "https://www.nist.gov/pqc/faq",
          "title": "NIST PQC FAQ",
          "domain": "nist.gov"
        }
      ]
    },
    "evidence_graph": {
      "items": [
        {
          "index": 0,
          "source_id": 1,
          "content": "RSA is vulnerable to Shor's algorithm...",
          "relevance_score": 0.92,
          "used_in_sections": ["1"]
        }
      ]
    },
    "trace": {
      "planning": {"sub_questions": ["..."], "duration_ms": 1200},
      "search": {"total_results": 45, "selected": 10, "duration_ms": 3500},
      "fetch": {"successful": 9, "failed": 1, "duration_ms": 8200},
      "rerank": {"input_candidates": 52, "output_evidence": 18, "duration_ms": 800},
      "synthesis": {"duration_ms": 4500},
      "evidence_graph": {"item_count": 18, "duration_ms": 400},
      "render": {"template": "analysis", "duration_ms": 6000}
    }
  }
}
```

> `evidence_graph.items[]` 已预留 span 级字段（`content`、`relevance_score`），证据粒度演进见 [ROADMAP.md §1](ROADMAP.md#1-证据粒度演进路线)。
>
> **`index` 字段说明**：`evidence_graph.items[].index` 是运行时生成的虚拟字段——每个 Evidence Graph 内从 0 开始的全图唯一递增序号，表示该证据在报告中的引用编号（即正文中 `[来源N]` 的 N）。它**不等于** `evidence_items.id`（数据库自增主键），每次 Render 时重新生成。详见 [DATABASE.md §2.5](DATABASE.md#25-证据条目表-evidence_items)。

**错误响应**：

| 场景 | 错误码 | HTTP 码 |
|:---|:---|:---|
| 任务不存在 | E2001 | 404 |
| 无权访问 | E2002 | 403 |
| 任务尚未完成 | E2003 | 409 |

---

#### GET `/api/research/{task_id}/state`

**权限**：user（需登录，仅 owner 或 admin）

获取执行状态快照（REST 版），是 SSE `task.status.snapshot` 事件的 REST 等价物，供前端断线恢复或轮询使用。

**路径参数**：

| 参数 | 类型 | 说明 |
|:---|:---|:---|
| task_id | string (UUID) | 任务 ID |

**响应** (200)：

```json
{
  "code": "0",
  "message": "ok",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "running",
    "current_phase": "fetching",
    "progress": {
      "completed_steps": 7,
      "total_steps": 12,
      "progress": 0.58
    },
    "steps": [
      {
        "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "phase": "searching",
        "step_type": "search",
        "status": "completed",
        "label": "搜索子问题 1",
        "started_at": "2026-06-19T10:00:35+00:00",
        "completed_at": "2026-06-19T10:00:42+00:00",
        "duration_ms": 7000,
        "error_code": null,
        "error_message": null
      }
    ],
    "topics": "量子计算在药物发现中的应用",
    "created_at": "2026-06-19T10:00:00+00:00",
    "started_at": "2026-06-19T10:00:05+00:00",
    "completed_at": null,
    "error": {
      "error_code": "E3101",
      "error_message": "Planning 阶段重试耗尽",
      "recoverable": false
    },
    "stats": {
      "total_sources": 25,
      "total_evidence": 42
    },
    "execution_pointer": {
      "_comment": "[v2] 未实现",
      "phase": "fetching",
      "step_index": 3,
      "total_steps_in_phase": 10
    },
    "last_completed_step": {
      "_comment": "[v2] 未实现",
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "type": "search",
      "completed_at": "2026-06-19T10:00:42+00:00"
    },
    "checkpoints": {
      "_comment": "[v2] 未实现",
      "items": [
        {
          "phase": "planning",
          "step_id": "b2c3d4e5-f6a7-8901-bcde-f1234567890",
          "saved_at": "2026-06-19T10:00:12+00:00"
        }
      ]
    }
  }
}
```

---

#### GET `/api/research/{task_id}/stream`

**权限**：user（需登录，仅 owner 或 admin）

SSE 连接端点，研究过程实时推送。事件协议详见 §4。

**路径参数**：

| 参数 | 类型 | 说明 |
|:---|:---|:---|
| task_id | string (UUID) | 任务 ID |

**响应**：`text/event-stream` (SSE)

> SSE 重连恢复与三层状态模型（Task / Phase / Step）的同步关系见 [ARCHITECTURE.md §3.6](ARCHITECTURE.md#36-sse-事件与状态同步)。

---

### 3.4 [v2] 暂停/恢复

#### POST `/api/research/{task_id}/pause`

> **[v2 规划]** 暂停正在运行的任务。v1.0 不支持。

#### POST `/api/research/{task_id}/resume`

> **[v2 规划]** 恢复已暂停的任务。v1.0 不支持。

---

### 3.5 系统健康检查

#### GET `/api/health/workers`

**权限**：公开（运维端点，无需认证）

检查 Celery Worker 集群健康状态。调用 `celery_app.control.ping(timeout=5.0)` 获取活跃 Worker 列表。

**响应** (200) — 有 Worker：

```json
{
  "code": "0",
  "message": "ok",
  "data": {
    "status": "healthy",
    "worker_count": 2,
    "workers": ["celery@host1", "celery@host2"]
  }
}
```

**响应** (200) — 无 Worker：

```json
{
  "code": "0",
  "message": "ok",
  "data": {
    "status": "no_workers",
    "worker_count": 0,
    "workers": []
  }
}
```

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| status | string | `healthy` 或 `no_workers`（非错误，仅表示当前无活跃 Worker） |
| worker_count | int | 活跃 Worker 数量 |
| workers | string[] | Worker 节点名称列表（Celery `ping()` 返回的 `{hostname: ok}` 键名） |

---

## 4. SSE 事件协议

> **SSE 实现方式**：手动 `StreamingResponse`（非 `sse-starlette`），完全控制事件序列。每 15 秒发送 `: ping\n\n` 注释帧（SSE 心跳）保持连接，防止 Nginx/Cloudflare 代理超时断连。浏览器忽略注释帧。

### 4.1 事件类型总览

| 事件 | 触发时机 | 携带数据 | 前端行为 |
|:---|:---|:---|:---|
| `task.created` | 任务被 Worker 拾取 | task_id, status | 初始化进度 UI |
| `task.status.snapshot` | 客户端首次连接 / 断连重连 | 当前完整状态快照（同 REST `/state`） | 恢复进度 UI 到当前状态 |
| `phase.started` | 进入新 Pipeline 阶段 | phase, timestamp | 高亮当前阶段 |
| `phase.completed` | 当前阶段所有 Step 完成 | phase, duration_ms | 标记阶段完成 |
| `step.started` | Step 开始执行 | step_id, step_type, label | 显示 "正在搜索子问题 1..." |
| `step.progress` | Step 执行中有进度可报告 | step_id, 阶段特定字段（如 `results_found`） | 更新 Step 进度条 |
| `step.completed` | Step 执行完成 | step_id, output 摘要 | 标记 Step 完成 |
| `step.failed` | Step 执行失败 | step_id, error_type | 显示警告或错误 |
| `step.skipped` | Step 被跳过（降级） | step_id, reason | 显示跳过标记 |
| `task.progress` | 全局进度更新 | completed_steps, total_steps, progress | 更新整体进度条 |
| `checkpoint.saved` | 系统保存了可恢复状态 | phase, last_completed_step_id, saved_at | 显示 "已保存进度"，启用 Retry 按钮 |
| `task.warning` | 可降级失败发生（不影响流程） | step_id, error_description | 显示黄色警告 |
| `task.completed` | 任务完成 | task_id, status, trace 摘要 | 显示完成 UI，允许获取报告 |
| `task.failed` | 任务致命失败 | task_id, error_type, error_description, recoverable | 显示错误 UI；`recoverable: true` 时显示 Retry 按钮 |
| `task.canceled` | 任务已取消 | task_id | 显示取消状态 |
| `task.paused` [v2] | 任务已暂停 | task_id | 显示暂停状态，提供恢复按钮 |
| `task.resumed` [v2] | 任务已恢复 | task_id, status | 恢复进度 UI，继续接收增量事件 |

### 4.2 SSE 连接生命周期

```
Client connects → GET /api/research/{task_id}/stream

  ┌─ 任务尚未开始 (PENDING)
  │    → task.created（延迟到 Worker 拾取后）
  │
  ├─ 任务正在运行 (RUNNING)
  │    → task.status.snapshot（立即推送完整快照）
  │    → 后续增量事件（phase / step / task.progress / checkpoint.saved）
  │
  └─ 任务已结束 (COMPLETED / FAILED / CANCELED)
       → task.status.snapshot（包含最终状态）
       → 连接关闭
```

### 4.3 SSE 事件格式示例

#### `event: task.created`

```
event: task.created
data: {"task_id": "550e8400-e29b-41d4-a716-446655440000", "status": "running", "created_at": "2026-06-19T10:00:05+00:00"}
```

#### `event: phase.started`

```
event: phase.started
data: {"phase": "searching", "timestamp": "2026-06-19T10:00:06+00:00"}
```

#### `event: step.started`

```
event: step.started
data: {"step_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "step_type": "search", "label": "搜索子问题 1：NIST PQC 标准进展"}
```

#### `event: step.progress`

```
event: step.progress
data: {"step_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "results_found": 15}
```

#### `event: step.completed`

```
event: step.completed
data: {"step_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "output": {"results_count": 15, "selected": 5}}
```

#### `event: task.progress`

```
event: task.progress
data: {"completed_steps": 7, "total_steps": 12, "progress": 0.58}
```

#### `event: task.completed`

```
event: task.completed
data: {"task_id": "550e8400-e29b-41d4-a716-446655440000", "status": "completed", "trace": {"total_duration_ms": 150000, "sources": 10, "evidence": 18}}
```

#### `event: task.failed`

```
event: task.failed
data: {"task_id": "550e8400-e29b-41d4-a716-446655440000", "error_type": "SynthesisFailed", "error_description": "LLM 综合失败，已重试 3 次", "recoverable": true, "last_checkpoint": "b2c3d4e5-f6a7-8901-bcde-f12345678901"}
```

---

## 5. 错误码表（完整）

错误码采用字符串类型（如 `"E2001"`），按业务域分段，每段内连续编号。HTTP 状态码与错误码一一对应。

### 5.1 认证与权限错误（E1xxx）

| 错误码 | HTTP | 错误类型 | 说明 |
|:---|:---|:---|:---|
| E1001 | 409 | `UsernameExists` | 用户名已存在 |
| E1002 | 401 | `InvalidCredentials` | 用户名或密码错误 |
| E1003 | 401 | `TokenExpired` | Access Token 已过期 |
| E1004 | 401 | `TokenInvalid` | Token 无效或格式错误 |
| E1005 | 403 | `Forbidden` | 无权限执行该操作 |
| E1006 | 401 | `RefreshTokenExpired` | Refresh Token 已过期 |
| E1007 | 401 | `RefreshTokenRevoked` | Refresh Token 已吊销 |
| E1008 | 401 | `RefreshTokenInvalid` | Refresh Token 无效或格式错误 |
| E1009 | 401 | `TokenReuseDetected` | Token 疑似泄露（Rotation 检测到旧 token 被重用，已吊销全部会话） |
| E1010 | 401 | `UserDisabled` | 用户已被禁用（status=disabled） |
| E1011 | 400 | `SamePassword` | 新密码不能与原密码相同 |

### 5.2 研究任务错误（E2xxx）

任务生命周期、状态、所有权相关错误。

| 错误码 | HTTP | 错误类型 | 说明 |
|:---|:---|:---|:---|
| E2001 | 404 | `TaskNotFound` | task_id 不存在 |
| E2002 | 403 | `TaskNotOwned` | 无权访问该任务（非 owner 且非 admin 审计） |
| E2003 | 409 | `InvalidTaskState` | 当前任务状态不支持该操作（如 RUNNING 不允许 retry） |
| E2004 | 400 | `TaskCanceled` | 任务已被取消，无法继续 |
| E2005 | 400 | `TopicTooLong` | 研究主题超过 500 字符 |
| E2006 | 400 | `InvalidTaskType` | task_type 不在 comparison / explainer / analysis 之内 |
| E2007 | 400 | `InvalidDepth` | depth 取值非法（MVP 仅支持 quick） |
| E2008 | 400 | `InvalidRequirements` | requirements 字段缺失或非法 |
| E2009 | 403 | `AdminRequired` | 该操作需要管理员权限 |

### 5.3 研究执行错误（E3xxx）

Pipeline 各阶段失败。`recoverable` 决定是否可断点续跑，`retry_after_ms` 建议重试等待时间。失败分类学详见 [ARCHITECTURE.md §5.5](ARCHITECTURE.md#55-failure-model失败分类学)。

| 错误码 | HTTP | 错误类型 | recoverable | 重试次数 | 说明 |
|:---|:---|:---|:---|:---|:---|
| E3101 | 500 | `PlanningFailed` | false | 3 | LLM 无法拆解研究主题（重试耗尽） |
| E3102 | 503 | `SearchBackendUnavailable` | true | 2 | Tavily API 完全不可用（重试耗尽） |
| E3103 | 500 | `InsufficientEvidence` | false | — | 证据量不满足最小阈值（见 [ARCHITECTURE.md §3.5](ARCHITECTURE.md#35-部分失败策略与-evidence-completeness-threshold)） |
| E3104 | 500 | `SynthesisFailed` | true | 3 | LLM 综合失败（重试耗尽） |
| E3105 | 500 | `RerankFailed` | false | 2 | Rerank 输入格式错误或计算失败 |
| E3106 | 500 | `EvidenceGraphBuildFailed` | false | — | Evidence Graph 构建失败 |
| E3107 | 500 | `RenderFailed` | true | 1 | 报告渲染失败 |
| E3108 | 502 | `LLMTimeout` | true | 3 | LLM 调用超时（重试耗尽） |
| E3109 | 429 | `LLMRateLimited` | true | 3（指数退避） | LLM API 限流（指数退避后仍失败） |
| E3110 | 401 | `LLMAuthFailed` | false | — | LLM 认证失败（重试无意义） |
| E3111 | 500 | `LLMUnknownError` | true | 3 | LLM 调用返回未预期错误 |
| E3112 | 500 | `CeleryWorkerLost` | true | — | Celery Worker 崩溃/丢失（DB checkpoint 完整，可从 `execution_context` 断点续跑） |
| E3999 | 500 | `UnknownInternal` | false | — | 未预期的内部错误（Pipeline Worker 崩溃/未捕获异常兜底） |

**`recoverable` 字段语义：**

| recoverable | 含义 | 前端行为 |
|:---|:---|:---|
| `true` | 任务可从最后 checkpoint 断点续跑，已完成阶段不丢失 | 显示 Retry 按钮，引导用户续跑 |
| `false` | 致命错误，重试没有意义（如 LLM 认证失败、参数校验失败） | 显示错误说明，不提供 Retry |
| 不返回 | 传统错误（非可恢复语义不适用） | 按传统错误处理 |

> 仅研究执行类错误（E3xxx）适用 `recoverable` / `retry_after_ms` / `last_checkpoint`；认证与系统类错误不携带这些字段。

### 5.4 系统通用错误（E9xxx）

| 错误码 | HTTP | 错误类型 | 说明 |
|:---|:---|:---|:---|
| E9001 | 500 | `InternalError` | 服务器内部错误（未预期） |
| E9002 | 503 | `ServiceUnavailable` | 服务暂不可用 |
| E9003 | 422 | `ValidationError` | 请求参数校验失败 |
| E9004 | 429 | `RateLimited` | 请求频率超限（见 [ARCHITECTURE.md §5.2](ARCHITECTURE.md#52-并发与系统容量)） |

---

## 6. 完整请求/响应示例

### 6.1 正常研究流程

**Step 1 — 用户注册**：

```
POST /api/auth/register
Content-Type: application/json

{
  "username": "zhangsan",
  "password": "mypassword123"
}
```

**响应**：

```json
HTTP/1.1 201 Created
Content-Type: application/json

{
  "code": "0",
  "message": "注册成功",
  "data": {
    "id": 1,
    "username": "zhangsan",
    "role": "user",
    "created_at": "2026-06-19T10:00:00+00:00"
  }
}
```

**Step 2 — 登录获取 Token**：

```
POST /api/auth/login
Content-Type: application/json

{
  "username": "zhangsan",
  "password": "mypassword123"
}
```

**响应**：

```json
HTTP/1.1 200 OK
Content-Type: application/json

{
  "code": "0",
  "message": "登录成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 900
  }
}
```

**Step 3 — 创建研究任务**：

```
POST /api/research
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
Content-Type: application/json

{
  "topic": "量子计算对现有密码学体系的影响",
  "requirements": {
    "task_type": "analysis",
    "depth": "quick",
    "max_sources": 10,
    "language": "zh"
  }
}
```

**响应**：

```json
HTTP/1.1 201 Created
Content-Type: application/json

{
  "code": "0",
  "message": "研究任务已创建",
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "pending",
    "created_at": "2026-06-19T10:00:00+00:00"
  }
}
```

**Step 4 — 连接 SSE 流**：

```
GET /api/research/550e8400-e29b-41d4-a716-446655440000/stream
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**SSE 返回**：

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

event: task.created
data: {"task_id": "550e8400-e29b-41d4-a716-446655440000", "status": "running", "created_at": "2026-06-19T10:00:05+00:00"}

event: phase.started
data: {"phase": "planning", "timestamp": "2026-06-19T10:00:05+00:00"}

event: step.started
data: {"step_id": "step-01", "step_type": "planning", "label": "拆解研究主题"}

event: step.progress
data: {"step_id": "step-01", "sub_questions_generated": 4}

event: step.completed
data: {"step_id": "step-01", "output": {"sub_questions": ["量子计算对 RSA 的威胁", "NIST PQC 标准化进展", "后量子密码迁移方案", "行业应对时间线"]}}

event: phase.completed
data: {"phase": "planning", "duration_ms": 1200}

event: phase.started
data: {"phase": "searching", "timestamp": "2026-06-19T10:00:06+00:00"}

... 后续 Search → Fetch → Rerank → Synthesis → Evidence Graph → Render 事件 ...

event: checkpoint.saved
data: {"phase": "fetching", "last_completed_step_id": "step-08", "saved_at": "2026-06-19T10:01:30+00:00"}

event: task.completed
data: {"task_id": "550e8400-e29b-41d4-a716-446655440000", "status": "completed", "trace": {"total_duration_ms": 150000, "sources": 10, "evidence": 18}}
```

**Step 5 — 获取报告**：

```
GET /api/research/550e8400-e29b-41d4-a716-446655440000/report
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**响应**：完整 Report JSON（结构见 §3.3 `GET /report`）。

---

### 6.2 错误流程：任务不存在

```
GET /api/research/00000000-0000-0000-0000-000000000000
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**响应**：

```json
HTTP/1.1 404 Not Found
Content-Type: application/json

{
  "code": "E2001",
  "message": "任务不存在",
  "detail": {
    "error_type": "TaskNotFound",
    "error_description": "task_id=00000000-0000-0000-0000-000000000000 不存在或已被删除",
    "recoverable": false
  }
}
```

---

### 6.3 错误流程：认证失败

```
POST /api/auth/login
Content-Type: application/json

{
  "username": "zhangsan",
  "password": "wrongpassword"
}
```

**响应**：

```json
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{
  "code": "E1002",
  "message": "用户名或密码错误",
  "detail": {
    "error_type": "InvalidCredentials",
    "error_description": "提供的用户名或密码不正确"
  }
}
```

---

### 6.4 错误流程：断点续跑状态冲突

```
POST /api/research/550e8400-e29b-41d4-a716-446655440000/retry
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

**响应**（任务正在运行中，不允许 retry）：

```json
HTTP/1.1 409 Conflict
Content-Type: application/json

{
  "code": "E2003",
  "message": "当前任务状态不支持该操作",
  "detail": {
    "error_type": "InvalidTaskState",
    "error_description": "任务当前状态为 running，不支持 retry 操作",
    "current_status": "running",
    "allowed_statuses": ["failed", "partially_completed", "canceled"]
  }
}
```

---

## 7. 接口权限速查表

| 方法 | 路径 | 权限 | 说明 |
|:---|:---|:---|:---|
| POST | `/api/auth/register` | 公开 | 注册 |
| POST | `/api/auth/login` | 公开 | 登录 |
| POST | `/api/auth/refresh` | 公开（携带 refresh_token） | Token 刷新（Rotation） |
| POST | `/api/auth/logout` | user | 吊销 refresh_token |
| PUT | `/api/auth/password` | user | 改密并吊销全部 refresh_token |
| POST | `/api/research` | user | 创建研究任务 |
| GET | `/api/research` | user | 我的研究历史列表 |
| GET | `/api/research/{task_id}` | user（owner + admin） | 任务状态 |
| DELETE | `/api/research/{task_id}` | user（owner + admin） | 删除任务 |
| POST | `/api/research/{task_id}/cancel` | user（owner + admin） | 取消任务 |
| POST | `/api/research/{task_id}/retry` | user（owner + admin） | 断点续跑 |
| GET | `/api/research/{task_id}/report` | user（owner + admin） | 获取报告 |
| GET | `/api/research/{task_id}/stream` | user（owner + admin） | SSE 连接 |
| GET | `/api/research/{task_id}/state` | user（owner + admin） | 执行状态快照 |
| GET | `/api/health/workers` | 公开 | Worker 集群健康检查 |

> **权限层级说明**：
> - **公开**：无需登录即可访问
> - **user**：登录即可访问（操作自己的资源）
> - **owner + admin**：仅任务创建者或管理员可访问。admin 拥有审计权限，可查看任意用户的任务，但不可创建/修改他人任务。完整权限模型见 [ARCHITECTURE.md §4](ARCHITECTURE.md#4-权限模型)。

---

## 8. 相关文档

- [产品需求文档](PRD.md)
- [架构设计文档](ARCHITECTURE.md)
- [研究管线设计文档](RESEARCH_PIPELINE.md)
- [数据库设计文档](DATABASE.md)
- [开发排期](ROADMAP.md)
