"""离线评估数据模型

使用 dataclass 定义指标与报告结构，所有数值在序列化时转换为原生 Python 类型。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SearchMetrics:
    """Search 阶段指标"""

    sub_question_count: int = 0
    total_results: int = 0
    avg_results_per_sub_question: float = 0.0
    coverage_rate: float = 0.0
    recall_at_k: float = 0.0
    k: int = 5

    def to_dict(self) -> dict[str, Any]:
        return {
            "sub_question_count": self.sub_question_count,
            "total_results": self.total_results,
            "avg_results_per_sub_question": self.avg_results_per_sub_question,
            "coverage_rate": self.coverage_rate,
            "recall_at_k": self.recall_at_k,
            "k": self.k,
        }


@dataclass
class FetchMetrics:
    """Fetch 阶段指标"""

    successful: int = 0
    failed: int = 0
    skipped_safety: int = 0
    success_rate: float = 0.0
    status_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "successful": self.successful,
            "failed": self.failed,
            "skipped_safety": self.skipped_safety,
            "success_rate": self.success_rate,
            "status_distribution": dict(self.status_distribution),
        }


@dataclass
class RerankMetrics:
    """Rerank 阶段指标"""

    evidence_count: int = 0
    mean_score: float = 0.0
    median_score: float = 0.0
    min_score: float = 0.0
    max_score: float = 0.0
    high_quality_ratio: float = 0.0
    score_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_count": self.evidence_count,
            "mean_score": self.mean_score,
            "median_score": self.median_score,
            "min_score": self.min_score,
            "max_score": self.max_score,
            "high_quality_ratio": self.high_quality_ratio,
            "score_distribution": dict(self.score_distribution),
        }


@dataclass
class PipelineEvaluationReport:
    """单任务离线评估报告"""

    task_id: str
    topic: str
    status: str
    task_type: str
    evaluated_at: datetime
    search: SearchMetrics | None = None
    fetch: FetchMetrics | None = None
    rerank: RerankMetrics | None = None
    targets: dict[str, float] = field(default_factory=dict)
    overall_pass: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "topic": self.topic,
            "status": self.status,
            "task_type": self.task_type,
            "evaluated_at": self.evaluated_at.isoformat(),
            "search": self.search.to_dict() if self.search else None,
            "fetch": self.fetch.to_dict() if self.fetch else None,
            "rerank": self.rerank.to_dict() if self.rerank else None,
            "targets": dict(self.targets),
            "overall_pass": self.overall_pass,
        }


@dataclass
class ManualDimensionScore:
    """单维度人工评分"""

    dimension: str
    score: int
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "score": self.score,
            "comment": self.comment,
        }


@dataclass
class ManualEvaluationRecord:
    """单条人工评估记录"""

    round: int
    task_id: str
    topic: str
    task_type: str
    rater: str
    scores: list[ManualDimensionScore]
    overall_score: float
    evaluated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round,
            "task_id": self.task_id,
            "topic": self.topic,
            "task_type": self.task_type,
            "rater": self.rater,
            "scores": [s.to_dict() for s in self.scores],
            "overall_score": self.overall_score,
            "evaluated_at": self.evaluated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ManualEvaluationRecord":
        scores = [
            ManualDimensionScore(
                dimension=s["dimension"],
                score=int(s["score"]),
                comment=s.get("comment", ""),
            )
            for s in data["scores"]
        ]
        evaluated_at_raw = data.get("evaluated_at")
        if isinstance(evaluated_at_raw, datetime):
            evaluated_at = evaluated_at_raw
        elif isinstance(evaluated_at_raw, str):
            evaluated_at = datetime.fromisoformat(evaluated_at_raw)
        else:
            evaluated_at = datetime.now(timezone.utc)
        return cls(
            round=int(data["round"]),
            task_id=str(data["task_id"]),
            topic=str(data["topic"]),
            task_type=str(data["task_type"]),
            rater=str(data["rater"]),
            scores=scores,
            overall_score=float(data["overall_score"]),
            evaluated_at=evaluated_at,
        )


@dataclass
class SystemReliabilityMetrics:
    """系统级可靠性指标

    跨任务聚合，不依赖单个任务的 Pipeline 产出。
    指标定义见 tests/TESTING_STRATEGY.md §11.3。
    """

    # Task Completion Rate
    task_completed: int = 0
    task_partially_completed: int = 0
    task_failed: int = 0
    task_canceled: int = 0
    task_completion_rate: float = 0.0

    # LLM Call Success Rate
    llm_calls_completed: int = 0
    llm_calls_failed: int = 0
    llm_call_success_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_completed": self.task_completed,
            "task_partially_completed": self.task_partially_completed,
            "task_failed": self.task_failed,
            "task_canceled": self.task_canceled,
            "task_completion_rate": self.task_completion_rate,
            "llm_calls_completed": self.llm_calls_completed,
            "llm_calls_failed": self.llm_calls_failed,
            "llm_call_success_rate": self.llm_call_success_rate,
        }


@dataclass
class ManualAggregationResult:
    """人工评估聚合结果"""

    record_count: int
    dimension_means: dict[str, float]
    overall_mean: float
    task_type_means: dict[str, float]
    round_means: dict[int, float]
    min_dimension: str
    min_dimension_mean: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_count": self.record_count,
            "dimension_means": dict(self.dimension_means),
            "overall_mean": self.overall_mean,
            "task_type_means": dict(self.task_type_means),
            "round_means": {str(k): v for k, v in self.round_means.items()},
            "min_dimension": self.min_dimension,
            "min_dimension_mean": self.min_dimension_mean,
        }


