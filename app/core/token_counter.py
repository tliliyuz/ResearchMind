"""Token 估算 — 中英文自适应算法

算法：
- 统计中文字符占比（Unicode 范围 一..鿿）
- 中文 > 30% → 1 token ≈ 1.5 字符
- 否则 → 1 token ≈ 4.0 字符

禁止全局固定比率 —— 中英文混合文本用固定比率偏差极大。
"""

from app.config import settings


def estimate_tokens(text: str) -> int:
    """用字符数估算 token 数。

    中文字符占比 > 30% → 1 token ≈ 1.5 字符
    否则（纯英文/英文为主）→ 1 token ≈ 4.0 字符
    """
    if not text:
        return 1

    chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
    ratio = (
        settings.TOKEN_CHINESE_RATIO
        if chinese_chars / len(text) > settings.TOKEN_CHINESE_THRESHOLD
        else settings.TOKEN_ENGLISH_RATIO
    )
    return max(1, int(len(text) / ratio))
