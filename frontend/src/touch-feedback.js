import { Capacitor, registerPlugin } from '@capacitor/core';
export function installTouchFeedback(){
  const printer=registerPlugin('NativePrinter');let last=0;
  document.addEventListener('pointerup',event=>{
    const target=event.target instanceof Element?event.target.closest('button,a[data-page],[role=button]'):null;
    if(!target||target.disabled||target.getAttribute('aria-disabled')==='true')return;
    target.classList.remove('tap-feedback');requestAnimationFrame(()=>target.classList.add('tap-feedback'));setTimeout(()=>target.classList.remove('tap-feedback'),220);
    if(event.pointerType!=='touch'||Date.now()-last<70)return;last=Date.now();
    if(Capacitor.getPlatform()==='android')printer.tapFeedback().catch(()=>{});else navigator.vibrate?.(8);
  },{passive:true});
}
