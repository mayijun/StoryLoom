"""FastAPI 入口"""

import sys
from pathlib import Path

# 让 backend/api 可以裸写 from api.xxx
_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from api.routers import projects, agents, assets, generation

app = FastAPI(
    title="多Agent小说生成系统 API",
    version="3.0",
    description="Multi-Agent Novel Generation System",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(agents.router)
app.include_router(assets.router)
app.include_router(generation.router)


@app.get("/api/health")
async def health():
    from api.engine import engine
    return {
        "status": "ok",
        "available_models": engine.get_available_models(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
