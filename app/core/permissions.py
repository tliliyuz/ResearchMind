"""权限检查 — 共享纯函数

对齐 ARCHITECTURE.md §4 权限模型：
- v1.0 仅保留 Task Access 一层权限，用户只能访问自己创建的研究任务。

所有函数操作已加载的模型对象，不触发额外 DB 查询。
"""

from app.core.exceptions import PermissionDeniedException


def require_task_accessible(task_owner_id: int, current_user_id: int) -> None:
    """Task 访问权限检查。

    仅 owner 可访问任务（查看详情/报告/trace）。
    非 owner 时抛出 E2002。

    Args:
        task_owner_id: 任务所有者的 user_id
        current_user_id: 当前登录用户的 user_id

    Raises:
        PermissionDeniedException: 当前用户非 owner
    """
    if task_owner_id != current_user_id:
        raise PermissionDeniedException()


def require_task_owner(task_owner_id: int, current_user_id: int) -> None:
    """Task owner-only 权限检查。

    仅任务所有者可操作（取消任务、retry 等写操作）。

    Args:
        task_owner_id: 任务所有者的 user_id
        current_user_id: 当前登录用户的 user_id

    Raises:
        PermissionDeniedException: 当前用户非 owner
    """
    if task_owner_id != current_user_id:
        raise PermissionDeniedException()
