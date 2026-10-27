const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')
const sandbox = {exports: {}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../frontend/src/utils/materialCategory.ts'), 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText, sandbox)
const {hasMaterialCategory, categoryPathLabel} = sandbox.exports
test('category is complete only with both platform identifiers', () => {
  assert.equal(hasMaterialCategory({platform_category_id: '1'}), false)
  assert.equal(hasMaterialCategory({category: '其他游戏道具'}), false)
  assert.equal(hasMaterialCategory({platform_category_id: '1', platform_channel_category_id: '2'}), true)
})
test('category displays a single readable path, without duplicate adjacent names or IDs', () => {
  assert.equal(categoryPathLabel({cat_id: '123', path: [{name: '游戏'}, {name: '道具'}, {name: '道具'}]}), '游戏 / 道具')
  assert.equal(categoryPathLabel({path: [], cat_name: '其他游戏道具'}), '其他游戏道具')
})

test('category attribute changes do not fabricate a new condition', () => {
  const context = {exports: {}}
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../frontend/src/pages/product-publish/categoryUtils.ts'), 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText, context)
  assert.equal(context.exports.platformAttributesPatch([]).condition, '')
  assert.equal(context.exports.platformAttributesPatch([{property_id: '20879', value_name: '99新'}]).condition, '99新')
})
