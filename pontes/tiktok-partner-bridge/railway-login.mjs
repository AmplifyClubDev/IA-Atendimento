import {chromium} from 'playwright';import {defaults} from './invite.mjs';
let context;let closing=false;
async function close(){if(closing)return;closing=true;try{await context?.close();}finally{process.exit(0);}}
process.on('SIGTERM',close);process.on('SIGINT',close);
context=await chromium.launchPersistentContext(defaults.profileDir,{headless:false,viewport:{width:1440,height:1000}});
let page=context.pages().find(p=>!p.isClosed())||await context.newPage();
await page.goto(defaults.partnerUrl,{waitUntil:'domcontentloaded',timeout:60000}).catch(()=>console.error('LOGIN_NAVIGATION_PENDING'));
console.log('LOGIN_BROWSER_OPEN');
await new Promise(()=>{});
