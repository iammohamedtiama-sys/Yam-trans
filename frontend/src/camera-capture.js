import jsQR from 'jsqr';
// Live capture only. Cancelling or leaving the screen always stops camera tracks.
export function captureCameraPhoto({facingMode='environment',signal,scanQr=false}={}) {
  if(!navigator.mediaDevices?.getUserMedia) return Promise.reject(Error('La caméra nécessite une connexion HTTPS et son autorisation dans le navigateur.'));
  return new Promise((resolve,reject)=>{
    let stream,finished=false,scanTimer=null;
    const previous=document.activeElement,host=document.createElement('div');host.className='camera-capture modal-backdrop';
    host.innerHTML='<section class="camera-dialog" role="dialog" aria-modal="true" aria-labelledby="cameraTitle"><header><div><small>CONTRÔLE D’IDENTITÉ</small><h2 id="cameraTitle">Photographier la pièce</h2></div><button type="button" data-camera-cancel aria-label="Fermer la caméra">×</button></header><div class="camera-viewport"><video autoplay playsinline muted></video><div class="camera-guide" aria-hidden="true"></div></div><p role="status">Placez la pièce entière dans le cadre, sans reflet. Le numéro doit être net.</p><footer><button type="button" data-camera-cancel>Annuler</button><button type="button" class="primary" data-camera-shoot disabled>Prendre la photo</button></footer></section>';
    if(scanQr){host.querySelector('h2').textContent='QR, CNIB ou passeport';host.querySelector('[role=status]').textContent='Présentez un QR : il est lu automatiquement. Pour une CNIB ou un passeport, cadrez la pièce puis prenez la photo.';}
    document.body.append(host);const video=host.querySelector('video'),shoot=host.querySelector('[data-camera-shoot]');
    const cleanup=()=>{clearTimeout(scanTimer);stream?.getTracks().forEach(track=>track.stop());video.srcObject=null;observer.disconnect();document.removeEventListener('keydown',key);window.removeEventListener('pagehide',cancel);window.removeEventListener('popstate',cancel);window.removeEventListener('yam:navigate',cancel);signal?.removeEventListener('abort',abort);host.remove();previous?.focus?.();};
    const finish=(value,error)=>{if(finished)return;finished=true;cleanup();if(error)reject(error);else resolve(value);};
    const cancel=()=>finish(null,Object.assign(Error('Prise de photo annulée.'),{code:'CANCELLED'}));
    const abort=()=>cancel();const key=e=>{if(e.key==='Escape'){e.preventDefault();cancel();}if(e.key==='Tab'){const buttons=[...host.querySelectorAll('button:not(:disabled)')];const i=buttons.indexOf(document.activeElement);e.preventDefault();buttons[(i+(e.shiftKey?-1:1)+buttons.length)%buttons.length]?.focus();}};
    const observer=new MutationObserver(()=>{if(!host.isConnected)cancel();});observer.observe(document.body,{childList:true});
    document.addEventListener('keydown',key);signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted){cancel();return;}
    window.addEventListener('pagehide',cancel);window.addEventListener('popstate',cancel);window.addEventListener('yam:navigate',cancel);
    host.querySelectorAll('[data-camera-cancel]').forEach(b=>b.onclick=cancel);host.querySelector('[data-camera-cancel]').focus();
    shoot.onclick=()=>{
      if(!video.videoWidth||!video.videoHeight)return;
      try{const scale=Math.min(1,2400/Math.max(video.videoWidth,video.videoHeight)),canvas=document.createElement('canvas');canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);finish(canvas.toDataURL('image/jpeg',.88));}catch(e){finish(null,Error('Impossible de prendre la photo. Recommencez.'));}
    };
    navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:facingMode},width:{ideal:1920},height:{ideal:1080}},audio:false}).then(async value=>{
      if(finished){value.getTracks().forEach(track=>track.stop());return;}
      stream=value;video.srcObject=value;
      const scan=()=>{if(finished)return;if(video.videoWidth&&video.videoHeight){const c=document.createElement('canvas'),scale=Math.min(1,900/video.videoWidth);c.width=Math.round(video.videoWidth*scale);c.height=Math.round(video.videoHeight*scale);const g=c.getContext('2d',{willReadFrequently:true});g.drawImage(video,0,0,c.width,c.height);const pixels=g.getImageData(0,0,c.width,c.height);const code=jsQR(pixels.data,c.width,c.height);if(code?.data){finish({type:'qr',value:code.data});return;}}scanTimer=setTimeout(scan,180);};if(scanQr)scanTimer=setTimeout(scan,180);video.onloadedmetadata=()=>{if(!finished)shoot.disabled=false;};
      try{await video.play();if(video.videoWidth)shoot.disabled=false;}catch{finish(null,Error('Impossible de démarrer la caméra. Vérifiez son autorisation.'));}
    }).catch(e=>finish(null,Error(e.name==='NotAllowedError'?'Autorisez la caméra pour photographier la pièce.':e.name==='NotFoundError'?'Aucune caméra détectée sur cet appareil.':'Caméra indisponible. Fermez les autres applications qui l’utilisent puis réessayez.')));
  });
}
