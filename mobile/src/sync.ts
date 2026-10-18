import {Store} from './store';
import {request, pullRequest, SessionExpired} from './api';
import type {Session} from './security';
const activeStores = new WeakSet<Store>();

export class SyncEngine {
  running = false;
  stopped = false;
  constructor(private store: Store, private session: Session, private notify: (message: string, expired?: boolean) => void,
    private persistSession: (session: Session) => Promise<void>,
    private transport = {push: (payload: unknown, token: string) => request('push', token, payload), pull: pullRequest}) {}
  async run(manual = false) {
    if (this.running || this.stopped || activeStores.has(this.store)) return;
    activeStores.add(this.store);
    this.running = true; this.notify('Connecting to server…');
    try {
      // Resume any interrupted download before pushing fresh operations.
      // With an accepted operation from a lost ACK, replay is safe on the server.
      const operations = await this.store.pending();
      for (const row of operations) {
        if (this.stopped) return;
        if (!manual && row.retry_at > Date.now()) break;
        try {
          const result = await this.transport.push(JSON.parse(row.payload), this.session.token);
          if (this.stopped) return; // replay after unlock safely recovers a response lost here
          if (!['accepted','conflict'].includes(result.status)) throw new Error('Unexpected sync response.');
          await this.store.acknowledge(row.id, result);
        } catch (error) {if (!this.stopped) await this.store.retryLater(row); throw error;}
      }
      let more = true;
      while (more && !this.stopped) {
        const status = await this.store.status();
        const response = await this.transport.pull(status.checkpoint?.cursor || '', this.session.token);
        if (this.stopped) return;
        if (!Array.isArray(response.changes) || typeof response.cursor !== 'string') throw new Error('Invalid sync response.');
        more = response.has_more === true;
        this.store.role = response.role;
        this.session.role = response.role; await this.persistSession(this.session);
        await this.store.pullPage(response.changes, response.cursor, !more);
      }
      this.notify(this.stopped ? 'Sync paused' : 'Up to date');
    } catch (error) {
      if (this.stopped) return;
      const expired = error instanceof SessionExpired;
      if (expired) {this.stopped = true; this.session.blocked = true; await this.persistSession(this.session);}
      this.notify(error instanceof Error ? error.message : 'Sync failed. Local changes remain safe.', expired);
    } finally {this.running = false; activeStores.delete(this.store);}
  }
}
