"""Knowrary 核心库：md 解析、关系归一、索引生成、契约校验。

CLI（knowrary.py）与后续的本地服务（FastAPI）都只依赖这里，避免两套解析实现漂移。
"""
from .diagnostics import Diagnostic, Diagnostics
from .index import INDEX_SCHEMA_VERSION, IndexResult, build_index, content_hash, index_path, load_previous
from .mdio import (NODE_DIRS, RE_LINK, RE_REL_HEADER, dump_frontmatter, first_paragraph, json_safe,
                   load_json, read, split_frontmatter, strip_md, walk_md, write, write_json_atomic,
                   yaml_scalar)
from .parser import Node, load_node, load_vault, validate_frontmatter
from .relations import Edge, NormalizedEdge, RelationTypes, load_relation_types, normalize_direction, parse_relations
from .schema import validate_index

__all__ = [
    "Diagnostic", "Diagnostics", "Edge", "INDEX_SCHEMA_VERSION", "IndexResult", "NODE_DIRS", "Node",
    "NormalizedEdge", "RE_LINK", "RE_REL_HEADER", "RelationTypes", "build_index", "content_hash",
    "dump_frontmatter", "first_paragraph", "index_path", "json_safe", "load_json", "load_node",
    "load_previous", "load_relation_types", "load_vault", "normalize_direction", "parse_relations", "read",
    "split_frontmatter", "strip_md", "validate_frontmatter", "validate_index", "walk_md", "write",
    "write_json_atomic", "yaml_scalar",
]
