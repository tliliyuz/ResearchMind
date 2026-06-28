"""研究任务 Pydantic Schema 单元测试 — 覆盖所有请求/响应模型的字段校验。

对齐 TESTING_STRATEGY.md：
- 每个字段的边界值独立用例
- 成功 + 失败成对验证
- 错误消息精确断言
"""

import pytest
from pydantic import ValidationError

from app.schemas.research import (
    ResearchCreateRequest,
    RequirementsSchema,
    ResearchTaskResponse,
    ResearchTaskListItem,
    ResearchTaskListResponse,
    ResearchCreateResponse,
    ProgressSchema,
)


# ═══════════════════════════════════════════════════════════════
# RequirementsSchema
# ═══════════════════════════════════════════════════════════════


class TestRequirementsSchema:
    """研究要求子模型校验"""

    def test_合法_完整字段(self):
        req = RequirementsSchema(
            task_type="analysis",
            depth="quick",
            max_sources=10,
            language="zh",
        )
        assert req.task_type == "analysis"
        assert req.depth == "quick"
        assert req.max_sources == 10
        assert req.language == "zh"

    def test_depth使用默认值_quick(self):
        req = RequirementsSchema(task_type="comparison")
        assert req.depth == "quick"

    def test_max_sources使用默认值_10(self):
        req = RequirementsSchema(task_type="explainer")
        assert req.max_sources == 10

    def test_language使用默认值_zh(self):
        req = RequirementsSchema(task_type="analysis")
        assert req.language == "zh"

    def test_task_type非法_抛出ValidationError(self):
        with pytest.raises(ValidationError) as exc_info:
            RequirementsSchema(task_type="invalid_type")  # type: ignore[arg-type]
        assert "task_type" in str(exc_info.value)

    def test_max_sources小于1_抛出ValidationError(self):
        with pytest.raises(ValidationError) as exc_info:
            RequirementsSchema(task_type="analysis", max_sources=0)
        assert "max_sources" in str(exc_info.value)

    def test_max_sources大于50_抛出ValidationError(self):
        with pytest.raises(ValidationError) as exc_info:
            RequirementsSchema(task_type="analysis", max_sources=51)
        assert "max_sources" in str(exc_info.value)

    def test_三种task_type全部合法(self):
        for tt in ("comparison", "explainer", "analysis"):
            req = RequirementsSchema(task_type=tt)  # type: ignore[arg-type]
            assert req.task_type == tt


# ═══════════════════════════════════════════════════════════════
# ResearchCreateRequest
# ═══════════════════════════════════════════════════════════════


class TestResearchCreateRequest:
    """创建研究任务请求校验"""

    def test_合法_完整请求(self):
        req = ResearchCreateRequest(
            topic="量子计算对密码学的影响",
            requirements={
                "task_type": "analysis",
                "depth": "quick",
                "max_sources": 10,
                "language": "zh",
            },
        )
        assert req.topic == "量子计算对密码学的影响"
        assert req.requirements.task_type == "analysis"

    def test_topic为空字符串_抛出ValidationError(self):
        with pytest.raises(ValidationError):
            ResearchCreateRequest(
                topic="",
                requirements={"task_type": "analysis"},
            )

    def test_topic为纯空格_抛出ValidationError(self):
        with pytest.raises(ValidationError):
            ResearchCreateRequest(
                topic="   ",
                requirements={"task_type": "analysis"},
            )

    def test_topic恰好500字符_合法(self):
        topic = "研" * 500
        req = ResearchCreateRequest(
            topic=topic,
            requirements={"task_type": "explainer"},
        )
        assert len(req.topic) == 500

    def test_topic超过500字符_抛出ValidationError(self):
        topic = "研" * 501
        with pytest.raises(ValidationError) as exc_info:
            ResearchCreateRequest(
                topic=topic,
                requirements={"task_type": "explainer"},
            )
        assert "topic" in str(exc_info.value)

    def test_requirements缺失_抛出ValidationError(self):
        with pytest.raises(ValidationError):
            ResearchCreateRequest(topic="test")  # type: ignore[call-arg]

    def test_requirements缺少task_type_抛出ValidationError(self):
        with pytest.raises(ValidationError):
            ResearchCreateRequest(
                topic="test",
                requirements={"depth": "quick"},  # type: ignore[typeddict-item]
            )


# ═══════════════════════════════════════════════════════════════
# ProgressSchema
# ═══════════════════════════════════════════════════════════════


