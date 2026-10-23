"""
Copyright (C) 2026 Ma Yijun (ma.yijun@outlook.com)
This file is part of StoryLoom — licensed under GPL v3, see LICENSE.

织章 StoryLoom —— Web 模式启动器（默认入口）

启动 FastAPI 后端（:8000）+ Vite 前端开发服务器（:5173），
就绪后自动打开浏览器。按 Ctrl+C 停止所有服务。

用法：
    python app.py
"""

import os
import sys
import time
import socket
import webbrowser
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
# Vite 默认绑定到 IPv6 回环 (::1)，用 localhost 才能连通
FRONTEND_HOST = "localhost"
FRONTEND_PORT = 5173


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except (ConnectionRefusedError, OSError):
        return False


def wait_for_port(host: str, port: int, timeout: float = 90.0) -> bool:
    """轮询等待端口就绪"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.5)
    return False


def main() -> None:
    os.chdir(PROJECT_ROOT)

    # Windows 下创建独立进程组，便于整体终止
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    # ---------- 启动后端 ----------
    print("🚀 启动 FastAPI 后端 (端口 8000)...", flush=True)
    backend_proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "api.main:app",
            "--host", BACKEND_HOST,
            "--port", str(BACKEND_PORT),
        ],
        cwd=str(BACKEND_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    # ---------- 启动前端 ----------
    print("🚀 启动 Vite 前端 (端口 5173)...", flush=True)
    # Windows 下 npm 实际是 npm.cmd，需经 shell 解析
    frontend_proc = subprocess.Popen(
        "npm run dev",
        cwd=str(FRONTEND_DIR),
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )

    procs = [backend_proc, frontend_proc]

    try:
        # 等待后端
        if wait_for_port(BACKEND_HOST, BACKEND_PORT, timeout=90):
            print(f"✅ 后端就绪: http://{BACKEND_HOST}:{BACKEND_PORT}", flush=True)
        else:
            print("⚠️  后端启动超时", flush=True)

        # 等待前端
        if wait_for_port(FRONTEND_HOST, FRONTEND_PORT, timeout=90):
            print(f"✅ 前端就绪: http://{FRONTEND_HOST}:{FRONTEND_PORT}", flush=True)
        else:
            print("⚠️  前端启动超时，请确认已执行 `cd frontend && npm install`", flush=True)

        # 打开浏览器
        url = f"http://localhost:{FRONTEND_PORT}"
        print(f"🌐 打开浏览器: {url}", flush=True)
        webbrowser.open(url)

        print("\n按 Ctrl+C 停止所有服务...\n", flush=True)
        while True:
            time.sleep(1)
            if any(p.poll() is not None for p in procs):
                print("⚠️  某个服务已退出，正在关闭...", flush=True)
                break
    except KeyboardInterrupt:
        print("\n🛑 正在停止服务...", flush=True)
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        try:
            for p in procs:
                p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            for p in procs:
                if p.poll() is None:
                    p.kill()
        print("✅ 已停止所有服务", flush=True)


if __name__ == "__main__":
    main()
