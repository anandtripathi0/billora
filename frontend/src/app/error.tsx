'use client';
export default function Error({reset}:{error:Error;reset:()=>void}){return <main className="screen-center"><h1>Something interrupted your workspace.</h1><p>Please try again.</p><button className="btn btn-primary" onClick={reset}>Try again</button></main>;}
