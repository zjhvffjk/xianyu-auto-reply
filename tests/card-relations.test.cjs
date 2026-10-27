const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')
const sandbox = {exports: {}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../frontend/src/utils/cardRelations.ts'), 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText, sandbox)
const {buildCardRelations} = sandbox.exports
const {getCardSelectionWarnings} = sandbox.exports

test('missing selected card stops saving instead of silently removing associations', () => {
  assert.throws(() => buildCardRelations(['own_1'], new Map()), /尚未加载/)
})

test('both entry points preserve dock identity and only emit each selected key once', () => {
  const cache = new Map([
    ['own_1', {id: 1, source: 'own'}],
    ['dock_7', {id: 2, source: 'dock_l1', dock_record_id: 7}],
    ['dock_8', {id: 2, source: 'dock_l2', dockRecordId: 8}],
  ])
  const output = JSON.parse(JSON.stringify(buildCardRelations(['own_1', 'dock_7', 'dock_8', 'own_1'], cache)))
  assert.deepEqual(output, [
    {card_id: 1, source: 'own', dock_record_id: null},
    {card_id: 2, source: 'dock_l1', dock_record_id: 7},
    {card_id: 2, source: 'dock_l2', dock_record_id: 8},
  ])
  assert.equal(buildCardRelations([], cache).length, 0)
})

test('same source and specification conflict is visible but different specifications are valid', () => {
  const first = {id: 1, source: 'own', enabled: true, is_multi_spec: true, spec_name: '颜色', spec_value: '蓝色'}
  assert.equal(getCardSelectionWarnings([first, {...first, id: 2}]).length, 1)
  assert.equal(getCardSelectionWarnings([first, {...first, id: 2, spec_value: '白色'}]).length, 0)
  assert.equal(getCardSelectionWarnings([first, {...first, id: 2, enabled: false}]).length, 0)
  assert.equal(getCardSelectionWarnings([first, {...first, source: 'dock_l1'}]).length, 0)
})
