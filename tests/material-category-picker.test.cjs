const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')
const sandbox = {exports: {}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../frontend/src/utils/materialCategory.ts'), 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText, sandbox)
const {savedMaterialCategoryChoices, categoryRecommendationInput} = sandbox.exports
const material = {title: '原商品标题', description: '原商品描述', platform_category_id: '1', platform_channel_category_id: '2', platform_category_name: '其他闲置', platform_attributes: [{property_id: 'old'}]}

test('已有素材类目按平台身份去重，排除不完整记录，同名不同频道保留', () => {
  const result = savedMaterialCategoryChoices([material, {...material}, {...material, platform_channel_category_id: '3'}, {...material, platform_category_id: ''}, {...material, platform_category_name: '', category: ''}])
  assert.equal(result.length, 2)
  assert.equal(result[0].cat_name, '其他闲置')
  assert.equal(result[1].channel_cat_id, '3')
  assert.equal(result[0].platform_attributes, undefined)
  assert.equal(material.platform_attributes.length, 1)
})

test('查询类目关键词独立于素材原文，不会因原商品标题重新推荐原类目', () => {
  const input = categoryRecommendationInput(material, '  其他闲置  ')
  assert.equal(input.title, '其他闲置')
  assert.equal(input.description, '其他闲置')
  assert.equal(material.title, '原商品标题')
  assert.equal(material.description, '原商品描述')
})

test('未输入关键词时仍支持按原商品获取建议', () => {
  const input = categoryRecommendationInput(material, '  ')
  assert.equal(input.title, material.title)
  assert.equal(input.description, material.description)
})
