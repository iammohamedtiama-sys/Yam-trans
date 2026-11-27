const {execFileSync}=require('node:child_process');
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
execFileSync(process.platform==='win32'?'npx.cmd':'npx',['vite','build','--config','vite.passenger.config.js'],{stdio:'inherit'});
const dir=path.resolve(__dirname,'../passenger-dist');
const assets=['./','./index.html','./manifest.webmanifest',...fs.readdirSync(path.join(dir,'assets')).map(f=>'./assets/'+f),'./icon-192.png','./icon-512.png'];
const version=crypto.createHash('sha256').update(assets.join()).digest('hex').slice(0,12);
fs.writeFileSync(path.join(dir,'sw.js'),`const CACHE='yam-voyageurs-${version}';const ASSETS=${JSON.stringify(assets)};self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS))));self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('yam-voyageurs-')&&k!==CACHE).map(k=>caches.delete(k))))));self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==location.origin||u.pathname.includes('/api/'))return;const allowed=ASSETS.some(a=>new URL(a,self.registration.scope).pathname===u.pathname);if(!allowed)return;e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)))})`);
