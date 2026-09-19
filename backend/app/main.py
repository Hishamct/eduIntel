from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.auth.router import router as auth_router
from app.users.router import router as users_router
from app.student.router import router as student_router
from app.teacher.router import router as teacher_router
from app.admin.router import router as admin_router
from app.ocr.router import router as ocr_router
from app.rag.router import router as rag_router
from app.announcements.router import router as announcements_router
from app.agents.router import router as agents_router
from app.ml.router import router as ml_router
from app.reports.router import router as reports_router

app = FastAPI(title="EduIntel AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(student_router)
app.include_router(teacher_router)
app.include_router(admin_router)
app.include_router(ocr_router)
app.include_router(rag_router)
app.include_router(announcements_router)
app.include_router(agents_router)
app.include_router(ml_router)
app.include_router(reports_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}

