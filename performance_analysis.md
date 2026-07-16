# ResearchMind 性能分析报告

> 生成时间：2026-07-08  
> 分析对象：150 样本 batch 压测（实际入库 145 + 6 失败 + 1 running）  
> 运行环境：服务器单 Celery Worker  
> 任务配置：`depth=quick`, `max_sources=10`

---

## 1. 核心结论

1. **端到端耗时**：P50 145s，P95 225s，P99 303s；平均 153s（约 2.5 分钟）。
2. **任务成功率**：95.04%（134 / 141 终态任务）。
3. **主要瓶颈**：
   - **Worker 稳定性**：6 个失败任务中 6 个为 `E3112 Celery Worker 崩溃/丢失`，是失败主因。
   - **Fetch 长尾与成功率**：P50 仅 2.36s，但 P95 49.83s、P99 98.46s；URL 实际成功率仅 53%。
   - **LLM 阶段**：synthesis P50 18.83s、render P50 17.08s、rerank P50 12.42s，合计约 48s，占 worker 处理时间的 32%。
4. **排队等待**：平均仅 4.43s，单 worker 当前未出现严重积压。

---

## 2. 端到端耗时

| 指标 | 值（秒） | 说明 |
|---|---|---|
| 平均端到端 | 153.18 | `created_at → completed_at` |
| P50 端到端 | 145 | 用户等待中位数 |
| P95 端到端 | 225 | 95% 任务在此时间内完成 |
| P99 端到端 | 303 | 长尾任务接近 5 分钟 |
| 最小端到端 | 0 | 存在脏数据/测试任务，需排查 |
| 最大端到端 | 643 | 严重长尾，约 10.7 分钟 |
| P50 Worker 处理 | 144 | `started_at → completed_at` |
| P95 Worker 处理 | 219 | 实际执行耗时 |
| P99 Worker 处理 | 281 | 执行长尾 |
| 平均排队等待 | 4.43 | `created_at → started_at` |

> 端到端与 Worker 处理时间几乎一致，说明当前单 worker 下排队时间可忽略。

---

## 3. 任务成功率与状态分布

### 3.1 总体统计

| 指标 | 值 |
|---|---|
| 总任务数 | 141 |
| 已完成（completed） | 134 |
| 成功数（completed + partially_completed） | 134 |
| 失败数（failed） | 7 |
| 取消数（canceled） | 0 |
| 运行中（running） | 1 |
| 严格成功率 | 95.04% |
| 宽松成功率 | 95.04% |

### 3.2 状态分布

| 状态 | 数量 | 占比 | 平均端到端（s） | 平均 Worker 处理（s） |
|---|---|---|---|---|
| completed | 134 | 94.37% | 155.65 | 150.99 |
| failed | 7 | 4.93% | 105.86 | 105.86 |
| running | 1 | 0.70% | — | — |

---

## 4. Pipeline 各阶段耗时

### 4.1 分阶段统计

| 阶段 | 平均（s） | P50（s） | P95（s） | P99（s） | 样本数 | 每任务平均次数 |
|---|---|---|---|---|---|---|
| synthesis | 20.41 | 18.83 | 31.70 | 40.81 | 163 | ~1.2 |
| render | 18.32 | 17.08 | 27.93 | 32.83 | 161 | ~1.1 |
| planning | 14.12 | 10.95 | 30.23 | 34.95 | 168 | ~1.2 |
| rerank | 12.93 | 12.42 | 19.33 | 25.95 | 164 | ~1.2 |
| fetch | 8.14 | 2.36 | 49.83 | 98.46 | 1635 | **~11.6** |
| search | 6.90 | 4.11 | 18.93 | 30.53 | 891 | **~6.3** |
| evidence_graph | 0.03 | 0.03 | 0.05 | 0.08 | 162 | ~1.1 |

### 4.2 关键观察

- **synthesis / render / rerank 是主要执行耗时**：三阶段 P50 合计约 48s，占 worker 处理时间（144s）的 33%。
- **search / fetch 次数多但单次中位数快**：平均每任务 6.3 次 search、11.6 次 fetch，但 P50 分别只有 4.1s 和 2.4s。
- **fetch 长尾非常严重**：P99 是 P50 的约 42 倍（98.46s / 2.36s），说明少数 URL 严重拖慢整体。
- **evidence_graph 完全健康**：毫秒级，不构成瓶颈。

---

## 5. Fetch 成功率与质量

### 5.1 URL 抓取状态分布

| fetch_status | 数量 | 占比 | 说明 |
|---|---|---|---|
| success | 1194 | 53.09% | 成功抓取 |
| blocked | 402 | 17.87% | 被反爬/防火墙拦截 |
| empty | 267 | 11.87% | 页面无内容或解析失败 |
| timeout | 81 | 3.60% | 超时 |
| dns_error | 29 | 1.29% | DNS 解析失败 |
| NULL | 276 | 12.27% | 未写入状态 |
| **合计** | **2249** | **100%** | — |

