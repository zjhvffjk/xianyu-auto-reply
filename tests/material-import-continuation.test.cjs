const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')
const sandbox = {exports: {}}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('frontend/src/utils/materialImportContinuation.ts', 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText, sandbox)
const {newlyImportedMaterialIds, loadImportedMaterials} = sandbox.exports

test('only newly created material IDs continue, never skipped or failed originals', () => {
  const rows = [{status:'created',material_id:3},{status:'exists',material_id:9},{status:'failed',material_id:10},{status:'created',material_id:3},{status:'created',material_id:4}]
  assert.deepEqual(Array.from(newlyImportedMaterialIds(rows)), [3,4])
})
test('invalid IDs and all-skipped results have no continuation', () => {
  assert.equal(newlyImportedMaterialIds([{status:'exists',material_id:1},{status:'created'},{status:'created',material_id:-1},{status:'created',material_id:0},{status:'created',material_id:1.5}]).length,0)
})
test('handoff loads exact new material objects, preserving order', async () => {
  const calls=[]
  const result=await loadImportedMaterials([3,4],async id=>{calls.push(id);return {success:true,data:{id,title:'original-'+id}}})
  assert.deepEqual(calls,[3,4])
  assert.deepEqual(Array.from(result,r=>r.title),['original-3','original-4'])
})
test('failed lookup rejects the handoff rather than silently dropping a material', async () => {
  await assert.rejects(loadImportedMaterials([3,4],async id=>id===3 ? {success:true,data:{id}} : {success:false,message:'素材已移除'}),/素材已移除/)
})
test('a mismatching returned ID cannot affect a different material', async () => {
  await assert.rejects(loadImportedMaterials([3],async()=>({success:true,data:{id:99}})),/读取素材失败/)
})
