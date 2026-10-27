const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')
const sandbox = { exports: {} }
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../frontend/src/pages/product-publish/publishTypes.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, sandbox)
const { materialToForm, buildSkuKey, PUBLISH_DESCRIPTION_LIMIT, MATERIAL_DESCRIPTION_LIMIT } = sandbox.exports

test('material import preserves zero stock, original price zero and unknown condition', () => {
  const form = materialToForm({ quantity: 0, original_price: 0, condition: '', price: 1.01 })
  assert.equal(form.quantity, 0)
  assert.equal(form.original_price, '0')
  assert.equal(form.condition, '')
  assert.equal(form.price, '1.01')
  assert.equal(materialToForm().quantity, 1)
  assert.equal(materialToForm().condition, '')
})

test('imported two-dimensional SKU keys match editor combinations and retain prices and zero stock', () => {
  const form = materialToForm({
    specifications: [
      { name: '颜色', support_image: true, values: [{ name: '红', image: '/static/red.png' }, { name: '蓝' }] },
      { name: '尺码', values: [{ name: 'S' }] },
    ],
    sku_rows: [
      { specs: { 尺码: 'S', 颜色: '红' }, price: 1.01, stock: 0 },
      { specs: { 颜色: '蓝', 尺码: 'S' }, price: 2, stock: 9 },
    ],
  })
  const previous = new Map(form.sku_rows.map(row => [row.key, row]))
  assert.equal(previous.get(buildSkuKey(form.specifications, { 颜色: '红', 尺码: 'S' })).stock, '0')
  assert.equal(previous.get('颜色:蓝|尺码:S').price, '2')
  assert.equal(form.specifications[0].values[0].image, '/static/red.png')
  assert.equal(form.specifications[0].supportImage, true)
})

test('opening another material rebuilds SKU values without retaining previous prices or mutating source', () => {
  const material = { specifications: [{ name: '份数', values: [{ name: '一份' }] }], sku_rows: [{ specs: { 份数: '一份' }, price: 1, stock: 0 }] }
  const first = materialToForm(material)
  const second = materialToForm({ ...material, sku_rows: [{ specs: { 份数: '一份' }, price: 3, stock: 5 }] })
  assert.equal(first.sku_rows[0].stock, '0')
  assert.equal(second.sku_rows[0].price, '3')
  second.sku_rows[0].specs.份数 = '两份'
  assert.equal(material.sku_rows[0].specs.份数, '一份')
})

test('saved category, attributes, video and shipping survive material conversion', () => {
  const material = { platform_category_id: '123', platform_channel_category_id: '456', platform_attributes: [{ property_id: '20879', value_name: '99新' }], platform_category_path: [{ id: '123', name: '游戏' }], condition: '99新', shipping_method: 'template', address: '测试地址', videos: [{ url: '/static/test.mp4' }] }
  const form = materialToForm(material)
  for (const key of Object.keys(material)) assert.deepEqual(form[key], material[key])
})

test('material and publish share 1500-character limit while imported historical text stays intact', () => {
  assert.equal(MATERIAL_DESCRIPTION_LIMIT, 1500)
  assert.equal(PUBLISH_DESCRIPTION_LIMIT, MATERIAL_DESCRIPTION_LIMIT)
  const description = '测'.repeat(1501)
  assert.equal(materialToForm({ description }).description, description)
})
