const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const ts = require('../frontend/node_modules/typescript')
const moduleUnderTest = { exports: {} }
const source = fs.readFileSync('frontend/src/utils/refundVerification.ts', 'utf8')
new Function('module', 'exports', ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText)(moduleUnderTest, moduleUnderTest.exports)
const { isVerifiedRefundCallback: verified } = moduleUnderTest.exports
const frame = {}
const url = 'https://pcauth-site.alipay.com/home?test'
const event = { source: frame, origin: 'https://pcauth-site.alipay.com', data: { type: 'verify', result: { code: '1000' } } }

test('accepts only success from current official frame', () => {
  assert.equal(verified(event, frame, url), true)
  assert.equal(verified({ ...event, data: JSON.stringify(event.data) }, frame, url), true)
})
test('rejects other windows, missing frame and hostile origins', () => {
  assert.equal(verified(event, {}, url), false)
  assert.equal(verified(event, null, url), false)
  for (const origin of ['null', 'http://localhost:9001', 'https://pcauth-site.alipay.com.evil.test']) {
    assert.equal(verified({ ...event, origin }, frame, url), false)
  }
})
test('malformed or failed verification never submits', () => {
  for (const data of ['not json', null, {type:'verify',result:{code:'1001'}}, {type:'UPDATE_HEIGHT',msg:1000}]) {
    assert.equal(verified({ ...event, data }, frame, url), false)
  }
})
test('untrusted verification URL cannot authorize refunds', () => {
  for (const candidate of ['javascript:alert(1)', 'https://evil.test/home', 'http://pcauth-site.alipay.com/home', 'https://u@pcauth-site.alipay.com/home']) {
    assert.equal(verified(event, frame, candidate), false)
  }
})
