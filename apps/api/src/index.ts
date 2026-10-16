import { Container } from "@cloudflare/containers";

interface Env {
  VIETSUB_GATEWAY: DurableObjectNamespace;
  VIETSUB_WS_TOKEN: string;
  VIETSUB_INTERNAL_TOKEN: string;
  ALLOWED_ORIGIN: string;
}
function equal(a:string,b:string):boolean {
  if (!a || a.length!==b.length) return false;
  let n=0; for(let i=0;i<a.length;i++) n |= a.charCodeAt(i)^b.charCodeAt(i);
  return n===0;
}
function unauthorized(){return new Response("Unauthorized",{status:401});}

export default {
  async fetch(request:Request,env:Env):Promise<Response> {
    const url=new URL(request.url);
    if(url.pathname==="/healthz" && request.method==="GET")
      return Response.json({status:"ok",service:"vietsub-pro-realtime-gateway"});
    if(url.pathname==="/api/v1/meta" && request.method==="GET")
      return Response.json({service:"Vietsub Pro Realtime Gateway",websocket:"/ws/vietsub",health:"/healthz"});
    if(url.pathname!=="/ws/vietsub") return new Response("Not found",{status:404});
    if(request.headers.get("Upgrade")?.toLowerCase()!=="websocket")
      return new Response("Expected WebSocket upgrade",{status:426});
    if(!env.VIETSUB_WS_TOKEN || !env.VIETSUB_INTERNAL_TOKEN)
      return new Response("Gateway secrets not configured",{status:503});
    if(env.ALLOWED_ORIGIN && request.headers.get("Origin")!==env.ALLOWED_ORIGIN)
      return new Response("Origin not allowed",{status:403});
    if(!equal(url.searchParams.get("token")??"",env.VIETSUB_WS_TOKEN)) return unauthorized();
    const id=env.VIETSUB_GATEWAY.idFromName("vietsub-global");
    return env.VIETSUB_GATEWAY.get(id).fetch(request);
  }
};

export class VietsubGateway extends DurableObject<Env> {
  async fetch(request:Request):Promise<Response> {
    const url=new URL(request.url);
    if(!equal(url.searchParams.get("token")??"",this.env.VIETSUB_WS_TOKEN)) return unauthorized();
    const container=new VietsubContainer(this.ctx,this.env);
    const headers=new Headers(request.headers);
    headers.delete("Cookie");
    headers.set("X-Internal-Token",this.env.VIETSUB_INTERNAL_TOKEN);
    // Preserve the WebSocket upgrade while forwarding to the container's port.
    const backend=new Request("http://container/ws/vietsub"+url.search,{method:"GET",headers});
    return container.fetch(backend);
  }
}

export class VietsubContainer extends Container<Env> {
  defaultPort=8000;
  sleepAfter="10m";
  envVars={
    INTERNAL_API_TOKEN:this.env.VIETSUB_INTERNAL_TOKEN,
    WHISPER_DEVICE:"cpu",
    COMPUTE_TYPE:"int8",
    MODEL_SIZE:"small",
    MAX_AUDIO_BYTES:"8388608",
    MAX_TEXT_CHARS:"5000"
  };
}
