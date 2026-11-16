-- Only the service-role RPC below exposes these tables. No changes to authenticated chat RLS.
begin;
create schema wg_trial;
revoke all on schema wg_trial from public, anon, authenticated;
create table wg_trial.sessions (
 id uuid primary key default gen_random_uuid(), token_hash text unique not null check(token_hash ~ '^[0-9a-f]{64}$'),
 used smallint not null default 0 check(used between 0 and 5),
 created_at timestamptz not null default now(), expires_at timestamptz not null,
 claimed_by uuid references auth.users(id) on delete cascade, claimed_at timestamptz
);
create index on wg_trial.sessions(expires_at);
create table wg_trial.conversations (
 id uuid primary key, guest uuid not null references wg_trial.sessions on delete cascade,
 title text not null, created_at timestamptz not null default now(), unique(guest,id)
);
create table wg_trial.requests (
 guest uuid not null references wg_trial.sessions on delete cascade, rid uuid not null,
 digest text not null, state text not null check(state in ('running','failed','done')),
 fence uuid not null, conversation uuid not null, ip_day text not null, day_start bigint not null,
 result jsonb, primary key(guest,rid)
);
create unique index trial_one_running on wg_trial.requests(guest) where state='running';
create table wg_trial.messages (
 seq bigint generated always as identity primary key, guest uuid not null, conversation uuid not null,
 role text not null check(role in ('user','assistant')), content text not null, context jsonb,
 created_at timestamptz not null default clock_timestamp(),
 foreign key(guest,conversation) references wg_trial.conversations(guest,id) on delete cascade
);
create index on wg_trial.messages(guest,conversation,seq);
create table wg_trial.windows (
 bucket text not null, subject text not null, starts bigint not null, n integer not null check(n>=0),
 expires_at timestamptz not null, primary key(bucket,subject,starts)
);
create index on wg_trial.windows(expires_at);
create table wg_trial.leases (
 fence uuid primary key, expires_at timestamptz not null
);
create index on wg_trial.leases(expires_at);
alter table wg_trial.sessions enable row level security;
alter table wg_trial.conversations enable row level security;
alter table wg_trial.requests enable row level security;
alter table wg_trial.messages enable row level security;
alter table wg_trial.windows enable row level security;
alter table wg_trial.leases enable row level security;

-- Caller holds the admission lock; pending IP successes occupy a slot until settlement.
create function wg_trial.take(b text,s text,t bigint,span int,lim int,cost int default 1)
returns boolean language plpgsql set search_path='' as $$
begin
 if lim < cost or cost < 1 then return false; end if;
 insert into wg_trial.windows values(b,s,t,cost,to_timestamp(t+span))
 on conflict(bucket,subject,starts) do update set n=wg_trial.windows.n+excluded.n
 where wg_trial.windows.n+excluded.n<=lim;
 return found;
end $$;

create function wg_trial.release(f uuid) returns void language plpgsql set search_path='' as $$
declare r wg_trial.requests;
begin
 update wg_trial.requests set state='failed' where fence=f and state='running' returning * into r;
 if found then
   update wg_trial.windows set n=n-1 where bucket='ip_success' and subject=r.ip_day and starts=r.day_start;
 end if;
 delete from wg_trial.leases where fence=f;
end $$;

create function wg_trial.status(n integer) returns jsonb language sql immutable as $$
 select jsonb_build_object('is_guest',true,'messages_used',n,'messages_remaining',5-n,'signup_required',n=5)
$$;

