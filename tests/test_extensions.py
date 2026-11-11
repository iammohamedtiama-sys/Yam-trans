from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from test_transport import client, m, setup, ticket, post, user_headers


def ext(h, path, data=None, method='POST'):
    return client.request(method, '/api/v2/extensions' + path, headers=h, json=data)


def item(h):
    req = {'id': 'part', 'sku': 'FILTRE', 'name': 'Filtre huile', 'minimum': 2}
    assert ext(h, '/stock/items', req).status_code == 200
    return req


def movement(**changes):
    return {'id': 'incoming', 'itemId': 'part', 'direction': 'Entrée', 'quantity': 5,
            'unitCost': 1000, 'reason': 'Achat fournisseur', **changes}


def charter_request(departure, **changes):
    start = datetime.fromisoformat(departure) + timedelta(days=2)
    return {'id': 'private', 'customerName': 'Organisation', 'phone': '+22670000001', 'busId': 'bus',
            'origin': 'Ouaga', 'destination': 'Koudougou', 'startsAt': start.isoformat(),
            'endsAt': (start + timedelta(hours=6)).isoformat(), 'amount': 100000, 'deposit': 20000, **changes}


def test_stock_retry_is_bound_to_request_and_cash_is_not_duplicated(setup):
    h, _, _ = setup
    req = item(h)
    assert ext(h, '/stock/items', req).status_code == 200
    assert ext(h, '/stock/items', {**req, 'name': 'Other'}).status_code == 409
    assert ext(h, '/stock/items', {**req, 'id': 'other', 'sku': ' filtre '}).status_code == 409
    for _ in range(2):
        assert ext(h, '/stock/movements', movement()).status_code == 200
    assert ext(h, '/stock/movements', movement(quantity=8)).status_code == 409
    assert ext(h, '/stock/movements', movement(id='out', direction='Sortie', quantity=3, busId='bus')).status_code == 200
    state = ext(h, '/state', method='GET').json()
    assert state['stockItems'][0]['quantity'] == 2
    assert state['stockItems'][0]['lowStock']
    with m.SessionLocal() as db:
        expenses = db.scalars(m.select(m.EntityV3).where(m.EntityV3.entity_type == 'expenses')).all()
        assert len(expenses) == 1 and expenses[0].payload['amount'] == 5000


def test_concurrent_stock_withdrawals_cannot_make_stock_negative(setup):
    h, _, _ = setup
    item(h)
    ext(h, '/stock/movements', movement(quantity=1))
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(lambda i: ext(h, '/stock/movements', movement(
            id='out-' + str(i), direction='Sortie', quantity=1, busId='bus')).status_code, range(4)))
    assert codes.count(200) == 1
    assert codes.count(409) == 3
    assert ext(h, '/state', method='GET').json()['stockItems'][0]['quantity'] == 0


def test_stock_requires_valid_bus_and_matching_trip(setup):
    h, _, _ = setup
    item(h)
    assert ext(h, '/stock/movements', movement(direction='Sortie')).status_code == 409
    assert ext(h, '/stock/movements', movement(busId='missing')).status_code == 404
    assert ext(h, '/stock/movements', movement(tripId='trip')).status_code == 422
    assert ext(h, '/stock/movements', movement(quantity=-1)).status_code == 422


def test_sales_role_cannot_write_stock_or_download_backup(setup):
    h, cid, _ = setup
    sales = user_headers(cid, 'sales-ext', ['sales'])
    assert ext(sales, '/stock/items', {'id': 'p', 'sku': 'P', 'name': 'P'}).status_code == 403
    assert ext(sales, '/backup', method='GET').status_code == 403
    state = ext(sales, '/state', method='GET').json()
    assert 'stockItems' not in state and 'outbox' not in state
    driver = user_headers(cid, 'driver-ext', ['driver'])
    assert ext(driver, '/state', method='GET').status_code == 403


def test_private_types_cannot_be_forged_via_legacy_sync(setup):
    h, _, _ = setup
    result = client.post('/api/v2/sync', headers=h, json={'deviceId': 'test', 'entities': {
        'stock_movements': [movement()], 'charters': [{'id': 'forged'}], 'parking_slots': [{'id': 'forged'}]}})
    assert result.status_code == 200
    assert ext(h, '/state', method='GET').json()['charters'] == []
    assert ext(h, '/state', method='GET').json()['stockMovements'] == []


def test_recurring_calendar_respects_weekdays_and_is_idempotent(setup):
    h, _, departure = setup
    start = datetime.fromisoformat(departure).date() + timedelta(days=1)
    req = {'id': 'calendar', 'templateTripId': 'trip', 'start': start.isoformat(),
           'end': (start + timedelta(days=6)).isoformat(), 'weekdays': [0, 2, 4], 'durationMinutes': 180}
    one = ext(h, '/schedules', req)
    assert one.status_code == 200, one.text
    assert len(one.json()['tripIds']) == 3
    assert ext(h, '/schedules', req).json() == one.json()
    synced = client.post('/api/v2/sync', headers=h, json={'entities': {}, 'deviceId': 'test'}).json()
    assert len(synced['entities']['ticket_trips']) == 4


