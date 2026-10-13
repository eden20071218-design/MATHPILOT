const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

test('Service Worker push handler works without window/document and deduplicates', async () => {
  const handlers = {}, seen = new Map(), notifications = [], receipts = [];
  const context = {
    self: { location:{origin:'https://mathpilot.test'}, addEventListener:(name,fn)=>handlers[name]=fn,
      registration:{showNotification:async(title,options)=>notifications.push({title,...options})},
      clients:{matchAll:async()=>[],claim:async()=>{},openWindow:async()=>{}},skipWaiting:async()=>{} },
    caches:{open:async()=>({match:async key=>seen.get(key.url),put:async(key,val)=>seen.set(key.url,val),keys:async()=>[],delete:async()=>{}})},
    URL, Request, Response, setTimeout,
    fetch:async(url,options)=>{receipts.push(JSON.parse(options.body));return {ok:true};},
  };
  vm.runInNewContext(fs.readFileSync('public/sw.js','utf8'),context);
  const data={title:'学习提醒',body:'复习时间',tag:'same-task',receipt_url:'https://mathpilot.test/api/v1/reminders/receipts',receipt_token:'test-token'};
  for(let i=0;i<2;i++) {let done;handlers.push({data:{json:()=>data},waitUntil:p=>done=p});await done;}
  assert.equal(notifications.length,1);
  assert.equal(receipts[0].open_windows,0);
  assert.equal(notifications[0].renotify,false);
});
