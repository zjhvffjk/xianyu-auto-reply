async (page) => {
  page.setDefaultTimeout(4000);
  const context=page.context(), failures=[], errors=[], reads=[], writes=[];
  let cleared=false, holdDetail=false, releaseDetail=null, failNextHistory=false;
  const check=async(name,fn)=>{try{await fn()}catch(e){failures.push(name+': '+e.message)}};
  const watch=p=>p.on('pageerror',e=>errors.push(e.message));watch(page);
  const material=id=>({id,title:'收尾素材'+id,description:'完整原文',price:1.01,quantity:1,images:[],videos:[],
    specifications:[],sku_rows:[],condition:'全新',shipping_method:'free',delivery_method:'express',postage:0,
    platform_category_id:'1',platform_channel_category_id:'2',platform_category_name:'其他闲置',
    auto_relist_can_configure:false,created_at:'2026-10-31T10:00:00+08:00',updated_at:'2026-10-31T10:00:00+08:00'});
  const paginate=(url,row,total=235)=>{
    const p=Number(url.searchParams.get('page')||1),size=Number(url.searchParams.get('page_size')||10);
    reads.push({path:url.pathname,page:p,size});
    return {list:Array.from({length:Math.max(0,Math.min(size,total-(p-1)*size))},(_,i)=>row((p-1)*size+i+1)),total,page:p,page_size:size,total_pages:Math.ceil(total/size)};
  };
  await context.route('**/api/**',async route=>{
    const req=route.request(),url=new URL(req.url()),path=url.pathname;
    let data={success:true,data:{}};
    if(path.endsWith('/auth/verify')) data={authenticated:true,user_id:9,username:'收尾回归',is_admin:false};
    else if(path.endsWith('/cookies/options')) data=[{id:'shop-a',pk:1,nickname:'测试店铺',enabled:true}];
    else if(path.endsWith('/personal-addresses')||path.endsWith('/addresses')) data={success:true,data:paginate(url,id=>({id,address:'回归地址'+id,name:'地址'+id,search_keyword:'回归地址'+id,use_count:0,is_enabled:true,weight:1,sort_order:0,address_type:'global'}))};
    else if(path.endsWith('/ai-listing/configs')) data={success:true,data:paginate(url,id=>({id,name:'回归配置'+id,provider_type:'openai',text_api_key_masked:'***',text_model:'fixture-model',image_enabled:false}))};
    else if(path.endsWith('/ai-listing/tasks')) data={success:true,data:paginate(url,id=>({task_id:'ai-'+id,keyword:'回归主题'+id,config_name:'回归配置',status:'success',total:1,success:1,failed:0,finished:true,progress_percent:100,created_at:'2026-10-31T10:00:00+08:00'}))};
    else if(path.endsWith('/auto-relist/events')) data={success:true,data:paginate(url,id=>({id,old_item_id:'续售商品'+id,status:'success',status_text:'已完成',result_unknown:false,created_at:'2026-10-31T10:00:00+08:00'}))};
    else if(path.endsWith('/auto-relist')) data={success:true,data:null};
    else if(/\/materials\/\d+$/.test(path)) {
      data={success:true,data:material(Number(path.split('/').at(-1)))};
      if(holdDetail&&path.endsWith('/1')) {holdDetail=false;releaseDetail=()=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});return;}
    }
    else if(path.endsWith('/materials')) data={success:true,data:paginate(url,material)};
    else if(path.endsWith('/publish/batches')) {
      if(failNextHistory) {failNextHistory=false;await route.abort();return;}
      data={success:true,data:paginate(url,id=>({batch_id:'t'+String(id).padStart(6,'0')+'-fixture',mode:'immediate',status:'completed',total:1,success:1,failed:0,unknown:0,finished:true,cancel_requested:false,interval_seconds:60,start_at:'2026-10-31T10:00:00+08:00',next_run_at:null,account_ids:['shop-a'],account_statuses:[]}))};
    }
    else if(path.endsWith('/logs/clear')&&req.method()==='DELETE') {writes.push(path);cleared=true;data={success:true,message:'已清空',data:{cleared_logs:1,cleared_batches:0,retained_logs:0,retained_batches:0}};}
    else if(path.endsWith('/product-publish/logs')) data={success:true,data:paginate(url,id=>({id,title:'联动日志'+id,user_id:9,account_id:'shop-a',status:'success',price:'1.01',created_at:'2026-10-31T10:00:00+08:00'}),cleared?0:1)};
    else if(path.includes('/account-capability/')) data={success:true,data:{account_id:'shop-a',can_publish:true,is_fish_shop:false,message:''}};
    else if(path.includes('user-settings')) data={success:true,value:'true'};
    else if(path.includes('announcements')) data={success:true,data:[]};
    else if(req.method()!=='GET') {writes.push('UNEXPECTED '+path);await route.abort();return;}
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await context.addInitScript(()=>{
    localStorage.setItem('auth-storage',JSON.stringify({state:{token:'test-only',refreshToken:'test-only',isAuthenticated:true},version:2}));
    localStorage.setItem('auth_token','test-only');localStorage.setItem('user_info',JSON.stringify({user_id:9,username:'收尾回归',is_admin:false}));
  });
  const exercise=async(scope,label)=>{
    const pager=scope.locator('.vben-card-footer').filter({hasText:'每页'});
    await pager.getByRole('combobox').selectOption('100');await scope.getByText(label(100),{exact:true}).waitFor();
    await pager.getByRole('button',{name:'尾页',exact:true}).click();await scope.getByText(label(235),{exact:true}).waitFor();
    await pager.getByRole('spinbutton').fill('2');await pager.getByRole('spinbutton').press('Enter');await scope.getByText(label(101),{exact:true}).waitFor();
    await pager.getByRole('button',{name:'首页',exact:true}).click();await scope.getByText(label(1),{exact:true}).waitFor();
    await page.setViewportSize({width:390,height:844});await pager.scrollIntoViewIfNeeded();
    const box=await pager.boundingBox();if(!box||box.x<0||box.x+box.width>391) throw Error('手机分页超出视口');
    await page.setViewportSize({width:1440,height:982});
  };
  await page.setViewportSize({width:1440,height:982});
  await check('随机地址分页和普通用户只读',async()=>{
    await page.goto('http://127.0.0.1:9001/product-publish/addresses');await page.getByText('回归地址1',{exact:true}).first().waitFor();
    await exercise(page,id=>'回归地址'+id);
    if(await page.getByRole('button',{name:'新增随机地址',exact:true}).count()) throw Error('普通用户出现全局地址写入口');
  });
  await check('个人地址分页',async()=>{
    await page.getByRole('button',{name:'个人地址库',exact:true}).click();await page.getByText('回归地址1',{exact:true}).waitFor();
    await exercise(page,id=>'回归地址'+id);
  });
  await check('单品素材选择分页',async()=>{
    await page.goto('http://127.0.0.1:9001/product-publish/single');await page.getByRole('button',{name:'从素材库导入',exact:true}).click();
    const modal=page.locator('.modal-content').filter({has:page.getByRole('heading',{name:'从素材库选择',exact:true})});
    await modal.getByText('收尾素材1',{exact:true}).waitFor();await exercise(modal,id=>'收尾素材'+id);
    holdDetail=true;
    await modal.getByTitle('查看素材详情',{exact:true}).nth(0).click();
    await modal.getByTitle('查看素材详情',{exact:true}).nth(1).click();
    const detail=page.locator('.modal-content').filter({has:page.getByRole('heading',{name:'素材详情',exact:true})});
    await detail.locator('.modal-header p').filter({hasText:'收尾素材2'}).waitFor();
    const response=page.waitForResponse(r=>r.url().endsWith('/materials/1'));
    await releaseDetail();releaseDetail=null;await response;
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    if((await detail.locator('.modal-header p').innerText())!=='收尾素材2') throw Error('旧预览覆盖当前素材');
  });
  await page.goto('http://127.0.0.1:9001/product-publish/materials');await page.getByText('收尾素材1',{exact:true}).waitFor();
  await page.getByRole('button',{name:'AI 铺货',exact:true}).click();
  const ai=page.locator('.modal-content').filter({has:page.getByRole('heading',{name:'AI 铺货',exact:true})});
  await check('AI配置分页',async()=>{
    await ai.getByRole('button',{name:'配置管理',exact:true}).click();await ai.getByText('回归配置1',{exact:true}).waitFor();
    await exercise(ai,id=>'回归配置'+id);
  });
  await check('AI历史分页',async()=>{
    await ai.getByRole('button',{name:'历史任务',exact:true}).click();await ai.getByText('回归主题1',{exact:true}).waitFor();
    await exercise(ai,id=>'回归主题'+id);
  });
  await ai.getByRole('button',{name:'关闭',exact:true}).click();
  await check('自动续售只读记录分页',async()=>{
    await page.getByTitle('管理员只读，查看自动续售',{exact:true}).first().click();
    const modal=page.locator('.modal-content').filter({has:page.getByRole('heading',{name:'自动续售',exact:true})});
    await modal.getByText('续售商品1',{exact:true}).waitFor();await exercise(modal,id=>'续售商品'+id);
    if(await modal.getByRole('button',{name:'保存并启用',exact:true}).count()) throw Error('只读续售出现保存入口');
  });
  await check('批量任务历史分页',async()=>{
    await page.goto('http://127.0.0.1:9001/product-publish/batch');
    const history=page.locator('section').filter({has:page.getByRole('heading',{name:'发布任务列表',exact:true})});
    await history.getByText('请求号：t000001-',{exact:true}).waitFor();await exercise(history,id=>'请求号：t'+String(id).padStart(6,'0')+'-');
  });
  await check('任务历史网络失败后只读恢复查询',async()=>{
    const history=page.locator('section').filter({has:page.getByRole('heading',{name:'发布任务列表',exact:true})});
    await page.clock.install();failNextHistory=true;
    await history.getByRole('button',{name:'刷新任务',exact:true}).click();
    await history.getByRole('alert').waitFor();
    await page.clock.fastForward(11000);
    await history.getByRole('alert').waitFor({state:'hidden'});
    await history.getByText('请求号：t000001-',{exact:true}).waitFor();
  });
  await check('清空日志同步其他已打开日志标签',async()=>{
    await page.goto('http://127.0.0.1:9001/product-publish/logs');await page.getByText('联动日志1',{exact:true}).waitFor();
    const other=await context.newPage();watch(other);await other.goto(page.url());await other.getByText('联动日志1',{exact:true}).waitFor();
    const before=reads.filter(r=>r.path.endsWith('/product-publish/logs')).length;
    await page.getByRole('button',{name:'清空日志',exact:true}).click();
    await page.getByRole('dialog',{name:'确认清空日志'}).getByRole('button',{name:'确认清空',exact:true}).click();
    await page.getByText('暂无发布记录',{exact:true}).waitFor();await other.getByText('暂无发布记录',{exact:true}).waitFor();
    if(reads.filter(r=>r.path.endsWith('/product-publish/logs')).length!==before+2) throw Error('清空后本页或另一页出现重复刷新');
    await other.close();
  });
  if(errors.length) failures.push('页面错误: '+errors.join('; '));
  if(writes.some(p=>p.startsWith('UNEXPECTED '))) failures.push('未声明写操作: '+writes.join(','));
  if(failures.length) throw Error(failures.join('\n'));
  return {success:true,checks:9,sharedPagination:true,previewRaceProtected:true,readRecovery:true,mobile:true,readOnlyPermissions:true,crossTabLogs:true,realWrites:0};
}
