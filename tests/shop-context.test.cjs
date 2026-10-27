const test = require('node:test')
const assert = require('node:assert/strict')
const { createRequire } = require('node:module')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '..')
const frontendRequire = createRequire(path.join(root, 'frontend/package.json'))
const ts = frontendRequire('typescript')
function load(relative) {
  const values = new Map()
  const localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  const sandbox = { exports: {}, localStorage, require: name => name === '@/store/authStore' ? { useAuthStore: () => null } : frontendRequire(name) }
  const code = ts.transpileModule(fs.readFileSync(path.join(root, relative), 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText
  vm.runInNewContext(code, sandbox)
  return sandbox.exports
}

test('shop selection is remembered separately for each signed-in user', () => {
  const { useShopSelections } = load('frontend/src/store/shopStore.ts')
  const store = useShopSelections.getState()
  store.setSelection('user-a', 'account-a', '会员A · 店铺A')
  store.setSelection('user-b', 'account-b', '会员B · 店铺B')
  assert.equal(useShopSelections.getState().selections['user-a'].accountId, 'account-a')
  assert.equal(useShopSelections.getState().selections['user-b'].accountId, 'account-b')
  store.setSelection('user-b', null)
  assert.equal(useShopSelections.getState().selections['user-b'], undefined)
  assert.equal(useShopSelections.getState().selections['user-a'].accountId, 'account-a')
})

test('shop items retain the existing configured and on-sale selection rules', () => {
  const { toShopItemRow, matchShopItemTab, isShopItemOnSale } = load('frontend/src/utils/shopItem.ts')
  const configured = toShopItemRow({item_id:'12345',has_card:true,platform_status:'在售'})
  assert.equal(toShopItemRow({item_id:'12345',item_price:'¥1.01'}).price,'1.01')
  assert.equal(matchShopItemTab(configured,'configured'),true)
  assert.equal(isShopItemOnSale(configured),true)
  assert.equal(isShopItemOnSale(toShopItemRow({item_id:'12345',platform_status:'已下架'})),false)
  assert.equal(isShopItemOnSale(toShopItemRow({item_id:'12345'})),true)
})
