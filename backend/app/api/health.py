from fastapi import APIRouter, Depends

from ..core.auth import verify_api_key
from ..core.time import utc_now

router = APIRouter()


@router.get("/health")
def get_health(_: None = Depends(verify_api_key)):
    return {
        "status": "ok",
        "server_time": utc_now(),
    }
