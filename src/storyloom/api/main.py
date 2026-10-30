"""FastAPI 入口"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# 显式加载根目录 .env（不管 uvicorn 从哪启动）
_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_ROOT / ".env")

from storyloom.api.routers import projects, agents, tasks, assets, generation
from storyloom.api.engine import engine

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
app.include_router(tasks.router)
app.include_router(assets.router)
app.include_router(generation.router)


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "available_models": engine.get_available_models(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("storyloom.api.main:app", host="0.0.0.0", port=8000, reload=True)
