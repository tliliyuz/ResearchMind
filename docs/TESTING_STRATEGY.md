# TESTING_STRATEGY — 测试策略文档

| 属性 | 值 |
|:---|:---|
| 文档版本 | v2.0 |
| 最后更新 | 2026-06-20 |

> 本文档定义了 ResearchMind 的测试分层策略、基础设施配置、各层覆盖范围与编写规范。测试进度追踪（各 Phase 测试任务、完成状态）见 [ROADMAP.md](ROADMAP.md)。

---

## 1. 测试策略概述

ResearchMind 的核心质量挑战在于：**7 阶段异步 Pipeline 的状态空间巨大**（Task 7 态 × Phase 7 阶段 × Step 6 态），断点续跑、Token Rotation 泄露检测、CAS 并发更新等关键路径不容出错。

### 1.1 测试金字塔

```
        ┌─────────────┐
        │  回归测试    │ 5-10%（端到端关键路径）
        ├─────────────┤
        │  集成测试    │ 20-25%（DB / Redis / Celery / 外部 API 边界）
        ├─────────────┤
        │  单元测试    │ 65-70%（纯函数 / 类 / 模块逻辑）
        └─────────────┘
```

| 层级 | 目标 | 频率 | 工具 |
|:---|:---|:---|:---|
| **单元测试** | 验证函数/类/方法的独立逻辑正确性，Mock 外部依赖 | 每次提交 | pytest + pytest-asyncio |
| **集成测试** | 验证模块边界与数据库/Redis/Celery 交互 | 每次提交 | pytest + httpx + 真实 MySQL/Redis |
| **回归测试** | 端到端关键路径，防止已有能力退化 | 每次提交 | pytest + httpx（含 SSE 流校验） |
| **压测** | 确保 Pipeline 并发吞吐达标 | Phase 5 | Locust + 真实 LLM 调用 |

### 1.2 核心原则（对齐 CLAUDE.md 测试约定）

| 原则 | 说明 | 反例 |
|:---|:---|:---|
| **强断言优先** | 验证具体值、顺序、错误码 | ❌ `is not None`、`> 0`、`isinstance` |
| **Mock 在边界截断** | 至少保留一层真实逻辑 | ❌ 全量 Mock 只验证管道 |
| **分支枚举** | 每个 `if/else`、错误码独立用例 | ❌ "非 XXX" 模糊覆盖 |
| **成功/失败成对** | 每个操作覆盖成功 + 失败 + 加载状态 | ❌ 只测 happy path |
| **禁测私有方法** | `_` 前缀方法通过公共 API 覆盖 | ❌ `def test__internal_helper` |
| **名实一致** | 测试名与验证行为严格对应 | ❌ `test_login`（太模糊） |
| **API 层 + Service 层缺一不可** | API 验证序列化/HTTP 码，Service 验证业务逻辑 | ❌ 仅有 API 层测试 |
| **Phase 完成即测试** | Phase N 的测试必须在 Phase N 功能完成时立即编写 | ❌ 推迟到 Phase 结束后 |

---

## 2. 测试分层

### 2.1 后端分层

| 层级 | 目录 | 运行速度 | 目标占比 |
|:---|:---|:---|:---|
| 单元测试 | `tests/unit/{api,services,pipeline,core,middleware,models}/` | < 5s | 65-70% |
| 集成测试 | `tests/integration/` | < 30s | 20-25% |
| 回归测试 | `tests/regression/` | < 120s | 5-10% |

> **Phase2 说明**：Phase2（Celery Pipeline + 前端）阶段，集成测试暂置于 `tests/unit/pipeline/`（使用 SQLite 内存库 + Mock 外部 API），真实 MySQL/Redis 中间件的集成测试将在 Phase4（断点续跑）和 Phase5（全链路压测）阶段启用。`tests/integration/` 与 `tests/regression/` 目录已就位，当前仅含 `__init__.py`，待 Phase4/5 迁移。