### 5.2 关键问题

- **实际 URL 抓取成功率仅 53%**，近一半来源不可用。
- `blocked` 占 18%，是最主要的失败类型，说明反爬策略需要优化。
- `empty` 占 12%，可能是 JS 渲染页面、内容提取失败或返回了错误页面。
- 12% 的 URL 状态为 NULL，说明 fetch 状态写入逻辑不完整，影响可观测性。

> 虽然任务完成率高达 95%，但系统通过跳过失败来源继续生成报告，可能导致证据覆盖面不足、报告质量下降。

---

## 6. Worker 崩溃分析（E3112）

### 6.1 失败任务详情

| 任务 ID | 错误码 | current_phase | completed_steps | 崩溃前运行秒数 |
|---|---|---|---|---|
| 0173a974-... | E3112 | searching | 2/7 | 43 |
| 217d220b-... | E3112 | fetching | 3/7 | 101 |
| 0d7a9e38-... | E3112 | reranking | 4/7 | 112 |
| 779003ef-... | E3112 | building_evidence_graph | 6/7 | 122 |
| f4a8d9bf-... | E3112 | synthesizing | 5/7 | 135 |
| f17e13aa-... | E3112 | synthesizing | 5/7 | 169 |
| 89723c5c-... | E3999 | planning | 1/7 | 54 |

### 6.2 关键发现

- 6 个 E3112 崩溃发生在 **searching / fetching / reranking / synthesizing / building_evidence_graph** 各个阶段。
- 崩溃前运行时间从 **43s 到 169s** 不等，不集中在某个固定超时阈值。
- 这排除了"某个阶段特定 bug"或"固定超时导致"的假设。

### 6.3 最可能原因

1. **Worker 进程被外部重启**（systemd/docker/健康检查/部署滚动）。
2. **内存不足 / OOM**：单 worker 连续处理 LLM + fetch 任务，内存累积后被系统 kill。
3. **Celery 连接心跳丢失**：Worker 与 Redis/数据库连接断开，被误判为丢失。

### 6.4 建议排查命令

```bash
# Celery Worker 日志
journalctl -u celery -n 500 --no-pager
# 或
docker logs <celery-worker-container> --tail 500

# 系统 OOM / 重启记录
dmesg -T | grep -i 'killed\|oom\|celery'
grep -i 'celery\|oom' /var/log/syslog
```

---

## 7. 瓶颈定位

### 7.1 第一瓶颈：Worker 稳定性（E3112）

- 导致 6/7 的任务失败。
- 不修复前，无论 fetch/LLM 多快，失败率都下不来。
- 单 worker 架构下，一个 worker 崩溃所有进行中的任务都失败。

### 7.2 第二瓶颈：Fetch 长尾与成功率

- P99 fetch 98.46s，拖慢部分任务。
- URL 成功率仅 53%，大量 `blocked` / `empty` / `timeout`。
- 影响报告证据质量和完整性。

### 7.3 第三瓶颈：LLM 阶段耗时

- synthesis P50 18.83s、render P50 17.08s、rerank P50 12.42s。
- 三阶段合计约 48s，是 worker 处理时间的主要组成部分。
- planning P95 30.23s，存在长尾。

### 7.4 非瓶颈

- **evidence_graph**：毫秒级，无需优化。
- **排队等待**：平均 4.43s，当前单 worker 下队列未积压。

---

## 8. 优化建议

### 8.1 P0：解决 Worker 崩溃（E3112）

| 优先级 | 措施 | 预期效果 |
|---|---|---|
| 立刻 | 查看 Celery 日志和 dmesg/syslog，定位是 OOM、异常 traceback 还是外部重启 | 明确根因 |
| 立刻 | 单 worker 改为多 worker：`celery -A app.tasks.celery_app worker --concurrency=2/4` | 失败率大幅下降，吞吐量提升 |
| 尽快 | 检查 `CELERY_TASK_LOCK_TTL`、`WORKER_TIMEOUT_SECONDS`、`PENDING_TASK_TIMEOUT_SECONDS` 是否合理 | 减少误判崩溃 |
| 尽快 | 增加 Worker 内存监控和自动重启策略 | 避免 OOM 导致雪崩 |

### 8.2 P1：提升 Fetch 成功率与速度

| 优先级 | 措施 | 预期效果 |
|---|---|---|
| 尽快 | 处理 `blocked`：轮换 User-Agent、加请求头、域名级限速、使用浏览器模式或第三方抓取服务 | blocked 从 18% 降到 5% 以下 |
| 尽快 | 处理 `empty`：增强 HTML→Markdown 解析，识别 JS 渲染页面，内容非空校验 | empty 从 12% 降到 3% 以下 |
| 尽快 | 处理 `timeout`：确保 `FETCH_TIMEOUT=15s` 严格生效，重试后总耗时不超过 20–30s | P99 fetch 从 98s 降到 30s 以下 |
| 尽快 | 补全 NULL 状态的 fetch_status 写入 | 可观测性提升 |
| 可选 | 增加内容缓存（URL hash → content），避免重复抓取 | 重复查询提速 |

