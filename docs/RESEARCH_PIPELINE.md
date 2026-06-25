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
> - `app/pipeline/reranker.py`（待改造）：`BaseReranker` ABC 抽象基类 + Claude Rerank 实现。ABC 定义 `rerank(query, candidates, top_k)` 方法签名。v1.0 使用 LLM Rerank（Claude API Prompt 内打分），v1.5 可替换为专用 Rerank API 实现。来源：DocMind `backend/app/rag/reranker.py` 的 ABC 模式。

### 5.2a 数据来源

Rerank 阶段不依赖 Fetch step 的 `output` JSON 传递正文（避免单条 JSON 过大）。启动时直接从 `research_sources` 表读取：

```sql
SELECT id, url, title, domain, content
FROM research_sources
WHERE task_id = ? AND fetch_status = 'success';
```

每行映射为一个 `FetchedDoc`，其中 `id` 对应 `source_id`，用于后续 Evidence Graph 的 `[来源N]` 引用。该设计保证 Retry 时正文可复用，且断点续跑无需重新抓取。
> - `app/pipeline/fusion.py`：RRF 多路融合排序（`rrf_fusion()`），v1.5 引入 SearXNG 作为降级后端后用于 Tavily + SearXNG 双路结果融合。算法 `score = Σ 1/(60 + rank_i)`。**v1.0 代码已就位，不激活**。来源：DocMind `backend/app/rag/fusion.py`，适配 ResearchMind 自有 SearchResult/SearchOutput 类型。

### 5.3 Stage 1：BM25 粗筛

| 参数 | 值 | 说明 |
|:---|:---|:---|
| 分词器 | jieba (中文) / split (英文) | 按 `language` 选择 |
| 分段策略 | 按 `\n\n` 段落切分 | 每段 ≤ 2000 字符 |
| 每文档取 top | 3 segments | 保证每个来源至少有 1 个候选，最多 3 个 |
| 候选总数上限 | 45 | = 15 docs × 3 segments |

> **为什么 Stage 1 不用纯向量检索？** 向量检索依赖 Embedding 模型质量，且额外增加 API 调用延迟。BM25 是纯本地计算（jieba 分词 + NumPy 矩阵），对 15 篇文档的段落级评分在 50ms 内完成，零 API 成本。
>
> **v1.5 句级匹配**：`app/pipeline/sentence_matcher.py` 提供句级 BM25 定位 + 修辞角色过滤（`match_sentences()` / `filter_chunk_sentences()`），在段落内部定位最佳证据句并过滤引用性句子（示例/测试/TODO 等）。**v1.0 代码已就位，v1.5 激活**。来源：DocMind `backend/app/rag/sentence_matcher.py`，适配 ResearchMind 自有类型。

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

> **Token 预算控制**：`app/pipeline/prompt_builder.py`（待改造）提供软上限 + 相关性优先填充算法，确保每阶段传入 LLM 的内容不超过 Token 预算。System Prompt 模板需替换为本文档各节定义的 Prompt。单条 Evidence 截断至 1500 字符是 ResearchMind 自行实现的策略（DocMind 无此功能）。来源：DocMind `backend/app/rag/prompt_builder.py` 的 Token 预算算法。

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

> **引用审计**：`app/core/evidence_auditor.py` 提供程序级三层证据审计（`audit_evidence()`）：第一层引用存在性检查（正则提取 `[来源N]` 并验证是否缺失引用）；第二层来源一致性检查（引用来源是否集中在可信源）；第三层句级证据回溯（逐句验证事实性断言能否在来源中找到原文支撑）。v1.0 MVP 使用第一层；v1.5 启用全部三层。来源：DocMind `backend/app/rag/evidence_auditor.py`，适配 ResearchMind 自有 SearchResult 类型。

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
> **SSE 事件发射器**：`app/pipeline/sse_stream.py`（待改造）封装 `StreamingResponse` 传输层 + 15 种事件类型发射逻辑（v1.0）+ 2 种预留 [v2] + `seq` 序号（保证事件有序）+ 重连快照（`task.status.snapshot`）。

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

total_steps 在 Planning 完成后动态确定：
  total_steps = 1 (Planning)
              + sub_questions.length (Search)
              + deduped_urls.length (Fetch)
              + 1 (Rerank)
              + 1 (Synthesis)
              + 1 (Evidence Graph)
              + 1 (Render)

示例（5 个子问题，10 个唯一 URL）：
  total_steps = 1 + 5 + 10 + 1 + 1 + 1 + 1 = 20
```

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

---

## 11. 成本追踪与 Token 预算

### 11.1 单任务 Token 预算

> 各阶段 LLM token 限额（硬/软限制）与全任务总预算见 [ARCHITECTURE.md §5.3](ARCHITECTURE.md#53-成本控制)。本节仅描述 Pipeline 内的成本追踪数据结构。

### 11.2 成本追踪数据结构

> **[Deviation]** ResearchMind 的 trace 为**成本+计时双模型**：每 Step 级 `cost`（token 成本细分 `{input_tokens, output_tokens, estimated_cost_usd, model}`）和 Task 级 `trace`（聚合 `total_tokens`/`total_cost_usd` + 按阶段 `breakdown`）。DocMind 的 `TraceRecorder` 为纯计时模型（`duration_ms` + `span_name` + `status`），不含成本字段。ResearchMind 在 docmind 基础上扩展了成本维度。

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
| `backend/app/services/research_service.py` | 研究任务创建入口 + 状态查询 |
| `backend/app/services/pipeline_orchestrator.py` | Pipeline 编排器（阶段调度、状态转换、TaskStateResolver） |
| `backend/app/pipeline/planner.py` | Planning 阶段：SubQuestion 拆解 + Prompt |
| `backend/app/pipeline/searcher.py` | Search 阶段：Tavily API 调用 + 去重 |
| `backend/app/pipeline/fetcher.py` | Fetch 阶段：HTTP 抓取 + trafilatura 提取 + 安全检查 |
| `backend/app/pipeline/reranker.py` | Rerank 阶段：BM25 粗筛 + LLM 精排 |
| `backend/app/pipeline/synthesizer.py` | Synthesis 阶段：LLM 跨源综合 |
| `backend/app/pipeline/evidence_graph.py` | Evidence Graph 构建：程序化数据组装 |
| `backend/app/pipeline/renderer.py` | Report Render：模板选择 + LLM 渲染 + 引用提取 |
| `backend/app/pipeline/sse_bridge.py` | SSE 事件发射器（Pipeline ↔ SSE Stream 桥接） |
| `backend/app/core/llm.py` | LLM 调用封装（流式/非流式） |
| `backend/app/core/cost_tracker.py` | Token 统计与成本聚合 |
| `backend/app/tasks/research_task.py` | Celery 异步任务入口 |

---

## 13. 相关文档

- [架构设计文档](ARCHITECTURE.md) — 技术选型、三层状态机、失败分类学、非功能需求
- [接口文档](API.md) — REST 端点、SSE 事件协议、请求/响应模型
- [数据库设计文档](DATABASE.md) — 表结构、Pipeline 状态字段持久化
- [产品需求文档](PRD.md) — 产品定位、task_type 定义、MVP 范围
- [开发排期](ROADMAP.md) — v1.0 / v1.5 / v2.0 Pipeline 演进路线
