import {TaskView} from '../../../components/task-view';
export default async function Page({params}:{params:Promise<{id:string}>}){const {id}=await params;return <TaskView id={id}/>;}
