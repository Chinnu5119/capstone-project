from fastapi import APIRouter

from . import alerts, costs, resources, system

api_router = APIRouter(prefix="/api")
for module in (system, costs, resources, alerts):
    api_router.include_router(module.router)
