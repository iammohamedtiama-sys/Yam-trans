// A rejected edit is kept separately from the authoritative operational record.
export const SYNC_KEYS={ticket_buses:'ticketBuses',ticket_routes:'ticketRoutes',ticket_trips:'ticketTrips',ticket_boardings:'ticketBoardings',ticket_customers:'ticketCustomers',ticket_promos:'ticketPromos',ticket_refunds:'ticketRefunds',ticket_reservations:'ticketReservations',ticket_baggage:'ticketBaggage',loyalty_transactions:'loyaltyTransactions',notification_logs:'notificationLogs'};
const clone=value=>value==null?null:JSON.parse(JSON.stringify(value));
export function reconcileSyncConflicts(previous=[],conflicts=[],sent={},remote={},at=new Date().toISOString(),userId=''){
 const archive=clone(previous)||[],records=[];
 for(const conflict of conflicts){
  const kinds=conflict.entityType?[conflict.entityType]:Object.keys(sent).filter(k=>sent[k]?.some(p=>p.id===conflict.id));
  const kind=kinds.length===1?kinds[0]:'';
  const local=kind?sent[kind]?.find(p=>p.id===conflict.id):null;
  const server=kind?remote[kind]?.find(p=>p.id===conflict.id):null;
  const same=archive.find(p=>p.userId===userId&&p.entityType===kind&&p.entityId===conflict.id&&p.type===conflict.type&&JSON.stringify(p.local)===JSON.stringify(local||null));
  const entry={userId,key:kind+':'+conflict.id+':'+at+':'+records.length,entityType:kind,entityId:conflict.id,type:conflict.type,message:conflict.message||conflict.detail||'La saisie locale diffère de la version autorisée sur le serveur.',local:clone(local),server:clone(server),at,status:'pending'};
  if(!same)archive.push(entry);
  records.push({kind,id:conflict.id,server:clone(server),hasLocal:!!local});
 }
 return {archive,records};
}

export function syncConflictsButton(state){
 const own=(state.syncConflicts||[]).filter(p=>!p.userId||p.userId===state.user?.id),count=own.filter(p=>p.status==='pending').length;
 return own.length?`<button type="button" class="sync-review-button" id="syncReview">${count?count+' saisie(s) à vérifier':'Conflits archivés ('+own.length+')'}</button>`:'';
}

export function bindSyncConflictReview({state,esc,save,render,download}){
 const open=document.querySelector('#syncReview');if(!open)return;
 open.onclick=()=>{
  const owner=state.company?.id+':'+state.user?.id;
  const host=document.querySelector('#fullMenuHost');if(!host)return;
  const list=(state.syncConflicts||[]).filter(p=>!p.userId||p.userId===state.user?.id).slice().reverse();
  host.innerHTML=`<div class="modal-backdrop"><section class="modal sync-review-dialog" role="dialog" aria-modal="true" aria-labelledby="syncReviewTitle"><div class="modal-head"><h3 id="syncReviewTitle">Saisies à vérifier</h3><button type="button" data-sync-close>Fermer</button></div><p>Les saisies locales sont conservées sur cet appareil. Les opérations refusées ne sont pas validées sur le serveur. Les autres ventes peuvent continuer.</p>${list.map((p,i)=>`<article class="sync-review-card"><b>${esc(p.local?.pnr||p.local?.code||p.entityId||'Opération')}</b><p>${esc(p.message)}</p>${p.status==='archived'?'<small>Archivé après vérification · copie locale conservée</small>':''}<small>${p.server?'Version serveur appliquée sur cet appareil.':'Saisie locale non validée, conservée dans ce dossier.'}</small><details><summary>Comparer les informations</summary><h4>Saisie locale conservée</h4><pre>${esc(JSON.stringify(p.local,null,2))}</pre><h4>Version serveur</h4><pre>${esc(JSON.stringify(p.server,null,2))}</pre></details><div class="button-row"><button type="button" data-sync-export="${i}">Exporter la saisie locale</button>${p.status!=='archived'?`<button type="button" data-sync-resolve="${i}">${p.server?'Conserver le serveur et archiver la saisie':'Archiver après vérification'}</button>`:''}</div></article>`).join('')}<p>Une place déjà vendue ne sera jamais forcée. Pour régulariser un paiement ou un billet refusé, contrôlez les encaissements puis utilisez les actions habituelles.</p></section></div>`;
  host.querySelector('[data-sync-close]').onclick=()=>host.replaceChildren();
  host.querySelectorAll('[data-sync-export]').forEach(b=>b.onclick=()=>download(list[Number(b.dataset.syncExport)]));
  host.querySelectorAll('[data-sync-resolve]').forEach(b=>b.onclick=()=>{
   if(owner!==state.company?.id+':'+state.user?.id)return;
   const entry=list[Number(b.dataset.syncResolve)];
   state.syncConflicts=state.syncConflicts.map(p=>p.key===entry.key?{...p,status:'archived',resolvedAt:new Date().toISOString()}:p);
   save();render();
  });
 };
}
