export class ApiError extends Error {
  constructor(public status:number,message:string) {super(message);this.name='ApiError';}
}
export async function api<T>(path:string,method='GET',body?:unknown):Promise<T> {
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),30000);
  try {
    const response=await fetch('/api/v1'+path,{method,credentials:'same-origin',cache:'no-store',signal:controller.signal,
      headers:{'Content-Type':'application/json','X-MathPilot-Request':'1'},body:body===undefined?undefined:JSON.stringify(body)});
    if(!response.ok){
      let message='服务暂时不可用，请稍后重试';
      try{const payload=await response.json();message=typeof payload.detail==='string'?payload.detail:Array.isArray(payload.detail)?payload.detail.map((e:{msg:string})=>e.msg.replace('Value error, ','')).join('；'):message;}catch{}
      if(response.status===401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event('mathpilot:expired'));
      throw new ApiError(response.status,message);
    }
    return response.status===204?undefined as T:await response.json() as T;
  }catch(error){
    if(error instanceof ApiError)throw error;
    throw new Error(error instanceof Error && error.name==='AbortError'?'请求超时。保存可能已完成，请刷新确认后再重试。':'无法连接服务，请检查网络和后端是否启动');
  }finally{clearTimeout(timer);}
}
export function localDay(value:string|Date,zone:string){return new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));}
export function clock(value:string|null,zone:string){return value?new Intl.DateTimeFormat('zh-CN',{timeZone:zone,hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)):'未安排';}
export function dayLabel(value:string|null,zone:string){return value?new Intl.DateTimeFormat('zh-CN',{timeZone:zone,month:'long',day:'numeric',weekday:'short'}).format(new Date(value)):'未安排日期';}
export const percent=(value:number)=>Math.round(Number(value)*100);
export const taskStatus:Record<string,string>={scheduled:'待学习',pending:'待安排',in_progress:'进行中',completed:'已完成',skipped:'已跳过',cancelled:'已取消'};
