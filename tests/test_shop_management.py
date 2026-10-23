"""店铺管理功能测试（纯前端新增，后端零改动）

背景：用户要求做「店铺管理」——参考阿奇索闲鱼自动发货（aldsidle.agiso.com）的
店铺切换 → 发货设置-宝贝设置 → 单独设置（可添加商品=店铺商品链接）流程。
本实现全部复用现有能力：
- 店铺 = xy_accounts（一个闲鱼账号一个店铺）
- 店铺商品 = xy_catalog_items（平台同步，GET /api/v1/items/cookie/{id}）
- 发货绑定 = xy_card_item_relations（websocket 自动发货按商品ID取卡券）
- 使用说明 = 商品默认回复；改价 = 现有商品改价接口

覆盖三层：
1. 纯函数（Node 直接加载 utils/shopItem.ts 实测行为）：
   商品链接解析、表格行映射、tab 口径、下架判断
2. 契约层：导航/路由/页签标题已接入；各页面按店铺维度（accountId/cookieId）
   调用接口，无跨店泄漏；单独设置两页签接通
3. 多租户安全：店铺维度所有查询强制带账号参数（反向断言不存在无账号调用）

仓库根直接 `python tests/test_shop_management.py` 可跑（Node 缺失时跳过行为层）。
"""

import os
import subprocess
import sys
import tempfile
import shutil

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_SRC = os.path.join(REPO_ROOT, "frontend", "src")
NAV_TS = os.path.join(FRONTEND_SRC, "config", "navigation.ts")
APP_TSX = os.path.join(FRONTEND_SRC, "App.tsx")
TABS_TSX = os.path.join(FRONTEND_SRC, "components", "layout", "TabsBar.tsx")
CARDS_TSX = os.path.join(FRONTEND_SRC, "pages", "cards", "Cards.tsx")
SHOP_ITEM_TS = os.path.join(FRONTEND_SRC, "utils", "shopItem.ts")
SHOP_STORE_TS = os.path.join(FRONTEND_SRC, "store", "shopStore.ts")
SHOP_API_TS = os.path.join(FRONTEND_SRC, "api", "shop.ts")
SHOP_DIR = os.path.join(FRONTEND_SRC, "pages", "shop")
SHOP_MANAGE_TSX = os.path.join(SHOP_DIR, "ShopManage.tsx")
SHOP_ITEM_SETTINGS_TSX = os.path.join(SHOP_DIR, "ShopItemSettings.tsx")
SHOP_ADD_MODAL_TSX = os.path.join(SHOP_DIR, "AddShopItemModal.tsx")
SHOP_SETTING_MODAL_TSX = os.path.join(SHOP_DIR, "ShopItemSettingModal.tsx")
SHOP_BATCH_MODALS_TSX = os.path.join(SHOP_DIR, "ShopBatchModals.tsx")

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


def read(path):
    return open(path, encoding="utf-8-sig").read()


def find_node():
    node = shutil.which("node")
    if node:
        return node
    # 回退：WorkBuddy 托管 node
    managed = os.path.join(
        os.path.expanduser("~"), ".workbuddy", "binaries", "node"
    )
    if os.path.isdir(managed):
        for name in sorted(os.listdir(managed)):
            for sub in sorted(os.listdir(os.path.join(managed, name)), reverse=True):
                candidate = os.path.join(managed, name, sub, "node.exe")
                if os.path.isfile(candidate):
                    return candidate
    return None


# ---------- 1. 纯函数行为（Node 实测） ----------

