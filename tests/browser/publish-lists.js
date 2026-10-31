async (page) => {
  page.setDefaultTimeout(5000);
  const context = page.context(), failures = [], errors = [], requests = [], writes = [];
  const held = new Map();
  let holdLogs = false, cleared = false, materialTotal = 235;
  const check = async (name, fn) => {
    try { await fn(); } catch (error) { failures.push(name + ': ' + error.message); }
  };
  const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const material = (id, title) => ({id, title, description:'完整原文', price:1.01, quantity:0, images:[],
    condition:'全新', platform_category_id:'1', platform_channel_category_id:'2', platform_category_name:'其他闲置',
    created_at:'2026-10-31T10:00:00+08:00', updated_at:'2026-10-31T10:00:00+08:00'});
  const log = (id, title, status='success') => ({id, title, status, user_id:9, account_id:'shop-a', price:'1.01',
    created_at:'2026-10-31T10:00:00+08:00', updated_at:'2026-10-31T10:00:00+08:00'});
  const respond = (route, data) => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  const watch = p => p.on('pageerror', error => errors.push(error.message));
  watch(page);
  await context.route('**/api/**', async route => {
    const req=route.request(), url=new URL(req.url()), path=url.pathname;
    let data={success:true,code:200,data:{}};
    if(path.endsWith('/auth/verify')) data={authenticated:true,user_id:9,username:'兼容回归',is_admin:false};
    else if(path.endsWith('/cookies/options')) data=[{pk:1,id:'shop-a',nickname:'测试店铺A',enabled:true},{pk:2,id:'shop-b',nickname:'测试店铺B',enabled:true}];
    else if(path.endsWith('/product-publish/materials')) {
      const p=Number(url.searchParams.get('page')), size=Number(url.searchParams.get('page_size')), title=url.searchParams.get('title');
      requests.push({path,page:p,size,title,category:url.searchParams.get('category')});
      const total=title?1:materialTotal;
      const list=title?[material(title==='旧请求'?901:902,title==='旧请求'?'旧结果':'新结果')]:Array.from({length:Math.max(0,Math.min(size,total-(p-1)*size))},(_,i)=>material((p-1)*size+i+1,'兼容素材'+((p-1)*size+i+1)));
      data={success:true,data:{list,total,page:p,page_size:size,total_pages:Math.ceil(total/size)}};
      if(title==='旧失败') data={success:false,message:'旧请求错误'};
      if(title==='旧请求'||title==='旧失败') { held.set('materials',()=>respond(route,data)); return; }
      if(title==='新等待') { held.set('newMaterials',()=>respond(route,data)); return; }
    } else if(path.endsWith('/product-publish/logs/clear') && req.method()==='DELETE') {
      writes.push(path);cleared=true;
      data={success:true,message:'已清空已结束记录',data:{cleared_logs:1,cleared_batches:0,retained_logs:0,retained_batches:0}};
    } else if(path.endsWith('/product-publish/logs')) {
      const p=Number(url.searchParams.get('page')), size=Number(url.searchParams.get('page_size'));
      const status=url.searchParams.get('status'), account=url.searchParams.get('account_id');
      requests.push({path,page:p,size,status,account});
      const total=cleared?0:235;
      data={success:true,data:{list:cleared?[]:Array.from({length:Math.max(0,Math.min(size,total-(p-1)*size))},(_,i)=>log((p-1)*size+i+1,'兼容日志'+((p-1)*size+i+1),status||'success')),total,page:p,page_size:size,total_pages:Math.ceil(total/size)}};
      if(holdLogs) { holdLogs=false; held.set('logs',()=>respond(route,data)); return; }
    } else if(path.includes('announcements')) data={success:true,data:[]};
    else if(path.includes('user-settings')) data={success:true,value:'true'};
    else if(req.method()!=='GET') { writes.push('UNEXPECTED '+path); await route.abort(); return; }
    await respond(route,data);
  });
  await context.addInitScript(()=>{
    localStorage.setItem('auth-storage',JSON.stringify({state:{token:'test-only',refreshToken:'test-only',isAuthenticated:true},version:2}));
    localStorage.setItem('auth_token','test-only');
    localStorage.setItem('user_info',JSON.stringify({user_id:9,username:'兼容回归',is_admin:false}));
    localStorage.setItem('shop-selections-v2',JSON.stringify({state:{selections:{'9':{accountId:'shop-a',label:'测试店铺A'}}},version:0}));
  });
  await page.setViewportSize({width:1440,height:982});
  await page.goto('http://127.0.0.1:9001/product-publish/materials');
  await page.getByText('兼容素材1',{exact:true}).waitFor();
  await check('素材库旧响应不能覆盖新搜索',async()=>{
    const search=page.getByPlaceholder('搜索标题...');
    await search.fill('旧请求');await search.press('Enter');
    await settle();
    if(!held.has('materials')) throw Error('未捕获慢请求');
    await search.fill('新请求');await search.press('Enter');
    await page.getByText('新结果',{exact:true}).waitFor();
    const response=page.waitForResponse(r=>r.url().includes(encodeURIComponent('旧请求')));
    await held.get('materials')();held.delete('materials');await response;await settle();
    if(!await page.getByText('新结果',{exact:true}).count()) throw Error('旧请求把当前结果覆盖了');
  });
  await check('过期失败不能污染当前结果',async()=>{
    const search=page.getByPlaceholder('搜索标题...');
    await search.fill('旧失败');await search.press('Enter');await settle();
    await search.fill('新请求');await search.press('Enter');await page.getByText('新结果',{exact:true}).waitFor();
    const response=page.waitForResponse(r=>r.url().includes(encodeURIComponent('旧失败')));
    await held.get('materials')();held.delete('materials');await response;await settle();
    if(await page.getByText('旧请求错误',{exact:true}).count()) throw Error('过期请求错误仍显示');
  });
  await check('旧请求结束不能结束新请求加载',async()=>{
    const search=page.getByPlaceholder('搜索标题...');
    await search.fill('旧请求');await search.press('Enter');await settle();
    await search.fill('新等待');await search.press('Enter');await settle();
    const response=page.waitForResponse(r=>r.url().includes(encodeURIComponent('旧请求')));
    await held.get('materials')();held.delete('materials');await response;await settle();
    const pager=page.locator('.vben-card-footer').filter({hasText:'每页'});
    try {
      if(!await pager.getByRole('combobox').isDisabled()) throw Error('旧请求提前结束了加载状态');
    } finally {
      await held.get('newMaterials')();held.delete('newMaterials');
    }
    await page.getByText('新结果',{exact:true}).waitFor();
  });
  await check('素材库公共分页与原选择规则',async()=>{
    await page.reload();await page.getByText('兼容素材1',{exact:true}).waitFor();
    const pager=page.locator('.vben-card-footer').filter({hasText:'每页'});
    await pager.getByRole('combobox').selectOption('100');
    await page.getByText('兼容素材100',{exact:true}).waitFor();
    await page.locator('thead input[type=checkbox]').check();
    if(await page.locator('tbody input[type=checkbox]:checked').count()!==100) throw Error('当前页全选不正确');
    await pager.getByRole('button',{name:'尾页',exact:true}).click({timeout:1500});
    await page.getByText('兼容素材235',{exact:true}).waitFor();
    if(await page.locator('tbody tr').count()!==35) throw Error('尾页数量不正确');
    await pager.getByRole('button',{name:'首页',exact:true}).click();
    await page.getByText('兼容素材1',{exact:true}).waitFor();
    if(await page.locator('tbody input[type=checkbox]:checked').count()) throw Error('素材库原本按当前页选择，不应扩展删除范围');
    await pager.getByRole('spinbutton').fill('2');await pager.getByRole('spinbutton').press('Enter');
    await page.getByText('兼容素材101',{exact:true}).waitFor();
    await page.getByPlaceholder('搜索标题...').fill('新请求');
    await page.getByRole('button',{name:'查询',exact:true}).click();await page.getByText('新结果',{exact:true}).waitFor();
    if(requests.at(-1).page!==1) throw Error('筛选未返回首页');
    await page.getByRole('button',{name:'重置',exact:true}).click();await page.getByText('兼容素材1',{exact:true}).waitFor();
    if(requests.at(-1).title) throw Error('重置仍携带旧筛选');
    await page.setViewportSize({width:390,height:844});await pager.scrollIntoViewIfNeeded();
    const box=await pager.boundingBox();if(!box||box.x<0||box.x+box.width>391) throw Error('手机分页超出视口');
    await page.screenshot({path:'output/playwright/publish-materials-mobile.png'});
  });
  await check('总数减少后自动返回有效页',async()=>{
    await page.setViewportSize({width:1440,height:982});
    const pager=page.locator('.vben-card-footer').filter({hasText:'每页'});
    await pager.getByRole('button',{name:'尾页',exact:true}).click();await page.getByText('兼容素材235',{exact:true}).waitFor();
    materialTotal=100;
    await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByText('兼容素材1',{exact:true}).waitFor();
    if(requests.at(-1).page!==1) throw Error('没有返回剩余素材所在页');
  });
  await page.setViewportSize({width:1440,height:982});
  await page.goto('http://127.0.0.1:9001/product-publish/logs');
  await page.getByText('兼容日志1',{exact:true}).waitFor();
  await check('发布日志公共分页和店铺状态筛选',async()=>{
    const pager=page.locator('.vben-card-footer').filter({hasText:'每页'});
    await pager.getByRole('combobox').selectOption('50');await page.getByText('兼容日志50',{exact:true}).waitFor();
    await pager.getByRole('button',{name:'尾页',exact:true}).click({timeout:1500});await page.getByText('兼容日志235',{exact:true}).waitFor();
    await pager.getByRole('spinbutton').fill('2');await pager.getByRole('button',{name:'跳转',exact:true}).click();
    await page.getByText('兼容日志51',{exact:true}).waitFor();
    await page.getByRole('combobox').nth(0).selectOption('shop-b');await page.getByRole('combobox').nth(1).selectOption('failed');
    await page.getByRole('button',{name:'查询',exact:true}).click();await page.getByText('兼容日志1',{exact:true}).waitFor();
    if(requests.at(-1).account!=='shop-b'||requests.at(-1).status!=='failed'||requests.at(-1).page!==1) throw Error('筛选参数变了');
    const resetResponse=page.waitForResponse(r=>r.url().includes('/product-publish/logs')&&!r.url().includes('account_id='));
    await page.getByRole('button',{name:'重置',exact:true}).click();await resetResponse;await settle();
  });
  await check('日志加载中禁用分页，避免重复切换',async()=>{
    await page.reload();await page.getByText('兼容日志1',{exact:true}).waitFor();
    holdLogs=true;
    await page.getByRole('button',{name:'刷新',exact:true}).click();
    await settle();
    const pager=page.locator('.vben-card-footer').filter({hasText:'每页'});
    try {
      if(!await pager.getByRole('combobox').isDisabled()) throw Error('加载中仍可改变分页参数');
      if(!await pager.getByRole('button',{name:'跳转',exact:true}).isDisabled()) throw Error('加载中仍可跳页');
    } finally {
      if(held.has('logs')) { await held.get('logs')();held.delete('logs'); }
    }
    await page.getByText('兼容日志1',{exact:true}).waitFor();
  });
  await check('清空后空列表仍可切换分页条数',async()=>{
    await page.getByRole('button',{name:'清空日志',exact:true}).click();
    await page.getByRole('dialog',{name:'确认清空日志'}).getByRole('button',{name:'确认清空',exact:true}).click();
    await page.getByText('暂无发布记录',{exact:true}).waitFor();
    const pager=page.locator('.vben-card-footer').filter({hasText:'每页'});
    const response=page.waitForResponse(r=>r.url().includes('page_size=100'));
    await pager.getByRole('combobox').selectOption('100');await response;await settle();
    if(!await page.getByText('暂无发布记录',{exact:true}).count()) throw Error('空列表未保持');
    await page.setViewportSize({width:390,height:844});await pager.scrollIntoViewIfNeeded();
    const box=await pager.boundingBox();if(!box||box.x<0||box.x+box.width>391) throw Error('手机日志分页超出视口');
    await page.screenshot({path:'output/playwright/publish-logs-mobile.png'});
  });
  for(const release of held.values()) await release();
  if(errors.length) failures.push('页面错误: '+errors.join('; '));
  if(writes.some(path=>path.startsWith('UNEXPECTED '))) failures.push('未声明写操作: '+writes.join(','));
  if(failures.length) throw Error(failures.join('\n'));
  return {success:true,checks:8,oldResponsesIgnored:true,staleErrorsIgnored:true,loadingPreserved:true,pageClamped:true,pagination:true,filters:true,selectionRulesPreserved:true,mobile:true,realWrites:0};
}
