import { Capacitor } from '@capacitor/core';
import { Geolocation } from '@capacitor/geolocation';
const native=()=>Capacitor.isNativePlatform();
const options={enableHighAccuracy:true,timeout:20000,maximumAge:0,minimumUpdateInterval:10000,interval:15000};
function explain(error){return Error(error?.code==='OS-PLUG-GLOC-0003'||error?.code===1?'Autorisez la localisation pour transmettre la position du voyage.':error?.code==='OS-PLUG-GLOC-0007'?'Activez la localisation GPS du téléphone.':error?.code===3?'Position non obtenue. Placez-vous près d’une fenêtre ou à l’extérieur puis réessayez.':error?.message||'Position GPS indisponible.');}
async function permission(){if(!native())return;const state=await Geolocation.requestPermissions({permissions:['location']});if(state.location!=='granted'&&state.coarseLocation!=='granted')throw Error('Autorisez la localisation dans les paramètres du téléphone.');}
export async function getCurrentLocation(){
  try{if(native()){await permission();return await Geolocation.getCurrentPosition(options);}if(!navigator.geolocation)throw Error('Localisation non disponible sur cet appareil.');return await new Promise((resolve,reject)=>navigator.geolocation.getCurrentPosition(resolve,reject,options));}catch(e){throw explain(e);}
}
export function watchLocation(onPosition,onError){
  let id=null,stopped=false;
  const fail=e=>{if(!stopped)onError(explain(e));};
  if(native())(async()=>{try{await permission();if(stopped)return;id=await Geolocation.watchPosition(options,(position,error)=>{if(stopped)return;if(error)fail(error);else if(position)onPosition(position);});if(stopped)await Geolocation.clearWatch({id});}catch(e){fail(e);}})();
  else if(navigator.geolocation)id=navigator.geolocation.watchPosition(p=>{if(!stopped)onPosition(p);},fail,options);else fail(Error('Localisation non disponible.'));
  return {stop(){stopped=true;if(id!==null){if(native())Geolocation.clearWatch({id}).catch(()=>{});else navigator.geolocation.clearWatch(id);id=null;}}};
}
