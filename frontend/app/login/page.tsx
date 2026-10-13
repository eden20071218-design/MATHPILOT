"use client";
import {useState,FormEvent} from 'react';
import {useRouter} from 'next/navigation';
import {api} from '../../lib/api';
import {useAction,ActionNotice} from '../../components/workspace';
export default function Login(){
  const [register,setRegister]=useState(false);const router=useRouter();const action=useAction();
  function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();const form=new FormData(e.currentTarget);void action.run(async()=>{await api('/auth/'+(register?'register':'login'),'POST',{email:form.get('email'),password:form.get('password'),...(register?{display_name:form.get('name')}:{})});router.replace('/');});}
  return <main className="login-page"><section className="login-story"><span className="brand light">MathPilot <span aria-hidden>↗</span></span><p className="eyebrow">你的数学学习空间</p><h1>从“哪里不会”<br/>到“今天学什么”。</h1><p>整理成绩，理解薄弱点。<br/>把大目标拆成每天可以完成的一小步。</p><div className="formula-card" aria-hidden><span>成绩记录</span><i>→</i><span>知识画像</span><i>→</i><span>今日任务</span><div className="formula-line">每一次反馈，让下一步更清晰。</div></div></section>
    <section className="login-form"><div><p className="eyebrow">开始自己的学习节奏</p><h2>{register?'创建学习账号':'欢迎回来'}</h2><p className="muted">{register?'仅需邮箱、昵称和密码。不自动填入任何成绩。':'登录后继续你的数学学习计划。'}</p>
    <form onSubmit={submit} className="form-stack">{register&&<label>怎么称呼你<input name="name" autoComplete="nickname" required maxLength={100}/></label>}<label>邮箱<input name="email" type="email" autoComplete="email" required maxLength={320}/></label><label>密码<input name="password" type="password" autoComplete={register?'new-password':'current-password'} minLength={10} maxLength={128} required/><small>至少 10 个字符，不要与其他网站使用相同密码。</small></label><button disabled={action.busy}>{action.busy?'正在处理…':register?'创建账号并进入':'登录学习空间'} →</button><ActionNotice state={action}/></form>
    <button className="quiet" disabled={action.busy} onClick={()=>setRegister(!register)}>{register?'已有账号？去登录':'还没有账号？创建账号'}</button><p className="privacy-note">学习记录仅向当前账号与授权管理员提供。本版本不包含广告追踪，也不将成绩发送给外部 AI 服务。</p></div></section></main>;
}
