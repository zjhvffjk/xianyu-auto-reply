const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')
const context = {exports: {}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../frontend/src/utils/polishedCopy.ts'), 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText, context)
const {getPolishedCopyError, isPolishedCopyPreview} = context.exports

test('long or multiline generated titles remain editable previews but cannot be adopted', () => {
  for (const title of ['【标价包邮直出】IVE李瑞小卡 love dive 爱河ny2.0瑞', '测'.repeat(31), '😀'.repeat(16), '标题\n换行']) {
    const copy = {title, description: '模型生成的完整正文'}
    assert.equal(isPolishedCopyPreview(copy), true)
    assert.notEqual(getPolishedCopyError(copy), '')
    assert.equal(copy.title, title)
    assert.equal(copy.description, '模型生成的完整正文')
  }
  assert.equal(isPolishedCopyPreview({title: '标题', description: null}), false)
})

test('accepts exact limits and optional bracket label without modifying copy', () => {
  const copy = {title: '【自动发货】' + '测'.repeat(24), description: '测'.repeat(1500)}
  const before = JSON.stringify(copy)
  assert.equal(getPolishedCopyError(copy), '')
  assert.equal(getPolishedCopyError({title: '普通商品', description: '普通正文'}), '')
  assert.equal(JSON.stringify(copy), before)
})

test('rejects invalid AI output and empty manual edits', () => {
  for (const copy of [null, {}, {title: 5, description: '正文'}, {title: ' ', description: '正文'}, {title: '标题', description: ' \n'}, {title: '标题', description: 5}]) {
    assert.notEqual(getPolishedCopyError(copy), '')
  }
})

test('over-limit edits, emoji and title newlines are rejected without truncation', () => {
  for (const copy of [{title: '测'.repeat(31), description: '正文'}, {title: '😀'.repeat(16), description: '正文'}, {title: '标题\n换行', description: '正文'}, {title: '标题', description: '测'.repeat(1501)}]) {
    const before = JSON.stringify(copy)
    assert.notEqual(getPolishedCopyError(copy), '')
    assert.equal(JSON.stringify(copy), before)
  }
})
