"""Planner 单元测试 — 验证 LLM 调用、JSON 解析、输出校验、重试逻辑。"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import PlanningFailedException
from app.core.llm import LLMResult
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.pipeline.planner import (
    _count_entities,
    _extract_json_from_text,
    _parse_planning_output,
    _validate_sub_questions,
    run_planning,
)


# ═══════════════════════════════════════════════════════════════
# 工具函数测试
# ═══════════════════════════════════════════════════════════════


class TestExtractJsonFromText:
    """JSON 提取：处理纯 JSON / markdown 代码块 / 混合文本。"""

    def test_纯JSON对象直接返回(self):
        text = '{"sub_questions": ["q1", "q2", "q3"], "rationale": "reason"}'
        result = _extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed["sub_questions"] == ["q1", "q2", "q3"]

    def test_markdown代码块提取(self):
        text = '```json\n{"sub_questions": ["a", "b", "c"]}\n```'
        result = _extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed["sub_questions"] == ["a", "b", "c"]

    def test_无语言标记的代码块(self):
        text = '```\n{"sub_questions": ["x", "y", "z"]}\n```'
        result = _extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed["sub_questions"] == ["x", "y", "z"]

    def test_JSON前后有说明文本(self):
        text = '这是分析结果：\n{"sub_questions": ["q1", "q2", "q3"]}\n以上是输出。'
        result = _extract_json_from_text(text)
        parsed = json.loads(result)
        assert parsed["sub_questions"] == ["q1", "q2", "q3"]


class TestCountEntities:
    """实体/关键词计数：中文 jieba 分词主路径 + 英文回退。"""

    def test_中文子问题_实体数正确(self):
        # "量子计算"=1, "后量子密码"=1, "标准"=1 → ≥3
        text = "量子计算对后量子密码标准的影响"
        count = _count_entities(text)
        assert count >= 2

    def test_英文子问题_实体数正确(self):
        text = "What is the impact of quantum computing on cryptography standards"
        count = _count_entities(text)
        assert count >= 2

    def test_虚词主导_实体不足(self):
        # 仅含虚词和单字，无有意义实体
        text = "的这个了吗呢吧"
        count = _count_entities(text)
        assert count < 2

    def test_纯标点空文本(self):
        assert _count_entities("") == 0


class TestValidateSubQuestions:
    """子问题校验：数量 3-5 / ≤200 字符 / ≥2 实体。"""

    def test_合格3个子问题_返回空列表(self):
        sqs = [
            "量子计算对密码学的具体威胁有哪些",
            "后量子密码算法的标准化进展如何",
            "NIST后量子密码竞赛的最新结果",
        ]
        errors = _validate_sub_questions(sqs)
        assert errors == []

    def test_合格5个子问题(self):
        sqs = [
            "量子计算对密码学的具体威胁有哪些",
            "后量子密码算法的标准化进展如何",
            "NIST后量子密码竞赛的最新结果",
            "量子密钥分发的商业化现状",
            "中国在量子通信领域的政策布局",
        ]
        errors = _validate_sub_questions(sqs)
        assert errors == []

    def test_数量不足3_返回错误(self):
        sqs = ["量子计算威胁"] * 2
        errors = _validate_sub_questions(sqs)
        assert len(errors) == 1
        assert "数量" in errors[0]
        assert "2" in errors[0]

    def test_数量超过5_返回错误(self):
        sqs = ["量子计算威胁"] * 6
        errors = _validate_sub_questions(sqs)
        assert len(errors) == 1
        assert "6" in errors[0]

    def test_子问题超200字符(self):
        long_sq = "这是一个超长的子问题文本" * 20  # >200 chars
        sqs = [long_sq, "正常子问题B", "正常子问题C"]
        errors = _validate_sub_questions(sqs)
        assert any("长度" in e for e in errors)

    def test_子问题实体不足2(self):
        # 仅含虚词/短疑问词，无有意义的实体
        sqs = ["这个吗", "那个呢", "是什么呀"]
        errors = _validate_sub_questions(sqs)
        # 每个都可能实体不足
        assert len(errors) >= 1

    def test_空字符串子问题(self):
        sqs = ["", "正常子问题B", "正常子问题C"]
        errors = _validate_sub_questions(sqs)
        assert any("为空" in e for e in errors)

    def test_非列表输入(self):
        errors = _validate_sub_questions("not a list")
        assert len(errors) == 1
        assert "不是数组" in errors[0]


class TestParsePlanningOutput:
    """JSON 解析：正常提取 / 缺失字段 / 无效 JSON。"""

    def test_正常解析(self):
        raw = '{"sub_questions": ["q1", "q2", "q3"], "rationale": "test"}'
        result = _parse_planning_output(raw)
        assert result["sub_questions"] == ["q1", "q2", "q3"]
        assert result["rationale"] == "test"

    def test_缺少sub_questions字段(self):
        raw = '{"rationale": "no questions"}'
        with pytest.raises(ValueError) as exc_info:
            _parse_planning_output(raw)
        assert "sub_questions" in str(exc_info.value)

    def test_无效JSON(self):
        raw = "这不是JSON"
        with pytest.raises(ValueError) as exc_info:
            _parse_planning_output(raw)
        assert "不是有效 JSON" in str(exc_info.value)

    def test_sub_questions不是数组(self):
        raw = '{"sub_questions": "not an array"}'
        with pytest.raises(ValueError) as exc_info:
            _parse_planning_output(raw)
        assert "不是数组" in str(exc_info.value)


# ═══════════════════════════════════════════════════════════════
# run_planning 集成测试（Mock LLM）
# ═══════════════════════════════════════════════════════════════


def _make_llm_result(content: str) -> LLMResult:
    """构建模拟 LLMResult。"""
    return LLMResult(
        content=content,
        reasoning_content="",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
    )


def _make_task(**overrides) -> ResearchTask:
    """构建测试用 ResearchTask。"""
    defaults = {
        "id": "task-uuid-001",
        "user_id": 1,
        "topic": "量子计算对网络安全的威胁与应对",
        "requirements": {
            "task_type": "analysis",
            "depth": "quick",
            "max_sources": 10,
            "language": "zh",
        },
        "status": "running",
        "current_phase": "planning",
        "total_steps": 1,
        "completed_steps": 0,
        "total_sources": 0,
        "total_evidence": 0,
    }
    defaults.update(overrides)
    task = ResearchTask(**defaults)
    return task


def _make_step(**overrides) -> ResearchStep:
    """构建测试用 ResearchStep。"""
    defaults = {
        "id": "step-uuid-001",
        "task_id": "task-uuid-001",
        "step_type": "planning",
        "status": "running",
        "label": "Planning：拆解研究主题",
    }
    defaults.update(overrides)
    return ResearchStep(**defaults)


def _valid_planning_json() -> str:
    """返回有效的 Planning JSON 输出。"""
    return json.dumps({
        "sub_questions": [
            "量子计算对现有加密算法的具体威胁有哪些",
            "后量子密码学标准化进展如何",
            "各国量子安全迁移策略对比分析",
        ],
        "rationale": "从威胁、应对、策略三个维度拆解",
    }, ensure_ascii=False)


class TestRunPlanningSuccess:
    """正常流程：单次 LLM 调用 + 校验通过。"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.task = _make_task()
        self.step = _make_step()
        self.sse_bridge = AsyncMock()

    @pytest.mark.asyncio
    async def test_正常_Planning_返回_sub_questions(self):
        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(_valid_planning_json())

            output = await run_planning(
                self.task, self.step, AsyncMock(), self.sse_bridge,
            )

            assert len(output["sub_questions"]) == 3
            assert output["sub_questions"][0].startswith("量子计算")
            assert output["retry_count"] == 0
            assert output["model"] is not None

    @pytest.mark.asyncio
    async def test_task_type_comparison_策略注入(self):
        self.task.requirements["task_type"] = "comparison"
        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(_valid_planning_json())
            await run_planning(self.task, self.step, AsyncMock(), self.sse_bridge)

            # 验证 prompt 包含 comparison 策略关键词
            call_args = mock_llm.call_args
            messages = call_args.kwargs["messages"]
            system_prompt = messages[0]["content"]
            assert "对比型拆解" in system_prompt

    @pytest.mark.asyncio
    async def test_task_type_explainer_策略注入(self):
        self.task.requirements["task_type"] = "explainer"
        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(_valid_planning_json())
            await run_planning(self.task, self.step, AsyncMock(), self.sse_bridge)

            messages = mock_llm.call_args.kwargs["messages"]
            system_prompt = messages[0]["content"]
            assert "解释型拆解" in system_prompt

    @pytest.mark.asyncio
    async def test_task_type_analysis_策略注入(self):
        self.task.requirements["task_type"] = "analysis"
        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(_valid_planning_json())
            await run_planning(self.task, self.step, AsyncMock(), self.sse_bridge)

            messages = mock_llm.call_args.kwargs["messages"]
            system_prompt = messages[0]["content"]
            assert "影响分析型拆解" in system_prompt

    @pytest.mark.asyncio
    async def test_LLM参数正确传递(self):
        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(_valid_planning_json())
            await run_planning(self.task, self.step, AsyncMock(), self.sse_bridge)

            call_kwargs = mock_llm.call_args.kwargs
            assert call_kwargs["deep_thinking"] is True
            assert call_kwargs["temperature"] == 0.3
            assert call_kwargs["max_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_SSE进度事件已发射(self):
        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            mock_llm.return_value = _make_llm_result(_valid_planning_json())
            await run_planning(self.task, self.step, AsyncMock(), self.sse_bridge)

            # 应发射 progress 事件（含 sub_questions_generated）
            publish_calls = [
                c for c in self.sse_bridge.publish.await_args_list
                if "step.progress" in str(c)
            ]
            assert len(publish_calls) >= 1


class TestRunPlanningRetry:
    """重试逻辑：校验失败 → 重试 → 通过 / 耗尽。"""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.task = _make_task()
        self.step = _make_step()
        self.sse_bridge = AsyncMock()

    @pytest.mark.asyncio
    async def test_首次校验失败_第二次通过(self):
        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            # 第一次返回无效 JSON
            bad_json = '{"sub_questions": ["too few"]}'  # 只有 1 个，数量不足
            mock_llm.side_effect = [
                _make_llm_result(bad_json),
                _make_llm_result(_valid_planning_json()),
            ]

            output = await run_planning(
                self.task, self.step, AsyncMock(), self.sse_bridge,
            )

            assert mock_llm.call_count == 2
            assert output["retry_count"] == 1
            assert len(output["sub_questions"]) == 3

    @pytest.mark.asyncio
    async def test_JSON解析失败_重试后通过(self):
        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            mock_llm.side_effect = [
                _make_llm_result("这不是JSON"),
                _make_llm_result(_valid_planning_json()),
            ]

            output = await run_planning(
                self.task, self.step, AsyncMock(), self.sse_bridge,
            )

            assert mock_llm.call_count == 2
            assert output["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_3次重试耗尽_抛出E3101(self):
        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            # 每次都返回无效 JSON
            mock_llm.return_value = _make_llm_result(
                '{"sub_questions": ["只有一个"]}'
            )

            with pytest.raises(PlanningFailedException) as exc_info:
                await run_planning(
                    self.task, self.step, AsyncMock(), self.sse_bridge,
                )

            assert exc_info.value.error_code == "E3101"
            assert mock_llm.call_count == 3  # PIPELINE_PLANNER_MAX_RETRIES

    @pytest.mark.asyncio
    async def test_重试时传递错误反馈到消息历史(self):
        with patch("app.pipeline.planner.chat_completion") as mock_llm:
            mock_llm.side_effect = [
                _make_llm_result('{"sub_questions": ["只有一个"]}'),
                _make_llm_result(_valid_planning_json()),
            ]

            await run_planning(
                self.task, self.step, AsyncMock(), self.sse_bridge,
            )

            # 第二次调用的 messages 应包含反馈
            second_call_messages = mock_llm.call_args_list[1].kwargs["messages"]
            # 应该有系统消息 + 用户消息 + AI消息 + 用户反馈消息
            assert len(second_call_messages) >= 4
            feedback_msg = second_call_messages[-1]["content"]
            assert "校验失败" in feedback_msg
