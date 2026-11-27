import { Capacitor, registerPlugin } from '@capacitor/core';
import { parseIdentityText } from './identity-text.js';
import { captureCameraPhoto } from './camera-capture.js';

const scanner=registerPlugin('IdentityScanner');
export const nativeIdentityAvailable=()=>Capacitor.getPlatform()==='android'&&Capacitor.isPluginAvailable('IdentityScanner');

export async function readIdentityDocument({source='camera',signal,kind='',image:providedImage}={},serverOcr) {
  if(source!=='camera')throw Error('Photographiez la pièce avec la caméra ; l’import de fichier est désactivé.');
  const image=providedImage || await captureCameraPhoto({signal});
  let result;
  try{
    result=nativeIdentityAvailable()?await scanner.readImage({image}):await serverOcr(image);
  }catch(e){result={image,text:'',warning:'Photo prise. La lecture a échoué : '+e.message};}
  return {...result,...parseIdentityText(result.text||'',kind),image,captureSource:'camera'};
}
