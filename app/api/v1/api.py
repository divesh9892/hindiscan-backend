from fastapi import APIRouter
from app.api.v1.endpoints import health, extract, admin, users, billing

api_router = APIRouter()

# Register the health endpoint under the /health prefix
api_router.include_router(health.router, prefix="/health", tags=["System"])
api_router.include_router(extract.router, prefix="/extract", tags=["Extraction"])
api_router.include_router(admin.router, prefix="/admin", tags=["Admin"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])