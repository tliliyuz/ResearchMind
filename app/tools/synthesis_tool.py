"""synthesis_tool —— 包装 run_synthesis。"""

from app.pipeline.synthesizer import run_synthesis
from app.tools.base import PhaseHandlerTool

synthesis_tool = PhaseHandlerTool(
    name="synthesis_tool",
    description="Synthesis 阶段：跨来源综合、发现冲突与知识缺口",
    mapped_phase="synthesis",
    handler=run_synthesis,
)
