import React, {useEffect, useRef, useState} from 'react';
import {ActivityIndicator, Alert, AppState, Linking, NativeModules, PermissionsAndroid, Platform, Pressable, StyleSheet, Text, TextInput, View} from 'react-native';
import type {Store} from './store';
import {bufferToBase64, Printer, validatePrinter} from './printer-protocol';
import {sendReceipt} from './print-job';

type Device={name:string;address:string};
const native=NativeModules.BilloraPrinter;
const requiresPermission=()=>Platform.OS==='android'&&Number(Platform.Version)>=31;
async function permission(transport:string){
  if(!native)throw new Error('Direct printing requires a rebuilt native Billora Android APK. It is unavailable in Expo Go or the browser.');
  if(transport==='bluetooth'&&requiresPermission()){
    const result=await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT);
    if(result!==PermissionsAndroid.RESULTS.GRANTED)throw new Error('Allow Nearby devices in Android app permissions, then refresh printers.');
  }
}
export async function thermalPrint(store:Store,invoice:any,active:()=>boolean=()=>AppState.currentState==='active'){
  const sent=await sendReceipt(store,invoice,{
    prepare:printer=>permission(printer.transport),active,
    confirmReprint:()=>new Promise<boolean>(resolve=>Alert.alert('Reprint receipt?','A previous print was attempted. Check the paper to avoid a duplicate receipt.',[{text:'Cancel',onPress:()=>resolve(false)},{text:'Reprint',onPress:()=>resolve(true)}],{cancelable:false})),
    send:async(printer,payload)=>{
      try{await native.print(printer.transport,printer.address,payload);}
      catch(e){throw new Error(`${(e as Error).message} Check the paper before retrying; no automatic retry was made.`);}
    }
  });
  if(sent&&active())Alert.alert('Receipt sent','Check the physical receipt. Sending bytes does not confirm paper was printed.');
}

