const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
const ts = require('../frontend/node_modules/typescript')

function client(result) {
  const calls = []
  const send = (...args) => { calls.push(args); return Promise.resolve(result) }
  const source = fs.readFileSync(path.join(__dirname, '../frontend/src/api/waybills.ts'), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const module = { exports: {} }
  vm.runInNewContext(code, { module, exports: module.exports, require: name => {
    assert.equal(name, '@/utils/request')
    return { get: send, put: send, post: send, del: send }
  } })
  return { api: module.exports, calls }
}

test('HTTP200业务失败在全部打单入口抛出原业务提示，不返回null数据', async () => {
  const { api } = client({ success: false, code: 409, message: '应用尚未开通', data: null })
  for (const operation of [() => api.getWaybillSettings('s'), () => api.saveWaybillSettings('s', {}),
    () => api.getWaybillTemplates('s'), () => api.previewWaybills('s', ['1']),
    () => api.syncWaybill('s', '1', {}), () => api.numberWaybill('s', '1', 't'),
    () => api.getWaybillWorkbench('s'), () => api.getWaybillRecords('s')]) {
    await assert.rejects(operation, /应用尚未开通/)
  }
})

test('打单记录条数和页码确实传入后端请求', async () => {
  for (const size of [10, 20, 50, 100]) {
    const { api, calls } = client({ success: true, data: { items: [], total: 0 } })
    await api.getWaybillRecords('shop', 3, size)
    assert.equal(calls[0][1].params.page, 3)
    assert.equal(calls[0][1].params.page_size, size)
  }
})

test('空模板列表是有效数据，缺失data不是成功', async () => {
  const good = client({ success: true, data: [] })
  assert.equal((await good.api.getWaybillTemplates('shop')).data.length, 0)
  const bad = client({ success: true, data: null })
  await assert.rejects(() => bad.api.getWaybillTemplates('shop'), /未完成/)
})

test('店铺标识作为URL路径编码，订单号只放请求体', async () => {
  const { api, calls } = client({ success: true, data: {} })
  await api.syncWaybill('shop/other?x=1', 'order-123', { name: '测试' })
  assert.equal(calls[0][0], '/api/v1/waybills/shop%2Fother%3Fx%3D1/sync')
  assert.equal(calls[0][1].order_no, 'order-123')
})

test('管理员平台配置使用统一入口，并传播业务失败', async () => {
  const good = client({ success: true, data: { configured: false } })
  await good.api.getWaybillPlatformConfig()
  await good.api.saveWaybillPlatformConfig({ app_key: 'platform', app_secret: 'test-only' })
  assert.equal(good.calls[0][0], '/api/v1/waybills/platform/config')
  assert.equal(good.calls[1][0], '/api/v1/waybills/platform/config')
  assert.equal(good.calls[1][1].app_key, 'platform')
  const bad = client({ success: false, data: null, message: '只有管理员可以配置' })
  await assert.rejects(() => bad.api.getWaybillPlatformConfig(), /只有管理员/)
  await assert.rejects(() => bad.api.saveWaybillPlatformConfig({}), /只有管理员/)
})

test('店铺授权状态、发起和撤销按店铺编码，业务失败不得显示授权成功', async () => {
  const good = client({ success: true, data: { status: 'pending' } })
  await good.api.getWaybillAuthorization('shop/other?x=1')
  await good.api.startWaybillAuthorization('shop/other?x=1')
  await good.api.revokeWaybillAuthorization('shop/other?x=1')
  assert.equal(good.calls.length, 3)
  assert.ok(good.calls.every(c => c[0] === '/api/v1/waybills/shop%2Fother%3Fx%3D1/authorization'))
  const bad = client({ success: false, data: null, message: '平台应用审核未完成' })
  for (const name of ['getWaybillAuthorization', 'startWaybillAuthorization', 'revokeWaybillAuthorization']) {
    await assert.rejects(() => bad.api[name]('shop'), /审核未完成/)
  }
})