class TestProgressSchema:
    """进度快照 Schema"""

    def test_合法进度(self):
        p = ProgressSchema(completed_steps=7, total_steps=12, progress=0.58)
        assert p.completed_steps == 7
        assert p.total_steps == 12
        assert p.progress == 0.58

    def test_默认值全部为0(self):
        p = ProgressSchema()
        assert p.completed_steps == 0
        assert p.total_steps == 0
        assert p.progress == 0.0

    def test_progress不能为负数(self):
        with pytest.raises(ValidationError):
            ProgressSchema(progress=-0.1)

    def test_progress不能超过1(self):
        with pytest.raises(ValidationError):
            ProgressSchema(progress=1.1)


# ═══════════════════════════════════════════════════════════════
# ResearchCreateResponse
# ═══════════════════════════════════════════════════════════════


class TestResearchCreateResponse:
    """创建响应 Schema"""

    def test_合法响应(self):
        from datetime import datetime, timezone
        resp = ResearchCreateResponse(
            task_id="550e8400-e29b-41d4-a716-446655440000",
            status="pending",
            created_at=datetime.now(timezone.utc),
        )
        assert resp.task_id == "550e8400-e29b-41d4-a716-446655440000"
        assert resp.status == "pending"


# ═══════════════════════════════════════════════════════════════
# ResearchTaskListItem
# ═══════════════════════════════════════════════════════════════


class TestResearchTaskListItem:
    """列表项 Schema"""

    def test_合法列表项(self):
        from datetime import datetime, timezone
        item = ResearchTaskListItem(
            task_id="uuid-1",
            topic="研究主题",
            status="completed",
            task_type="analysis",
            total_sources=10,
            total_evidence=18,
            created_at=datetime.now(timezone.utc),
        )
        assert item.task_id == "uuid-1"
        assert item.status == "completed"
        assert item.task_type == "analysis"


# ═══════════════════════════════════════════════════════════════
# ResearchTaskListResponse
# ═══════════════════════════════════════════════════════════════


class TestResearchTaskListResponse:
    """分页列表响应 Schema"""

    def test_空列表(self):
        resp = ResearchTaskListResponse(total=0, page=1, page_size=20, items=[])
        assert resp.total == 0
        assert len(resp.items) == 0

    def test_含数据列表(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        item = ResearchTaskListItem(
            task_id="uuid-1",
            topic="研究主题",
            status="pending",
            task_type="comparison",
            created_at=now,
        )
        resp = ResearchTaskListResponse(total=1, page=1, page_size=20, items=[item])
        assert resp.total == 1
        assert resp.page == 1
        assert resp.page_size == 20
        assert len(resp.items) == 1
        assert resp.items[0].task_id == "uuid-1"


# ═══════════════════════════════════════════════════════════════
# ResearchTaskResponse
# ═══════════════════════════════════════════════════════════════


class TestResearchTaskResponse:
    """任务详情响应 Schema"""

    def test_完整详情响应(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        resp = ResearchTaskResponse(
            task_id="uuid-1",
            topic="研究主题",
            status="running",
            current_phase="searching",
            requirements={"task_type": "analysis", "depth": "quick"},
            progress=ProgressSchema(completed_steps=3, total_steps=10, progress=0.3),
            total_sources=5,
            total_evidence=0,
            created_at=now,
        )
        assert resp.task_id == "uuid-1"
        assert resp.status == "running"
        assert resp.current_phase == "searching"
        assert resp.progress.completed_steps == 3
        assert resp.progress.progress == 0.3

    def test_失败任务含错误信息(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        resp = ResearchTaskResponse(
            task_id="uuid-1",
            topic="失败的研究",
            status="failed",
            requirements={"task_type": "analysis"},
            created_at=now,
            error_code="E3101",
            error_message="LLM 无法拆解研究主题",
            recoverable=False,
        )
        assert resp.status == "failed"
        assert resp.error_code == "E3101"
        assert resp.recoverable is False

    def test_错误消息含SQL时被清洗(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        resp = ResearchTaskResponse(
            task_id="uuid-1",
            topic="失败的研究",
            status="failed",
            requirements={"task_type": "analysis"},
            created_at=now,
            error_code="E3999",
            error_message="Celery Worker 未捕获异常: [SQL: INSERT INTO research_sources ...]",
            recoverable=False,
        )
        assert resp.error_message == "未预期的内部错误，请稍后重试"
        assert "SQL" not in resp.error_message

    def test_错误消息为JSON时提取友好message(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        raw = '{"code": "E3110", "message": "LLM 认证失败"}'
        resp = ResearchTaskResponse(
            task_id="uuid-1",
            topic="失败的研究",
            status="failed",
            requirements={"task_type": "analysis"},
            created_at=now,
            error_code="E3110",
            error_message=raw,
            recoverable=False,
        )
        assert resp.error_message == "LLM 认证失败"
