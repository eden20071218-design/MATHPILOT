"use client";
import {FormEvent,useState} from 'react';
import {useRouter} from 'next/navigation';
import {useWorkspace,Heading,useAction,ActionNotice,Notice} from './workspace';
import {api} from '../lib/api';

export function PushControls(){
  const action=useAction();const [deliveries,setDeliveries]=useState<{id:string;status:string;attempts:number;open_windows:number|null;last_error:string|null}[]>([]);
  async function enable(){
    if(!window.isSecureContext||!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window))throw new Error('需要支持 Web Push 的浏览器和 HTTPS（本机可使用 localhost）');
    if(await Notification.requestPermission()!=='granted')throw new Error('尚未允许通知。若曾拒绝，请在浏览器网站设置中修改权限后重试。');
    const {public_key}=await api<{public_key:string}>('/reminders/public-key');
    await navigator.serviceWorker.register('/sw.js');const registration=await navigator.serviceWorker.ready;
    const base64=public_key.replace(/-/g,'+').replace(/_/g,'/');
    const bytes=Uint8Array.from(atob(base64+'='.repeat((4-base64.length%4)%4)),c=>c.charCodeAt(0));
    const subscription=await registration.pushManager.getSubscription()||await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes});
    await api('/reminders/subscriptions','POST',subscription.toJSON());action.setMessage('此浏览器已订阅后台提醒。关闭网页后是否展示还取决于系统权限、网络及后台调度服务。');
  }
  async function disable(){
    if(!('serviceWorker' in navigator))throw new Error('当前浏览器不支持 Service Worker');
    const registration=await navigator.serviceWorker.getRegistration('/');const sub=await registration?.pushManager.getSubscription();
    if(sub){const saved=await api<{id:string}>('/reminders/subscriptions','POST',sub.toJSON());await api('/reminders/subscriptions/'+saved.id,'DELETE');await sub.unsubscribe();}
    action.setMessage('此浏览器的订阅已取消。');
  }
  return <section className="panel"><h2>浏览器后台通知</h2><p className="muted">使用 Web Push，不依赖页面轮询。通知正文不包含你的成绩。</p><div className="inline"><button disabled={action.busy} onClick={()=>void action.run(enable)}>开启后台推送</button><button className="secondary" disabled={action.busy} onClick={()=>void action.run(disable)}>取消此浏览器订阅</button></div>
    <div className="inline"><button className="quiet" disabled={action.busy} onClick={()=>void action.run(async()=>{const r=await api<{send_after:string}>('/reminders/test','POST');action.setMessage('测试已排队：'+r.send_after+'。请关闭本网站所有标签页，保持浏览器运行；免打扰时段会延后发送。');})}>安排一分钟后的测试推送</button><button className="quiet" disabled={action.busy} onClick={()=>void action.run(async()=>setDeliveries(await api('/reminders/deliveries')))}>查看推送回执</button></div><ActionNotice state={action}/>
    {!!deliveries.length&&<div className="table-scroll"><table><thead><tr><th>发送状态</th><th>尝试次数</th><th>展示时网站窗口数</th><th>失败原因</th></tr></thead><tbody>{deliveries.map(d=><tr key={d.id}><td>{d.status}</td><td>{d.attempts}</td><td>{d.open_windows??'无展示回执'}</td><td>{d.last_error||'—'}</td></tr>)}</tbody></table></div>}
    <p className="footnote">推送服务接受不代表系统已经展示。真实关闭网页验收必须另行完成；离线、休眠和系统免打扰可能影响到达。</p></section>;
}
export function SettingsView(){
  const {data,refresh}=useWorkspace();const action=useAction();const router=useRouter();
  if(!data)return null;
  function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();const f=new FormData(e.currentTarget);void action.run(async()=>{
    await api('/student/settings','PUT',{display_name:f.get('name'),target_score:Number(f.get('target')),full_score:Number(f.get('full')),target_date:f.get('date'),daily_minutes:Number(f.get('minutes')),study_start:f.get('start'),hide_scores:f.get('hide')==='on',reminders:{enabled:f.get('enabled')==='on',lead_minutes:Number(f.get('lead')),timezone:f.get('zone'),quiet_start:f.get('quiet')==='on'?f.get('quiet_start'):null,quiet_end:f.get('quiet')==='on'?f.get('quiet_end'):null}});
    await refresh();action.setMessage('设置已保存。目标或学习时间改变后，请到规划解释页重新规划，已有任务不会被静默移动。');
  });}
  return <><Heading eyebrow="让计划适应你的生活" title="个人设置">调整你的学习目标、时间和通知方式。邮箱与账号身份不可在这里修改。</Heading>
    <form className="form-stack" onSubmit={submit}><section className="panel"><h2>我的目标</h2><div className="form-grid"><label>昵称<input name="name" required maxLength={100} defaultValue={data.student.display_name}/></label><label>邮箱<input value={data.student.email} readOnly/></label><label>目标分数<input name="target" type="number" min="0" max="1000" step=".01" required defaultValue={data.goal?.target_score??''}/></label><label>考试满分<input name="full" type="number" min="1" max="1000" required defaultValue={data.preferences.full_score||100}/></label><label>目标考试日期<input name="date" type="date" required defaultValue={data.goal?.target_date||''}/></label></div></section>
    <section className="panel"><h2>每天的学习时间</h2><div className="form-grid"><label>每日上限（分钟）<input name="minutes" type="number" min="15" max="240" required defaultValue={data.goal?.daily_minutes||60}/></label><label>每天开始学习的时间<input name="start" type="time" required defaultValue={data.preferences.study_start||'19:00'}/></label><label>学习所在时区<select name="zone" defaultValue={data.student.timezone}>{Array.from(new Set([data.student.timezone,'Asia/Shanghai','Asia/Hong_Kong','Asia/Tokyo','Europe/London','America/New_York','America/Los_Angeles','UTC'])).map(z=><option key={z}>{z}</option>)}</select></label></div><p className="footnote">规划会在每天固定时段内安排任务，不会超过学习时长上限。当前版本暂不支持跨午夜学习时段。</p></section>
    <section className="panel"><h2>提醒偏好</h2><label className="check"><input type="checkbox" name="enabled" defaultChecked={data.reminders.enabled}/>启用任务提醒</label><div className="form-grid"><label>开始前提前几分钟<input name="lead" type="number" min="0" max="10080" required defaultValue={data.reminders.lead_minutes}/></label><div><label className="check"><input type="checkbox" name="quiet" defaultChecked={data.reminders.quiet_start!==null}/>启用免打扰时间</label><div className="inline"><label>免打扰开始<input name="quiet_start" type="time" defaultValue={data.reminders.quiet_start?.slice(0,5)||'22:00'}/></label><label>免打扰结束<input name="quiet_end" type="time" defaultValue={data.reminders.quiet_end?.slice(0,5)||'08:00'}/></label></div></div></div></section>
    <section className="panel"><h2>隐私与显示</h2><label className="check"><input type="checkbox" name="hide" defaultChecked={data.preferences.hide_scores}/>隐藏首页、成绩列表与报告中的分数</label><p className="footnote">这是展示偏好，不是加密或授权控制；编辑成绩和查看诊断文字仍可能涉及分数。学生端访问权限始终由服务端验证。</p><p>不启用广告追踪；不自动分享学习数据。管理员仍可根据服务管理职责访问数据。</p></section>
    <ActionNotice state={action}/><button disabled={action.busy} className="save-button">{action.busy?'正在保存…':'保存全部设置'}</button></form>
    <PushControls/>
    <section className="panel"><h2>账号与数据</h2><div className="inline"><button className="secondary" disabled={action.busy} onClick={()=>void action.run(async()=>{const data=await api('/student/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='mathpilot-my-data.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);action.setMessage('个人学习数据已导出，不包含密码或推送订阅密钥。');})}>导出我的学习记录</button><button className="quiet danger" disabled={action.busy} onClick={()=>void action.run(async()=>{await api('/auth/logout-all','POST');router.replace('/login');})}>退出所有登录设备</button></div><Notice>当前版本未提供自助重置密码或删除账号；请联系部署管理员处理。退出登录不会自动取消设备推送，如使用公共设备，请先取消此浏览器订阅。</Notice></section></>;
}