### 2.2 前端分层

| 层级 | 目标占比 | 工具 |
|:---|:---|:---|
| 单元测试（store / utils / api） | 45-50% | vitest + jsdom |
| 组件测试（views / components） | 40-45% | vitest + @vue/test-utils |
| 集成 / 快照测试 | 5-10% | vitest |

---

## 3. 测试基础设施

### 3.1 pytest 配置（`pytest.ini`）

```ini
[pytest]
testpaths = tests
asyncio_mode = auto
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --strict-markers
    --tb=short
    --disable-warnings
markers =
    unit: 单元测试（纯函数/类，无 I/O 或使用 SQLite 内存库）
    integration: 集成测试（需 MySQL/Redis/外部服务）
    slow: 慢速测试（需要完整 Pipeline 运行或 LLM 调用）
    regression: 回归测试（端到端关键路径）
```

### 3.2 测试数据库策略

| 场景 | 方案 | 依赖 |
|:---|:---|:---|
| 单元测试 | SQLite 内存数据库 (`sqlite+aiosqlite:///:memory:`) | `aiosqlite`（dev dependency） |
| 集成测试 | 真实 MySQL + Redis（Docker Compose 或 CI service container） | Docker |
| 本地跳过集成 | `pytest -m "not integration"` | — |

**单元测试隔离机制**：每个测试函数获取独立的事务会话，测试结束自动回滚，确保测试间无状态泄漏。

### 3.3 Mock 策略

| 场景 | Mock 方式 | 保留真实逻辑 |
|:---|:---|:---|
| LLM 调用 (`AsyncOpenAI`) | `unittest.mock.AsyncMock` | `_classify_llm_error` / `_retry_delay` / `_max_retries` |
| Redis 操作 | `AsyncMock` | 限流中间件的路由分组、阈值计算逻辑 |
| 数据库查询 | **不 Mock**（使用 SQLite 内存库） | SQLAlchemy 完整 ORM 路径 |
| 外部 HTTP API（Tavily / Fetch） | `httpx.AsyncMock` | 失败降级逻辑 |
| 时间敏感测试 | `freezegun` 冻结点 | 仅 Token 过期、TTL 等时间依赖测试 |
| bcrypt 哈希 | **不 Mock** | 确保密码哈希正确性 |

### 3.4 环境变量隔离

测试环境变量在 `tests/conftest.py` 中统一设置，**在任何 app 模块导入之前**注入：

```python
os.environ["ENV"] = "testing"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-for-testing-only"
os.environ["REFRESH_TOKEN_SECRET_KEY"] = "test-refresh-secret-key-for-testing-only"
os.environ["LLM_API_KEY"] = "test-llm-api-key"
os.environ["RATE_LIMIT_ENABLED"] = "false"
```

---

## 4. 后端测试策略

### 4.1 关键路径 100% 覆盖要求

以下模块的**行覆盖和分支覆盖均需达到 100%**：

| 模块 | 理由 |
|:---|:---|
| `app/services/auth_service.py` | 认证业务逻辑（含 Token Rotation + 泄露检测） |
| `app/core/security.py` | JWT 生成/验证 + bcrypt 哈希 — 所有认证流程的基石 |
| `app/api/auth.py` | 认证 API 端点 |
| `app/middleware/auth_middleware.py` | ASGI 认证中间件 — 所有 API 请求的入口 |

### 4.2 异常体系测试（`core/exceptions.py`）

每个异常类覆盖 3 个维度，共计 31+ 异常类：

1. **默认/带参构造** — 验证 `error_code`、`error_message`、`status_code`
2. **`detail` 结构化字段** — 验证 `error_type`、`error_description` 及可选字段（`recoverable`、`retry_after_ms`）
3. **HTTPException 序列化** — 验证 `detail` 属性包含 `{"code", "message", "detail"}` 三元组

