"""单元测试：素材同步价格/库存取值 + 批量定时发布状态机。

覆盖：
1. extract_detail_price_quantity（material_sync_service）：价格优先取卖家后台
   设置价（列表接口 price_text 是小刀后的到手价），库存取真实值，多规格取
   SKU 库存之和；取不到返回 None 由调用方回落。
2. build_publish_queue / advance_after_publish（scheduled_publish_task）：
   队列展开顺序（账号外层）与发布后的状态推进（中间条 running、末条
   completed、失败也推进不阻塞）。
3. 契约层：间隔下限为技术下限 30 秒（scheduler 扫描周期），默认 300 秒，
   低于 5 分钟前端仅警告不拦截；scheduler 已注册新任务码；前端三个 API 已接通。

不依赖数据库与第三方库，仓库根直接 `python tests/test_scheduled_publish.py` 可跑。
"""
import ast
import os
import re
from datetime import datetime, timedelta

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNC_SRC = os.path.join(REPO_ROOT, "backend-web", "app", "services", "material_sync_service.py")
TASK_SRC = os.path.join(REPO_ROOT, "common", "services", "scheduled_publish_task.py")
MODEL_SRC = os.path.join(REPO_ROOT, "common", "models", "scheduled_publish_task.py")
ROUTE_SRC = os.path.join(REPO_ROOT, "backend-web", "app", "api", "routes", "product_publish.py")
API_TS = os.path.join(REPO_ROOT, "frontend", "src", "api", "productPublish.ts")
PAGE_TSX = os.path.join(REPO_ROOT, "frontend", "src", "pages", "product-publish", "BatchPublish.tsx")
SCHEDULER_SRC = os.path.join(REPO_ROOT, "scheduler", "app", "services", "scheduler_service.py")
DOCKERFILE_SRC = os.path.join(REPO_ROOT, "scheduler", "Dockerfile")

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


