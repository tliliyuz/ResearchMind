"""WorkingMemory / ReActEntry 单元测试。"""

from datetime import datetime, timezone

import pytest

from app.agent.memory import ReActEntry, WorkingMemory


class TestReActEntry:
    def test_to_dict_包含iso时间(self):
        entry = ReActEntry(
            iteration=1,
            phase="planning",
            thought="思考",
            tool_name="plan_tool",
            observation="完成",
        )
        data = entry.to_dict()
        assert data["iteration"] == 1
        assert data["phase"] == "planning"
        assert data["thought"] == "思考"
        assert isinstance(data["timestamp"], str)

    def test_from_dict_恢复时间(self):
        ts = datetime.now(timezone.utc)
        entry = ReActEntry.from_dict({
            "iteration": 2,
            "phase": "search",
            "tool_name": "search_tool",
            "timestamp": ts.isoformat(),
        })
        assert entry.iteration == 2
        assert entry.phase == "search"
        assert entry.tool_name == "search_tool"
        assert isinstance(entry.timestamp, datetime)


class TestWorkingMemory:
    def test_add_超过上限丢弃最旧(self):
        memory = WorkingMemory(max_entries=3)
        for i in range(5):
            memory.add(ReActEntry(iteration=i, phase="planning"))
        assert len(memory.recent()) == 3
        assert memory.recent()[0].iteration == 2
        assert memory.recent()[-1].iteration == 4

    def test_to_messages_格式化记录(self):
        memory = WorkingMemory()
        memory.add(ReActEntry(
            iteration=1,
            phase="planning",
            thought="思考1",
            tool_name="plan_tool",
            arguments={"x": 1},
            observation="观察1",
        ))
        messages = memory.to_messages()
        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"
        content = messages[0]["content"]
        assert "思考：思考1" in content
        assert "plan_tool" in content
        assert "观察：观察1" in content

    def test_dict_序列化反序列化(self):
        memory = WorkingMemory(max_entries=10)
        memory.add(ReActEntry(iteration=1, phase="planning", thought="t"))
        items = memory.to_dict_list()
        restored = WorkingMemory.from_dict_list(items, max_entries=10)
        assert len(restored.recent()) == 1
        assert restored.recent()[0].thought == "t"

    def test_from_dict_list_过滤非dict(self):
        restored = WorkingMemory.from_dict_list([None, {"iteration": 1, "phase": "p"}], max_entries=5)
        assert len(restored.recent()) == 1

    def test_add_后进入pending队列(self):
        memory = WorkingMemory()
        entry = ReActEntry(iteration=1, phase="planning")
        memory.add(entry)
        assert memory.pending_entries() == [entry]

    def test_mark_persisted_清空pending(self):
        memory = WorkingMemory()
        memory.add(ReActEntry(iteration=1, phase="planning"))
        memory.mark_persisted()
        assert memory.pending_entries() == []
        # entries 仍保留在内存缓冲区
        assert len(memory.recent()) == 1

    def test_from_dict_list_不进入pending队列(self):
        memory = WorkingMemory.from_dict_list([{"iteration": 1, "phase": "planning"}], max_entries=5)
        assert memory.pending_entries() == []
        assert len(memory.recent()) == 1