export function PrinterPanel({store}:{store:Store}) {
  const [printer,setPrinter]=useState<Printer>({transport:'bluetooth',address:'',width:58});
  const [saved,setSaved]=useState<Printer|null>(null),[devices,setDevices]=useState<Device[]>([]);
  const [busy,setBusy]=useState(false),[loaded,setLoaded]=useState(false),[status,setStatus]=useState('Pair your printer, then select it below.');
  const mounted=useRef(true),working=useRef(false);
  const active=()=>mounted.current&&AppState.currentState==='active';
  async function list(transport:Printer['transport'],ask=true){
    if(ask)await permission(transport);
    else if(!native || (transport==='bluetooth'&&requiresPermission()&&!(await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT))))return;
    if(!active())return;
    if(transport==='bluetooth'){
      if(!native.bluetoothStatus)throw new Error('Rebuild the Android APK to enable Bluetooth setup.');
      const state=await native.bluetoothStatus();
      if(!state.available)throw new Error('This phone has no Bluetooth adapter.');
      if(!state.enabled){setDevices([]);setStatus('Bluetooth is off. Open Android Bluetooth settings to turn it on.');return;}
    }
    const found:Device[]=transport==='lan'?[]:await native.devices(transport);
    if(!active())return;
    setDevices(found.sort((a,b)=>(a.name||'').localeCompare(b.name||'')));
    setStatus(found.length?'Select your printer below. Paired devices can include other accessories.':transport==='lan'?'Enter the printer’s local IPv4 address.':'No paired printers found. Pair in Android settings, return and refresh.');
  }
  useEffect(()=>{
    mounted.current=true;
    void (async()=>{
      try{
        const row=await store.db.getFirstAsync<{value:string}>('SELECT value FROM app_settings WHERE business=? AND key=?',store.business,'printer');
        const value=row?validatePrinter(JSON.parse(row.value)):null;
        if(!mounted.current)return;
        if(value){setPrinter(value);setSaved(value);}
        await list(value?.transport||'bluetooth',false);
      }catch(e){if(mounted.current)setStatus((e as Error).message);}
      finally{if(mounted.current)setLoaded(true);}
    })();
    return()=>{mounted.current=false;};
  },[store]);
  async function run(action:()=>Promise<void>){
    if(working.current||!loaded)return;
    working.current=true;setBusy(true);
    try{await action();}catch(e){if(active()){setStatus((e as Error).message);Alert.alert('Printer',(e as Error).message);}}
    finally{working.current=false;if(mounted.current)setBusy(false);}
  }
  const button=(title:string,onPress:()=>void,disabled=false)=><Pressable accessibilityRole="button" disabled={busy||!loaded||disabled} onPress={onPress} style={[styles.button,(busy||!loaded||disabled)&&{opacity:0.5}]}><Text style={styles.text}>{title}</Text></Pressable>;
  const save=async(value:Printer)=>{
    await store.transaction(tx=>tx.runAsync('INSERT OR REPLACE INTO app_settings VALUES(?,?,?)',store.business,'printer',JSON.stringify(value)));
    if(active())setSaved(value);
  };
  return <View style={styles.card}>
    <Text style={styles.title}>Thermal printer</Text>
    <Text style={styles.note}>{saved?`Saved: ${saved.name||saved.address} · ${saved.width} mm`:'No printer saved on this phone.'}</Text>
    <Text style={styles.note}>Works offline. Choose Bluetooth for a portable receipt printer.</Text>
    <View style={styles.row}>{(['bluetooth','lan','usb'] as const).map(transport=><Pressable key={transport} accessibilityRole="radio" accessibilityState={{checked:printer.transport===transport}} disabled={busy||!loaded} onPress={()=>void run(async()=>{setPrinter({transport,address:'',width:printer.width});setDevices([]);await list(transport);})} style={[styles.choice,printer.transport===transport&&styles.selected]}><Text style={styles.text}>{transport==='bluetooth'?'Bluetooth':transport.toUpperCase()}</Text></Pressable>)}</View>
    {printer.transport==='bluetooth'&&<>
      {button('Pair printer / turn on Bluetooth',()=>void run(async()=>{if(!native)await permission('bluetooth');await native.pair();}))}
      <Text style={styles.note}>Pair in Android settings, return to Billora and unlock. Your printer page will reopen.</Text>
      {button('Android app permissions',()=>void Linking.openSettings().catch(()=>Alert.alert('Permissions','Open Android Settings → Apps → Billora → Permissions.')))}
    </>}
    {printer.transport!=='lan'&&button('Refresh printer list',()=>void run(()=>list(printer.transport)))}
    {devices.map(device=><Pressable key={device.address} accessibilityRole="radio" accessibilityState={{checked:printer.address===device.address}} disabled={busy||!loaded} style={[styles.device,printer.address===device.address&&styles.selected]} onPress={()=>{setPrinter({...printer,address:device.address,name:device.name});setStatus('Selected. Tap Connect & save, then print a test receipt.');}}><Text style={styles.text}>{printer.address===device.address?'✓ ':''}{device.name||'Unnamed device'}</Text><Text style={styles.note}>{device.address}</Text></Pressable>)}
    {printer.transport==='lan'?<TextInput accessibilityLabel="Printer IPv4 address" editable={!busy&&loaded} style={styles.device} placeholder="192.168.1.100" value={printer.address} onChangeText={address=>setPrinter({...printer,address,name:undefined})} autoCapitalize="none" keyboardType="decimal-pad"/>:<Text style={styles.note}>Selected: {printer.name||printer.address||'None'}</Text>}
    {button(`Paper width: ${printer.width} mm (tap to change)`,()=>setPrinter({...printer,width:printer.width===58?80:58}))}
    {button(printer.transport==='bluetooth'?'Connect & save printer':'Save printer',()=>void run(async()=>{
      const value=validatePrinter(printer);await permission(value.transport);if(!active())return;
      if(value.transport==='bluetooth'){setStatus('Connecting to printer…');await native.checkBluetooth(value.address);}
      if(!active())return;await save(value);
      if(active())setStatus(value.transport==='bluetooth'?'Connection tested and printer saved. Billora reconnects for each receipt.':'Printer saved. Print a test receipt to verify it.');
    }),!printer.address)}
    {button('Print test receipt',()=>void run(async()=>{
      const value=validatePrinter(printer);await permission(value.transport);if(!active())return;
      setStatus('Sending test receipt…');
      const text=`BILLORA TEST\n${value.width} mm paper\n${'-'.repeat(value.width===58?32:48)}\nThermal printing\nCheck alignment and legibility.\n\n\n`;
      try{await native.print(value.transport,value.address,bufferToBase64([27,64,...Array.from(text,c=>c.charCodeAt(0)),29,86,0]));}
      catch(e){throw new Error(`${(e as Error).message} Check the paper before retrying.`);}
      if(active())setStatus('Test sent. Check the paper, then Connect & save if you changed printers.');
    }),!printer.address)}
    {saved&&button('Forget saved printer',()=>void run(async()=>{
      await store.transaction(tx=>tx.runAsync('DELETE FROM app_settings WHERE business=? AND key=?',store.business,'printer'));
      if(active()){setSaved(null);setPrinter({...printer,address:'',name:undefined});setStatus('Printer removed from Billora. Android pairing is unchanged.');}
    }))}
    {(busy||!loaded)&&<ActivityIndicator color="#79634D"/>}
    <Text accessibilityLiveRegion="polite" style={styles.status}>{status}</Text>
    <Text style={styles.note}>Supports Bluetooth Classic SPP / ESC/POS, LAN port 9100 and USB OTG. BLE-only printers need a compatible vendor print service. Use PDF / Android printing for Hindi text. Never retry an uncertain print before checking the paper.</Text>
  </View>;
}
const styles=StyleSheet.create({
  card:{padding:18,backgroundColor:'#FFFDF9',borderRadius:20,marginVertical:12},
  title:{fontSize:20,fontWeight:'700',color:'#40352B'},text:{color:'#40352B',fontWeight:'600'},
  note:{color:'#675A4B',lineHeight:20,marginVertical:6},status:{color:'#40352B',lineHeight:21,marginVertical:12},
  button:{backgroundColor:'#F4EDE3',padding:16,borderRadius:12,marginVertical:5},
  row:{flexDirection:'row',flexWrap:'wrap',gap:8,marginVertical:10},choice:{padding:12,borderRadius:12,borderWidth:1,borderColor:'#E8DCCB'},
  selected:{backgroundColor:'#E9F2E9',borderColor:'#3F8A69'},device:{padding:14,borderWidth:1,borderColor:'#E8DCCB',borderRadius:12,marginVertical:4}
});