### 8.3 P2：优化 LLM 阶段

| 优先级 | 措施 | 预期效果 |
|---|---|---|
| 可选 | 控制 synthesis 输入 context 长度，设置 token 预算 | synthesis 长尾降低 |
| 可选 | render 报告分片/虚拟滚动，避免一次性渲染超长 Markdown | render 耗时下降 |
| 可选 | planning 阶段限制 outline 长度和章节数 | planning P95 降低 |

### 8.4 P3：消除脏数据

| 优先级 | 措施 |
|---|---|
| 可选 | 排查 `min_e2e_seconds = 0` 的任务，确认是否为测试数据或状态机异常 |

---

## 9. 关键 SQL 速查

### 9.1 端到端 P50/P95/P99

```sql
WITH e2e AS (
    SELECT
        TIMESTAMPDIFF(SECOND, created_at, completed_at) AS e2e_seconds,
        TIMESTAMPDIFF(SECOND, started_at, completed_at) AS worker_seconds
    FROM research_tasks
    WHERE completed_at IS NOT NULL
      AND created_at >= '2026-07-07 00:00:00'
),
stats AS (
    SELECT
        e2e_seconds,
        worker_seconds,
        ROW_NUMBER() OVER (ORDER BY e2e_seconds) AS e2e_rn,
        ROW_NUMBER() OVER (ORDER BY worker_seconds) AS worker_rn,
        (SELECT COUNT(*) FROM e2e) AS cnt
    FROM e2e
)
SELECT
    MAX(CASE WHEN e2e_rn = FLOOR(cnt * 0.50) THEN e2e_seconds END) AS e2e_p50_seconds,
    MAX(CASE WHEN e2e_rn = FLOOR(cnt * 0.95) THEN e2e_seconds END) AS e2e_p95_seconds,
    MAX(CASE WHEN e2e_rn = FLOOR(cnt * 0.99) THEN e2e_seconds END) AS e2e_p99_seconds,
    MAX(CASE WHEN worker_rn = FLOOR(cnt * 0.50) THEN worker_seconds END) AS worker_p50_seconds,
    MAX(CASE WHEN worker_rn = FLOOR(cnt * 0.95) THEN worker_seconds END) AS worker_p95_seconds,
    MAX(CASE WHEN worker_rn = FLOOR(cnt * 0.99) THEN worker_seconds END) AS worker_p99_seconds,
    cnt AS sample_count
FROM stats;
```

### 9.2 各阶段耗时统计

```sql
WITH ranked_steps AS (
    SELECT
        step_type,
        duration_ms,
        ROW_NUMBER() OVER (PARTITION BY step_type ORDER BY duration_ms) AS rn,
        COUNT(*) OVER (PARTITION BY step_type) AS cnt
    FROM research_steps
    WHERE duration_ms IS NOT NULL
      AND status = 'completed'
)
SELECT
    step_type,
    ROUND(AVG(duration_ms) / 1000, 2) AS avg_seconds,
    ROUND(MAX(CASE WHEN rn = FLOOR(cnt * 0.50) THEN duration_ms END) / 1000, 2) AS p50_seconds,
    ROUND(MAX(CASE WHEN rn = FLOOR(cnt * 0.95) THEN duration_ms END) / 1000, 2) AS p95_seconds,
    ROUND(MAX(CASE WHEN rn = FLOOR(cnt * 0.99) THEN duration_ms END) / 1000, 2) AS p99_seconds,
    cnt AS sample_count
FROM ranked_steps
GROUP BY step_type, cnt
ORDER BY avg_seconds DESC;
```

### 9.3 Fetch 状态分布

```sql
SELECT
    fetch_status,
    COUNT(*) AS cnt,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
FROM research_sources
WHERE task_id IN (
    SELECT id FROM research_tasks WHERE created_at >= '2026-07-07 00:00:00'
)
GROUP BY fetch_status
ORDER BY cnt DESC;
```

### 9.4 Worker 崩溃任务明细

```sql
SELECT
    rt.id,
    rt.error_code,
    rt.current_phase,
    rt.completed_steps,
    rt.total_steps,
    TIMESTAMPDIFF(SECOND, rt.started_at, rt.updated_at) AS running_seconds_before_crash
FROM research_tasks rt
WHERE rt.status = 'failed'
  AND rt.created_at >= '2026-07-07 00:00:00'
ORDER BY running_seconds_before_crash DESC;
```

---

## 10. 后续跟踪指标

修复后建议重新跑 batch 并对比以下指标：

1. 端到端 P50 / P95 / P99
2. Worker 处理 P50 / P95 / P99
3. 任务成功率（严格/宽松）
4. Fetch URL 成功率（success / blocked / empty / timeout / dns_error）
5. E3112 出现频次
6. Worker 崩溃前平均运行时间
7. 排队等待时间（验证多 worker 后是否仍然可忽略）
