import React, {createContext, useCallback, useContext, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Alert, AppState, FlatList, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View} from 'react-native';
import {NavigationContainer, DefaultTheme, useFocusEffect} from '@react-navigation/native';
import {createNativeStackNavigator} from '@react-navigation/native-stack';
import {SafeAreaProvider, SafeAreaView} from 'react-native-safe-area-context';
import NetInfo from '@react-native-community/netinfo';
import * as Crypto from 'expo-crypto';
import * as ScreenCapture from 'expo-screen-capture';
import {activate, openStore, persistSession, savedSession, Session, signOut, unlock} from './security';
import {Store, RecordData} from './store';
import {SyncEngine} from './sync';
import {request} from './api';
import {calculate, decimal, Line, normalizeMobile, rupees, scaled} from './money';
import {printInvoice, shareBackup, shareInvoice} from './documents';
import {PrinterPanel, thermalPrint} from './printers';

const colors = {bg:'#FAF7F0', card:'#FFFDF9', surface:'#F4EDE3', primary:'#79634D', pressed:'#604D3B', heading:'#40352B', text:'#675A4B', border:'#E8DCCB', success:'#3F8A69', error:'#D45B57'};
const Stack = createNativeStackNavigator();
type Context = {store: Store; session: Session; online: boolean; syncText: string; engine: SyncEngine; refresh: number; changed: () => void; lock: () => void; logout: () => Promise<void>};
const Workspace = createContext<Context>(null!);
const useWorkspace = () => useContext(Workspace);
function Button({title, onPress, secondary = false, disabled = false}: {title:string; onPress:()=>void; secondary?:boolean; disabled?:boolean}) {
  return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress} style={({pressed}) => [styles.button, secondary && styles.secondary, pressed && {opacity:0.75}, disabled && {opacity:0.5}]}><Text style={{color:secondary?colors.heading:'white',fontWeight:'700',textAlign:'center'}}>{title}</Text></Pressable>;
}
function Field({label, value, set, secret = false, numeric = false}: {label:string; value:string; set:(v:string)=>void; secret?:boolean; numeric?:boolean}) {
  return <View style={{marginBottom:12}}><Text style={styles.label}>{label}</Text><TextInput accessibilityLabel={label} value={value} onChangeText={set} secureTextEntry={secret} keyboardType={numeric?'decimal-pad':'default'} autoCapitalize="none" style={styles.input}/></View>;
}
function Page({children}: {children:React.ReactNode}) {
  return <SafeAreaView edges={['bottom']} style={styles.page}><KeyboardAvoidingView style={{flex:1}} behavior={Platform.OS==='ios'?'padding':undefined}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.content}>{children}</ScrollView></KeyboardAvoidingView></SafeAreaView>;
}
function Card({children}: {children:React.ReactNode}) {return <View style={styles.card}>{children}</View>;}
function Note({children}: {children:React.ReactNode}) {return <Text style={styles.note}>{children}</Text>;}
function Toggle({label, value, set}: {label:string;value:boolean;set:(v:boolean)=>void}) {return <View style={styles.row}><Text style={styles.text}>{label}</Text><Switch value={value} onValueChange={set} trackColor={{true:colors.success}}/></View>;}
function useAction() {
  const [busy,setBusy]=useState(false), lock=useRef(false);
  const run=async(action:()=>Promise<any>)=>{if(lock.current)return;lock.current=true;setBusy(true);try{await action();}catch(e){Alert.alert('Billora',e instanceof Error?e.message:'Could not complete this action.');}finally{lock.current=false;setBusy(false);}};
  return {busy,run};
}
function useRecords(kind:'product'|'customer'|'invoice') {
  const {store,refresh}=useWorkspace(),[records,setRecords]=useState<RecordData[]>([]);
  useFocusEffect(useCallback(()=>{let active=true;store.list(kind).then(r=>{if(active)setRecords(r);}).catch(e=>Alert.alert('Local database',e.message));return()=>{active=false;};},[store,kind,refresh]));
  return records;
}

