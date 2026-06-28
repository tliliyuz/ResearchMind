"""研究任务相关请求/响应模型 — 对齐 API.md §3

提供创建、列表、详情、删除研究任务所需的 Pydantic Schema。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.exceptions import sanitize_error_message_for_client


# ── 研究要求子模型 ──────────────────────────────────────────────

VALID_TASK_TYPES = ("comparison", "explainer", "analysis")
VALID_DEPTHS = ("quick",)


class RequirementsSchema(BaseModel):
    """研究要求配置 — 决定 Planner 策略、Rerank 维度、Report 模板。

    task_type 必填：直接决定 Planner 拆解策略 / Rerank 排序维度 / Report 模板选择。
    """

    task_type: Literal["comparison", "explainer", "analysis"] = Field(
        ..., description="研究类型：comparison / explainer / analysis"
    )
    depth: Literal["quick"] = Field(
        "quick", description="研究深度，MVP 仅支持 quick"
    )
    max_sources: int = Field(
        10, ge=1, le=50, description="信息源数量上限（1-50）"
    )
    language: str = Field(
        "zh", min_length=2, max_length=10, description="报告语言，如 zh / en"
    )


# ── 创建请求 ────────────────────────────────────────────────────


class ResearchCreateRequest(BaseModel):
    """创建研究任务请求 — 对齐 API.md §3.1 POST /api/research。"""

    topic: str = Field(
        ..., min_length=1, max_length=500, description="研究主题（≤ 500 字符）"
    )
    requirements: RequirementsSchema = Field(
        ..., description="研究要求配置（task_type / depth / max_sources / language）"
    )

    @field_validator("topic")
    @classmethod
    def validate_topic_not_blank(cls, v: str) -> str:
        """拒绝纯空白主题。"""
        if not v.strip():
            raise ValueError("研究主题不能为空")
        return v


# ── 进度子模型 ──────────────────────────────────────────────────


class ProgressSchema(BaseModel):
    """任务进度快照 — 从 execution_context.progress 提取。

    API 响应中的顶层便利字段，前端不应直接访问 execution_context。
    """

    completed_steps: int = Field(0, ge=0, description="已完成步骤数")
    total_steps: int = Field(0, ge=0, description="总步骤数")
    progress: float = Field(0.0, ge=0.0, le=1.0, description="进度比例 0.0-1.0")


# ── 详情响应 ────────────────────────────────────────────────────


class ResearchTaskResponse(BaseModel):
    """研究任务详情响应 — 对齐 API.md §3.1 GET /api/research/{task_id}。"""

    task_id: str = Field(..., description="任务 UUID")
    topic: str = Field(..., description="研究主题")
    status: str = Field(..., description="Task 状态：pending / running / completed 等")
    current_phase: str | None = Field(None, description="当前 Pipeline 阶段")
    requirements: dict = Field(..., description="研究要求配置")
    progress: ProgressSchema = Field(default_factory=ProgressSchema, description="进度快照")
    total_sources: int = Field(0, description="来源总数")
    total_evidence: int = Field(0, description="证据总数")
    error_code: str | None = Field(None, description="错误码")
    error_message: str | None = Field(None, description="错误详情")
    recoverable: bool | None = Field(None, description="是否可断点续跑")
    created_at: datetime = Field(..., description="创建时间（ISO 8601 UTC）")
    started_at: datetime | None = Field(None, description="Worker 拾取时间")
    completed_at: datetime | None = Field(None, description="完成时间")

    model_config = {"from_attributes": True}

    @field_validator("error_message", mode="before")
    @classmethod
    def _sanitize_error_message(cls, v):
        """接口层兜底清洗：防止存量脏数据（SQL/堆栈/JSON）泄露到前端。"""
        return sanitize_error_message_for_client(v)


# ── 列表项响应 ──────────────────────────────────────────────────


class ResearchTaskListItem(BaseModel):
    """研究任务列表项 — 对齐 API.md §3.1 GET /api/research。"""

    task_id: str = Field(..., description="任务 UUID")
    topic: str = Field(..., description="研究主题")
    status: str = Field(..., description="Task 状态")
    task_type: str = Field(..., description="研究类型")
    total_sources: int = Field(0, description="来源总数")
    total_evidence: int = Field(0, description="证据总数")
    created_at: datetime = Field(..., description="创建时间")
    completed_at: datetime | None = Field(None, description="完成时间")

    model_config = {"from_attributes": True}


class ResearchTaskListResponse(BaseModel):
    """研究任务分页列表响应。"""

    total: int = Field(..., ge=0, description="总记录数")
    page: int = Field(..., ge=1, description="当前页码")
    page_size: int = Field(..., ge=1, description="每页条数")
    items: list[ResearchTaskListItem] = Field(default_factory=list, description="任务列表")


# ── 创建响应 ────────────────────────────────────────────────────


class ResearchCreateResponse(BaseModel):
    """创建研究任务响应 — 对齐 API.md §3.1 POST /api/research。"""

    task_id: str = Field(..., description="任务 UUID")
    status: str = Field(..., description="初始状态，固定为 pending")
    created_at: datetime = Field(..., description="创建时间（ISO 8601 UTC）")


class ResearchCancelResponse(BaseModel):
    """取消研究任务响应 — 对齐 API.md §3.2 POST /api/research/{task_id}/cancel。"""

    task_id: str = Field(..., description="任务 UUID")
    status: str = Field(..., description="取消后的状态，固定为 canceled")


# ── Retry 相关 Schema（对齐 API.md §3.2）─────────────────────────


class ResumeFromSchema(BaseModel):
    """断点续跑恢复信息 — 从 execution_context 提取。"""

    phase: str | None = Field(None, description="恢复的 Pipeline 阶段（如 fetching）")
    last_completed_step_id: str | None = Field(None, description="最后完成的 Step UUID")
    next_step_type: str | None = Field(None, description="下一个待执行的 step_type（如 rerank）")


class ResearchRetryResponse(BaseModel):
    """POST /api/research/{task_id}/retry 响应 — 对齐 API.md §3.2。"""

    task_id: str = Field(..., description="任务 UUID")
    status: str = Field(..., description="断点续跑启动后的状态")
    resume_from: ResumeFromSchema = Field(default_factory=ResumeFromSchema, description="恢复信息")


# ── 报告相关 Schema（对齐 API.md §3.3）───────────────────────────


class ReportSourceSchema(BaseModel):
    """报告引用来源 — 来自 research_sources。"""

    id: int = Field(..., description="来源 ID")
    url: str = Field(..., description="来源 URL")
    title: str = Field(..., description="来源标题")
    domain: str = Field(..., description="来源域名")


class ReportSectionSourceSchema(BaseModel):
    """章节引用的证据来源映射。"""

    id: int = Field(..., description="research_sources.id")
    evidence_index: int = Field(..., description="Evidence Graph 中的 0-based index")


class ReportSectionSchema(BaseModel):
    """报告章节。"""

    heading: str = Field(..., description="章节标题")
    content: str = Field(..., description="Markdown 正文")
    sources: list[ReportSectionSourceSchema] = Field(
        default_factory=list, description="本章引用的证据来源列表"
    )


class ReportSchema(BaseModel):
    """完整研究报告。"""

    title: str = Field(..., description="报告标题，即研究主题")
    generated_at: datetime = Field(..., description="报告生成时间（ISO 8601 UTC）")
    sections: list[ReportSectionSchema] = Field(..., description="章节列表")
    sources: list[ReportSourceSchema] = Field(..., description="报告涉及来源列表")


class ResearchReportResponse(BaseModel):
    """GET /api/research/{task_id}/report 响应 — 对齐 API.md §3.3。"""

    task_id: str = Field(..., description="任务 UUID")
    status: str = Field(..., description="任务状态")
    report: ReportSchema = Field(..., description="结构化报告")
    evidence_graph: dict = Field(..., description="Evidence Graph 数据")
    trace: dict | None = Field(None, description="Pipeline Trace 数据")