create function public.waveguide_trial(op text, a jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare
 s wg_trial.sessions; r wg_trial.requests; conv uuid; f uuid; stale uuid;
 ts timestamptz:=clock_timestamp(); epoch_s bigint:=floor(extract(epoch from ts));
 d bigint:=(epoch_s/86400)*86400; h bigint:=(epoch_s/3600)*3600;
 m bigint:=(epoch_s/60)*60; ten bigint:=(epoch_s/600)*600;
 request_key uuid:=(a->>'rid')::uuid; ip text:=a->>'ip'; v jsonb; token text:=a->>'token_hash';
begin
 -- Serializes short metadata transactions across API instances, never external work.
 perform pg_advisory_xact_lock(1947362801);
 for stale in select fence from wg_trial.leases where expires_at<=ts loop perform wg_trial.release(stale); end loop;
 if op='cleanup' then
   delete from wg_trial.sessions where expires_at<=ts;
   delete from wg_trial.windows where expires_at<ts-interval '1 day';
   return '{}'::jsonb;
 end if;
 if op='create' then
   if not wg_trial.take('create',ip,d,86400,coalesce((a->>'create_limit')::int,3)) then
     return jsonb_build_object('error','TOO_MANY_GUEST_SESSIONS','retry',d+86400-epoch_s);
   end if;
   insert into wg_trial.sessions(token_hash,expires_at) values(token,ts+interval '90 days');
   return wg_trial.status(0);
 end if;
 if op='release' then perform wg_trial.release((a->>'fence')::uuid); return '{}'::jsonb; end if;
 if op='renew' then
   update wg_trial.leases set expires_at=ts+interval '120 seconds' where fence=(a->>'fence')::uuid;
   return jsonb_build_object('renewed',found);
 end if;
 if op<>'account_admit' then
   select * into s from wg_trial.sessions where token_hash=token and expires_at>ts for update;
   if not found or s.claimed_at is not null then return '{"error":"INVALID_GUEST_SESSION"}'; end if;
 end if;
 if op='status' then return wg_trial.status(s.used); end if;
 if op='sessions' then
   return jsonb_build_object('sessions',coalesce((select jsonb_agg(jsonb_build_object('id',id,'title',title,'created_at',created_at)
      order by created_at desc) from wg_trial.conversations where guest=s.id),'[]'::jsonb));
 end if;
 if op='messages' then
   conv:=(a->>'session_id')::uuid;
   if not exists(select 1 from wg_trial.conversations where guest=s.id and id=conv) then return '{"error":"NOT_FOUND"}'; end if;
   return jsonb_build_object('messages',coalesce((select jsonb_agg(jsonb_build_object('id',seq::text,'role',role,'content',content,
      'structured',context->'structured','created_at',created_at) order by seq) from wg_trial.messages where guest=s.id and conversation=conv),'[]'::jsonb));
 end if;
 if op='finish' then
   select * into r from wg_trial.requests where guest=s.id and requests.rid=request_key;
   if not found or r.fence<>(a->>'fence')::uuid or r.state<>'running' then return '{"error":"LEASE_LOST"}'; end if;
   if nullif(trim(a->>'answer'),'') is null then perform wg_trial.release(r.fence); return '{"error":"CHAT_FAILED"}'; end if;
   insert into wg_trial.conversations(id,guest,title) values(r.conversation,s.id,left(a->>'message',50)) on conflict(id) do nothing;
   insert into wg_trial.messages(guest,conversation,role,content,context) values
     (s.id,r.conversation,'user',a->>'message',null),(s.id,r.conversation,'assistant',a->>'answer',a->'context');
   if (a->>'charge')::boolean then update wg_trial.sessions set used=used+1 where id=s.id returning used into s.used;
   else update wg_trial.windows set n=n-1 where bucket='ip_success' and subject=r.ip_day and starts=r.day_start; end if;
   v:=jsonb_build_object('answer',a->>'answer','session_id',r.conversation,'structured',a->'context'->'structured','guest',wg_trial.status(s.used));
   update wg_trial.requests set state='done',result=v where guest=s.id and requests.rid=r.rid;
   delete from wg_trial.leases where fence=r.fence;
   return v;
 end if;
 if op not in ('admit','account_admit') then raise exception 'invalid operation'; end if;
 if op='admit' then
   if not wg_trial.take('ip_attempt',ip,h,3600,coalesce((a->>'hour_limit')::int,30)) then
     return jsonb_build_object('error','IP_RATE_LIMITED','retry',h+3600-epoch_s); end if;
   if not wg_trial.take('guest_attempt',s.id::text,ten,600,coalesce((a->>'attempt_limit')::int,10)) then
     return jsonb_build_object('error','GUEST_RATE_LIMITED','retry',ten+600-epoch_s); end if;
   select * into r from wg_trial.requests where guest=s.id and requests.rid=request_key;
   if found and r.digest<>a->>'digest' then return '{"error":"IDEMPOTENCY_CONFLICT"}'; end if;
   if r.state='done' then return jsonb_build_object('replay',r.result || jsonb_build_object('guest',wg_trial.status(s.used))); end if;
   if exists(select 1 from wg_trial.requests where guest=s.id and state='running') then return '{"error":"REQUEST_IN_PROGRESS","retry":2}'; end if;
   if s.used>=5 then return jsonb_build_object('error','GUEST_LIMIT_REACHED','guest',wg_trial.status(s.used)); end if;
   conv:=(a->>'session_id')::uuid;
   if conv is not null and not exists(select 1 from wg_trial.conversations where guest=s.id and id=conv) then return '{"error":"NOT_FOUND"}'; end if;
 end if;
 if (select count(*) from wg_trial.leases)>=coalesce((a->>'concurrent')::int,12) then return '{"error":"GLOBAL_AI_BUDGET_EXCEEDED","retry":2}'; end if;
 -- Roll back partial budget updates when any bucket is full. Count parser + final generation conservatively.
 begin
   if not wg_trial.take('global_min','all',m,60,coalesce((a->>'minute_budget')::int,120),2) then
      v:=jsonb_build_object('error','GLOBAL_AI_BUDGET_EXCEEDED','retry',m+60-epoch_s); raise sqlstate 'WG001'; end if;
   if not wg_trial.take('global_day','all',d,86400,coalesce((a->>'day_budget')::int,4000),2) then
      v:=jsonb_build_object('error','GLOBAL_AI_BUDGET_EXCEEDED','retry',d+86400-epoch_s); raise sqlstate 'WG001'; end if;
   if op='admit' and not wg_trial.take('ip_success',ip,d,86400,coalesce((a->>'success_limit')::int,15)) then
      v:=jsonb_build_object('error','IP_RATE_LIMITED','retry',d+86400-epoch_s); raise sqlstate 'WG001'; end if;
 exception when sqlstate 'WG001' then return v; end;
 f:=gen_random_uuid();
 insert into wg_trial.leases values(f,ts+interval '120 seconds');
 if op='admit' then
   conv:=coalesce(conv,gen_random_uuid());
   insert into wg_trial.requests values(s.id,request_key,a->>'digest','running',f,conv,ip,d,null)
   on conflict on constraint requests_pkey do update set state='running',fence=excluded.fence,conversation=excluded.conversation,
     ip_day=excluded.ip_day,day_start=excluded.day_start;
 end if;
 return jsonb_build_object('fence',f,'session_id',conv);
end $$;
revoke all on all tables in schema wg_trial from public, anon, authenticated;
revoke all on all functions in schema wg_trial from public, anon, authenticated;
revoke all on function public.waveguide_trial(text,jsonb) from public, anon, authenticated;
grant execute on function public.waveguide_trial(text,jsonb) to service_role;
commit;

