"""单元测试：Token 刷新风控退避（websocket token_manager）。

背景：上游原版对单次刷新流程内的滑块重试有上限（max_captcha_verification_count=3），
但刷新周期之间没有退避——账号被平台长时间风控时（实测持续 5 小时、330+ 次空撞），
仍按正常间隔（默认 3 分钟）高频重试，无谓加重风控。本模块在周期层加指数退避：
连续风控失败 → 5/15/30 分钟阶梯；刷新成功即恢复正常；非风控失败不累计。

覆盖两层：
1. 纯函数：risk_backoff_interval 阶梯与封顶、RISK_FAIL_STATUSES 成员判定。
2. 行为层：AST 抽出 TokenManager._apply_refresh_outcome，注入假 self，
   验证累计/重置/非风控不累计。
3. 契约层：_execute_cookie_refresh 的三个分支均已接入退避判断。

不依赖数据库与第三方服务，仓库根直接 `python tests/test_token_risk_backoff.py` 可跑。
"""

import ast
import os
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(
    REPO_ROOT, "websocket", "app", "services", "xianyu", "token_manager.py"
)

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}" + (f" —— {detail}" if detail else ""))


# ---------- 1. 纯函数 ----------

def test_backoff_function():
    print("\n[1] risk_backoff_interval 阶梯与封顶")
    ns = {}
    src = open(SRC, encoding="utf-8-sig").read()
    # 只编译模块级常量与纯函数（避开 asyncio/loguru 依赖）
    tree = ast.parse(src)
    picks = {"RISK_FAIL_STATUSES", "RISK_BACKOFF_STEPS", "risk_backoff_interval"}
    nodes = [
        n for n in tree.body
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in picks)
        or (isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in picks for t in n.targets
        ))
    ]
    mod = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, "<extract>", "exec"), ns)  # noqa: S102 - 仅本地测试

    fn = ns["risk_backoff_interval"]
    check("0 → 0（无退避）", fn(0) == 0, f"got {fn(0)}")
    check("负数 → 0", fn(-3) == 0, f"got {fn(-3)}")
    check("第 1 次失败 → 300 秒（5 分钟）", fn(1) == 300, f"got {fn(1)}")
    check("第 2 次失败 → 900 秒（15 分钟）", fn(2) == 900, f"got {fn(2)}")
    check("第 3 次失败 → 1800 秒（30 分钟）", fn(3) == 1800, f"got {fn(3)}")
    check("第 10 次仍封顶 1800", fn(10) == 1800, f"got {fn(10)}")

    steps = ns["RISK_BACKOFF_STEPS"]
    check("阶梯为 (300, 900, 1800)", tuple(steps) == (300, 900, 1800), f"got {steps}")

    statuses = ns["RISK_FAIL_STATUSES"]
    for s in (
        "failed_captcha_max_retries",
        "failed_captcha",
        "failed_captcha_exception",
        "failed_risk_log_create",
        "skipped_risk_control_processing",
        "skipped_risk_control_check_failed",
        "skipped_local_slider_disabled",
        "skipped_local_slider_config_unavailable",
    ):
        check(f"风控状态 {s} 命中退避", s in statuses)
    for s in ("failed_network", "failed_timeout", "failed_api", "skipped_startup_cache_lookup_failed"):
        check(f"非风控状态 {s} 不触发退避", s not in statuses)


# ---------- 2. 行为层 ----------

class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.infos = []

    def warning(self, msg, *args):
        self.warnings.append(str(msg))

    def info(self, msg, *args):
        self.infos.append(str(msg))


def load_apply_outcome():
    """抽出顶层常量/纯函数 + _apply_refresh_outcome 方法，注入假符号后编译执行。"""
    src = open(SRC, encoding="utf-8-sig").read()
    tree = ast.parse(src)
    picks = {"RISK_FAIL_STATUSES", "RISK_BACKOFF_STEPS", "risk_backoff_interval"}
    top_nodes = [
        n for n in tree.body
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in picks)
        or (isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in picks for t in n.targets
        ))
    ]
    cls = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "TokenManager"
    )
    fn = next(
        n for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "_apply_refresh_outcome"
    )
    mod = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *top_nodes,
            fn,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(mod)
    ns = {"logger": FakeLogger()}
    exec(compile(mod, "<extract>", "exec"), ns)  # noqa: S102 - 仅本地测试
    return ns["_apply_refresh_outcome"], ns["logger"]


