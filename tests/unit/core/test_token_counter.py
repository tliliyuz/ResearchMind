"""Token 估算单元测试 — 覆盖 app/core/token_counter.py 中英文自适应算法。

对齐 TESTING_STRATEGY.md §4.8：
- 纯英文 ratio 4.0 / 纯中文 ratio 1.5 / 混合>30%中文用中文 ratio
- 临界点 30% / 空字符串返回 1
"""

from app.core.token_counter import estimate_tokens


class TestEstimateTokens:
    """中英文自适应 token 估算"""

    def test_纯英文_ratio_4(self):
        """纯英文：1 token ≈ 4.0 字符"""
        text = "Hello this is a test string with many words"
        result = estimate_tokens(text)
        expected = max(1, int(len(text) / 4.0))
        assert result == expected

    def test_纯中文_ratio_1_5(self):
        """纯中文：1 token ≈ 1.5 字符"""
        text = "这是一段纯中文文本用于测试自适应算法"
        result = estimate_tokens(text)
        expected = max(1, int(len(text) / 1.5))
        assert result == expected

    def test_中文超过30百分比用ratio_1_5(self):
        """中文占比 > 30% → 使用中文 ratio 1.5"""
        # 构造：20 中文 + 20 英文 = 40 字符，中文占比 50% > 30%
        text = "测试中文内容测试中文内容hello world english text"
        result = estimate_tokens(text)
        expected = max(1, int(len(text) / 1.5))
        assert result == expected

    def test_中文低于30百分比用ratio_4(self):
        """中文占比 ≤ 30% → 使用英文 ratio 4.0"""
        # 构造：5 中文 + 30 英文 = 35 字符，中文占比 ≈14% < 30%
        text = "你好hello this is a long english sentence"
        result = estimate_tokens(text)
        # 中文占比应 < 30%
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        assert chinese_chars / len(text) <= 0.3
        expected = max(1, int(len(text) / 4.0))
        assert result == expected

    def test_临界点恰好30百分比用ratio_4(self):
        """中文占比恰好 30%（≤ threshold）→ 使用英文 ratio"""
        # 10 字符中 3 个中文 = 30%
        text = "abc一二三efgh"
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        assert chinese_chars / len(text) == 0.3
        result = estimate_tokens(text)
        expected = max(1, int(len(text) / 4.0))
        assert result == expected

    def test_空字符串返回1(self):
        assert estimate_tokens("") == 1

    def test_最少返回1(self):
        """单字符不应返回 0"""
        assert estimate_tokens("a") == 1
        assert estimate_tokens("中") == 1

    def test_结果为正整数(self):
        result = estimate_tokens("some text here")
        assert isinstance(result, int)
        assert result > 0  # "some text here" = 15 字符，ratio=4.0 → int(15/4)=3
