import * as SecureStore from 'expo-secure-store';
import * as SQLite from 'expo-sqlite';
import * as Crypto from 'expo-crypto';
import * as LocalAuthentication from 'expo-local-authentication';
import {Store, Database} from './store';
import {apiBase, request} from './api';

export type Session = {token: string; device_id: string; user_id: number; business: {id: string; [key: string]: any}; role: string; expires_at: string; api: string; blocked?: boolean};
const options = {keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY};
export async function savedSession(): Promise<Session | null> {
  const text = await SecureStore.getItemAsync('billora.session');
  return text ? JSON.parse(text) : null;
}
export async function persistSession(session: Session) {await SecureStore.setItemAsync('billora.session', JSON.stringify(session), options);}
export async function unlock() {
  const level = await LocalAuthentication.getEnrolledLevelAsync();
  if (level === LocalAuthentication.SecurityLevel.NONE) throw new Error('Set an Android screen-lock PIN or biometric before using Billora offline.');
  const result = await LocalAuthentication.authenticateAsync({promptMessage: 'Unlock Billora', cancelLabel: 'Cancel', disableDeviceFallback: false});
  if (!result.success) throw new Error('Device unlock cancelled.');
}
export async function activate(mobile: string, password: string) {
  await unlock();
  const existing = await savedSession(), api = apiBase();
  if (existing && existing.api !== api) throw new Error('The API server changed. Restore the previous build and sync/export before switching servers.');
  const result = await request<Session>('login', undefined, {mobile, password, name: 'Billora Android', ...(existing ? {device_id: existing.device_id} : {})});
  if (existing && (existing.user_id !== result.user_id || existing.business.id !== result.business.id)) throw new Error('This device contains another shop’s data.');
  const session = {...result, api, blocked: false};
  await persistSession(session); return session;
}
export async function openStore(session: Session) {
  if (session.api !== apiBase()) throw new Error('API configuration changed. Restore the previous API before opening this database.');
  const keyName = `billora.key.${session.device_id}`, dbName = `billora-${session.device_id}.db`;
  let key = await SecureStore.getItemAsync(keyName);
  if (!key) {
    // No fallback key or destructive recreation if an existing encrypted DB cannot open.
    key = Array.from(await Crypto.getRandomBytesAsync(32), x => x.toString(16).padStart(2, '0')).join('');
    await SecureStore.setItemAsync(keyName, key, options);
  }
  if (!/^[a-f0-9]{64}$/.test(key)) throw new Error('Invalid database key. Contact support; do not clear storage.');
  const db = await SQLite.openDatabaseAsync(dbName);
  await db.execAsync(`PRAGMA key = "x'${key}'";`);
  const cipher = await db.getFirstAsync('PRAGMA cipher_version');
  if (!cipher) {await db.closeAsync(); throw new Error('Use a standalone SQLCipher-enabled build. Expo Go is not supported.');}
  // Expo's default exclusive transaction opens another connection without replaying
  // PRAGMA key. Explicitly key each writer before its first database read/write.
  const database: Database = {
    execAsync: sql => db.execAsync(sql),
    runAsync: (sql, ...args) => db.runAsync(sql, ...args),
    getFirstAsync: (sql, ...args) => db.getFirstAsync(sql, ...args),
    getAllAsync: (sql, ...args) => db.getAllAsync(sql, ...args),
    closeAsync: () => db.closeAsync(),
    withExclusiveTransactionAsync: async task => {
      const writer = await SQLite.openDatabaseAsync(dbName, {useNewConnection: true});
      try {
        await writer.execAsync(`PRAGMA key = "x'${key}'"; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;`);
        await writer.execAsync('BEGIN IMMEDIATE');
        try {await task(writer); await writer.execAsync('COMMIT');}
        catch (error) {await writer.execAsync('ROLLBACK'); throw error;}
      } finally {await writer.closeAsync();}
    }
  };
  const store = new Store(database, session.business.id, Crypto.randomUUID);
  store.role = session.role; await store.init(); return store;
}
export async function signOut(session: Session, store: Store) {
  const status = await store.status();
  if (status.pending?.n) throw new Error('Unsynced changes remain. Sync or resolve them before removing device data. You can lock the app instead.');
  await request('devices', session.token, {device_id: session.device_id});
  await store.db.closeAsync?.();
  await SQLite.deleteDatabaseAsync(`billora-${session.device_id}.db`);
  await SecureStore.deleteItemAsync(`billora.key.${session.device_id}`);
  await SecureStore.deleteItemAsync('billora.session');
}
