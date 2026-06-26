"""成本追踪核心模块测试 —— calculate_cost_usd / extract_step_cost。

对齐 RESEARCH_PIPELINE.md §11.2 的 Step 级成本结构：
{input_tokens, output_tokens, estimated_cost_usd, model}
"""

import pytest

from app.core.cost_tracker import calculate_cost_usd, extract_step_cost


class TestCalculateCostUsd:
    """按模型单价计算美元成本。"""

    def test_已知模型_deepseek_v4_pro(self):
        """deepseek-v4-pro：input 0.435 / 1M，output 0.87 / 1M。"""
        cost = calculate_cost_usd(1_000_000, 1_000_000, "deepseek-v4-pro")
        assert cost == 1.305

    def test_已知模型_deepseek_v4_flash(self):
        """deepseek-v4-flash：input 0.14 / 1M，output 0.28 / 1M。"""
        cost = calculate_cost_usd(1_000_000, 500_000, "deepseek-v4-flash")
        assert cost == 0.28

    def test_小token数保留6位小数(self):
        cost = calculate_cost_usd(3200, 450, "deepseek-v4-pro")
        # 3200 * 0.435 / 1e6 + 450 * 0.87 / 1e6 = 0.001392 + 0.0003915 = 0.0017835
        assert cost == 0.001784

    def test_未知模型返回0(self):
        cost = calculate_cost_usd(1000, 500, "unknown-model")
        assert cost == 0.0


class TestExtractStepCost:
    """从 Step output 中提取成本信息。"""

    def test_顶层token字段(self):
        output = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "model": "deepseek-v4-pro",
            "sub_questions": ["q1", "q2"],
        }
        cost = extract_step_cost(output)
        assert cost == {
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost_usd": calculate_cost_usd(100, 50, "deepseek-v4-pro"),
            "model": "deepseek-v4-pro",
        }

    def test_usage备选路径(self):
        output = {
            "usage": {"prompt_tokens": 200, "completion_tokens": 100},
            "model": "deepseek-v4-flash",
        }
        cost = extract_step_cost(output)
        assert cost == {
            "input_tokens": 200,
            "output_tokens": 100,
            "estimated_cost_usd": calculate_cost_usd(200, 100, "deepseek-v4-flash"),
            "model": "deepseek-v4-flash",
        }

    def test_顶层字段优先于usage(self):
        output = {
            "prompt_tokens": 300,
            "completion_tokens": 150,
            "usage": {"prompt_tokens": 999, "completion_tokens": 999},
            "model": "deepseek-v4-pro",
        }
        cost = extract_step_cost(output)
        assert cost["input_tokens"] == 300
        assert cost["output_tokens"] == 150

    def test_缺失token字段返回None(self):
        assert extract_step_cost({"model": "deepseek-v4-pro"}) is None
        assert extract_step_cost({"prompt_tokens": 100}) is None
        assert extract_step_cost({"completion_tokens": 100}) is None

    def test_token全0返回None(self):
        assert extract_step_cost({"prompt_tokens": 0, "completion_tokens": 0}) is None

    def test_无model字段使用default_model(self):
        output = {"prompt_tokens": 1000, "completion_tokens": 200}
        cost = extract_step_cost(output, default_model="deepseek-v4-pro")
        assert cost["model"] == "deepseek-v4-pro"

    def test_无model且无default返回unknown(self):
        output = {"prompt_tokens": 1000, "completion_tokens": 200}
        cost = extract_step_cost(output)
        assert cost["model"] == "unknown"
        assert cost["estimated_cost_usd"] == 0.0

    def test_无效token值返回None(self):
        assert extract_step_cost({"prompt_tokens": -1, "completion_tokens": 10}) is None
        assert extract_step_cost({"prompt_tokens": "abc", "completion_tokens": 10}) is None
        assert extract_step_cost({"prompt_tokens": None, "completion_tokens": 10}) is None