```python
# 模式示例
class TestUsernameExistsException:
    def test_错误码为E1001_HTTP状态码为409(self):
        exc = UsernameExistsException(username="testuser")
        assert exc.error_code == "E1001"
        assert exc.status_code == 409

    def test_detail包含error_type和error_description(self):
        exc = UsernameExistsException(username="testuser")
        assert exc.error_detail["error_type"] == "UsernameExists"
        assert "testuser" in exc.error_detail["error_description"]

    def test_HTTPException_detail序列化为统一响应格式(self):
        exc = UsernameExistsException(username="testuser")
        assert exc.detail["code"] == "E1001"
        assert isinstance(exc.detail["detail"], dict)
```

### 4.3 安全模块测试（`core/security.py`）

覆盖全部 7 个公开函数：`hash_password` / `verify_password` / `create_access_token` / `decode_access_token` / `create_refresh_token` / `decode_refresh_token` / `hash_token`。

每个函数覆盖成功路径 + 失败路径（过期 token、伪造 token、类型错误）。

```python
# 模式示例：成功/失败成对
class TestCreateAccessToken:
    def test_payload包含sub_username_role三个字段(self):
        token = create_access_token(user_id=42, username="bob", role="admin")
        payload = decode_access_token(token)
        assert payload["sub"] == "42"
        assert payload["username"] == "bob"
        assert payload["role"] == "admin"

    def test_过期token_decode返回空dict(self):
        # 构造已过期的 JWT
        ...
        assert decode_access_token(expired) == {}

    def test_伪造token_decode返回空dict(self):
        assert decode_access_token("not.a.jwt") == {}
```

### 4.4 认证服务测试（`services/auth_service.py`）

覆盖 6 个公开函数的所有分支：

| 函数 | 关键分支 |
|:---|:---|
| `register()` | 正常注册 / 用户名重复 → E1001 |
| `login()` | 正常登录 / 密码错误 → E1002 / 用户不存在 → E1002 / 用户禁用 → E1010 |
| `refresh()` | 正常刷新 Rotation / JWT 解码失败 → E1008 / token 不在 DB → E1008 / **已吊销重用 → E1009 泄露检测** / token 过期 → E1006 / 用户禁用 → E1010 |
| `logout()` | 正常吊销 / JWT 解码失败静默成功 / 已吊销幂等 |
| `change_password()` | 正常改密 / 旧密码错误 → E1002 / 新密码=旧密码 → E1011 |
| `revoke_all_user_tokens()` | 有活跃 token → 全部吊销 / 0 活跃 token → 无操作 |

**泄露检测**是最高优先级测试场景：已吊销 token 被重用时必须触发 `TokenLeakDetectedException`(E1009)，并验证该用户**全部** refresh_token 均被吊销。

### 4.5 LLM 客户端测试（`core/llm.py`）

覆盖 `stream_chat_completion()` 和 `chat_completion()` 的重试策略分支：

| 场景 | 验证点 |
|:---|:---|
| 流式正常调用 | chunk 逐条 yield，content + reasoning_content 正确 |
| timeout 错误 → 3 次重试 | 最终抛出 `LLMTimeoutException`，中间 sleep 2 次 |
| auth 错误 → 0 次重试 | 仅调用 1 次 API，直接抛出 `LLMAuthFailedException` |
| rate_limit → 指数退避 3 次 | sleep 参数依次为 5.0、10.0，最终抛出 `LLMRateLimitException` |
| 非流式空 choices | 抛出 `LLMUnknownException`（E3111，不重试）[Deviation] 原述 `LLMCallFailedException` 该类未在 exceptions.py / API.md §5 定义，已映射到已定义的 `LLMUnknownException` |

```python
# 模式示例：重试策略验证
async def test_timeout错误重试3次后抛出LLMTimeoutException(self):
    mock_client.chat.completions.create.side_effect = Exception("Request timed out")
    with pytest.raises(LLMTimeoutException):
        async for _ in stream_chat_completion(messages=[...]):
            pass
    assert mock_client.chat.completions.create.call_count == 3
```