def test_conflicting_calendar_rolls_back_every_new_departure(setup):
    h, cid, departure = setup
    day = datetime.fromisoformat(departure).date()
    # First day is free, second day collides with the existing departure.
    req = {'id': 'calendar', 'templateTripId': 'trip', 'start': (day - timedelta(days=1)).isoformat(),
           'end': day.isoformat(), 'weekdays': list(range(7)), 'durationMinutes': 180}
    assert ext(h, '/schedules', req).status_code == 409
    with m.SessionLocal() as db:
        trips = db.scalars(m.select(m.EntityV3).where(m.EntityV3.company_id == cid, m.EntityV3.entity_type == 'ticket_trips')).all()
        assert len(trips) == 1
    assert ext(h, '/state', method='GET').json()['schedules'] == []


def test_calendar_rejects_invalid_days_and_long_period(setup):
    h, _, departure = setup
    day = datetime.fromisoformat(departure).date()
    req = {'id': 'calendar', 'templateTripId': 'trip', 'start': day.isoformat(),
           'end': (day + timedelta(days=100)).isoformat(), 'weekdays': [9], 'durationMinutes': 180}
    assert ext(h, '/schedules', req).status_code == 422


def test_charter_deposit_payments_and_request_bound_retry(setup):
    h, _, departure = setup
    req = charter_request(departure)
    one = ext(h, '/charters', req)
    assert one.status_code == 200, one.text
    assert one.json()['balance'] == 80000
    assert ext(h, '/charters', req).json() == one.json()
    assert ext(h, '/charters', {**req, 'amount': 90000}).status_code == 409
    payment = {'id': 'pay', 'amount': 50000}
    for _ in range(2):
        paid = ext(h, '/charters/private/payments', payment)
        assert paid.status_code == 200, paid.text
        assert paid.json()['balance'] == 30000
    assert ext(h, '/charters/private/payments', {'id': 'more', 'amount': 40000}).status_code == 409
    assert len(ext(h, '/state', method='GET').json()['charterPayments']) == 2


def test_charter_bus_collision_checks_regular_and_private_trips(setup):
    h, _, departure = setup
    req = charter_request(departure)
    assert ext(h, '/charters', {**req, 'startsAt': departure}).status_code == 409
    assert ext(h, '/charters', req).status_code == 200
    assert ext(h, '/charters', {**req, 'id': 'other'}).status_code == 409
    assert ext(h, '/charters', {**req, 'id': 'naive', 'startsAt': req['startsAt'][:19]}).status_code == 422


def test_sync_cannot_schedule_a_bus_during_a_charter(setup):
    h, _, departure = setup
    req = charter_request(departure)
    assert ext(h, '/charters', req).status_code == 200
    result = client.post('/api/v2/sync', headers=h, json={'deviceId': 'test', 'entities': {'ticket_trips': [{
        'id': 'conflicting', 'busId': 'bus', 'origin': 'Ouaga', 'destination': 'Bobo',
        'departureAt': req['startsAt'], 'status': 'Planifié'}]}}).json()
    assert result['conflicts'][0]['type'] == 'vehicle_conflict'
    assert not any(t['id'] == 'conflicting' for t in result['entities']['ticket_trips'])


def test_charter_cannot_be_closed_before_departure_or_cancelled_with_deposit(setup):
    h, _, departure = setup
    ext(h, '/charters', charter_request(departure))
    assert ext(h, '/charters/private/status', {'status': 'Annulé'}).status_code == 409
    assert ext(h, '/charters/private/status', {'status': 'Terminé'}).status_code == 409


def test_cancel_unpaid_charter_releases_bus(setup):
    h, _, departure = setup
    req = charter_request(departure, deposit=0)
    ext(h, '/charters', req)
    assert ext(h, '/charters/private/status', {'status': 'Annulé'}).status_code == 200
    assert ext(h, '/charters', {**req, 'id': 'replacement'}).status_code == 200


def test_parking_slot_price_and_occupancy_are_server_controlled(setup):
    h, _, _ = setup
    slot = {'id': 's1', 'label': 'A1', 'vehicleType': 'Moto', 'rate': 500, 'pricing': 'jour'}
    assert ext(h, '/parking/slots', slot).status_code == 200
    req = {'id': 'parking', 'slotId': 's1', 'registration': 'BF-1', 'vehicleType': 'Moto',
           'customerName': 'Client', 'phone': '70000000', 'condition': 'Bon état', 'rate': 1, 'pricing': 'forfait'}
    r = client.post('/api/v2/operations/parking', headers=h, json=req)
    assert r.status_code == 200, r.text
    assert r.json()['rate'] == 500 and r.json()['pricing'] == 'jour'
    assert client.post('/api/v2/operations/parking', headers=h, json={**req, 'id': 'second', 'registration': 'BF-2'}).status_code == 409
    assert ext(h, '/parking/slots', {**slot, 'rate': 200}).status_code == 409
    assert client.post('/api/v2/operations/parking/parking/release', headers=h, json={'paid': 500, 'condition': 'Identique'}).status_code == 200
    assert client.post('/api/v2/operations/parking', headers=h, json={**req, 'id': 'second', 'registration': 'BF-2'}).status_code == 200


