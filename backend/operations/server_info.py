import psutil
import time
from fastapi import HTTPException

from backend.logger import logger
from backend.schema.output import ServerInfo, ResponseModel


async def get_server_info() -> ServerInfo:
    try:
        return ServerInfo(
            cpu=psutil.cpu_percent(interval=0.5),
            memory_total=psutil.virtual_memory().total,
            memory_used=psutil.virtual_memory().used,
            memory_percent=psutil.virtual_memory().percent,
            disk_total=psutil.disk_usage("/").total,
            disk_used=psutil.disk_usage("/").used,
            disk_percent=psutil.disk_usage("/").percent,
            uptime=int(time.time() - psutil.boot_time()),
        )
    except Exception as e:
        logger.error(f"error when get server info: {e}")
        # Return a valid ServerInfo with zeros on failure instead of wrong type
        return ServerInfo(
            cpu=0.0,
            memory_total=0,
            memory_used=0,
            memory_percent=0.0,
            disk_total=0,
            disk_used=0,
            disk_percent=0.0,
            uptime=0,
        )
