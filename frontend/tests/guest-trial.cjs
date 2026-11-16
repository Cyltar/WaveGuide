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
 // Verified login returns to the same chat origin; claim completes before account history loads.
 const user={id:"00000000-0000-4000-8000-000000000099",aud:"authenticated",role:"authenticated",
   email:"guest@example.test",app_metadata:{provider:"email",providers:["email"]},user_metadata:{},created_at:"2026-01-01T00:00:00Z"};
 const exp=Math.floor(Date.now()/1000)+3600;
 const token=[Buffer.from(JSON.stringify({alg:"HS256",typ:"JWT"})).toString("base64url"),
   Buffer.from(JSON.stringify({sub:user.id,aud:"authenticated",exp})).toString("base64url"),"test-signature"].join(".");
 await page.route("**/auth/v1/**",route=>route.fulfill({contentType:"application/json",headers:{"access-control-allow-origin":"*",
   "access-control-allow-headers":"*"},body:JSON.stringify(route.request().url().includes("/token")?
   {access_token:token,refresh_token:"offline",token_type:"bearer",expires_in:3600,expires_at:exp,user}:user)}));
 let claimed=false;
 await page.route("**/api/trial/guest/claim",r=>{claimed=true;return r.fulfill({json:{claimed:true,session_id:id}});});
 await page.route("**/sessions",r=>r.fulfill({json:{sessions:[{id,title:"Claimed conversation"}]}}));
 await page.route("**/sessions/"+id,r=>r.fulfill({json:{messages}}));
 await page.reload();await modal.waitFor();
 await modal.getByRole("link",{name:"Create a free account"}).click();
 await page.getByLabel("Email",{exact:true}).fill(user.email);
 await page.getByLabel("Password",{exact:true}).fill("offline-only");
 await page.getByLabel("Confirm password",{exact:true}).fill("offline-only");
 await page.locator("form button[type=submit]").click();
 await page.getByText(/Account created. Check your email/).waitFor();
 assert.equal(claimed,false);
 await page.goto(base);await modal.waitFor();
 await modal.getByRole("link",{name:"Log in"}).click();
 await page.getByLabel("Email",{exact:true}).fill(user.email);
 await page.getByLabel("Password",{exact:true}).fill("offline-only");
 await page.getByRole("button",{name:"Sign in",exact:true}).click();
 await page.getByText("Coaching answer 5",{exact:true}).waitFor();
 assert.ok(claimed);assert.equal(await page.getByLabel("Message WaveGuide").isEnabled(),true);
 console.log("PASS: guest landing, all five responses, failure, modal links, dismissal, restored history and 320px layout");
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
