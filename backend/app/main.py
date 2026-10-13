from fastapi import FastAPI, Depends
from app.core.auth import require_admin
from app.api.auth import router as auth_router
from app.api.student import router as student_router

from app.api.crud import router
from app.api.knowledge import router as knowledge_router
from app.api.diagnosis import router as diagnosis_router
from app.api.planning import router as planning_router
from app.api.reminders import router as reminders_router
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True, allow_methods=['GET','POST','PUT','PATCH','DELETE'], allow_headers=['Authorization','Content-Type','X-MathPilot-Request','X-Admin-Key'])
app.include_router(router, prefix=settings.api_prefix, dependencies=[Depends(require_admin)])
app.include_router(knowledge_router, prefix=settings.api_prefix, dependencies=[Depends(require_admin)])
app.include_router(diagnosis_router, prefix=settings.api_prefix, dependencies=[Depends(require_admin)])
app.include_router(planning_router, prefix=settings.api_prefix, dependencies=[Depends(require_admin)])
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(student_router, prefix=settings.api_prefix)


@app.middleware('http')
async def private_responses(request, call_next):
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response
app.include_router(reminders_router, prefix=settings.api_prefix)


@app.get("/health", tags=["System"])
def health() -> dict[str, str]:
    return {"status": "ok"}

