async (page) => {
  const context=page.context(), errors=[], writes=[];
  let cleared=false, allEnded=false;
  const watch=p=>{p.on('pageerror',e=>errors.push(e.message));p.on('console',m=>{if(m.type()==='error') errors.push(m.text())})};
  watch(page);
  const log=(id,status)=>({id,user_id:9,account_id:'test-shop',title:'清空测试素材'+id,price:'1.01',status,
    created_at:'2026-10-31T10:00:00+08:00',updated_at:'2026-10-31T10:00:00+08:00'});
  const job=(id,status)=>({batch_id:id,mode:'scheduled',status,total:2,success:status==='completed'?2:0,
    failed:0,publishing:0,pending:status==='waiting'?2:0,cancelled:0,unknown:status==='attention'?1:0,
    start_at:'2099-01-01T10:00:00+08:00',next_run_at:null,interval_seconds:60,
    finished:status==='completed',cancel_requested:false,account_ids:['test-shop'],account_statuses:[],items:[]});
  await context.route('**/api/**',async route=>{
    const req=route.request(), url=new URL(req.url());
    let result={success:true,code:200,data:{}};
    if(url.pathname.endsWith('/auth/verify')) result={authenticated:true,user_id:9,username:'清空测试',is_admin:false};
    else if(url.pathname.endsWith('/cookies/options')) result=[{id:'test-shop',pk:1,nickname:'测试店铺',enabled:true}];
    else if(url.pathname.endsWith('/logs/clear')&&req.method()==='DELETE') {
      writes.push(url.pathname);cleared=true;
      result={success:true,message:allEnded?'已清空 2 条已结束发布记录、1 个已结束批量任务':'已清空 2 条已结束发布记录、1 个已结束批量任务；保留 2 条未完成任务或待核查相关记录、2 个任务',
        data:{cleared_logs:2,cleared_batches:1,retained_logs:allEnded?0:2,retained_batches:allEnded?0:2}};
    } else if(url.pathname.endsWith('/product-publish/logs')) {
      const list=[...(!cleared?[log(1,'success'),log(2,'cancelled')]:[]),...(!allEnded?[log(3,'pending'),log(4,'unknown')]:[])];
      result={success:true,data:{list,total:list.length,page:1,page_size:20,total_pages:1}};
    } else if(url.pathname.endsWith('/publish/batches')) {
      const list=[...(!cleared?[job('completed-test','completed')]:[]),...(!allEnded?[job('waiting-test','waiting'),job('unknown-test','attention')]:[])];
      result={success:true,data:{list,total:list.length,page:1,page_size:10}};
    } else if(url.pathname.endsWith('/publish/batch/completed-test/status')) result={success:true,data:{...job('completed-test','completed'),history_cleared:cleared}};
    else if(url.pathname.endsWith('/product-publish/materials')) result={success:true,data:{list:[],total:0,page:1,page_size:10,total_pages:0}};
    else if(url.pathname.includes('user-settings')) result={success:true,value:'true'};
    else if(url.pathname.includes('announcements')) result={success:true,data:[]};
    else if(req.method()!=='GET') throw Error('不应发起的写操作：'+url.pathname);
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});
  });
  await context.addInitScript(()=>{
    localStorage.setItem('auth-storage',JSON.stringify({state:{token:'test-only',refreshToken:'test-only',isAuthenticated:true},version:2}));
    localStorage.setItem('auth_token','test-only');
    localStorage.setItem('user_info',JSON.stringify({user_id:9,username:'清空测试',is_admin:false}));
    sessionStorage.setItem('batch-publish:9','completed-test');
  });
  await page.setViewportSize({width:1440,height:982});
  await page.goto('http://127.0.0.1:9001/product-publish/batch');
  const history=page.locator('section').filter({has:page.getByRole('heading',{name:'发布任务列表',exact:true})});
  await history.getByText('请求号：complete',{exact:true}).waitFor();
  const logsPage=await context.newPage();watch(logsPage);
  await logsPage.setViewportSize({width:1440,height:982});
  await logsPage.goto('http://127.0.0.1:9001/product-publish/logs');
  await logsPage.getByText('清空测试素材1',{exact:true}).waitFor();
  await logsPage.getByRole('button',{name:'清空日志',exact:true}).click();
  let dialog=logsPage.getByRole('dialog',{name:'确认清空日志'});
  if(!(await dialog.innerText()).includes('不限制记录日期')) throw Error('仍有旧10天限制文案');
  await dialog.getByRole('button',{name:'取消',exact:true}).click();
  if(writes.length) throw Error('取消清空也触发写操作');
  await logsPage.getByRole('button',{name:'清空日志',exact:true}).click();
  await logsPage.screenshot({path:'output/playwright/xianyu-history-clear-confirm.png'});
  await dialog.getByRole('button',{name:'确认清空',exact:true}).click();
  await logsPage.getByText('清空测试素材1',{exact:true}).waitFor({state:'hidden'});
  await logsPage.getByText('清空测试素材3',{exact:true}).waitFor();
  await logsPage.getByText('清空测试素材4',{exact:true}).waitFor();
  await history.getByText('请求号：complete',{exact:true}).waitFor({state:'hidden'});
  await history.getByText('请求号：waiting-',{exact:true}).waitFor();
  await history.getByText('请求号：unknown-',{exact:true}).waitFor();
  await page.waitForFunction(()=>sessionStorage.getItem('batch-publish:9')===null);
  if(writes.length!==1) throw Error('清空请求次数不对');
  await logsPage.reload();
  await logsPage.getByText('清空测试素材3',{exact:true}).waitFor();
  if(await logsPage.getByText('清空测试素材1',{exact:true}).count()) throw Error('刷新后旧记录重新出现');
  await logsPage.screenshot({path:'output/playwright/xianyu-history-clear-retained.png'});
  await logsPage.setViewportSize({width:390,height:844});
  await logsPage.getByRole('button',{name:'清空日志',exact:true}).click();
  await logsPage.screenshot({path:'output/playwright/xianyu-history-clear-mobile.png'});
  await dialog.getByRole('button',{name:'取消',exact:true}).click();
  allEnded=true;cleared=false;
  await logsPage.reload();
  await logsPage.getByText('清空测试素材1',{exact:true}).waitFor();
  await logsPage.getByRole('button',{name:'清空日志',exact:true}).click();
  await dialog.getByRole('button',{name:'确认清空',exact:true}).click();
  await logsPage.getByText('暂无发布记录',{exact:true}).waitFor();
  await history.getByText('暂无发布任务，选择素材并检查后可创建',{exact:true}).waitFor();
  if(writes.length!==2) throw Error('额外执行了清空请求');
  await logsPage.close();
  if(errors.length) throw Error(errors.join('; '));
  return {errors,todayHistoryCleared:true,logsRefreshed:true,batchHistorySyncedAcrossTabs:true,
    activeAndUnknownRetained:true,finishedTrackingCleared:true,reloadStable:true,emptyState:true,
    cancelledDialogNoWrite:true,mobile:true,realPublishRequests:0};
}
