"""OfficeCLI 安装状态查询端点。"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from crabagent.core.office.manager import get_office_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/officecli", tags=["officecli"])


@router.get("/status")
async def officecli_status():
    """返回 OfficeCLI 的安装状态，供前端轮询。"""
    mgr = get_office_manager()
    status = mgr.get_install_status()
    # 补充 available 字段方便前端判断
    status["available"] = mgr.available
    if mgr.version:
        status["version"] = mgr.version
    return status
