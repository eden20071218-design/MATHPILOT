"use client";
import {createContext,useCallback,useContext,useEffect,useRef,useState,ReactNode} from 'react';
import Link from 'next/link';
import {usePathname,useRouter} from 'next/navigation';
import {api,ApiError} from '../lib/api';
import type {Overview} from '../lib/types';

const Session=createContext<{data:Overview|null;refresh:()=>Promise<void>}>({data:null,refresh:async()=>{}});
export const useWorkspace=()=>useContext(Session);
const links=[['/','学习首页','⌂'],['/exams','成绩管理','↗'],['/knowledge','知识画像','∑'],['/calendar','学习日历','▦'],['/plan','规划解释','⤴'],['/reports','学习报告','▥'],['/settings','个人设置','⚙']];

export function Workspace({children}:{children:ReactNode}){
  const path=usePathname();const router=useRouter();const [data,setData]=useState<Overview|null>(null);const [error,setError]=useState('');const [loading,setLoading]=useState(true);
  const generation=useRef(0);
  const refresh=useCallback(async()=>{const id=++generation.current;setError('');setLoading(true);try{const result=await api<Overview>('/student/overview');if(id===generation.current)setData(result);}catch(e){if(id!==generation.current)return;if(e instanceof ApiError&&e.status===401){setData(null);}else{setError(e instanceof Error?e.message:'加载失败');throw e;}}finally{if(id===generation.current)setLoading(false);}},[]);
  const publicPage=path==='/login';
  useEffect(()=>{if(publicPage){generation.current++;setData(null);setLoading(false);return;}void refresh().catch(()=>{});},[publicPage,refresh]);
  useEffect(()=>{const expired=()=>{generation.current++;setData(null);setLoading(false);router.replace('/login?expired=1');};window.addEventListener('mathpilot:expired',expired);return()=>window.removeEventListener('mathpilot:expired',expired);},[router]);
  async function logout(){try{await api('/auth/logout','POST');generation.current++;setData(null);router.replace('/login');}catch(e){setError((e as Error).message);}}
  return <Session.Provider value={{data,refresh}}>{publicPage?children:<div className="workspace">
    <a href="#main-content" className="skip-link">跳到主要内容</a>
    <aside className="sidebar"><Link href="/" className="brand"><span className="brand-mark">M<span>π</span></span><span>MathPilot<small>把每一步，学明白</small></span></Link>
      <div className="nav-caption">我的学习空间</div><nav aria-label="主要导航">{links.map(([href,label,icon])=><Link key={href} href={href} aria-current={path===href?'page':undefined} className={path===href?'active':''}><span aria-hidden>{icon}</span>{label}</Link>)}</nav>
      <div className="sidebar-note"><span className="tiny-grid" aria-hidden>ƒ(x)</span><p>稳步前进，比一次满分更重要。</p><small>诊断是参考，不是给你的标签。</small></div>
      <button className="quiet logout" onClick={logout}>退出登录 ↗</button>
    </aside>
    <div className="workspace-body"><header className="topbar"><span>数学学习 / <strong>{links.find(([href])=>href===path)?.[1]||'任务详情'}</strong></span><button className="quiet" disabled={loading} onClick={()=>void refresh().catch(()=>{})}>{loading?'更新中…':'刷新数据'}</button><span className="user-chip"><span className="avatar">{data?.student.display_name.slice(0,1)||'同'}</span>{data?.student.display_name||'加载中'}</span></header>
      <main id="main-content" className="page-content">{loading&&!data?<Loading/>:error?<div className="panel"><Notice error>{error}</Notice><button onClick={()=>void refresh().catch(()=>{})}>重新加载</button></div>:data?children:<Loading/>}</main>
      <footer className="footer">MathPilot · 每次学习都留下可解释的进步 <span>估计有不确定性，目标不是成绩保证。</span></footer>
    </div></div>}</Session.Provider>;
}
export function Heading({eyebrow,title,children,action}:{eyebrow:string;title:string;children?:ReactNode;action?:ReactNode}){return <div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{children&&<p className="muted">{children}</p>}</div>{action}</div>;}
export function Notice({children,error=false}:{children:ReactNode;error?:boolean}){return <div role={error?'alert':'status'} className={'notice '+(error?'error':'')}>{children}</div>;}
export function Empty({title,children,href,label}:{title:string;children:ReactNode;href?:string;label?:string}){return <div className="empty"><span className="empty-symbol" aria-hidden>∅</span><h3>{title}</h3><p>{children}</p>{href&&<Link className="button secondary" href={href}>{label||'开始设置'} →</Link>}</div>;}
export function Loading(){return <div role="status" aria-live="polite" className="loading"><span className="skeleton heading-skeleton"/><span className="skeleton"/><span className="skeleton"/><p>正在读取你的学习记录…</p></div>;}
export function useAction(){const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');const [error,setError]=useState('');async function run(fn:()=>Promise<void>){setBusy(true);setError('');setMessage('');try{await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}return{busy,message,error,setMessage,run};}
export function ActionNotice({state}:{state:ReturnType<typeof useAction>}){return <>{state.error&&<Notice error>{state.error}</Notice>}{state.message&&<Notice>{state.message}</Notice>}</>;}
