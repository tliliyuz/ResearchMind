"""异常处理器测试 — 覆盖 app/core/exceptions.py 全部异常类。

对齐 TESTING_STRATEGY.md §4.2：
每个异常类覆盖 3 个维度：错误码/状态码、detail 结构化字段、HTTPException 序列化。
"""

import pytest

from app.core.exceptions import (
    AdminPermissionRequiredException,
    AppException,
    EvidenceGraphBuildFailedException,
    InsufficientEvidenceException,
    InternalServerException,
    InvalidCredentialsException,
    InvalidDepthException,
    InvalidRefreshTokenException,
    InvalidRequirementsException,
    InvalidTaskTypeException,
    InvalidTokenException,
    LLMAuthFailedException,
    LLMRateLimitException,
    LLMTimeoutException,
    LLMUnknownException,
    PasswordSameAsCurrentException,
    PermissionDeniedException,
    PlanningFailedException,
    RateLimitExceededException,
    RefreshTokenExpiredException,
    RefreshTokenRevokedException,
    RenderFailedException,
    RerankFailedException,
    SearchFailedException,
    ServiceUnavailableException,
    SynthesisFailedException,
    TaskAccessDeniedException,
    TaskCanceledException,
    TaskNotFoundException,
    TaskStatusConflictException,
    TokenExpiredException,
    TokenLeakDetectedException,
    TopicTooLongException,
    UserDisabledException,
    UsernameExistsException,
    ValidationFailedException,
)


# ═══════════════════════════════════════════════════════════════
# E1xxx — 认证与权限错误
# ═══════════════════════════════════════════════════════════════


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
        assert exc.detail["message"] == "用户名已存在"
        assert isinstance(exc.detail["detail"], dict)
        assert exc.detail["detail"]["error_type"] == "UsernameExists"


class TestInvalidCredentialsException:
    def test_错误码为E1002_HTTP状态码为401(self):
        exc = InvalidCredentialsException()
        assert exc.error_code == "E1002"
        assert exc.status_code == 401

    def test_detail结构完整(self):
        exc = InvalidCredentialsException()
        assert exc.error_detail["error_type"] == "InvalidCredentials"
        assert exc.detail["code"] == "E1002"


class TestTokenExpiredException:
    def test_错误码为E1003_HTTP状态码为401(self):
        exc = TokenExpiredException()
        assert exc.error_code == "E1003"
        assert exc.status_code == 401

    def test_error_type为TokenExpired(self):
        exc = TokenExpiredException()
        assert exc.error_detail["error_type"] == "TokenExpired"


class TestInvalidTokenException:
    def test_错误码为E1004_HTTP状态码为401(self):
        exc = InvalidTokenException()
        assert exc.error_code == "E1004"
        assert exc.status_code == 401

    def test_带detail参数时内容正确(self):
        exc = InvalidTokenException(detail="签名验证失败")
        assert exc.error_detail["error_description"] == "签名验证失败"


class TestPermissionDeniedException:
    def test_错误码为E1005_HTTP状态码为403(self):
        exc = PermissionDeniedException()
        assert exc.error_code == "E1005"
        assert exc.status_code == 403


class TestRefreshTokenExpiredException:
    def test_错误码为E1006_HTTP状态码为401(self):
        exc = RefreshTokenExpiredException()
        assert exc.error_code == "E1006"
        assert exc.status_code == 401


class TestRefreshTokenRevokedException:
    def test_错误码为E1007_HTTP状态码为401(self):
        exc = RefreshTokenRevokedException()
        assert exc.error_code == "E1007"
        assert exc.status_code == 401


class TestInvalidRefreshTokenException:
    def test_错误码为E1008_HTTP状态码为401(self):
        exc = InvalidRefreshTokenException()
        assert exc.error_code == "E1008"
        assert exc.status_code == 401

    def test_带detail参数验证(self):
        exc = InvalidRefreshTokenException(detail="refresh_token 不存在")
        assert exc.error_detail["error_description"] == "refresh_token 不存在"


class TestTokenLeakDetectedException:
    def test_错误码为E1009_HTTP状态码为401(self):
        exc = TokenLeakDetectedException()
        assert exc.error_code == "E1009"
        assert exc.status_code == 401

    def test_error_type为TokenLeakDetected(self):
        exc = TokenLeakDetectedException()
        assert exc.error_detail["error_type"] == "TokenLeakDetected"
        assert "已吊销" in exc.error_detail["error_description"]