export default function App() {
  const [session,setSession]=useState<Session|null>(null),[store,setStore]=useState<Store|null>(null),[locked,setLocked]=useState(true),[boot,setBoot]=useState(true);
  const [online,setOnline]=useState(false),[syncText,setSyncText]=useState('Offline — saved on this device'),[refresh,setRefresh]=useState(0),[engine,setEngine]=useState<SyncEngine|null>(null);
  const changed=()=>setRefresh(x=>x+1),{busy,run}=useAction();
  useEffect(()=>{ScreenCapture.preventScreenCaptureAsync().catch(()=>{});savedSession().then(setSession).finally(()=>setBoot(false));const stop=NetInfo.addEventListener(s=>setOnline(!!s.isConnected && s.isInternetReachable!==false));return stop;},[]);
  const close=useCallback(()=>{setLocked(true);if(engine)engine.stopped=true;},[engine]);
  useEffect(()=>{const sub=AppState.addEventListener('change',s=>{if(s!=='active')close();});return()=>sub.remove();},[close]);
  useEffect(()=>{if(!engine||locked)return;engine.stopped=false;if(online)void engine.run();const timer=setInterval(()=>{if(online&&AppState.currentState==='active')void engine.run();},60000);return()=>clearInterval(timer);},[engine,online,locked]);
  async function enter(next: Session, existing?:Store|null) {
    if(next.blocked||Date.parse(next.expires_at)<=Date.now())throw new Error('Sign in online again. Your pending records remain on this phone.');
    const db=existing||await openStore(next);
    db.role=next.role;
    if(!(await db.list('business')).length)await db.pullPage([{kind:'business',id:next.business.id,version:'',data:next.business}],'',true);
    const sync=new SyncEngine(db,next,(message,expired)=>{setSyncText(message);changed();if(expired){setSession({...next,blocked:true});setLocked(true);}},persistSession);
    setSession(next);setStore(db);setEngine(sync);setLocked(false);changed();
  }
  if(boot)return <SafeAreaProvider><View style={styles.center}><ActivityIndicator color={colors.primary}/></View></SafeAreaProvider>;
  if(locked||!session||!store||!engine)return <SafeAreaProvider><Page><Text style={styles.brand}>BILLORA</Text><Text style={styles.title}>Your shop, in your pocket.</Text><Note>Secure billing on this phone, even without internet after activation.</Note>
    {session&&!session.blocked&&Date.parse(session.expires_at)>Date.now()?<Card><Text style={styles.subtitle}>{session.business.name}</Text><Button title={busy?'Unlocking…':'Unlock with device screen lock'} disabled={busy} onPress={()=>void run(async()=>{await unlock();await enter(session,store);})}/><Note>New device activation and expired sessions require internet. Unsynced bills stay on this phone.</Note></Card>:
    <Login busy={busy} run={run} onLogin={async(m,p)=>enter(await activate(m,p),store)} existing={!!session}/>}
    <Note>{online?'Online':'Offline'} · Uninstalling Billora or clearing its storage can destroy unsynced bills.</Note></Page></SafeAreaProvider>;
  const value:Context={store,session,online,syncText,engine,refresh,changed,lock:close,logout:async()=>{if(engine.running)throw new Error('Wait for the current sync to finish.');engine.stopped=true;await signOut(session,store);setSession(null);setStore(null);setEngine(null);setLocked(true);}};
  return <SafeAreaProvider><Workspace.Provider value={value}><NavigationContainer theme={{...DefaultTheme,colors:{...DefaultTheme.colors,background:colors.bg,card:colors.card,text:colors.heading,primary:colors.primary,border:colors.border}}}><Stack.Navigator screenOptions={{headerShadowVisible:false,headerTintColor:colors.heading,contentStyle:{backgroundColor:colors.bg}}}>
    <Stack.Screen name="Dashboard" component={Dashboard} options={{title:'Billora'}}/>
    <Stack.Screen name="Create Bill" component={CreateBill}/><Stack.Screen name="Invoices" component={Invoices}/><Stack.Screen name="Invoice" component={InvoiceDetail}/>
    <Stack.Screen name="Products" component={Products}/><Stack.Screen name="Product" component={ProductForm}/>
    <Stack.Screen name="Customers" component={Customers}/><Stack.Screen name="Customer" component={CustomerForm}/>
    <Stack.Screen name="Customer Collection" component={Collection}/><Stack.Screen name="Settings" component={Settings}/><Stack.Screen name="Sync Status" component={SyncStatus}/>
  </Stack.Navigator></NavigationContainer></Workspace.Provider></SafeAreaProvider>;
}

