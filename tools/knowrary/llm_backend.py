"""Knowrary · LLM 后端（配置文件驱动：多 provider、按角色选用）

配置文件：<vault>/.knowrary/llm.local.json（gitignore 忽略 *.local.json），模板见 llm.example.json。
环境变量 KNOWRARY_LLM_CONFIG 可指向别处。没有配置文件时退回 `claude -p`（复用 Claude Code 登录）。

{
  "providers": {
    "<名字>": { "type": "claude-cli" | "anthropic" | "openai", "model": "...", "api_key": "sk-.. 或 env:VAR", "base_url": "..." }
  },
  "roles": { "learn": "<名字>", "review": "<名字>" }
}

零第三方依赖：anthropic / openai 兼容协议都走 urllib；装了 anthropic SDK 时 anthropic 类型自动改用 SDK 流式（长输出更稳）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_NAME = "llm.local.json"
EXAMPLE_NAME = "llm.example.json"
ROLES = ("learn", "review")
TYPES = ("claude-cli", "anthropic", "openai")
DEFAULT_MODELS = {"anthropic": "claude-opus-5", "openai": "gpt-4o"}
DEFAULT_CONFIG = {
    "providers": {"claude-cli": {"type": "claude-cli"}},
    "roles": {"learn": "claude-cli", "review": "claude-cli"},
}
TIMEOUT = 900


class LLMConfigError(SystemExit):
    pass


# ---------------------------------------------------------------- 配置

def config_path(vault: Path) -> Path:
    env = os.environ.get("KNOWRARY_LLM_CONFIG")
    return Path(env).expanduser() if env else vault / ".knowrary" / CONFIG_NAME


def load_config(vault: Path) -> tuple[dict, Path | None]:
    """返回 (配置, 来源路径)；没有配置文件时返回 (默认配置, None)。"""
    path = config_path(vault)
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG)), None
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LLMConfigError(f"LLM 配置不是合法 JSON：{path}\n  {e}")
    validate_config(cfg, path)
    return cfg, path


def validate_config(cfg: dict, path: Path) -> None:
    providers = cfg.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise LLMConfigError(f"{path}: `providers` 必须是非空对象")
    for name, p in providers.items():
        if not isinstance(p, dict) or p.get("type") not in TYPES:
            raise LLMConfigError(f"{path}: provider `{name}` 的 type 必须是 {'/'.join(TYPES)}")
        if p["type"] == "openai" and not p.get("base_url"):
            raise LLMConfigError(f"{path}: provider `{name}`（openai 兼容）缺少 base_url")
    roles = cfg.get("roles") or {}
    if not isinstance(roles, dict):
        raise LLMConfigError(f"{path}: `roles` 必须是对象")
    for role, name in roles.items():
        if name not in providers:
            raise LLMConfigError(f"{path}: 角色 `{role}` 指向不存在的 provider `{name}`")
    for role in ROLES:
        roles.setdefault(role, next(iter(providers)))
    cfg["roles"] = roles


def resolve_provider(cfg: dict, role: str, override: str | None = None) -> tuple[str, dict]:
    """按角色取 provider；--llm <名字> 可临时覆盖。"""
    name = override or cfg["roles"].get(role) or next(iter(cfg["providers"]))
    if name not in cfg["providers"]:
        raise LLMConfigError(f"未知 provider `{name}`，可选：{', '.join(cfg['providers'])}")
    return name, cfg["providers"][name]


def resolve_secret(value: str | None) -> str | None:
    """api_key 支持 `env:VAR_NAME` 引用环境变量。"""
    if isinstance(value, str) and value.startswith("env:"):
        var = value[4:]
        secret = os.environ.get(var)
        if not secret:
            raise LLMConfigError(f"api_key 引用的环境变量 {var} 未设置")
        return secret
    return value


def describe(cfg: dict, path: Path | None) -> str:
    lines = [f"配置文件：{path or '（无，使用默认 claude-cli）'}"]
    for name, p in cfg["providers"].items():
        roles = [r for r, n in cfg["roles"].items() if n == name]
        tag = f"  ← 角色 {', '.join(roles)}" if roles else ""
        model = p.get("model") or DEFAULT_MODELS.get(p["type"], "（claude 默认）")
        lines.append(f"  {name:<14} {p['type']:<10} {model}{tag}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 调用

def ask(prompt: str, provider: dict, model_override: str | None = None) -> str:
    model = model_override or provider.get("model")
    kind = provider["type"]
    if kind == "claude-cli":
        return _ask_claude_cli(prompt, model)
    if kind == "anthropic":
        return _ask_anthropic(prompt, provider, model or DEFAULT_MODELS["anthropic"])
    return _ask_openai(prompt, provider, model or DEFAULT_MODELS["openai"])


def _ask_claude_cli(prompt: str, model: str | None) -> str:
    cmd = ["claude", "-p", "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=TIMEOUT)
    except FileNotFoundError:
        raise LLMConfigError("找不到 `claude` 命令：安装 Claude Code，或在 llm.local.json 里配置 anthropic / openai 类型的 provider")
    if proc.returncode != 0:
        raise SystemExit(f"claude -p 失败（{proc.returncode}）：{proc.stderr[:500]}")
    try:
        data = json.loads(proc.stdout)
        return data.get("result") if isinstance(data, dict) else proc.stdout
    except json.JSONDecodeError:
        return proc.stdout


def _ask_anthropic(prompt: str, provider: dict, model: str) -> str:
    api_key = resolve_secret(provider.get("api_key")) or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMConfigError("anthropic provider 缺少 api_key（也可设置 ANTHROPIC_API_KEY）")
    base = (provider.get("base_url") or "https://api.anthropic.com").rstrip("/")
    max_tokens = int(provider.get("max_tokens", 16000))
    if importlib.util.find_spec("anthropic") is None:
        return _ask_anthropic_rest(prompt, api_key, base, model, max_tokens)
    return _ask_anthropic_sdk(prompt, api_key, base, model, max_tokens)


def _ask_anthropic_sdk(prompt: str, api_key: str, base: str, model: str, max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, base_url=base)
    with client.messages.stream(
        model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise SystemExit("模型拒绝了这次请求")
    return "".join(b.text for b in msg.content if b.type == "text")


def _ask_anthropic_rest(prompt: str, api_key: str, base: str, model: str, max_tokens: int) -> str:
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    payload = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    data = _post_json(f"{base}/v1/messages", headers, payload)
    if data.get("stop_reason") == "refusal":
        raise SystemExit("模型拒绝了这次请求")
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _ask_openai(prompt: str, provider: dict, model: str) -> str:
    """OpenAI 兼容协议：OpenAI / DeepSeek / 通义 / Ollama / vLLM 等。"""
    api_key = resolve_secret(provider.get("api_key")) or "none"
    base = provider["base_url"].rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    if provider.get("max_tokens"):
        payload["max_tokens"] = int(provider["max_tokens"])
    if provider.get("temperature") is not None:
        payload["temperature"] = provider["temperature"]
    data = _post_json(f"{base}/chat/completions", headers, payload)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise SystemExit("OpenAI 兼容接口返回格式异常：\n" + json.dumps(data, ensure_ascii=False)[:800])


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:800]
        raise SystemExit(f"LLM 请求失败 HTTP {e.code}（{url}）：\n{detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"LLM 连接失败（{url}）：{e.reason}")


def ping(provider: dict, model_override: str | None = None) -> str:
    """连通性测试：要求模型只回复 OK。"""
    return ask("只回复两个大写字母：OK", provider, model_override).strip()
