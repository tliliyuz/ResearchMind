"""
ORM 模型包 —— 导入全部模型类，使 Alembic 的 target_metadata 能发现全部表。

一表一文件，按依赖顺序导入：先 user 域（无外部依赖），后 research 域。
共享枚举/工具见 enums.py、_types.py。
"""

from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.models.research_task import ResearchTask
from app.models.research_step import ResearchStep
from app.models.agent_memory_entry import AgentMemoryEntry
from app.models.research_source import ResearchSource
from app.models.evidence_item import EvidenceItem
from app.models.report_section import ReportSection
from app.models.section_evidence import SectionEvidence

__all__ = [
    "User",
    "RefreshToken",
    "ResearchTask",
    "ResearchStep",
    "AgentMemoryEntry",
    "ResearchSource",
    "EvidenceItem",
    "ReportSection",
    "SectionEvidence",
]
