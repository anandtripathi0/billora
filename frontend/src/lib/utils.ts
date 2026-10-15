import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
export function currency(value: string | number = 0) { return new Intl.NumberFormat('en-IN', {style: 'currency', currency: 'INR', maximumFractionDigits: 2}).format(Number(value)); }
export function human(value: string) { return value.replaceAll('__', ' ').replaceAll('_', ' ').replace(/\b\w/g, l => l.toUpperCase()); }