### 4.6 Pipeline 阶段测试（`pipeline/`）

每个 Pipeline 阶段独立测试，覆盖：

| 阶段 | 核心验证 |
|:---|:---|
| **BM25 段落切分** | 按双换行切分、空白段落跳过、超长段落截断、空输入边界 |
| **BM25 评分** | 相关性降序、top_k 截断、空段落列表边界 |
| **Planner**（Phase 2） | 子问题生成数量、topic 注入 Prompt、JSON 解析容错 |
| **Searcher**（Phase 2） | Tavily API 调用、结果去重、失败降级 |
| **Fetcher**（Phase 2） | 内容抓取、编码检测、超时处理 |
| **Reranker**（Phase 3） | 精排正确性、API 异常降级、空/单输入边界 |
| **Synthesis**（Phase 3） | 来源引用格式、token 预算控制 |
| **Evidence Graph Build**（Phase 3） | 证据条目数、来源关联、used_in_sections 映射 |
| **Report Render**（Phase 3） | Markdown 输出格式、`[来源N]` 锚点生成 |

### 4.7 Trace 记录器测试（`core/trace_recorder.py`）

覆盖 7 阶段数据收集 + `finish()` 聚合：

- 各阶段 `record_*()` 写入阶段数据并累加 token
- `finish()` 返回完整 trace 含聚合统计，未执行阶段为 None
- `record_error()` 标记失败并写入对应阶段
- 部分失败阶段 status 为 `partial`

### 4.8 其他核心模块

| 模块 | 覆盖要点 |
|:---|:---|
| `core/token_counter.py` | 中英文自适应算法：纯英文 ratio 4.0 / 纯中文 ratio 1.5 / 混合>30%中文用中文 ratio / 临界点 30% / 空字符串返回 1 |
| `core/permissions.py` | Task Access（`require_task_accessible`）+ System Permissions（`require_admin`）两层权限，**禁止混用** |
| `core/sse.py` | `format_sse_event()` JSON 序列化 + 中文保留 / `format_sse_heartbeat()` / `stream_with_heartbeat()` 静默触发心跳 |
| `middleware/rate_limit_middleware.py` | Redis Lua 限流逻辑、路由分组、阈值计算 |
| `middleware/auth_middleware.py` | 有效 token → 注入 user_id / 无效 token → 401 / 无 token → 401 |
| `models/_types.py` | `UTCDateTime` aware↔naive 双向转换（写入剥离 tzinfo / 读取附加 UTC）、`utcnow()` 返回 aware datetime |
| `schemas/auth.py` | Pydantic 校验规则、边界值（用户名纯数字禁止、密码 < 6 字符禁止） |

---

## 5. 前端测试策略

### 5.1 覆盖范围

| 层级 | 测试对象 | 关键覆盖 |
|:---|:---|:---|
| **Store 单元测试** | `authStore` / `taskStore` | login/logout/refresh 并发防抖、`scheduleRefresh`、`isAdmin`、Pipeline 状态驱动 |
| **API 层单元测试** | Axios 拦截器 | Token 自动刷新（E1003/E1004）、并发请求防抖、错误码处理 |
| **组件测试** | LoginPage / ResearchPage / HistoryPage / Admin | 表单校验、Tab 切换、loading 状态、错误提示、SSE 事件驱动的 UI 更新 |
| **路由守卫测试** | Router Guards | 未登录 → `/login`、admin 守卫、公开页面、已登录访问 `/login` 重定向 |

### 5.2 Auth Store 测试要点（核心示例）

```javascript
// 模式示例：并发防抖 — 刷新中再次调用不重复请求 API
it('并发防抖_刷新中再次调用不重复请求API', async () => {
  authApi.refreshToken.mockImplementation(() =>
    new Promise(resolve => setTimeout(() => resolve({...}), 50))
  )
  const store = useAuthStore()
  store.refreshToken = 'some-refresh'

  const [r1, r2] = await Promise.all([store.refresh(), store.refresh()])

  expect(r1).toBe(true)
  expect(r2).toBe(true)
  expect(authApi.refreshToken).toHaveBeenCalledTimes(1)  // 仅 1 次 API 调用
})
```

