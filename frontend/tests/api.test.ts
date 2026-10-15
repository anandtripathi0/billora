import { describe, expect, it, vi, afterEach } from 'vitest';
import { api, send } from '@/lib/api';
afterEach(()=>vi.unstubAllGlobals());
describe('session API client',()=>{
  it('fetches CSRF token before mutation and includes cookies',async()=>{const fetcher=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({csrfToken:'server-token'})}).mockResolvedValueOnce({ok:true,json:async()=>({id:1})});vi.stubGlobal('fetch',fetcher);await send('products/',{name:'Notebook'});expect(fetcher.mock.calls[0][0]).toBe('/api/auth/csrf/');expect(fetcher.mock.calls[1][1].headers.get('X-CSRFToken')).toBe('server-token');expect(fetcher.mock.calls[1][1].credentials).toBe('include');});
  it('surfaces server validation errors',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:400,json:async()=>({stock:['Insufficient stock.']})}));await expect(api('products/')).rejects.toThrow('stock: Insufficient stock.');});
});
