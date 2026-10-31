async (page) => {
  const context=page.context(),errors=[],writes=[],placements=[];
  page.setDefaultTimeout(6000);page.on('pageerror',error=>errors.push(error.message));
  let authenticated=false,isAdmin=false,tokenReads=0,saved={remote_url:'https://configured.example.invalid/token',remote_secret_key:'fake-test-key'};
  const ad=placement=>({id:placement==='home'?101:102,user_id:7,title:placement==='home'?'首页测试文字广告':'仪表盘测试文字广告',
    content:'仅用于浏览器回归的广告内容',link:null,expire_date:null,image_url:null,ad_type:placement==='home'?'home_text':'text',
    months:1,total_amount:'25.00',status:'approved',created_at:null,updated_at:null,source:'local'});
  await context.route('**/api/**',async route=>{
    const request=route.request(),url=new URL(request.url());let result={success:true,data:{}};
    if(url.pathname.endsWith('/auth/verify'))result=authenticated?{authenticated:true,user_id:7,username:'上游兼容测试',is_admin:isAdmin}:{authenticated:false};
    else if(url.pathname.endsWith('/advertisements/public')) {
      const placement=url.searchParams.get('placement')||'dashboard';placements.push(placement);
      result={success:true,data:{carousel:[],text:[ad(placement)]}};
    } else if(url.pathname.endsWith('/user-settings/external-api/token')) {
      if(request.method()==='GET'){tokenReads++;result={success:true,data:saved};}
      else if(request.method()==='PUT'){writes.push({type:'save',data:request.postDataJSON()});saved=request.postDataJSON();result={success:true,message:'测试配置已保存',data:saved};}
    } else if(url.pathname.endsWith('/user-settings/external-api/token/test')&&request.method()==='POST') {
      writes.push({type:'test',data:request.postDataJSON()});result={success:true,message:'测试连通成功',data:{token:'',device_id:'',api_mode:''}};
    } else if(url.pathname.endsWith('/cookies/options'))result=[];
    else if(url.pathname.endsWith('/cookies/stats/order-trend'))result={success:true,data:{trend:[]}};
    else if(url.pathname.endsWith('/cookies/stats'))result={success:true,data:{total_accounts:0,total_keywords:0,
      active_accounts:0,total_orders:0,today_reply_count:0,yesterday_reply_count:0,account_limit:10,used_account_count:0,remaining_account_count:10}};
    else if(url.pathname.includes('/user-settings/'))result={success:true,value:url.pathname.includes('disclaimer_agreed')?'true':'',dock_code:'fake-dock',secret_key:'fake-user-key'};
    else if(url.pathname.endsWith('/system-control/status'))result={success:true,data:{runtime:'docker',services:[]}};
    else if(url.pathname.includes('announcements'))result={success:true,data:[]};
    else if(url.pathname.includes('system-settings'))result={success:true,data:{'system.name':'兼容测试站点','menu_visibility.ad_apply':true}};
    else if(request.method()!=='GET')throw Error('不应调用的写操作：'+url.pathname);
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});
  });
  await page.setViewportSize({width:1440,height:982});
  await page.goto('http://127.0.0.1:9001/');await page.getByText('首页测试文字广告',{exact:true}).waitFor();
  if(!page.url().endsWith('/'))throw Error('公开首页要求登录');
  await page.getByRole('button',{name:'展开文字广告：首页测试文字广告',exact:true}).click();
  await page.getByText('仅用于浏览器回归的广告内容',{exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('link',{name:'登录',exact:true}).first().click();
  await page.waitForURL('**/login');await page.getByRole('button',{name:'登 录',exact:true}).waitFor();
  if(writes.length)throw Error('公开浏览/登录导航产生写请求');
  authenticated=true;
  await page.evaluate(()=>{
    localStorage.setItem('auth-storage',JSON.stringify({state:{token:'test-only',refreshToken:'test-only',isAuthenticated:true},version:2}));
    localStorage.setItem('auth_token','test-only');localStorage.setItem('user_info',JSON.stringify({user_id:7,username:'上游兼容测试',is_admin:false}));
  });
  await page.setViewportSize({width:1440,height:982});
  await page.goto('http://127.0.0.1:9001/dashboard');await page.getByText('仪表盘测试文字广告',{exact:true}).waitFor();
  if(await page.getByText('首页测试文字广告',{exact:true}).count())throw Error('首页和仪表盘广告混用');
  await page.goto('http://127.0.0.1:9001/personal-settings');await page.getByRole('heading',{name:'个人设置',exact:true}).waitFor();
  if(tokenReads)throw Error('未打开个人远程配置就读取Token');
  await page.getByRole('button',{name:'远程URL配置',exact:true}).click();
  const card=page.locator('div.vben-card').filter({has:page.getByRole('heading',{name:'Token获取方式',exact:true})});
  const input=card.getByPlaceholder('https://api.xianyushop.shop/api/external/invoke');
  await input.waitFor();
  await page.waitForFunction(()=>document.querySelector('#personal-token-remote-url')?.value==='https://configured.example.invalid/token');
  await input.fill('https://new.example.invalid/token');await card.getByPlaceholder('请输入远程接口秘钥').fill('fake-new-test-key');
  await card.getByRole('button',{name:'测试',exact:true}).click();await page.getByText('测试连通成功',{exact:true}).first().waitFor();
  if(writes.length!==1||writes[0].type!=='test'||saved.remote_url!=='https://configured.example.invalid/token')throw Error('测试修改了配置');
  await card.getByRole('button',{name:'保存',exact:true}).click();await page.getByText('测试配置已保存',{exact:true}).first().waitFor();
  if(writes.length!==2||saved.remote_url!=='https://new.example.invalid/token')throw Error('个人配置未按输入保存');
  await page.reload();await page.getByRole('button',{name:'远程URL配置',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#personal-token-remote-url')?.value==='https://new.example.invalid/token');
  await page.setViewportSize({width:390,height:844});await card.getByRole('button',{name:'保存',exact:true}).click({trial:true});
  await page.screenshot({path:'output/playwright/upstream-personal-token-mobile.png'});
  isAdmin=true;
  await page.evaluate(()=>{
    const user={user_id:7,username:'上游兼容测试',is_admin:true};
    localStorage.setItem('user_info',JSON.stringify(user));
    localStorage.setItem('auth-storage',JSON.stringify({state:{token:'test-only',refreshToken:'test-only',isAuthenticated:true,user},version:2}));
  });
  await page.goto('http://127.0.0.1:9001/settings');
  const tabs=page.getByRole('tablist',{name:'系统设置功能模块'}).getByRole('tab');
  await tabs.first().waitFor();
  if(await tabs.count()!==6)throw Error('系统设置模块缺失');
  for(let i=0;i<6;i++){await tabs.nth(i).click();if(await tabs.nth(i).getAttribute('aria-selected')!=='true')throw Error('系统设置标签未切换');}
  if(writes.length!==2)throw Error('系统设置浏览触发写操作');
  if(errors.length)throw Error(errors.join('; '));
  if(!placements.includes('home')||!placements.includes('dashboard'))throw Error('广告未按展示位置请求');
  return {success:true,publicHome:true,loginNavigation:true,adPlacements:true,personalConfig:true,testDoesNotSave:true,
    saveAndReload:true,systemSettingsTabs:6,mobile:true,realWrites:0};
}