def enable_messages(h, cid):
    with m.SessionLocal() as db:
        c = db.get(m.Company, cid)
        c.settings = {**c.settings, 'features': {'sms': True}}
        db.commit()
    assert ext(h, '/preferences', {'stageNotifications': True}, 'PUT').status_code == 200
    assert post(h, '/tickets/confirm', {'ticket': ticket()}).status_code == 200


def test_trip_notifications_are_once_per_event_and_no_positions(setup, monkeypatch):
    h, cid, _ = setup
    enable_messages(h, cid)
    req = {'id': 'event', 'stage': 'Parti', 'message': 'Bon voyage'}
    for _ in range(2):
        assert client.post('/api/v2/operations/trips/trip/tracking', headers=h, json=req).status_code == 200
    client.post('/api/v2/operations/trips/trip/tracking', headers=h, json={'id': 'gps', 'stage': 'Position', 'latitude': 12, 'longitude': -1})
    assert len(ext(h, '/state', method='GET').json()['outbox']) == 1
    calls = []
    monkeypatch.setattr(m, 'send_notification', lambda req, token, db: calls.append(req))
    assert ext(h, '/notifications/dispatch', {}).json()['processed'] == 1
    assert ext(h, '/notifications/dispatch', {}).json()['processed'] == 0
    assert len(calls) == 1


def test_uncertain_provider_response_is_not_retried_automatically(setup, monkeypatch):
    h, cid, _ = setup
    enable_messages(h, cid)
    client.post('/api/v2/operations/trips/trip/tracking', headers=h, json={'id': 'event', 'stage': 'Approche'})
    calls = []
    def failure(req, token, db):
        calls.append(req)
        raise TimeoutError()
    monkeypatch.setattr(m, 'send_notification', failure)
    result = ext(h, '/notifications/dispatch', {}).json()
    assert result['jobs'][0]['status'] == 'À vérifier'
    assert ext(h, '/notifications/dispatch', {}).json()['processed'] == 0
    assert len(calls) == 1


def test_server_search_counts_segment_seats_without_exposing_passenger(setup):
    h, _, departure = setup
    assert post(h, '/tickets/confirm', {'ticket': ticket(dropPoint='Boromo')}).status_code == 200
    date = departure[:10]
    result = ext(h, f'/search?origin=Boromo&destination=Bobo&date={date}', method='GET')
    assert result.status_code == 200, result.text
    assert result.json()['trips'][0]['available'] == 2
    assert 'Voyageur' not in result.text and '+226' not in result.text
    busy = ext(h, f'/search?origin=Ouaga&destination=Bobo&date={date}', method='GET').json()
    assert busy['trips'][0]['available'] == 1


def test_backup_includes_new_business_records_and_excludes_auth_secrets(setup):
    h, cid, departure = setup
    item(h)
    ext(h, '/charters', charter_request(departure))
    with m.SessionLocal() as db:
        db.add(m.EntityV3(company_id='other', entity_type='stock_items', entity_id='private',
                         payload={'id': 'private', 'name': 'OTHER-COMPANY'}, version=1, updated_at=m.utcnow(), deleted=False))
        db.commit()
    result = ext(h, '/backup', method='GET')
    assert result.status_code == 200
    assert len(result.json()['entities']['stock_items']) == 1
    assert len(result.json()['entities']['charters']) == 1
    assert 'OTHER-COMPANY' not in result.text and 'password_hash' not in result.text
    assert 'requestHash' not in result.text


def test_old_guichet_datetime_local_departures_remain_compatible(setup):
    h, _, departure = setup
    naive = (datetime.fromisoformat(departure) + timedelta(days=1)).replace(tzinfo=None).isoformat(timespec='minutes')
    result = client.post('/api/v2/sync', headers=h, json={'deviceId': 'legacy', 'entities': {'ticket_trips': [{
        'id': 'legacy', 'busId': 'bus', 'origin': 'Ouaga', 'destination': 'Bobo', 'departureAt': naive,
        'status': 'Publié', 'fareSimple': 5000, 'fareVip': 7000}]}}).json()
    assert not result['conflicts']
    found = ext(h, '/search?origin=Ouaga&destination=Bobo&date=' + naive[:10], method='GET')
    assert found.status_code == 200 and found.json()['trips'][0]['id'] == 'legacy'
