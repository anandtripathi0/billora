'use client';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import type { RecordData } from '@/lib/api';
import { currency } from '@/lib/utils';
export default function RevenueChart({rows}: {rows: RecordData[]}) {
  const data = rows.map(row => ({name: new Date(row.month).toLocaleDateString('en-IN', {month: 'short'}), value: Number(row.revenue)}));
  return <div style={{height: 260, width: '100%'}}><ResponsiveContainer><AreaChart data={data} margin={{top: 20, right: 12, left: 0, bottom: 0}}><defs><linearGradient id="revenue" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#C8AB85" stopOpacity={0.35}/><stop offset="100%" stopColor="#C8AB85" stopOpacity={0}/></linearGradient></defs><CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="4 6"/><XAxis dataKey="name" axisLine={false} tickLine={false} tick={{fill: '#796955', fontSize: 11}} dy={10}/><YAxis axisLine={false} tickLine={false} tick={{fill: '#796955', fontSize: 11}} tickFormatter={v => v >= 1000 ? `${v/1000}k` : `${v}`} width={48}/><Tooltip contentStyle={{background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 12}} formatter={value => currency(Number(value))}/><Area type="monotone" dataKey="value" name="Revenue" stroke="#79634D" strokeWidth={3} fill="url(#revenue)"/></AreaChart></ResponsiveContainer></div>;
}
