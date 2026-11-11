from .permissions import verified_action
"""Native YamTrans extensions; no third-party application code is imported."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .transport import active, bus_seats, lock_company, overlap, route_fare, stops_for


class Operation(BaseModel):
    model_config = {'str_strip_whitespace': True}
    id: str = Field(min_length=1, max_length=100)


class StockItem(Operation):
    sku: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=160)
    unit: str = Field(default='pièce', min_length=1, max_length=30)
    minimum: float = Field(default=0, ge=0, le=1_000_000_000, allow_inf_nan=False)


class StockMovement(Operation):
    itemId: str
    direction: Literal['Entrée', 'Sortie']
    quantity: float = Field(gt=0, le=1_000_000_000, allow_inf_nan=False)
    unitCost: float = Field(default=0, ge=0, le=1_000_000_000_000, multiple_of=0.01, allow_inf_nan=False)
    busId: str = ''
    tripId: str = ''
    reason: str = Field(min_length=3, max_length=500)
    paymentMethod: Literal['Espèces', 'Mobile Money', 'Virement', 'Carte'] = 'Espèces'


class Schedule(Operation):
    templateTripId: str
    start: str
    end: str
    weekdays: list[int] = Field(min_length=1, max_length=7)
    durationMinutes: int = Field(ge=15, le=10080)


class Charter(Operation):
    customerName: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=5, max_length=50)
    busId: str
    origin: str = Field(min_length=1, max_length=160)
    destination: str = Field(min_length=1, max_length=160)
    startsAt: str
    endsAt: str
    amount: float = Field(gt=0, le=1_000_000_000_000, multiple_of=0.01, allow_inf_nan=False)
    deposit: float = Field(default=0, ge=0, le=1_000_000_000_000, multiple_of=0.01, allow_inf_nan=False)
    paymentMethod: Literal['Espèces', 'Mobile Money', 'Virement', 'Carte'] = 'Espèces'


class CharterPayment(Operation):
    amount: float = Field(gt=0, le=1_000_000_000_000, multiple_of=0.01, allow_inf_nan=False)
    paymentMethod: Literal['Espèces', 'Mobile Money', 'Virement', 'Carte'] = 'Espèces'


class CharterStatus(BaseModel):
    status: Literal['Terminé', 'Annulé']


class Slot(Operation):
    label: str = Field(min_length=1, max_length=60)
    vehicleType: Literal['Moto', 'Voiture']
    rate: float = Field(ge=0, le=1_000_000_000_000, multiple_of=0.01, allow_inf_nan=False)
    pricing: Literal['jour', 'forfait']
    active: bool = True


class Preferences(BaseModel):
    stageNotifications: bool


def parse_time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, 'Date et heure avec fuseau horaire requises') from None


def legacy_trip_time(value):
    """Older guichets send datetime-local values interpreted as UTC by transport.py."""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return parse_time(value)


def install(app, env):
    Entity, Company, User = env['EntityV3'], env['Company'], env['AppUser']
    session, auth, now = env['db_session'], env['read_token'], env['utcnow']

    def rows(db, cid, kind):
        return [dict(r.payload) for r in db.scalars(select(Entity).where(
            Entity.company_id == cid, Entity.entity_type == kind, Entity.deleted.is_(False))).all()]

    def get(db, cid, kind, ident):
        row = db.get(Entity, {'company_id': cid, 'entity_type': kind, 'entity_id': ident})
        if not row or row.deleted:
            raise HTTPException(404, 'Élément introuvable dans cette société')
        return dict(row.payload)

    def put(db, cid, kind, payload):
        p = dict(payload)
        ident = p.get('id') or str(uuid.uuid4())
        row = db.get(Entity, {'company_id': cid, 'entity_type': kind, 'entity_id': ident})
        version = row.version + 1 if row else 1
        p.update(id=ident, companyId=cid, _serverVersion=version, updatedAt=now().isoformat())
        if row:
            row.payload, row.version, row.updated_at = p, version, now()
        else:
            db.add(Entity(company_id=cid, entity_type=kind, entity_id=ident,
                          payload=p, version=version, updated_at=now(), deleted=False))
        db.flush()
        return p

    def access(db, token, roles, write=False):
        if write:
            lock_company(db, Company, token.get('cid'))
        c, u = env['resolve_company_user'](token, db)
        if verified_action(u) and (c.settings or {}).get("modules",{}).get("tickets"):return c,u
        manager = u.role in {'admin', 'company_admin', 'superuser'}
        modules = u.modules or {}
        granted = set(modules.get('ticketRoles', []))
        if not (c.settings or {}).get('modules', {}).get('tickets') or (
            not manager and (not modules.get('tickets') or not (granted & (set(roles) | {'manager'})))
        ):
            raise HTTPException(403, 'Droit insuffisant pour cette opération')
        return c, u

    def is_manager(u):
        return u.role in {'admin', 'company_admin', 'superuser'} or 'manager' in (u.modules or {}).get('ticketRoles', [])

    def stamp(u):
        return {'createdBy': u.id, 'createdByName': u.name, 'agency': u.agency, 'createdAt': now().isoformat()}

    def audit(db, c, u, action, details):
        put(db, c.id, 'audit', {**stamp(u), 'action': action, 'details': details, 'at': now().isoformat(), 'user': u.name})

    def fingerprint(req):
        return hashlib.sha256(json.dumps(req.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def retry(db, c, u, kind, req):
        row = db.get(Entity, {'company_id': c.id, 'entity_type': kind, 'entity_id': req.id})
        if row:
            if row.payload.get('createdBy') != u.id or row.payload.get('requestHash') != fingerprint(req):
                raise HTTPException(409, 'Cette référence correspond à une autre opération')
            return dict(row.payload)

    def available_bus(db, cid, bus_id, start, end, exclude=''):
        bus = get(db, cid, 'ticket_buses', bus_id)
        if bus.get('active') is False or bus.get('status') in {'En panne', 'Maintenance', 'Indisponible'}:
            raise HTTPException(409, 'Bus indisponible')
        for t in rows(db, cid, 'ticket_trips'):
            if t.get('busId') != bus_id or t.get('id') == exclude or t.get('status') in {'Annulé', 'Terminé', 'Clôturé', 'Arrivé'}:
                continue
            a = legacy_trip_time(t['departureAt'])
            # Historical departures without an end keep a conservative four-hour window.
            b = legacy_trip_time(t['expectedArrivalAt']) if t.get('expectedArrivalAt') else a + timedelta(minutes=int(t.get('durationMinutes') or 240))
            if start < b and a < end:
                raise HTTPException(409, 'Ce bus est déjà affecté à un départ sur ce créneau')
        for t in rows(db, cid, 'charters'):
            if t.get('busId') == bus_id and t['status'] == 'Confirmé' and start < parse_time(t['endsAt']) and parse_time(t['startsAt']) < end:
                raise HTTPException(409, 'Ce bus est déjà affecté à un voyage privé sur ce créneau')
        return bus

    env['check_vehicle_availability'] = available_bus

    @app.get('/api/v2/extensions/state')
    def state(token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'sales', 'dispatch', 'reports'})
        manager = is_manager(u)
        roles = set((u.modules or {}).get('ticketRoles', []))
        result = {'preferences': {'stageNotifications': bool((c.settings or {}).get('stageNotifications'))}}
        if manager or 'dispatch' in roles:
            movements = rows(db, c.id, 'stock_movements')
            items = []
            for item in rows(db, c.id, 'stock_items'):
                quantity = round(sum(float(m['quantity']) * (1 if m['direction'] == 'Entrée' else -1)
                                     for m in movements if m['itemId'] == item['id']), 6)
                items.append({**item, 'quantity': quantity, 'lowStock': quantity <= item['minimum']})
            result.update(stockItems=items, stockMovements=movements, schedules=rows(db, c.id, 'recurring_schedules'))
        if manager or roles & {'dispatch', 'sales', 'reports'}:
            result['charters'] = rows(db, c.id, 'charters')
            result['parkingSlots'] = rows(db, c.id, 'parking_slots')
        if manager or roles & {'dispatch', 'sales'}:
            result['parking'] = rows(db, c.id, 'parking')
        if manager or 'reports' in roles:
            result['charterPayments'] = rows(db, c.id, 'charter_payments')
            result['outbox'] = rows(db, c.id, 'stage_outbox')
        return result

    @app.post('/api/v2/extensions/stock/items')
    def stock_item(req: StockItem, token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'dispatch'}, True)
        previous = retry(db, c, u, 'stock_items', req)
        if previous:
            return previous
        if any(i['sku'].strip().casefold() == req.sku.strip().casefold() for i in rows(db, c.id, 'stock_items')):
            raise HTTPException(409, 'Cette référence de pièce existe déjà')
        item = put(db, c.id, 'stock_items', {**req.model_dump(), **stamp(u), 'requestHash': fingerprint(req)})
        audit(db, c, u, 'Pièce créée', req.sku)
        db.commit()
        return item

    @app.post('/api/v2/extensions/stock/movements')
    def movement(req: StockMovement, token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'dispatch'}, True)
        previous = retry(db, c, u, 'stock_movements', req)
        if previous:
            return previous
        item = get(db, c.id, 'stock_items', req.itemId)
        if req.busId:
            get(db, c.id, 'ticket_buses', req.busId)
        if req.tripId:
            trip = get(db, c.id, 'ticket_trips', req.tripId)
            if not req.busId or trip.get('busId') != req.busId:
                raise HTTPException(422, 'Le voyage doit correspondre au bus de la sortie')
        quantity = sum(float(m['quantity']) * (1 if m['direction'] == 'Entrée' else -1)
                       for m in rows(db, c.id, 'stock_movements') if m['itemId'] == req.itemId)
        if req.direction == 'Sortie' and (not req.busId or req.quantity > quantity + 1e-9):
            raise HTTPException(409, 'Sortie impossible : bus requis et stock disponible suffisant')
        result = put(db, c.id, 'stock_movements', {**req.model_dump(), **stamp(u), 'requestHash': fingerprint(req), 'itemName': item['name']})
        if req.direction == 'Entrée' and req.unitCost:
            put(db, c.id, 'expenses', {'id': 'stock-' + req.id, **stamp(u), 'amount': round(req.unitCost * req.quantity, 2),
                'category': 'Achat de pièces', 'label': item['name'], 'description': req.reason, 'paymentMethod': req.paymentMethod, 'stockMovementId': req.id})
        if req.direction == 'Sortie':
            put(db, c.id, 'fleet_events', {'id': 'stock-' + req.id, **stamp(u), 'busId': req.busId, 'tripId': req.tripId,
                'kind': 'Pièce détachée', 'label': item['name'] + ' · ' + req.reason, 'quantity': req.quantity,
                'amount': 0, 'stockMovementId': req.id})
        audit(db, c, u, 'Mouvement de stock', req.id)
        db.commit()
        return result

    @app.post('/api/v2/extensions/schedules')
    def schedule(req: Schedule, token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'dispatch'}, True)
        previous = retry(db, c, u, 'recurring_schedules', req)
        if previous:
            return previous
        try:
            start = datetime.strptime(req.start, '%Y-%m-%d').date()
            end = datetime.strptime(req.end, '%Y-%m-%d').date()
        except ValueError:
            raise HTTPException(422, 'Dates au format AAAA-MM-JJ requises') from None
        if not 0 <= (end - start).days <= 90 or any(d not in range(7) for d in req.weekdays):
            raise HTTPException(422, 'Période maximale : 90 jours ; jours de 0 (lundi) à 6 (dimanche)')
        template = get(db, c.id, 'ticket_trips', req.templateTripId)
        original = legacy_trip_time(template['departureAt'])
        trip_ids = []
        for delta in range((end - start).days + 1):
            day = start + timedelta(days=delta)
            if day.weekday() not in req.weekdays:
                continue
            departure = original.replace(year=day.year, month=day.month, day=day.day)
            if departure <= now():
                raise HTTPException(422, 'Tous les départs doivent être futurs')
            arrival = departure + timedelta(minutes=req.durationMinutes)
            available_bus(db, c.id, template['busId'], departure, arrival)
            ident = str(uuid.uuid5(uuid.NAMESPACE_URL, c.id + ':' + req.id + ':' + day.isoformat()))
            allowed = ('routeId', 'busId', 'origin', 'destination', 'stops', 'boardingPoint', 'dropPoint',
                       'fareSimple', 'fareVip', 'fareChildSimple', 'fareChildVip', 'cargoCapacityKg', 'cargoCapacityCount')
            trip = {k: template[k] for k in allowed if k in template}
            put(db, c.id, 'ticket_trips', {**trip, **stamp(u), 'id': ident, 'departureAt': departure.isoformat(),
                'expectedArrivalAt': arrival.isoformat(), 'durationMinutes': req.durationMinutes,
                'status': 'Planifié', 'scheduleId': req.id})
            trip_ids.append(ident)
        if not trip_ids:
            raise HTTPException(422, 'Aucun jour sélectionné dans cette période')
        result = put(db, c.id, 'recurring_schedules', {**req.model_dump(), **stamp(u), 'tripIds': trip_ids, 'requestHash': fingerprint(req)})
        audit(db, c, u, 'Calendrier récurrent créé', req.id)
        db.commit()
        return result

    @app.post('/api/v2/extensions/charters')
    def charter(req: Charter, token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'dispatch'}, True)
        previous = retry(db, c, u, 'charters', req)
        if previous:
            return previous
        start, end = parse_time(req.startsAt), parse_time(req.endsAt)
        if start <= now() or end <= start or req.deposit > req.amount:
            raise HTTPException(422, 'Vérifiez les dates et l’acompte du voyage privé')
        available_bus(db, c.id, req.busId, start, end)
        result = put(db, c.id, 'charters', {**req.model_dump(), **stamp(u), 'startsAt': start.isoformat(),
            'endsAt': end.isoformat(), 'paid': req.deposit, 'balance': round(req.amount - req.deposit, 2),
            'status': 'Confirmé', 'requestHash': fingerprint(req)})
        if req.deposit:
            put(db, c.id, 'charter_payments', {'id': 'deposit-' + req.id, **stamp(u), 'charterId': req.id,
                'amount': req.deposit, 'paymentMethod': req.paymentMethod})
        audit(db, c, u, 'Voyage privé confirmé', req.id)
        db.commit()
        return result

    @app.post('/api/v2/extensions/charters/{ident}/payments')
    def charter_payment(ident: str, req: CharterPayment, token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'sales', 'reports'}, True)
        previous = retry(db, c, u, 'charter_payments', req)
        if previous:
            if previous.get('charterId') != ident:
                raise HTTPException(409, 'Référence de règlement utilisée pour un autre voyage')
            return get(db, c.id, 'charters', ident)
        charter = get(db, c.id, 'charters', ident)
        if charter['status'] != 'Confirmé' or req.amount > charter['balance']:
            raise HTTPException(409, 'Voyage fermé ou règlement supérieur au solde')
        put(db, c.id, 'charter_payments', {**req.model_dump(), **stamp(u), 'charterId': ident, 'requestHash': fingerprint(req)})
        paid = round(charter['paid'] + req.amount, 2)
        result = put(db, c.id, 'charters', {**charter, 'paid': paid, 'balance': round(charter['amount'] - paid, 2)})
        audit(db, c, u, 'Règlement voyage privé', req.id)
        db.commit()
        return result

    @app.post('/api/v2/extensions/charters/{ident}/status')
    def charter_status(ident: str, req: CharterStatus, token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'manager'}, True)
        charter = get(db, c.id, 'charters', ident)
        if charter['status'] == req.status:
            return charter
        if charter['status'] != 'Confirmé':
            raise HTTPException(409, 'Ce voyage privé est déjà fermé')
        if req.status == 'Annulé' and charter['paid']:
            raise HTTPException(409, 'Un acompte est encaissé : régularisez le remboursement avant annulation')
        if req.status == 'Terminé' and (charter['balance'] or parse_time(charter['startsAt']) > now()):
            raise HTTPException(409, 'Le voyage doit avoir commencé et être entièrement réglé')
        result = put(db, c.id, 'charters', {**charter, 'status': req.status, 'closedAt': now().isoformat()})
        audit(db, c, u, 'Statut voyage privé', ident + ': ' + req.status)
        db.commit()
        return result

    @app.post('/api/v2/extensions/parking/slots')
    def slot(req: Slot, token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'manager'}, True)
        if any(s['label'].casefold() == req.label.strip().casefold() and s['id'] != req.id for s in rows(db, c.id, 'parking_slots')):
            raise HTTPException(409, 'Cet emplacement existe déjà')
        if any(p.get('slotId') == req.id and p['status'] == 'Déposé' for p in rows(db, c.id, 'parking')):
            raise HTTPException(409, 'Un véhicule occupe cet emplacement')
        result = put(db, c.id, 'parking_slots', {**req.model_dump(), 'label': req.label.strip(), **stamp(u)})
        audit(db, c, u, 'Emplacement parking configuré', req.label)
        db.commit()
        return result

    def check_parking_slot(db, c, payload):
        slots = [s for s in rows(db, c.id, 'parking_slots') if s.get('active')]
        if not slots and not payload.get('slotId'):
            return payload
        slot = next((s for s in slots if s['id'] == payload.get('slotId')), None)
        if not slot or slot['vehicleType'] != payload['vehicleType']:
            raise HTTPException(422, 'Choisissez un emplacement actif du bon type de véhicule')
        if any(p.get('slotId') == slot['id'] and p['status'] == 'Déposé' for p in rows(db, c.id, 'parking')):
            raise HTTPException(409, 'Cet emplacement est déjà occupé')
        return {**payload, 'slotLabel': slot['label'], 'rate': slot['rate'], 'pricing': slot['pricing']}

    env['check_parking_slot'] = check_parking_slot

    @app.put('/api/v2/extensions/preferences')
    def preferences(req: Preferences, token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'manager'}, True)
        c.settings = {**(c.settings or {}), **req.model_dump()}
        db.commit()
        return req.model_dump()

    def queue_trip_notifications(db, c, u, trip, event):
        if event['stage'] == 'Position' or not (c.settings or {}).get('stageNotifications'):
            return
        channels = [ch for ch in ('sms', 'whatsapp') if (c.settings or {}).get('features', {}).get(ch)]
        phones = {t.get('phone') for t in rows(db, c.id, 'tickets') if t.get('tripId') == trip['id'] and active(t) and t.get('phone')}
        for phone in phones:
            for channel in channels:
                ident = hashlib.sha256((event['id'] + ':' + channel + ':' + phone).encode()).hexdigest()
                put(db, c.id, 'stage_outbox', {'id': ident, **stamp(u), 'tripId': trip['id'], 'eventId': event['id'],
                    'channel': channel, 'to': phone, 'message': f"{c.name} : {trip['origin']} → {trip['destination']} · {event['stage']}. {event.get('message', '')}",
                    'status': 'En attente', 'attempts': 0})

    env['queue_trip_notifications'] = queue_trip_notifications

    @app.post('/api/v2/extensions/notifications/dispatch')
    def dispatch(token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'reports'}, True)
        jobs = [p for p in rows(db, c.id, 'stage_outbox') if p['status'] == 'En attente'][:10]
        # Commit a lease before contacting a provider. An uncertain send is never retried automatically.
        for job in jobs:
            put(db, c.id, 'stage_outbox', {**job, 'status': 'En cours', 'attempts': job['attempts'] + 1})
        db.commit()
        result = []
        for job in jobs:
            status, detail = 'Envoyé', ''
            try:
                env['send_notification'](env['NotificationSendRequest'](channel=job['channel'], to=job['to'],
                    message=job['message'], kind='trip-stage', reference=job['eventId']), token, db)
            except HTTPException as exc:
                status, detail = 'À vérifier', str(exc.detail)[:500]
            except Exception:
                status, detail = 'À vérifier', 'Réponse fournisseur inconnue ; contrôlez avant tout nouvel envoi'
                db.rollback()
            lock_company(db, Company, c.id)
            current = get(db, c.id, 'stage_outbox', job['id'])
            result.append(put(db, c.id, 'stage_outbox', {**current, 'status': status, 'detail': detail}))
            db.commit()
        return {'processed': len(result), 'jobs': result}

    @app.get('/api/v2/extensions/search')
    def search(origin: str, destination: str, date: str, token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'sales', 'dispatch', 'reports'})
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(422, 'Date invalide') from None
        allocations = [p for kind in ('tickets', 'ticket_reservations', 'ticket_holds') for p in rows(db, c.id, kind) if active(p)]
        results = []
        for trip in rows(db, c.id, 'ticket_trips'):
            if not trip.get('busId') or not str(trip.get('departureAt', '')).startswith(date) or legacy_trip_time(trip['departureAt']) <= now() or trip.get('status') not in {'Publié', 'Planifié', 'Opérations', 'Ouvert à la vente', 'Embarquement'}:
                continue
            stops = stops_for(trip)
            if origin not in stops or destination not in stops or stops.index(origin) >= stops.index(destination):
                continue
            bus = get(db, c.id, 'ticket_buses', trip['busId'])
            if bus.get('active') is False or bus.get('status') in {'Maintenance', 'En panne', 'Indisponible'}:
                continue
            route = next((r for r in rows(db, c.id, 'ticket_routes') if r['id'] == trip.get('routeId')), {})
            segment = {'boardingPoint': origin, 'dropPoint': destination}
            seats = []
            for seat in bus_seats(bus):
                occupied = any(a.get('tripId') == trip['id'] and str(a.get('seat')) == str(seat['label']) and overlap(trip, segment, a) for a in allocations)
                seats.append({'label': seat['label'], 'class': seat['class'], 'available': not occupied,
                    'fare': route_fare(route, trip, segment, seat['class'])})
            results.append({'id': trip['id'], 'origin': origin, 'destination': destination, 'departureAt': trip['departureAt'],
                'bus': bus.get('name'), 'available': sum(s['available'] for s in seats), 'seats': seats})
        return {'trips': sorted(results, key=lambda t: t['departureAt'])[:100]}

    @app.get('/api/v2/extensions/backup')
    def backup(token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, {'manager'})
        kinds = sorted({r.entity_type for r in db.scalars(select(Entity).where(Entity.company_id == c.id)).all()})
        # Company entities only; no authentication secrets or account password hashes.
        entities = {kind: rows(db, c.id, kind) for kind in kinds}
        for items in entities.values():
            for item in items:
                item.pop('requestHash', None)
                item.pop('tokenHash', None)
        return {'format': 'yamtrans-company-export', 'version': 1, 'exportedAt': now().isoformat(),
                'company': {'id': c.id, 'code': c.code, 'name': c.name}, 'entities': entities,
                'restore': 'Restauration administrateur sur une base de test avant remise en production'}
