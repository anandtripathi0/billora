import type { Metadata } from 'next';
import { Providers } from '@/components/providers';
import { GeistSans } from 'geist/font/sans';
import './globals.css';
export const metadata: Metadata = {title: {default: 'Billora — Business, beautifully in balance.', template: '%s · Billora'}, description: 'A considered workspace for Indian businesses. Invoices, inventory, customers and payments, together.'};
export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) { return <html lang="en" className={GeistSans.variable}><body><Providers>{children}</Providers></body></html>; }
