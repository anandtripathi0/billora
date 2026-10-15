import { AdminBusinessDetail } from '@/components/admin';
export default async function Page({params}:{params:Promise<{id:string}>}){const{id}=await params;return <AdminBusinessDetail id={id}/>;}
