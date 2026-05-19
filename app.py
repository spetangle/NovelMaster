# -*- coding: utf-8 -*-
"""
NovelMaster WebUI 应用入口 (FastAPI)
"""

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

# 尝试导入API路由
try:
    from api.routes import router as api_router
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from api.routes import router as api_router

# 获取路径
BASE_DIR = Path(__file__).parent
WEB_DIR = BASE_DIR / 'web'
STATIC_DIR = WEB_DIR / 'static'

# 创建FastAPI应用
app = FastAPI(
    title="NovelMaster API",
    description="AI小说创作助手API",
    version="1.2.0"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册API路由
app.include_router(api_router, prefix="/api")

# 挂载静态文件
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    """主页面"""
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/{path:path}")
async def catch_all(path: str):
    """SPA路由 - 所有路径都返回index.html"""
    # 检查是否是静态文件请求
    if '.' in path:
        file_path = WEB_DIR / path
        if file_path.exists():
            return FileResponse(str(file_path))
    
    # 返回index.html以支持前端路由
    return FileResponse(str(WEB_DIR / "index.html"))


def main():
    """启动服务"""
    import uvicorn
    
    workspace = os.getenv('WORKSPACE', './workspace')
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', '13567'))
    
    print(f"""
╔══════════════════════════════════════════════════════╗
║           NovelMaster WebUI v1.2.0 (FastAPI)          ║
╠══════════════════════════════════════════════════════╣
║  工作目录: {workspace}
║  地址: http://{host}:{port}
║  API文档: http://{host}:{port}/docs
╚══════════════════════════════════════════════════════╝
    按 Ctrl+C 可结束进程
    """)
    
    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        reload=debug,
        reload_dirs=[str(BASE_DIR)]
    )


if __name__ == '__main__':
    main()