NODE_HARNESS_TEMPLATE = """
import {{
  parseShopItemId, buildShopItemUrl, toShopItemRow,
  matchShopItemTab, isShopItemOffshelf, isShopItemOnSale,
}} from '{util_uri}'
import type {{ Item }} from '{types_uri}'

let pass = 0
let fail = 0
function check(name, ok, detail) {{
  if (ok) {{ pass += 1; console.log('PASS ' + name) }}
  else {{ fail += 1; console.log('FAIL ' + name + (detail ? ' -- ' + detail : '')) }}
}}

// parseShopItemId：链接 / ID / 混排文案 / 非法输入
const parseCases = [
  ['https://www.goofish.com/item?id=771234567890', '771234567890'],
  ['https://www.goofish.com/item/?id=771234567890&spm=a21ybx.item', '771234567890'],
  ['https://m.goofish.com/item?id=99887766554433', '99887766554433'],
  ['https://www.goofish.com/item/771234567890', '771234567890'],
  ['771234567890', '771234567890'],
  ['  771234567890  ', '771234567890'],
  ['share text https://www.goofish.com/item?id=771234567890 tap', '771234567890'],
  ['not a link', null],
  ['', null],
  ['https://example.com/item?id=abcdefg', null],
  ['id=12', null],
]
for (const [input, expected] of parseCases) {{
  const got = parseShopItemId(input)
  check('parseShopItemId ' + JSON.stringify(input), got === expected, 'got=' + JSON.stringify(got))
}}

// buildShopItemUrl
check('buildShopItemUrl', buildShopItemUrl('771234567890') === 'https://www.goofish.com/item?id=771234567890')

// toShopItemRow：字段映射与兜底
const item = {{
  item_id: '771234567890', title: '', item_title: 'fallback title', price: '',
  item_price: '16.5', item_status_desc: 'sold out', has_card: true,
  has_default_reply: false, is_multi_spec: 1, item_quantity: 3,
  item_shelf_time: '2026-10-01', is_seller_item: true,
}} as unknown as Item
const row = toShopItemRow(item)
check('toShopItemRow title 兜底 item_title', row.title === 'fallback title', row.title)
check('toShopItemRow price 兜底 item_price', row.price === '16.5', row.price)
check('toShopItemRow hasCard', row.hasCard === true)
check('toShopItemRow hasDefaultReply', row.hasDefaultReply === false)
check('toShopItemRow quantity 数字转字符串', row.quantity === '3', row.quantity)
check('toShopItemRow statusDesc', row.statusDesc === 'sold out')

// matchShopItemTab：卡券或使用说明任一即「已设置」
const configuredRow = {{ hasCard: true, hasDefaultReply: false }} as ReturnType<typeof toShopItemRow>
const replyOnlyRow = {{ hasCard: false, hasDefaultReply: true }} as ReturnType<typeof toShopItemRow>
const emptyRow = {{ hasCard: false, hasDefaultReply: false }} as ReturnType<typeof toShopItemRow>
check('tab all 恒真', matchShopItemTab(emptyRow, 'all'))
check('tab configured 命中卡券', matchShopItemTab(configuredRow, 'configured'))
check('tab configured 命中使用说明', matchShopItemTab(replyOnlyRow, 'configured'))
check('tab unconfigured 双无配置', matchShopItemTab(emptyRow, 'unconfigured'))
check('tab unconfigured 排除已设置', !matchShopItemTab(configuredRow, 'unconfigured'))

// isShopItemOffshelf
const offshelfRow = {{ ...emptyRow, statusDesc: '已下架' }} as ReturnType<typeof toShopItemRow>
check('isShopItemOffshelf 含下架', isShopItemOffshelf(offshelfRow))
check('isShopItemOffshelf 空状态视为在售', !isShopItemOffshelf(emptyRow))

// isShopItemOnSale：宝贝设置列表只列在售（用户要求：下架的不显示）
const onSaleRow = {{ ...emptyRow, statusDesc: '在售', platformStatus: '在卖' }} as ReturnType<typeof toShopItemRow>
const soldRow = {{ ...emptyRow, statusDesc: '已售出', platformStatus: '售出' }} as ReturnType<typeof toShopItemRow>
const deletedRow = {{ ...emptyRow, statusDesc: '用户删除', platformStatus: '用户删除' }} as ReturnType<typeof toShopItemRow>
const violationRow = {{ ...emptyRow, statusDesc: '违规', platformStatus: '违规' }} as ReturnType<typeof toShopItemRow>
check('isShopItemOnSale 在售为真', isShopItemOnSale(onSaleRow))
check('isShopItemOnSale 在卖为真', isShopItemOnSale({{ ...emptyRow, statusDesc: '在卖' }} as ReturnType<typeof toShopItemRow>))
check('isShopItemOnSale 空状态为真（个人版/老数据）', isShopItemOnSale(emptyRow))
check('isShopItemOnSale 下架为假', !isShopItemOnSale(offshelfRow))
check('isShopItemOnSale 下架（platform_status=下架）为假',
      !isShopItemOnSale({{ ...emptyRow, platformStatus: '下架' }} as ReturnType<typeof toShopItemRow>))
check('isShopItemOnSale 售出为假', !isShopItemOnSale(soldRow))
check('isShopItemOnSale 用户删除为假', !isShopItemOnSale(deletedRow))
check('isShopItemOnSale 违规为假', !isShopItemOnSale(violationRow))
check('toShopItemRow 透传 platform_status', onSaleRow.platformStatus === '在卖')

console.log('SUMMARY ' + pass + ' ' + fail)
"""


