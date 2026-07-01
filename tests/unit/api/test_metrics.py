"""/metrics 端点接口测试 — 验证 Prometheus 抓取端点可公开访问。"""

import pytest

from app.metrics import emit_task_status_transition


class TestMetricsEndpoint:
    """GET /metrics"""

    async def test_未携带JWT可访问(self, async_client):
        response = await async_client.get("/metrics")
        assert response.status_code == 200

    async def test_返回ContentType正确(self, async_client):
        response = await async_client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert "version=0.0.4" in response.headers["content-type"]

    async def test_响应体包含核心指标名称(self, async_client):
        # 预先触发一次埋点，确保指标非空
        emit_task_status_transition("pending")

        response = await async_client.get("/metrics")
        assert response.status_code == 200
        body = response.text

        assert "researchmind_task_status_total" in body
        assert "researchmind_phase_duration_seconds" in body
        assert "researchmind_llm_tokens_total" in body
        assert "researchmind_celery_workers_active" in body
