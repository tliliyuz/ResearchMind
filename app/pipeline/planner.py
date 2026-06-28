"""Planning 阶段 —— 研究主题拆解为 SubQuestion[]。

对齐 RESEARCH_PIPELINE.md §2：
- LLM 调用（deepseek-v4-pro, deep_thinking=True, temperature=0.3）
- task_type 策略段落实时注入
- 输出校验（3-5 子问题, ≤200 字符, ≥2 实体）
- 校验失败重试（最多 3 次）→ 仍失败 E3101
"""

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import PlanningFailedException
from app.core.llm import chat_completion
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.pipeline.sse_bridge import (
    SSEBridge,
    EVENT_STEP_COMPLETED,
    EVENT_STEP_PROGRESS,
)

logger = logging.getLogger(__name__)

# ── task_type 策略段落（对齐 RESEARCH_PIPELINE.md §2.4）────────

_TASK_TYPE_STRATEGIES: dict[str, str] = {
    "comparison": (
        "**对比型拆解**：首先生成对比维度列表（如性能、生态、成本、安全性），"
        "然后每个维度 × 候选对象矩阵生成检索子问题。"
        "确保每个候选对象在关键维度上都被覆盖。"
    ),
    "explainer": (
        "**解释型拆解**：先分析主题隐含的研究方向（如最新进展、不同流派、争议焦点），"
        "再将每个方向拆为独立的检索子问题。"
        "优先覆盖不同观点/流派，避免单一叙事。"
    ),
    "analysis": (
        "**影响分析型拆解**：按因果链拆解——原因 → 直接影响 → 间接影响 → 应对策略。"
        "每个子问题覆盖因果链的一个环节，确保最终报告可形成递进推理。"
    ),
}

# ── System Prompt 模板（对齐 RESEARCH_PIPELINE.md §2.3）────────

_SYSTEM_PROMPT_TEMPLATE = """你是一个专业研究规划师。你的任务是将用户的研究主题拆解为 3-5 个可独立进行网络搜索的子问题。

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
{{
  "sub_questions": [
    "子问题 1 文本",
    "子问题 2 文本"
  ],
  "rationale": "拆解逻辑简述（1-2 句）"
}}"""

_RETRY_FEEDBACK_MESSAGE = """上一次输出校验失败：{errors}

请修正后重新输出。要求：
- sub_questions 必须恰好 3-5 个
- 每个子问题不超过 200 字符
- 每个子问题至少包含 2 个有意义的实体或关键词
- 输出严格 JSON 格式，不要包含 markdown 代码块标记"""


# ── 工具函数 ──────────────────────────────────────────────────


def _extract_json_from_text(text: str) -> str:
    """从 LLM 输出中提取 JSON（处理可能的 markdown 代码块包装）。"""
    text = text.strip()

    # 尝试提取 ```json ... ``` 代码块
    code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if code_block_match:
        return code_block_match.group(1).strip()

    # 尝试提取 { ... } 最外层对象
    brace_start = text.find("{")
    if brace_start == -1:
        return text  # 返回原文，后续解析会报错

    # 从第一个 { 到最后一个 }
    brace_end = text.rfind("}")
    if brace_end == -1:
        return text

    return text[brace_start:brace_end + 1]


