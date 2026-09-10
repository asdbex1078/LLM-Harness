"""FastAPI 本地服务：只读 index、读写 layout，静态托管前端构建产物。

边界（设计文档 3.4）：这一层永远不改 Markdown。改 md 只能走阶段 3 的 ChangeSet。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .contracts import LayoutPatch, LayoutRead, LayoutSaved
from .index_service import current_index
from .layout_store import (LayoutBroken, PatchRejected, RevisionConflict, apply_patch, find_orphans,
                           load_or_init)
from .paths import WEB_DIST, vault_path

app = FastAPI(title="Knowrary 本地服务", version="0.2.0",
              description="结构视图的数据源：index 只读、layout 可写、Markdown 不动")

# 开发期前端跑在 Vite（5173），构建产物同源托管时用不到 CORS
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(LayoutBroken)
def _on_layout_broken(_request, exc: LayoutBroken) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc),
                                                  "hint": "原文件已保留，修好或删除后重启即可重新生成"})


@app.get("/api/health")
def health() -> dict:
    vault = vault_path()
    index = current_index(vault)
    layout, generated = load_or_init(vault, index)
    return {"vault": str(vault), "index_revision": index["revision"], "stats": index["stats"],
            "layout_revision": layout.revision, "layout_generated": generated,
            "web_dist": WEB_DIST.exists()}


@app.get("/api/index")
def get_index() -> dict:
    """派生缓存，只读。前端据此渲染节点与边，真值永远在 md。"""
    return current_index(vault_path())


@app.get("/api/layout", response_model=LayoutRead)
def get_layout() -> LayoutRead:
    vault = vault_path()
    index = current_index(vault)
    layout, generated = load_or_init(vault, index)
    return LayoutRead(layout=layout, orphans=find_orphans(layout, index, vault),
                      index_revision=index["revision"], generated=generated)


@app.patch("/api/layout", response_model=LayoutSaved)
def patch_layout(patch: LayoutPatch) -> LayoutSaved:
    """高频写入口：拖拽、折叠、便签。只改 layout.json，不进确认流程。"""
    vault = vault_path()
    index = current_index(vault)
    try:
        doc, orphans = apply_patch(vault, patch, index)
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail={
            "message": str(exc), "current_revision": exc.current.revision,
            "hint": "重新 GET /api/layout 后基于新 revision 重试"}) from exc
    except PatchRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LayoutSaved(revision=doc.revision, updated_at=doc.updated_at or "", orphans=orphans)


def _mount_web() -> None:
    """有构建产物时同源托管前端（运行期零 Node）。"""
    if not WEB_DIST.exists():
        return
    assets = WEB_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/")
    def index_html() -> FileResponse:
        return FileResponse(str(WEB_DIST / "index.html"))


_mount_web()


def vault_assets_dir() -> Path:
    return vault_path() / "assets"
