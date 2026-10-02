// Run with ego-browser against resource_convergence.py --serve; see resource_convergence.md.
import fs from 'node:fs/promises';
export async function verifyChatPicker(p, root) {
 const {token}=JSON.parse(await fs.readFile(root+'/browser/browser-session.json','utf8'));
 const control=async changes=>p.evaluate(async({token,changes})=>{
  const csrf=document.cookie.split('; ').find(v=>v.startsWith('tg-signer-csrf='))?.split('=')[1];
  const r=await fetch('/__e2e/control',{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf||'')},body:JSON.stringify(changes)});
  if(!r.ok)throw Error(await r.text());return r.json();
 },{token,changes});
 const results={};
 const state=()=>p.evaluate(()=>({ids:[...document.querySelectorAll('[data-chat-id]')].map(e=>Number(e.dataset.chatId)),selects:document.querySelectorAll('[data-chat-picker] select').length,manual:document.querySelector('input[placeholder="手动输入 Chat ID..."]')?.value}));
 let s=await state(); if(s.ids.length!==50||s.selects!==0)throw Error(JSON.stringify(s));
 results.first_page=s;
 await p.click('text="下一页"');await p.waitForSelector('[data-chat-id="51"]');
 s=await state();if(s.ids.length!==50||s.ids[0]!==51)throw Error(JSON.stringify(s));results.second_page=s;
 await p.fill('#chat-picker-search','Chat 199');await p.waitForSelector('[data-chat-id="200"]');
 s=await state();if(s.ids.length!==1)throw Error(JSON.stringify(s));
 await p.click('[data-chat-id="200"]');
 s=await state();if(s.manual!=='200')throw Error(JSON.stringify(s));results.selection=s;
 await p.fill('#chat-picker-search','');await p.waitForSelector('[data-chat-id="1"]');
 s=await state();if(s.manual!=='200')throw Error('selected chat lost');
 await control({search_delay:1,reset:true});
 await p.fill('#chat-picker-search','Chat 010');
 await new Promise(resolve => setTimeout(resolve, 400));
 await p.fill('#chat-picker-search','Chat 199');await p.waitForSelector('[data-chat-id="200"]');
 s=await state();if(s.ids.length!==1||s.ids[0]!==200)throw Error('stale search overwrote results');results.changed_search=s;
 await p.fill('#chat-picker-search','Chat 011');
 await new Promise(r=>setTimeout(r,400));
 await p.click('button[aria-label="Close modal"]');
 await p.waitForSelector('[data-chat-picker]',{state:'detached'});
 await control({search_delay:0});
 await p.click('text="新增任务"');await p.waitForSelector('[data-chat-id="1"]');
 s=await state();if(s.ids.length!==50)throw Error('reopened dialog has stale rows');results.reopen=s;
 await control({fail_refresh:true});await p.click('text="刷新列表"');
 await p.waitForFunction(()=>[...document.querySelectorAll('[data-chat-picker] button')].some(b=>b.textContent==='刷新列表'&&!b.disabled));
 await p.waitForSelector('[data-chat-id="1"]');
 s=await state();if(s.ids.length!==50)throw Error('failed refresh discarded cached page');
 await p.click('text="下一页"');await p.waitForSelector('[data-chat-id="51"]');
 await p.fill('#chat-picker-search','Chat 199');await p.waitForSelector('[data-chat-id="200"]');
 await p.click('[data-chat-id="200"]');
 s=await state();if(s.manual!=='200'||s.ids.length!==1)throw Error('cached selection unavailable during refresh failure');
 results.refresh_failure_cached_selection=s;
 await control({search_delay:1});
 await p.fill('#chat-picker-search','Chat 012');
 await new Promise(resolve=>setTimeout(resolve,400));
 await p.click('text="刷新列表"');await p.waitForSelector('[data-chat-id="13"]');
 s=await state();if(s.ids.length!==1||s.manual!=='200')throw Error('refresh failure stranded pending search');
 results.refresh_failure_pending_search=s;
 await control({search_delay:0});
 await p.fill('#chat-picker-search','');await p.waitForSelector('[data-chat-id="1"]');
 await control({fail_refresh:false});await p.click('text="刷新列表"');await p.waitForSelector('[data-chat-id="1"]');
 results.refresh_retry=await state();
 await p.fill('input[placeholder="手动输入 Chat ID..."]','-100123456');
 await p.fill('#chat-picker-search','Chat 199');await p.waitForSelector('[data-chat-id="200"]');
 s=await state();if(s.manual!=='-100123456')throw Error('manual chat overwritten');results.manual_preserved=s;
 results.requests=(await control({})).requests;
 if(results.requests.some(x=>!x.includes('/search?')&&!x.includes('include_items=false')))throw Error('full chat payload requested');
 await fs.writeFile(root+'/browser-result.json',JSON.stringify(results,null,2));
 await fs.writeFile(root+'/browser.snapshot.txt',await p.snapshot({scope:'full_page'}));
 console.log({first:results.first_page.ids.length,second:results.second_page.ids.length,selected:results.selection.manual,staleSafe:true,refreshRetry:true,manualPreserved:true,requests:results.requests});
}

