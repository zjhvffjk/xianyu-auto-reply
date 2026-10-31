async (page) => {
  const context=page.context(),errors=[],writes=[];
  page.setDefaultTimeout(5000);
  let failure='',holdDelete=null,notifyDeleteStart;
  const base={mode:'scheduled',total:2,success:2,failed:0,publishing:0,pending:0,cancelled:0,unknown:0,
    start_at:'2099-01-01T10:00:00+08:00',next_run_at:null,interval_seconds:60,cancel_requested:false,
    account_ids:['test-shop'],account_statuses:[],items:[]};
  let jobs=Array.from({length:18},(_,i)=>({...base,batch_id:`finished-${String(i+1).padStart(2,'0')}`,
    status:'completed',finished:true,can_delete_history:true}));
  jobs.splice(4,0,...['waiting','running','cancelling','unknown','claimed','pending'].map(state=>({...base,
    batch_id:'protected-'+state,status:state==='unknown'?'cancelled':state==='claimed'||state==='pending'?'completed':state,
    finished:['unknown','claimed','pending'].includes(state),unknown:state==='unknown'?1:0,
    pending:['waiting','pending'].includes(state)?1:0,publishing:state==='running'?1:0,can_delete_history:false})));
  const original=[...jobs];
  const watch=p=>p.on('pageerror',error=>errors.push(error.message));watch(page);
  await context.route('**/api/**',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    let result={success:true,data:{}};
    if(url.pathname.endsWith('/auth/verify')) result={authenticated:true,user_id:9,username:'任务删除测试',is_admin:false};
    else if(url.pathname.endsWith('/cookies/options')) result=[{id:'test-shop',pk:1,nickname:'测试店铺',enabled:true}];
    else if(url.pathname.endsWith('/publish/batches/delete-history')&&method==='POST') {
      const ids=request.postDataJSON().batch_ids;writes.push(ids);
      if(failure==='network') {await route.abort('failed');return;}
      if(failure==='business') result={success:false,message:'测试删除失败'};
      else {
        if(holdDelete) await new Promise(resolve=>{holdDelete=resolve;notifyDeleteStart();});
        const kept=jobs.filter(job=>!ids.includes(job.batch_id)||!job.can_delete_history);
        const cleared=jobs.length-kept.length;jobs=kept;
        result={success:true,message:`已删除 ${cleared} 个任务历史，商品和发布日志保留`,
          data:{cleared_batches:cleared,retained_batches:ids.length-cleared,unavailable_batches:0}};
      }
    } else if(url.pathname.endsWith('/publish/batches')) {
      const p=Number(url.searchParams.get('page')||1),size=Number(url.searchParams.get('page_size')||10);
      result={success:true,data:{list:jobs.slice((p-1)*size,p*size),total:jobs.length,page:p,page_size:size}};
    } else if(url.pathname.endsWith('/product-publish/logs')) result={success:true,data:{list:[{
      id:1,user_id:9,account_id:'test-shop',title:'删除任务后保留的发布日志',price:'1.01',status:'success',
      created_at:'2026-11-01T10:00:00+08:00'}],total:1,page:1,page_size:20,total_pages:1}};
    else if(url.pathname.endsWith('/product-publish/materials')) result={success:true,data:{list:[],total:0,page:1,page_size:10,total_pages:0}};
    else if(url.pathname.includes('user-settings')) result={success:true,value:'true'};
    else if(url.pathname.includes('announcements')) result={success:true,data:[]};
    else if(method!=='GET') throw Error('不应发起写操作：'+url.pathname);
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});
  });
  await context.addInitScript(()=>{
    localStorage.setItem('auth-storage',JSON.stringify({state:{token:'test-only',refreshToken:'test-only',isAuthenticated:true},version:2}));
    localStorage.setItem('auth_token','test-only');localStorage.setItem('user_info',JSON.stringify({user_id:9,username:'任务删除测试',is_admin:false}));
  });
  await page.setViewportSize({width:1440,height:982});await page.goto('http://127.0.0.1:9001/product-publish/batch');
  const history=p=>p.locator('section').filter({has:p.getByRole('heading',{name:'发布任务列表',exact:true})});
  const section=history(page),box=id=>section.getByRole('checkbox',{name:'选择任务历史 '+id,exact:true});
  await box('finished-01').waitFor();
  for(const state of ['waiting','running','cancelling','unknown','claimed','pending']) {
    if(!await box('protected-'+state).isDisabled()) throw Error('保护状态仍可勾选：'+state);
  }
  await section.getByRole('checkbox',{name:'选择本页可删除任务',exact:true}).check();
  await section.getByRole('button',{name:'删除所选（4）',exact:true}).waitFor();
  await section.getByRole('checkbox',{name:'选择本页可删除任务',exact:true}).uncheck();
  await box('finished-01').check();await section.getByRole('button',{name:'删除所选（1）',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'删除所选任务历史'});
  await dialog.getByRole('button',{name:'取消',exact:true}).click();
  if(writes.length) throw Error('取消确认仍调用删除');
  await section.getByRole('button',{name:'下一页',exact:true}).click();
  await box('finished-05').waitFor();await section.getByRole('button',{name:'删除所选（0）',exact:true}).waitFor();
  await section.getByRole('combobox').selectOption('100');await box('finished-01').waitFor();
  await box('finished-01').check();await box('finished-02').check();
  failure='business';await section.getByRole('button',{name:'删除所选（2）',exact:true}).click();
  await dialog.getByRole('button',{name:'确认删除',exact:true}).click();
  await page.getByText('测试删除失败',{exact:true}).first().waitFor();
  if(writes.length!==1) throw Error('失败时重复发送删除');
  if(!await box('finished-01').isChecked()||!await box('finished-02').isChecked()) throw Error('失败丢失选择');
  failure='network';await dialog.getByRole('button',{name:'确认删除',exact:true}).click();
  await page.getByText('删除结果未确认，请刷新任务列表核查；未取消任何发布任务',{exact:true}).first().waitFor();
  if(writes.length!==2||!await box('finished-01').isChecked()) throw Error('断网重试写入或丢失选择');
  await dialog.getByRole('button',{name:'取消',exact:true}).click();
  const other=await context.newPage();watch(other);other.setDefaultTimeout(5000);
  await other.goto('http://127.0.0.1:9001/product-publish/batch');await history(other).getByRole('checkbox',{name:'选择任务历史 finished-01',exact:true}).waitFor();
  failure='';holdDelete=true;
  const deleteStarted=new Promise(resolve=>{notifyDeleteStart=resolve;});
  await section.getByRole('button',{name:'删除所选（2）',exact:true}).click();
  await dialog.getByRole('button',{name:'确认删除',exact:true}).click();
  await deleteStarted;
  await dialog.getByRole('button',{name:'取消',exact:true}).isDisabled().then(disabled=>{if(!disabled)throw Error('删除中可取消弹窗');});
  await dialog.getByRole('button',{name:'确认删除',exact:true}).isDisabled().then(disabled=>{if(!disabled)throw Error('删除中允许重复提交');});
  if(typeof holdDelete!=='function') throw Error('缺少受控删除请求');holdDelete();holdDelete=null;
  await box('finished-01').waitFor({state:'hidden'});await box('finished-02').waitFor({state:'hidden'});
  await history(other).getByRole('checkbox',{name:'选择任务历史 finished-01',exact:true}).waitFor({state:'hidden'});
  await box('finished-03').waitFor();await section.getByRole('button',{name:'删除所选（0）',exact:true}).waitFor();
  if(JSON.stringify(writes.at(-1))!==JSON.stringify(['finished-01','finished-02'])) throw Error('删除范围不是所选记录');
  if(jobs.filter(job=>job.batch_id.startsWith('protected-')).length!==6) throw Error('保护任务被移除');
  await page.reload();await box('finished-03').waitFor();if(await box('finished-01').count()) throw Error('刷新后记录恢复');
  await page.setViewportSize({width:390,height:844});await box('finished-03').check();
  await section.getByRole('button',{name:'删除所选（1）',exact:true}).click();await dialog.waitFor();
  await dialog.getByRole('button',{name:'确认删除',exact:true}).click({trial:true});
  await page.screenshot({path:'output/playwright/batch-history-delete-mobile.png'});
  await dialog.getByRole('button',{name:'取消',exact:true}).click();
  await other.goto('http://127.0.0.1:9001/product-publish/logs');await other.getByText('删除任务后保留的发布日志',{exact:true}).waitFor();
  await other.close();
  if(writes.length!==3||jobs.length!==original.length-2) throw Error('删除次数或剩余记录数量异常');
  if(errors.length) throw Error(errors.join('; '));
  return {success:true,selectedOnly:true,protectedStates:6,currentPageSelection:true,confirmation:true,
    failureKeepsSelection:true,doubleSubmitProtected:true,crossTab:true,reloadStable:true,logsKept:true,mobile:true,realWrites:0};
}
