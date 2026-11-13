import { jsPDF } from 'jspdf';
import './extensions.css';

// Server-authoritative services. Operational records are never cached across accounts.
export function createExtensionsUi(ctx) {
  const {state, shell, esc, money, uid, ticketRole, notify, render, serverUrl} = ctx;
  let owner='', tab='search', data=null, loading=false, generation=0, results=null;
  const can = role => ticketRole(role);
  const tabs = () => [
    ...(can('sales') || can('dispatch') || can('reports') ? [['search','Rechercher un départ']] : []),
    ...(can('dispatch') ? [['schedule','Calendrier'],['stock','Stock de pièces']] : []),
    ...(can('dispatch') || can('sales') || can('reports') ? [['charters','Voyages privés'],['parking','Parking']] : []),
    ...(can('reports') ? [['messages','Messages par étape']] : []),
    ...(can('manager') ? [['backup','Sauvegarde']] : [])
  ];
  async function api(path, body, method=body===undefined?'GET':'POST') {
    if(!navigator.onLine || !state.authToken) throw Error('Connectez-vous au serveur pour cette opération.');
    const key=state.company.id+':'+state.user.id;
    const response=await fetch(serverUrl()+'/api/v2/extensions'+path,{
      method, headers:{Authorization:'Bearer '+state.authToken,'Content-Type':'application/json'},
      ...(body===undefined?{}:{body:JSON.stringify(body)})
    });
    const value=await response.json();
    if(key!==state.company?.id+':'+state.user?.id) throw Error('Le compte actif a changé.');
    if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'Vérifiez les informations saisies.');
    return value;
  }
  async function load() {
    if(loading)return;
    loading=true;const epoch=generation;
    try {const value=await api('/state');if(epoch===generation)data=value;}
    catch(e){if(epoch===generation){data={error:e.message};notify(e.message,'warning');}}
    finally {if(epoch===generation){loading=false;if(state.page==='ticketExtensions')render();}}
  }
  const field=(name,label,type='text',attrs='')=>`<label>${label}<input name="${name}" type="${type}" ${attrs}></label>`;
  const select=(name,label,list,fn,optional=false)=>`<label>${label}<select name="${name}" ${optional?'':'required'}>${optional?'<option value="">Sans affectation</option>':''}${list.map(x=>`<option value="${esc(x.id)}">${esc(fn(x))}</option>`).join('')}</select></label>`;
  const buses=(name='busId',optional=false)=>select(name,'Bus',state.ticketBuses.filter(b=>b.active!==false),b=>b.name+' · '+b.registration,optional);
  const trips=(name='tripId',optional=false)=>select(name,'Voyage',state.ticketTrips,t=>`${t.origin} → ${t.destination} · ${new Date(t.departureAt).toLocaleString('fr-FR')}`,optional);
  const form=(id,title,content,button='Enregistrer')=>`<section class="panel"><h3>${title}</h3><form id="${id}" class="settings-form no-wizard"><div class="grid">${content}</div><button type="submit" class="primary">${button}</button></form></section>`;
  const empty=message=>`<div class="empty">${message}</div>`;
  const dateTime=v=>new Date(v).toLocaleString('fr-FR');
  const safeIso=v=>{const date=new Date(v);if(!Number.isFinite(date.getTime()))throw Error('Date ou heure invalide.');return date.toISOString();};
  function search() {
    const places=[...new Set(state.ticketTrips.flatMap(t=>[t.origin,...String(t.stops||'').split(','),t.destination]).map(s=>String(s||'').trim()).filter(Boolean))];
    const cities=places.map(p=>({id:p,label:p}));
    return form('extSearch','Disponibilités et tarifs du serveur',select('origin','Départ',cities,x=>x.label)+select('destination','Arrivée',cities,x=>x.label)+field('date','Date','date','required'),'Rechercher')+
      `<section class="panel"><h3>Départs disponibles</h3><p>La recherche vérifie les tronçons et les places réservées. Choisir un résultat ouvre la vente ; le siège est ensuite confirmé au guichet.</p>${results?results.trips.map(t=>`<article class="ext-row"><div><b>${esc(t.origin)} → ${esc(t.destination)}</b><small>${esc(dateTime(t.departureAt))} · ${esc(t.bus||'')}</small></div><span class="ext-badge">${t.available} place(s)</span><div class="ext-seat-summary">${['Simple','VIP'].map(cls=>{const seats=t.seats.filter(s=>s.class===cls&&s.available),fare=seats.find(s=>s.fare!==null)?.fare;return `<span>${cls} : ${seats.length}${fare!==undefined?' · '+money(fare):''}</span>`;}).join('')}</div>${can('sales')?`<button data-ext-sell="${esc(t.id)}" data-from="${esc(t.origin)}" data-to="${esc(t.destination)}" ${!t.available?'disabled':''}>Vendre un billet</button>`:''}</article>`).join('')||empty('Aucun départ disponible pour ces critères.'):empty('Choisissez votre trajet et la date.')}</section>`;
  }
  function schedule() {
    return `<div class="admin-grid">${form('extSchedule','Programmer des départs récurrents',trips('templateTripId')+field('start','Première date','date','required')+field('end','Dernière date','date','required')+field('durationMinutes','Durée estimée (minutes)','number','min="15" max="10080" value="240" required')+`<fieldset class="ext-days"><legend>Jours de départ</legend>${['Lun','Mar','Mer','Jeu','Ven','Sam','Dim'].map((d,i)=>`<label><input type="checkbox" name="weekdays" value="${i}">${d}</label>`).join('')}</fieldset>`,'Créer le calendrier')}<section class="panel"><h3>Calendriers enregistrés</h3><p>Les conflits de bus sont contrôlés avant validation de l’ensemble. Pour les anciens départs sans durée, une occupation de quatre heures est retenue.</p>${(data?.schedules||[]).map(s=>`<article class="ext-row"><div><b>${esc(s.start)} → ${esc(s.end)}</b><small>${s.tripIds.length} départ(s) · ${s.durationMinutes} minutes</small></div></article>`).join('')||empty('Aucun calendrier récurrent.')}</section></div>`;
  }
  function stock() {
    const items=data?.stockItems||[],movements=data?.stockMovements||[];
    return `<div class="ext-kpis"><article><small>Références</small><b>${items.length}</b></article><article><small>Au seuil d’alerte</small><b>${items.filter(i=>i.lowStock).length}</b></article><article><small>Mouvements tracés</small><b>${movements.length}</b></article></div><div class="admin-grid">${form('extStockItem','Ajouter une référence',field('sku','Référence','text','required')+field('name','Désignation','text','required')+field('unit','Unité','text','value="pièce" required')+field('minimum','Stock minimal','number','min="0" step="0.001" value="0" required'))}${form('extStockMovement','Entrée ou sortie de stock',select('itemId','Pièce',items,x=>x.sku+' · '+x.name)+select('direction','Mouvement',[{id:'Entrée'},{id:'Sortie'}],x=>x.id)+field('quantity','Quantité','number','min="0.001" step="0.001" required')+field('unitCost','Coût unitaire d’achat (FCFA)','number','min="0" step="0.01" value="0"')+select('paymentMethod','Paiement de l’achat',['Espèces','Mobile Money','Virement','Carte'].map(id=>({id})),x=>x.id)+buses('busId',true)+trips('tripId',true)+field('reason','Motif / référence fournisseur','text','minlength="3" required'))}</div><section class="panel"><div class="panel-head"><div><h3>Stock disponible</h3><p>Une sortie exige un bus et ne peut pas rendre le stock négatif. Les achats sont comptabilisés une fois ; les sorties ne créent pas une seconde dépense.</p></div><button id="extStockCsv">Exporter CSV</button></div>${items.map(i=>`<article class="ext-row"><div><b>${esc(i.sku)} · ${esc(i.name)}</b><small>Seuil : ${i.minimum} ${esc(i.unit)}</small></div><span class="ext-badge ${i.lowStock?'ext-warn':''}">${i.quantity} ${esc(i.unit)}</span></article>`).join('')||empty('Ajoutez votre première pièce.')}</section><section class="panel"><h3>Historique des mouvements</h3>${movements.slice().reverse().map(m=>`<article class="ext-row"><div><b>${esc(m.direction)} · ${esc(m.itemName)}</b><small>${esc(m.reason)} · ${esc(m.createdByName)} · ${esc(dateTime(m.createdAt))}</small></div><span>${m.quantity}</span></article>`).join('')||empty('Aucun mouvement.')}</section>`;
  }
  function charters() {
    const list=data?.charters||[];
    return `<div class="ext-kpis"><article><small>Voyages privés</small><b>${list.length}</b></article><article><small>Encaissé</small><b>${money(list.reduce((a,c)=>a+c.paid,0))}</b></article><article><small>Restant à encaisser</small><b>${money(list.filter(c=>c.status==='Confirmé').reduce((a,c)=>a+c.balance,0))}</b></article></div>${can('dispatch')?form('extCharter','Affréter un bus',field('customerName','Client / organisation','text','required')+field('phone','Téléphone','tel','required')+buses()+field('origin','Lieu de départ','text','required')+field('destination','Destination','text','required')+field('startsAt','Début de mise à disposition','datetime-local','required')+field('endsAt','Fin de mise à disposition','datetime-local','required')+field('amount','Prix convenu (FCFA)','number','min="1" required')+field('deposit','Acompte encaissé (FCFA)','number','min="0" value="0" required')+select('paymentMethod','Paiement',['Espèces','Mobile Money','Virement','Carte'].map(id=>({id})),x=>x.id),'Confirmer le voyage privé'):''}<section class="panel"><h3>Dossiers d’affrètement</h3><p>Les créneaux sont contrôlés avec les départs réguliers et les autres affrètements. Les règlements sont saisis après encaissement effectif.</p>${list.slice().reverse().map(c=>`<article class="ext-row"><div><b>${esc(c.customerName)} · ${esc(c.origin)} → ${esc(c.destination)}</b><small>${esc(dateTime(c.startsAt))} — ${esc(dateTime(c.endsAt))}</small><small>${esc(c.status)} · ${esc(c.phone)} · réf. ${esc(c.id)}</small></div><div><b>${money(c.amount)}</b><small>Payé ${money(c.paid)} · solde ${money(c.balance)}</small></div><div class="button-row"><button data-ext-charter-receipt="${esc(c.id)}">Reçu PDF</button>${c.status==='Confirmé'&&c.balance&&(can('sales')||can('reports'))?`<button data-ext-charter-pay="${esc(c.id)}">Encaisser un règlement</button>`:''}${c.status==='Confirmé'&&can('manager')?`<button data-ext-charter-status="${esc(c.id)}" data-status="${c.paid?'Terminé':'Annulé'}">${c.paid?'Terminer':'Annuler'}</button>`:''}</div></article>`).join('')||empty('Aucun voyage privé.')}</section><div id="extDialog"></div>`;
  }
  function parking() {
    const slots=data?.parkingSlots||[],deposits=data?.parking||[];
    return `<div class="admin-grid">${can('manager')?form('extSlot','Configurer un emplacement',field('label','Emplacement','text','required')+select('vehicleType','Type',['Moto','Voiture'].map(id=>({id})),x=>x.id)+field('rate','Tarif (FCFA)','number','min="0" required')+select('pricing','Facturation',[{id:'jour',label:'Par jour commencé'},{id:'forfait',label:'Forfait'}],x=>x.label)):''}${can('sales')?form('extParking','Consigner un véhicule',select('slotId','Emplacement disponible',slots.filter(s=>s.active&&!deposits.some(p=>p.slotId===s.id&&p.status==='Déposé')),s=>`${s.label} · ${s.vehicleType} · ${money(s.rate)} / ${s.pricing}`)+field('registration','Immatriculation','text','required')+field('customerName','Déposant','text','required')+field('phone','Téléphone','tel','required')+field('condition','État à l’entrée','text','required'),'Confirmer le dépôt'):''}</div><section class="panel"><h3>Occupation du parking</h3><p>Les tarifs sont repris de l’emplacement sur le serveur. Les restitutions restent accessibles dans Pilotage & services → Parking.</p><div class="ext-slots">${slots.map(s=>{const p=deposits.find(p=>p.slotId===s.id&&p.status==='Déposé');return `<article class="${p?'occupied':''}"><b>${esc(s.label)}</b><span>${esc(s.vehicleType)}</span><small>${money(s.rate)} / ${esc(s.pricing)}</small><strong>${p?esc(p.registration):'Libre'}</strong></article>`;}).join('')||empty('Configurez les emplacements du parking.')}</div></section><section class="panel"><h3>Dépôts et reçus</h3>${deposits.slice().reverse().map(p=>`<article class="ext-row"><div><b>${esc(p.registration)} · ${esc(p.customerName)}</b><small>${esc(p.slotLabel||'Sans emplacement')} · ${esc(p.status)} · ${esc(dateTime(p.depositedAt))}</small></div><button data-ext-parking-receipt="${esc(p.id)}">Reçu PDF</button></article>`).join('')||empty('Aucun dépôt.')}</section>`;
  }
  function messages() {
    const jobs=data?.outbox||[];
    return `${can('manager')?form('extPreferences','Notifications voyageurs',`<label class="switch-line"><input name="stageNotifications" type="checkbox" ${data?.preferences?.stageNotifications?'checked':''}>Préparer les SMS / WhatsApp à chaque étape publiée par l’équipage</label>`):''}<section class="panel"><div class="panel-head"><div><h3>Messages par étape</h3><p>Les canaux de la société doivent être configurés. Chaque événement prépare un message par téléphone et canal. Le bouton traite dix messages ; un résultat incertain reste à vérifier pour éviter un double envoi.</p></div><button id="extDispatch">Envoyer les messages en attente</button></div>${jobs.slice().reverse().map(j=>`<article class="ext-row"><div><b>${esc(j.channel)} · ${esc(j.to)}</b><small>${esc(j.message)}</small>${j.detail?`<small>${esc(j.detail)}</small>`:''}</div><span class="ext-badge ${j.status==='À vérifier'?'ext-warn':''}">${esc(j.status)}</span></article>`).join('')||empty('Aucun message préparé.')}</section>`;
  }
  function backup() {
    return `<section class="panel"><h3>Export complet des données métier</h3><p>Billets, réservations, courrier, bagages, clients, identité, carnets, parking, stock, affrètements et historiques de la société sont inclus. Ce fichier contient des données clients : conservez-le dans un espace réservé aux responsables.</p><p>Les mots de passe et clés fournisseurs sont exclus. Cet export serveur complète la sauvegarde PostgreSQL ; il ne s’importe pas dans l’ancien bouton de restauration locale.</p><button id="extBackup" class="primary">Télécharger l’export société</button></section>`;
  }
  function panel() {
    const key=state.company?.id+':'+state.user?.id;
    if(owner!==key){owner=key;generation++;data=null;loading=false;results=null;tab=tabs()[0]?.[0]||'search';}
    if(!tabs().some(([id])=>id===tab))tab=tabs()[0]?.[0]||'search';
    const content=data?.error?`<section class="panel">${esc(data.error)} <button id="extRetry">Réessayer</button></section>`:data?({search,schedule,stock,charters,parking,messages,backup})[tab]():empty('Chargement des services…');
    return shell(`<section class="panel transport-hero"><div><span class="eyebrow">SERVICES AVANCÉS</span><h2>Planifier, exploiter et suivre</h2><p>Départs, stock, affrètements et services de gare.</p></div><button id="extRefresh">Actualiser</button></section><nav class="ops-tabs">${tabs().map(([id,label])=>`<button data-ext-tab="${id}" class="${tab===id?'primary':''}">${label}</button>`).join('')}</nav>${content}`);
  }
  function handler(id, action) {
    const form=document.getElementById(id);if(!form)return;
    form.onsubmit=async e=>{
      e.preventDefault();const button=form.querySelector('[type=submit]');if(button.disabled)return;
      button.disabled=true;const fd=new FormData(form),d=Object.fromEntries(fd);
      d.id=form.dataset.operationId||(form.dataset.operationId=uid());
      try {await action(d,fd);delete form.dataset.operationId;if(!['extSearch','extPreferences'].includes(id))form.reset();await ctx.sync();await load();notify('Opération enregistrée.','success');}
      catch(error){notify(error.message,'error',9000);}
      finally {if(button.isConnected)button.disabled=false;}
    };
  }
  async function csv(filename, rows) {
    const text=rows.map(row=>row.map(value=>{let s=String(value??'');if(/^[=+@-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';}).join(';')).join('\r\n');
    await ctx.saveBlob(new Blob(['\ufeff'+text],{type:'text/csv;charset=utf-8'}),filename);
  }
  async function receipt(title,reference,rows) {
    const doc=new jsPDF();doc.setFillColor(7,95,78);doc.rect(0,0,210,40,'F');doc.setTextColor(255,255,255);doc.setFontSize(20);doc.text(String(state.company.name).slice(0,65),15,18);doc.setFontSize(12);doc.text(title,15,29);doc.setTextColor(25,40,45);doc.setFontSize(10);let y=54;
    for(const [label,value] of [['Référence',reference],...rows]){const lines=doc.splitTextToSize(String(value??'').replace(/[\u202f\u00a0]/g,' '),120);if(y+lines.length*5>275){doc.addPage();y=20;}doc.setFont('helvetica','bold');doc.text(label,15,y);doc.setFont('helvetica','normal');doc.text(lines,72,y);y+=Math.max(10,lines.length*5+4);}
    await ctx.saveBlob(doc.output('blob'),reference.replace(/[^a-z0-9-]/gi,'-')+'.pdf');
  }
  function bind() {
    if(state.page!=='ticketExtensions'){generation++;owner='';data=null;loading=false;return;}
    if(!data&&!loading)load();
    document.querySelectorAll('[data-ext-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.extTab;render();});
    for(const id of ['extRefresh','extRetry'])document.getElementById(id)?.addEventListener('click',()=>load());
    handler('extSearch',async d=>{results=await api('/search?'+new URLSearchParams({origin:d.origin,destination:d.destination,date:d.date}));});
    handler('extStockItem',d=>api('/stock/items',{...d,minimum:Number(d.minimum)}));
    handler('extStockMovement',d=>api('/stock/movements',{...d,quantity:Number(d.quantity),unitCost:Number(d.unitCost)}));
    handler('extSchedule',async(d,fd)=>{await ctx.sync();await api('/schedules',{...d,weekdays:fd.getAll('weekdays').map(Number),durationMinutes:Number(d.durationMinutes)});});
    handler('extCharter',d=>api('/charters',{...d,startsAt:safeIso(d.startsAt),endsAt:safeIso(d.endsAt),amount:Number(d.amount),deposit:Number(d.deposit)}));
    handler('extSlot',d=>api('/parking/slots',{...d,rate:Number(d.rate),active:true}));
    handler('extParking',async d=>{const slot=data.parkingSlots.find(s=>s.id===d.slotId);if(!slot)throw Error('Choisissez un emplacement.');await ctx.operationsApi('/parking',{...d,vehicleType:slot.vehicleType,rate:slot.rate,pricing:slot.pricing});});
    handler('extPreferences',(d,fd)=>api('/preferences',{stageNotifications:fd.has('stageNotifications')},'PUT'));
    document.querySelectorAll('[data-ext-sell]').forEach(b=>b.onclick=()=>{
      if(b.dataset.from!==state.ticketTrips.find(t=>t.id===b.dataset.extSell)?.origin){notify('Ce résultat part d’une escale. Le guichet actuel vend au départ de la ligne ; utilisez la réservation de tronçon via le responsable.','warning',9000);return;}
      ctx.navigate('ticketSale');const trip=document.querySelector('#saleTrip');trip.value=b.dataset.extSell;trip.dispatchEvent(new Event('change'));const drop=document.querySelector('#saleDropPoint');if(drop){drop.value=b.dataset.to;drop.dispatchEvent(new Event('change'));}
    });
    document.querySelector('#extStockCsv')?.addEventListener('click',()=>csv('yamtrans-stock.csv',[['Référence','Désignation','Quantité','Unité','Minimum','Alerte'],...(data.stockItems||[]).map(i=>[i.sku,i.name,i.quantity,i.unit,i.minimum,i.lowStock?'Oui':'Non'])]));
    document.querySelectorAll('[data-ext-charter-receipt]').forEach(b=>b.onclick=()=>{const c=data.charters.find(c=>c.id===b.dataset.extCharterReceipt);receipt('VOYAGE PRIVÉ · RELEVÉ DES RÈGLEMENTS',c.id,[['Client',c.customerName],['Téléphone',c.phone],['Départ',c.origin],['Destination',c.destination],['Début',dateTime(c.startsAt)],['Fin',dateTime(c.endsAt)],['Montant convenu',money(c.amount)],['Payé',money(c.paid)],['Solde',money(c.balance)],['Statut',c.status]]);});
    document.querySelectorAll('[data-ext-parking-receipt]').forEach(b=>b.onclick=()=>{const p=data.parking.find(p=>p.id===b.dataset.extParkingReceipt);receipt('CONSIGNATION · REÇU',p.id,[['Déposant',p.customerName],['Téléphone',p.phone],['Véhicule',p.vehicleType+' · '+p.registration],['Emplacement',p.slotLabel||'—'],['Dépôt',dateTime(p.depositedAt)],['État à l’entrée',p.condition],['Tarif',money(p.rate)+' / '+p.pricing],['Statut',p.status],['Montant réglé',money(p.paid||0)],['État à la sortie',p.releaseCondition||'Non restitué']]);});
    document.querySelectorAll('[data-ext-charter-pay]').forEach(b=>b.onclick=()=>{
      const charter=data.charters.find(c=>c.id===b.dataset.extCharterPay),host=document.querySelector('#extDialog');
      host.innerHTML=`<div class="modal-backdrop"><div class="modal"><button id="extCloseDialog">Fermer</button>${form('extCharterPayment','Enregistrer un règlement',field('amount','Montant réellement encaissé','number',`min="1" max="${charter.balance}" required`)+select('paymentMethod','Paiement',['Espèces','Mobile Money','Virement','Carte'].map(id=>({id})),x=>x.id))}</div></div>`;
      host.querySelector('#extCloseDialog').onclick=()=>host.replaceChildren();handler('extCharterPayment',d=>api('/charters/'+encodeURIComponent(charter.id)+'/payments',{...d,amount:Number(d.amount)}));
    });
    document.querySelectorAll('[data-ext-charter-status]').forEach(b=>b.onclick=async()=>{if(!confirm('Confirmer ce changement de statut ?'))return;try{await api('/charters/'+encodeURIComponent(b.dataset.extCharterStatus)+'/status',{status:b.dataset.status});await load();}catch(e){notify(e.message,'error');}});
    document.querySelector('#extDispatch')?.addEventListener('click',async e=>{const b=e.currentTarget;b.disabled=true;try{const result=await api('/notifications/dispatch',{});notify(result.processed+' message(s) traité(s).','info');await load();}catch(e){notify(e.message,'error');}finally{if(b.isConnected)b.disabled=false;}});
    document.querySelector('#extBackup')?.addEventListener('click',async e=>{const b=e.currentTarget;b.disabled=true;try{const value=await api('/backup');await ctx.saveBlob(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),'yamtrans-societe-'+new Date().toISOString().slice(0,10)+'.json');}catch(e){notify(e.message,'error');}finally{if(b.isConnected)b.disabled=false;}});
  }
  return {panel,bind};
}
