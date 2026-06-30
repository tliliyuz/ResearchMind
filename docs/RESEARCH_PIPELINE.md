# RESEARCH PIPELINE — 研究管线详细设计

| 属性 | 值 |
|:---|:---|
| 文档版本 | v1.0 |
| 最后更新 | 2026-06-19 |

本文档描述 ResearchMind 研究管线（Research Pipeline）的完整设计，涵盖 Planning → Search → Fetch → Rerank → Synthesis → Evidence Graph Build → Report Render 七阶段。各阶段的 Prompt 模板、算法策略、数据契约、`task_type` 驱动逻辑、SSE 事件映射、错误传播与断点续跑机制。

> **权威归属**：Pipeline 七阶段的高层定义（输入/输出/核心职责）、三层状态机（Task/Phase/Step）、失败分类学、SLA 目标见 [ARCHITECTURE.md §2-§5](ARCHITECTURE.md#2-系统分层与-pipeline-架构)（架构真理源）。本文档是各阶段的**深度设计展开**——每阶段的 Prompt 模板、算法细节、数据结构、阶段内决策逻辑以本文档为准。

---

## 1. Pipeline 总览

### 1.1 七阶段全景图

```
用户输入（topic + requirements）
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Core Research Engine                      │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│  │ PLANNING │──▶│  SEARCH  │──▶│  FETCH   │──▶│  RERANK  │ │
│  │ (LLM)    │   │ (Tavily) │   │ (HTTP)   │   │ (BM25+   │ │
│  │          │   │          │   │          │   │  LLM)    │ │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘ │
│                                                     │       │
│                                                     ▼       │
│  ┌──────────┐   ┌──────────────────┐                       │
│  │  REPORT  │◀──│ EVIDENCE GRAPH   │◀──┌──────────────┐    │
│  │  RENDER  │   │     BUILD        │   │  SYNTHESIS   │    │
│  │ (LLM)    │   │  (程序化构建)     │   │  (LLM)       │    │
│  └──────────┘   └──────────────────┘   └──────────────┘    │
│                                                              │
│  核心产物：Evidence Graph（结构化认知资产）                    │
├─────────────────────────────────────────────────────────────┤
│                 Presentation Layer                           │
│                                                              │
│  Report JSON（Markdown + 引用锚点 + Evidence Graph + Trace）  │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 各阶段速览

| 阶段 | 引擎 | 输入 | 输出 | v1.0 并行度 | 致命失败 |
|:---|:---|:---|:---|:---|:---|
| **Planning** | LLM | topic + requirements | SubQuestion[] (3-5) | 1 次调用 | ✅ |
| **Search** | Tavily API | SubQuestion[] | SearchResult[] | 每个子问题串行 | ❌（单个可降级） |
| **Fetch** | HTTP | SearchResult[] (去重后) | FetchedDoc[] | 每个 URL 串行 | ❌（单个可降级） |
| **Rerank** | BM25 + LLM | FetchedDoc[] + SubQuestion[] | Evidence[] (top-K) | BM25 批量；LLM 1 次 | ✅ |
| **Synthesis** | LLM | Evidence[] + SubQuestion[] | SynthesisNotes | 1 次调用 | ✅ |
| **Evidence Graph** | 程序化 | SynthesisNotes + Evidence[] + Sources[] | EvidenceGraph | 纯计算 | ✅ |
| **Render** | LLM | EvidenceGraph + 模板 | Report JSON | 1 次调用 | ✅ |

> **v1.0 串行约束**：MVP 所有阶段线性串行（前一阶段全部完成 → 下一阶段开始）。v2.0 升级为真 DAG 后，Search/Fetch 可跨子问题并行执行。v1.0 的 `research_steps` 已通过 `parent_step_id` 预留树结构，升级不涉及表结构变更。

### 1.3 版本范围

本文档描述 v1.0 MVP 的管线行为。以 `[v1.5]` / `[v2]` 标记预留的扩展点。各版本演进路线见 [ROADMAP.md](ROADMAP.md)。

---

## 2. Planning — 研究主题拆解

### 2.1 目标

将用户输入的 `topic` 拆解为 3-5 个可独立检索的 SubQuestion。这是全 Pipeline 最重要的决策点——拆解质量直接决定后续搜索的覆盖度和最终报告的结构。

### 2.2 输入

| 字段 | 来源 | 说明 |
|:---|:---|:---|
| `topic` | 用户输入 | 研究主题（≤ 500 字符） |
| `task_type` | `requirements.task_type` | `comparison` / `explainer` / `analysis` |
| `language` | `requirements.language` | 报告语言，如 `zh` / `en` |

### 2.3 System Prompt

```
你是一个专业研究规划师。你的任务是将用户的研究主题拆解为 3-5 个可独立进行网络搜索的子问题。

研究类型：{task_type}
输出语言：{language}

拆解原则：
1. 每个子问题必须可独立搜索（self-contained），不依赖其他子问题的结果
2. 子问题应覆盖主题的不同维度/角度，避免重叠
3. 子问题的答案集合应能组合成一个完整的研究报告
4. 使用与研究类型匹配的拆解策略（见下方策略说明）
5. 输出严格 JSON 格式，不要输出其他内容

{task_type_strategy}

示例输出格式：
{
  "sub_questions": [
    "子问题 1 文本",
    "子问题 2 文本"
  ],
  "rationale": "拆解逻辑简述（1-2 句）"
}
```

### 2.4 task_type 驱动的拆解策略

`task_type_strategy` 段落在运行时根据 `task_type` 注入：

| task_type | 注入的策略说明 |
|:---|:---|
| `comparison` | **对比型拆解**：首先生成对比维度列表（如性能、生态、成本、安全性），然后每个维度 × 候选对象矩阵生成检索子问题。确保每个候选对象在关键维度上都被覆盖。 |
| `explainer` | **解释型拆解**：先分析主题隐含的研究方向（如最新进展、不同流派、争议焦点），再将每个方向拆为独立的检索子问题。优先覆盖不同观点/流派，避免单一叙事。 |
| `analysis` | **影响分析型拆解**：按因果链拆解——原因 → 直接影响 → 间接影响 → 应对策略。每个子问题覆盖因果链的一个环节，确保最终报告可形成递进推理。 |

> **为什么 Planner 策略必须按 `task_type` 分叉而非让 LLM 自行判断？** LLM 在 Planning 阶段对最终报告结构没有全局视野。如果不指定策略，LLM 倾向产出「关键词展开式」子问题（把 topic 的关键词替换近义词），缺乏结构化和维度覆盖。这会导致后续 Rerank 无法按 task_type 偏好排序，Synthesis 缺乏组织轴线，最终报告结构松散。`task_type` 是整个 Pipeline 的结构性约束——从 Planning 阶段就注入。

### 2.5 参数

| 参数 | v1.0 默认值 | 说明 |
|:---|:---|:---|
| `model` | deepseek-v4-pro | 规划任务需强推理能力 |
| `max_tokens` | 1000 | 输出 3-5 个子问题 + rationale |
| `temperature` | 0.3 | 低温度保证拆解稳定性 |
| `deep_thinking` | `True` | 需深度思考拆解逻辑 |

### 2.6 输出校验

```
Planner 输出 → Pydantic 校验：
  ✅ sub_questions 长度 3-5
  ✅ 每个子问题 ≤ 200 字符
  ✅ 每个子问题至少含 2 个实体/关键词
  ❌ 不满足 → 重试（最多 3 次）
  ❌ 3 次仍失败 → E3101 PlanningFailed
```

| 校验规则 | 目的 |
|:---|:---|
| 数量 3-5 | 太少无覆盖度，太多增加搜索成本 |
| ≤ 200 字符 | 控制搜索 query 长度，避免过拟合 |
| ≥ 2 个实体/关键词 | 防止空洞子问题（如「研究一下这个」） |

### 2.7 状态转换

| 事件 | Phase | Step | SSE 事件 |
|:---|:---|:---|:---|
| Planner 开始 | → `planning` | `planning_01` STARTED | `phase.started` + `step.started` |
| SubQuestions 产出 | — | `planning_01` 进度更新 | `step.progress` (含 `sub_questions_generated`) |
| Planner 完成 | — | `planning_01` COMPLETED | `step.completed` (含 sub_questions 摘要) + `phase.completed` (含 `duration_ms`) |
| Planner 失败 | — | `planning_01` FAILED | `step.failed` → `task.failed` (E3101, recoverable=false) |

### 2.8 Checkpoint

Planning 完成后立即保存 checkpoint：
```json
{
  "phase": "planning",
  "last_completed_step_id": "planning_01_uuid",
  "saved_at": "2026-06-19T10:00:06+00:00"
}
```

> Planning 是第一个阶段，失败后无 checkpoint 可恢复。E3101 的 `recoverable=false` 反映这一事实——不存在「已完成阶段」可以复用。

---

## 3. Search — 多子问题搜索

### 3.1 目标

对 Planning 产出的每个 SubQuestion 调用 Tavily Search API，获取 URL + 标题 + 摘要。每个子问题独立搜索，结果跨子问题去重。

### 3.2 搜索策略

```
for each sub_question in SubQuestion[]:    # v1.0 串行
    ┌─────────────────────────────────┐
    │ Tavily Search API               │
    │   query = sub_question           │
    │   search_depth = "advanced"      │
    │   max_results = 5                │
    │   include_answer = false         │  ← 不需要 Tavily 的 LLM 摘要
    │   include_raw_content = false    │  ← 正文在 Fetch 阶段获取
    │   include_domains = []           │  ← v1.0 不过滤域名
    │   exclude_domains = []           │  ← [v1.5] 支持 requirements.exclude_domains
    └─────────────────────────────────┘
            │
            ▼
    SearchResult[] (title + url + snippet)
            │
            ▼
    跨子问题 URL 去重（保留首次出现的 sub_question 归属）
```

| 参数 | v1.0 值 | 说明 |
|:---|:---|:---|
| `search_depth` | `advanced` | 使用 Tavily 深度搜索，结果更全 |
| `max_results` / sub_question | 5 | 子问题 × 5 = 总计 15-25 原始结果 |
| 总结果上限 | 25 | 去重后超过 25 条则按 Tavily 评分截断 |
| 重试 | 2 次（指数退避 1s/2s） | 单次 API 调用失败或超时 |

### 3.3 输出数据结构

```python
SearchResult = {
    "url": str,              # 搜索结果 URL
    "title": str,            # 页面标题
    "snippet": str,          # Tavily 返回的摘要
    "source_sub_question": str,  # 来自哪个子问题
    "tavily_score": float,   # Tavily 相关性评分
}
```

### 3.4 失败策略

| 场景 | 行为 | Step 状态 |
|:---|:---|:---|
| 单个子问题搜索 0 结果 | 跳过该子问题，继续搜索下一个 | SKIPPED |
| 单个子问题 Tavily 调用失败 | 重试 2 次；仍失败 → 跳过 | SKIPPED |
| 全部子问题 0 结果或全失败 | 致命 | FAILED → E3102 |
| 去重后总结果 < 3 | 触发质量警告，但不阻断 | WARNING |

> **为什么单个子问题失败不致命？** Search 失败不等于「无法研究」。一个子问题的搜索结果缺失时，Synthesis 仍可基于其他子问题的证据产出部分报告，最终 Task 可能走向 `PARTIALLY_COMPLETED`。全部子问题无结果才说明「Tavily 不可用或主题无法被搜索」，此时应告知用户而非产出空报告。

### 3.5 状态转换

| 事件 | SSE 事件 | 携带数据 |
|:---|:---|:---|
| Search 阶段开始 | `phase.started` | `phase: "searching"` |
| 单个子问题搜索开始 | `step.started` | `step_type: "search"`, `label: "搜索子问题 N: ..."` |
| 单个子问题搜索完成 | `step.progress` | `results_found: N` |
| 单个子问题搜索完成 | `step.completed` | `results_count`, `selected` |
| 全部子问题搜索完成 | `phase.completed` | `total_results`, `after_dedup`, `duration_ms` |
| 全部子问题搜索失败 | `task.failed` | E3102, `recoverable: true` (可重试) |

### 3.6 Checkpoint

Search 阶段完成后保存 checkpoint，包含去重后的 URL 列表，供 Retry 时跳过已完成搜索。

---

## 4. Fetch — 网页内容抓取

### 4.1 目标

对去重后的 SearchResult URL 列表进行网页抓取，提取正文内容并截断。

### 4.2 抓取流程

```
for each url in deduped_urls:           # v1.0 串行
    ┌─────────────────────────────────┐
    │ URL 安全检查                     │
    │   ✅ 协议仅 http/https           │
    │   ✅ 非内网 IP（127.x, 10.x,    │
    │      172.16-31.x, 192.168.x）    │
    │   ❌ 违规 → 跳过                 │
    └─────────────────────────────────┘
            │
            ▼
    ┌─────────────────────────────────┐
    │ HTTP GET（timeout=15s）          │
    │   User-Agent: ResearchMind/1.0   │
    │   Accept: text/html              │
    └─────────────────────────────────┘
            │
    ┌───────┴────────┐
    │ 成功 (200)      │ 失败 (非200/超时/DNS)
    ▼                 ▼
   正文提取          跳过该 URL
   (trafilatura)     (SKIPPED)
    │
    ▼
   内容截断（100KB）
    │
    ▼
   FetchedDoc
```

### 4.3 正文提取

使用 `trafilatura` 库提取网页正文：
- 自动识别正文区域（去除导航、广告、评论区）
- 保留标题层级结构
- 输出 Markdown 格式

> **为什么用 trafilatura 而非 BeautifulSoup 手写规则？** trafilatura 针对新闻/文章类网页优化，内置 boiletplate removal 和正文识别算法。ResearchMind 的目标页面主要是技术文章和新闻，trafilatura 的默认策略已经足够。不手写规则避免陷入「每遇到一种新网页结构就要更新提取器」的维护陷阱。

### 4.4 安全约束

| 约束 | 值 | 说明 |
|:---|:---|:---|
| 协议白名单 | `http`, `https` | 禁止 `file://`, `ftp://` 等 |
| IP 黑名单 | 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 | 防止 SSRF 攻击 |
| 单页大小上限 | 100 KB（截断） | 防止超大页面 OOM |
| 响应体上限 | 2 MB（超过则跳过） | 防止下载非文本资源 |
| 请求超时 | 15 秒 | 防止无限等待 |
| 总 URL 上限 | 15 个/任务 | 成本 + 时间控制 |

### 4.5 失败策略

| 场景 | 行为 | Step 状态 | 重试 |
|:---|:---|:---|:---|
| HTTP 200 + 正文提取成功 | 正常 | COMPLETED | — |
| 超时 | 重试 1 次 → 仍失败则跳过 | SKIPPED | 1 |
| HTTP 403/404/5xx | 不重试，直接跳过 | SKIPPED | 0 |
| DNS 解析失败 | 不重试，直接跳过 | SKIPPED | 0 |
| 正文提取为空 | 跳过 | SKIPPED | 0 |
| 全部 URL 失败 | 致命（如果剩余阶段无法满足 Evidence Threshold） | FAILED | — |

> **403 为什么不重试？** 403 表示服务器明确拒绝访问，换时间/换 IP 大概率仍然 403。浪费重试预算不如跳过该源，用其他可访问的源凑够 Evidence。

### 4.6 输出数据结构

```python
FetchedDoc = {
    "url": str,
    "title": str,
    "domain": str,              # 提取的域名（用于来源展示）
    "content": str,             # trafilatura 提取的 Markdown 正文（截断后） # 持久化到 research_sources.content，供 Rerank 阶段读取
    "content_length": int,      # 原始正文长度
    "fetched_at": datetime,
    "fetch_status": str,        # "success" / "timeout" / "blocked" / "empty" / "dns_error"
}
```

### 4.7 状态转换

| 事件 | SSE 事件 | 携带数据 |
|:---|:---|:---|
| Fetch 阶段开始 | `phase.started` | `phase: "fetching"` |
| 单个 URL 抓取开始 | `step.started` | `url`, `label` |
| 单个 URL 抓取成功 | `step.completed` | `url`, `content_length` |
| 单个 URL 抓取失败 | `step.skipped` | `url`, `reason` |
| 全部 URL 抓取完成 | `phase.completed` | `successful`, `failed`, `total_size_kb`, `duration_ms` |

### 4.8 Checkpoint

每个 URL 抓取完成后保存 checkpoint，记录已成功抓取的 URL 列表。Retry 时跳过已成功的 URL。

---

## 5. Rerank — 证据粗筛+精排

### 5.1 目标

从 Fetch 阶段获取的文档中，筛选出与研究主题最相关、信息量最高的内容片段，作为 Synthesis 的输入证据。采用**二段式排序**：BM25 粗筛 → LLM 精排。

### 5.2 二段式架构

```
FetchedDoc[] (最多 15 篇, 每篇 ≤ 100KB)
         │
         ▼
┌─────────────────────────────────────┐
│ Stage 1: BM25 粗筛（程序化，~50ms） │
│                                     │
│  1. 每篇文档按段落切分为 segments    │
│  2. 每个 segment + sub_question     │
│     计算 BM25 得分                  │
│  3. 取每篇文档 top-3 segments       │
│     → 最多 45 个候选 segments       │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│ Stage 2: LLM Rerank 精排            │
│                                     │
│  1. 将候选 segments + sub_questions │
│     组装为 Rerank Prompt            │
│  2. LLM 对每个 segment 打分 (0-10)  │
│  3. 按 task_type 加权调整           │
│  4. 取 top-K 作为 Evidence[]        │
└─────────────────────────────────────┘
         │
         ▼
Evidence[] (top-K, K = min(max_sources, 候选数))
```

> **实现模块**：
> - `app/pipeline/reranker.py`（已就位）：`BaseReranker` ABC 抽象基类 + DeepSeek LLM Rerank 实现。ABC 定义 `rerank(query, candidates, top_k)` 方法签名。v1.0 使用 LLM Rerank（DeepSeek API Prompt 内打分），v1.5 可替换为专用 Rerank API 实现。

### 5.2a 数据来源

Rerank 阶段不依赖 Fetch step 的 `output` JSON 传递正文（避免单条 JSON 过大）。启动时直接从 `research_sources` 表读取：

```sql
SELECT id, url, title, domain, content
FROM research_sources
WHERE task_id = ? AND fetch_status = 'success';
```

每行映射为一个 `FetchedDoc`，其中 `id` 对应 `source_id`，用于后续 Evidence Graph 的 `[来源N]` 引用。该设计保证 Retry 时正文可复用，且断点续跑无需重新抓取。
> - `app/pipeline/fusion.py`：RRF 多路融合排序（`rrf_fusion()`），v1.5 引入 SearXNG 作为降级后端后用于 Tavily + SearXNG 双路结果融合。算法 `score = Σ 1/(60 + rank_i)`。**v1.0 代码已就位，不激活**。适配 ResearchMind 自有 SearchResult/SearchOutput 类型。

### 5.3 Stage 1：BM25 粗筛

| 参数 | 值 | 说明 |
|:---|:---|:---|
| 分词器 | jieba (中文) / split (英文) | 按 `language` 选择 |
| 分段策略 | 按 `\n\n` 段落切分 | 每段 ≤ 2000 字符 |
| 每文档取 top | 3 segments | 保证每个来源至少有 1 个候选，最多 3 个 |
| 候选总数上限 | 45 | = 15 docs × 3 segments |

> **为什么 Stage 1 不用纯向量检索？** 向量检索依赖 Embedding 模型质量，且额外增加 API 调用延迟。BM25 是纯本地计算（jieba 分词 + NumPy 矩阵），对 15 篇文档的段落级评分在 50ms 内完成，零 API 成本。
>
> **v1.5 句级匹配**：`app/pipeline/sentence_matcher.py` 提供句级 BM25 定位 + 修辞角色过滤（`match_sentences()` / `filter_chunk_sentences()`），在段落内部定位最佳证据句并过滤引用性句子（示例/测试/TODO 等）。**v1.0 代码已就位，v1.5 激活**。适配 ResearchMind 自有类型。

### 5.4 Stage 2：LLM Rerank

#### System Prompt

```
你是一个研究证据评审专家。你需要对以下内容片段进行相关性评分。

研究主题：{topic}
研究类型：{task_type}
子问题：{sub_questions}

评分标准（0-10）：
- 相关性：内容是否直接回答子问题（权重 40%）
- 信息量：内容是否包含具体数据、事实、观点（权重 30%）
- 权威性：来源是否可靠（.gov/.edu 加分，个人博客减分）（权重 15%）
- {task_type_dimension}（权重 15%）

逐条评分，输出严格 JSON 格式：
{
  "ratings": [
    {"segment_index": 0, "score": 8.5, "rationale": "一句话理由"},
    ...
  ]
}
```

#### task_type 加权维度

| task_type | `task_type_dimension` | 说明 |
|:---|:---|:---|
| `comparison` | 属性对齐度：内容是否包含可对比的维度信息 | 偏爱「A 的延迟是 Xms，B 的延迟是 Yms」这类可对齐的事实 |
| `explainer` | 观点新颖度：内容是否提供独特观点而非重复已有信息 | 偏爱小众但信息密度高的源 |
| `analysis` | 因果关联度：内容是否包含因果推理或影响分析 | 偏爱含「导致」「因此」「影响」等因果链的内容 |

> `task_type_dimension` 直接变更 Rerank 的评分维度权重，而非仅靠 LLM 「自己理解」。这保证了不同 task_type 产出的 Evidence 集合具有不同的信息侧重，为后续 Synthesis 提供差异化素材。

### 5.5 输出数据结构

```python
Evidence = {
    "source_url": str,
    "source_title": str,
    "domain": str,
    "content": str,              # 入选的 segment 原文
    "relevance_score": float,    # LLM 评分 (0-10)
    "bm25_score": float,         # BM25 粗筛得分（调试用）
    "sub_question_index": int,   # 关联的子问题序号
    "word_count": int,           # segment 字数
}
```

### 5.6 失败策略

| 场景 | 行为 |
|:---|:---|
| BM25 粗筛后候选为空 | 致命 → E3105（输入数据问题） |
| LLM Rerank 单次失败 | 重试 2 次 |
| LLM Rerank 重试耗尽 | 致命 → E3105, `recoverable=false` |
| LLM 返回无效 JSON | 重试（计入重试次数） |
| 精排后 Evidence 数量 < 3 | 触发质量警告，不阻断 |

### 5.7 状态转换

| 事件 | SSE 事件 | 携带数据 |
|:---|:---|:---|
| Rerank 阶段开始 | `phase.started` | `phase: "reranking"` |
| BM25 粗筛完成 | `step.progress` | `candidates_count` |
| LLM Rerank 完成 | `step.completed` | `evidence_count`, `avg_score`, `top_domains` |
| Rerank 失败 | `task.failed` | E3105 |

---

## 6. Synthesis — 跨源综合

### 6.1 目标

对 Rerank 产出的 Evidence[] 进行跨源综合：识别共识观点、发现矛盾与冲突、按主题聚类、生成 SynthesisNotes——这是 Evidence Graph 构建前的「认知整理」步骤。

### 6.2 System Prompt

```
你是一个研究综合专家。请基于以下研究证据进行跨源综合。

研究主题：{topic}
研究类型：{task_type}

研究证据（共 {evidence_count} 条）：
{evidence_items_formatted}

请完成以下任务：

1. **观点聚类**：将证据按观点/结论分组，每组标注核心主题
2. **共识识别**：标记多个来源共同支持的高置信度结论
3. **冲突发现**：标注不同来源之间的矛盾或分歧
4. **信息缺口**：指出研究主题中未被证据覆盖的方面

输出严格 JSON 格式：
{
  "clusters": [
    {
      "theme": "聚类主题",
      "summary": "该聚类的核心结论（1-2 句）",
      "consensus_level": "strong" | "moderate" | "weak",
      "supporting_evidence_indices": [0, 3, 7],
      "conflicting_evidence_indices": []
    }
  ],
  "conflicts": [
    {
      "topic": "分歧主题",
      "position_a": {"summary": "...", "evidence_indices": [1]},
      "position_b": {"summary": "...", "evidence_indices": [4]}
    }
  ],
  "knowledge_gaps": ["未被充分覆盖的方面 1", ...],
  "overall_assessment": "整体证据质量评估（2-3 句）"
}
```

### 6.3 Evidence 格式化策略

```
对于每条 Evidence：
  来源标注：[来源 N] {domain} — {title}
  内容：{content}

Evidence 按 relevance_score 降序排列
最多传入 K = min(max_sources, evidence_count) 条
单条 Evidence 内容截断至 1500 字符（LLM context 窗口有限）
```

> **Token 预算控制**：各阶段内部自行实现 Token 预算截断（如 Rerank 的 `_build_rerank_prompt()` 中的逐步截断逻辑），确保每阶段传入 LLM 的内容不超过 Token 预算。System Prompt 模板需替换为本文档各节定义的 Prompt。单条 Evidence 截断至 1500 字符是 ResearchMind 自有实现策略。ResearchMind 无独立 prompt_builder 模块，各阶段 Prompt 构建逻辑内聚在对应阶段文件中。

### 6.4 参数

| 参数 | v1.0 值 | 说明 |
|:---|:---|:---|
| `model` | deepseek-v4-pro | 高难度认知任务 |
| `max_tokens` | 5000 | 聚类输出可能很长 |
| `temperature` | 0.3 | 低温度保证综合一致性 |
| `deep_thinking` | `True` | 需深度跨源推理 |
| 最大输入 Evidence 数 | `max_sources` 条 | 截断超出部分 |
| 单条 Evidence 截断 | 1500 字符 | 保留核心信息，控制 context 长度 |

### 6.5 失败策略

| 场景 | 行为 |
|:---|:---|
| LLM 调用失败 | 重试 3 次 |
| 重试耗尽 | 致命 → E3104, `recoverable=true` |
| LLM 返回无效 JSON | 重试（计入次数） |
| 输出中 conflict 为 null（LLM 未完成冲突检测） | 不阻断，clusters 仍可用于后续步骤 |

### 6.6 状态转换

| 事件 | SSE 事件 | 携带数据 |
|:---|:---|:---|
| Synthesis 开始 | `phase.started` | `phase: "synthesizing"` |
| 观点聚类完成 | `step.progress` | `clusters_count` |
| 综合完成 | `step.completed` | `clusters`, `conflicts`, `gaps_count` |
| 综合失败 | `step.failed` → `task.failed` | E3104, `recoverable: true` |

### 6.7 Checkpoint

Synthesis 完成后保存 checkpoint。Retry 时可复用 SynthesisNotes，跳过 LLM 综合步骤。

---

## 7. Evidence Graph Build — 结构化认知资产

### 7.1 目标

将 SynthesisNotes + Evidence[] + Sources[] 构建为结构化的 **Evidence Graph**——这是 ResearchMind 全流程的核心产物，独立于任何报告格式。后续 Report Render 读取 Evidence Graph 渲染为具体格式的报告。

### 7.2 为什么 Evidence Graph 是核心产物

| 没有 Evidence Graph | 有 Evidence Graph |
|:---|:---|
| Synthesis 和 Report 耦合，换模板需重跑全 Pipeline | 一个 Graph → 多模板渲染 |
| 无法产出一份研究的两个版本（如技术版+管理版） | 同一 Graph 渲染为不同视角的报告 |
| 报告格式变更侵入核心引擎 | 表达层独立演进 |
| 引用映射散落在 Markdown 中，无法程序化校验 | 结构化 mapping，Section→Evidence→Source 可追溯 |

### 7.3 数据模型

```python
EvidenceGraph = {
    "task_id": str,
    "generated_at": datetime,

    # 核心：结构化证据条目
    "items": [
        {
            "index": int,                    # 证据序号（全图唯一）
            "source_id": int,                # → research_sources.id
            "source_url": str,
            "source_title": str,
            "domain": str,
            "content": str,                  # 证据原文 segment
            "relevance_score": float,        # LLM Rerank 评分 (0-1) [Deviation] 原文档写 0-10，实际 Rerank 归一化为 0-1
            "cluster_theme": str,            # 所属 Synthesis 聚类主题
            "consensus_level": str,          # strong / moderate / weak
            "used_in_sections": [str],       # 被哪些 report_section 引用（Report Render 阶段填充）
        }
    ],

    # Synthesis 聚类（从 SynthesisNotes 结构化）
    "clusters": [
        {
            "theme": str,
            "summary": str,
            "consensus_level": str,
            "evidence_indices": [int],
        }
    ],

    # 冲突记录
    "conflicts": [
        {
            "topic": str,
            "position_a": {"summary": str, "evidence_indices": [int]},
            "position_b": {"summary": str, "evidence_indices": [int]},
        }
    ],

    # 知识缺口
    "knowledge_gaps": [str],

    # 来源清单
    "sources": [
        {
            "id": int,                       # → research_sources.id
            "url": str,
            "title": str,
            "domain": str,
            "evidence_count": int,           # 该源贡献的证据数
        }
    ]
}
```

### 7.4 构建过程

```
SynthesisNotes + Evidence[] + Sources[]
         │
         ▼
1. 导入 Evidence[] → items[]（复制 Rerank 结果）
         │
         ▼
2. 导入 SynthesisNotes.clusters → clusters[]
   将每个 cluster.supporting_evidence_indices
   写回 items[].cluster_theme + consensus_level
         │
         ▼
3. 导入 SynthesisNotes.conflicts → conflicts[]
         │
         ▼
4. 导入 SynthesisNotes.knowledge_gaps → knowledge_gaps[]
         │
         ▼
5. 聚合 Sources[] → sources[]
   统计每个 source 贡献的 evidence 数
         │
         ▼
6. 按 relevance_score 降序排列 items[]
   重新分配 index（保证全图唯一递增）
         │
         ▼
EvidenceGraph（结构化字典，可 JSON 序列化）
```

> Evidence Graph Build 是**纯程序化步骤**，不调用 LLM。所有信息已在前面阶段产出，此步骤仅作结构化组装和索引分配。这是有意的设计——核心认知资产的组装不依赖不可靠的 LLM 随机输出。

### 7.5 持久化

> Evidence Graph 通过 `evidence_items`、`research_sources`、`section_evidence` 三表持久化。完整映射关系与表结构见 [DATABASE.md §2](DATABASE.md#2-表结构)。

### 7.6 状态转换

| 事件 | SSE 事件 | 携带数据 |
|:---|:---|:---|
| Evidence Graph 构建开始 | `phase.started` | `phase: "building_evidence_graph"` |
| 构建完成 | `step.completed` | `item_count`, `cluster_count`, `source_count` |
| 构建失败 | `task.failed` | E3106, `recoverable=false` |

> **为什么 E3106 不可恢复？** Evidence Graph Build 是纯数据组装。如果失败，说明上游数据（Evidence、SynthesisNotes）有结构性问题，必须修复上游后重跑 Pipeline，而非简单 Retry 此阶段。

---

## 8. Report Render — 报告渲染

### 8.1 目标

读取 Evidence Graph，按 `task_type` 选择模板，调用 LLM 渲染 Markdown 报告 + 引用锚点，组装最终 Report JSON。

### 8.2 模板选择

| task_type | 模板 | Section 组织方式 |
|:---|:---|:---|
| `comparison` | `comparison_v1` | 1. 概述 → 2. 候选对象简介 → 3. 对比维度矩阵 → 4. 逐维度深度分析 → 5. 总结与建议 |
| `explainer` | `explainer_v1` | 1. 背景 → 2-N. 按研究方向/聚类组织章节 → N+1. 争议与前沿 → 总结 |
| `analysis` | `analysis_v1` | 1. 现状概述 → 2. 威胁/原因分析 → 3. 影响推演 → 4. 应对策略 → 5. 时间线预估 |

### 8.3 System Prompt

```
你是一个专业研究报告撰写专家。请基于以下研究证据图谱撰写报告。

研究主题：{topic}
研究类型：{task_type}
报告语言：{language}
报告模板：{template_sections_description}

证据图谱：
- 证据条目：{item_count} 条
- 观点聚类：{clusters_summary}
- 已知冲突：{conflicts_summary}
- 知识缺口：{knowledge_gaps}

证据详情：
{evidence_items_formatted}

写作要求：
1. 每个 Section 的内容必须基于提供的证据，不得编造
2. 每个事实性陈述必须标注来源引用：`[来源N]`
3. Section 末尾列出该节使用的所有来源索引
4. 使用 Markdown 格式，包含标题层级、列表、表格（如需要）
5. 承认知识缺口——不要为了报告「完整」而编造内容

输出格式：
{sections_json_schema}
```

### 8.4 引用锚点机制

```
对于每个 Section：
  1. LLM 在 Markdown 正文中使用 [来源N] 标注引用
  2. 渲染完成后，正则提取 Section 中出现的所有 [来源N]
  3. 去重 + 排序 → 填入 section.sources[]
  4. 写入 section_evidence 关联表（M:N）

示例：
  Section.content: "NIST 正在推进 PQC 标准化[来源0]，预计 2024 年发布最终标准[来源2]。"
  → section.sources: [{"id": 1, "evidence_index": 0}, {"id": 3, "evidence_index": 2}]
```

> **[Deviation]** `[来源N]` 中的 `N` 使用 0-based `GraphItem.index`（与 `API.md §3.3` 及前端 `markdown.js` 解析一致），**不等同于** `research_sources.id`。`section.sources[].id` 仍为 `research_sources.id`，`section.sources[].evidence_index` 存储 `GraphItem.index`。原示例中 `[来源1]` 映射到 `evidence_index: 0` 的表述已修正。

### 8.5 输出 JSON Schema

每个 Section 输出：

```json
{
  "heading": "2. 量子计算对 RSA 的威胁",
  "content": "Markdown 正文，含 [来源N] 引用标注...",
  "sources": [
    {"id": 1, "evidence_index": 0},
    {"id": 3, "evidence_index": 2}
  ]
}
```

完整报告结构见 [API.md §3.3 `GET /report` 响应](API.md#33-结果获取)。

### 8.6 参数

| 参数 | v1.0 值 | 说明 |
|:---|:---|:---|
| `model` | deepseek-v4-pro | 报告质量至关重要 |
| `max_tokens` | 8000 | 长报告需要大输出窗口 |
| `temperature` | 0.5 | 适度创意保证可读性 |
| `deep_thinking` | `False` | 报告渲染主要靠模板约束 |

### 8.7 失败策略

| 场景 | 行为 |
|:---|:---|
| LLM 调用失败 | 重试 1 次 |
| 重试耗尽 | 致命 → E3107, `recoverable=true` (可复用 Evidence Graph 重渲) |
| Section 数量 < 预期 | 不阻断，输出已有 Section |
| 引用提取失败（内容无 [来源N]） | 该 Section 的 `sources` 为空，标记 `citation_issues` |

### 8.8 后处理

```
Report Render 输出
         │
         ▼
1. 正则提取所有 Section 中的 [来源N] 引用
2. 按 Section 分组 → 填充 section.sources[]
3. 写入 section_evidence 关联表
4. 更新 research_tasks.completed_at
5. 组装最终 Report JSON（含 Evidence Graph + Trace）
```

> **引用审计**：`app/core/evidence_auditor.py` 提供程序级三层证据审计（`audit_evidence()`）：第一层引用存在性检查（正则提取 `[来源N]` 并验证是否缺失引用）；第二层来源一致性检查（引用来源是否集中在可信源）；第三层句级证据回溯（逐句验证事实性断言能否在来源中找到原文支撑）。v1.0 MVP 使用第一层；v1.5 启用全部三层。适配 ResearchMind 自有 SearchResult 类型。

### 8.9 状态转换

| 事件 | SSE 事件 | 携带数据 |
|:---|:---|:---|
| Render 开始 | `phase.started` | `phase: "rendering"` |
| 各 Section 渲染进度 | `step.progress` | `sections_completed`, `total_sections` |
| Render 完成 | `step.completed` + `task.completed` | `section_count`, `total_sources`, `total_evidence` |
| Render 失败 | `task.failed` | E3107, `recoverable: true` |

---

## 9. Pipeline SSE 事件映射

### 9.1 事件总览

> SSE 事件协议、wire format、心跳机制见 [API.md §4 SSE 事件协议](API.md#4-sse-事件协议)（API 真理源）。本节仅描述 Pipeline 各阶段如何映射到 SSE 事件。
>
> **SSE 事件发射器**：`app/pipeline/sse_bridge.py` 封装 `StreamingResponse` 传输层 + 15 种事件类型发射逻辑（v1.0）+ 2 种预留 [v2] + `seq` 序号（保证事件有序）+ 重连快照（`task.status.snapshot`）。

```
Pipeline 阶段推进
         │
         ▼
    Phase 事件（阶段边界）
    ├── phase.started → 阶段开始
    └── phase.completed → 阶段完成（含 duration_ms）
         │
         ▼
    Step 事件（执行单元）
    ├── step.started → Step 开始（含 step_type + label）
    ├── step.progress → Step 内进度（阶段特定字段）
    ├── step.completed → Step 完成（含 output 摘要）
    ├── step.failed → Step 失败
    └── step.skipped → Step 跳过（降级）
         │
         ▼
    Task 事件（任务全局）
    ├── task.created → 任务被 Worker 拾取（status: pending → running）
    ├── task.progress → 全局进度更新
    ├── task.warning → 可降级失败（不影响流程）
    ├── checkpoint.saved → 可恢复状态已保存
    ├── task.completed → 任务成功完成
    ├── task.failed → 任务致命失败
    ├── task.canceled → 任务已取消
    ├── task.paused [v2] → 任务已暂停
    └── task.resumed [v2] → 任务已恢复
```

### 9.2 每阶段 SSE 事件详情

| 阶段 | Step 事件 | Phase 边界 |
|:---|:---|:---|
| Planning | `step.started` → `step.progress` → `step.completed` | Planning 首 Step → `phase.started`；完成 → `phase.completed` |
| Search | 每个子问题 1 个 Step | 首个 Search Step → `phase.started`；末个完成 → `phase.completed` |
| Fetch | 每个 URL 1 个 Step | 同上 |
| Rerank | BM25 + LLM Rerank 合并为一个 Step | Rerank Step → `phase.started` + `phase.completed` |
| Synthesis | 1 个 Step | 同上 |
| Evidence Graph | 1 个 Step | 同上 |
| Render | 1 个 Step（内含 Section 级进度） | Render Step 完成 + `phase.completed` + `task.completed` |

> 各事件的 wire format（字段名、类型、示例值）见 [API.md §4](API.md#4-sse-事件协议)。

### 9.3 进度计算

```
全局进度 = completed_steps / total_steps
```

`total_steps` 固定为七阶段总数（`len(PHASE_ORDER)` = 7），即 Planning / Search / Fetch / Rerank / Synthesis / Evidence Graph / Render 各计 1 步。每完成一个大阶段 `completed_steps + 1`，进度从 `1/7` 单调增长到 `7/7`。

> **[Deviation]** 原始设计（`v1.0-pre`）要求 `total_steps` 在 Planning 完成后动态计算：`1 + sub_questions.length + deduped_urls.length + 4 fixed phases`。但实践发现动态分母会导致进度条回退（如 Search 创建子 step 时分母从 1 跳到 6，进度从 `1/1=100%` 跌到 `1/6≈17%`），UX 不可接受。修复后固定为 7，子 Step 不再影响全局分母。详见 `CHANGELOG.md`「进度条分母固定为七阶段」、`FRONTEND.md §4.4.2`。
>
> Phase 4 如需更细粒度的子步骤进度，可在 Phase 内部通过 `execution_pointer`（`step_index / total_steps_in_phase`）表达，不改变全局分母。

每个 Step 完成时触发 `task.progress` 事件，携带 `completed_steps / total_steps / progress`。

### 9.4 SSE 重连恢复

> SSE 重连时的 `task.status.snapshot` 数据格式与连接生命周期见 [API.md §4.2](API.md#42-sse-连接生命周期)。管道内进度状态通过 `execution_context.progress` 保存（见 [ARCHITECTURE.md §3.3](ARCHITECTURE.md#33-execution-context断点续跑的核心)）。

---

## 10. 错误传播与断点续跑

### 10.1 错误传播链

```
Step 失败
    │
    ├── Step 类别 = 可降级（Search/Fetch 单次失败）
    │       └── Step → SKIPPED
    │              └── 继续执行后续 Step
    │                     └── 全部 Step 终态后 → TaskStateResolver 评估：
    │                            ├── 满足 Evidence Threshold → PARTIALLY_COMPLETED
    │                            └── 不满足 → FAILED (E3103)
    │
    └── Step 类别 = 致命（Planning / Rerank / Synthesis / Render）
            └── Step → FAILED（含重试耗尽）
                   └── Task → FAILED
                          └── recoverable 由失败类型决定
```

#### Worker 崩溃相关错误

除阶段内 Step 失败外，以下错误在 Worker 级别产生，由基础设施层（超时监察者 / 任务调度器）检测并标记：

| 错误码 | 名称 | 触发条件 | `recoverable` | 说明 |
|:---|:---|:---|:---|:---|
| **E3112** | `CeleryWorkerLost` | Worker 崩溃/丢失，超时监察者检测到任务级锁（`rm:task_lock:{task_id}`）缺失超过阈值后标记 | `true` | Worker 进程意外终止（OOM Kill、节点宕机、Celery worker 重启等），任务级锁因未正常释放而被监察者判定为丢失。恢复路径：调度器将任务重新入队，新 Worker 通过 §10.5 崩溃恢复流程接续执行。 |
| **E3113** | `CeleryWorkerNotPickedUp` | Worker 未在时限内拾取任务，`pending` 超时后标记 | `true` | 任务已进入 `research_tasks` 表并处于 `pending` 状态，但在配置的等待窗口内无 Worker 拾取（所有 Worker 满载、队列积压、Worker 全部下线等）。恢复路径：调度器重新投递任务消息至 Celery 队列。 |

> **E3112 vs 阶段内致命错误的区别**：阶段内致命错误（E3101–E3107）由 Pipeline 逻辑检测到，意味着「该阶段的输入或执行存在不可恢复的问题」。E3112/E3113 由基础设施层检测到，意味着「执行环境本身出了问题，但任务数据完好」。因此 E3112/E3113 始终 `recoverable=true`——重新调度即可恢复，无需修复上游数据。

### 10.2 TaskStateResolver

> TaskStateResolver 在所有 Step 终态后触发，按 FATAL failure > all completed > partial with threshold 规则推导 Task 最终状态。完整评估算法与 `min_evidence` 计算见 [ARCHITECTURE.md §3.7](ARCHITECTURE.md#37-taskstateresolver)。

### 10.3 Checkpoint 策略

| 保存时机 | checkpoint 内容 | 用途 |
|:---|:---|:---|
| 每个 Phase 完成后 | `phase` + `last_completed_step_id` | Retry 时确定恢复起点 |
| 每个 Step 完成后 | 更新 `execution_context.progress` | SSE 重连时推送进度快照 |
| 每个 Fetch URL 成功后 | 记录已成功 URL | Retry 时跳过已完成 URL |
| Synthesis 完成后 | 缓存 SynthesisNotes | Retry 时跳过 LLM 综合 |

> Checkpoint 写入与 Step 状态更新在**同一数据库事务**内完成，保证原子性。Retry 发生时，Worker 读取 `execution_context`，从 `last_completed_step_id` 的下一个 Step 开始执行。

### 10.4 断点续跑流程

Pipeline 层断点续跑：读取 `execution_context` → 创建新 context（保留历史）→ 从 `last_completed_step_id` 的下一个 Step 恢复 → 复用已完成 Step 的 output → Evidence 只 INSERT 不 DELETE。

> 断点续跑的 API 请求流程（前置校验、状态检查）见 [API.md §3.2](API.md#32-执行控制)。Execution Context 的创建与恢复策略见 [ARCHITECTURE.md §3.3](ARCHITECTURE.md#33-execution-context断点续跑的核心)。

### 10.5 Worker 崩溃恢复

**问题**：Celery Worker 被 SIGKILL/OOM/断电杀死后，任务可能永久卡在 `running`（死锁）。`task_time_limit` 超时强杀同效。

**恢复依赖四层机制**：

| 层级 | 机制 | 职责 |
|:---|:---|:---|
| 传输层 | Celery `acks_late=True` | Worker 崩溃后未 ACK 任务自动重回 Redis 队列 |
| 入口层 | Pipeline 入口三元状态检查 | `pending`→正常执行 / `running`→崩溃恢复 / 终态→跳过 |
| 并发层 | 任务级租约锁 | 防止同一任务被两个 Worker 同时恢复；TTL 短、自动刷新、崩溃后快速过期 |
| 监察层 | Worker Timeout Watcher | 运行时持续扫描，主动发现并处置卡死任务 |

**关键设计决策**：

| 决策 | 值 | 理由 |
|:---|:---|:---|
| 任务级幂等锁 | **租约模式**：TTL = `CELERY_TASK_LOCK_TTL`（20s），Worker 执行期间每 `CELERY_LOCK_REFRESH_INTERVAL`（10s）刷新一次；崩溃后旧锁在 20s 内自动过期 | 相比固定长 TTL，租约模式在崩溃后快速释放锁（20s vs 900s），大幅缩短恢复窗口；正常执行期间锁持续续期，不会误过期 |
| 启动恢复阈值 | `STALE_TASK_RECOVERY_SECONDS`（60s） | 任务 `running` 超过 60s 且锁已过期即判定为过时，充分覆盖租约过期场景 |
| Step 锁遗留容忍 | TTL 600s 内恢复时当前 phase step 被跳过 | 未提交的 step output 本身已随 Worker 丢失，重新执行无副作用 |
| 启动恢复重入安全 | 多 FastAPI 实例同时检测同一过时任务 → 各自 re-queue → 任务锁保证只有一个 Worker 进入 | 无需实例间协调 |
| `task_time_limit` 不单独处理 | 超时 SIGKILL ≡ Worker 崩溃，统一覆盖 | 减少分支复杂度 |

**超时监察者（Worker Timeout Watcher）**：

FastAPI `lifespan()` 启动后台协程 `_run_worker_timeout_watcher()`，在运行时持续监控任务健康状态：

| 检查项 | 参数 | 行为 |
|:---|:---|:---|
| 任务级锁缺失 | 每 `WORKER_TIMEOUT_CHECK_INTERVAL`（5s）扫描所有 `running` 任务 | 检查任务级租约锁是否存在；锁缺失持续超过 `WORKER_TIMEOUT_SECONDS`（10s）且超过启动宽限期 `WORKER_TIMEOUT_GRACE_SECONDS`（5s）后，CAS 将任务标记为 `failed`（E3112，`recoverable=true`） |
| 长时间 `pending` 任务 | 同上扫描周期 | `started_at` 超过 `PENDING_TASK_TIMEOUT_SECONDS`（30s）仍为 `pending` 则标记 `failed`（E3113，`recoverable=true`） |
| Redis 不可用 | — | 跳过本轮判定，不误判（避免网络抖动导致误标 `failed`） |

> `recoverable=true` 表示该失败任务可在下次启动恢复时被重新投递。超时监察者实现见 `app/tasks/watcher.py`。

**`app/tasks/recovery.py` 模块**：

| 函数 | 职责 |
|:---|:---|
| `recover_stale_tasks(check_lock: bool)` | 扫描过时 `running` 任务并重新投递 |

两个入口调用 `recover_stale_tasks`：

| 入口 | `check_lock` 值 | 场景 |
|:---|:---|:---|
| FastAPI `lifespan()` 启动恢复 | `False` | 应用启动时，不检查锁（此时锁可能尚未建立），仅按 `STALE_TASK_RECOVERY_SECONDS` 判定过时 |
| Celery `worker_ready` 信号恢复 | `True` | Worker 就绪时，同时检查租约锁是否已过期，避免误回收正在执行的任务 |

以下各节描述 Pipeline 内各组件在恢复路径中的具体行为。

#### 10.5.1 `_run_pipeline()` — 入口三元检查

Celery 任务入口（`app/tasks/research_task.py`）在拾取任务后查询 task 状态，三元分支：

| 状态 | 行为 | SSE |
|:---|:---|:---|
| `pending` | 正常首次执行，调用 `orchestrator.run()` | 正常流程 |
| `running` | **崩溃恢复**：记录 warning 日志，调用 `orchestrator.run()` | 无 `task.created`（已发过） |
| 其他终态 | 跳过执行，返回 `{"status": "skipped"}` | — |

#### 10.5.2 `_start_task()` — 恢复路径

`PipelineOrchestrator._start_task()`（`app/services/pipeline_orchestrator.py`）先 `refresh(task)` 获取最新 DB 状态，再分流：

- **`status == "pending"`**（正常路径）：CAS `UPDATE research_tasks SET status='running' WHERE status='pending'`，发送 `task.created` SSE，修复 `total_steps`，获取任务锁。CAS 失败返回 `False`。
- **`status == "running"`**（恢复路径）：不执行 CAS（已 running），不发送 `task.created` SSE（已发过），修复 `total_steps`，获取任务锁。锁获取成功返回 `True`，锁已被占用返回 `False`（另一 Worker 已在恢复）。

#### 10.5.3 `_create_step()` — Step 复用

`_create_step()` 三层复用逻辑（见 `app/services/pipeline_orchestrator.py`）在崩溃恢复时表现：

| DB 中 Step 状态 | 恢复行为 | 理由 |
|:---|:---|:---|
| `completed` / `skipped` | 复用已有 Step，不重新执行 | 已完成阶段不丢失 |
| `pending` / `running` | 崩溃恢复：新建 Step 重新执行 | 旧 Step 产出已随 Worker 丢失 |
| `failed` | 新建 Step 重新执行 | 等同于 Retry 行为 |

> Step 级锁（`rm:step_lock:{step_id}`，TTL=600s）在恢复时可能仍被旧 Worker 持有。此时该 Step 被跳过——未提交的 output 已丢失，可接受。TTL 600s 内未恢复则锁自动过期。

#### 10.5.4 `run()` — 任务锁生命周期

`PipelineOrchestrator.run()` 用 `try/finally` 包裹全量 phase 循环，确保所有退出路径释放任务锁：

| 退出路径 | 锁行为 |
|:---|:---|
| `_start_task()` 返回 `False` | 无锁，不释放 |
| Phase 间取消检测命中 | `finally` 块释放 |
| 全部 Phase 完成 → `_finalize_task()` | `finally` 块释放 |
| 致命异常 → `_handle_fatal_error()` | `except` 块释放 |

> 任务锁实现见 `app/tasks/lock.py`（`acquire_task_lock_async` / `release_task_lock_async`）。启动时过时任务恢复见 `app/main.py` `lifespan()`。

#### 10.5.5 Trace Snapshot — 中间持久化

`PipelineOrchestrator.run()` 在每个 Phase 完成后、checkpoint commit 前，调用 `self._trace.snapshot()` 将当前 trace 中间快照写入 `self._task.trace`。这确保崩溃恢复时 `previous_trace` 包含崩溃前所有已完成阶段的完整数据（`total_tokens`、`total_cost_usd`、各阶段 `breakdown`）。

```
Phase N 完成
    │
    ├── self._trace.record(phase, cost_info)    # 记录本阶段 token/成本
    │
    ├── self._trace.snapshot()                   # 将当前聚合 trace 写入 task.trace
    │       └── task.trace = {
    │               "total_tokens": ...,
    │               "total_cost_usd": ...,
    │               "breakdown": { phase_1: ..., ..., phase_N: ... }
    │           }
    │
    └── checkpoint commit（phase + last_completed_step_id）
```

关键性质：

| 性质 | 说明 |
|:---|:---|
| **无副作用** | `TraceRecorder.snapshot()` 仅读取当前内部状态并写入 `task.trace`，不修改 trace 内部计数器、不推进阶段指针，可多次安全调用 |
| **幂等性** | 同一 Phase 完成后多次调用 `snapshot()`，`task.trace` 内容一致（同一阶段的 breakdown 条目不会重复） |
| **崩溃安全** | 若 Worker 在 Phase N 完成后、`snapshot()` 调用前崩溃，该阶段的 trace 数据丢失但可通过 `_build_trace_from_steps()` 重建（见 §10.5.6） |

> **为什么不等到任务完成才写入 trace？** 如果 trace 仅在 `_finalize_task()` 时一次性写入，崩溃恢复后 `task.trace` 为空——新 Worker 无法知道崩溃前各阶段消耗了多少 token 和成本。中间持久化让恢复后的 Worker 能准确延续成本追踪，避免总成本统计缺失。

#### 10.5.6 `_build_trace_from_steps()` — Trace 重建

当 `task.trace` 为空（旧任务在首个 checkpoint 前崩溃，或 §10.5.5 中 `snapshot()` 未及调用即崩溃），`_build_trace_from_steps()` 从 `research_steps` 表的已完成/跳过记录中重建 minimal trace dict。

重建逻辑：

```
SELECT phase, status, cost
FROM research_steps
WHERE task_id = ? AND status IN ('completed', 'skipped')
```

对查询结果按 Phase 分组，提取各 Phase 的：

| 字段 | 来源 | 说明 |
|:---|:---|:---|
| `duration_ms` | `step.cost.duration_ms` | 阶段执行耗时 |
| `input_tokens` | `step.cost.input_tokens` | 输入 token 数 |
| `output_tokens` | `step.cost.output_tokens` | 输出 token 数 |
| `model` | `step.cost.model` | 使用的模型名称 |
| `cost_usd` | `step.cost.estimated_cost_usd` | 估算成本（USD） |

**同一 Phase 多条记录时的去重策略**：崩溃恢复可能产生同一 Phase 的多条 `research_steps` 记录（旧 Step 状态为 `running` 未清理，新 Step 重新执行后状态为 `completed`）。此时保留 `duration_ms` 最长的一条记录——最长耗时记录最可能对应实际成功完成的执行，短耗时记录通常是崩溃中断的不完整执行。

重建产出 minimal trace dict 格式：

```python
{
    "total_tokens": <sum of input_tokens + output_tokens across phases>,
    "total_cost_usd": <sum of cost_usd across phases>,
    "breakdown": {
        "<phase_name>": {
            "tokens": <input_tokens + output_tokens>,
            "cost": <cost_usd>,
            "duration_ms": <duration_ms>,
            "model": "<model>",
        },
        ...
    }
}
```

重建的 trace 可被 `TraceRecorder._preload_previous_phases()` 使用——恢复后的 Worker 将重建的 breakdown 注入 `TraceRecorder` 内部状态，后续 Phase 的 `snapshot()` 和最终 `_finalize_task()` 在已有数据基础上继续聚合，保证 `task.trace` 的完整性和连续性。

> **重建 trace vs 完整 trace 的差异**：重建 trace 缺少 `snapshot()` 提供的实时聚合精度（如中间时间点的 `total_tokens` 快照），但各 Phase 的 token/cost 数据完整。对于崩溃恢复场景，这一精度损失可接受——恢复后新 Worker 从下一个 Phase 开始，`snapshot()` 会逐步补全聚合数据。

### 10.6 Agent Loop 执行细节

本节描述 `AgentLoop.run()` 的逐步控制流、终止条件、错误恢复策略以及 thought / tool_call 解析规则。架构层面的 Phase-Locked ReAct 定义见 [ARCHITECTURE.md §2.3.1](ARCHITECTURE.md#231-react-loop-控制流)。

**单轮循环控制流程**：

1. `AgentLoop` 检查 `AgentContext.finished` 或 `current_phase is None`，满足则退出循环。
2. 构造 LLM 消息：system prompt（含 phase 顺序、当前 phase、已完成 phase、当前阶段主工具）+ `WorkingMemory.to_messages()` + 当前 phase 用户级指令。
3. `PhaseController.get_available_tools()` 返回当前 phase 可用 Tool 列表（当前 phase tool + `finish_tool` + `memory_tool`）。
4. 调用 `chat_completion(messages, tools=tool_schemas, tool_choice="auto")`。
5. 若 LLM 返回 `reasoning_content`，发布 `agent.thought` SSE。
6. 解析 `tool_calls`；对每个 `ToolCall`：
   - 发布 `agent.action` SSE。
   - `PhaseController.is_tool_available(name)` 校验；若不可用，直接返回错误 observation。
   - `AgentRuntime._execute_tool()` 创建/复用 `ResearchStep`、调用 `Tool.execute()`、写入 Step 状态与 output、发布 `step.*` SSE。
   - 发布 `agent.observation` SSE。
   - 将 `ReActEntry` 写入 `WorkingMemory`。
   - 若当前 phase 的 primary tool 成功执行，调用 `mark_phase_done()`。
7. 本轮全部 Tool Call 处理完成后，若 `current_phase_done`，调用 `advance()` 推进到下一 phase。
8. `AgentContext.iteration_count` 自增，进入下一轮。

**终止条件**：

| 条件 | 触发位置 | 行为 |
|:---|:---|:---|
| 所有 phase 完成 | `PhaseController.advance()` 返回 False | `AgentContext.finished = True`，循环正常退出 |
| LLM 显式调用 `finish_tool` | `finish_tool.execute()` | `AgentContext.finished = True`，循环立即退出 |
| 达到最大迭代次数 | `AgentLoop.run()` 循环判断 | 抛出 `AgentLoopExhaustedError`，由 `AgentRuntime` 捕获后按证据阈值判定 Task 状态 |

**最大迭代次数**：由 `app/config.py` 的 `MAX_AGENT_ITERATIONS` 控制，默认 **30**。该上限用于防止 LLM 因 prompt 误解或 `memory_tool` 滥用而陷入无限循环；达到上限时任务通常标记为 `failed` 且 `recoverable=true`，用户可通过 Retry 继续执行。

**错误恢复策略**：

| 异常场景 | 处理方式 | 是否终止 Loop |
|:---|:---|:---|
| LLM API 调用失败 | 记录 observation "LLM 调用失败: {exc}" 到 `WorkingMemory`，继续下一轮 | 否 |
| LLM 返回 content 但未返回 tool_calls | 将 content 作为 observation 记录，继续下一轮 | 否 |
| LLM 请求了当前 phase 不可用的 Tool | 返回 observation "Tool 'x' 在当前 phase 不可用"，不创建 Step | 否 |
| Tool 参数校验失败 | `PhaseHandlerTool` 返回 `success=False` 的 `ToolResult`，`AgentRuntime` 标记 Step 失败 | 否 |
| Tool 执行抛异常 | `AgentRuntime._execute_tool()` 捕获并包装为 failed `ToolResult`，记录 Step 失败 | 否 |
| 达到 `MAX_AGENT_ITERATIONS` | `AgentLoop` 抛出 `AgentLoopExhaustedError` | 是（进入最终化） |

**Thought 解析与验证**：

- **Thought 来源**：LLM 返回的 `reasoning_content` 直接作为 thought 文本，不额外解析。
- **Tool Call 解析**：由 `app/core/llm.py` 将 LLM 原始响应解析为 `ToolCall` 列表（`id`/`name`/`arguments`）。
- **Phase 可用性校验**：`PhaseController.is_tool_available(name)` 在可用列表中查找，拒绝越权调用。
- **参数校验**：`validate_tool_params(params, schema)` 校验 JSON Schema 的 `required` 字段与 `properties` 中声明的基础类型（string/integer/number/boolean/object/array）。

---

## 11. 成本追踪与 Token 预算

### 11.1 单任务 Token 预算

> 各阶段 LLM token 限额（硬/软限制）与全任务总预算见 [ARCHITECTURE.md §5.3](ARCHITECTURE.md#53-成本控制)。本节仅描述 Pipeline 内的成本追踪数据结构。

### 11.2 成本追踪数据结构

> **[Deviation]** ResearchMind 的 trace 为**成本+计时双模型**：每 Step 级 `cost`（token 成本细分 `{input_tokens, output_tokens, estimated_cost_usd, model}`）和 Task 级 `trace`（聚合 `total_tokens`/`total_cost_usd` + 按阶段 `breakdown`）。区别于纯计时模型（仅 `duration_ms` + `span_name` + `status`、不含成本字段），ResearchMind 在计时基础上扩展了成本维度。

每 Step 完成后写入 `research_steps`：

```python
step.cost = {
    "input_tokens": 3200,
    "output_tokens": 450,
    "estimated_cost_usd": 0.012,
    "model": "deepseek-v4-pro",
}
```

任务完成后聚合到 `research_tasks.trace`：

```python
task.trace = {
    "total_tokens": 48000,
    "total_cost_usd": 0.18,
    "breakdown": {
        "planning": {"tokens": 2800, "cost": 0.01},
        "rerank": {"tokens": 4200, "cost": 0.015},
        "synthesis": {"tokens": 15000, "cost": 0.055},
        "render": {"tokens": 26000, "cost": 0.10},
    }
}
```

> 成本追踪通过 DeepSeek API 返回的 `usage` 对象自动记录，不估算、不手工计入。Search（Tavily）和 Fetch（HTTP）成本不计入 token 追踪但计入 `total_cost_usd`。

---

## 12. 相关源文件（预期）

| 文件 | 职责 |
|:---|:---|
| `app/services/research_service.py` | 研究任务创建入口 + 状态查询 |
| `app/services/pipeline_orchestrator.py` | Pipeline 编排器（阶段调度、状态转换、TaskStateResolver） |
| `app/pipeline/planner.py` | Planning 阶段：SubQuestion 拆解 + Prompt |
| `app/pipeline/searcher.py` | Search 阶段：Tavily API 调用 + 去重 |
| `app/pipeline/fetcher.py` | Fetch 阶段：HTTP 抓取 + trafilatura 提取 + 安全检查 |
| `app/pipeline/reranker.py` | Rerank 阶段：BM25 粗筛 + LLM 精排 |
| `app/pipeline/synthesizer.py` | Synthesis 阶段：LLM 跨源综合 |
| `app/pipeline/evidence_graph.py` | Evidence Graph 构建：程序化数据组装 |
| `app/pipeline/renderer.py` | Report Render：模板选择 + LLM 渲染 + 引用提取 |
| `app/pipeline/sse_bridge.py` | SSE 事件发射器（Pipeline ↔ SSE Stream 桥接） |
| `app/core/llm.py` | LLM 调用封装（流式/非流式） |
| `app/core/cost_tracker.py` | Token 统计与成本聚合 |
| `app/tasks/research_task.py` | Celery 异步任务入口 |

---

## 13. 相关文档

- [架构设计文档](ARCHITECTURE.md) — 技术选型、三层状态机、失败分类学、非功能需求
- [接口文档](API.md) — REST 端点、SSE 事件协议、请求/响应模型
- [数据库设计文档](DATABASE.md) — 表结构、Pipeline 状态字段持久化
- [产品需求文档](PRD.md) — 产品定位、task_type 定义、MVP 范围
- [开发排期](ROADMAP.md) — v1.0 / v1.5 / v2.0 Pipeline 演进路线