### 5.3 组件测试要点

- **表单校验**：空用户名 / 纯数字用户名 / 密码 < 6 字符 → 错误提示文案
- **提交状态**：按钮 loading + disabled，防止重复提交
- **SSE 事件驱动**：Mock `fetch` + `ReadableStream`，验证 15 种 SSE 事件类型（v1.0）+ 2 种预留 [v2] 对应的 UI 变更
- **Evidence Graph 面板**：双向联动 — 点击 `[来源N]` 锚点展开 Evidence 面板；点击 Evidence 条目高亮所有引用锚点

### 5.4 路由守卫测试要点

```javascript
// 模式示例
it('未登录访问需要认证的页面_重定向到/login', async () => {
  await router.push('/research')
  expect(router.currentRoute.value.path).toBe('/login')
})

it('非admin访问/admin_重定向到/research', async () => {
  store.user = { id: 1, username: 'user', role: 'user' }
  await router.push('/admin')
  expect(router.currentRoute.value.path).toBe('/research')
})
```

---

## 6. CI/CD 集成

### 6.1 GitHub Actions 工作流（`.github/workflows/test.yml`）

```yaml
name: 全量测试

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  backend-tests:
    runs-on: ubuntu-latest
    services:
      mysql:
        image: mysql:8.0
        env:
          MYSQL_ROOT_PASSWORD: testpass
          MYSQL_DATABASE: researchmind_test
        ports:
          - 3306:3306
        options: >-
          --health-cmd="mysqladmin ping"
          --health-interval=10s
          --health-timeout=5s
          --health-retries=3
      redis:
        image: redis:7.0
        ports:
          - 6379:6379

    steps:
      - uses: actions/checkout@v4

      - name: 设置 Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: 安装依赖
        run: |
          pip install -r requirements.txt
          pip install aiosqlite

      - name: 运行单元测试（含覆盖率）
        run: |
          pytest tests/unit/ -v \
            --cov=app \
            --cov-report=xml \
            --cov-report=term-missing \
            --tb=short \
            -m "not slow"

      - name: 上传覆盖率到 Codecov
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml

      - name: 运行集成测试（需 MySQL / Redis）
        run: pytest tests/integration/ -v --tb=short
        env:
          MYSQL_HOST: localhost
          MYSQL_PORT: 3306
          MYSQL_USER: root
          MYSQL_PASSWORD: testpass
          MYSQL_DATABASE: researchmind_test
          REDIS_URL: redis://localhost:6379/0
          JWT_SECRET_KEY: ci-test-jwt-secret
          REFRESH_TOKEN_SECRET_KEY: ci-test-refresh-secret
          LLM_API_KEY: ci-test-llm-key

  frontend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: 设置 Node.js 20
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: 安装依赖
        working-directory: ./frontend
        run: npm ci

      - name: 运行前端测试
        working-directory: ./frontend
        run: npm run test -- --coverage

      - name: 上传前端覆盖率
        uses: codecov/codecov-action@v4
        with:
          directory: ./frontend/coverage
```

### 6.2 本地 Pre-commit Hook（可选）

```bash
#!/bin/bash
# .git/hooks/pre-commit
echo "运行后端单元测试..."
pytest tests/unit/ -v --tb=short -m "not slow" || exit 1

echo "运行前端测试..."
cd frontend && npm run test || exit 1

echo "全部测试通过!"
```

---

## 7. 覆盖率目标

| 指标 | Phase 1 | Phase 2-3 | Phase 4-5 | Phase 6+ |
|:---|:---|:---|:---|:---|
| **后端行覆盖** | ≥ 85% | ≥ 88% | ≥ 90% | ≥ 92% |
| **后端分支覆盖** | ≥ 80% | ≥ 85% | ≥ 88% | ≥ 90% |
| **前端行覆盖** | ≥ 75% | ≥ 80% | ≥ 85% | ≥ 85% |
| **前端分支覆盖** | ≥ 70% | ≥ 75% | ≥ 80% | ≥ 85% |

