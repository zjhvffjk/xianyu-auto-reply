"""单元测试：keyword_service.validate_keyword_max_length 独立验证。

不做数据库/框架依赖，直接从源码 AST 抽出校验函数与常量后 exec。
背景：xy_keyword_rules.keyword 列宽仅 120 字符，线上曾因保存超长多行关键词
触发 mysql DataError 1406（2026-10-22 线上 105 次），保存前必须校验。
"""

import ast
import os

# 相对本文件定位仓库根：tests/ -> 仓库根
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(
    REPO_ROOT, "backend-web", "app", "services", "keyword_service.py"
)

WANT_FUNCS = {"validate_keyword_max_length"}
WANT_CONSTS = {"KEYWORD_MAX_LENGTH"}


def load_namespace():
    tree = ast.parse(open(SRC, encoding="utf-8-sig").read())
    ns = {}
    picked = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name in WANT_FUNCS:
            picked.append(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in WANT_CONSTS:
                    picked.append(node)
    exec(compile(ast.Module(body=picked, type_ignores=[]), SRC, "exec"), ns)
    return ns


NS = load_namespace()
validate = NS["validate_keyword_max_length"]
MAX_LEN = NS["KEYWORD_MAX_LENGTH"]


def test_max_length_is_120():
    """与 xy_keyword_rules.keyword 列宽保持一致。"""
    assert MAX_LEN == 120


def test_empty_and_normal_pass():
    """空串与常规长度不抛异常。"""
    validate("")
    validate("在吗")
    validate("你好\n这个还有货吗")


def test_boundary_120_passes():
    """正好 120 字符（边界值）放行。"""
    validate("啊" * 120)


def test_121_raises_with_hint():
    """121 字符抛 ValueError，且提示里带上限与当前长度。"""
    try:
        validate("啊" * 121)
    except ValueError as exc:
        assert "120" in str(exc)
        assert "121" in str(exc)
        assert "精简" in str(exc)
    else:
        raise AssertionError("121 字符应当抛出 ValueError")


def test_multiline_joined_over_limit():
    """多行关键词拼接后超长（线上真实场景：2026-10-22 报错参数原样）必须被拦下。"""
    lines = [
        "有吗", "在吗", "你好，这个还有货吗", "是我自己的账号吗", "购买后如何使用",
        "尊嘟假嘟", "真的假的", "哈喽", "你这卖的是什么", "真嘟假嘟",
        "多少钱", "什么价", "怎么卖的", "这个怎么领取", "1",
        "你好", "这个要怎么弄", "还有吗", "多少", "在",
        "1分钱？", "直接拍吗？", "怎么兑换", "能用吗", "怎么买",
    ]
    joined = "\n".join(lines)
    assert len(joined) > 120
    try:
        validate(joined)
    except ValueError:
        pass
    else:
        raise AssertionError(f"多行拼接 {len(joined)} 字符应当抛出 ValueError")
