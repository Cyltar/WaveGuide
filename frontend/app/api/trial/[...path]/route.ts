import { isIP } from "node:net";
import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

async function forward(req: NextRequest, ctx: {params: Promise<{path:string[]}>}) {
  const route = (await ctx.params).path.join("/");
  const allowed = req.method === "GET" ? /^guest\/(?:status|sessions(?:\/[0-9a-f-]{36})?)$/ :
    /^(?:chat|guest\/(?:session|claim))$/;
  if (!allowed.test(route)) return new Response(null,{status:404});
  if (req.method === "POST" && req.headers.get("origin") !== req.nextUrl.origin)
    return new Response(null,{status:403});
  if(route === "guest/claim" && !req.cookies.has("waveguide_guest"))
    return NextResponse.json({claimed:false},{headers:{"cache-control":"private, no-store"}});
  const origin = process.env.WAVEGUIDE_BACKEND_URL, secret = process.env.INTERNAL_PROXY_SECRET;
  const ip = process.env.VERCEL === "1" ? req.headers.get("x-vercel-forwarded-for") :
    process.env.NODE_ENV === "development" ? "127.0.0.1" : null;
  if (!origin || !secret || secret.length < 32 || !ip || !isIP(ip)) return new Response(null,{status:503});
  const headers = new Headers({"x-waveguide-ip":ip,"x-waveguide-proxy":secret,"content-type":"application/json"});
  const cookie=req.cookies.get("waveguide_guest")?.value;
  if (cookie && /^[a-zA-Z0-9_-]{43}$/.test(cookie)) headers.set("cookie", "waveguide_guest="+cookie);
  const auth=await createClient();
  const {data,error}=await auth.auth.getSession();
  if(error) return new Response(null,{status:401});
  if(data.session) headers.set("authorization","Bearer "+data.session.access_token);
  const reader=req.body?.getReader();
  let length=0;
  const chunks:Uint8Array[]=[];
  if(reader) {
    for(;;) {
      const {done,value}=await reader.read(); if(done) break;
      length+=value.length;
      if(length>16384) {await reader.cancel();return new Response(null,{status:413});}
      chunks.push(value);
    }
  }
  try {
    const upstream=await fetch(new URL("/"+route,origin),{method:req.method,headers,
      body:req.method==="POST"? Buffer.concat(chunks).toString("utf8"):undefined,
      cache:"no-store",redirect:"error",signal:AbortSignal.timeout(285000)});
    const result=new NextResponse(upstream.body,{status:upstream.status,headers:{"content-type":"application/json","cache-control":"private, no-store"}});
    for(const name of ["set-cookie","retry-after"]) {
      const value=upstream.headers.get(name); if(value) result.headers.set(name,value);
    }
    return result;
  } catch {return NextResponse.json({detail:{code:"CHAT_FAILED",message:"Connection interrupted. Retry the same message."}},{status:503});}
}
export {forward as GET,forward as POST};
