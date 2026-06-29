# DATABASE — 数据库设计文档

| 属性 | 值 |
|:---|:---|
| 文档版本 | v1.0 |
| 最后更新 | 2026-06-28 |

> 本文档是 **数据库表结构、索引策略、外键级联规则** 的唯一真理源。相关定义禁止在其他文档中重复，应使用交叉引用链接到本文档对应章节。状态机字段语义（Task / Phase / Step 三层状态、Execution Context、Evidence Completeness Threshold）见 [ARCHITECTURE.md §3](ARCHITECTURE.md#3-研究任务状态机)，Pipeline 各阶段的输入输出数据持久化见 [RESEARCH_PIPELINE.md](RESEARCH_PIPELINE.md)，接口中的请求/响应字段见 [API.md](API.md)，产品需求见 [PRD.md](PRD.md)。

---

## 0. 时区约定

> **所有 DATETIME 列均存储 UTC 时间。** 四层 UTC 统一策略（MySQL → 后端 → API → 前端）：底层 MySQL 存 UTC naive datetime，ORM 层 `UTCDateTime` TypeDecorator 读写转换，Pydantic 序列化为 `+00:00`，前端 `new Date()` 自动转本地时区。数据库层面实现细节见下文。

`app/models/_types.py` 中的 `UTCDateTime` TypeDecorator 在 ORM 层完成 aware ↔ naive 双向转换——写入时转为 UTC 并剥离 tzinfo 存 naive UTC，读取时附加 UTC tzinfo 返回 aware datetime。Pydantic 收到 aware datetime 后自动序列化为 `2026-06-19T10:00:00+00:00`。前端 `new Date(isoString)` 自动转换为本地时区显示。底层列依然是 `DATETIME`，不需要数据迁移。

- **列类型**：所有时间列声明为 `UTCDateTime`（底层 `DATETIME`，MySQL 不存储时区）
- **服务端默认值**：`created_at` / `updated_at` 使用 `CURRENT_TIMESTAMP`（连接级 `time_zone='+00:00'` 保证其为 UTC），**禁止** `(UTC_TIMESTAMP())`——其在 `ON UPDATE` 子句中需额外括号易致语法错误
- **updated_at 自动更新**：由 ORM 层 `onupdate=func.current_timestamp()` 维护（经 service/ORM 发起的 UPDATE 自动刷新）；DDL 层不再声明 `ON UPDATE` 子句
- **连接时区**：`core/database.py` 连接建立钩子执行 `SET time_zone='+00:00'`

---

## 1. ER 关系

```
users (用户表)
  │
  ├── refresh_tokens (刷新令牌表)
  │
  │ 1:N
  ▼
research_tasks (研究任务表) ────┬── research_steps (DAG 执行树)
  │                             │     │
  │ 1:N                         │     │ 产生
  ▼                             ▼     ▼
research_sources (来源表) ◄────┼── evidence_items (证据条目表)
  │                             │     │
  │                             │     │ M:N
  │                             │     ▼
  │                             └── section_evidence (章节-证据关联表)
  │                                   │
  │ 1:N                               │
  ▼                                   │
report_sections (报告章节表) ◄─────────┘
```

**关系说明**：
- 一个用户可创建多个研究任务，每个任务属于一个用户（1:N）
- 一个用户可有多个刷新令牌，每个令牌属于一个用户（1:N）
- 一个任务包含多个执行步骤，每个步骤属于一个任务（1:N）
- 步骤之间通过 `parent_step_id` 构成执行树（自引用 1:N），v1.0 为线性 Tree，v2.0 升级为真 DAG
- 一个任务产生多个来源，每个来源属于一个任务（1:N）
- 一个任务产生多条证据，每条证据属于一个任务（1:N）
- 一个来源可关联多条证据，每条证据属于一个来源（1:N）
- 一个步骤可产生多条证据，每条证据可选关联产生它的步骤（N:1，可为空）
- 一个任务包含多个报告章节，章节之间可嵌套（自引用 1:N）
- 章节与证据之间为多对多关系（M:N），通过 `section_evidence` 关联表实现

---

## 2. 表结构

> ResearchMind 是独立项目，自建全部数据库表（包括 users）。下述表结构、工程约定与级联策略均为 ResearchMind 自有设计。

### 2.1 用户表 `users`

```sql
CREATE TABLE users (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    username        VARCHAR(64)  NOT NULL UNIQUE,
    password_hash   VARCHAR(256) NOT NULL,                  -- bcrypt 哈希
    role            ENUM('user','admin') DEFAULT 'user',
    status          ENUM('active','disabled') DEFAULT 'active',  -- disabled 后拒绝登录与 Token 刷新
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP  -- 自动更新由 ORM onupdate 维护
);
```

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| id | BIGINT | 主键 |
| username | VARCHAR(64) | 用户名，唯一 |
| password_hash | VARCHAR(256) | bcrypt 哈希后的密码 |
| role | ENUM | 角色：user（普通用户）/ admin（管理员） |
| status | ENUM | 状态：active（正常）/ disabled（禁用），禁用后拒绝登录和 Token 刷新 |
| created_at | DATETIME | 创建时间（UTC） |
| updated_at | DATETIME | 更新时间（UTC），自动更新 |

> 用户管理、JWT、权限中间件均为 ResearchMind 自有实现（详见 [ARCHITECTURE.md §4 权限模型](ARCHITECTURE.md#4-权限模型) 与 [API.md §1 设计约束](API.md#1-设计约束)）。`users` 表通过 `user_id` 外键关联到 `research_tasks`。

### 2.2 研究任务表 `research_tasks`

```sql
CREATE TABLE research_tasks (
    id              UUID PRIMARY KEY,
    user_id         BIGINT NOT NULL,                            -- 创建者（关联 users.id）
    topic           VARCHAR(500) NOT NULL,                      -- 用户输入的研究主题
    requirements    JSON NOT NULL,                              -- 研究要求（task_type, depth, max_sources, language...）

    -- Level 1: Task State
    status          ENUM('pending','running','completed','partially_completed',
                         'failed','canceled','paused')
                         NOT NULL DEFAULT 'pending',

    -- Level 2: Phase State
    current_phase   ENUM('planning','searching','fetching','reranking',
                         'synthesizing','building_evidence_graph','rendering')
                         DEFAULT NULL,

    -- Execution Context（断点续跑核心）
    execution_context JSON DEFAULT NULL,                        -- ARCHITECTURE §3.3 结构

    -- 统计
    total_steps     INT DEFAULT 0,
    completed_steps INT DEFAULT 0,
    total_sources   INT DEFAULT 0,
    total_evidence  INT DEFAULT 0,

    -- Trace 追踪数据
    trace           JSON DEFAULT NULL,                          -- Pipeline 七阶段 Trace JSON（TraceRecorder.finish() 产出）

    -- 错误
    error_code      VARCHAR(50) DEFAULT NULL,
    error_message   TEXT DEFAULT NULL,
    recoverable     BOOLEAN DEFAULT NULL,                       -- 是否可以断点续跑

    -- 时间
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at      DATETIME DEFAULT NULL,                      -- Worker 拾取时间
    completed_at    DATETIME DEFAULT NULL,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, -- 记录最后修改时间（ORM onupdate 维护）

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    INDEX idx_user (user_id),
    INDEX idx_status (status),
    INDEX idx_created (created_at DESC)
);
```

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| id | UUID | 主键，UUID 格式 |
| user_id | BIGINT | 创建者用户 ID，外键关联 `users.id` |
| topic | VARCHAR(500) | 用户输入的研究主题 |
| requirements | JSON | 研究要求（task_type, depth, max_sources, language 等） |
| status | ENUM | Task 级状态：pending / running / completed / partially_completed / failed / canceled / paused |
| current_phase | ENUM | Phase 级状态：planning / searching / fetching / reranking / synthesizing / building_evidence_graph / rendering |
| execution_context | JSON | 断点续跑上下文（current_phase, last_completed_step_id, execution_pointer, progress） |
| total_steps | INT | 总步骤数 |
| completed_steps | INT | 已完成步骤数 |
| total_sources | INT | 来源总数 |
| total_evidence | INT | 证据总数 |
| error_code | VARCHAR(50) | 错误码（E3xxx 系列） |
| error_message | TEXT | 错误详情 |
| recoverable | BOOLEAN | 是否支持断点续跑（NULL = 未失败） |
| trace | JSON | Pipeline 七阶段 Trace JSON，由 TraceRecorder.finish() 写入。结构：task_id / user_id / status / total_duration_ms / total_input_tokens / total_output_tokens / total_cost_usd / phases / phase_durations_ms / error_message / created_at |
| created_at | DATETIME | 创建时间（UTC） |
| started_at | DATETIME | Worker 拾取时间（UTC） |
| completed_at | DATETIME | 完成时间（UTC） |
| updated_at | DATETIME | 最后修改时间（UTC），ORM onupdate 自动维护 |

> **权威定义**：Task State 的完整转换规则（触发条件、状态间转换表）见 [ARCHITECTURE.md §3.2](ARCHITECTURE.md#32-task-state-转换规则)。Task State 由 `TaskStateResolver` 统一计算，**禁止**由任务自身直接写入。三层状态模型详见 [ARCHITECTURE.md §3.1](ARCHITECTURE.md#31-三层状态模型)。

### 2.3 研究步骤表 `research_steps`

```sql
CREATE TABLE research_steps (
    id              UUID PRIMARY KEY,
    task_id         UUID NOT NULL,
    step_type       ENUM('planning','search','fetch','rerank',
                         'synthesis','evidence_graph','render') NOT NULL,
    parent_step_id  UUID DEFAULT NULL,                          -- DAG 边：父步骤

    -- Level 3: Step State
    status          ENUM('pending','running','completed','failed','skipped','retrying')
                         NOT NULL DEFAULT 'pending',

    -- 标签（前端展示用）
    label           VARCHAR(200) DEFAULT NULL,                  -- 如 "搜索子问题 2：NIST PQC 标准进展"

    -- 输入输出
    input           JSON DEFAULT NULL,                          -- Step 输入参数
    output          JSON DEFAULT NULL,                          -- Step 产出

    -- 重试
    retry_count     INT DEFAULT 0,
    max_retries     INT DEFAULT 0,                              -- 0 = 使用阶段默认值

    -- 错误
    error_code      VARCHAR(50) DEFAULT NULL,
    error_message   TEXT DEFAULT NULL,

    -- 成本
    cost            JSON DEFAULT NULL,                          -- Step 级成本：{input_tokens, output_tokens, estimated_cost_usd, model}

    -- 性能
    duration_ms     INT DEFAULT NULL,                           -- 执行耗时

    -- 时间
    started_at      DATETIME DEFAULT NULL,
    completed_at    DATETIME DEFAULT NULL,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- ORM onupdate 维护

    FOREIGN KEY (task_id) REFERENCES research_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_step_id) REFERENCES research_steps(id) ON DELETE SET NULL,
    INDEX idx_task (task_id),
    INDEX idx_parent (parent_step_id),
    INDEX idx_task_status (task_id, status)
);
```

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| id | UUID | 主键 |
| task_id | UUID | 所属任务 ID，外键关联 `research_tasks.id` |
| step_type | ENUM | 步骤类型：planning / search / fetch / rerank / synthesis / evidence_graph / render |
| parent_step_id | UUID | 父步骤 ID（DAG 边），自引用外键，可为空 |
| status | ENUM | Step 级状态：pending / running / completed / failed / skipped / retrying |
| label | VARCHAR(200) | 步骤标签，前端展示用 |
| input | JSON | Step 输入参数 |
| output | JSON | Step 产出 |
| retry_count | INT | 已重试次数 |
| max_retries | INT | 最大重试次数（0 = 使用阶段默认值） |
| error_code | VARCHAR(50) | 错误码 |
| error_message | TEXT | 错误详情 |
| cost | JSON | Step 级成本：`{input_tokens, output_tokens, estimated_cost_usd, model}`，仅 LLM 阶段写入 |
| duration_ms | INT | 执行耗时（毫秒） |
| started_at | DATETIME | 开始时间（UTC） |
| completed_at | DATETIME | 完成时间（UTC） |
| updated_at | DATETIME | 最后修改时间（UTC） |

> **权威定义**：Step State 的完整转换规则与各阶段失败策略见 [ARCHITECTURE.md §3.1](ARCHITECTURE.md#31-三层状态模型)（三层状态模型）和 [ARCHITECTURE.md §5.5](ARCHITECTURE.md#55-failure-model失败分类学)（失败分类学）。

> `parent_step_id` 在 v1.0 用于线性 Tree；v2.0 升级为真 DAG 时将引入 `step_edges` 关联表（`from_step_id`、`to_step_id`、`dependency_type`），见 [ARCHITECTURE.md §3.4](ARCHITECTURE.md#34-step-执行树v10-treev20-dag)。

### 2.4 来源表 `research_sources`

```sql
CREATE TABLE research_sources (
    id              INT AUTO_INCREMENT PRIMARY KEY,             -- 报告中的引用编号 [1], [2]...
    task_id         UUID NOT NULL,
    url             VARCHAR(2048) NOT NULL,
    title           VARCHAR(500) DEFAULT NULL,
    domain          VARCHAR(255) DEFAULT NULL,
    fetched_at      DATETIME DEFAULT NULL,
    fetch_status    ENUM('success','timeout','blocked','empty','dns_error') DEFAULT NULL,
    content         MEDIUMTEXT DEFAULT NULL COMMENT '网页 Markdown 正文，fetch_status=success 时写入',
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- ORM onupdate 维护

    FOREIGN KEY (task_id) REFERENCES research_tasks(id) ON DELETE CASCADE,
    UNIQUE KEY uk_task_url (task_id, url(255)),                 -- 同任务内 URL 去重
    INDEX idx_task (task_id)
);
```

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| id | INT | 主键（自增），同时作为报告中的引用编号 [1], [2]... |
| task_id | UUID | 所属任务 ID，外键关联 `research_tasks.id` |
| url | VARCHAR(2048) | 来源 URL |
| title | VARCHAR(500) | 网页标题 |
| domain | VARCHAR(255) | 域名 |
| fetched_at | DATETIME | 抓取时间（UTC） |
| fetch_status | ENUM | 抓取状态：success / timeout / blocked / empty / dns_error |
| content | MEDIUMTEXT | 网页 Markdown 正文；fetch_status='success' 时写入 |
| updated_at | DATETIME | 最后修改时间（UTC） |

### 2.5 证据条目表 `evidence_items`

```sql
CREATE TABLE evidence_items (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    task_id         UUID NOT NULL,
    source_id       INT NOT NULL,                               -- 来源
    step_id         UUID DEFAULT NULL,                          -- 产生此证据的 Step

    content         TEXT NOT NULL,                              -- 证据原文片段
    relevance_score DECIMAL(4,3) DEFAULT NULL,                  -- Rerank 相关性分数 (0.000-1.000)

    -- Claim 级关联 [v2]
    -- claim_id     UUID DEFAULT NULL,
    -- position_in_doc INT DEFAULT NULL,                        -- 原文位置偏移

    -- 用于哪些章节
    used_in_sections JSON DEFAULT NULL,                         -- ["1", "2.1"]

    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- ORM onupdate 维护

    FOREIGN KEY (task_id) REFERENCES research_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES research_sources(id) ON DELETE CASCADE,
    FOREIGN KEY (step_id) REFERENCES research_steps(id) ON DELETE SET NULL,
    INDEX idx_task (task_id),
    INDEX idx_source (source_id),
    INDEX idx_score (task_id, relevance_score DESC)
);
```

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| id | INT | 主键（自增） |
| task_id | UUID | 所属任务 ID，外键关联 `research_tasks.id` |
| source_id | INT | 来源 ID，外键关联 `research_sources.id` |
| step_id | UUID | 产生此证据的 Step ID，外键关联 `research_steps.id`，可为空 |
| content | TEXT | 证据原文片段 |
| relevance_score | DECIMAL(4,3) | Rerank 相关性分数（0.000-1.000） |
| used_in_sections | JSON | 被哪些章节使用，如 `["1", "2.1"]` |
| created_at | DATETIME | 创建时间（UTC） |
| updated_at | DATETIME | 最后修改时间（UTC） |

> `claim_id`、`position_in_doc` 字段为 [v2 预留](ROADMAP.md#5-v20--full-deep-research)。

### 2.6 报告章节表 `report_sections`

```sql
CREATE TABLE report_sections (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    task_id         UUID NOT NULL,
    parent_section_id INT DEFAULT NULL,                         -- 父章节（支持嵌套）
    heading         VARCHAR(300) NOT NULL,
    content         MEDIUMTEXT NOT NULL,                        -- Markdown 正文
    sort_order      INT NOT NULL DEFAULT 0,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- ORM onupdate 维护

    FOREIGN KEY (task_id) REFERENCES research_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_section_id) REFERENCES report_sections(id) ON DELETE CASCADE,
    INDEX idx_task (task_id),
    INDEX idx_parent (parent_section_id)
);
```

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| id | INT | 主键（自增） |
| task_id | UUID | 所属任务 ID，外键关联 `research_tasks.id` |
| parent_section_id | INT | 父章节 ID，自引用外键（支持嵌套），可为空 |
| heading | VARCHAR(300) | 章节标题 |
| content | MEDIUMTEXT | Markdown 正文 |
| sort_order | INT | 排序序号 |
| updated_at | DATETIME | 最后修改时间（UTC） |

### 2.7 章节-证据关联表 `section_evidence`

```sql
CREATE TABLE section_evidence (
    section_id      INT NOT NULL,
    evidence_id     INT NOT NULL,

    PRIMARY KEY (section_id, evidence_id),
    FOREIGN KEY (section_id) REFERENCES report_sections(id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_id) REFERENCES evidence_items(id) ON DELETE CASCADE
);
```

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| section_id | INT | 章节 ID，外键关联 `report_sections.id` |
| evidence_id | INT | 证据 ID，外键关联 `evidence_items.id` |

> 联合主键 `(section_id, evidence_id)` 保证同一章节不重复关联同一条证据。

### 2.8 刷新令牌表 `refresh_tokens`

> 配合 Refresh Token 机制（见 [ARCHITECTURE.md §4](ARCHITECTURE.md#4-权限模型)），持久化存储刷新令牌哈希，支持 Rotation 与泄露检测。基于 ResearchMind 自有 JWT 基础设施。

```sql
CREATE TABLE refresh_tokens (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id         BIGINT NOT NULL,
    token_hash      VARCHAR(256) NOT NULL COMMENT 'refresh_token 的 SHA-256 哈希，不存明文',
    expires_at      DATETIME NOT NULL COMMENT '过期时间（创建后 7 天）',
    revoked_at      DATETIME NULL COMMENT '吊销时间（NULL=有效，非NULL=已吊销及吊销时间）',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_token_hash (token_hash),
    INDEX idx_user_active (user_id, revoked_at, expires_at) COMMENT '查询某用户有效 token',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| id | BIGINT | 主键 |
| user_id | BIGINT | 所属用户 ID，外键关联 `users.id` |
| token_hash | VARCHAR(256) | refresh_token 的 SHA-256 哈希值（不存明文，防数据库泄露后伪造） |
| expires_at | DATETIME | Token 过期时间（创建后 +7 天） |
| revoked_at | DATETIME | 吊销时间（NULL=有效；非 NULL=已吊销，值为吊销时间） |
| created_at | DATETIME | 创建时间（UTC） |

> refresh_token 的轮换、泄露检测、改密吊销和过期清理策略见 [API.md §2](API.md#2-认证接口)。

---

## 3. 索引策略

| 表 | 索引 | 类型 | 用途 |
|:---|:---|:---|:---|
| users | username (UNIQUE) | 唯一索引 | 登录查询 |
| research_tasks | idx_user (user_id) | 普通索引 | 按用户列出任务 |
| research_tasks | idx_status (status) | 普通索引 | 按状态筛选任务 |
| research_tasks | idx_created (created_at DESC) | 普通索引 | 按创建时间倒序排列 |
| research_steps | idx_task (task_id) | 普通索引 | 按任务列出步骤 |
| research_steps | idx_parent (parent_step_id) | 普通索引 | 按父步骤查找子步骤 |
| research_steps | idx_task_status (task_id, status) | 复合索引 | 按任务+状态筛选步骤 |
| research_sources | uk_task_url (task_id, url(255)) | 唯一索引 | 同任务内 URL 去重 |
| research_sources | idx_task (task_id) | 普通索引 | 按任务列出来源 |
| evidence_items | idx_task (task_id) | 普通索引 | 按任务列出证据 |
| evidence_items | idx_source (source_id) | 普通索引 | 按来源查找证据 |
| evidence_items | idx_score (task_id, relevance_score DESC) | 复合索引 | 按任务+相关性排序 |
| report_sections | idx_task (task_id) | 普通索引 | 按任务列出章节 |
| report_sections | idx_parent (parent_section_id) | 普通索引 | 按父章节查找子章节 |
| refresh_tokens | idx_user_id (user_id) | 普通索引 | 按用户查询刷新令牌 |
| refresh_tokens | idx_token_hash (token_hash) | 普通索引 | 按 token 哈希查找（刷新校验入口） |
| refresh_tokens | idx_user_active (user_id, revoked_at, expires_at) | 复合索引 | 查询用户有效 token + 改密批量吊销 + Rotation 检测 |

> **注意**：MySQL 会自动为外键列创建索引（若该列尚未建立索引）。上表中 `research_steps.task_id`、`evidence_items.source_id` 等因已有显式索引，不再重复。`research_steps.parent_step_id` 和 `report_sections.parent_section_id` 作为自引用外键，显式建立索引以支持 DAG 遍历查询。

---

## 4. 外键策略

| FK 字段 | 引用表 | 级联行为 | 设计理由 |
|:---|:---|:---|:---|
| `research_tasks.user_id` | `users(id)` | `ON DELETE RESTRICT` | 用户有研究记录时禁止删除，防止误删导致数据丢失（需先清理任务） |
| `research_steps.task_id` | `research_tasks(id)` | `ON DELETE CASCADE` | 任务删除时所有步骤一并删除 |
| `research_steps.parent_step_id` | `research_steps(id)` | `ON DELETE SET NULL` | 删除父步骤时不删除子步骤（由 task CASCADE 统一处理） |
| `research_sources.task_id` | `research_tasks(id)` | `ON DELETE CASCADE` | 任务删除时所有来源一并删除 |
| `evidence_items.task_id` | `research_tasks(id)` | `ON DELETE CASCADE` | 任务删除时所有证据一并删除 |
| `evidence_items.source_id` | `research_sources(id)` | `ON DELETE CASCADE` | 来源删除时关联证据一并删除 |
| `evidence_items.step_id` | `research_steps(id)` | `ON DELETE SET NULL` | Step 删除后证据保留（证据是核心资产），仅解除关联 |
| `report_sections.task_id` | `research_tasks(id)` | `ON DELETE CASCADE` | 任务删除时所有章节一并删除 |
| `report_sections.parent_section_id` | `report_sections(id)` | `ON DELETE CASCADE` | 父章节删除时子章节一并删除 |
| `section_evidence.section_id` | `report_sections(id)` | `ON DELETE CASCADE` | 章节删除时关联自动解除 |
| `section_evidence.evidence_id` | `evidence_items(id)` | `ON DELETE CASCADE` | 证据删除时关联自动解除 |
| `refresh_tokens.user_id` | `users(id)` | `ON DELETE CASCADE` | 用户删除时自动清理其刷新令牌，避免悬空数据 |

**级联策略总结**：
- **用户 → 任务**：`RESTRICT`（保护用户数据，防止级联误删）
- **用户 → 刷新令牌**：`CASCADE`（用户删除时自动清理令牌）
- **任务 → 派生数据**：`CASCADE`（任务删除时清理全部派生数据：steps / sources / evidence / sections / section_evidence）
- **自引用外键**：`parent_step_id` → `SET NULL`（保留子步骤）；`parent_section_id` → `CASCADE`（删除子树）

> **[Deviation] `delete_task` 使用 bulk `sa_delete` 而非 ORM 级联删除**：SQLite 异步驱动下，SQLAlchemy ORM 在删除 `research_tasks` 父行前会尝试将子表外键 `SET NULL`，而 `task_id` 列为 `NOT NULL`，导致 `IntegrityError`。因此 `research_service.delete_task()` 改用 `sa_delete(ResearchTask).where(...)` 直接执行 bulk DELETE，依赖数据库层 `ON DELETE CASCADE` 约束完成级联清理。此偏差在 MySQL 生产环境无影响（InnoDB 原生支持 CASCADE），Phase 4 若有其他 ORM 级联需求需重新评估。详见 `app/services/research_service.py:450-461`。
>
> **一致性保障**：外键约束在数据库层保证引用完整性，避免程序 Bug 产生脏数据。ORM 模型、Alembic 迁移脚本必须与外键定义同步。

---

## 5. 相关文档

- [产品需求文档](PRD.md)
- [架构设计文档](ARCHITECTURE.md)
- [研究管线设计文档](RESEARCH_PIPELINE.md)
- [接口文档](API.md)
- [开发排期](ROADMAP.md)
