import { allocationActive, isoLocal, segmentFare } from './transport-model.js';
import './transport.css';

export function createTransportUi(ctx) {
  const {state, esc, money, uid, now, persist, render, shell, notify, ticketRole, navigatePage} = ctx;
  let selectedTrip='', tenant='', serverData=null, hold=null, holding=false;
  const replace=(key,item)=>{const i=state[key].findIndex(x=>x.id===item.id);if(i<0)state[key].push(item);else state[key][i]=item;};
  async function api(path,body,method='POST') {
    if (!navigator.onLine || !state.authToken) throw new Error('Connexion au serveur requise pour cette opération');
    const company=state.company?.id;
    const r=await fetch(ctx.serverUrl()+'/api/v2/transport'+path,{method,headers:{'Content-Type':'application/json',Authorization:'Bearer '+state.authToken},...(body!==undefined?{body:JSON.stringify(body)}:{})});
    if(company!==state.company?.id)throw new Error('La société active a changé');
    const data=await r.json().catch(()=>({detail:'Réponse serveur invalide'}));
    if(!r.ok){const error=new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail||data));error.status=r.status;throw error;}
    return data;
  }
  async function synced() {
    if(!await ctx.sync())throw new Error('Synchronisez YamTrans avec le serveur avant cette opération');
    if(state.syncStatus==='conflict')throw new Error('Résolvez les conflits de synchronisation avant cette opération');
  }
  async function load() {
    serverData=null;
    if(selectedTrip && ticketRole('dispatch'))serverData=await api('/trips/'+encodeURIComponent(selectedTrip)+'/overview',undefined,'GET');
    if(ticketRole('sales')) {
      const data=await api('/state',undefined,'GET');
      state.transportHolds=data.holds;state.transportWaitlist=data.waitlist;
    }
    render();
  }
  function panel() {
    if(tenant!==state.company?.id){tenant=state.company?.id;selectedTrip='';serverData=null;hold=null;state.transportWaitlist=[];state.transportHolds=[];}
    const tr=state.ticketTrips.find(t=>t.id===selectedTrip),data=serverData?.trip?.id===selectedTrip?serverData:null;
    const reservations=state.ticketReservations.filter(r=>(!selectedTrip||r.tripId===selectedTrip)&&!['Convertie','Annulée'].includes(r.status));
    const waitlist=(state.transportWaitlist||[]).filter(r=>r.status==='En attente'&&(!selectedTrip||r.tripId===selectedTrip)).sort((a,b)=>String(a.createdAt).localeCompare(String(b.createdAt)));
    const tripOptions=state.ticketTrips.slice().sort((a,b)=>String(b.departureAt).localeCompare(String(a.departureAt))).map(t=>`<option value="${esc(t.id)}" ${t.id===selectedTrip?'selected':''}>${esc(t.origin)} → ${esc(t.destination)} · ${esc(new Date(t.departureAt).toLocaleString('fr-FR'))}</option>`).join('');
    return shell(`<section class="panel transport-hero"><div><span class="eyebrow">EXPLOITATION TRANSPORT</span><h2>Un départ, toute l’opération</h2><p>Réservations, passagers, bagages et caisse restent reliés au même voyage.</p></div><div class="button-row">${ticketRole('sales')?'<button id="transportGroup">Groupe / aller-retour</button>':''}<button id="transportRefresh">Actualiser le serveur</button></div></section>
    <section class="panel"><label>Voyage<select id="transportTrip"><option value="">Choisir un départ</option>${tripOptions}</select></label><p class="muted">Les données locales restent consultables hors connexion. Les validations communes aux guichets nécessitent le serveur.</p></section>
    ${data?`<section class="metric-grid"><article><div><small>Passagers embarqués</small><b>${data.boarded}/${data.tickets.length}</b></div></article><article><div><small>Bagages + colis</small><b>${data.baggageCount}</b></div></article><article><div><small>Poids enregistré</small><b>${data.weightKg.toFixed(1)} kg</b></div></article><article><div><small>Points à contrôler</small><b>${data.warnings.length}</b></div></article>${data.net!==undefined?`<article><div><small>Net du départ</small><b>${money(data.net)}</b></div></article>`:''}</section>
    <section class="panel"><div class="panel-head"><div><h3>Contrôle avant départ</h3><p>Passagers embarqués, bagages enregistrés et capacité déclarée de la soute.</p></div><button id="transportExport">Exporter le contrôle CSV</button></div>${data.warnings.length?`<div class="transport-alerts">${data.warnings.map(w=>`<div><b>${esc(w.code||'Soute')}</b><span>${esc(w.message)}</span></div>`).join('')}</div>`:'<p class="transport-good">Aucune anomalie détectée sur les données synchronisées.</p>'}<p class="muted">Capacité : ${Number(tr?.cargoCapacityKg||0)?esc(tr.cargoCapacityKg)+' kg':'poids non renseigné'} · ${Number(tr?.cargoCapacityCount||0)?esc(tr.cargoCapacityCount)+' pièces':'nombre non renseigné'}</p></section>`:''}
    <div class="admin-grid transport-grid">${ticketRole('sales')?`<section class="panel"><h3>Réservations à traiter</h3><p>Un acompte est repris dans le billet lors de la conversion. L’expiration libère le siège.</p><div class="compact-list">${reservations.map(r=>`<div><b>${esc(r.code||r.id)} · ${esc(r.passengerName)}</b><span>Siège ${esc(r.seat)} · ${money(r.deposit||0)} versés · ${allocationActive(r)?'Active':'Expirée'}</span>${r.expiresAt?`<small>Limite : ${esc(new Date(r.expiresAt).toLocaleString('fr-FR'))}</small>`:''}<div class="button-row">${allocationActive(r)?`<button data-convert-reservation="${esc(r.id)}">Émettre le billet</button>`:''}${!Number(r.deposit||0)?`<button data-cancel-reservation="${esc(r.id)}">Annuler</button>`:''}</div></div>`).join('')||'<div class="empty">Aucune réservation à traiter.</div>'}</div><button data-page="ticketReservations">Nouvelle réservation</button></section>
    <section class="panel"><h3>Liste d’attente</h3><p>Ordre d’inscription conservé. Vérifiez les disponibilités avant d’émettre un billet.</p><form id="transportWaitForm" class="settings-form no-wizard"><div class="grid"><label>Passager<input name="passengerName" required></label><label>Téléphone<input name="phone" required></label><label>Classe<select name="seatClass"><option>Simple</option><option>VIP</option></select></label></div><button class="primary" ${tr?'':'disabled'}>Inscrire sur ce départ</button></form><div class="compact-list">${waitlist.map((w,i)=>`<div><b>${i+1}. ${esc(w.passengerName)}</b><span>${esc(w.phone)} · ${esc(w.seatClass)}</span><div class="button-row"><button data-sell-wait="${esc(w.id)}">Préparer la vente</button><button data-close-wait="${esc(w.id)}">Marquer traitée</button></div></div>`).join('')||'<p>Aucune personne en attente.</p>'}</div></section>`:''}
    ${tr&&ticketRole('dispatch')?`<section class="panel"><h3>Remplacer le bus</h3><p>Les numéros et classes des sièges occupés doivent exister dans le nouveau bus. Les billets et bagages conservent leur voyage.</p><form id="transportBusForm" class="settings-form no-wizard"><label>Nouveau bus<select name="busId" required>${state.ticketBuses.filter(b=>b.id!==tr.busId&&b.active!==false).map(b=>`<option value="${esc(b.id)}">${esc(b.name)} · ${esc(b.registration)}</option>`).join('')}</select></label><label>Motif<input name="reason" minlength="3" required></label><button class="primary">Contrôler et remplacer</button></form></section>
    <section class="panel"><h3>Programmer plusieurs départs</h3><p>Reprend la ligne, le bus, les tarifs et l’heure de ce voyage. Chaque date crée un départ indépendant.</p><form id="transportRepeatForm" class="settings-form no-wizard"><label>Dates séparées par des virgules<textarea name="dates" required placeholder="2026-11-02, 2026-11-04, 2026-11-06"></textarea></label><button class="primary">Créer les départs</button></form></section>
    <section class="panel"><h3>Rattacher un bordereau Courrier</h3><p>Relie les colis et leurs recettes au même départ que les passagers et bagages. Le bordereau conserve ses scans et son historique.</p><form id="transportManifestForm" class="settings-form no-wizard"><label>Bordereau<select name="manifestId" required><option value="">Choisir un bordereau</option>${state.manifests.filter(m=>!m.tripId||m.tripId===selectedTrip).map(m=>`<option value="${esc(m.id)}">${esc(m.code)} · ${esc(m.origin)} → ${esc(m.destination)}</option>`).join('')}</select></label><button class="primary">Rattacher au départ</button></form></section>
    <section class="panel"><h3>Capacité de soute</h3><form id="transportCapacityForm" class="settings-form no-wizard"><div class="grid"><label>Poids maximal en kg<input name="cargoCapacityKg" type="number" min="0" step="0.1" value="${Number(tr.cargoCapacityKg||0)}"></label><label>Nombre maximal de pièces<input name="cargoCapacityCount" type="number" min="0" step="1" value="${Number(tr.cargoCapacityCount||0)}"></label></div><small>0 signifie qu’aucune limite n’est renseignée.</small><button class="primary">Enregistrer les limites</button></form></section>`:''}
    ${tr&&ticketRole('reports')?`<section class="panel"><h3>Dépenses du départ</h3><form id="transportExpenseForm" class="settings-form no-wizard"><div class="grid"><label>Montant<input type="number" name="amount" min="1" required></label><label>Paiement<select name="paymentMethod"><option>Espèces</option><option>Mobile Money</option><option>Virement</option></select></label></div><label>Motif<input name="reason" minlength="3" required></label><button class="primary">Enregistrer la dépense</button></form></section>
    <section class="panel"><h3>Clôture du départ</h3>${data?.expectedCash!==undefined?`<div class="transport-financial"><span>Billets encaissés <b>${money(data.ticketIncome)}</b></span><span>Bagages encaissés <b>${money(data.baggageIncome)}</b></span><span>Courrier encaissé <b>${money(data.courierIncome||0)}</b></span><span>Acomptes non convertis <b>${money(data.depositIncome||0)}</b></span><span>Remboursements <b>${money(data.refunds)}</b></span><span>Dépenses <b>${money(data.expenses)}</b></span><span>Espèces attendues <b>${money(data.expectedCash)}</b></span></div>`:'<p>Actualisez les données serveur avant de clôturer.</p>'}${data?.closures?.length?`<div class="transport-good">Clôture enregistrée le ${esc(new Date(data.closures[0].createdAt).toLocaleString('fr-FR'))} · espèces comptées : ${money(data.closures[0].countedCash)} · écart : ${money(data.closures[0].difference)}</div>`:''}<form id="transportClosureForm" class="settings-form no-wizard"><label>Espèces réellement comptées<input name="countedCash" type="number" min="0" required></label><label>Observation<textarea name="note"></textarea></label><button class="primary" ${data?.closures?.length?'disabled':''}>Enregistrer la clôture</button></form><small>Le relevé conserve les montants au moment de la clôture. Il ne bloque pas les opérations futures.</small></section>`:''}</div><div id="ticketModal"></div>`);
  }
  async function run(button, action) {
    if(button?.disabled)return;
    if(button)button.disabled=true;
    try {await action();persist();notify('Opération enregistrée.','success');}
    catch(e){notify(e.message,'error',6500);}
    finally {if(button?.isConnected)button.disabled=false;}
  }
  const form=(selector,action)=>{
    const el=document.querySelector(selector);
    if(el)el.onsubmit=e=>{e.preventDefault();run(el.querySelector('button[type="submit"],button:not([type])'),async()=>{await synced();await action(Object.fromEntries(new FormData(el)));await load();});};
  };
  function bind() {
    document.querySelector('#transportGroup')?.addEventListener('click',openGroup);
    document.querySelector('#transportTrip')?.addEventListener('change',e=>{selectedTrip=e.target.value;serverData=null;render();load().catch(e=>notify(e.message,'warning',6000));});
    document.querySelector('#transportRefresh')?.addEventListener('click',e=>run(e.currentTarget,async()=>{await synced();await load();}));
    form('#transportWaitForm',async d=>{await api('/waitlist',{...d,phone:ctx.normalizePhone(d.phone),tripId:selectedTrip});});
    form('#transportBusForm',async d=>{const r=await api('/trips/'+selectedTrip+'/bus',d);replace('ticketTrips',r.trip);r.tickets.forEach(t=>replace('tickets',t));});
    form('#transportRepeatForm',async d=>{const dates=d.dates.split(/[,;\s]+/).filter(Boolean);if(dates.length>60)throw new Error('60 dates au maximum');const r=await api('/trips/'+selectedTrip+'/repeat',{dates});r.trips.forEach(t=>replace('ticketTrips',t));});
    form('#transportManifestForm',async d=>{const r=await api('/trips/'+selectedTrip+'/manifests',d);replace('manifests',r.manifest);r.shipments.forEach(sh=>replace('shipments',sh));});
    form('#transportCapacityForm',async d=>replace('ticketTrips',await api('/trips/'+selectedTrip+'/capacity',{cargoCapacityKg:Number(d.cargoCapacityKg),cargoCapacityCount:Number(d.cargoCapacityCount)},'PUT')));
    form('#transportExpenseForm',async d=>replace('expenses',await api('/trips/'+selectedTrip+'/expenses',{...d,amount:Number(d.amount)})));
    form('#transportClosureForm',async d=>{const r=await api('/trips/'+selectedTrip+'/closure',{...d,countedCash:Number(d.countedCash)});notify('Clôture enregistrée · écart : '+money(r.difference),r.difference?'warning':'success',8000);});
    document.querySelectorAll('[data-cancel-reservation]').forEach(b=>b.onclick=()=>run(b,async()=>{replace('ticketReservations',await api('/reservations/'+b.dataset.cancelReservation+'/cancel',{}));render();}));
    document.querySelectorAll('[data-convert-reservation]').forEach(b=>b.onclick=()=>convert(b.dataset.convertReservation));
    document.querySelectorAll('[data-close-wait]').forEach(b=>b.onclick=()=>run(b,async()=>{await api('/waitlist/'+b.dataset.closeWait+'/close',{});await load();}));
    document.querySelectorAll('[data-sell-wait]').forEach(b=>b.onclick=()=>{const w=state.transportWaitlist.find(r=>r.id===b.dataset.sellWait);navigatePage('ticketSale');const tr=document.querySelector('#saleTrip');tr.value=w.tripId;tr.dispatchEvent(new Event('change'));document.querySelector('#ticketPassengerName').value=w.passengerName;document.querySelector('#ticketCustomerPhone').value=w.phone;});
    document.querySelector('#transportExport')?.addEventListener('click',()=>{
      const rows=[['PNR','Passager','Siège','Embarqué','Bagages'],...serverData.tickets.map(t=>[t.pnr,t.passengerName,t.seat,t.boarded?'Oui':'Non',serverData.baggage.filter(b=>b.ticketId===t.id).map(b=>b.code).join(', ')])];
      const csv=rows.map(r=>r.map(x=>`"${String(x??'').replaceAll('"','""')}"`).join(';')).join('\r\n');ctx.saveBlob(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}),'controle-depart.csv');
    });
    // Add an entry point to each ticket action dialog without removing print/PDF.

    const reservation=document.querySelector('#ticketReservationForm');
    if(reservation){
      reservation.classList.add('no-wizard');
      const updateReservationFare=()=>{const tr=state.ticketTrips.find(t=>t.id===reservation.elements.tripId.value),bus=state.ticketBuses.find(b=>b.id===tr?.busId),seat=ctx.busSeats(bus||{}).find(s=>String(s.label)===reservation.elements.seat.value.trim());reservation.elements.amount.readOnly=true;reservation.elements.amount.value=tr&&seat?segmentFare(state.ticketRoutes.find(r=>r.id===tr.routeId),tr,tr.origin,tr.destination,seat.class):''};
      reservation.elements.tripId.addEventListener('change',updateReservationFare);reservation.elements.seat.addEventListener('input',updateReservationFare);updateReservationFare();
      if(!reservation.elements.expiresAt)reservation.querySelector('.grid')?.insertAdjacentHTML('beforeend','<label>Expiration de la réservation<input type="datetime-local" name="expiresAt" required></label>');
      reservation.onsubmit=e=>{e.preventDefault();run(reservation.querySelector('button'),async()=>{
        await synced();const d=Object.fromEntries(new FormData(reservation)),tr=state.ticketTrips.find(t=>t.id===d.tripId);
        if(!tr)throw new Error('Choisissez un voyage');
        const r=await api('/reservations',{...d,id:uid(),phone:ctx.normalizePhone(d.phone),amount:Number(d.amount),deposit:Number(d.deposit||0),boardingPoint:tr.origin,dropPoint:tr.destination,expiresAt:isoLocal(d.expiresAt)});
        replace('ticketReservations',r);persist();render();
      });};
      reservation.insertAdjacentHTML('afterend','<p><button type="button" data-transport-reservations>Convertir ou annuler une réservation</button></p>');
      reservation.parentElement.querySelector('[data-transport-reservations]').onclick=()=>navigatePage('ticketOperations');
    }
  }
  function openGroup() {
    const tr=state.ticketTrips.find(t=>t.id===selectedTrip),host=document.querySelector('#ticketModal');
    if(!tr||!host)return notify('Choisissez le départ aller.','warning');
    const returns=state.ticketTrips.filter(t=>t.id!==tr.id&&t.origin===tr.destination&&t.destination===tr.origin&&new Date(t.departureAt)>new Date(tr.departureAt));
    host.innerHTML=`<div class="modal-backdrop"><form id="transportGroupForm" class="modal wide-modal settings-form no-wizard"><div class="modal-head"><div><h3>Groupe / aller-retour</h3><p>${esc(tr.origin)} → ${esc(tr.destination)}</p></div><button type="button" id="closeTransportGroup">×</button></div><label>Retour facultatif<select name="returnTrip"><option value="">Aller simple</option>${returns.map(r=>`<option value="${esc(r.id)}">${esc(new Date(r.departureAt).toLocaleString('fr-FR'))} · ${esc(r.origin)} → ${esc(r.destination)}</option>`).join('')}</select></label><p>Chaque personne a son billet et son siège. Tous les billets sont validés ensemble, ou aucun ne l’est.</p><div id="groupTravelers"></div><button type="button" id="addGroupTraveler">Ajouter un passager</button><label>Mode de paiement<select name="paymentMethod"><option>Espèces</option><option>Mobile Money</option><option>Carte</option><option>Virement</option></select></label><p id="groupTotal" class="transport-good"></p><p>Le montant total doit avoir été encaissé avant validation. Cette action enregistre le règlement.</p><button class="primary" type="submit">Valider tous les billets</button></form></div>`;
    const f=host.querySelector('form'),travelers=f.querySelector('#groupTravelers');
    const seats=trip=>ctx.busSeats(state.ticketBuses.find(b=>b.id===trip?.busId));
    const opts=trip=>'<option value="">Choisir un siège</option>'+seats(trip).map(s=>`<option value="${esc(s.label)}">${esc(s.label)} · ${esc(s.class)}</option>`).join('');
    const ret=()=>state.ticketTrips.find(t=>t.id===f.elements.returnTrip.value);
    const total=()=>{
      let amount=0,count=0;
      for(const row of travelers.children)for(const [field,trip] of [['outSeat',tr],['backSeat',ret()]]){
        if(!trip)continue;const seat=seats(trip).find(s=>String(s.label)===row.querySelector('[name="'+field+'"]').value);
        if(seat){amount+=Number(seat.class==='VIP'?trip.fareVip||0:trip.fareSimple||0);count++;}
      }
      f.querySelector('#groupTotal').textContent=count+' billet(s) · total à encaisser : '+money(amount);
    };
    function add(){
      if(travelers.children.length>=10)return notify('10 passagers au maximum par commande.','warning');
      const row=document.createElement('div');row.className='group-traveler grid';
      row.innerHTML=`<label>Passager<input name="passengerName" required></label><label>Téléphone<input name="phone" required></label><label>Siège aller<select name="outSeat" required>${opts(tr)}</select></label><label>Siège retour<select name="backSeat" ${ret()?'required':'disabled'}>${opts(ret())}</select></label><button type="button" class="remove-traveler">Retirer ce passager</button>`;
      row.querySelector('button').onclick=()=>{if(travelers.children.length>1){row.remove();total();}};
      row.onchange=total;travelers.appendChild(row);total();
    }
    f.elements.returnTrip.onchange=()=>{for(const row of travelers.children){const sel=row.querySelector('[name="backSeat"]');sel.innerHTML=opts(ret());sel.disabled=!ret();sel.required=!!ret();}total();};
    f.querySelector('#addGroupTraveler').onclick=add;add();
    f.querySelector('#closeTransportGroup').onclick=()=>host.innerHTML='';
    f.onsubmit=e=>{e.preventDefault();run(f.querySelector('button.primary'),async()=>{
      await synced();const items=[];
      for(const row of travelers.children){
        const passengerName=row.querySelector('[name="passengerName"]').value.trim(),phone=ctx.normalizePhone(row.querySelector('[name="phone"]').value);
        for(const [field,trip] of [['outSeat',tr],['backSeat',ret()]]){
          if(!trip)continue;
          const seat=seats(trip).find(s=>String(s.label)===row.querySelector('[name="'+field+'"]').value);
          if(!seat)throw new Error('Choisissez tous les sièges');
          const fare=Number(seat.class==='VIP'?trip.fareVip||0:trip.fareSimple||0);
          items.push({id:uid(),pnr:ctx.pnr(),publicToken:uid(),tripId:trip.id,passengerName,phone,seat:seat.label,seatClass:seat.class,boardingPoint:trip.origin,dropPoint:trip.destination,fare,paid:fare,discount:0,paymentMethod:f.elements.paymentMethod.value});
        }
      }
      const result=await api('/bookings/confirm',{bookingId:uid(),tickets:items});
      result.tickets.forEach(t=>replace('tickets',t));persist();
      host.innerHTML=`<div class="modal-backdrop"><div class="modal"><div class="modal-head"><h3>${result.tickets.length} billet(s) émis</h3><button id="closeGroupResult">×</button></div><div class="compact-list">${result.tickets.map(t=>`<div><b>${esc(t.passengerName)} · ${esc(t.pnr)}</b><span>${esc(t.origin)} → ${esc(t.destination)} · siège ${esc(t.seat)}</span><button data-group-ticket="${esc(t.id)}">Ouvrir / imprimer</button></div>`).join('')}</div></div></div>`;
      host.querySelector('#closeGroupResult').onclick=()=>{host.innerHTML='';render();};
      host.querySelectorAll('[data-group-ticket]').forEach(b=>b.onclick=()=>ctx.openTicket(b.dataset.groupTicket));
    });};
  }
  function enhanceTicket(id) {
    const t=state.tickets.find(t=>t.id===id),host=document.querySelector('#ticketModal')||document.querySelector('#fullMenuHost'),actions=host?.querySelector('.modal-actions');
    if(!t||!actions||!allocationActive(t)||t.boarded||!ticketRole('manager'))return;
    if(actions.querySelector('[data-refund-ticket]'))return;const b=document.createElement('button');b.dataset.refundTicket=id;b.textContent='Annuler / rembourser';actions.appendChild(b);
    b.onclick=()=>{
      const modal=host.querySelector('.modal');
      if(modal.querySelector('#transportRefundForm'))return;
      modal.insertAdjacentHTML('beforeend',`<form id="transportRefundForm" class="settings-form no-wizard"><h4>Annulation et remboursement</h4><label>Montant à rembourser<input name="amount" type="number" min="0" max="${Number(t.paid||0)}" value="${Number(t.paid||0)}" required></label><label>Motif<input name="reason" minlength="3" required></label><small>Le billet sera invalidé et son siège libéré. Le montant initial reste dans l’historique.</small><button class="primary">Valider le remboursement</button></form>`);
      const f=modal.querySelector('#transportRefundForm');f.onsubmit=e=>{e.preventDefault();run(f.querySelector('button'),async()=>{await synced();const d=Object.fromEntries(new FormData(f));const r=await api('/tickets/'+id+'/refund',{amount:Number(d.amount),reason:d.reason});replace('tickets',r.ticket);replace('ticketRefunds',r.refund);persist();render();});};
    };
  }
  function convert(id) {
    const r=state.ticketReservations.find(r=>r.id===id),tr=state.ticketTrips.find(t=>t.id===r?.tripId),host=document.querySelector('#ticketModal');
    if(!r||!tr||!host)return;
    host.innerHTML=`<div class="modal-backdrop"><form id="transportConvert" class="modal settings-form no-wizard"><div class="modal-head"><h3>Émettre le billet de ${esc(r.passengerName)}</h3><button type="button" id="closeTransportConvert">×</button></div><p>Siège ${esc(r.seat)} · montant ${money(r.amount)} · acompte ${money(r.deposit)}</p><label>Complément encaissé<input name="extra" type="number" min="0" max="${Math.max(0,Number(r.amount)-Number(r.deposit||0))}" value="${Math.max(0,Number(r.amount)-Number(r.deposit||0))}" required></label><label>Mode de paiement<select name="paymentMethod"><option>Espèces</option><option>Mobile Money</option><option>Carte</option></select></label><button class="primary">Confirmer et émettre</button></form></div>`;
    host.querySelector('#closeTransportConvert').onclick=()=>host.innerHTML='';
    const f=host.querySelector('form');f.onsubmit=e=>{e.preventDefault();run(f.querySelector('button.primary'),async()=>{
      await synced();const d=Object.fromEntries(new FormData(f)),bus=state.ticketBuses.find(b=>b.id===tr.busId),seat=bus?.seats?.find(s=>String(s.label)===String(r.seat));
      const result=await api('/tickets/confirm',{reservationId:r.id,ticket:{id:uid(),pnr:ctx.pnr(),publicToken:uid(),tripId:tr.id,passengerName:r.passengerName,phone:r.phone,seat:r.seat,seatClass:seat?.class||'Simple',fare:Number(r.amount),paid:Number(r.deposit||0)+Number(d.extra||0),discount:0,paymentMethod:d.paymentMethod,boardingPoint:r.boardingPoint||tr.origin,dropPoint:r.dropPoint||tr.destination,busLabel:bus?.name||''}});
      replace('tickets',result.ticket);r.status='Convertie';r.ticketId=result.ticket.id;persist();await ctx.sync();render();await ctx.printTicket(result.ticket);
    });};
  }
  async function selectSeat(tripId,seat,boardingPoint,dropPoint) {
    if(holding)throw new Error('La réservation du siège précédent est en cours');
    if(!navigator.onLine){hold=null;notify('Mode hors connexion : la disponibilité entre agences sera vérifiée à la synchronisation.','warning',6000);return;}
    holding=true;
    try {await synced();hold=await api('/holds',{tripId,seat,boardingPoint,dropPoint,deviceId:ctx.deviceId(),holdId:hold?.id||''});notify('Siège bloqué pendant 5 minutes sur les guichets connectés.','success');}
    finally {holding=false;}
  }
  async function confirmTicket(ticket,document=null) {
    if(!navigator.onLine){if(document)throw new Error('La sauvegarde de la pièce et du billet nécessite une connexion');if(ticket.packId)throw new Error('Un carnet prépayé nécessite une connexion pour éviter deux débits concurrents');return {...ticket,status:'À synchroniser',confirmationSource:'offline'}};
    if(holding)throw new Error('Attendez la confirmation du blocage du siège');
    const data=await api('/tickets/confirm',{ticket,document,holdId:hold?.id||''});hold=null;
    if(data.customer)replace('ticketCustomers',data.customer);
    return data.ticket;
  }
  function releaseHold() {
    const old=hold;hold=null;
    if(old&&navigator.onLine)api('/holds/'+old.id,undefined,'DELETE').catch(()=>{});
  }
  return {panel,bind,boardTicket:async(id,tripId,documentNumber='')=>api('/tickets/'+encodeURIComponent(id)+'/board',{tripId,documentNumber}),recoverTicket:async id=>(await api('/tickets/'+encodeURIComponent(id),undefined,'GET')).ticket,confirmTicket,selectSeat,releaseHold,enhanceTicket};
}
