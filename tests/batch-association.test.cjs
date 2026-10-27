const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')
const sandbox = {exports: {}, Error}
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../frontend/src/utils/batchAssociation.ts'), 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText, sandbox)
const {saveAssociations} = sandbox.exports

test('mixed batch preserves business and network failures, continues after failure, retries only failed items', async () => {
  const writes = []
  const progress = []
  const failures = await saveAssociations(['A', 'B', 'C', 'D', 'A'], async id => {
    writes.push(id)
    if (id === 'B') return {success: false, message: '卡券已停用'}
    if (id === 'C') throw new Error('连接中断')
    return {success: true}
  }, (done, total) => progress.push([done, total]))
  assert.deepEqual(writes, ['A', 'B', 'C', 'D'])
  assert.deepEqual(JSON.parse(JSON.stringify(failures)), [{itemId: 'B', reason: '卡券已停用'}, {itemId: 'C', reason: '连接中断'}])
  assert.deepEqual(progress, [[1, 4], [2, 4], [3, 4], [4, 4]])
  const retried = []
  const remaining = await saveAssociations(failures.map(f => f.itemId), async id => {
    retried.push(id)
    return {success: true}
  }, () => {})
  assert.deepEqual(retried, ['B', 'C'])
  assert.equal(remaining.length, 0)
})

test('empty batch never writes or reports progress', async () => {
  let calls = 0
  const failures = await saveAssociations([], async () => { calls++; return {success: true} }, () => calls++)
  assert.equal(calls, 0)
  assert.equal(failures.length, 0)
})
