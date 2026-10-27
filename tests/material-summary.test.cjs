const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')
const sandbox = {exports: {}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../frontend/src/utils/materialSummary.ts'), 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText, sandbox)
const {getMaterialImage, getMissingMaterialFields} = sandbox.exports
const complete = {title: '商品', description: '描述', images: ['/static/uploads/example.png'], price: 1, quantity: 0, platform_category_id: '123', platform_channel_category_id: '456', condition: '99新'}

test('zero stock is complete; actual absent condition/category remain visible', () => {
  assert.equal(getMissingMaterialFields(complete).length, 0)
  assert.deepEqual(Array.from(getMissingMaterialFields({...complete, condition: '', platform_channel_category_id: null})), ['平台类目', '成色'])
})
test('missing content is listed without replacing the original material', () => {
  const material = {...complete, description: ' ', images: [], quantity: null, price: 0}
  assert.deepEqual(Array.from(getMissingMaterialFields(material)), ['描述', '图片', '售价', '库存'])
  assert.equal(material.description, ' ')
  assert.equal(material.quantity, null)
})
test('image selection accepts uploaded/remote images and rejects unsafe schemes', () => {
  assert.equal(getMaterialImage(['javascript:alert(1)', '//example.com/a.png']), 'https://example.com/a.png')
  assert.equal(getMaterialImage(['/static/uploads/a.png']), '/static/uploads/a.png')
  assert.equal(getMaterialImage(['data:text/html,test']), '')
})
