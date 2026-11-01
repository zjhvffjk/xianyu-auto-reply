async (page) => {
  const context=page.context(),errors=[],writes=[],results=[];
  page.setDefaultTimeout(5000);page.on('pageerror',error=>errors.push(error.message));
  const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
  let scenario;
  await context.addInitScript(()=>{
    const userId=Number(new URL(location.href).searchParams.get('test_user')||9);
    localStorage.setItem('auth-storage',JSON.stringify({state:{token:'bootstrap-test-only',refreshToken:'test-only',isAuthenticated:true},version:2}));
    localStorage.setItem('auth_token','bootstrap-test-only');
    localStorage.setItem('refresh_token','test-only');
    localStorage.setItem('user_info',JSON.stringify({user_id:userId,username:'加载回归',is_admin:false}));
  });
  const handler=async route=>{
    const current=scenario,request=route.request(),url=new URL(request.url()),path=url.pathname;
    let result={success:true,data:{}};
    if(path.endsWith('/auth/verify')){
      current.authStarted.resolve();await current.auth.promise;
      result={authenticated:!current.invalid,user_id:current.userId,username:'加载回归',is_admin:false};
    }else if(path==='/api/v1/auth/refresh'){
      current.refreshCalls++;current.refreshStarted.resolve();await current.refreshGate.promise;
      result={success:true,token:'bootstrap-refreshed',refresh_token:'test-only-refreshed',user_id:current.userId,username:'加载回归',is_admin:false};
    }else if(path==='/api/v1/system-settings/public')result={};
    else if(path==='/api/v1/system-settings'){
      current.settingsCalls++;current.settingsStarted.resolve();await current.settings.promise;
      if(current.refresh&&request.headers().authorization!=='Bearer bootstrap-refreshed'){
        await route.fulfill({status:401,contentType:'application/json',body:'{}'});return;
      }
      if(current.settingsFail&&current.settingsCalls===1){await route.fulfill({status:503,contentType:'application/json',body:'{}'});return;}
      // 设置接口直接返回键值字典，由前端API再封装success/data。
      result={'login.system_name':current.name,'navigation.hidden_menu_keys':['items'],
        'theme.color_preset':'amber','theme.font_family':'system','disclaimer.title':'加载回归声明',
        'disclaimer.content':'测试声明内容','disclaimer.checkbox_text':'已阅读测试声明',
        'disclaimer.agree_button_text':'同意测试声明','disclaimer.disagree_button_text':'退出测试声明'};
    }else if(path.endsWith('/user-settings/disclaimer_agreed')){
      if(request.method()==='PUT'){
        writes.push({case:current.id,path});result={success:true,value:'true'};
      }else{
        current.disclaimerCalls++;current.disclaimerStarted.resolve();await current.disclaimer.promise;
        if(current.refresh&&request.headers().authorization!=='Bearer bootstrap-refreshed'){
          await route.fulfill({status:401,contentType:'application/json',body:'{}'});return;
        }
        if(current.disclaimerFail){await route.abort('failed');return;}
        result={success:true,value:current.pending?'false':'true'};
      }
    }else if(path.endsWith('/cookies/options'))result=[];
    else if(path.endsWith('/product-publish/materials'))result={success:true,data:{list:[],total:0,page:1,page_size:10,total_pages:0}};
    else if(path.endsWith('/publish/batches'))result={success:true,data:{list:[],total:0,page:1,page_size:10}};
    else if(path.includes('announcements'))result={success:true,data:[]};
    else if(request.method()!=='GET')throw Error('不应发起业务写入：'+path);
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});
  };
  await context.route('**/api/**',handler);
  const heading=page.getByRole('heading',{name:'批量发布',exact:true});
  const start=async(id,options={})=>{
    scenario={id,name:'加载系统'+id,userId:9,settingsCalls:0,disclaimerCalls:0,refreshCalls:0,
      auth:deferred(),settings:deferred(),disclaimer:deferred(),authStarted:deferred(),settingsStarted:deferred(),disclaimerStarted:deferred(),...options};
    scenario.refreshGate=deferred();scenario.refreshStarted=deferred();
    await page.goto(`http://127.0.0.1:9001/product-publish/batch?test_user=${scenario.userId}`);
    await scenario.authStarted.promise;
    if(scenario.settingsCalls||scenario.disclaimerCalls)throw Error('鉴权完成前请求了私有初始化数据');
    scenario.auth.resolve();
    return scenario;
  };
  const awaitParallel=async current=>{
    let timer;
    try{
      await Promise.race([Promise.all([current.settingsStarted.promise,current.disclaimerStarted.promise]),
        new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('初始化仍为串行：免责声明未返回时系统设置尚未发起')),1200);})]);
    }finally{clearTimeout(timer);}
  };
  const verifyVisible=async current=>{
    await heading.waitFor();await page.getByText(current.name,{exact:true}).first().waitFor();
    if(current.settingsCalls!==((current.settingsFail||current.refresh)?2:1))throw Error('系统设置重复请求或失败重试丢失：'+current.settingsCalls);
    if(!current.settingsFail&&await page.getByRole('link',{name:'商品管理',exact:true}).count())throw Error('隐藏菜单设置未生效');
  };
  try{
    let current=await start('A');await awaitParallel(current);
    let responded=page.waitForResponse(response=>response.url().includes('/user-settings/disclaimer_agreed'));
    current.disclaimer.resolve();await responded;
    if(await heading.count())throw Error('系统设置未完成就放行了页面');
    current.settings.resolve();await verifyVisible(current);
    if(await page.evaluate(()=>document.documentElement.dataset.themeColorPreset)!=='amber')throw Error('初始化主题设置未保留');
    await page.evaluate(()=>window.dispatchEvent(new CustomEvent('login-branding-updated',{detail:{'login.system_name':'实时更新系统名'}})));
    await page.getByText('实时更新系统名',{exact:true}).first().waitFor();
    results.push({case:'parallel-and-name-update',settingsRequests:current.settingsCalls});

    current=await start('B',{userId:10});await awaitParallel(current);
    responded=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/v1/system-settings');
    current.settings.resolve();await responded;
    if(await heading.count())throw Error('免责声明未检查就放行了页面');
    current.disclaimer.resolve();await verifyVisible(current);
    if(await page.getByText('实时更新系统名',{exact:true}).count())throw Error('沿用了上一用户的设置快照');
    results.push({case:'reverse-order-and-new-user',settingsRequests:current.settingsCalls});

    current=await start('pending',{pending:true});await awaitParallel(current);
    current.settings.resolve();current.disclaimer.resolve();
    await page.getByRole('heading',{name:'加载回归声明',exact:true}).waitFor();
    if(await heading.count())throw Error('未同意声明就展示了业务页面');
    const agree=page.getByRole('button',{name:'同意测试声明',exact:true});
    if(!await agree.isDisabled())throw Error('未勾选确认即可同意声明');
    await page.getByRole('checkbox',{name:'已阅读测试声明',exact:true}).check();await agree.click();
    await verifyVisible(current);results.push({case:'consent-still-required',settingsRequests:current.settingsCalls});

    current=await start('disclaimer-failure',{disclaimerFail:true});await awaitParallel(current);
    current.settings.resolve();current.disclaimer.resolve();
    await page.getByRole('heading',{name:'加载回归声明',exact:true}).waitFor();
    if(await heading.count())throw Error('声明请求失败时跳过了确认');
    await page.getByRole('button',{name:'退出测试声明',exact:true}).click();
    await page.waitForURL(url=>url.pathname==='/login');results.push({case:'consent-failure-and-decline'});

    current=await start('settings-retry',{settingsFail:true});await awaitParallel(current);
    current.settings.resolve();current.disclaimer.resolve();await verifyVisible(current);
    results.push({case:'existing-settings-retry',settingsRequests:current.settingsCalls});

    current=await start('token-refresh',{refresh:true});await awaitParallel(current);
    const rejected=Promise.all([
      page.waitForResponse(response=>new URL(response.url()).pathname==='/api/v1/system-settings'&&response.status()===401),
      page.waitForResponse(response=>response.url().includes('/user-settings/disclaimer_agreed')&&response.status()===401),
    ]);
    current.settings.resolve();current.disclaimer.resolve();await rejected;
    await current.refreshStarted.promise;current.refreshGate.resolve();await verifyVisible(current);
    if(current.refreshCalls!==1||current.disclaimerCalls!==2)throw Error('并行401未共用一次刷新并恢复原请求');
    results.push({case:'parallel-401-single-refresh',refreshRequests:current.refreshCalls});

    current=await start('invalid',{invalid:true});current.settings.resolve();current.disclaimer.resolve();
    await page.waitForURL(url=>url.pathname==='/login');
    if(current.settingsCalls||current.disclaimerCalls)throw Error('无效登录仍读取私有设置');
    results.push({case:'invalid-auth-blocked'});
    if(writes.length!==1||writes[0].case!=='pending')throw Error('发生了预期声明同意之外的写入');
    if(errors.length)throw Error(errors.join('; '));
    return {success:true,parallel:true,bothChecksGatePage:true,settingsReuseScopedToMount:true,brandingEvent:true,hiddenMenu:true,
      consentRequired:true,authFailureBlocked:true,settingsRetry:true,results,realWrites:0};
  }finally{
    scenario?.auth.resolve();scenario?.settings.resolve();scenario?.disclaimer.resolve();
    scenario?.refreshGate.resolve();
  }
}
