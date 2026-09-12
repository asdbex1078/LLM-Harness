"""FastAPI 本地服务：只读 index、读写 layout，静态托管前端构建产物。

边界（设计文档 3.4）：这一层永远不改 Markdown。改 md 只能走阶段 3 的 ChangeSet。
"""
from __future__ import annotations

import difflib
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .contracts import ChangeResult, ChangeSet, FileDiff, LayoutPatch, LayoutRead, LayoutSaved, NodeDetail
from .index_service import current_index, invalidate
from .layout_store import (LayoutBroken, PatchRejected, RevisionConflict, apply_patch, find_orphans,
                           load_or_init)
from .paths import WEB3D_DIST, WEB_DIST, core, vault_path

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
            "web_dist": WEB_DIST.exists(), "web3d": WEB3D_DIST.exists()}


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
        doc, orphans, backup = apply_patch(vault, patch, index)
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail={
            "message": str(exc), "current_revision": exc.current.revision,
            "hint": "重新 GET /api/layout 后基于新 revision 重试"}) from exc
    except PatchRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LayoutSaved(revision=doc.revision, updated_at=doc.updated_at or "", orphans=orphans,
                       backup=backup)


@app.get("/api/node/{node_id}", response_model=NodeDetail)
def get_node(node_id: str) -> NodeDetail:
    """单个节点：md 原文 + 元数据 + 出入边 + Obsidian 打开链接。只读。"""
    vault = vault_path()
    index = current_index(vault)
    meta = next((n for n in index["nodes"] if n["id"] == node_id), None)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"节点 `{node_id}` 不在索引里")
    if meta.get("virtual") or not meta.get("path"):
        raise HTTPException(status_code=404, detail=f"`{node_id}` 只是被引用的占位 stub，还没有 md 文件")
    path = vault / meta["path"]
    edges = {e["id"]: e for e in index["edges"]}
    return NodeDetail(
        id=node_id, path=meta["path"], raw=core.read(path), digest=meta.get("digest", ""),
        meta={k: v for k, v in meta.items() if k not in ("out", "in", "path", "digest")},
        out=[edges[i] for i in meta.get("out", []) if i in edges],
        in_edges=[edges[i] for i in meta.get("in", []) if i in edges],
        obsidian_uri=f"obsidian://open?vault={quote(vault.name)}&file={quote(meta['path'])}",
    )


@app.post("/api/changes", response_model=ChangeResult)
def post_changes(changeset: ChangeSet) -> ChangeResult:
    """Markdown 写回的唯一入口：默认只预览，dry_run=false 才落盘（落盘前自动备份）。"""
    vault = vault_path()
    index = current_index(vault)
    if changeset.base_revision and changeset.base_revision != index["revision"]:
        raise HTTPException(status_code=409, detail={
            "message": f"索引已更新（当前 revision {index['revision']}）", "current_revision": index["revision"],
            "hint": "重新拉取 /api/index 后再提交"})
    payload = [c.model_dump(exclude_none=True) for c in changeset.changes]
    try:
        edits = core.plan(vault, payload, index)
    except core.WriteConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except core.ChangeRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    files = [FileDiff(path=e.rel, notes=e.notes, diff=_diff(e)) for e in edits]
    if changeset.dry_run:
        return ChangeResult(applied=False, files=files, index_revision=index["revision"])
    snapshot = core.commit(vault, edits)
    invalidate(vault)                      # md 变了，索引缓存作废
    return ChangeResult(applied=True, files=files, backup=snapshot or None,
                        index_revision=current_index(vault)["revision"])


def _diff(edit) -> str:
    """给人看的统一 diff（只保留有变化的片段）。"""
    lines = difflib.unified_diff(edit.before.splitlines(), edit.after.splitlines(),
                                 fromfile=f"a/{edit.rel}", tofile=f"b/{edit.rel}", lineterm="", n=2)
    return "\n".join(list(lines)[:60])


def _mount_web() -> None:
    """有构建产物时同源托管前端（运行期零 Node）。/3d 是只读的 3D 总览原型，可随时删。"""
    if WEB3D_DIST.exists():
        app.mount("/3d", StaticFiles(directory=str(WEB3D_DIST), html=True), name="web3d")
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
