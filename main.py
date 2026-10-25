from dotenv import load_dotenv

from fastapi import FastAPI

from fastapi.middleware.cors import (
    CORSMiddleware,
)

from handlers.portfolio import (
    router as portfolio_router,
)

from handlers.monitoring import (
    router as monitoring_router,
)

from handlers.alerts import (
    router as alerts_router,
)

from handlers.auth import (
    router as auth_router,
)

from handlers.manager import (
    router as manager_router,
)


load_dotenv()


app = FastAPI(
    title="Privacy-First AI Portfolio Intelligence Platform",
    description=(
        "Analyze frontend-supplied portfolio data without storing raw "
        "portfolio data and continuously monitor "
        "selected holdings."
    ),
    version="2.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Routers
# ============================================================

app.include_router(
    auth_router
)

app.include_router(
    manager_router
)

app.include_router(
    portfolio_router
)

app.include_router(
    monitoring_router
)

app.include_router(
    alerts_router
)


# ============================================================
# Root
# ============================================================

@app.get("/")
async def root():

    return {
        "success": True,
        "message": (
            "Privacy-First Portfolio "
            "Intelligence API"
        ),
        "version": "2.0.0",
    }


# ============================================================
# Health
# ============================================================

@app.get("/health")
async def health():

    return {
        "success": True,
        "status": "healthy",
    }
