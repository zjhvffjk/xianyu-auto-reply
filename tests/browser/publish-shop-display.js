async (page) => {
  const errors=[],checks=[],writes=[];let accountFailure=false,emptyAccounts=false;
  page.setDefaultTimeout(5000);page.on('pageerror',error=>errors.push(error.message));
  const accounts=[{pk:1,id:'2217291130670',member_name:'xy_first',nickname:'星集资源',remark:'私有备注A',enabled:true,online:true},
    {pk:2,id:'2220000000000',member_name:'xy_second',nickname:'星集资源',remark:'私有备注B',enabled:false,online:false},
    {pk:3,id:'no-name-shop',member_name:'xy_plain',nickname:'',remark:'不可冒充昵称',enabled:true}];
  const material={id:11,title:'选择店铺回归素材',price:'1.01',quantity:1,category:'其他闲置',condition:'全新',
    images:[],videos:[],source_account_id:'2217291130670',source_item_id:'original-item'};
  const logs=[['2217291130670','昵称测试A'],['2220000000000','昵称测试B'],['no-name-shop','会员名回退'],['removed-shop','已删除账号回退']]
    .map(([account_id,title],i)=>({id:i+1,user_id:9,username:'test-only',account_id,title,price:'1.01',status:'success',created_at:'2026-11-01T02:00:00+08:00'}));
  logs.push({id:5,user_id:9,username:'test-only',account_id:'historical-removed-shop',account_nickname:'芋圆奶茶',title:'历史账号昵称快照',price:'1.01',status:'success',created_at:'2026-11-01T02:00:00+08:00'});
  await page.context().route('**/api/**',async route=>{
    const request=route.request(),url=new URL(request.url());let result={success:true,data:{}};
    if(url.pathname.endsWith('/auth/verify'))result={authenticated:true,user_id:9,username:'店铺显示测试',is_admin:true};
    else if(url.pathname.endsWith('/cookies/options')){
      if(accountFailure){await route.fulfill({status:503,contentType:'application/json',body:'{}'});return;}
      result=emptyAccounts?[]:accounts;
    }
    else if(url.pathname.endsWith('/product-publish/materials'))result={success:true,data:{list:[material],total:1,page:1,page_size:10,total_pages:1}};
    else if(url.pathname.endsWith('/publish/batches'))result={success:true,data:{list:[],total:0,page:1,page_size:10}};
    else if(url.pathname.endsWith('/product-publish/logs'))result={success:true,data:{list:logs,total:logs.length,page:1,page_size:20,total_pages:1}};
    else if(url.pathname.endsWith('/publish/batch/check')&&request.method()==='POST'){
      const data=request.postDataJSON();checks.push(data);
      result={success:true,data:{fingerprint:'test-only',total:data.account_ids.length,ready:true,duplicate_count:0,
        items:data.account_ids.map(account_id=>({account_id,material_id:11,title:material.title,errors:[],success_count:0,uncertain:false}))}};
    }else if(url.pathname.includes('user-settings'))result={success:true,value:'true'};
    else if(url.pathname.includes('announcements'))result={success:true,data:[]};
    else if(request.method()!=='GET'){writes.push(url.pathname);throw Error('不应提交真实任务：'+url.pathname);}
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});
  });
  await page.context().addInitScript(()=>{
    localStorage.setItem('auth-storage',JSON.stringify({state:{token:'test-only',refreshToken:'test-only',isAuthenticated:true},version:2}));
    localStorage.setItem('auth_token','test-only');localStorage.setItem('user_info',JSON.stringify({user_id:9,username:'店铺显示测试',is_admin:true}));
    localStorage.setItem('shop-selections-v2',JSON.stringify({state:{selections:{9:{accountId:'2217291130670',label:'xy_first · 星集资源'}}},version:0}));
  });
  await page.setViewportSize({width:1440,height:982});await page.goto('http://127.0.0.1:9001/product-publish/batch');
  const trigger=page.getByRole('button',{name:'发布目标店铺',exact:true});await trigger.waitFor();
  if(await page.getByRole('heading',{name:'发布目标店铺',exact:true}).count())throw Error('仍保留占位的大块店铺区域');
  await trigger.click();const menu=page.getByRole('dialog',{name:'选择发布目标店铺',exact:true});
  const first=menu.getByRole('checkbox',{name:'发布到 xy_first · 星集资源',exact:true});
  await first.waitFor();if(!await first.isChecked())throw Error('没有沿用当前店铺作为默认发布目标');
  await menu.getByRole('checkbox',{name:'发布到 xy_second · 星集资源',exact:true}).check();
  await menu.getByPlaceholder('搜索店铺昵称或账号').fill('xy_second');
  if(await first.count())throw Error('店铺搜索没有过滤列表');
  await menu.getByPlaceholder('搜索店铺昵称或账号').press('Escape');await menu.waitFor({state:'hidden'});
  await page.getByRole('checkbox',{name:'选择素材 11',exact:true}).check();
  const source=page.getByRole('combobox',{name:'素材来源店铺',exact:true});
  if(await source.inputValue()!=='2217291130670')throw Error('选择发布目标改变了素材来源');
  await page.getByRole('button',{name:'检查并预览发布',exact:true}).click();
  await page.getByRole('button',{name:'确认发布 2 件商品',exact:true}).waitFor();
  if(JSON.stringify(checks[0])!==JSON.stringify({account_ids:['2217291130670','2220000000000'],material_ids:[11]}))throw Error('显示名替代了原始发布ID');
  await trigger.click();await menu.getByRole('checkbox',{name:'发布到 xy_second · 星集资源',exact:true}).uncheck();
  await page.getByRole('heading',{name:'批量发布',exact:true}).click();await menu.waitFor({state:'hidden'});
  if(await page.getByRole('button',{name:/^确认发布 /}).count())throw Error('切换目标后旧的发布检查仍可提交');
  await page.setViewportSize({width:390,height:844});await trigger.click();
  const box=await menu.boundingBox();if(!box||box.x<0||box.x+box.width>391)throw Error('手机店铺菜单超出视口');
  await page.screenshot({path:'output/playwright/publish-shop-dropdown-mobile.png'});
  await menu.getByRole('button',{name:'清空选择',exact:true}).click();
  if(await first.isChecked())throw Error('清空没有移除目标');
  await menu.getByPlaceholder('搜索店铺昵称或账号').press('Escape');await trigger.click();
  if(await first.isChecked())throw Error('展开后又自动选回当前店铺');
  await first.focus();await first.press('Space');if(!await first.isChecked())throw Error('键盘无法勾选店铺');
  await first.press('Escape');if(!await trigger.evaluate(element=>document.activeElement===element))throw Error('Escape关闭后未恢复焦点');
  await page.goto('http://127.0.0.1:9001/product-publish/logs');
  for(const [title,name,id] of [['昵称测试A','星集资源','2217291130670'],['昵称测试B','星集资源','2220000000000'],['会员名回退','xy_plain','no-name-shop'],['已删除账号回退','removed-shop','removed-shop'],['历史账号昵称快照','芋圆奶茶','historical-removed-shop']]){
    const row=page.getByRole('row').filter({has:page.getByText(title,{exact:true})});await row.waitFor();
    const accountCell=row.getByRole('cell').nth(1);const text=await accountCell.innerText();
    const titleText=await accountCell.locator('[title]').getAttribute('title');
    if(text.trim()!==name||!titleText.includes(id))throw Error('日志昵称或ID提示不正确：'+title);
  }
  await page.setViewportSize({width:1440,height:982});
  await page.getByRole('heading',{name:'发布日志',exact:true}).click({trial:true});
  await page.screenshot({path:'output/playwright/publish-log-nicknames.png'});
  accountFailure=true;await page.goto('http://127.0.0.1:9001/product-publish/batch');
  await trigger.getByText('店铺加载失败',{exact:true}).waitFor();await trigger.click();
  await menu.getByRole('alert').waitFor();accountFailure=false;
  await menu.getByRole('button',{name:'重新加载',exact:true}).click();await first.waitFor();
  if(!await first.isChecked())throw Error('店铺重试未恢复当前默认选择');
  emptyAccounts=true;await page.reload();await trigger.click();
  await menu.getByText('暂无可用店铺，请先添加账号',{exact:true}).waitFor();
  if(writes.length||errors.length)throw Error(JSON.stringify({writes,errors}));
  return {success:true,compactHeader:true,multiShop:true,currentShopDefault:true,search:true,sourceIndependent:true,
    originalIds:true,checkInvalidated:true,outsideAndEscape:true,clearSelectionStable:true,keyboard:true,nicknames:true,fallbacks:true,loadRetry:true,emptyState:true,mobile:true,realPublishRequests:0};
}
