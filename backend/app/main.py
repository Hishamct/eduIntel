# from fastapi import FastAPI
# from app.auth.router import router as auth_router
# from app.users.router import router as users_router
# from app.student.router import router as student_router
# from app.teacher.router import router as teacher_router
# from app.admin.router import router as admin_router

# app = FastAPI(title="EduIntel AI")

# app.include_router(auth_router)
# app.include_router(users_router)
# app.include_router(student_router)
# app.include_router(teacher_router)
# app.include_router(admin_router)

# @app.get("/health")
# def health_check():
#     return {"status": "ok"}


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.auth.router import router as auth_router
from app.users.router import router as users_router
from app.student.router import router as student_router
from app.teacher.router import router as teacher_router
from app.admin.router import router as admin_router

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

@app.get("/health")
def health_check():
    return {"status": "ok"}