class TestUserDisabledException:
    def test_错误码为E1010_HTTP状态码为401(self):
        exc = UserDisabledException()
        assert exc.error_code == "E1010"
        assert exc.status_code == 401


class TestPasswordSameAsCurrentException:
    def test_错误码为E1011_HTTP状态码为400(self):
        exc = PasswordSameAsCurrentException()
        assert exc.error_code == "E1011"
        assert exc.status_code == 400


# ═══════════════════════════════════════════════════════════════
# E2xxx — 研究任务错误
# ═══════════════════════════════════════════════════════════════


class TestTaskNotFoundException:
    def test_错误码为E2001_HTTP状态码为404(self):
        exc = TaskNotFoundException(task_id="abc-123")
        assert exc.error_code == "E2001"
        assert exc.status_code == 404
        assert "abc-123" in exc.error_detail["error_description"]
        assert exc.error_detail["recoverable"] is False


class TestTaskAccessDeniedException:
    def test_错误码为E2002_HTTP状态码为403(self):
        exc = TaskAccessDeniedException()
        assert exc.error_code == "E2002"
        assert exc.status_code == 403


class TestTaskStatusConflictException:
    def test_错误码为E2003_HTTP状态码为409(self):
        exc = TaskStatusConflictException()
        assert exc.error_code == "E2003"
        assert exc.status_code == 409

    def test_带detail参数(self):
        exc = TaskStatusConflictException(detail="任务已完成，无法取消")
        assert "任务已完成" in exc.error_detail["error_description"]


class TestTaskCanceledException:
    def test_错误码为E2004_HTTP状态码为400(self):
        exc = TaskCanceledException()
        assert exc.error_code == "E2004"
        assert exc.status_code == 400


class TestTopicTooLongException:
    def test_错误码为E2005_HTTP状态码为400(self):
        exc = TopicTooLongException()
        assert exc.error_code == "E2005"
        assert exc.status_code == 400


class TestInvalidTaskTypeException:
    def test_错误码为E2006_HTTP状态码为400(self):
        exc = InvalidTaskTypeException()
        assert exc.error_code == "E2006"
        assert exc.status_code == 400


class TestInvalidDepthException:
    def test_错误码为E2007_HTTP状态码为400(self):
        exc = InvalidDepthException()
        assert exc.error_code == "E2007"
        assert exc.status_code == 400


class TestInvalidRequirementsException:
    def test_错误码为E2008_HTTP状态码为400(self):
        exc = InvalidRequirementsException()
        assert exc.error_code == "E2008"
        assert exc.status_code == 400


class TestAdminPermissionRequiredException:
    def test_错误码为E2009_HTTP状态码为403(self):
        exc = AdminPermissionRequiredException()
        assert exc.error_code == "E2009"
        assert exc.status_code == 403


# ═══════════════════════════════════════════════════════════════
# E3xxx — 研究执行错误（含 recoverable / retry_after_ms）
# ═══════════════════════════════════════════════════════════════


class TestPlanningFailedException:
    def test_错误码为E3101_HTTP状态码为500(self):
        exc = PlanningFailedException()
        assert exc.error_code == "E3101"
        assert exc.status_code == 500

    def test_recoverable为False且无retry_after_ms(self):
        exc = PlanningFailedException()
        assert exc.error_detail["recoverable"] is False
        assert "retry_after_ms" not in exc.error_detail


class TestSearchFailedException:
    def test_错误码为E3102_HTTP状态码为503(self):
        exc = SearchFailedException()
        assert exc.error_code == "E3102"
        assert exc.status_code == 503

    def test_recoverable为True_retry_after_ms为10000(self):
        exc = SearchFailedException()
        assert exc.error_detail["recoverable"] is True
        assert exc.error_detail["retry_after_ms"] == 10000


class TestInsufficientEvidenceException:
    def test_错误码为E3103_HTTP状态码为500(self):
        exc = InsufficientEvidenceException()
        assert exc.error_code == "E3103"
        assert exc.status_code == 500

    def test_recoverable为False(self):
        exc = InsufficientEvidenceException()
        assert exc.error_detail["recoverable"] is False


