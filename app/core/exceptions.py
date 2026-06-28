"""自定义异常 — 统一错误码体系，对齐 API.md §1.4

[Deviation] ResearchMind 的 `detail` 为结构化 JSON 对象
（`error_type` + `error_description` + 可选 `recoverable`/`retry_after_ms`），
与 docmind 基类 `AppException.detail: str`（扁平字符串）不同。
"""

from fastapi import HTTPException


class AppException(HTTPException):
    """业务异常基类，携带统一错误码。

    detail 支持 dict | str 两种形式：
    - dict：结构化错误（error_type + error_description + 可选字段）
    - str：简单错误描述（兼容旧用法）
    """

    def __init__(self, code: str, message: str, status_code: int = 400, detail: dict | str = ""):
        self.error_code = code
        self.error_message = message
        self.error_detail = detail
        super().__init__(
            status_code=status_code,
            detail={
                "code": code,
                "message": message,
                "detail": detail,
            },
        )


def extract_recoverable_from_exception(error: Exception) -> bool:
    """从异常中提取 recoverable 字段（优先读取 AppException.error_detail.recoverable）。"""
    detail = getattr(error, "error_detail", None)
    if isinstance(detail, dict):
        return bool(detail.get("recoverable", False))
    return False


# ==================== 认证与权限错误 E1xxx ====================

class UsernameExistsException(AppException):
    def __init__(self, username: str):
        super().__init__(
            "E1001", "用户名已存在", 409,
            {"error_type": "UsernameExists", "error_description": f"用户名 '{username}' 已被注册"},
        )


class InvalidCredentialsException(AppException):
    def __init__(self):
        super().__init__(
            "E1002", "用户名或密码错误", 401,
            {"error_type": "InvalidCredentials", "error_description": "用户名或密码错误"},
        )


class TokenExpiredException(AppException):
    def __init__(self):
        super().__init__(
            "E1003", "Token 已过期", 401,
            {"error_type": "TokenExpired", "error_description": "access_token 已过期，请使用 refresh_token 刷新"},
        )


class InvalidTokenException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E1004", "Token 无效或格式错误", 401,
            {"error_type": "InvalidToken", "error_description": detail or "Token 无效或格式错误"},
        )


class PermissionDeniedException(AppException):
    def __init__(self):
        super().__init__(
            "E1005", "无权限执行此操作", 403,
            {"error_type": "PermissionDenied", "error_description": "当前用户无权限执行此操作"},
        )


class RefreshTokenExpiredException(AppException):
    def __init__(self):
        super().__init__(
            "E1006", "Refresh Token 已过期", 401,
            {"error_type": "RefreshTokenExpired", "error_description": "refresh_token 已过期，请重新登录"},
        )


class RefreshTokenRevokedException(AppException):
    def __init__(self):
        super().__init__(
            "E1007", "Refresh Token 已吊销", 401,
            {"error_type": "RefreshTokenRevoked", "error_description": "refresh_token 已被吊销（可能因改密或主动登出）"},
        )


class InvalidRefreshTokenException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E1008", "Refresh Token 无效或格式错误", 401,
            {"error_type": "InvalidRefreshToken", "error_description": detail or "Refresh Token 无效或格式错误"},
        )


class TokenLeakDetectedException(AppException):
    def __init__(self):
        super().__init__(
            "E1009", "Token 疑似泄露，已吊销全部会话", 401,
            {"error_type": "TokenLeakDetected", "error_description": "检测到已吊销的旧 Token 被重用，已吊销该用户全部 Refresh Token"},
        )


class UserDisabledException(AppException):
    def __init__(self):
        super().__init__(
            "E1010", "用户已被禁用", 401,
            {"error_type": "UserDisabled", "error_description": "该用户账号已被管理员禁用，请联系管理员"},
        )


class PasswordSameAsCurrentException(AppException):
    def __init__(self):
        super().__init__(
            "E1011", "新密码不能与原密码相同", 400,
            {"error_type": "PasswordSameAsCurrent", "error_description": "请设置一个与当前密码不同的新密码"},
        )


# ==================== 研究任务错误 E2xxx ====================

class TaskNotFoundException(AppException):
    def __init__(self, task_id: str):
        super().__init__(
            "E2001", "任务不存在", 404,
            {"error_type": "TaskNotFound", "error_description": f"task_id={task_id} 不存在或已被删除", "recoverable": False},
        )


class TaskAccessDeniedException(AppException):
    def __init__(self):
        super().__init__(
            "E2002", "无权访问该任务", 403,
            {"error_type": "TaskAccessDenied", "error_description": "此任务不属于当前用户且当前用户非管理员"},
        )


class TaskStatusConflictException(AppException):
    def __init__(
        self,
        detail: str = "",
        current_status: str | None = None,
        allowed_statuses: list[str] | None = None,
    ):
        detail_dict: dict = {
            "error_type": "TaskStatusConflict",
            "error_description": detail or "当前任务状态不支持该操作",
        }
        if current_status:
            detail_dict["current_status"] = current_status
        if allowed_statuses:
            detail_dict["allowed_statuses"] = allowed_statuses
        super().__init__("E2003", "当前任务状态不支持该操作", 409, detail_dict)


class TaskCanceledException(AppException):
    def __init__(self):
        super().__init__(
            "E2004", "任务已被取消，无法继续", 400,
            {"error_type": "TaskCanceled", "error_description": "任务已被取消，无法继续执行"},
        )


