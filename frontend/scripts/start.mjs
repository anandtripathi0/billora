import { cpSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

if (existsSync('.env.local')) process.loadEnvFile('.env.local');
const output = resolve('.next/standalone');
if (!existsSync(`${output}/server.js`)) throw new Error('Build Billora first: npm run build');
// Next standalone does not bundle these directories automatically.
cpSync('.next/static', `${output}/.next/static`, { recursive: true });
if (existsSync('public')) cpSync('public', `${output}/public`, { recursive: true });
process.env.HOSTNAME ||= '127.0.0.1';
process.env.PORT ||= '3000';
await import(pathToFileURL(`${output}/server.js`).href);