def make_self(interval=180):
    """假 TokenManager：只保留退避逻辑触及的属性。"""
    return types.SimpleNamespace(
        cookie_id="TESTACC",
        cookie_refresh_interval=interval,
        normal_cookie_refresh_interval=interval,
        risk_fail_streak=0,
    )


def test_apply_outcome():
    print("\n[2] _apply_refresh_outcome：累计 / 阶梯 / 重置 / 非风控不累计")
    apply_outcome, fake_logger = load_apply_outcome()

    # 连续三次风控失败：间隔 180 → 300 → 900 → 1800
    self = make_self()
    apply_outcome(self, succeeded=False, status="failed_captcha_max_retries")
    check("第 1 次风控：streak=1，间隔 300", self.risk_fail_streak == 1 and self.cookie_refresh_interval == 300,
          f"got streak={self.risk_fail_streak} interval={self.cookie_refresh_interval}")
    apply_outcome(self, succeeded=False, status="failed_captcha")
    check("第 2 次风控：streak=2，间隔 900", self.risk_fail_streak == 2 and self.cookie_refresh_interval == 900,
          f"got streak={self.risk_fail_streak} interval={self.cookie_refresh_interval}")
    apply_outcome(self, succeeded=False, status="skipped_risk_control_processing")
    check("第 3 次风控：streak=3，间隔 1800", self.risk_fail_streak == 3 and self.cookie_refresh_interval == 1800,
          f"got streak={self.risk_fail_streak} interval={self.cookie_refresh_interval}")
    check("有风控警告日志", any("退避" in m for m in fake_logger.warnings))

    # 第 4 次封顶
    apply_outcome(self, succeeded=False, status="failed_captcha")
    check("第 4 次仍封顶 1800", self.cookie_refresh_interval == 1800,
          f"got {self.cookie_refresh_interval}")

    # 成功一次：立即恢复正常
    apply_outcome(self, succeeded=True, status="success")
    check("成功后 streak 归零", self.risk_fail_streak == 0, f"got {self.risk_fail_streak}")
    check("成功后间隔恢复 180", self.cookie_refresh_interval == 180,
          f"got {self.cookie_refresh_interval}")
    check("有退避解除日志", any("退避解除" in m for m in fake_logger.infos))

    # 非风控失败不累计、不改间隔
    self2 = make_self()
    apply_outcome(self2, succeeded=False, status="failed_network")
    check("网络失败不累计 streak", self2.risk_fail_streak == 0, f"got {self2.risk_fail_streak}")
    check("网络失败间隔不变", self2.cookie_refresh_interval == 180,
          f"got {self2.cookie_refresh_interval}")
    apply_outcome(self2, succeeded=False, status="failed_timeout")
    apply_outcome(self2, succeeded=False, status="failed_api")
    check("连续网络失败仍不退避", self2.cookie_refresh_interval == 180,
          f"got {self2.cookie_refresh_interval}")

    # 无风控历史时成功：不打解除日志（避免噪声）
    self3 = make_self()
    apply_outcome(self3, succeeded=True, status="success")
    check("无风控历史时静默重置", self3.risk_fail_streak == 0 and self3.cookie_refresh_interval == 180)


# ---------- 3. 契约层 ----------

def test_contracts():
    print("\n[3] 契约：_execute_cookie_refresh 各分支已接入退避")
    src = open(SRC, encoding="utf-8-sig").read()

    # _execute_cookie_refresh 内应有 4 处 _apply_refresh_outcome 调用
    tree = ast.parse(src)
    cls = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "TokenManager"
    )
    fn = next(
        n for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "_execute_cookie_refresh"
    )
    call_count = sum(
        1 for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_apply_refresh_outcome"
    )
    check("_execute_cookie_refresh 接入 4 处退避调用（成功/skipped/重试成功/重试失败）",
          call_count == 4, f"got {call_count}")

    check("上游核心逻辑未改动：refresh_token 仍由 xianyu 提供",
          "await self.xianyu.refresh_token()" in src)
    check("本文件不重复定义上游的单次滑块上限（仍由 xianyu_async 管）",
          "max_captcha_verification_count =" not in src)
    check("正常间隔有备份字段（退避恢复用）",
          "normal_cookie_refresh_interval" in src)


def main():
    test_backoff_function()
    test_apply_outcome()
    test_contracts()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
