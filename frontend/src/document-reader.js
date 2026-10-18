import { Capacitor, registerPlugin } from '@capacitor/core';
import { parseIdentityText } from './identity-text.js';

const scanner=registerPlugin('IdentityScanner');
export const nativeIdentityAvailable=()=>Capacitor.getPlatform()==='android'&&Capacitor.isPluginAvailable('IdentityScanner');

async function imageData(file){
 if(!file||file.size>15_000_000)throw Error('Choisissez une image de moins de 15 Mo.');
 const url=URL.createObjectURL(file);
 try{
  const image=new Image();image.src=url;await image.decode();
  if(!image.naturalWidth||image.naturalWidth*image.naturalHeight>100_000_000)throw Error('Dimensions d’image excessives.');
  const scale=Math.min(1,2400/Math.max(image.naturalWidth,image.naturalHeight)),canvas=document.createElement('canvas');
  canvas.width=Math.round(image.naturalWidth*scale);canvas.height=Math.round(image.naturalHeight*scale);canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);
  return canvas.toDataURL('image/jpeg',0.88);
 }finally{URL.revokeObjectURL(url);}
}

export async function readIdentityDocument({source='file',file},serverOcr){
 let result;
 if(source==='camera'||source==='gallery'){
  if(!nativeIdentityAvailable())throw Error('La caméra native nécessite la nouvelle version Android de YamTrans.');
  result=await (source==='camera'?scanner.takePhoto():scanner.choosePhoto());
 }else{
  const image=await imageData(file);
  try{result={...await serverOcr(image),image};}
  catch(e){return {image,text:'',candidates:[],warning:'Photo conservée. '+e.message};}
 }
 return {...result,...parseIdentityText(result.text||''),image:result.image};
}
