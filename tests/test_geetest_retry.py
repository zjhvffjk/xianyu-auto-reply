"""极验请求重试逻辑单元测试。

直接从源码里 AST 抽出 `_request_geetest` 与 `GeetestConfig`，
保证测的就是线上要跑的那份代码；httpx / loguru 用假件替换。

用法：python test_geetest_retry.py
"""
import ast
import asyncio
import os
import sys
import types
import typing

# 相对本文件定位仓库根：tests/ -> 仓库根 -> common/services/geetest
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(REPO_ROOT, "common", "services", "geetest")

# ---------------- 从源码抽取 ----------------


def extract(path, want_funcs, want_classes):
    src = open(path, encoding="utf-8").read()
    chunks = []
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name in want_funcs:
            chunks.append(ast.get_source_segment(src, node))
        elif isinstance(node, ast.ClassDef) and node.name in want_classes:
            chunks.append(ast.get_source_segment(src, node))
    return "\n\n".join(chunks)


CODE = extract(
    os.path.join(ROOT, "geetest_config.py"), set(), {"GeetestConfig"}
) + "\n\n" + extract(
    os.path.join(ROOT, "geetest_lib.py"), {"_request_geetest"}, set()
)

# ---------------- 假件 ----------------


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    """前 fail_times 次调用抛连接异常，之后返回 payload。"""

    calls = 0
    fail_times = 0
    payload = {"seccode": "true"}
    urls = []

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None):
        return await self._handle(url)

    async def post(self, url, data=None):
        return await self._handle(url)

    async def _handle(self, url):
        FakeClient.calls += 1
        FakeClient.urls.append(url)
        if FakeClient.calls <= FakeClient.fail_times:
            raise RuntimeError("All connection attempts failed")
        return FakeResponse(FakeClient.payload)


class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.errors = []

    def warning(self, msg):
        self.warnings.append(msg)

    def error(self, msg):
        self.errors.append(msg)

    def info(self, msg):
        pass


def build_namespace():
    httpx_mod = types.ModuleType("httpx")
    httpx_mod.AsyncClient = FakeClient
    logger = FakeLogger()
    loguru_mod = types.ModuleType("loguru")
    loguru_mod.logger = logger
    ns = {
        "os": os,
        "asyncio": asyncio,
        "httpx": httpx_mod,
        "logger": logger,
        "Any": typing.Any,
        "Optional": typing.Optional,
    }
    exec(CODE, ns)  # noqa: S102
    ns["_LOGGER"] = logger
    ns["_LOGS"] = logger
    # 测试里不想真的等 0.5 秒
    ns["GeetestConfig"].RETRY_INTERVAL = 0
    return ns


NS = build_namespace()
request_geetest = NS["_request_geetest"]
Config = NS["GeetestConfig"]
LOGS = NS["_LOGS"]


def reset(fail_times=0, payload=None):
    FakeClient.calls = 0
    FakeClient.fail_times = fail_times
    FakeClient.urls = []
    FakeClient.payload = {"seccode": "true"} if payload is None else payload
    LOGS.warnings.clear()
    LOGS.errors.clear()


CASES = [
    ("一次就成功：只发 1 次请求，不重试",
     dict(fail_times=0), "true", 1, 0),
    ("第 1 次连不上、第 2 次成功：自动重试后拿到结果",
     dict(fail_times=1), "true", 2, 1),
    ("前 2 次都连不上、第 3 次成功：用完重试额度才成功",
     dict(fail_times=2), "true", 3, 2),
    ("3 次全连不上：返回 None，交给调用方降级",
     dict(fail_times=3), None, 3, 2),
    ("失败次数超过重试次数：也只发 3 次，不会无限重试",
     dict(fail_times=9), None, 3, 2),
    ("响应不是 JSON 对象：返回 None",
     dict(fail_times=0, payload=["not", "a", "dict"]), None, 1, 0),
]

URL = f"{Config.API_URL}{Config.VALIDATE_URL}"


def main():
    ok = fail = 0
    for name, setup, expect_seccode, expect_calls, expect_warn in CASES:
        reset(**setup)
        got = asyncio.run(request_geetest("post", URL, {}))
        seccode = got.get("seccode") if isinstance(got, dict) else got
        if seccode == expect_seccode and FakeClient.calls == expect_calls \
                and len(LOGS.warnings) == expect_warn:
            ok += 1
            print(f"  PASS  {name}")
        else:
            fail += 1
            print(f"  FAIL  {name}")
            print(f"        seccode: expect={expect_seccode!r} got={seccode!r}")
            print(f"        calls:   expect={expect_calls} got={FakeClient.calls}")
            print(f"        warns:   expect={expect_warn} got={len(LOGS.warnings)}")

    print()
    checks = [
        ("API 走 https", Config.API_URL == "https://api.geetest.com"),
        ("超时 5 秒", Config.TIMEOUT == 5.0),
        ("重试 3 次", Config.RETRY_TIMES == 3),
        ("请求地址用的是 https", URL.startswith("https://")),
    ]
    for name, passed in checks:
        if passed:
            ok += 1
            print(f"  PASS  {name}")
        else:
            fail += 1
            print(f"  FAIL  {name}")

    print(f"\n== {ok}/{ok + fail} 通过")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
