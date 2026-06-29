"""人工评估记录处理

提供人工评估 JSON 记录的校验、加载、聚合与轮次对比。
协议定义见 tests/TESTING_STRATEGY.md §11.4。
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

logger = logging.getLogger(__name__)

from app.evaluation.constants import (
    MANUAL_DIMENSIONS,
    MAX_MANUAL_SCORE,
    MIN_MANUAL_SCORE,
)
from app.evaluation.models import (
    ManualAggregationResult,
    ManualDimensionScore,
    ManualEvaluationRecord,
)


def validate_manual_record(data: dict[str, Any]) -> ManualEvaluationRecord:
    """校验人工评估记录并转换为 ManualEvaluationRecord。

    Raises:
        ValueError: 必要字段缺失或评分超出有效范围。
    """
    required = {"round", "task_id", "topic", "task_type", "rater", "scores", "overall_score"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"人工评估记录缺少必要字段: {sorted(missing)}")

    scores_raw = data["scores"]
    if not isinstance(scores_raw, list):
        raise ValueError("scores 必须是评分列表")

    seen_dimensions = set()
    scores: list[ManualDimensionScore] = []
    for item in scores_raw:
        dimension = item.get("dimension")
        score = item.get("score")
        if dimension not in MANUAL_DIMENSIONS:
            raise ValueError(f"未知评估维度: {dimension}")
        if dimension in seen_dimensions:
            raise ValueError(f"重复评估维度: {dimension}")
        if not isinstance(score, int) or not (MIN_MANUAL_SCORE <= score <= MAX_MANUAL_SCORE):
            raise ValueError(
                f"维度 {dimension} 的评分 {score} 不在 [{MIN_MANUAL_SCORE}, {MAX_MANUAL_SCORE}] 范围内"
            )
        seen_dimensions.add(dimension)
        scores.append(
            ManualDimensionScore(
                dimension=dimension,
                score=score,
                comment=item.get("comment", ""),
            )
        )

    missing_dimensions = set(MANUAL_DIMENSIONS) - seen_dimensions
    if missing_dimensions:
        raise ValueError(f"缺少评估维度: {sorted(missing_dimensions)}")

    return ManualEvaluationRecord.from_dict(data)


def aggregate_manual_records(records: list[ManualEvaluationRecord]) -> ManualAggregationResult:
    """聚合多个人工评估记录，计算维度均值、总体均值、task_type 均值、轮次均值。"""
    if not records:
        return ManualAggregationResult(
            record_count=0,
            dimension_means={d: 0.0 for d in MANUAL_DIMENSIONS},
            overall_mean=0.0,
            task_type_means={},
            round_means={},
            min_dimension=MANUAL_DIMENSIONS[0],
            min_dimension_mean=0.0,
        )

    dimension_scores: dict[str, list[int]] = defaultdict(list)
    task_type_scores: dict[str, list[float]] = defaultdict(list)
    round_scores: dict[int, list[float]] = defaultdict(list)
    overall_scores: list[float] = []

    for record in records:
        for score_item in record.scores:
            dimension_scores[score_item.dimension].append(score_item.score)
        task_type_scores[record.task_type].append(record.overall_score)
        round_scores[record.round].append(record.overall_score)
        overall_scores.append(record.overall_score)

    dimension_means = {
        d: mean(scores) if scores else 0.0 for d, scores in dimension_scores.items()
    }
    task_type_means = {
        t: mean(scores) if scores else 0.0 for t, scores in task_type_scores.items()
    }
    round_means = {
        r: mean(scores) if scores else 0.0 for r, scores in round_scores.items()
    }

    min_dimension = min(dimension_means, key=lambda k: dimension_means[k])
    min_dimension_mean = dimension_means[min_dimension]

    return ManualAggregationResult(
        record_count=len(records),
        dimension_means=dimension_means,
        overall_mean=mean(overall_scores) if overall_scores else 0.0,
        task_type_means=task_type_means,
        round_means=dict(sorted(round_means.items())),
        min_dimension=min_dimension,
        min_dimension_mean=min_dimension_mean,
    )


def compare_rounds(
    current: ManualAggregationResult,
    baseline: ManualAggregationResult,
) -> dict[str, Any]:
    """对比两轮人工评估结果，输出改进/退步分析。"""
    dimension_deltas: dict[str, float] = {}
    for dimension in MANUAL_DIMENSIONS:
        current_mean = current.dimension_means.get(dimension, 0.0)
        baseline_mean = baseline.dimension_means.get(dimension, 0.0)
        dimension_deltas[dimension] = current_mean - baseline_mean

    return {
        "baseline_overall_mean": baseline.overall_mean,
        "current_overall_mean": current.overall_mean,
        "overall_delta": current.overall_mean - baseline.overall_mean,
        "dimension_deltas": dimension_deltas,
        "baseline_min_dimension": baseline.min_dimension,
        "current_min_dimension": current.min_dimension,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_manual_records(directory: Path | str) -> list[ManualEvaluationRecord]:
    """加载目录下的人工评估 JSON 记录。

    支持每个 `.json` 文件包含单个记录对象或记录对象数组。
    无法解析或校验失败的文件会被记录警告并跳过，不影响其他文件加载。

    Args:
        directory: 人工评估记录目录，例如 `eval/manual/round1`。

    Returns:
        校验通过的 ManualEvaluationRecord 列表，按文件名排序。

    Raises:
        ValueError: 目录不存在或不是目录。
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        raise ValueError(f"目录不存在: {dir_path}")
    if not dir_path.is_dir():
        raise ValueError(f"不是有效目录: {dir_path}")

    records: list[ManualEvaluationRecord] = []
    for file_path in sorted(dir_path.glob("*.json")):
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("跳过无效人工评估文件 %s: %s", file_path, e)
            continue

        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            logger.warning("跳过无效人工评估文件 %s: 顶层必须是对象或数组", file_path)
            continue

        for item in items:
            try:
                records.append(validate_manual_record(item))
            except ValueError as e:
                logger.warning("跳过无效记录 %s: %s", file_path, e)
                continue

    return records


def load_all_manual_rounds(base_directory: Path | str = "eval/manual") -> list[ManualEvaluationRecord]:
    """加载 base_directory 下所有 round* 子目录的人工评估记录。

    Args:
        base_directory: 人工评估根目录，例如 `eval/manual`。

    Returns:
        所有 round 子目录中校验通过的 ManualEvaluationRecord 列表。

    Raises:
        ValueError: 目录不存在或不是目录。
    """
    base_path = Path(base_directory)
    if not base_path.exists():
        raise ValueError(f"目录不存在: {base_path}")
    if not base_path.is_dir():
        raise ValueError(f"不是有效目录: {base_path}")

    records: list[ManualEvaluationRecord] = []
    for round_dir in sorted(base_path.glob("round*")):
        if round_dir.is_dir():
            records.extend(load_manual_records(round_dir))
    return records
