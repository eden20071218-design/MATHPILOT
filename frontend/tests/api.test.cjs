const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');
function moduleWith(fetch){
  const events=[];const exports={};
  const output=ts.transpileModule(fs.readFileSync('lib/api.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  vm.runInNewContext(output,{exports,fetch,AbortController,setTimeout,clearTimeout,Intl,Date,Event,window:{dispatchEvent:e=>events.push(e.type)}});
  return {...exports,events};
}
test('API sends same-origin cookie credentials, no-store and CSRF header',async()=>{
  let request;const api=moduleWith(async(path,options)=>{request={path,options};return {ok:true,status:200,json:async()=>({saved:true})};});
  assert.equal((await api.api('/student/settings','PUT',{test:1})).saved,true);
  assert.equal(request.path,'/api/v1/student/settings');assert.equal(request.options.credentials,'same-origin');
  assert.equal(request.options.headers['X-MathPilot-Request'],'1');assert.equal(request.options.cache,'no-store');
});
test('API preserves validation errors and expired-session event',async()=>{
  const api=moduleWith(async()=>({ok:false,status:401,json:async()=>({detail:'登录已失效'})}));
  await assert.rejects(api.api('/student/overview'),/登录已失效/);
  assert.deepEqual(api.events,['mathpilot:expired']);
});
test('incorrect login shows error without recursive expired redirect',async()=>{
  const api=moduleWith(async()=>({ok:false,status:401,json:async()=>({detail:'邮箱或密码不正确'})}));
  await assert.rejects(api.api('/auth/login','POST',{}),/邮箱或密码不正确/);assert.equal(api.events.length,0);
});
test('Pydantic details become actionable field messages',async()=>{
  const api=moduleWith(async()=>({ok:false,status:422,json:async()=>({detail:[{msg:'Value error, 总分不一致'}]})}));
  await assert.rejects(api.api('/student/exams','POST',{}),/总分不一致/);
});
test('network failures are readable and empty 204 is handled',async()=>{
  await assert.rejects(moduleWith(async()=>{throw new TypeError('Failed to fetch')}).api('/auth/me'),/无法连接服务/);
  assert.equal(await moduleWith(async()=>({ok:true,status:204})).api('/auth/logout','POST'),undefined);
});
test('calendar dates and hours honor student timezone and DST',()=>{
  const api=moduleWith(()=>{});
  assert.equal(api.localDay('2026-10-13T18:00:00Z','Asia/Shanghai'),'2026-10-14');
  assert.equal(api.localDay('2026-10-13T02:00:00Z','America/New_York'),'2026-10-12');
  assert.equal(api.clock('2026-11-01T06:30:00Z','America/New_York'),'01:30');
});
