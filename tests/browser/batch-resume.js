async (page) => {
  page.setDefaultTimeout(5000);
  const context=page.context(),errors=[],writes=[];
  let failure=false,release=null,started;
  const base={mode:'immediate',total:3,success:0,failed:0,publishing:0,pending:2,cancelled:0,unknown:1,
    start_at:'2026-11-07T00:00:00+08:00',next_run_at:null,interval_seconds:300,cancel_requested:false,
    account_ids:['test-shop'],account_statuses:[],items:[],finished:false,can_delete_history:false};
  let jobs=[{...base,batch_id:'paused-test',status:'attention',can_resume:true},
    {...base,batch_id:'cancelled-test',status:'cancelled',cancel_requested:true,pending:0,finished:true,can_resume:false},
    {...base,batch_id:'no-pending-test',status:'attention',pending:0,can_resume:false}];
  page.on('pageerror',error=>errors.push(error.message));
  await context.route('**/api/**',async route=>{
    const req=route.request(),url=new URL(req.url());let result={success:true,data:{}};
    if(url.pathname.endsWith('/auth/verify')) result={authenticated:true,user_id:9,username:'继续任务测试',is_admin:false};
    else if(url.pathname.endsWith('/cookies/options')) result=[{id:'test-shop',pk:1,nickname:'测试店铺',enabled:true}];
    else if(url.pathname.endsWith('/publish/batches')) result={success:true,data:{list:jobs,total:jobs.length,page:1,page_size:10}};
    else if(url.pathname.endsWith('/paused-test/resume')) {
      writes.push(req.method());
      if(failure) result={success:false,message:'任务已取消，请刷新后查看'};
      else {
        if(started) await new Promise(resolve=>{release=resolve;started();});
        jobs=jobs.map(job=>job.batch_id==='paused-test'?{...job,status:'waiting',can_resume:false,next_run_at:'2026-11-07T00:05:00+08:00'}:job);
        result={success:true,message:'已继续尚未开始的商品，待核查项不会自动重发',data:jobs[0]};
      }
    } else if(url.pathname.endsWith('/product-publish/materials')) result={success:true,data:{list:[],total:0,page:1,page_size:10,total_pages:0}};
    else if(url.pathname.includes('user-settings')) result={success:true,value:'true'};
    else if(url.pathname.includes('announcements')) result={success:true,data:[]};
    else if(req.method()!=='GET') throw Error('不应执行的写操作：'+url.pathname);
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});
  });
  await context.addInitScript(()=>{
    localStorage.setItem('auth-storage',JSON.stringify({state:{token:'test-only',refreshToken:'test-only',isAuthenticated:true},version:2}));
    localStorage.setItem('auth_token','test-only');localStorage.setItem('user_info',JSON.stringify({user_id:9,username:'继续任务测试',is_admin:false}));
  });
  await page.goto('http://127.0.0.1:9001/product-publish/batch');
  const section=page.locator('section').filter({has:page.getByRole('heading',{name:'发布任务列表',exact:true})});
  const button=section.getByRole('button',{name:'继续剩余',exact:true});
  await button.waitFor();
  if(await button.count()!==1||writes.length) throw Error('恢复入口错误或自动恢复了历史任务');
  await button.click();
  const dialog=page.getByRole('dialog',{name:'继续剩余商品'});
  await dialog.getByText(/待核查.*不会自动重发/).waitFor();
  await dialog.getByRole('button',{name:'取消',exact:true}).click();
  if(writes.length) throw Error('取消确认仍恢复任务');
  failure=true;await button.click();await dialog.getByRole('button',{name:'确认继续',exact:true}).click();
  await page.getByText('任务已取消，请刷新后查看',{exact:true}).first().waitFor();
  if(writes.length!==1) throw Error('失败后自动重试了恢复');
  failure=false;const pending=new Promise(resolve=>{started=resolve;});
  await dialog.getByRole('button',{name:'确认继续',exact:true}).click();await pending;
  if(!await dialog.getByRole('button',{name:'确认继续',exact:true}).isDisabled()) throw Error('请求中可重复提交');
  release();await button.waitFor({state:'hidden'});
  await section.getByText('等待执行',{exact:true}).waitFor();
  if(writes.length!==2||jobs[0].unknown!==1||errors.length) throw Error('恢复修改了未知项或出现浏览器错误');
  return {success:true,confirmation:true,noAutomaticResume:true,unknownKept:true,duplicateProtected:true,ownerCancelledNotResumed:true,realWrites:0};
}
