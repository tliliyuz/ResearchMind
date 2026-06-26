"""Step 级成本计算 —— 从 LLM output 提取 token 用量并按模型单价估算美元成本。

对齐 RESEARCH_PIPELINE.md §11.2：
- Step 级 cost 字段：{input_tokens, output_tokens, estimated_cost_usd, model}
- Task 级 trace 聚合：total_tokens / total_cost_usd / breakdown[phase]

[Deviation] MVP 仅追踪 LLM token 成本；Search/Fetch 等第三方服务成本暂不计入。
[Deviation] DeepSeek 定价使用 cache miss 价格作为保守估算。
"""

from typing import Any

from decimal import ROUND_HALF_UP, Decimal

# 模型定价：每 1M token 美元（cache miss 价格，保守估算）
MODEL_PRICING_USD_PER_1M: dict[str, dict[str, float]] = {
    "deepseek-v4-pro": {"input": 0.435, "output": 0.87},
    "deepseek-v4-flash": {"input": 0.14, "output": 0.28},
}


def calculate_cost_usd(input_tokens: int, output_tokens: int, model: str) -> float:
    """按模型单价计算美元成本，保留 6 位小数。

    Args:
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        model: 模型名称（未在定价表中时成本为 0.0）

    Returns:
        估算成本（美元）
    """
    pricing = MODEL_PRICING_USD_PER_1M.get(model)
    if pricing is None:
        return 0.0

    input_cost = input_tokens * pricing["input"] / 1_000_000
    output_cost = output_tokens * pricing["output"] / 1_000_000
    total = Decimal(str(input_cost + output_cost)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    return float(total)


def _safe_int(value: Any) -> int | None:
    """安全将值转为 int；None / 非数字返回 None。"""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def extract_step_cost(output: dict, default_model: str | None = None) -> dict | None:
    """从 Step output 中提取 token 用量与成本。

    提取路径（优先级）：
    1. output["prompt_tokens"] / output["completion_tokens"]
    2. output["usage"]["prompt_tokens"] / output["usage"]["completion_tokens"]

    Args:
        output: Step output dict
        default_model: 默认模型名（output 中无 model 字段时使用）

    Returns:
        cost dict 或 None（token 字段缺失或全为 0 / 无效）
    """
    if not isinstance(output, dict):
        return None

    usage = output.get("usage") if isinstance(output.get("usage"), dict) else {}

    input_tokens = _safe_int(output.get("prompt_tokens"))
    if input_tokens is None:
        input_tokens = _safe_int(usage.get("prompt_tokens"))

    output_tokens = _safe_int(output.get("completion_tokens"))
    if output_tokens is None:
        output_tokens = _safe_int(usage.get("completion_tokens"))

    if input_tokens is None or output_tokens is None:
        return None
    if input_tokens < 0 or output_tokens < 0:
        return None
    if input_tokens == 0 and output_tokens == 0:
        return None

    model = output.get("model") or default_model or "unknown"
    cost_usd = calculate_cost_usd(input_tokens, output_tokens, model)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": cost_usd,
        "model": model,
    }
