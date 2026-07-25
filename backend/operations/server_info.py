import psutil
import time

from backend.logger import logger
from backend.schema.output import ServerInfo


async def get_server_info() -> ServerInfo:
    """Collect server metrics. Uses short interval to minimize blocking."""
    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return ServerInfo(
            cpu=cpu,
            memory_total=mem.total,
            memory_used=mem.used,
            memory_percent=mem.percent,
            disk_total=disk.total,
            disk_used=disk.used,
            disk_percent=disk.percent,
            uptime=int(time.time() - psutil.boot_time()),
        )
    except Exception as e:
        logger.error("error getting server info: %s", e)
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
