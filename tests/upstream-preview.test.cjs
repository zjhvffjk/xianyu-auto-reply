const test = require('node:test')
const assert = require('node:assert/strict')
const http = require('node:http')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

test('Vite preview preserves ordinary API and uploaded asset proxy alongside public status', async () => {
  const backend = http.createServer((req, res) => {
    if (req.url.startsWith('/static/')) { res.end('test-uploaded-asset'); return }
    res.setHeader('content-type', 'application/json')
    res.end(JSON.stringify({ marker: 'test-backend', forwardedFor: req.headers['x-forwarded-for'] }))
  })
  await new Promise(resolve => backend.listen(0, '127.0.0.1', resolve))
  const oldTarget = process.env.VITE_BACKEND_SERVICE_URL
  process.env.VITE_BACKEND_SERVICE_URL = `http://127.0.0.1:${backend.address().port}`
  let preview
  try {
    const vite = await import(pathToFileURL(path.resolve('frontend/node_modules/vite/dist/node/index.js')).href)
    preview = await vite.preview({ root: path.resolve('frontend'), configFile: path.resolve('frontend/vite.config.ts'),
      preview: { host: '127.0.0.1', port: 0, strictPort: true, open: false } })
    const base = `http://127.0.0.1:${preview.httpServer.address().port}`
    const api = await fetch(base + '/api/upstream-merge-test')
    assert.equal(api.headers.get('content-type'), 'application/json', '普通API必须到达测试后端')
    assert.equal((await api.json()).marker, 'test-backend')
    assert.equal(await (await fetch(base + '/static/upstream-test-image')).text(), 'test-uploaded-asset')
    const status = await (await fetch(base + '/api/v1/public/status', { headers: { 'x-forwarded-for': 'spoofed' } })).json()
    assert.equal(status.marker, 'test-backend')
    assert.notEqual(status.forwardedFor, 'spoofed')
    assert.equal((await (await fetch(base + '/frontend-health')).json()).success, true)
  } finally {
    if (oldTarget === undefined) delete process.env.VITE_BACKEND_SERVICE_URL
    else process.env.VITE_BACKEND_SERVICE_URL = oldTarget
    if (preview) {
      preview.httpServer.closeAllConnections()
      await new Promise(resolve => preview.httpServer.close(resolve))
    }
    backend.closeAllConnections()
    await new Promise(resolve => backend.close(resolve))
  }
})
