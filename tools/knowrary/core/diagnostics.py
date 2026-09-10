"""结构化诊断：解析、校验、索引共用一套错误/警告模型。

CLI 打印、index.json 的 errors/warnings 字段和自测断言都读同一批 Diagnostic，
避免"check 说合法、index 说非法"这类两套校验漂移。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Diagnostic:
    level: str            # error | warning
    code: str             # 机器可读的分类，见 core/README 或各 emit 处
    message: str          # 中文说明，直接给人看
    file: str = ""        # vault 相对路径，空表示 vault 级问题
    node: str = ""        # 相关节点 id
    edge: str = ""        # 相关边 id（源->目标#类型）

    def to_dict(self) -> dict:
        d = {"level": self.level, "code": self.code, "message": self.message}
        for k in ("file", "node", "edge"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        return d

    def render(self) -> str:
        return f"{self.file}: {self.message}" if self.file else self.message


@dataclass
class Diagnostics:
    """收集器。按插入顺序保留，最终由 index 生成时统一排序。"""

    items: list[Diagnostic] = field(default_factory=list)

    def error(self, code: str, message: str, **loc) -> None:
        self.items.append(Diagnostic("error", code, message, **loc))

    def warn(self, code: str, message: str, **loc) -> None:
        self.items.append(Diagnostic("warning", code, message, **loc))

    def extend(self, other: "Diagnostics | list[Diagnostic]") -> None:
        self.items.extend(other.items if isinstance(other, Diagnostics) else other)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.items if d.level == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.items if d.level == "warning"]

    def sorted_dicts(self, level: str) -> list[dict]:
        """索引里的诊断按 (文件, 分类, 说明) 排序，保证同样的 vault 产出同样的字节。"""
        picked = self.errors if level == "error" else self.warnings
        return [d.to_dict() for d in sorted(picked, key=lambda d: (d.file, d.code, d.message))]