def _count_entities(text: str) -> int:
    """统计文本中实体/关键词数量（≥2 字符的中文词 或 ≥3 字符的英文词）。

    使用 jieba 分词，过滤标点和单字虚词。
    纯英文文本回退到空格分词。
    """
    import re as _re

    # 检测中文比例
    chinese_chars = len(_re.findall(r"[一-鿿]", text))
    total_chars = len(text.strip())
    is_chinese_dominant = chinese_chars > total_chars * 0.3 if total_chars > 0 else False

    if is_chinese_dominant:
        try:
            import jieba
            words = jieba.lcut(text)
            # 中文常见虚词/停用词（单字 + 高频虚词）
            _chinese_stopwords = {
                "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
                "一个", "这", "那", "这个", "那个", "也", "与", "及", "或", "但", "而",
                "吗", "呢", "吧", "啊", "哦", "呀", "么", "嘛", "哈",
                "什么", "怎么", "怎样", "为什么", "哪里", "哪个", "如何",
                "可以", "可能", "应该", "需要", "能够", "会", "要",
                "着", "过", "得", "地", "所", "被", "把", "让", "将", "以",
            }
            meaningful = [
                w for w in words
                if len(w) >= 2
                and w not in _chinese_stopwords
                and not w.isdigit()
                and w.strip()
            ]
            return len(meaningful)
        except ImportError:
            pass

    # 回退：英文按空格分词，过滤短词和停用词
    import string as _string
    english_stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "in", "on", "at", "to", "for", "of", "and", "or", "it", "its",
        "this", "that", "what", "how", "why", "when", "where", "who",
        "has", "have", "do", "does", "did", "will", "would", "can", "could",
    }
    words = text.split()
    punctuation = set(_string.punctuation)
    meaningful = [
        w for w in words
        if len(w) >= 3
        and w.lower() not in english_stopwords
        and not w.isdigit()
        and w.strip() not in punctuation
    ]
    return len(meaningful)


def _validate_sub_questions(sub_questions: list[str]) -> list[str]:
    """校验 sub_questions 列表，返回错误信息列表（空列表 = 通过）。

    校验规则（对齐 RESEARCH_PIPELINE.md §2.6）：
    1. 数量 3-5
    2. 每条 ≤ 200 字符
    3. 每条 ≥ 2 个实体/关键词
    """
    errors: list[str] = []

    if not isinstance(sub_questions, list):
        return ["sub_questions 不是数组"]

    n = len(sub_questions)
    if n < 3:
        errors.append(f"子问题数量 {n} < 3，需要至少 3 个")
    if n > 5:
        errors.append(f"子问题数量 {n} > 5，最多 5 个")

    for i, sq in enumerate(sub_questions):
        if not isinstance(sq, str) or not sq.strip():
            errors.append(f"子问题 {i + 1} 为空或非字符串")
            continue

        sq_clean = sq.strip()
        char_count = len(sq_clean)
        if char_count > 200:
            errors.append(f"子问题 {i + 1} 长度 {char_count} > 200 字符")

        entity_count = _count_entities(sq_clean)
        if entity_count < 2:
            errors.append(f"子问题 {i + 1} 仅含 {entity_count} 个实体/关键词，需要 ≥2")

    return errors


def _parse_planning_output(raw_text: str) -> dict:
    """解析 LLM 输出为 dict，提取 JSON 并校验顶层字段。

    Returns:
        {"sub_questions": [...], "rationale": "..."}

    Raises:
        ValueError: JSON 解析失败或顶层字段缺失
    """
    json_text = _extract_json_from_text(raw_text)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM 输出不是有效 JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("LLM 输出不是 JSON 对象")

    if "sub_questions" not in data:
        raise ValueError("缺少顶层字段 'sub_questions'")

    sub_questions = data["sub_questions"]
    if not isinstance(sub_questions, list):
        raise ValueError("'sub_questions' 不是数组")

    rationale = data.get("rationale", "")
    if not isinstance(rationale, str):
        rationale = str(rationale)

    return {
        "sub_questions": [str(sq) for sq in sub_questions],
        "rationale": rationale,
    }


# ── 主入口 ────────────────────────────────────────────────────


