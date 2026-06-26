"""研究任务 API 接口测试 — 覆盖 POST / GET / DELETE / REPORT 端点。

对齐 API.md §3.1 / §3.3：
- POST /api/research — 创建（201）+ 错误码（E2005-E2008）
- GET /api/research — 列表（分页+状态筛选）
- GET /api/research/{task_id} — 详情（E2001/E2002）
- DELETE /api/research/{task_id} — 删除（级联验证）
- GET /api/research/{task_id}/report — 报告获取（E2001/E2002/E2003）
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.evidence_item import EvidenceItem
from app.models.report_section import ReportSection
from app.models.research_source import ResearchSource
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.models.section_evidence import SectionEvidence
from app.models.user import User


# ═══════════════════════════════════════════════════════════════
# Fixtures — 预置用户（满足 FK 约束）
# ═══════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
async def seed_test_users(db_session: AsyncSession):
    """预置测试用户：user_id=1 (testuser), user_id=2 (admin), user_id=999 (other)。

    满足 research_tasks 的 FK 约束。
    """
    users = [
        User(id=1, username="testuser", password_hash=hash_password("pass"), role="user", status="active"),
        User(id=2, username="admin", password_hash=hash_password("pass"), role="admin", status="active"),
        User(id=999, username="other", password_hash=hash_password("pass"), role="user", status="active"),
    ]
    for u in users:
        existing = await db_session.get(User, u.id)
        if existing is None:
            db_session.add(u)
    await db_session.flush()


# ═══════════════════════════════════════════════════════════════
# POST /api/research — 创建研究任务
# ═══════════════════════════════════════════════════════════════


class TestCreateResearchAPI:
    """POST /api/research"""

    async def test_正常创建_返回201含task_id(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.post(
            "/api/research",
            json={
                "topic": "量子计算对密码学的影响",
                "requirements": {
                    "task_type": "analysis",
                    "depth": "quick",
                    "max_sources": 10,
                    "language": "zh",
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["code"] == "0"
        assert data["message"] == "研究任务已创建"
        assert "task_id" in data["data"]
        assert data["data"]["status"] == "pending"
        assert len(data["data"]["task_id"]) == 36  # UUID

    async def test_创建后task可查询(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.post(
            "/api/research",
            json={
                "topic": "可查询测试",
                "requirements": {"task_type": "comparison"},
            },
            headers=auth_headers,
        )
        task_id = response.json()["data"]["task_id"]

        # 通过 GET 验证
        detail = await async_client.get(f"/api/research/{task_id}", headers=auth_headers)
        assert detail.status_code == 200
        assert detail.json()["data"]["topic"] == "可查询测试"

    async def test_topic为空_返回422(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.post(
            "/api/research",
            json={
                "topic": "",
                "requirements": {"task_type": "analysis"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_topic超过500字符_返回422(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.post(
            "/api/research",
            json={
                "topic": "研" * 501,
                "requirements": {"task_type": "analysis"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_缺少requirements_返回422(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.post(
            "/api/research",
            json={"topic": "没有requirements"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_task_type非法_返回422(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.post(
            "/api/research",
            json={
                "topic": "测试",
                "requirements": {"task_type": "invalid_type"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_未登录_返回401(self, async_client: AsyncClient):
        response = await async_client.post(
            "/api/research",
            json={
                "topic": "未登录测试",
                "requirements": {"task_type": "analysis"},
            },
        )
        assert response.status_code == 401

    async def test_三种task_type全部可创建(self, async_client: AsyncClient, auth_headers: dict):
        for tt in ("comparison", "explainer", "analysis"):
            response = await async_client.post(
                "/api/research",
                json={
                    "topic": f"{tt}类型测试",
                    "requirements": {"task_type": tt, "max_sources": 15},
                },
                headers=auth_headers,
            )
            assert response.status_code == 201
            assert response.json()["data"]["status"] == "pending"


# ═══════════════════════════════════════════════════════════════
# GET /api/research — 任务列表
# ═══════════════════════════════════════════════════════════════


class TestListResearchAPI:
    """GET /api/research"""

    async def test_空列表_返回total为0(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.get("/api/research", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "0"
        assert data["data"]["total"] == 0
        assert data["data"]["items"] == []

    async def test_有任务时_返回列表(self, async_client: AsyncClient, auth_headers: dict):
        # 先创建两条任务
        for topic in ["任务A", "任务B"]:
            await async_client.post(
                "/api/research",
                json={"topic": topic, "requirements": {"task_type": "analysis"}},
                headers=auth_headers,
            )

        response = await async_client.get("/api/research", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] == 2
        assert len(data["items"]) == 2

    async def test_支持status筛选(self, async_client: AsyncClient, auth_headers: dict):
        await async_client.post(
            "/api/research",
            json={"topic": "pending任务", "requirements": {"task_type": "comparison"}},
            headers=auth_headers,
        )

        response = await async_client.get(
            "/api/research", params={"status": "pending"}, headers=auth_headers
        )
        assert response.status_code == 200
        items = response.json()["data"]["items"]
        assert all(item["status"] == "pending" for item in items)

    async def test_支持分页参数(self, async_client: AsyncClient, auth_headers: dict):
        for i in range(5):
            await async_client.post(
                "/api/research",
                json={"topic": f"任务{i}", "requirements": {"task_type": "explainer"}},
                headers=auth_headers,
            )

        response = await async_client.get(
            "/api/research", params={"page": 1, "page_size": 2}, headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert len(data["items"]) == 2

    async def test_列表按创建时间降序(self, async_client: AsyncClient, auth_headers: dict):
        await async_client.post(
            "/api/research",
            json={"topic": "第一个", "requirements": {"task_type": "analysis"}},
            headers=auth_headers,
        )
        await async_client.post(
            "/api/research",
            json={"topic": "第二个", "requirements": {"task_type": "analysis"}},
            headers=auth_headers,
        )

        response = await async_client.get("/api/research", headers=auth_headers)
        items = response.json()["data"]["items"]
        assert items[0]["topic"] == "第二个"  # 最新的在前
        assert items[1]["topic"] == "第一个"

    async def test_不同用户任务隔离(self, async_client: AsyncClient, auth_headers: dict):
        await async_client.post(
            "/api/research",
            json={"topic": "我的任务", "requirements": {"task_type": "analysis"}},
            headers=auth_headers,
        )

        # 当前用户只能看到自己的任务
        response = await async_client.get("/api/research", headers=auth_headers)
        assert response.json()["data"]["total"] == 1


# ═══════════════════════════════════════════════════════════════
# GET /api/research/{task_id} — 任务详情
# ═══════════════════════════════════════════════════════════════


class TestGetResearchDetailAPI:
    """GET /api/research/{task_id}"""

    async def test_正常获取详情(self, async_client: AsyncClient, auth_headers: dict):
        create_resp = await async_client.post(
            "/api/research",
            json={"topic": "详情测试", "requirements": {"task_type": "analysis"}},
            headers=auth_headers,
        )
        task_id = create_resp.json()["data"]["task_id"]

        response = await async_client.get(f"/api/research/{task_id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["task_id"] == task_id
        assert data["topic"] == "详情测试"
        assert data["status"] == "pending"
        assert data["requirements"]["task_type"] == "analysis"
        assert "progress" in data

    async def test_任务不存在_返回404_E2001(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.get(
            "/api/research/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404
        assert response.json()["code"] == "E2001"

    async def test_无权访问他人任务_返回403_E2002(
        self, async_client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        """创建者 user_id=1（auth_headers），但任务属于 user_id=999"""
        task = ResearchTask(
            id="550e8400-e29b-41d4-a716-446655440000",
            user_id=999,
            topic="别人的任务",
            requirements={"task_type": "analysis"},
            status="pending",
        )
        db_session.add(task)
        await db_session.flush()

        response = await async_client.get(
            "/api/research/550e8400-e29b-41d4-a716-446655440000",
            headers=auth_headers,
        )
        assert response.status_code == 403
        assert response.json()["code"] == "E2002"

    async def test_admin可访问他人任务(
        self, async_client: AsyncClient, admin_headers: dict, db_session: AsyncSession
    ):
        """admin 可以审计查看任意用户的任务。"""
        task = ResearchTask(
            id="550e8400-e29b-41d4-a716-446655440001",
            user_id=999,
            topic="审计目标",
            requirements={"task_type": "analysis"},
            status="pending",
        )
        db_session.add(task)
        await db_session.flush()

        response = await async_client.get(
            "/api/research/550e8400-e29b-41d4-a716-446655440001",
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["data"]["topic"] == "审计目标"


# ═══════════════════════════════════════════════════════════════
# DELETE /api/research/{task_id} — 删除研究任务
# ═══════════════════════════════════════════════════════════════


class TestDeleteResearchAPI:
    """DELETE /api/research/{task_id}"""

    async def test_正常删除_返回200(self, async_client: AsyncClient, auth_headers: dict):
        create_resp = await async_client.post(
            "/api/research",
            json={"topic": "待删除", "requirements": {"task_type": "analysis"}},
            headers=auth_headers,
        )
        task_id = create_resp.json()["data"]["task_id"]

        response = await async_client.delete(f"/api/research/{task_id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["code"] == "0"
        assert response.json()["message"] == "研究任务已删除"

    async def test_删除后查询返回404(self, async_client: AsyncClient, auth_headers: dict):
        create_resp = await async_client.post(
            "/api/research",
            json={"topic": "删后查", "requirements": {"task_type": "analysis"}},
            headers=auth_headers,
        )
        task_id = create_resp.json()["data"]["task_id"]

        await async_client.delete(f"/api/research/{task_id}", headers=auth_headers)

        # 验证已删除
        response = await async_client.get(f"/api/research/{task_id}", headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["code"] == "E2001"

    async def test_级联删除关联步骤(self, async_client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
        create_resp = await async_client.post(
            "/api/research",
            json={"topic": "级联删除测试", "requirements": {"task_type": "analysis"}},
            headers=auth_headers,
        )
        task_id = create_resp.json()["data"]["task_id"]

        await async_client.delete(f"/api/research/{task_id}", headers=auth_headers)

        # 验证 step 也被级联删除
        from sqlalchemy import func
        q = select(func.count()).select_from(ResearchStep).where(ResearchStep.task_id == task_id)
        count_result = await db_session.execute(q)
        assert count_result.scalar() == 0

    async def test_任务不存在_返回404(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.delete(
            "/api/research/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
        )
        assert response.status_code == 404
        assert response.json()["code"] == "E2001"

    async def test_无权删除他人任务_返回403(
        self, async_client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        task = ResearchTask(
            id="550e8400-e29b-41d4-a716-446655440002",
            user_id=999,
            topic="别人的任务",
            requirements={"task_type": "analysis"},
            status="pending",
        )
        db_session.add(task)
        await db_session.flush()

        response = await async_client.delete(
            "/api/research/550e8400-e29b-41d4-a716-446655440002",
            headers=auth_headers,
        )
        assert response.status_code == 403
        assert response.json()["code"] == "E2002"




# ═══════════════════════════════════════════════════════════════
# POST /api/research/{task_id}/cancel — 取消任务
# ═══════════════════════════════════════════════════════════════


class TestCancelResearchAPI:
    """POST /api/research/{task_id}/cancel"""

    async def _seed_task(self, db_session: AsyncSession, status: str, user_id: int = 1, task_id: str | None = None) -> ResearchTask:
        task = ResearchTask(
            id=task_id or "task-cancel-001",
            user_id=user_id,
            topic="待取消任务",
            requirements={"task_type": "analysis"},
            status=status,
        )
        db_session.add(task)
        await db_session.flush()
        return task

    async def test_pending任务_取消成功返回200(self, async_client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
        task = await self._seed_task(db_session, status="pending", task_id="task-cancel-pending")

        response = await async_client.post(f"/api/research/{task.id}/cancel", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "0"
        assert data["message"] == "任务已取消"
        assert data["data"]["task_id"] == task.id
        assert data["data"]["status"] == "canceled"

    async def test_running任务_取消成功返回200(self, async_client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
        task = await self._seed_task(db_session, status="running", task_id="task-cancel-running")

        response = await async_client.post(f"/api/research/{task.id}/cancel", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "canceled"

    async def test_已终态返回409_E2003(self, async_client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
        for idx, status in enumerate(["completed", "failed", "partially_completed", "canceled"]):
            task = await self._seed_task(db_session, status=status, task_id=f"task-cancel-{status}-{idx}")
            response = await async_client.post(f"/api/research/{task.id}/cancel", headers=auth_headers)
            assert response.status_code == 409
            assert response.json()["code"] == "E2003"

    async def test_任务不存在返回404_E2001(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.post(
            "/api/research/00000000-0000-0000-0000-000000000000/cancel",
            headers=auth_headers,
        )
        assert response.status_code == 404
        assert response.json()["code"] == "E2001"

    async def test_无权取消他人任务返回403_E2002(self, async_client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
        task = await self._seed_task(db_session, status="pending", user_id=999, task_id="task-cancel-other")

        response = await async_client.post(f"/api/research/{task.id}/cancel", headers=auth_headers)
        assert response.status_code == 403
        assert response.json()["code"] == "E2002"

    async def test_admin可取消他人任务(self, async_client: AsyncClient, admin_headers: dict, db_session: AsyncSession):
        task = await self._seed_task(db_session, status="running", user_id=999, task_id="task-cancel-admin")

        response = await async_client.post(f"/api/research/{task.id}/cancel", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "canceled"

    async def test_CAS并发状态变更返回409_E2003(self, async_client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
        """模拟任务在 cancel 前已被 Worker 改为 completed，CAS 失败返回 E2003。"""
        task = await self._seed_task(db_session, status="running", task_id="task-cancel-cas")
        # 直接改 DB 状态为终态，但内存对象仍为 running（模拟并发）
        from sqlalchemy import update as sa_update
        await db_session.execute(
            sa_update(ResearchTask)
            .where(ResearchTask.id == task.id)
            .values(status="completed")
        )
        await db_session.flush()

        response = await async_client.post(f"/api/research/{task.id}/cancel", headers=auth_headers)
        assert response.status_code == 409
        assert response.json()["code"] == "E2003"


# ═══════════════════════════════════════════════════════════════
# GET /api/research/{task_id}/report — 报告获取
# ═══════════════════════════════════════════════════════════════


class TestGetResearchReportAPI:
    """GET /api/research/{task_id}/report"""

    async def _seed_completed_task_with_report(
        self,
        db_session: AsyncSession,
        user_id: int = 1,
        task_id: str = "task-report-001",
    ) -> ResearchTask:
        """预置一个 completed 任务，含 Evidence Graph Step 与 ReportSection。"""
        task = ResearchTask(
            id=task_id,
            user_id=user_id,
            topic="量子计算对密码学的影响",
            requirements={"task_type": "analysis", "depth": "quick", "max_sources": 10, "language": "zh"},
            status="completed",
            total_steps=7,
            completed_steps=7,
            total_sources=1,
            total_evidence=2,
            completed_at=datetime(2026, 1, 1, 0, 0, 10, tzinfo=timezone.utc),
        )
        db_session.add(task)
        await db_session.flush()

        source = ResearchSource(
            task_id=task.id,
            url="https://example.com/source-0",
            title="来源 0",
            domain="example.com",
            content="量子计算对 RSA 算法构成严重威胁。",
            fetch_status="success",
            fetched_at=datetime(2026, 1, 1, 0, 0, 3, tzinfo=timezone.utc),
        )
        db_session.add(source)
        await db_session.flush()

        ev1 = EvidenceItem(
            task_id=task.id,
            source_id=source.id,
            content="量子计算对 RSA 算法构成严重威胁。",
            relevance_score=0.95,
            used_in_sections=["1"],
        )
        ev2 = EvidenceItem(
            task_id=task.id,
            source_id=source.id,
            content="NIST 推进后量子密码标准化。",
            relevance_score=0.85,
            used_in_sections=["1"],
        )
        db_session.add(ev1)
        db_session.add(ev2)
        await db_session.flush()

        evidence_graph_step = ResearchStep(
            id="step-eg-report-001",
            task_id=task.id,
            step_type="evidence_graph",
            status="completed",
            output={
                "graph": {
                    "task_id": task.id,
                    "generated_at": datetime(2026, 1, 1, 0, 0, 7, tzinfo=timezone.utc).isoformat(),
                    "items": [
                        {
                            "index": 0,
                            "evidence_item_id": ev1.id,
                            "source_id": source.id,
                            "source_url": source.url,
                            "source_title": source.title,
                            "domain": source.domain,
                            "content": ev1.content,
                            "relevance_score": 0.95,
                            "used_in_sections": ["1"],
                        },
                        {
                            "index": 1,
                            "evidence_item_id": ev2.id,
                            "source_id": source.id,
                            "source_url": source.url,
                            "source_title": source.title,
                            "domain": source.domain,
                            "content": ev2.content,
                            "relevance_score": 0.85,
                            "used_in_sections": ["1"],
                        },
                    ],
                    "clusters": [],
                    "conflicts": [],
                    "knowledge_gaps": [],
                    "sources": [
                        {
                            "id": source.id,
                            "url": source.url,
                            "title": source.title,
                            "domain": source.domain,
                            "evidence_count": 2,
                        }
                    ],
                }
            },
            started_at=datetime(2026, 1, 1, 0, 0, 6, tzinfo=timezone.utc),
            completed_at=datetime(2026, 1, 1, 0, 0, 7, tzinfo=timezone.utc),
            duration_ms=1000,
        )
        db_session.add(evidence_graph_step)

        section = ReportSection(
            task_id=task.id,
            heading="1. 概述",
            content="量子计算威胁[来源0]，NIST 推进标准化[来源1]。",
            sort_order=0,
        )
        db_session.add(section)
        await db_session.flush()

        db_session.add(SectionEvidence(section_id=section.id, evidence_id=ev1.id))
        db_session.add(SectionEvidence(section_id=section.id, evidence_id=ev2.id))
        await db_session.flush()

        return task

    async def test_已完成任务返回完整报告JSON(self, async_client: AsyncClient, auth_headers: dict, db_session: AsyncSession):
        task = await self._seed_completed_task_with_report(db_session)

        response = await async_client.get(f"/api/research/{task.id}/report", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["task_id"] == task.id
        assert data["status"] == "completed"
        assert data["report"]["title"] == task.topic
        assert len(data["report"]["sections"]) == 1
        assert data["report"]["sections"][0]["heading"] == "1. 概述"
        assert len(data["report"]["sections"][0]["sources"]) == 2
        assert data["report"]["sections"][0]["sources"][0] == {"id": 1, "evidence_index": 0}
        assert data["report"]["sections"][0]["sources"][1] == {"id": 1, "evidence_index": 1}
        assert len(data["report"]["sources"]) == 1
        assert data["evidence_graph"]["items"][0]["index"] == 0
        assert "trace" in data

    async def test_任务不存在_返回404_E2001(self, async_client: AsyncClient, auth_headers: dict):
        response = await async_client.get(
            "/api/research/00000000-0000-0000-0000-000000000000/report",
            headers=auth_headers,
        )
        assert response.status_code == 404
        assert response.json()["code"] == "E2001"

    async def test_无权访问他人任务_返回403_E2002(
        self, async_client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        task = await self._seed_completed_task_with_report(db_session, user_id=999, task_id="task-report-002")

        response = await async_client.get(f"/api/research/{task.id}/report", headers=auth_headers)
        assert response.status_code == 403
        assert response.json()["code"] == "E2002"

    async def test_未完成任务_返回409_E2003(
        self, async_client: AsyncClient, auth_headers: dict, db_session: AsyncSession
    ):
        task = ResearchTask(
            id="task-report-003",
            user_id=1,
            topic="进行中的任务",
            requirements={"task_type": "analysis"},
            status="running",
        )
        db_session.add(task)
        await db_session.flush()

        response = await async_client.get(f"/api/research/{task.id}/report", headers=auth_headers)
        assert response.status_code == 409
        assert response.json()["code"] == "E2003"
