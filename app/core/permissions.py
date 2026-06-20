"""权限检查 — 共享纯函数，两层分离

对齐 ARCHITECTURE.md §4 权限模型：
- require_task_accessible：资源归属检查（owner 或 admin 可通过）
- require_admin：系统角色检查（仅 admin 可通过）

从 DocMind 复制两层分离模式，替换为 Task 级权限检查逻辑。
所有函数操作已加载的模型对象，不触发额外 DB 查询。
"""

from app.core.exceptions import AdminPermissionRequiredException, PermissionDeniedException


def require_task_accessible(task_owner_id: int, current_user_id: int, role: str) -> None:
    """Task 访问权限检查。

    owner 或 admin 可访问任务（查看详情/报告/trace）。
    非 owner 且非 admin 时抛出 E2002。

    Args:
        task_owner_id: 任务所有者的 user_id
        current_user_id: 当前登录用户的 user_id
        role: 当前用户的角色（user / admin）

    Raises:
        PermissionDeniedException: 当前用户非 owner 且非 admin
    """
    if task_owner_id != current_user_id and role != "admin":
        raise PermissionDeniedException()


def require_task_owner(task_owner_id: int, current_user_id: int) -> None:
    """Task owner-only 权限检查。

    仅任务所有者可操作（admin 也不允许）。
    用于取消任务、retry 等写操作。

    Args:
        task_owner_id: 任务所有者的 user_id
        current_user_id: 当前登录用户的 user_id

    Raises:
        PermissionDeniedException: 当前用户非 owner
    """
    if task_owner_id != current_user_id:
        raise PermissionDeniedException()


def require_admin(role: str) -> None:
    """管理员权限检查。

    仅 admin 角色可通过。
    用于管理后台接口（统计/用户管理/全局任务查看）。

    Args:
        role: 当前用户的角色

    Raises:
        AdminPermissionRequiredException: 当前用户非 admin
    """
    if role != "admin":
        raise AdminPermissionRequiredException()
