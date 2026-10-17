// Pure rules shared by the guichet and the transport control screen.
export function allocationActive(item, at = Date.now()) {
  if (item.deleted || item.cancelled || ['Annulé','Annulée','Remboursé','Expirée','Convertie','Libérée'].includes(item.status)) return false;
  if (item.expiresAt && (!Number.isFinite(Date.parse(item.expiresAt)) || Date.parse(item.expiresAt) <= at)) return false;
  return true;
}

export function segmentFare(route, trip, from, to, seatClass, category = 'adult') {
  for (const line of String(route?.segmentFares || '').split(/[\n;]/)) {
    const match = line.match(/^\s*(.+?)\s*>\s*(.+?)\s*=\s*([\d.]+)\s*,\s*([\d.]+)\s*$/);
    if (match && match[1].trim() === from && match[2].trim() === to) return Number(match[seatClass === 'VIP' ? 4 : 3]);
  }
  const key = category === 'child' ? (seatClass === 'VIP' ? 'fareChildVip' : 'fareChildSimple') : (seatClass === 'VIP' ? 'fareVip' : 'fareSimple');
  const adultKey = seatClass === 'VIP' ? 'fareVip' : 'fareSimple';
  return Number(route?.[key] ?? route?.[adultKey] ?? trip?.[key] ?? trip?.[adultKey] ?? 0);
}

export function peakOccupancy(trip, tickets) {
  const stops = [trip.origin, ...String(trip.stops || '').split(',').map(s=>s.trim()).filter(Boolean), trip.destination];
  return Math.max(0, ...stops.slice(0,-1).map((_,i) => tickets.filter(t => {
    if (!allocationActive(t)) return false;
    const a=stops.indexOf(t.boardingPoint || trip.origin), b=stops.indexOf(t.dropPoint || trip.destination);
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