async def run_planning(
    task: ResearchTask,
    step: ResearchStep,
    session: AsyncSession,
    sse_bridge: SSEBridge,
) -> dict:
    """执行 Planning 阶段。

    1. 构建 System Prompt（含 task_type 策略注入）
    2. 调用 deepseek-v4-pro（deep_thinking=True, temperature=0.3, max_tokens=1000）
    3. 解析 JSON → Pydantic 式校验
    4. 校验失败 → 重新调用（最多 3 次），传递错误反馈
    5. 3 次耗尽 → raise PlanningFailedException(E3101)

    Returns:
        output dict（写入 step.output）
    """
    task_id = str(task.id)
    step_id = str(step.id)

    # 提取参数
    requirements = task.requirements or {}
    task_type = requirements.get("task_type", "explainer")
    language = requirements.get("language", "zh")

    # 获取策略段落
    strategy = _TASK_TYPE_STRATEGIES.get(
        task_type, _TASK_TYPE_STRATEGIES["explainer"]
    )

    # 构建 System Prompt
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        task_type=task_type,
        language=language,
        task_type_strategy=strategy,
    )

    logger.info(
        "Planning 开始: task_id=%s, task_type=%s, language=%s",
        task_id, task_type, language,
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"研究主题：{task.topic}"},
    ]

    total_prompt_tokens = 0
    total_completion_tokens = 0

    for attempt in range(1, settings.PIPELINE_PLANNER_MAX_RETRIES + 1):
        logger.info("Planning 第 %d/%d 次尝试: task_id=%s", attempt, settings.PIPELINE_PLANNER_MAX_RETRIES, task_id)

        # 发射进度
        await sse_bridge.publish(EVENT_STEP_PROGRESS, {
            "step_id": step_id,
            "phase": "planning",
            "attempt": attempt,
            "max_retries": settings.PIPELINE_PLANNER_MAX_RETRIES,
        })

        # 调用 LLM
        result = await chat_completion(
            messages=messages,
            model=settings.LLM_MODEL,
            deep_thinking=True,
            temperature=0.3,
            max_tokens=1000,
        )

        total_prompt_tokens += result.prompt_tokens
        total_completion_tokens += result.completion_tokens

        # 解析 JSON
        try:
            parsed = _parse_planning_output(result.content)
        except ValueError as e:
            logger.warning("Planning JSON 解析失败 (attempt %d): %s", attempt, e)
            if attempt < settings.PIPELINE_PLANNER_MAX_RETRIES:
                messages.append({"role": "assistant", "content": result.content})
                messages.append({
                    "role": "user",
                    "content": f"JSON 解析失败：{e}。请重新输出严格 JSON 格式。",
                })
                continue
            raise PlanningFailedException(
                detail=f"JSON 解析失败（{settings.PIPELINE_PLANNER_MAX_RETRIES} 次重试耗尽）: {e}"
            )

        sub_questions = parsed["sub_questions"]

        # 校验
        validation_errors = _validate_sub_questions(sub_questions)
        if not validation_errors:
            # 通过！发射 SSE 事件并返回
            await sse_bridge.publish(EVENT_STEP_PROGRESS, {
                "step_id": step_id,
                "sub_questions_generated": len(sub_questions),
                "sub_questions": sub_questions,
                "rationale": parsed["rationale"],
            })

            output = {
                "sub_questions": sub_questions,
                "rationale": parsed["rationale"],
                "model": settings.LLM_MODEL,
                "retry_count": attempt - 1,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
            }

            logger.info(
                "Planning 完成: task_id=%s, sub_questions=%d, retries=%d",
                task_id, len(sub_questions), attempt - 1,
            )
            return output

        # 校验失败
        logger.warning("Planning 校验失败 (attempt %d): %s", attempt, ", ".join(validation_errors))

        if attempt < settings.PIPELINE_PLANNER_MAX_RETRIES:
            # 追加错误反馈到消息历史
            messages.append({"role": "assistant", "content": result.content})
            messages.append({
                "role": "user",
                "content": _RETRY_FEEDBACK_MESSAGE.format(
                    errors="; ".join(validation_errors),
                ),
            })
            continue

        # 重试耗尽
        raise PlanningFailedException(
            detail=f"输出校验失败（{settings.PIPELINE_PLANNER_MAX_RETRIES} 次重试耗尽）: {'; '.join(validation_errors)}"
        )

    # 不应到达此处
    raise PlanningFailedException(detail="Planning 阶段意外退出")
