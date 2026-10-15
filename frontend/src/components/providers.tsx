'use client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { MotionConfig } from 'motion/react';
import { CheckCircle2, AlertCircle, X } from 'lucide-react';
type Toast = {message: string; error?: boolean};
const NoticeContext = createContext<(message: string, error?: boolean) => void>(() => {});
export const useNotice = () => useContext(NoticeContext);
export function Providers({children}: {children: React.ReactNode}) {
  const [client] = useState(() => new QueryClient({defaultOptions: {queries: {staleTime: 30000, retry: 1, refetchOnWindowFocus: false}}}));
  const [toast, setToast] = useState<Toast | null>(null);
  const notify = useCallback((message: string, error = false) => setToast({message, error}), []);
  useEffect(() => { if (!toast) return; const id = setTimeout(() => setToast(null), 7000); return () => clearTimeout(id); }, [toast]);
  return <QueryClientProvider client={client}><MotionConfig reducedMotion="user"><NoticeContext.Provider value={notify}>{children}{toast && <div className={`toast ${toast.error ? 'toast-error' : ''}`} role={toast.error ? 'alert' : 'status'}>{toast.error ? <AlertCircle size={20}/> : <CheckCircle2 size={20}/>}<span>{toast.message}</span><button onClick={() => setToast(null)} aria-label="Dismiss notification"><X size={16}/></button></div>}</NoticeContext.Provider></MotionConfig></QueryClientProvider>;
}
