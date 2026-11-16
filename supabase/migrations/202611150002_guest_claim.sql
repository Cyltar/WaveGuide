-- Transfer only after the API has verified both the account bearer and the guest cookie.
begin;
create function public.waveguide_claim_guest(token text, account_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $$
declare s wg_trial.sessions; f uuid; active_chat uuid;
begin
 perform pg_advisory_xact_lock(1947362801);
 select * into s from wg_trial.sessions where token_hash=token and expires_at>clock_timestamp() for update;
 if not found then return '{"error":"INVALID_GUEST_SESSION"}'; end if;
 if s.claimed_at is not null then
   if s.claimed_by=account_id then return '{"claimed":true}'; end if;
   return '{"error":"CLAIM_CONFLICT"}';
 end if;
 if account_id is null or not exists(select 1 from auth.users where id=account_id) then return '{"error":"CLAIM_CONFLICT"}'; end if;
 for f in select l.fence from wg_trial.leases l join wg_trial.requests r using(fence)
          where r.guest=s.id and l.expires_at<=clock_timestamp() loop perform wg_trial.release(f); end loop;
 if exists(select 1 from wg_trial.requests where guest=s.id and state='running') then return '{"error":"REQUEST_IN_PROGRESS","retry":2}'; end if;
 select id into active_chat from wg_trial.conversations where guest=s.id order by created_at desc limit 1;
 insert into public.chat_sessions(id,user_id,title,created_at)
   select id,account_id,title,created_at from wg_trial.conversations where guest=s.id;
 insert into public.chat_messages(session_id,role,content,used_context,created_at)
   select conversation,role,content,context,created_at + (row_number() over (partition by conversation,created_at order by seq) - 1) * interval '1 microsecond'
   from wg_trial.messages where guest=s.id order by seq;
 update wg_trial.sessions set claimed_by=account_id,claimed_at=clock_timestamp() where id=s.id;
 delete from wg_trial.requests where guest=s.id;
 delete from wg_trial.conversations where guest=s.id;
 return jsonb_build_object('claimed',true,'session_id',active_chat);
end $$;
revoke all on function public.waveguide_claim_guest(text,uuid) from public,anon,authenticated;
grant execute on function public.waveguide_claim_guest(text,uuid) to service_role;
commit;

