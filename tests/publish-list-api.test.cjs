const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')

function api() {
  const calls = []
  const writes = []
  const sandbox = {exports:{}, URLSearchParams, require: name => {
    assert.equal(name, '@/utils/request')
    return {get: url => {calls.push(new URL(url, 'http://test'));return Promise.resolve({success:true})},
      post: (url,body) => {writes.push({url,body});return Promise.resolve({success:true})}}
  }}
  vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname, '../frontend/src/api/productPublish.ts'), 'utf8'), {
    compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020},
  }).outputText, sandbox)
  return {...sandbox.exports, calls, writes}
}

test('material list preserves pagination and exact source/category filters without introducing writes', async () => {
  const {getMaterials, calls} = api()
  for (const size of [10,20,50,100]) {
    await getMaterials(2,size,{title:'原文 A&B',category:'其他闲置',condition:'全新',platform_category_id:'123',source_account_id:'shop/a',own_only:true,include_unlinked:true})
    const url = calls.at(-1)
    assert.equal(url.pathname,'/api/v1/product-publish/materials')
    assert.deepEqual(Object.fromEntries(url.searchParams),{page:'2',page_size:String(size),title:'原文 A&B',category:'其他闲置',condition:'全新',platform_category_id:'123',source_account_id:'shop/a',own_only:'true',include_unlinked:'true'})
  }
})

test('log list sends pagination and scoped filters and resets absent filters', async () => {
  const {getPublishLogs,calls}=api()
  await getPublishLogs(3,100,'shop/a','unknown')
  assert.deepEqual(Object.fromEntries(calls.at(-1).searchParams),{page:'3',page_size:'100',account_id:'shop/a',status:'unknown'})
  await getPublishLogs(1,20)
  assert.deepEqual(Object.fromEntries(calls.at(-1).searchParams),{page:'1',page_size:'20'})
})

test('batch history page size is transmitted and legacy calls stay at ten', async () => {
  const {getPublishBatches,calls}=api()
  await getPublishBatches(2,100)
  assert.deepEqual(Object.fromEntries(calls.at(-1).searchParams),{page:'2',page_size:'100'})
  await getPublishBatches()
  assert.deepEqual(Object.fromEntries(calls.at(-1).searchParams),{page:'1',page_size:'10'})
})

test('selected history deletion sends only explicit batch ids to the scoped endpoint', async () => {
  const {deletePublishBatchHistory,writes}=api()
  await deletePublishBatchHistory(['selected-one','selected-two'])
  assert.equal(writes[0].url,'/api/v1/product-publish/publish/batches/delete-history')
  assert.equal(JSON.stringify(writes[0].body),JSON.stringify({batch_ids:['selected-one','selected-two']}))
})
