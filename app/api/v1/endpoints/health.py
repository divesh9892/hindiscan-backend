from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def health_check():
    """
    Check if the FastAPI backend is awake and responding.
    """
    return {
        "status": "online",
        "message": "HindiScan AI Engine is awake and ready."
    }