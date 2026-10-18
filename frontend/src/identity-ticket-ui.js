import { readIdentityDocument, nativeIdentityAvailable } from './document-reader.js';
// Identity photos stay in memory until the server saves the sale atomically.
export function createIdentityTicketUi(ctx) {
  const {state, esc, notify, render, api} = ctx;
  let saleForm=null, photo='', reading=false, generation=0,tenant='';
  const normalized=s=>String(s||'').toUpperCase().replace(/\s/g,'');
  let captureSerial=0;
  async function capture(input,status,candidates,preview,onNumber,onPhoto,source='file',onFields=()=>{}) {
    const file=input.files?.[0];if(source==='file'&&!file)return;
    const key=state.company?.id+':'+state.user?.id,page=state.page,serial=++captureSerial;
    const valid=()=>serial===captureSerial&&key===state.company?.id+':'+state.user?.id&&state.page===page;
    const fresh=el=>document.getElementById(el.id)||el;
    status.textContent=source==='camera'?'Ouverture de la caméra…':'Lecture de la pièce…';candidates.replaceChildren();
    try {
      const result=await readIdentityDocument({source,file},image=>api('/documents/ocr',{image}));if(!valid())return;
      onPhoto(result.image);preview=fresh(preview);preview.src=result.image;preview.hidden=false;
      status=fresh(status);candidates=fresh(candidates);candidates.replaceChildren();
      if(result.primaryNumber)onNumber(result.primaryNumber);
      onFields(result);
      for(const number of result.candidates||[]){const b=document.createElement('button');b.type='button';b.textContent=number;b.onclick=()=>onNumber(number);candidates.append(b);}
      status.textContent=result.warning||(result.primaryNumber?'Numéro proposé automatiquement. Vérifiez le numéro et le nom sur la pièce puis confirmez.':'Aucun numéro lisible. Photographiez la pièce entière, nette et sans reflet, ou saisissez le numéro.');
    } catch(e) {if(valid()&&e.code!=='CANCELLED')fresh(status).textContent=e.message;}
  }
  function bindSale() {
    const f=document.querySelector('#ticketSaleForm');
    if(!f){if(saleForm){saleForm=null;photo='';generation++;}return;}
    if(f===saleForm)return;
    saleForm=f;
    const ref=f.elements.documentNumber?.closest('label');if(!ref)return;
    ref.innerHTML='Numéro de CNIB / passeport<input name="documentNumber" maxlength="100" autocomplete="off">';
    const box=document.createElement('section');box.className='identity-sale-card';
    box.innerHTML=`<div><b>Voyager avec sa CNIB</b><p>Photographiez la pièce à l’achat. Le voyageur pourra la présenter à l’embarquement pour retrouver son billet.</p></div><div class="grid"><label>Type de pièce<select name="documentKind"><option>CNIB</option><option>Passeport</option><option>Autre</option></select></label><label>Expiration de la pièce<input name="documentExpiresOn" type="date"></label></div><div class="button-row"><button type="button" id="saleNativeCamera">Prendre une photo</button><button type="button" id="saleNativeGallery">Importer une image</button></div><label class="file-button" id="saleWebPhoto">Importer une image<input id="saleIdentityPhoto" type="file" accept="image/png,image/jpeg,image/webp"></label><img hidden class="ops-document-photo" id="saleIdentityPreview" alt="Pièce à vérifier"><p id="saleIdentityStatus" role="status"></p><div id="saleIdentityCandidates" class="button-row"></div><label><input type="checkbox" id="saleIdentityConfirmed" name="documentConfirmed"> J’ai vérifié le numéro, le nom et la photo sur la pièce</label><button type="button" id="saleIdentityClear">Retirer la pièce</button>`;
    ref.parentElement.insertAdjacentElement('afterend',box);
    const status=box.querySelector('#saleIdentityStatus'),preview=box.querySelector('img'),confirmed=box.querySelector('#saleIdentityConfirmed');
    if(photo){preview.src=photo;preview.hidden=false;status.textContent='Photo prête à être associée au billet.';}
    const invalidate=()=>{confirmed.checked=false;};
    f.elements.documentNumber.addEventListener('input',invalidate);f.elements.passengerName.addEventListener('input',invalidate);f.elements.phone.addEventListener('input',invalidate);
    const read=async(input,source='file')=>{
      if(reading)return;reading=true;confirmed.checked=false;
      try{await capture(input,status,box.querySelector('#saleIdentityCandidates'),preview,number=>{const form=document.querySelector('#ticketSaleForm');if(form){form.elements.documentNumber.value=number;form.querySelector('#saleIdentityConfirmed').checked=false;}},value=>{photo=value;},source,result=>{const form=document.querySelector('#ticketSaleForm');if(!form)return;if(result.customerName&&!form.elements.passengerName.value)form.elements.passengerName.value=result.customerName;if(result.kind)form.elements.documentKind.value=result.kind;});}
      finally{reading=false;}
    };
    const native=nativeIdentityAvailable();box.querySelector('#saleNativeCamera').hidden=!native;box.querySelector('#saleNativeGallery').hidden=!native;box.querySelector('#saleWebPhoto').hidden=native;
    box.querySelector('#saleNativeCamera').onclick=e=>read(e.currentTarget,'camera');box.querySelector('#saleNativeGallery').onclick=e=>read(e.currentTarget,'gallery');
    box.querySelector('#saleIdentityPhoto').onchange=e=>read(e.target);
    box.querySelector('#saleIdentityClear').onclick=()=>{captureSerial++;photo='';preview.removeAttribute('src');preview.hidden=true;confirmed.checked=false;f.elements.documentNumber.value='';f.elements.documentExpiresOn.value='';box.querySelector('#saleIdentityPhoto').value='';box.querySelector('#saleIdentityCandidates').replaceChildren();status.textContent='Pièce retirée.';};
  }
  function saleDocument() {
    const f=document.querySelector('#ticketSaleForm');if(!f)return null;
    if(reading)throw Error('Attendez la fin de la lecture de la pièce.');
    const number=normalized(f.elements.documentNumber.value);
    if(!number&&!photo)return null;
    if(!number)throw Error('Confirmez le numéro de la pièce photographiée.');
    if(!f.querySelector('#saleIdentityConfirmed')?.checked)throw Error('Vérifiez et confirmez la pièce avant de créer le billet.');
    return {kind:f.elements.documentKind.value,number,expiresOn:f.elements.documentExpiresOn.value,photo};
  }
  function resetSale(){photo='';saleForm=null;reading=false;generation++;captureSerial++;}
  function bindBoarding() {
    const host=document.querySelector('#boardingIdentity');if(!host)return;
    const input=host.querySelector('[name=number]'),status=host.querySelector('[role=status]'),results=host.querySelector('#boardingIdentityResults');
    status.id='boardingIdentityStatus';host.querySelector('img').id='boardingIdentityPreview';
    const photoInput=host.querySelector('#boardingIdentityPhoto');
    photoInput.closest('label').insertAdjacentHTML('beforebegin','<div class="button-row"><button type="button" id="boardingNativeCamera">Prendre une photo</button><button type="button" id="boardingNativeGallery">Importer une image</button></div>');
    const native=nativeIdentityAvailable();photoInput.closest('label').hidden=native;host.querySelector('#boardingNativeCamera').hidden=!native;host.querySelector('#boardingNativeGallery').hidden=!native;
    const read=(el,source='file')=>capture(el,status,host.querySelector('#boardingIdentityCandidates'),host.querySelector('img'),number=>{const field=document.querySelector('#boardingIdentity [name=number]');if(field)field.value=number;},()=>{},source);
    photoInput.onchange=e=>read(e.target);host.querySelector('#boardingNativeCamera').onclick=e=>read(e.currentTarget,'camera');host.querySelector('#boardingNativeGallery').onclick=e=>read(e.currentTarget,'gallery');
    host.querySelector('form').onsubmit=async e=>{
      e.preventDefault();const b=e.target.querySelector('[type=submit]');if(b.disabled)return;b.disabled=true;results.replaceChildren();
      try {
        const tripId=document.querySelector('#boardingTrip').value;if(!tripId)throw Error('Choisissez le départ à contrôler.');
        const number=normalized(input.value),value=await api('/documents/lookup?number='+encodeURIComponent(number));
        if(!host.isConnected||document.querySelector('#boardingTrip')?.value!==tripId)return;
        const list=value.tickets||[];
        results.innerHTML=`<h4>${esc(value.customerName)}</h4>${value.photo?`<img class="ops-document-photo" src="${esc(value.photo)}" alt="Pièce enregistrée à l’achat">`:''}<p>Comparez la pièce présentée et la photo enregistrée avant validation.</p>`;
        const matches=list.filter(t=>t.tripId===tripId);
        for(const t of matches){const card=document.createElement('div');card.className='ops-identity-result';card.innerHTML=`<b>${esc(t.passengerName)} · siège ${esc(t.seat)}</b><span>${esc(t.origin)} → ${esc(t.destination)} · ${esc(new Date(t.departureAt).toLocaleString('fr-FR'))}</span><small>${esc(t.pnr)} · ${t.boarded?'Déjà embarqué':Number(t.balance)>0?'Solde à régler':'Billet réglé'}</small>`;if(!t.boarded){const btn=document.createElement('button');btn.textContent='Pièce contrôlée · valider l’embarquement';btn.className='primary';btn.onclick=async()=>{if(btn.disabled)return;btn.disabled=true;try{const out=await ctx.boardTicket(t.id,tripId,number);status.textContent=out.alreadyBoarded?'Passager déjà embarqué.':`${t.passengerName} · siège ${t.seat} · embarquement confirmé.`;btn.textContent='Embarqué';}catch(e){notify(e.message,'error',8000);btn.disabled=false;}};card.append(btn);}results.append(card);}
        if(!matches.length){status.textContent='Aucun billet pour ce départ. Contrôlez les autres voyages ci-dessous ; un responsable doit transférer le billet avant tout embarquement.';for(const t of list){const row=document.createElement('div');row.className='ops-identity-result';row.innerHTML=`<b>Autre départ · ${esc(t.pnr)}</b><span>${esc(t.origin)} → ${esc(t.destination)} · ${esc(new Date(t.departureAt).toLocaleString('fr-FR'))} · siège ${esc(t.seat)}</span>`;results.append(row);}}
        else status.textContent=`${matches.length} billet(s) retrouvé(s) avec la pièce.`;
      }catch(e){status.textContent=e.message;notify(e.message,'warning');}finally{b.disabled=false;}
    };
    document.querySelector('#boardingTrip')?.addEventListener('change',()=>{results.replaceChildren();status.textContent='Départ changé. Recherchez à nouveau la pièce.';});
  }
  function bind(){const key=state.company?.id+':'+state.user?.id;if(tenant!==key){resetSale();tenant=key;}bindSale();bindBoarding();}
  return {bind,saleDocument,resetSale};
}