function Login({busy,run,onLogin,existing}:{busy:boolean;run:(f:()=>Promise<any>)=>Promise<void>;onLogin:(m:string,p:string)=>Promise<void>;existing:boolean}) {
  const [mobile,setMobile]=useState(''),[password,setPassword]=useState(''),[show,setShow]=useState(false);
  return <Card><Text style={styles.subtitle}>{existing?'Sign in again':'Activate this device'}</Text><Field label="Mobile number" value={mobile} set={setMobile} numeric/><Field label="Password" value={password} set={setPassword} secret={!show}/><Toggle label="Show password" value={show} set={setShow}/>
    <Button title={busy?'Connecting to server…':'Sign in'} disabled={busy} onPress={()=>void run(async()=>{const secret=password;setPassword('');await onLogin(normalizeMobile(mobile),secret);})}/><Note>Use your existing Billora account. Forgotten or temporary passwords must be handled through the website/admin.</Note></Card>;
}
function Dashboard({navigation}:any) {
  const {session,store,online,syncText,engine,refresh}=useWorkspace(),[status,setStatus]=useState<any>({}), invoices=useRecords('invoice');
  useEffect(()=>{void store.status().then(setStatus);},[store,refresh]);
  const total=invoices.filter(x=>!x.cancelled_at).reduce((a,x)=>a+scaled(x.total),0);
  return <Page><Note>{online?'● Online':'● Offline'} · {session.role}</Note><Text style={styles.title}>{session.business.name}</Text><Text style={styles.text}>Ready for your next customer.</Text>
    <Button title="＋ Create a bill" onPress={()=>navigation.navigate('Create Bill')}/><Card><Note>Cached lifetime sales</Note><Text style={styles.title}>{rupees(total)}</Text><Note>{status.invoices?.n||0} pending invoices · {status.pending?.n||0} pending changes</Note><Note>{syncText}</Note><Button title="Sync now" secondary onPress={()=>void engine.run(true)}/></Card>
    {['Invoices','Products','Customers','Customer Collection','Sync Status','Settings'].map(name=><Button key={name} title={name} secondary onPress={()=>navigation.navigate(name)}/>)}</Page>;
}
function Products({navigation}:any) {
  const records=useRecords('product'),[search,setSearch]=useState(''),[low,setLow]=useState(false);
  const filtered=records.filter(p=>p.is_active!==false&&`${p.name} ${p.sku}`.toLowerCase().includes(search.toLowerCase())&&(!low||scaled(p.stock||'0',3)<=scaled(p.low_stock_threshold||'5',3)));
  return <SafeAreaView edges={['bottom']} style={styles.page}><FlatList data={filtered} keyExtractor={p=>p.id} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" ListHeaderComponent={<><Button title="＋ Add product" onPress={()=>navigation.navigate('Product')}/><Field label="Search products or SKU" value={search} set={setSearch}/><Toggle label="Low stock only" value={low} set={setLow}/></>} renderItem={({item:p})=><Card><Text style={styles.subtitle}>{p.name}</Text><Note>{p.sku} · {p.stock||'0'} {p.unit||'pcs'} in stock</Note><Text style={styles.text}>₹{p.selling_price??'Price needed'}</Text>{p.sync_status==='conflict'&&<Note>Sync issue — review before billing.</Note>}<Button title="Edit / adjust stock" secondary onPress={()=>navigation.navigate('Product',{id:p.id})}/></Card>}/></SafeAreaView>;
}
function ProductForm({route,navigation}:any) {
  const {store,changed}=useWorkspace(),id=route.params?.id,[record,setRecord]=useState<any>(null);
  const [name,setName]=useState(''),[sku,setSku]=useState(''),[price,setPrice]=useState(''),[stock,setStock]=useState('0'),[gst,setGST]=useState('0'),[inclusive,setInclusive]=useState(false),[delta,setDelta]=useState(''),[reason,setReason]=useState('');
  const {run,busy}=useAction();
  useEffect(()=>{if(id)void store.get('product',id).then(p=>{setRecord(p);setName(p.name);setSku(p.sku);setPrice(p.selling_price||'');setStock(p.stock);setGST(p.gst_rate||'0');setInclusive(!!p.price_includes_tax);});},[id,store]);
  return <Page><Card><Field label="Product name" value={name} set={setName}/><Field label="SKU" value={sku} set={setSku}/><Field label="Selling price ₹" value={price} set={setPrice} numeric/><Field label="GST %" value={gst} set={setGST} numeric/><Toggle label="Price includes GST" value={inclusive} set={setInclusive}/>{!id&&<Field label="Opening stock" value={stock} set={setStock} numeric/>}
    <Button title="Save on device" disabled={busy} onPress={()=>void run(async()=>{await store.enqueue(id?'product.update':'product.create',id||Crypto.randomUUID(),{name,sku,selling_price:price,gst_rate:gst,price_includes_tax:inclusive,unit:record?.unit||'pcs',...(!id?{stock}:{})},record?.version);changed();navigation.goBack();})}/></Card>
    {id&&record&&<Card><Text style={styles.subtitle}>Stock: {record.stock}</Text><Field label="Stock change (+ / − quantity)" value={delta} set={setDelta}/><Field label="Adjustment reason" value={reason} set={setReason}/><Button title="Record stock adjustment" disabled={busy} onPress={()=>void run(async()=>{await store.enqueue('stock.adjust',id,{delta,reason});changed();navigation.goBack();})}/><Button title="Deactivate product" secondary disabled={busy} onPress={()=>Alert.alert('Remove product?', 'Historical bills remain intact.',[{text:'Cancel'},{text:'Deactivate',onPress:()=>void run(async()=>{await store.enqueue('product.delete',id,{},record.version);changed();navigation.goBack();})}])}/></Card>}</Page>;
}
function Customers({navigation}:any) {
  const records=useRecords('customer'),[search,setSearch]=useState('');
  return <SafeAreaView edges={['bottom']} style={styles.page}><FlatList data={records.filter(c=>c.is_active!==false&&`${c.name} ${c.mobile}`.toLowerCase().includes(search.toLowerCase()))} keyExtractor={c=>c.id} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" ListHeaderComponent={<><Button title="＋ Add customer" onPress={()=>navigation.navigate('Customer')}/><Field label="Search name or mobile" value={search} set={setSearch}/></>} renderItem={({item:c})=><Card><Text style={styles.subtitle}>{c.name}</Text><Note>{c.mobile}</Note>{c.sync_status==='conflict'&&<Note>Sync issue — review before billing.</Note>}<Button title="Edit customer" secondary onPress={()=>navigation.navigate('Customer',{id:c.id})}/><Button title="History & collection" secondary onPress={()=>navigation.navigate('Customer Collection',{id:c.id})}/></Card>}/></SafeAreaView>;
}
function CustomerForm({route,navigation}:any) {
  const {store,changed}=useWorkspace(),id=route.params?.id,[record,setRecord]=useState<any>(null),[name,setName]=useState(''),[mobile,setMobile]=useState(route.params?.mobile||''),[address,setAddress]=useState(''),{run,busy}=useAction();
  useEffect(()=>{if(id)void store.get('customer',id).then(c=>{setRecord(c);setName(c.name);setMobile(c.mobile);setAddress(c.address||'');});},[id,store]);
  return <Page><Card><Field label="Customer name" value={name} set={setName}/><Field label="Mobile number" value={mobile} set={setMobile} numeric/><Field label="Address" value={address} set={setAddress}/><Button title="Save on device" disabled={busy} onPress={()=>void run(async()=>{await store.enqueue(id?'customer.update':'customer.create',id||Crypto.randomUUID(),{name,mobile:normalizeMobile(mobile),address},record?.version);changed();navigation.goBack();})}/>
    {record&&<Button title="Deactivate customer" secondary disabled={busy} onPress={()=>Alert.alert('Remove customer?',`${name} · ${mobile}. Existing bills and balances remain.`,[{text:'Cancel'},{text:'Deactivate',onPress:()=>void run(async()=>{await store.enqueue('customer.delete',id,{},record.version);changed();navigation.goBack();})}])}/>}</Card></Page>;
}
function CreateBill({navigation}:any) {
  const {store,changed}=useWorkspace(),products=useRecords('product'),customers=useRecords('customer'),[mobile,setMobile]=useState(''),[search,setSearch]=useState(''),[items,setItems]=useState<Line[]>([]),[discount,setDiscount]=useState('0'),[gst,setGST]=useState(false),[full,setFull]=useState(false),[paid,setPaid]=useState('0'),[qr,setQR]=useState(false),[business,setBusiness]=useState<any>(null),draft=useRef(Crypto.randomUUID()),{run,busy}=useAction();
  useEffect(()=>{void store.get('business',store.business).then(setBusiness);},[store]);
  let normalized='';try{normalized=normalizeMobile(mobile);}catch{}
  const customer=customers.find(c=>c.mobile===normalized&&c.is_active!==false);
  let total=0,problem='';try{if(items.length)total=calculate(items,discount,gst,(customer?.state_code||business?.state_code)!==business?.state_code).totals.total;}catch(e){problem=(e as Error).message;}
  return <Page><Field label="Customer mobile number" value={mobile} set={setMobile} numeric/>{customer?<Note>✓ {customer.name}</Note>:<Button title="Create customer on this phone" secondary onPress={()=>navigation.navigate('Customer',{mobile})}/>}
    <Field label="Find product" value={search} set={setSearch}/>{products.filter(p=>p.is_active!==false&&p.selling_price!=null&&`${p.name} ${p.sku}`.toLowerCase().includes(search.toLowerCase())).slice(0,search?30:5).map(p=><Button key={p.id} secondary title={`${p.name} · ₹${p.selling_price} · Stock ${p.stock}`} onPress={()=>{if(items.some(x=>x.product===p.id))return;setItems([...items,{product:p.id,description:p.name,quantity:'1',unit_price:p.selling_price,gst_rate:p.gst_rate||'0',price_includes_tax:!!p.price_includes_tax}]);setSearch('');}}/>)}
    {items.map((item,index)=><Card key={item.product}><Text style={styles.subtitle}>{item.description}</Text><Field label="Quantity" value={item.quantity} set={v=>setItems(items.map((x,i)=>i===index?{...x,quantity:v}:x))} numeric/><Field label="Unit price ₹" value={item.unit_price} set={v=>setItems(items.map((x,i)=>i===index?{...x,unit_price:v}:x))} numeric/><Button title="Remove line" secondary onPress={()=>setItems(items.filter((_,i)=>i!==index))}/></Card>)}
    <Card><Field label="Discount ₹" value={discount} set={setDiscount} numeric/><Toggle label="Apply GST" value={gst} set={setGST}/><Text style={styles.title}>{rupees(total)}</Text><Note>{problem}</Note><Toggle label="Paid in full (cash)" value={full} set={setFull}/>{!full&&<Field label="Amount received ₹ (0 = unpaid)" value={paid} set={setPaid} numeric/>}<Toggle label="Include UPI QR for balance" value={qr} set={setQR}/><Button title={busy?'Saving…':'Save bill on device'} disabled={busy||!customer||!items.length||!!problem} onPress={()=>void run(async()=>{const receipt=await store.saveBill({id:draft.current,customer:customer!.id,items,discount,gst,paid:full?'full':paid,includeQR:qr,payment_method:'cash'});changed();navigation.replace('Invoice',{id:receipt.id});})}/><Note>Saving works offline. No server request is needed.</Note></Card></Page>;
}
function Invoices({navigation}:any) {
  const invoices=useRecords('invoice');
  return <SafeAreaView edges={['bottom']} style={styles.page}><FlatList data={[...invoices].sort((a,b)=>b.date.localeCompare(a.date))} keyExtractor={i=>i.id} contentContainerStyle={styles.content} ListHeaderComponent={<Button title="＋ Create bill" onPress={()=>navigation.navigate('Create Bill')}/>} renderItem={({item:i})=><Card><Text style={styles.subtitle}>{i.number||'Provisional bill'}</Text><Note>{i.customer_snapshot.name} · {i.date}</Note><Text style={styles.text}>₹{i.total} · Pending ₹{decimal(scaled(i.total)-scaled(i.paid_amount))}</Text><Note>{i.cancelled_at?'Cancelled':i.sync_status&&i.sync_status!=='synced'?'Saved on device — awaiting sync':'Synced'}</Note><Button title="View / print / share" secondary onPress={()=>navigation.navigate('Invoice',{id:i.id})}/></Card>}/></SafeAreaView>;
}
function InvoiceDetail({route}:any) {
  const {store,refresh,changed}=useWorkspace(),[invoice,setInvoice]=useState<any>(null),[original,setOriginal]=useState<any>(null),[paid,setPaid]=useState(''),{run,busy}=useAction();
  useEffect(()=>{void store.get('invoice',route.params.id).then(setInvoice);void store.db.getFirstAsync<{body:string}>('SELECT body FROM original_receipts WHERE business=? AND id=?',store.business,route.params.id).then(r=>setOriginal(r?JSON.parse(r.body):null));},[store,route.params.id,refresh]);
  if(!invoice)return <Page><ActivityIndicator/></Page>;
  return <Page><Text style={styles.title}>{invoice.number||'Provisional bill'}</Text><Note>{invoice.customer_snapshot.name} · {invoice.date}</Note><Note>{invoice.sync_status&&invoice.sync_status!=='synced'?'Saved on device — awaiting sync':'Synchronized with Billora'}</Note><Card>{invoice.items.map((i:any,n:number)=><View key={n} style={styles.row}><Text style={[styles.text,{flex:1}]}>{i.description} × {i.quantity}</Text><Text style={styles.text}>₹{i.total}</Text></View>)}<Text style={styles.title}>₹{invoice.total}</Text><Note>Paid ₹{invoice.paid_amount} · Due ₹{decimal(scaled(invoice.total)-scaled(invoice.paid_amount))}</Note></Card>
    <Button title="Print receipt / Android print" disabled={busy} onPress={()=>void run(()=>printInvoice(invoice))}/><Button title="Direct thermal printer" secondary disabled={busy} onPress={()=>void run(()=>thermalPrint(store,invoice))}/><Button title="Save PDF / share to WhatsApp" secondary disabled={busy} onPress={()=>void run(()=>shareInvoice(invoice))}/><Note>Choose WhatsApp in Android’s share sheet. Delivery requires connectivity. Reprinting never creates another bill.</Note>
    {original&&<Button title="Export original device copy" secondary disabled={busy} onPress={()=>void run(()=>shareInvoice(original))}/>}
    {!invoice.cancelled_at&&scaled(invoice.paid_amount)<scaled(invoice.total)&&<Card><Field label="Additional payment ₹" value={paid} set={setPaid} numeric/><Button title="Record cash payment" disabled={busy} onPress={()=>void run(async()=>{await store.pay(invoice.id,paid,'cash');setPaid('');changed();})}/></Card>}</Page>;
}
function Collection({route,navigation}:any) {
  const customers=useRecords('customer'),invoices=useRecords('invoice');
  return <Page><Note>Calculated from cached invoices and payments; cancelled sales are excluded. Unsynced device bills are included and labelled.</Note>{customers.filter(c=>!route.params?.id||c.id===route.params.id).map(c=>{
    const sales=invoices.filter(i=>i.customer===c.id&&!i.cancelled_at),total=sales.reduce((a,i)=>a+scaled(i.total),0),paid=sales.reduce((a,i)=>a+scaled(i.paid_amount),0);
    return <Card key={c.id}><Text style={styles.subtitle}>{c.name}</Text><Note>{c.mobile} · {sales.length} orders</Note><Text style={styles.text}>Purchases {rupees(total)} · Received {rupees(paid)}</Text><Text style={styles.subtitle}>Outstanding {rupees(total-paid)}</Text>{route.params?.id&&sales.map(i=><Button key={i.id} title={`${i.number||'Provisional'} · ₹${i.total}`} secondary onPress={()=>navigation.navigate('Invoice',{id:i.id})}/>)}</Card>;
  })}</Page>;
}
function Settings() {
  const {store,session,lock,logout,engine}=useWorkspace(),{run,busy}=useAction();
  async function reserve() {
    const today=new Date(),fiscal=today.getMonth()>=3?today.getFullYear():today.getFullYear()-1;
    const remaining=await store.db.getFirstAsync<{n:number}>('SELECT SUM(end_number-next_number+1) n FROM number_ranges WHERE business=? AND fiscal_year=? AND next_number<=end_number',store.business,fiscal);
    if((remaining?.n||0)>20)throw new Error('This device already has enough reserved numbers.');
    let allocation=await store.db.getFirstAsync<{value:string}>('SELECT value FROM app_settings WHERE business=? AND key=?',store.business,'allocation_request');
    if(!allocation){allocation={value:Crypto.randomUUID()};await store.transaction(tx=>tx.runAsync('INSERT INTO app_settings VALUES(?,?,?)',store.business,'allocation_request',allocation!.value));}
    const range=await request('ranges',session.token,{id:allocation.value});await store.addRange(range);
    await store.transaction(tx=>tx.runAsync('DELETE FROM app_settings WHERE business=? AND key=?',store.business,'allocation_request'));Alert.alert('Numbers reserved','100 invoice numbers are available offline.');
  }
  return <Page><Card><Text style={styles.subtitle}>{session.business.name}</Text><Note>GSTIN and business identity are managed on the existing website, then downloaded by Sync Now.</Note><Button title="Reserve offline invoice numbers" disabled={busy} onPress={()=>void run(reserve)}/><Note>Without a valid range, bills are clearly provisional until synchronized. Have your accountant review numbering and GST particulars before production use.</Note></Card><UPISettings/><PrinterPanel store={store}/><Card><Button title="Export device backup" secondary disabled={busy} onPress={()=>Alert.alert('Confidential backup','This JSON export contains customer data and unsynced records. Save it only to a location you control. Recovery currently requires support; importing a backup onto another live device is unsafe.',[{text:'Cancel'},{text:'Export',onPress:()=>void run(async()=>shareBackup(await store.exportData()))}])}/><Note>Offline records are not yet backed up to Neon. Uninstalling or clearing storage can destroy them. Android automatic backup is disabled.</Note><Button title="Lock Billora" secondary onPress={lock}/><Button title="Revoke session & remove local data" secondary disabled={busy||engine.running} onPress={()=>Alert.alert('Sign out and remove this device’s data?','Requires internet and no pending changes. This removes cached customer data from this phone.',[{text:'Cancel'},{text:'Sign out',onPress:()=>void run(logout)}])}/></Card></Page>;
}
function UPISettings() {
  const {store,refresh,changed}=useWorkspace(),[business,setBusiness]=useState<any>(null),[upi,setUPI]=useState(''),[payee,setPayee]=useState(''),{busy,run}=useAction();
  useEffect(()=>{void store.get('business',store.business).then(b=>{setBusiness(b);setUPI(b.settings.upi_id||'');setPayee(b.settings.upi_payee_name||'');});},[store,refresh]);
  return <Card><Text style={styles.subtitle}>UPI payments</Text><Field label="UPI ID" value={upi} set={setUPI}/><Field label="Payee name" value={payee} set={setPayee}/><Button title="Save UPI settings on device" disabled={busy} onPress={()=>void run(async()=>{if(!business?.version)throw new Error('Complete the first sync before changing business settings.');await store.enqueue('business.settings',store.business,{upi_id:upi,upi_payee_name:payee},business.version);changed();Alert.alert('Saved','Settings will synchronize before subsequent offline bills.');})}/><Note>QR codes request payment only. They do not confirm that money was received.</Note></Card>;
}
function SyncStatus() {
  const {store,engine,syncText,refresh}=useWorkspace(),[status,setStatus]=useState<any>({}),{busy,run}=useAction();
  useEffect(()=>{void store.status().then(setStatus);},[store,refresh]);
  return <Page><Text style={styles.title}>{syncText}</Text><Note>{status.pending?.n||0} pending changes · {status.invoices?.n||0} pending invoices</Note><Note>Last complete sync: {status.checkpoint?.completed_at||'Never'}</Note><Button title="Sync now" disabled={busy||engine.running} onPress={()=>void engine.run(true)}/>{status.conflicts?.map((c:any)=><Card key={c.id}><Text style={styles.subtitle}>Review required</Text><Text style={styles.text}>{c.detail}</Text><Note>Reference {c.id}</Note><Note>The original event remains on this phone and in the server audit. Financial conflicts require an administrator/accountant to reconcile; no automatic overwrite or discard is performed.</Note></Card>)}<Button title="Export records for reconciliation" secondary disabled={busy} onPress={()=>Alert.alert('Export confidential data?','Share only with your authorized administrator.',[{text:'Cancel'},{text:'Export',onPress:()=>void run(async()=>shareBackup(await store.exportData()))}])}/></Page>;
}
export const styles=StyleSheet.create({page:{flex:1,backgroundColor:colors.bg},center:{flex:1,alignItems:'center',justifyContent:'center',backgroundColor:colors.bg},content:{padding:20,paddingBottom:40},brand:{fontSize:16,letterSpacing:5,color:colors.primary,fontWeight:'800',marginTop:36,marginBottom:20},title:{fontSize:30,lineHeight:38,fontWeight:'800',color:colors.heading,marginBottom:10},subtitle:{fontSize:19,fontWeight:'700',color:colors.heading,marginBottom:8},text:{fontSize:15,lineHeight:23,color:colors.text},note:{fontSize:13,lineHeight:20,color:colors.text,marginBottom:12},label:{fontSize:13,fontWeight:'600',color:colors.heading,marginBottom:6},input:{borderColor:colors.border,borderWidth:1,borderRadius:12,padding:14,minHeight:50,fontSize:16,color:colors.heading,backgroundColor:colors.card},button:{backgroundColor:colors.primary,borderRadius:14,padding:16,minHeight:52,justifyContent:'center',marginVertical:6},secondary:{backgroundColor:colors.surface,borderWidth:1,borderColor:colors.border},card:{backgroundColor:colors.card,borderRadius:20,borderWidth:1,borderColor:colors.border,padding:18,marginVertical:10},row:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:12,marginVertical:6}});
