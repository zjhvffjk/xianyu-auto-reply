const test = require('node:test')
const assert = require('node:assert/strict')
const { createRequire } = require('node:module')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const root = path.resolve(__dirname, '..')
const ts = createRequire(path.join(root, 'frontend/package.json'))('typescript')
const source = fs.readFileSync(path.join(root, 'frontend/src/utils/accountLabel.ts'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const sandbox = { exports: {} }
vm.runInNewContext(compiled, sandbox)
const { getAccountName, getAccountNickname } = sandbox.exports

test('all labels use verified names and keep the submitted account ID untouched', () => {
  const account = { id: '123', member_name: 'xy_member', nickname: '小店', note: '私人备注' }
  assert.equal(getAccountName(account), 'xy_member · 小店')
  assert.equal(getAccountNickname(account), '小店')
  assert.equal(account.id, '123')
  assert.equal(getAccountName({ id: '123', nickname: '小店' }), '小店')
  assert.equal(getAccountName({ id: '123', member_name: '同名', nickname: '同名' }), '同名')
  assert.equal(getAccountName({ id: '123', member_name: 'x***8', note: '备注' }), '123')
  assert.equal(getAccountName({ id: '123' }), '123')
  assert.equal(getAccountNickname({ id: '123', member_name: 'xy_member' }), 'xy_member')
})
