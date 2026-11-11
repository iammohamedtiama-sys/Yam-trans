import { Capacitor, registerPlugin } from '@capacitor/core';
import { parseIdentityText } from './identity-text.js';
import { captureCameraPhoto } from './camera-capture.js';

const scanner=registerPlugin('IdentityScanner');
export const nativeIdentityAvailable=()=>Capacitor.getPlatform()==='android'&&Capacitor.isPluginAvailable('IdentityScanner');

export async function readIdentityDocument({source='camera',signal,kind=''}={},serverOcr) {
  if(source!=='camera')throw Error('Photographiez la pièce avec la caméra ; l’import de fichier est désactivé.');
  let result;
  if(nativeIdentityAvailable())result=await scanner.takePhoto();
  else{
    const image=await captureCameraPhoto({signal});
    try{result={...await serverOcr(image),image};}
    catch(e){result={image,text:'',warning:'Photo prise. La lecture a échoué : '+e.message};}
  }
  return {...result,...parseIdentityText(result.text||'',kind),image:result.image,captureSource:'camera'};
}