关键路径模块（§4.1）的行覆盖和分支覆盖**任何阶段不可低于 100%**。

### 覆盖率命令

```bash
# 后端：单元测试覆盖率（HTML 报告）
pytest tests/unit/ -v --cov=app --cov-report=html --cov-report=term-missing

# 后端：含集成测试的完整覆盖率
pytest tests/ -v --cov=app --cov-report=html -m "not regression"

# 前端：覆盖率
cd frontend && npm run test -- --coverage
```

---

## 8. 测试编写规范

### 8.1 命名规范

| 维度 | 规范 | 示例 |
|:---|:---|:---|
| 文件名 | `test_{模块名}.py` | `test_security.py`、`test_auth_service.py` |
| 测试类 | `Test{被测类/函数群}`（英文 PascalCase） | `TestCreateAccessToken`、`TestRefreshService` |
| 测试函数 | `test_{中文行为描述}` | `test_过期token_decode返回空dict`、`test_已吊销token重用_抛出E1009` |

### 8.2 结构规范

```python
"""测试文件 docstring：说明测试的模块和覆盖范围。"""

import pytest
from app.xxx import TargetClass


class TestTargetMethodName:
    """每个方法一个测试类，按功能分组。"""

    def test_正常情况_返回值类型正确(self):
        """测试名 = 场景 + 预期行为。"""
        result = target_method(input_value)
        assert result == expected_concrete_value   # ✅ 强断言

    def test_边界条件_输入为空列表返回空列表(self):
        result = target_method([])
        assert result == []

    def test_错误分支_输入类型错误抛出ValueError(self):
        with pytest.raises(ValueError) as exc_info:
            target_method(None)
        assert "具体错误信息" in str(exc_info.value)
```

### 8.3 禁止模式（硬性规则）

```python
# ❌ 禁止：弱断言
assert result is not None
assert len(result) > 0
assert isinstance(result, dict)

# ✅ 正确：强断言
assert result == {"code": "0", "message": "ok"}
assert len(result) == 3
assert result[0]["id"] == 1

# ❌ 禁止：条件断言
if error_case:
    assert exception_raised

# ✅ 正确：独立分支测试
def test_错误分支_场景A(self): ...
def test_正常分支_场景A(self): ...

# ❌ 禁止：测试私有方法
def test__internal_helper(self): ...

# ✅ 正确：通过公共 API 间接覆盖
def test_公共方法_场景触发内部逻辑(self): ...

# ❌ 禁止：全量 Mock 仅验证管道
def test_pipeline_calls_abc_then_def(self):
    mock_a.assert_called()
    mock_b.assert_called()

# ✅ 正确：Mock 在边界，保留真实逻辑
def test_服务层_真实DB访问_外部LLM_API被Mock(self): ...
```

### 8.4 标记使用

```python
@pytest.mark.unit
async def test_纯函数逻辑_无IO依赖(self):
    ...

@pytest.mark.integration
async def test_完整请求链路_含DB读写(self):
    ...

@pytest.mark.slow
async def test_LLM完整调用_30秒超时(self):
    ...

@pytest.mark.regression
async def test_端到端_注册登录刷新退出(self):
    ...
```

### 8.5 pytest.raises 使用规范

```python
# ✅ 正确：捕获具体异常并验证错误码
with pytest.raises(UsernameExistsException) as exc_info:
    await register(db_session, username="testuser", password="pass123")
assert exc_info.value.error_code == "E1001"
assert exc_info.value.status_code == 409

# ❌ 禁止：仅捕获异常不验证具体字段
with pytest.raises(Exception):
    await register(db_session, ...)
```

---

## 9. 按 Phase 的测试重点

