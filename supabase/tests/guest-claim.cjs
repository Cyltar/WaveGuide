/* Executable transaction/rollback and two-owner tests; no external accounts. */
const {PGlite}=require(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{randomUUID}=require('node:crypto');
(async()=>{
 const db=new PGlite(); try{
 await db.exec(`create schema auth;create table auth.users(id uuid primary key);create role anon;create role authenticated;create role service_role;
 create table chat_sessions(id uuid primary key,user_id uuid references auth.users on delete cascade,title text,created_at timestamptz);
 create table chat_messages(id uuid default gen_random_uuid(),session_id uuid references chat_sessions on delete cascade,role text,content text,used_context jsonb,created_at timestamptz);`);
 const dir=process.argv[2]||path.join(__dirname,'../migrations');
 for(const file of ['202611150001_guest_trial.sql','202611150002_guest_claim.sql'])await db.exec(fs.readFileSync(path.join(dir,file),'utf8').replace(/^\uFEFF/,''));
 const user=randomUUID(),other=randomUUID(),old=randomUUID();
 await db.query('insert into auth.users values($1),($2)',[user,other]);
 await db.query("insert into chat_sessions values($1,$2,'existing',now())",[old,user]);
 const g={token_hash:'a'.repeat(64),ip:'ip',rid:randomUUID(),digest:'test'};
 const call=async(op,a)=>(await db.query('select public.waveguide_trial($1,$2) v',[op,a])).rows[0].v;
 const claim=async(u,token=g.token_hash)=>(await db.query('select public.waveguide_claim_guest($1,$2) v',[token,u])).rows[0].v;
 await call('create',g);
 const lease=await call('admit',g);
 assert.equal((await claim(user)).error,'REQUEST_IN_PROGRESS');
 await call('finish',{...g,...lease,message:'guest question',answer:'guest answer',charge:true,context:{structured:{type:'test'}}});
 assert.equal((await claim(user,'b'.repeat(64))).error,'INVALID_GUEST_SESSION');
 await db.exec("alter table chat_messages add constraint artificial_failure check(role='user')");
 await assert.rejects(()=>claim(user));
 assert.equal((await call('messages',{...g,session_id:lease.session_id})).messages.length,2);
 await db.exec("alter table chat_messages drop constraint artificial_failure");
 assert.equal((await claim(user)).claimed,true);
 assert.equal((await claim(user)).claimed,true);
 assert.equal((await claim(other)).error,'CLAIM_CONFLICT');
 assert.equal((await call('status',g)).error,'INVALID_GUEST_SESSION');
 assert.equal((await db.query('select * from chat_sessions')).rows.length,2);
 const messages=(await db.query('select * from chat_messages order by created_at')).rows;
 assert.deepEqual(messages.map(m=>m.content),['guest question','guest answer']);
 assert.equal(messages[1].used_context.structured.type,'test');
 await db.query('delete from auth.users where id=$1',[user]);
 assert.equal((await db.query('select * from wg_trial.sessions')).rows.length,0);
 assert.equal((await db.query('select * from chat_messages')).rows.length,0);
 console.log('PASS: claim isolation, rollback, same-account replay, preservation, cascade');
 }finally{await db.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
