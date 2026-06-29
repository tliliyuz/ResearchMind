"""Agent Runtime 层异常。"""


class AgentLoopExhaustedError(Exception):
    """Agent Loop 达到最大迭代次数仍未结束。"""

    def __init__(self, max_iterations: int):
        self.max_iterations = max_iterations
        super().__init__(f"Agent Loop 迭代次数超过上限 {max_iterations}")
