const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('../frontend/node_modules/typescript')
const context = {exports: {}, Date, Intl}
vm.runInNewContext(ts.transpileModule(fs.readFileSync('frontend/src/utils/batchSchedule.ts','utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context)
const {defaultBeijingStart,batchSchedulePayload} = context.exports
test('Beijing input is independent of system time zone',()=>{
  assert.equal(defaultBeijingStart(new Date('2026-10-25T07:00:00Z')),'2026-10-25T15:05')
  assert.equal(batchSchedulePayload('scheduled','2026-10-25T16:00',5,new Date('2026-10-25T07:00:00Z')).start_at,'2026-10-25T16:00:00+08:00')
})
test('past and invalid dates are rejected instead of silently publishing immediately',()=>{
  for(const value of ['', '2026-02-31T12:00','2026-10-25T14:59','2026-10-25T15:00'])
    assert.throws(()=>batchSchedulePayload('scheduled',value,5,new Date('2026-10-25T07:00:00Z')))
})
test('immediate and scheduled share bounded per-item intervals',()=>{
  assert.equal(batchSchedulePayload('immediate','',0.5).interval_seconds,30)
  assert.equal(batchSchedulePayload('immediate','',5).interval_seconds,300)
  for(const value of [0,0.4,NaN,Infinity,1441]) assert.throws(()=>batchSchedulePayload('immediate','',value))
})
