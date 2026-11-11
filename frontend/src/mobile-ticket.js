let open=false;
window.addEventListener('resize',()=>{if(window.innerWidth>760){open=false;document.body.classList.remove('seat-sheet-active');document.querySelectorAll('.seat-sheet-open').forEach(el=>{el.classList.remove('seat-sheet-open');el.removeAttribute('role');el.removeAttribute('aria-modal');});}});
const mobile=()=>window.innerWidth<=760;
export function enhanceMobileTicketSale(){
 const form=document.querySelector('#ticketSaleForm');
 if(!form){open=false;document.body.classList.remove('seat-sheet-active');return;}
 const picker=form.querySelector('#seatPicker'),section=picker?.closest('.counter-step');if(!section||section.dataset.mobileSeats)return;
 section.dataset.mobileSeats='1';section.classList.add('mobile-seat-section');
 const launch=document.createElement('button');launch.id='openMobileSeats';launch.type='button';launch.className='mobile-seat-launch';
 const close=document.createElement('button');close.id='closeMobileSeats';close.type='button';close.className='mobile-seat-close';close.textContent='Valider le siège';
 const summary=document.createElement('p');summary.className='mobile-seat-summary';summary.setAttribute('aria-live','polite');
 section.insertBefore(launch,picker);section.insertBefore(summary,picker);section.append(close);
 let choosing=false;
 const update=()=>{const seat=form.querySelector('#selectedSeat')?.value;launch.textContent=seat?'Modifier le siège '+seat:'Choisir mon siège';summary.textContent=seat?'Siège '+seat+' · '+(form.querySelector('#selectedSeatClass')?.value||''):'Sélectionnez une place Simple ou VIP sur le plan du bus.';section.classList.toggle('seat-sheet-open',open&&mobile());document.body.classList.toggle('seat-sheet-active',open&&mobile());if(open&&mobile()){section.setAttribute('role','dialog');section.setAttribute('aria-modal','true');section.setAttribute('aria-label','Choisir une place');}else{section.removeAttribute('role');section.removeAttribute('aria-modal');}};
 const set=value=>{open=value;update();if(!open)launch.focus();else picker.querySelector('[data-seat]:not(:disabled)')?.focus();};
 launch.onclick=()=>{if(!form.elements.tripId.value){form.elements.tripId.focus();form.elements.tripId.reportValidity();return;}set(true);};close.onclick=()=>set(false);
 picker.addEventListener('click',e=>{if(e.target.closest('[data-seat]'))choosing=true;});
 const observer=new MutationObserver(()=>{if(!section.isConnected){observer.disconnect();return;}if(choosing&&form.querySelector('#selectedSeat')?.value){choosing=false;set(false);}else update();});observer.observe(picker,{subtree:true,childList:true,attributes:true,attributeFilter:['class']});
 section.addEventListener('keydown',e=>{if(open&&e.key==='Escape'){e.preventDefault();set(false);}if(open&&e.key==='Tab'){const buttons=[...section.querySelectorAll('button:not(:disabled)')].filter(b=>b.getClientRects().length);const first=buttons[0],last=buttons.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}});
 form.elements.tripId.addEventListener('change',()=>{open=false;update();});
 update();
}