def load_top_level_functions(path, names):
    """AST 抽出指定名称的顶层函数并真实执行，返回名字 -> 可调用对象的映射。"""
    tree = ast.parse(open(path, encoding="utf-8").read())
    picked = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    found = {node.name for node in picked}
    missing = set(names) - found
    assert not missing, f"{os.path.basename(path)} 缺少函数: {missing}"

    mod = ast.Module(
        body=[
            # 与原模块一致：注解不求值，省去往命名空间塞 typing 对象
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *picked,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(mod)
    ns = {"datetime": datetime, "timedelta": timedelta, "Any": object}
    exec(compile(mod, "<extract>", "exec"), ns)  # noqa: S102 - 仅本地测试
    return {name: ns[name] for name in names}


# ---------- 1. 价格/库存提取 ----------

def test_extract_price_quantity():
    print("\n[1] extract_detail_price_quantity 价格/库存取值")
    fn = load_top_level_functions(SYNC_SRC, ["extract_detail_price_quantity"])["extract_detail_price_quantity"]

    # 实测样本：标价 1 元小刀 0.1 元的商品，详情表单 price=1.0、quantity=9996
    price, qty = fn({"price": 1.0, "quantity": 9996})
    check("单规格：取卖家设置价与真实库存", (price, qty) == (1.0, 9996), f"got {(price, qty)}")

    # 价格两位小数规整
    price, qty = fn({"price": 16.9, "quantity": 18})
    check("价格规整到两位小数", (price, qty) == (16.9, 18), f"got {(price, qty)}")

    # 价格无效 → None（调用方回落快照价）
    for bad in (None, 0, 0.0, -1, "1.0", "", True):
        price, _ = fn({"price": bad, "quantity": 5})
        check(f"价格无效({bad!r}) → None", price is None, f"got {price!r}")

    # 库存无效/售罄 0 → None（调用方回落 1）
    for bad in (None, 0, -3, "5", True):
        _, qty = fn({"price": 1.0, "quantity": bad})
        check(f"库存无效({bad!r}) → None", qty is None, f"got {qty!r}")

    # 多规格：库存取各 SKU 之和
    price, qty = fn({
        "price": 9.9,
        "quantity": 1,
        "sku_rows": [
            {"sku_id": "a", "price": 9.9, "stock": 10},
            {"sku_id": "b", "price": 19.9, "stock": 5},
            {"sku_id": "c", "price": 29.9, "stock": 0},
        ],
    })
    check("多规格：库存=SKU之和(15)，价格=最低SKU价", (price, qty) == (9.9, 15), f"got {(price, qty)}")

    # 多规格但全为 0 库存 → None
    _, qty = fn({"price": 9.9, "sku_rows": [{"stock": 0}, {"stock": 0}]})
    check("多规格全0库存 → None", qty is None, f"got {qty!r}")

    # 空表单 → 全 None
    price, qty = fn({})
    check("空表单 → (None, None)", (price, qty) == (None, None), f"got {(price, qty)}")


# ---------- 2. 队列展开与状态推进 ----------

def test_queue_and_advance():
    print("\n[2] build_publish_queue / advance_after_publish 状态机")
    fns = load_top_level_functions(
        TASK_SRC, ["build_publish_queue", "advance_after_publish"]
    )
    build_queue = fns["build_publish_queue"]
    advance = fns["advance_after_publish"]

    # 队列展开：账号外层，与立即发布语义一致
    queue = build_queue([101, 102, 103], ["accA", "accB"])
    check("2账号×3素材=6条，账号外层", queue == [
        ("accA", 101), ("accA", 102), ("accA", 103),
        ("accB", 101), ("accB", 102), ("accB", 103),
    ], f"got {queue}")

    check("空素材 → 空队列", build_queue([], ["accA"]) == [])
    check("空账号 → 空队列", build_queue([101], []) == [])

    now = datetime(2026, 10, 19, 20, 0, 0)

    # 中间条：推进下标 + running + 下一条时间=now+间隔
    state = advance(next_index=0, queue_len=6, success=True, interval_seconds=300, now=now)
    check("中间条 → running，next_run_at=+5分钟", state == {
        "next_index": 1, "status": "running",
        "next_run_at": now + timedelta(seconds=300),
    }, f"got {state}")

    # 末条：completed，不再排下一次
    state = advance(next_index=5, queue_len=6, success=True, interval_seconds=300, now=now)
    check("末条 → completed，next_run_at=None", state == {
        "next_index": 6, "status": "completed", "next_run_at": None,
    }, f"got {state}")

    # 失败也推进（不阻塞后续队列）
    state = advance(next_index=2, queue_len=6, success=False, interval_seconds=300, now=now)
    check("失败也推进下标", state["next_index"] == 3 and state["status"] == "running", f"got {state}")

    # 间隔下限保护：异常小值按 1 秒处理，不会除以零或负间隔
    state = advance(next_index=0, queue_len=6, success=True, interval_seconds=0, now=now)
    check("间隔0 → 按1秒（不崩）", state["next_run_at"] == now + timedelta(seconds=1), f"got {state}")


# ---------- 3. 契约层 ----------

def test_contracts():
    print("\n[3] 契约：间隔下限=技术下限30秒 + 默认300秒 + 低于5分钟仅警告")

    model_src = open(MODEL_SRC, encoding="utf-8").read()
    check("模型定义 MIN_PUBLISH_INTERVAL_SECONDS = 30（技术下限）",
          "MIN_PUBLISH_INTERVAL_SECONDS = 30" in model_src)
    check("模型定义 DEFAULT_PUBLISH_INTERVAL_SECONDS = 300（默认值）",
          "DEFAULT_PUBLISH_INTERVAL_SECONDS = 300" in model_src)
    check("模型列默认值用 DEFAULT 而非 MIN",
          "default=DEFAULT_PUBLISH_INTERVAL_SECONDS" in model_src)

    route_src = open(ROUTE_SRC, encoding="utf-8").read()
    check("路由 ScheduledPublishRequest 带 ge=MIN_INTERVAL_SECONDS 校验", "ge=MIN_INTERVAL_SECONDS" in route_src)
    check("路由默认值用 DEFAULT_INTERVAL_SECONDS", "DEFAULT_INTERVAL_SECONDS," in route_src)
    check("路由有三个 scheduled 端点", route_src.count("/publish/scheduled") >= 3)

    api_src = open(API_TS, encoding="utf-8").read()
    for fn_name in ("createScheduledPublish", "listScheduledPublish", "cancelScheduledPublish"):
        check(f"前端 api：{fn_name} 已定义", f"export const {fn_name}" in api_src)

    page_src = open(PAGE_TSX, encoding="utf-8").read()
    check("前端页面：MIN_INTERVAL_MINUTES = 0.5（技术下限）", "MIN_INTERVAL_MINUTES = 0.5" in page_src)
    check("前端页面：DEFAULT_INTERVAL_MINUTES = 5（默认值）", "DEFAULT_INTERVAL_MINUTES = 5" in page_src)
    check("前端页面：RISK_WARNING_MINUTES = 5（警告阈值）", "RISK_WARNING_MINUTES = 5" in page_src)
    check("前端页面：间隔输入 min 为技术下限", "min={MIN_INTERVAL_MINUTES}" in page_src)
    check("前端页面：低于阈值时显示风控警告（不拦截）",
          "text-amber-500" in page_src and "触发平台风控" in page_src)
    check("前端页面：提交时只拦截技术下限以下的间隔",
          "intervalMinutes < MIN_INTERVAL_MINUTES" in page_src)
    check("前端页面：定时模式调 createScheduledPublish", "createScheduledPublish({" in page_src)
    check("前端页面：任务列表有取消按钮", "handleCancelScheduled" in page_src)

    scheduler_src = open(SCHEDULER_SRC, encoding="utf-8").read()
    check("scheduler 注册了定时发布循环", "_run_scheduled_publish_loop" in scheduler_src)
    check("scheduler 导入了 TASK_CODE_SCHEDULED_PUBLISH", "TASK_CODE_SCHEDULED_PUBLISH" in scheduler_src)

    task_src = open(TASK_SRC, encoding="utf-8").read()
    check("执行器只查 pending/running（cancelled 天然不再执行）",
          '"pending", "running"' in task_src)
    check("执行器有分布式锁（防多实例重复发）", "distributed_lock" in task_src)

    # scheduler 容器里必须带 backend-web 源码：发布执行经
    # common/services/backend_web_loader.py 按仓库相对路径动态加载 backend-web
    # 模块（如 publish_account_capability_service.py），缺这份代码定时发布
    # 会报「未找到 backend-web 模块文件」（曾因此全部发布失败）
    dockerfile_src = open(DOCKERFILE_SRC, encoding="utf-8").read()
    check("scheduler Dockerfile 复制了 backend-web（loader 依赖）",
          re.search(r"^COPY backend-web /app/backend-web$", dockerfile_src, re.M) is not None)


def main():
    test_extract_price_quantity()
    test_queue_and_advance()
    test_contracts()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
