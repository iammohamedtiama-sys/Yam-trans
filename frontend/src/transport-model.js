// Pure rules shared by the guichet and the transport control screen.
export const stopName=value=>String(value&&typeof value==='object'?(value.name||value.label||''):(value??'')).replace(/\s+/gu,' ').trim();
export const stopKey=value=>stopName(value).normalize('NFKD').replace(/\p{M}/gu,'').toLocaleLowerCase('fr');
export function journeyStops(trip){
 const middle=Array.isArray(trip?.stops)?trip.stops:String(trip?.stops||'').split(/[,;\n\r]+/),origin=stopName(trip?.origin),destination=stopName(trip?.destination);
 if(!origin||!destination)throw Error('Départ et destination de la ligne requis');
 const stops=[],seen=new Set();
 for(const raw of [origin,...middle,destination]){const name=stopName(raw),key=stopKey(name);if(!name)continue;if(stops.length&&stopKey(stops.at(-1))===key)continue;if(seen.has(key))throw Error('Arrêt répété sur la ligne : '+name+'. Précisez des étapes distinctes.');seen.add(key);stops.push(name);}
 if(stops.length<2)throw Error('Le départ et la destination doivent être différents');return stops;
}
export function journeySpan(trip,from,to){
 const stops=journeyStops(trip),keys=stops.map(stopKey),a=keys.indexOf(stopKey(from||trip.origin)),b=keys.indexOf(stopKey(to||trip.destination));
 if(a<0||b<0)throw Error('Arrêt absent de ce trajet. Arrêts disponibles : '+stops.join(' → ')+'. Actualisez le départ puis choisissez à nouveau le siège.');
 if(a>=b)throw Error('La descente doit suivre l’embarquement');return {from:stops[a],to:stops[b],start:a,end:b};
}
export function allocationActive(item, at = Date.now()) {
  if (item.deleted || item.cancelled || ['Annulé','Annulée','Remboursé','Expirée','Convertie','Libérée'].includes(item.status)) return false;
  if (item.expiresAt && (!Number.isFinite(Date.parse(item.expiresAt)) || Date.parse(item.expiresAt) <= at)) return false;
  return true;
}

export function segmentFare(route, trip, from, to, seatClass, category = 'adult') {
  for (const line of String(route?.segmentFares || '').split(/[\n;]/)) {
    const match = line.match(/^\s*(.+?)\s*>\s*(.+?)\s*=\s*([^,;]+)\s*,\s*([^,;]+)\s*$/);
    if (match && stopKey(match[1]) === stopKey(from) && stopKey(match[2]) === stopKey(to)) {const fare=Number(match[seatClass === 'VIP' ? 4 : 3]);if(!Number.isFinite(fare)||fare<0)throw Error('Tarif de tronçon invalide');return fare;}
  }
  const key = category === 'child' ? (seatClass === 'VIP' ? 'fareChildVip' : 'fareChildSimple') : (seatClass === 'VIP' ? 'fareVip' : 'fareSimple');
  const adultKey = seatClass === 'VIP' ? 'fareVip' : 'fareSimple';
  return Number(route?.[key] ?? route?.[adultKey] ?? trip?.[key] ?? trip?.[adultKey] ?? 0);
}

export function peakOccupancy(trip, tickets) {
  const stops = journeyStops(trip);
  return Math.max(0, ...stops.slice(0,-1).map((_,i) => tickets.filter(t => {
    if (!allocationActive(t)) return false;
    const a=stops.map(stopKey).indexOf(stopKey(t.boardingPoint || trip.origin)), b=stops.map(stopKey).indexOf(stopKey(t.dropPoint || trip.destination));
    return a<0 || b<0 || (a<=i && i<b);
  }).length));
}

export function isoLocal(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new Error('Date invalide');
  return date.toISOString();
}

export function ticketNetReceipts(ticket) {
  if(ticket.deleted || ticket.cancelled || ticket.status==='Annulé') return 0;
  const paid=Number(ticket.paid ?? ticket.amount ?? 0);
  return ticket.status==='Remboursé' ? Math.max(0,paid-Number(ticket.refundedAmount ?? paid)) : paid;
}
