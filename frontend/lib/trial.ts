import type {ChatResponse,SessionResponse,SessionsResponse} from "@/types/chat";
import {ApiError} from "@/lib/api";

export type Allowance={messages_used:number;messages_remaining:number;signup_required:boolean};
async function call<T>(path:string,body?:object):Promise<T> {
  const response=await fetch("/api/trial/"+path,{method: body ? "POST":"GET",credentials:"same-origin",
    cache:"no-store",headers:body?{"Content-Type":"application/json"}:undefined,body:body?JSON.stringify(body):undefined});
  const data=await response.json().catch(()=>({}));
  if(!response.ok) throw new ApiError(data.detail?.message || "WaveGuide is temporarily unavailable.",response.status,data.detail?.code);
  return data as T;
}
let initializing:Promise<Allowance>|null=null;
export function initTrial() {
  // Coalesce initial hydration effects before the first HttpOnly cookie reaches the browser.
  return initializing ??= call<Allowance>("guest/session",{}).finally(()=>{initializing=null;});
}
export const guestStatus=()=>call<Allowance>("guest/status");
export const guestSessions=()=>call<SessionsResponse>("guest/sessions");
export const guestMessages=(id:string)=>call<SessionResponse>("guest/sessions/"+encodeURIComponent(id));
export async function guestSend(message:string,session_id:string|null) {
  const bytes=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(JSON.stringify([message,session_id])));
  const digest=Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,"0")).join("");
  const previous=sessionStorage.getItem("wg-pending-submission")?.split(":");
  const request_id=previous?.[0]===digest ? previous[1]:crypto.randomUUID();
  sessionStorage.setItem("wg-pending-submission",digest+":"+request_id);
  const response=await call<ChatResponse & {guest:Allowance}>("chat",{message,session_id,request_id});
  sessionStorage.removeItem("wg-pending-submission");
  return response;
}