> 具体任务排期与测试进度追踪见 [ROADMAP.md](ROADMAP.md)。

| Phase | 测试重点 | 关键风险 |
|:---|:---|:---|
| **Phase 1** | 异常体系完整覆盖、JWT/bcrypt 安全模块、Auth Service 全部分支（含泄露检测）、Auth API 端点、前端 Auth Store + LoginPage + 路由守卫 | Token Rotation 泄露检测漏测 |
| **Phase 2** | Task CRUD API、TaskStateResolver 三层状态计算、Planner/Searcher/Fetcher 阶段、SSE 事件流、Celery 幂等锁、前端 ResearchPage 三态切换 | Pipeline 状态机死锁 / 竞态 |
| **Phase 3** | BM25 粗筛集成、LLM Rerank、Synthesis、Evidence Graph Build、Report Render、Cancel API、全链路集成测试、前端 Evidence Graph 双向联动 | CAS 并发更新丢失 / 证据-来源关联断裂 |
| **Phase 4** | Execution Context 持久化、Retry API、CAS 更新、限流激活、断点续跑集成测试 | 断点续跑状态恢复不完整 |
| **Phase 5** | Admin API、Trace API、ECharts 统计、全量回归、Pipeline 并发压测、限流阈值调优 | 高并发下 Pipeline 吞吐瓶颈 |
| **Phase 6** | v1.5/v2.0 功能增量（DAG 并行、多角色、SearXNG 降级）按需测试 | 按新增功能评估 |

---

## 10. 附录

### 10.1 常用测试命令速查

```bash
# ── 后端 ──

# 运行所有单元测试
pytest tests/unit/ -v

# 运行所有单元测试 + 覆盖率（HTML 报告）
pytest tests/unit/ -v --cov=app --cov-report=html

# 运行特定模块
pytest tests/unit/core/test_security.py -v

# 运行特定标记
pytest tests/ -v -m unit
pytest tests/ -v -m "not integration and not slow"

# 运行特定测试用例（关键字匹配）
pytest tests/ -v -k "test_过期token"

# 排除慢速测试
pytest tests/ -v -m "not slow"

# 运行集成测试
pytest tests/integration/ -v

# 运行回归测试
pytest tests/regression/ -v

# ── 前端 ──

# 单次运行
cd frontend && npm run test

# Watch 模式
cd frontend && npm run test:watch

# 单文件
cd frontend && npx vitest run authStore.test.js

# 覆盖率
cd frontend && npm run test -- --coverage
```

### 10.2 新模块测试上线流程

1. 模块代码完成后，在对应 `tests/unit/` 子目录创建 `test_{模块名}.py`
2. 按本文档第 8 节规范编写测试：每方法一个测试类、每分支一个用例、成功/失败成对
3. 本地运行 `pytest tests/unit/{子目录}/test_{模块名}.py -v`，全部通过
4. 运行全量单元测试 `pytest tests/unit/ -v`，确认无回归
5. 检查覆盖率 `pytest tests/unit/ -v --cov=app --cov-report=term-missing`，确认关键路径 100%
6. 提交代码时测试文件与功能代码在同一 commit

---

## 相关文档

- [CLAUDE.md](../CLAUDE.md) — 测试约定
- [ARCHITECTURE.md](ARCHITECTURE.md) — 架构设计（状态机、权限模型、非功能需求）
- [API.md](API.md) — 接口文档（错误码、SSE 协议）
- [DATABASE.md](DATABASE.md) — 表结构（索引、外键策略）
- [RESEARCH_PIPELINE.md](RESEARCH_PIPELINE.md) — Pipeline 各阶段设计
- [DEVELOPMENT.md](DEVELOPMENT.md) — 开发指南（项目结构、命令速查）
- [ROADMAP.md](ROADMAP.md) — 开发排期（Phase 准入规则）
- [RESEARCH_PIPELINE.md](RESEARCH_PIPELINE.md) — Pipeline 各阶段设计（含各模块锚点）