class TestSynthesisFailedException:
    def test_错误码为E3104_HTTP状态码为500_recoverable为True(self):
        exc = SynthesisFailedException()
        assert exc.error_code == "E3104"
        assert exc.error_detail["recoverable"] is True


class TestRerankFailedException:
    def test_错误码为E3105_HTTP状态码为500(self):
        exc = RerankFailedException()
        assert exc.error_code == "E3105"
        assert exc.status_code == 500


class TestEvidenceGraphBuildFailedException:
    def test_错误码为E3106_recoverable为False(self):
        exc = EvidenceGraphBuildFailedException()
        assert exc.error_code == "E3106"
        assert exc.error_detail["recoverable"] is False


class TestRenderFailedException:
    def test_错误码为E3107_recoverable为True(self):
        exc = RenderFailedException()
        assert exc.error_code == "E3107"
        assert exc.error_detail["recoverable"] is True


class TestLLMTimeoutException:
    def test_错误码为E3108_HTTP状态码为502(self):
        exc = LLMTimeoutException()
        assert exc.error_code == "E3108"
        assert exc.status_code == 502
        assert exc.error_detail["recoverable"] is True


class TestLLMRateLimitException:
    def test_错误码为E3109_HTTP状态码为429_retry_after_ms为15000(self):
        exc = LLMRateLimitException()
        assert exc.error_code == "E3109"
        assert exc.status_code == 429
        assert exc.error_detail["retry_after_ms"] == 15000


class TestLLMAuthFailedException:
    def test_错误码为E3110_HTTP状态码为401_recoverable为False(self):
        exc = LLMAuthFailedException()
        assert exc.error_code == "E3110"
        assert exc.status_code == 401
        assert exc.error_detail["recoverable"] is False


class TestLLMUnknownException:
    def test_错误码为E3111_HTTP状态码为500(self):
        exc = LLMUnknownException()
        assert exc.error_code == "E3111"
        assert exc.status_code == 500
        assert exc.error_detail["recoverable"] is True


# ═══════════════════════════════════════════════════════════════
# E9xxx — 系统通用错误
# ═══════════════════════════════════════════════════════════════


class TestInternalServerException:
    def test_错误码为E9001_HTTP状态码为500(self):
        exc = InternalServerException()
        assert exc.error_code == "E9001"
        assert exc.status_code == 500


class TestServiceUnavailableException:
    def test_错误码为E9002_HTTP状态码为503(self):
        exc = ServiceUnavailableException()
        assert exc.error_code == "E9002"
        assert exc.status_code == 503


class TestValidationFailedException:
    def test_错误码为E9003_HTTP状态码为422(self):
        exc = ValidationFailedException()
        assert exc.error_code == "E9003"
        assert exc.status_code == 422


class TestRateLimitExceededException:
    def test_错误码为E9004_HTTP状态码为429(self):
        exc = RateLimitExceededException()
        assert exc.error_code == "E9004"
        assert exc.status_code == 429

    def test_retry_after默认60秒(self):
        exc = RateLimitExceededException()
        assert exc.error_detail["retry_after_ms"] == 60000

    def test_自定义retry_after(self):
        exc = RateLimitExceededException(retry_after=30)
        assert exc.error_detail["retry_after_ms"] == 30000


# ═══════════════════════════════════════════════════════════════
# AppException 基类
# ═══════════════════════════════════════════════════════════════


class TestAppException:
    def test_基类构造_全部字段正确(self):
        exc = AppException(
            code="E9999", message="测试异常", status_code=418,
            detail={"error_type": "TestError", "error_description": "用于测试"},
        )
        assert exc.error_code == "E9999"
        assert exc.error_message == "测试异常"
        assert exc.status_code == 418
        assert exc.error_detail["error_type"] == "TestError"

    def test_detail为str时兼容(self):
        exc = AppException(code="E9998", message="msg", detail="simple string")
        assert exc.error_detail == "simple string"

    def test_HTTPException_detail三元组序列化(self):
        exc = AppException(
            code="E9997", message="msg", status_code=400,
            detail={"error_type": "T", "error_description": "D"},
        )
        # 父类 HTTPException.detail 被设为 {"code", "message", "detail"} 三元组
        assert exc.detail["code"] == "E9997"
        assert exc.detail["message"] == "msg"
        assert exc.detail["detail"]["error_type"] == "T"
        assert exc.detail["detail"]["error_description"] == "D"
