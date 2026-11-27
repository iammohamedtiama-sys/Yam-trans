export const manifestLocked = manifest => Boolean(manifest?.arrivedAt);
export const manifestLockMessage = 'Arrivée confirmée : ce bordereau ne peut plus être modifié.';
export function manifestEditAttributes(manifest) {
  return manifestLocked(manifest)
    ? `disabled aria-disabled="true" title="${manifestLockMessage}"`
    : '';
}

export function refreshManifestLocks(manifests, root=document) {
  const arrived=new Set((manifests||[]).filter(manifestLocked).map(m=>String(m.id)));
  root.querySelectorAll('[data-edit-manifest]').forEach(button=>{
    if(!arrived.has(button.dataset.editManifest))return;
    button.disabled=true;button.setAttribute('aria-disabled','true');button.title=manifestLockMessage;
  });
  const form=root.querySelector('#manifestForm');
  if(!form||!arrived.has(form.dataset.manifestId))return;
  form.querySelectorAll('input,select,textarea,button:not(#closeManifest)').forEach(field=>field.disabled=true);
  if(!form.querySelector('[data-manifest-lock-note]')){
    const note=root.createElement('p');note.dataset.manifestLockNote='';note.setAttribute('role','status');note.textContent=manifestLockMessage;form.prepend(note);
  }
}