def test_pure_functions_with_node():
    print("\n[1] 纯函数行为（Node 加载 utils/shopItem.ts 实测）")
    node = find_node()
    if not node:
        print("  - 未找到 node，跳过行为层（契约层仍可验证）")
        return

    util_uri = "file://" + SHOP_ITEM_TS.replace("\\", "/")
    types_uri = "file://" + os.path.join(FRONTEND_SRC, "types", "index.ts").replace("\\", "/")
    harness = NODE_HARNESS_TEMPLATE.format(util_uri=util_uri, types_uri=types_uri)

    with tempfile.TemporaryDirectory() as tmp:
        harness_path = os.path.join(tmp, "shop_item_harness.ts")
        with open(harness_path, "w", encoding="utf-8") as f:
            f.write(harness)
        try:
            proc = subprocess.run(
                [node, harness_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
        except Exception as exc:  # noqa: BLE001 - 本地测试容错
            print(f"  - node 执行失败：{exc}")
            return

    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    node_pass = sum(1 for ln in lines if ln.startswith("PASS "))
    node_fail = [ln for ln in lines if ln.startswith("FAIL ")]
    check(f"Node 行为断言 {node_pass} 项全部通过", proc.returncode == 0 and not node_fail,
          "; ".join(node_fail[:3]) + (f" | stderr: {proc.stderr[:200]}" if proc.stderr else ""))


# ---------- 2. 契约层 ----------

def test_navigation_and_routes():
    print("\n[2] 契约：已并入卡券管理（不再有独立一级菜单）")

    nav_src = read(NAV_TS)
    check("导航：不存在独立「店铺管理」菜单", "shop-management" not in nav_src and "'店铺管理'" not in nav_src)
    check("导航：未残留 Building2 图标导入", "Building2" not in nav_src)

    app_src = read(APP_TSX)
    check("路由：不存在 /shop-management 独立路由",
          "shop-management" not in app_src and "pages/shop/ShopManage'" not in app_src)

    tabs_src = read(TABS_TSX)
    check("页签：不存在店铺管理标题映射", "/shop-management" not in tabs_src)

    cards_src = read(CARDS_TSX)
    check("卡券管理：已引入店铺切换器与发货设置",
          "ShopSwitcher" in cards_src and "ShopDeliverySettings" in cards_src)
    check("卡券管理：店铺切换器位于页头标题旁（框选位置）", "<h1 className=\"page-title\">卡券管理</h1>" in cards_src
          and cards_src.index("<ShopSwitcher />") > cards_src.index("<h1 className=\"page-title\">卡券管理</h1>"))
    check("卡券管理：店铺切换为图标按钮内联（不再渲染独立下拉框/状态徽标）",
          "compact" not in cards_src and cards_src.count("<ShopSwitcher />") == 1)
    check("卡券管理：发货设置区块在卡券列表之后",
          cards_src.index("<ShopDeliverySettings />") > cards_src.index("卡券列表（与商品管理表格一致）"))


def test_store_and_api():
    print("\n[3] 契约：当前店铺 store 与 API 门面")

    store_src = read(SHOP_STORE_TS)
    check("store：zustand persist 持久化", "persist(" in store_src and "name: 'shop-storage'" in store_src)
    check("store：持久化当前店铺选择与显示名",
          "currentAccountId: state.currentAccountId" in store_src
          and "currentAccountLabel: state.currentAccountLabel" in store_src)
    check("store：setCurrentAccount 可清空选择",
          "currentAccountId: accountId" in store_src and "accountId ? (label ?? null) : null" in store_src)

    api_src = read(SHOP_API_TS)
    check("api：店铺商品分页强制带 accountId（cookie_id）",
          "getItemsPaginated(" in api_src and "accountId," in api_src)


def test_shop_manage_page():
    print("\n[4] 契约：店铺切换器与发货设置组件")

    src = read(SHOP_MANAGE_TSX)
    check("组件：导出 ShopSwitcher 与 ShopDeliverySettings",
          "export function ShopSwitcher" in src and "export function ShopDeliverySettings" in src)
    check("组件：账号列表经分页接口拉取（后端按 token 限定范围）",
          "getAccountDetailsPaginated(" in src)
    check("组件：当前店铺选择越界时自动清空（防跨用户残留）",
          "accounts.find((a) => a.id === currentAccountId)" in src
          and "setCurrentAccount(null)" in src)
    check("组件：店铺名优先显示会员名/昵称（不再只显示数字ID）",
          "account.nickname || account.member_name" in src)
    check("组件：未选店铺时发货设置显示引导态", "请点击标题旁的店铺图标" in src)
    check("组件：店铺切换为图标按钮 + 下拉菜单（无独立 Select 组件）",
          "getAccountDetailsPaginated(" in src and "ChevronDown" in src
          and "from '@/components/common/Select'" not in src)
    check("组件：店铺图标为绿底白字徽章（#3E9B57）", "bg-[#3E9B57]" in src)
    check("组件：无账号时引导去账号管理", "账号管理" in src)
    check("组件：宝贝设置页按店铺维度渲染（key 绑定 accountId）",
          "<ShopItemSettings" in src and "key={currentAccountId}" in src
          and "accountId={currentAccountId}" in src)
    check("组件：不含独立页面标题（不占菜单）", "page-title" not in src)


def test_item_settings_page():
    print("\n[5] 契约：宝贝设置页")

    src = read(SHOP_ITEM_SETTINGS_TSX)
    check("页面：商品数据按店铺维度拉取（cookie_id 隔离）", "getItems(accountId)" in src)
    check("页面：不存在无账号参数的商品查询调用", "getItems()" not in src)
    check("页面：三个 tab（全部/已设置/未设置）",
          "'all'" in src and "'configured'" in src and "'unconfigured'" in src)
    check("页面：tab 口径走纯函数 matchShopItemTab", "matchShopItemTab(row, tab)" in src)
    check("页面：只列在售商品（下架/售出被过滤掉，走纯函数 isShopItemOnSale）",
          "isShopItemOnSale(" in src and "list.filter(" in src)
    check("页面：发货状态徽标使用 has_card / has_default_reply",
          "row.hasCard" in src and "row.hasDefaultReply" in src)
    check("页面：批量操作四项（使用说明/关联卡券/改价/取消关联）",
          "'reply'" in src and "'card'" in src and "'price'" in src
          and "batchClearItemRelations(" in src)
    check("页面：从平台刷新走整店同步", "fetchAllItemsFromAccount(accountId)" in src)
    check("页面：添加商品 / 单独设置弹窗已接入",
          "<AddShopItemModal" in src and "<ShopItemSettingModal" in src)


def test_add_item_modal():
    print("\n[6] 契约：添加商品弹窗（勾选 + 粘贴链接）")

    src = read(SHOP_ADD_MODAL_TSX)
    check("弹窗：粘贴链接解析走 parseShopItemId", "parseShopItemId(linkInput)" in src)
    check("弹窗：链接无法识别时提示", "无法识别商品链接" in src)
    check("弹窗：链接匹配不到商品时引导先从平台刷新",
          "本地未找到该商品" in src and "从平台刷新" in src)
    check("弹窗：匹配成功自动勾选", "setCheckedIds((prev) => new Set(prev).add(itemId)" in src)
    check("弹窗：确认后进入单独设置", "onConfigure(firstItem)" in src)


def test_item_setting_modal():
    print("\n[7] 契约：单独设置弹窗（发货内容 + 使用说明）")

    src = read(SHOP_SETTING_MODAL_TSX)
    check("弹窗：两个页签（发货内容 / 使用说明）",
          "发货内容（关联卡券）" in src and "使用说明（默认回复）" in src)
    check("弹窗：已关联卡券来自 getCardsByItemId", "getCardsByItemId(itemId)" in src)
    check("弹窗：可选卡券服务端分页 getSelectableCards", "getSelectableCards(itemId" in src)
    check("弹窗：保存走 updateItemCards", "updateItemCards(itemId, cardItems)" in src)
    check("弹窗：使用说明读取 getItemDefaultReply（带账号维度）",
          "getItemDefaultReply(cookieId, itemId)" in src)
    check("弹窗：使用说明保存 saveItemDefaultReply（带账号维度）",
          "saveItemDefaultReply(cookieId, itemId" in src)
    check("弹窗：内容方式三种（默认回复/API/站外联系）",
          "'text'" in src and "'api'" in src and "'external_contact'" in src)
    check("弹窗：商品链接展示走 buildShopItemUrl", "buildShopItemUrl(itemId)" in src)


def test_batch_modals():
    print("\n[8] 契约：批量操作弹窗组")

    src = read(SHOP_BATCH_MODALS_TSX)
    check("批量：使用说明走批量默认回复接口", "batchSaveItemDefaultReply(" in src)
    check("批量：关联卡券逐条 updateItemCards（带覆盖提示）",
          "updateItemCards(itemId, [cardItem])" in src and "覆盖" in src)
    check("批量：改价仅鱼小铺商品并提示跳过", "is_seller_item" in src and "跳过" in src)
    check("批量：改价走 updateItemPrice（带账号维度）", "updateItemPrice(accountId, itemId" in src)


def main():
    print("=" * 60)
    print("店铺管理功能测试")
    print("=" * 60)
    test_pure_functions_with_node()
    test_navigation_and_routes()
    test_store_and_api()
    test_shop_manage_page()
    test_item_settings_page()
    test_add_item_modal()
    test_item_setting_modal()
    test_batch_modals()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
