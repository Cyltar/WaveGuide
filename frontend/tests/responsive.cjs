/* eslint-disable @typescript-eslint/no-require-imports -- Standalone offline browser acceptance tests. */
// Run against a local production build with Playwright installed in your development environment.
// Every authentication and backend request is intercepted; no real account or chat is touched.
const { chromium } = require(process.env.WAVEGUIDE_PLAYWRIGHT || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  const context = await browser.newContext();
  const page = await context.newPage();
  const base = process.env.FRONTEND_TEST_URL || 'http://127.0.0.1:3100';
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const user = {id:'00000000-0000-0000-0000-000000000001', aud:'authenticated', role:'authenticated',
    email:'player@example.com', app_metadata:{provider:'email',providers:['email']}, user_metadata:{},
    created_at:'2026-01-01T00:00:00Z'};
  const exp = Math.floor(Date.now()/1000)+3600;
  const token = [Buffer.from(JSON.stringify({alg:'HS256',typ:'JWT'})).toString('base64url'),
    Buffer.from(JSON.stringify({sub:user.id,exp,aud:'authenticated',role:'authenticated'})).toString('base64url'),
    'offline-signature'].join('.');
  let deletionRequests = 0, failDeletion = true, finishDeletion;
  let chats = 0, limitNext = false;
  await page.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const json = (body, status=200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(body),
      headers:{'access-control-allow-origin':'*','access-control-allow-headers':'authorization,content-type,apikey,x-client-info,x-supabase-api-version'}});
    if (request.method()==='OPTIONS') return json({});
    if (url.pathname.startsWith('/auth/v1/')) {
      if (url.pathname.endsWith('/token')) return json({access_token:token,refresh_token:'offline-refresh',
        token_type:'bearer',expires_in:3600,expires_at:exp,user});
      if (url.pathname.endsWith('/user')) return json(user);
      if (url.pathname.endsWith('/logout')) return json({});
      return json({});
    }
    if (url.pathname === '/sessions') return json({sessions:[{id:'session-one',title:'My last ranked game'},
      {id:'session-two',title:'A very long conversation title that should stay inside the sidebar without overflowing'}]});
    if (url.pathname.startsWith('/sessions/')) return json({messages:[{id:'one',role:'assistant',content:'## Saved review\n\n- A recorded observation\n- A second observation\n\n```js\nconst example = 1;\n```'}]});
    if (url.pathname === '/chat') {
      chats++;
      if (limitNext) return json({detail:{code:'DAILY_LIMIT_REACHED',message:'Daily limit reached'}},429);
      return json({answer:'## Your review\n\n- Keep tracking the wave.\n\n```text\nMeasured evidence\n```', session_id:'session-one'});
    }
    if (url.pathname === '/account' && request.method()==='DELETE') {
      deletionRequests++;
      await new Promise(resolve => {finishDeletion=resolve;});
      return json(failDeletion ? {detail:{message:'offline error'}} : {deleted:true}, failDeletion ? 503 : 200);
    }
    if (url.origin === new URL(base).origin) return route.continue();
    return route.abort();
  });
  const output = process.env.WAVEGUIDE_SCREENSHOTS;
  if(output) fs.mkdirSync(output,{recursive:true});
  const screenshot = async name => {if(output) await page.screenshot({path:path.join(output,`${name}.png`),animations:"disabled"});};
  try {
    await page.goto(`${base}/login`);
    await page.getByLabel('Email',{exact:true}).fill(user.email);
    await page.getByLabel('Password',{exact:true}).fill('offline-test-only');
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await page.getByRole('heading',{name:/Your League Journey/}).waitFor();
    for(const width of [320,375,390,430,768,1024,1440]) {
      await page.setViewportSize({width,height:width>=768 ? 900 : 844});
      await page.waitForTimeout(260);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`overflow at ${width}`);
      const sidebar = page.locator('#navigation');
      if(width<768) {
        await sidebar.waitFor({state:'hidden'});
        await page.getByRole('button',{name:'Open navigation'}).click();
        await sidebar.waitFor({state:'visible'});
        assert.equal(await page.locator('.chat-canvas').evaluate(node=>node.inert),true);
        await page.getByRole('button',{name:'Close navigation',exact:true}).last().click();
        await sidebar.waitFor({state:'hidden'});
      } else {
        assert.equal(await sidebar.isVisible(),true);
        assert.equal(await page.getByRole('button',{name:'Open navigation'}).isVisible(),false);
      }
      await screenshot(`welcome-${width}`);
    }
    await page.emulateMedia({reducedMotion:'reduce'});
    assert.equal(await page.locator('.prompt-card').first().evaluate(n=>getComputedStyle(n).transitionDuration),'0s');
    await page.emulateMedia({reducedMotion:'no-preference'});
    // Preserve history, new chat, prompt fill, send, Markdown and multiline input.
    await page.getByRole('button',{name:'My last ranked game',exact:true}).click();
    await page.getByRole('heading',{name:'Saved review'}).waitFor();
    assert.equal(await page.locator('.assistant-content li').count(),2);
    await page.locator('.new-chat').click();
    await page.getByRole('button',{name:'Analyze my last 3 games',exact:true}).click();
    assert.equal(await page.getByLabel('Message WaveGuide').inputValue(),'Analyze my last 3 games.');
    assert.equal(chats,0);
    await page.getByLabel('Message WaveGuide').press('Enter');
    await page.getByRole('heading',{name:'Your review'}).waitFor();
    assert.equal(chats,1);
    assert.equal(await page.locator('.assistant-content pre').count(),1);
    await screenshot('conversation-desktop');
    await page.getByLabel('Message WaveGuide').fill('Line one');
    await page.getByLabel('Message WaveGuide').press('Shift+Enter');
    assert.equal(chats,1);
    assert.ok((await page.getByLabel('Message WaveGuide').inputValue()).includes('\n'));
    await page.getByLabel('Message WaveGuide').fill('');
    await page.setViewportSize({width:320,height:740});
    await page.getByRole('button',{name:'Open navigation'}).click();
    await screenshot('navigation-mobile');
    // Escape and backdrop close; focus returns to the trigger.
    await page.keyboard.press('Escape');
    await page.locator('#navigation').waitFor({state:'hidden'});
    assert.equal(await page.getByRole('button',{name:'Open navigation'}).evaluate(n=>n===document.activeElement),true);
    await page.getByRole('button',{name:'Open navigation'}).click();
    await page.locator('.navigation-backdrop').click({position:{x:315,y:350}});
    await page.locator('#navigation').waitFor({state:'hidden'});
    await page.getByRole('button',{name:'Open navigation'}).click();
    await page.getByRole('button',{name:/Open account for/}).click();
    await screenshot('account-mobile');
    await page.getByRole('button',{name:'Delete Account',exact:true}).click();
    await screenshot('delete-confirmation-mobile');
    const modal = page.locator('dialog[open]');
    assert.equal(await modal.evaluate(n=>n.scrollWidth>n.clientWidth),false);
    assert.equal(await page.getByRole('button',{name:'Cancel',exact:true}).evaluate(n=>n===document.activeElement),true);
    await page.keyboard.press('Tab'); await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(()=>document.querySelector('dialog[open]').contains(document.activeElement)),true);
    await page.getByRole('button',{name:'Cancel',exact:true}).click();
    assert.equal(deletionRequests,0);
    await page.keyboard.press('Escape');
    await page.locator('dialog[open]').waitFor({state:'hidden'});
    await page.keyboard.press('Escape');
    // Daily limit modal remains readable, focus-contained and dismissible.
    limitNext=true;
    await page.getByLabel('Message WaveGuide').fill('Another review');
    await page.getByLabel('Message WaveGuide').press('Enter');
    await page.getByRole('heading',{name:'Daily limit reached'}).waitFor();
    await screenshot('daily-limit-mobile');
    await page.getByRole('button',{name:'Got it',exact:true}).click();
    assert.equal(await page.getByLabel('Message WaveGuide').isDisabled(),true);
    await page.getByRole('button',{name:'Open navigation'}).click();
    await page.getByRole('button',{name:/Open account for/}).click();
    await page.getByRole('button',{name:'Delete Account',exact:true}).click();
    await page.getByRole('button',{name:'Delete Account',exact:true}).click();
    await page.getByRole('button',{name:'Deleting...',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Cancel',exact:true}).isDisabled(),true);
    await page.keyboard.press('Escape');
    assert.equal(await modal.isVisible(),true);
    while(!finishDeletion) await page.waitForTimeout(10);
    finishDeletion();
    await page.getByRole('alert').waitFor();
    assert.equal(new URL(page.url()).pathname,'/');
    assert.equal(deletionRequests,1);
    failDeletion=false; finishDeletion=undefined;
    await page.getByRole('button',{name:'Delete Account',exact:true}).click();
    while(!finishDeletion) await page.waitForTimeout(10);
    finishDeletion();
    await page.waitForURL('**/login');
    assert.equal(deletionRequests,2);
    await context.grantPermissions([]);
    await page.emulateMedia({reducedMotion:'reduce'});
    assert.equal(await page.evaluate(()=>matchMedia('(prefers-reduced-motion: reduce)').matches),true);
    assert.deepEqual(errors,[]);
    console.log('PASS: seven viewport widths, navigation, account dialogs, chat/history/Markdown, quota and offline deletion flow.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});

