import { ThermalReceipt } from '@/components/thermal';
export default async function Page({params}:{params:Promise<{id:string}>}){const {id}=await params;return <ThermalReceipt id={id}/>;}
