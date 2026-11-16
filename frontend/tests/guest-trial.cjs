/* eslint-disable @typescript-eslint/no-require-imports -- standalone mocked browser acceptance */
const {chromium}=require(process.env.WAVEGUIDE_PLAYWRIGHT || "playwright");
const assert=require("node:assert/strict");
(async()=>{
 const browser=await chromium.launch({channel:"msedge",headless:true});
 try {
 const page=await browser.newPage({viewport:{width:320,height:780}});
 const base=process.env.FRONTEND_TEST_URL || "http://127.0.0.1:3100";
 const messages=[], ids=new Set(); let used=0, sendCount=0, fail=false;
 const status=()=>({is_guest:true,messages_used:used,messages_remaining:5-used,signup_required:used===5});
 const id="00000000-0000-4000-8000-000000000001";
 await page.route("**/api/trial/**",async route=>{
   const path=new URL(route.request().url()).pathname;
   const json=(data,status=200)=>route.fulfill({status,contentType:"application/json",body:JSON.stringify(data)});
   if(path.endsWith("/guest/session")||path.endsWith("/guest/status"))return json(status());
   if(path.endsWith("/guest/sessions"))return json({sessions:used?[{id,title:"Guest chat"}]:[]});
   if(path.endsWith("/"+id))return json({messages});
   if(path.endsWith("/chat")){
     const {message,request_id}=route.request().postDataJSON();
     sendCount++;
     if(fail){fail=false;return json({detail:{code:"CHAT_FAILED",message:"Temporary failure"}},503);}
     assert.ok(!ids.has(request_id));ids.add(request_id);
     messages.push({role:"user",content:message},{role:"assistant",content:"Coaching answer "+(++used)});
     return json({answer:"Coaching answer "+used,session_id:id,guest:status()});
   }
   return route.abort();
 });
 await page.goto(base);await page.getByText("5 free messages remaining",{exact:true}).waitFor();
 const input=page.getByLabel("Message WaveGuide");
 fail=true;await input.fill("Try again");await input.press("Enter");
 await page.getByText("Error: Temporary failure").waitFor();assert.equal(used,0);
 for(let i=1;i<=5;i++){
   await input.fill("Question "+i);await input.press("Enter");
   await page.getByText("Coaching answer "+i,{exact:true}).waitFor();
 }
 const modal=page.getByRole("dialog",{name:/5 free messages/});await modal.waitFor();
 assert.equal(await modal.getByRole("link",{name:"Create a free account"}).getAttribute("href"),"/signup");
 assert.equal(await modal.getByRole("link",{name:"Log in"}).getAttribute("href"),"/login");
 await modal.getByRole("button",{name:"Back to conversation"}).click();
 assert.equal(await input.isDisabled(),true);assert.equal(sendCount,6);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.reload();await modal.waitFor();await page.keyboard.press("Escape");
 await page.getByText("Coaching answer 5",{exact:true}).waitFor();
 assert.equal(await input.isDisabled(),true);
 console.log("PASS: guest landing, all five responses, failure, modal links, dismissal, restored history and 320px layout");
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