class TopicTooLongException(AppException):
    def __init__(self):
        super().__init__(
            "E2005", "研究主题超过 500 字符", 400,
            {"error_type": "TopicTooLong", "error_description": "研究主题不能超过 500 字符"},
        )


class InvalidTaskTypeException(AppException):
    def __init__(self):
        super().__init__(
            "E2006", "task_type 取值非法", 400,
            {"error_type": "InvalidTaskType", "error_description": "task_type 必须为 comparison / explainer / analysis 之一"},
        )


class InvalidDepthException(AppException):
    def __init__(self):
        super().__init__(
            "E2007", "depth 取值非法", 400,
            {"error_type": "InvalidDepth", "error_description": "MVP 仅支持 depth=quick"},
        )


class InvalidRequirementsException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E2008", "requirements 字段缺失或非法", 400,
            {"error_type": "InvalidRequirements", "error_description": detail or "requirements 字段缺失或格式不正确"},
        )


class AdminPermissionRequiredException(AppException):
    def __init__(self):
        super().__init__(
            "E2009", "该操作需要管理员权限", 403,
            {"error_type": "AdminRequired", "error_description": "该操作仅限管理员执行"},
        )


# ==================== 研究执行错误 E3xxx ====================

class PlanningFailedException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E3101", "LLM 无法拆解研究主题", 500,
            {"error_type": "PlanningFailed", "error_description": detail or "Planning 阶段重试耗尽，LLM 无法拆解研究主题", "recoverable": False},
        )


class SearchFailedException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E3102", "Tavily API 完全不可用", 503,
            {"error_type": "SearchFailed", "error_description": detail or "Tavily API 重试耗尽，所有搜索请求均失败", "recoverable": True, "retry_after_ms": 10000},
        )


class InsufficientEvidenceException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E3103", "来源量不满足最小阈值", 500,
            {"error_type": "InsufficientEvidence", "error_description": detail or "收集到的来源量不满足最小阈值，无法生成可靠报告", "recoverable": False},
        )


class SynthesisFailedException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E3104", "LLM 综合失败", 500,
            {"error_type": "SynthesisFailed", "error_description": detail or "Synthesis 阶段重试耗尽，LLM 无法完成跨源综合", "recoverable": True, "retry_after_ms": 5000},
        )


class RerankFailedException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E3105", "Rerank 输入格式错误或计算失败", 500,
            {"error_type": "RerankFailed", "error_description": detail or "Rerank 阶段失败（BM25 候选为空或 LLM Rerank 重试耗尽）", "recoverable": False},
        )


class EvidenceGraphBuildFailedException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E3106", "来源图谱构建失败", 500,
            {"error_type": "EvidenceGraphFailed", "error_description": detail or "来源图谱构建失败（上游数据结构异常）", "recoverable": False},
        )


class RenderFailedException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E3107", "报告渲染失败", 500,
            {"error_type": "RenderFailed", "error_description": detail or "报告渲染阶段失败", "recoverable": True, "retry_after_ms": 5000},
        )


class LLMTimeoutException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E3108", "LLM 调用超时", 502,
            {"error_type": "LLMTimeout", "error_description": detail or "LLM API 调用超时，重试耗尽", "recoverable": True, "retry_after_ms": 5000},
        )


class LLMRateLimitException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E3109", "LLM API 限流", 429,
            {"error_type": "LLMRateLimit", "error_description": detail or "LLM API 限流，指数退避后仍失败", "recoverable": True, "retry_after_ms": 15000},
        )


class LLMAuthFailedException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E3110", "LLM 认证失败", 401,
            {"error_type": "LLMAuthFailed", "error_description": detail or "LLM API Key 无效或认证失败（重试无意义）", "recoverable": False},
        )


class LLMUnknownException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E3111", "LLM 调用返回未预期错误", 500,
            {"error_type": "LLMUnknown", "error_description": detail or "LLM 调用返回未预期错误", "recoverable": True, "retry_after_ms": 3000},
        )


class UnknownInternalException(AppException):
    """未预期的内部错误（兜底错误码，Worker 崩溃/未捕获异常时使用）。"""

    def __init__(self, detail: str = ""):
        super().__init__(
            "E3999", "未预期的内部错误", 500,
            {"error_type": "UnknownInternal", "error_description": detail or "Pipeline 执行过程中发生未预期的内部错误", "recoverable": False},
        )


# ==================== 系统通用错误 E9xxx ====================

class InternalServerException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E9001", "服务器内部错误", 500,
            {"error_type": "InternalError", "error_description": detail or "服务器内部错误，请稍后重试"},
        )


class ServiceUnavailableException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E9002", "服务暂不可用", 503,
            {"error_type": "ServiceUnavailable", "error_description": detail or "服务暂不可用，请稍后重试"},
        )


class ValidationFailedException(AppException):
    def __init__(self, detail: str = ""):
        super().__init__(
            "E9003", "请求参数校验失败", 422,
            {"error_type": "ValidationError", "error_description": detail or "请求参数校验失败，请检查输入"},
        )


class RateLimitExceededException(AppException):
    def __init__(self, detail: str = "", retry_after: int = 60):
        super().__init__(
            "E9004", "请求频率超限", 429,
            {"error_type": "RateLimitExceeded", "error_description": detail or "请求频率超限，请稍后重试", "retry_after_ms": retry_after * 1000},
        )
