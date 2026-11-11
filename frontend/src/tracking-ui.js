import { getCurrentLocation } from './location.js';
export function mapEmbedUrl(latitude,longitude){
  const lat=Number(latitude),lon=Number(longitude);if(!Number.isFinite(lat)||!Number.isFinite(lon)||Math.abs(lat)>90||Math.abs(lon)>180)return '';
  const y=Math.min(85,Math.max(-85,lat)),bbox=[Math.max(-180,lon-.025),Math.max(-85,y-.018),Math.min(180,lon+.025),Math.min(85,y+.018)].join(',');
  return 'https://www.openstreetmap.org/export/embed.html?bbox='+encodeURIComponent(bbox)+'&layer=mapnik&marker='+encodeURIComponent(lat+','+lon);
}

export function createTrackingUi(ctx){
  const {state,shell,esc,notify,render,ticketRole}=ctx;
  let owner='',data=null,loading=false,timer=null,secret=null,selectedBus='',generation=0;
  async function api(path,body,method=body===undefined?'GET':'POST'){
    if(!navigator.onLine||!state.authToken)throw Error('Connexion requise pour le suivi GPS.');
    const account=state.company.id+':'+state.user.id;
    const r=await fetch(ctx.serverUrl()+'/api/v2/gps'+path,{method,headers:{Authorization:'Bearer '+state.authToken,'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
    const d=await r.json();if(account!==state.company?.id+':'+state.user?.id)throw Error('Le compte actif a changé.');if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'Opération GPS impossible.');return d;
  }
  async function load(){
    if(loading)return;loading=true;const epoch=generation;
    try{const result=await api('/fleet');if(epoch===generation){data=result;render();}}
    catch(e){if(epoch===generation){data={error:e.message};notify(e.message,'warning');render();}}
    finally{if(epoch===generation)loading=false;}
  }
  function panel(){
    const key=state.company?.id+':'+state.user?.id;if(owner!==key){owner=key;generation++;data=null;loading=false;secret=null;selectedBus='';}
    const buses=data?.buses||[],bus=buses.find(b=>b.id===selectedBus)||buses.find(b=>b.position)||buses[0],p=bus?.position;
    return shell(`<section class="panel transport-hero"><div><span class="eyebrow">SUIVI DES VÉHICULES</span><h2>Les positions réelles, au même endroit</h2><p>Téléphone de l’équipage ou boîtier installé dans le véhicule. Les positions anciennes restent signalées.</p></div><button id="gpsRefresh">Actualiser</button></section>${data?.error?`<section class="panel">${esc(data.error)}</section>`:!data?'<section class="panel" role="status">Chargement du suivi…</section>':`<section class="panel"><label>Véhicule<select id="gpsBus">${buses.map(b=>`<option value="${esc(b.id)}" ${b.id===bus?.id?'selected':''}>${esc(b.name)} · ${esc(b.registration)}</option>`).join('')}</select></label>${p?`<p class="${p.ageSeconds>300?'gps-stale':'gps-fresh'}"><b>${p.ageSeconds>300?'Position ancienne':'Dernière position reçue'}</b> · ${esc(new Date(p.recordedAt).toLocaleString('fr-FR'))} · ${p.source==='device'?'Boîtier GPS':'Téléphone'}${p.accuracy!==null&&p.accuracy!==undefined?' · précision '+Math.round(p.accuracy)+' m':''}${p.speedKph!==null&&p.speedKph!==undefined?' · '+p.speedKph+' km/h':''}</p><iframe class="gps-map" title="Position du véhicule sur la carte" loading="lazy" referrerpolicy="no-referrer" src="${esc(mapEmbedUrl(p.latitude,p.longitude))}"></iframe>`:'<div class="empty">Aucune position reçue. Transmettez la position depuis le téléphone de l’équipage ou configurez un boîtier GPS.</div>'}</section><div class="gps-cards">${buses.map(b=>`<article class="gps-card"><div><strong>${esc(b.name)}</strong><small>${esc(b.registration)}</small></div>${b.position?`<span class="${b.position.ageSeconds>300?'gps-stale':'gps-fresh'}">${b.position.ageSeconds>300?'Position ancienne':'Position reçue'} · ${esc(new Date(b.position.recordedAt).toLocaleTimeString('fr-FR'))}</span>`:'<small>Aucune position</small>'}<button data-gps-bus="${esc(b.id)}">Voir sur la carte</button></article>`).join('')}</div><section class="panel"><h3>Transmettre depuis ce téléphone</h3><p>Choisissez votre voyage et autorisez la localisation. Le suivi continu du téléphone reste dans Pilotage & services ; gardez l’application ouverte.</p><label>Voyage<select id="gpsPhoneTrip"><option value="">Choisir le voyage</option>${(data.trips||[]).filter(t=>!['Arrivé','Annulé','Terminé','Clôturé'].includes(t.status)).map(t=>`<option value="${esc(t.id)}">${esc(t.origin)} → ${esc(t.destination)} · ${esc(new Date(t.departureAt).toLocaleString('fr-FR'))}</option>`).join('')}</select></label><div class="button-row"><button id="gpsPhone" class="primary">Partager ma position</button><button data-page="ticketPilotage">Équipage & suivi continu</button></div><p id="gpsPhoneStatus" role="status"></p></section>${ticketRole('manager')?`<section class="panel"><h3>Boîtiers GPS des véhicules</h3><p>Associez un boîtier à son bus. La clé d’envoi est propre au boîtier et reste distincte des comptes des agents.</p><form id="gpsDeviceForm" class="settings-form no-wizard"><div class="grid"><label>Bus<select name="busId" required>${buses.map(b=>`<option value="${esc(b.id)}">${esc(b.name)} · ${esc(b.registration)}</option>`).join('')}</select></label><label>Nom du boîtier<input name="label" required maxlength="120"></label><label>Référence du matériel<input name="externalId" maxlength="120"></label></div><button type="submit" class="primary">Associer un boîtier</button></form>${secret?`<div class="gps-secret"><b>Clé affichée une seule fois</b><p>Conservez-la dans la configuration du boîtier ou de sa passerelle.</p><label>Clé d’envoi<input id="gpsDeviceSecret" class="gps-key-input" readonly value="${esc(secret.token)}"></label><button id="gpsCopySecret">Copier la clé</button><pre class="gps-key">POST ${esc(secret.endpoint)}\nAuthorization: Bearer [clé du boîtier]</pre><button id="gpsForgetSecret">Masquer la clé</button></div>`:''}${(data.devices||[]).map(d=>`<article class="ext-row"><div><b>${esc(d.label)}</b><small>${esc(d.externalId||'')} · ${d.active?'Actif':'Désactivé'}</small></div><div class="button-row"><button data-gps-toggle="${esc(d.id)}" data-active="${d.active}">${d.active?'Désactiver':'Activer'}</button><button data-gps-rotate="${esc(d.id)}">Renouveler la clé</button></div></article>`).join('')}</section>`:''}`}`);
  }
  async function run(b,fn){if(b.disabled)return;b.disabled=true;b.setAttribute('aria-busy','true');try{await fn();}catch(e){notify(e.message,'error',8000);}finally{if(b.isConnected){b.disabled=false;b.removeAttribute('aria-busy');}}}
  function bind(){
    if(state.page!=='ticketTracking'){if(timer)clearInterval(timer);timer=null;owner='';secret=null;generation++;data=null;loading=false;return;}
    if(!data&&!loading)load();if(!timer)timer=setInterval(()=>{if(!document.hidden&&navigator.onLine&&!document.querySelector('#gpsDeviceForm input:focus')&&!secret)load();},30000);
    document.querySelector('#gpsRefresh')?.addEventListener('click',()=>load());
    document.querySelector('#gpsBus')?.addEventListener('change',e=>{selectedBus=e.target.value;render();});document.querySelectorAll('[data-gps-bus]').forEach(b=>b.onclick=()=>{selectedBus=b.dataset.gpsBus;render();document.querySelector('.gps-map')?.scrollIntoView({behavior:'smooth',block:'center'});});
    const f=document.querySelector('#gpsDeviceForm');if(f)f.onsubmit=e=>{e.preventDefault();run(f.querySelector('button'),async()=>{secret=await api('/devices',Object.fromEntries(new FormData(f)));f.reset();await load();});};
    document.querySelector('#gpsForgetSecret')?.addEventListener('click',()=>{secret=null;render();});document.querySelector('#gpsCopySecret')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(secret.token);notify('Clé copiée.','success');}catch{document.querySelector('#gpsDeviceSecret').select();notify('Sélectionnez puis copiez la clé.','info');}});
    document.querySelectorAll('[data-gps-toggle]').forEach(b=>b.onclick=()=>run(b,async()=>{await api('/devices/'+encodeURIComponent(b.dataset.gpsToggle),{active:b.dataset.active!=='true'},'PUT');await load();}));
    document.querySelectorAll('[data-gps-rotate]').forEach(b=>b.onclick=()=>run(b,async()=>{if(!confirm('Remplacer la clé du boîtier ? L’ancienne clé cessera de fonctionner.'))return;secret=await api('/devices/'+encodeURIComponent(b.dataset.gpsRotate)+'/rotate',{});await load();}));
    document.querySelector('#gpsPhone')?.addEventListener('click',e=>run(e.currentTarget,async()=>{
      const tripId=document.querySelector('#gpsPhoneTrip').value;if(!tripId)throw Error('Choisissez le voyage.');
      const position=await getCurrentLocation();
      await ctx.operationsApi('/trips/'+encodeURIComponent(tripId)+'/tracking',{id:crypto.randomUUID(),stage:'Position',latitude:position.coords.latitude,longitude:position.coords.longitude,accuracy:position.coords.accuracy});await load();notify('Position transmise.','success');
    }));
  }
  return {panel,bind};
}