export async function verifyChatPickerRaces(p, root) {
 const {token}=JSON.parse(await fs.readFile(root+'/browser/browser-session.json','utf8'));
 const control=changes=>p.evaluate(async({token,changes})=>{
  const csrf=document.cookie.split('; ').find(v=>v.startsWith('tg-signer-csrf='))?.split('=')[1];
  const r=await fetch('/__e2e/control',{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(csrf||'')},body:JSON.stringify(changes)});
  if(!r.ok)throw Error(await r.text());return r.json();
 },{token,changes});
 await p.evaluate(()=>{
  window.__chatAborts=[];const original=window.fetch;
  window.fetch=function(input,options){
   const url=String(input);if(url.includes('/search?'))options?.signal?.addEventListener('abort',()=>window.__chatAborts.push(url),{once:true});
   return original.call(this,input,options);
  };
 });
 const waitStarted=async fragment=>{
  for(let i=0;i<30;i++){if((await control({})).requests.some(x=>x.includes(fragment)))return;await new Promise(r=>setTimeout(r,50));}
  throw Error('request never started: '+fragment);
 };
 await control({search_delay:1.5,reset:true});
 await p.fill('#chat-picker-search','Chat 012');await waitStarted('q=Chat+012');
 await p.fill('#chat-picker-search','Chat 198');await p.waitForSelector('[data-chat-id="199"]');
 if(await p.evaluate(()=>document.querySelectorAll('[data-chat-id]').length)!==1)throw Error('stale response was rendered');
 await p.fill('#chat-picker-search','Chat 013');await waitStarted('q=Chat+013');
 await p.evaluate(()=>history.pushState(null,'','/dashboard/account-tasks?name=acct24'));
 await p.waitForFunction(()=>document.querySelector('#chat-picker-search')?.value==='');
 await p.waitForSelector('[data-chat-id="1"]');
 if(await p.evaluate(()=>document.querySelectorAll('[data-chat-id]').length)!==50)throw Error('previous account response leaked');
 await p.fill('#chat-picker-search','Chat 014');await waitStarted('q=Chat+014');
 await p.click('button[aria-label="Close modal"]');
 await control({search_delay:0});
 await new Promise(r=>setTimeout(r,1600));
 if(await p.evaluate(()=>Boolean(document.querySelector('[data-chat-picker]'))))throw Error('dialog reopened after stale completion');
 const aborts=await p.evaluate(()=>window.__chatAborts);
 for(const part of ['Chat+012','Chat+013','Chat+014'])if(!aborts.some(x=>x.includes(part)))throw Error('not aborted: '+part);
 await fs.writeFile(root+'/browser-races.json',JSON.stringify({querySwitch:true,accountSwitch:true,close:true,aborts},null,2));
 console.log({querySwitch:true,accountSwitch:true,close:true,abortedRequests:aborts.length});
 await p.click('text="新增任务"');await p.waitForSelector('[data-chat-id="1"]');
 const sizes = [];
 for (const [width, height, mobile] of [[1280, 900, false], [390, 844, true]]) {
  await p.cdp('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor:1, mobile});
  const size = await p.evaluate(() => ({viewport:innerWidth, documentWidth:document.documentElement.scrollWidth, rows:document.querySelectorAll('[data-chat-id]').length}));
  if(size.documentWidth > size.viewport || size.rows !== 50) throw Error(JSON.stringify(size));
  sizes.push(size);
  await fs.writeFile(`${root}/picker-${width}.snapshot.txt`, await p.snapshot({scope:'full_page'}));
 }
 await fs.writeFile(root+'/browser-layout.json',JSON.stringify(sizes,null,2));
}
