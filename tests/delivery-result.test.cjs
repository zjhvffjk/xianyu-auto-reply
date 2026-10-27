const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')
const sandbox = {exports: {}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../frontend/src/utils/deliveryResult.ts'), 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText, sandbox)
const {getDeliveryNotice} = sandbox.exports
const result = data => ({success: true, message: '后端完整发货结果', data})

test('successful request with rejected or failed messages is not shown as delivery success', () => {
  for (const data of [{send_intercepted: true}, {send_failed_count: 1}]) {
    const notice = getDeliveryNotice(result(data))
    assert.equal(notice.type, 'error')
    assert.equal(notice.message, '后端完整发货结果')
  }
})
test('partial, degraded and closed-order delivery retain warnings', () => {
  for (const data of [
    {quantity_requested: 3, quantity_sent: 2}, {quantity_degraded_for_dock_card: true},
    {quantity_degraded_for_fixed_content: true}, {early_break_reason: '库存不足'},
    {is_card_only: true}, {skipped_due_to_dock_card: true},
  ]) assert.equal(getDeliveryNotice(result(data)).type, 'warning')
})
test('intentional single-send and card-only mode have accurate severity', () => {
  assert.equal(getDeliveryNotice(result({quantity_requested: 3, quantity_sent: 1, quantity_degraded_for_disabled_switch: true})).type, 'success')
  assert.equal(getDeliveryNotice(result({only_send_card: true})).type, 'info')
  assert.equal(getDeliveryNotice(result({quantity_requested: 1, quantity_sent: 1})).type, 'success')
})
test('business failure preserves actionable reason', () => {
  const notice = getDeliveryNotice({success: false, message: '订单正在被其他发货流程处理'})
  assert.equal(notice.type, 'error')
  assert.equal(notice.message, '订单正在被其他发货流程处理')
})
