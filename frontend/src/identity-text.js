// OCR suggestions are never proof of identity. The agent confirms the document.
const plain=s=>String(s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase();
const cleanNumber=s=>s.toUpperCase().replace(/[\s-]/g,'').replace(/^([A-Z]{1,3})([0-9OI]+)$/,(_,prefix,digits)=>prefix+digits.replace(/O/g,'0').replace(/I/g,'1'));
export function documentNumberKind(value){const n=cleanNumber(String(value||''));return /^B[A-Z0-9]{4,29}$/.test(n)&&/\d/.test(n)?'CNIB':/^A[A-Z0-9]{4,29}$/.test(n)&&/\d/.test(n)?'Passeport':'';}
export function parseIdentityText(text,preferredKind=''){
 const lines=String(text||'').split(/\r?\n/).map(s=>s.trim()).filter(Boolean),found=new Map();
 const add=(raw,score)=>{const value=cleanNumber(raw);if(value.length<6||value.length>24||!/[0-9]{4}/.test(value)||/^(19|20)\d{2}$/.test(value))return;found.set(value,Math.max(found.get(value)||0,score));};
 for(let i=0;i<lines.length;i++){
  const line=plain(lines[i]),labeled=/(?:NUMERO|NUMBER|DOCUMENT\s*(?:NO|N°)|N[°º]|CNIB\s*[:=])/.test(line);
  // Dates and place codes must not become a card number.
  const scan=line.replace(/\b\d{1,4}[/.]\d{1,2}[/.]\d{1,4}\b/g,' ');
  for(const m of scan.matchAll(/\b[A-Z]{1,3}[ \t-]*\d[\dOI \t-]{3,18}\d\b/g))add(m[0],labeled?100:80);
  if(labeled){
   const value=scan.replace(/^.*?(?:NUMERO|NUMBER|N[°º]|CNIB\s*[:=]|DOCUMENT\s*(?:NO|N°))[^A-Z0-9]*/,'');
   for(const m of value.matchAll(/\b(?:[A-Z]{1,3}[ \t-]*)?\d[\dOI \t-]{3,18}\d\b/g))add(m[0],100);
   if(i+1<lines.length&&/^[A-Z0-9 \t-]+$/.test(plain(lines[i+1])))add(lines[i+1],90);
  }
  // ICAO document number at the beginning of a passport MRZ line.
  if(/^[A-Z0-9<]{30,44}$/.test(line)&&/\d/.test(line.slice(0,9)))add(line.slice(0,9).replace(/</g,''),85);
 }
 const detected=/PASSEPORT|PASSPORT|P<BFA/.test(plain(text))?'Passeport':/CNIB|CARTE\s+NATIONALE/.test(plain(text))?'CNIB':'';
 const expected=preferredKind||detected;
 const candidates=[...found].filter(([n])=>documentNumberKind(n)&&(!expected||documentNumberKind(n)===expected)).sort((a,b)=>b[1]-a[1]).map(([n])=>n).slice(0,15);
 const field=pattern=>{
  for(let i=0;i<lines.length;i++){
   const normalized=plain(lines[i]);const m=normalized.match(pattern);if(!m)continue;
   let value=lines[i].slice(m[0].length).replace(/^\s*[:/\-]\s*/,'').trim();
   if(!value&&lines[i+1]&&!/NUMERO|NUMBER|NAISSANCE|BIRTH|NATIONAL|EXPIR|PRENOM|GIVEN|SURNAME/.test(plain(lines[i+1])))value=lines[i+1];
   if(value&&/[A-Za-zÀ-ÿ]/.test(value)&&!/[0-9]/.test(value)&&value.length<120)return value;
  }return '';
 };
 const surname=field(/^(?:NOM(?:\s*\/\s*SURNAME)?|SURNAME)\s*:?\s*/);
 const firstNames=field(/^(?:PRENOMS?(?:\s*\/\s*GIVEN\s*NAMES?)?|GIVEN\s*NAMES?)\s*:?\s*/);
 const mrz=lines.map(plain).find(l=>/^P<[A-Z<]{3}/.test(l));
 let mrzName='';if(mrz){const [last,first]=mrz.slice(5).split('<<');mrzName=[first,last].filter(Boolean).map(v=>v.replace(/</g,' ').trim()).join(' ');}
 let expiresOn='';
 const expiryLine=lines.findIndex(l=>/EXPIR|VALID.*(?:UNTIL|JUSQU)/.test(plain(l)));
 if(expiryLine>=0){const match=(lines[expiryLine]+' '+(lines[expiryLine+1]||'')).match(/(\d{2})[/. -](\d{2})[/. -](\d{4})/);if(match)expiresOn=match[3]+'-'+match[2]+'-'+match[1];}
 const second=lines.map(plain).find(l=>/^[A-Z0-9<]{40,44}$/.test(l)&&/^[A-Z][A-Z0-9<]{8}\d/.test(l));
 if(second&&/^[0-9]{6}$/.test(second.slice(21,27))){const d=second.slice(21,27);expiresOn='20'+d.slice(0,2)+'-'+d.slice(2,4)+'-'+d.slice(4,6);}
 if(expiresOn&&(!Number.isFinite(Date.parse(expiresOn+'T00:00:00Z'))))expiresOn='';
 const kind=expected||documentNumberKind(candidates[0]);
 return {text:String(text||''),candidates,primaryNumber:candidates[0]||'',customerName:[firstNames,surname].filter(Boolean).join(' ')||mrzName,expiresOn,kind,requiresConfirmation:true};
}
