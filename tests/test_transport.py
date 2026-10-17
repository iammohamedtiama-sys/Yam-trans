import importlib
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

DB_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + DB_DIR.name + "/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
m = importlib.import_module("app.main")
client = TestClient(m.app)


@pytest.fixture()
def setup():
    with m.SessionLocal() as db:
        db.execute(delete(m.EntityV3))
        company = db.scalar(m.select(m.Company).where(m.Company.code == "YAMTRANS"))
        company.settings = {**company.settings, "modules":{"courier":True,"baggage":True,"tickets":True}}
        user=db.scalar(m.select(m.AppUser).where(m.AppUser.company_id==company.id,m.AppUser.username=="admin"))
        headers={"Authorization":"Bearer "+m.make_token(user,company)}
        cid=company.id
        db.commit()
    departure=(datetime.now(timezone.utc)+timedelta(days=10)).isoformat()
    entities={"ticket_buses":[{"id":"bus","name":"Bus 1","registration":"BF-1","seats":[{"label":"A1","class":"Simple"},{"label":"A2","class":"VIP"}]}],"ticket_trips":[{"id":"trip","busId":"bus","origin":"Ouaga","destination":"Bobo","stops":"Boromo","departureAt":departure,"status":"Ouvert à la vente","fareSimple":5000,"fareVip":7000}],"shipments":[{"id":"courier","code":"OUA-001","origin":"Ouaga","destination":"Bobo","fee":1000,"createdAt":datetime.now(timezone.utc).isoformat()}]}
    r=client.post('/api/v2/sync',headers=headers,json={"deviceId":"test","entities":entities})
    assert r.status_code==200,r.text
    assert not r.json()['conflicts']
    return headers,cid,departure


def ticket(ident="ticket", **changes):
    return {"id":ident,"pnr":"PNR-"+ident,"tripId":"trip","passengerName":"Voyageur","phone":"+22670000001","seat":"A1","seatClass":"Simple","boardingPoint":"Ouaga","dropPoint":"Bobo","fare":5000,"paid":5000,"paymentMethod":"Espèces",**changes}


def post(headers,path,data):
    return client.post('/api/v2/transport'+path,headers=headers,json=data)


def test_health_and_existing_courier_are_preserved(setup):
    h,_,_=setup
    assert client.get('/health').status_code==200
    data=client.post('/api/v2/sync',headers=h,json={"deviceId":"test","entities":{}}).json()
    assert data['entities']['shipments'][0]['fee']==1000


def test_two_guichets_cannot_hold_same_segment(setup):
    h,_,_=setup
    data={"tripId":"trip","seat":"A1","boardingPoint":"Ouaga","dropPoint":"Bobo","deviceId":"one"}
    assert post(h,'/holds',data).status_code==200
    assert post(h,'/holds',{**data,"deviceId":"two"}).status_code==409


def test_nonoverlapping_segments_can_be_sold(setup):
    h,_,_=setup
    assert post(h,'/tickets/confirm',{"ticket":ticket('one',dropPoint='Boromo')}).status_code==200
    assert post(h,'/tickets/confirm',{"ticket":ticket('two',boardingPoint='Boromo')}).status_code==200
    assert post(h,'/tickets/confirm',{"ticket":ticket('three')}).status_code==409


def test_booking_is_atomic_under_concurrency(setup):
    h,_,_=setup
    with ThreadPoolExecutor(max_workers=5) as pool:
        codes=list(pool.map(lambda n:post(h,'/tickets/confirm',{"ticket":ticket(str(n))}).status_code,range(5)))
    assert codes.count(200)==1,codes
    assert codes.count(409)==4,codes


def test_confirmation_retry_is_idempotent(setup):
    h,_,_=setup
    one=post(h,'/tickets/confirm',{"ticket":ticket()})
    two=post(h,'/tickets/confirm',{"ticket":ticket()})
    assert one.json()==two.json()


def test_hold_is_consumed_by_confirmation(setup):
    h,_,_=setup
    hold=post(h,'/holds',{"tripId":"trip","seat":"A1","boardingPoint":"Ouaga","dropPoint":"Bobo","deviceId":"one"}).json()
    assert post(h,'/tickets/confirm',{"ticket":ticket(),"holdId":hold['id']}).status_code==200
    assert client.get('/api/v2/transport/state',headers=h).json()['holds']==[]


def test_batch_is_atomic_if_one_seat_is_taken(setup):
    h,_,_=setup
    post(h,'/tickets/confirm',{"ticket":ticket('existing',seat='A2')})
    result=post(h,'/bookings/confirm',{"bookingId":"group","tickets":[ticket('group-one'),ticket('group-two',seat='A2')]})
    assert result.status_code==409,result.text
    data=client.post('/api/v2/sync',headers=h,json={"deviceId":"test","entities":{}}).json()['entities']['tickets']
    assert [t['id'] for t in data]==['existing']


def test_group_order_confirms_multiple_seats(setup):
    h,_,_=setup
    result=post(h,'/bookings/confirm',{"bookingId":"group","tickets":[ticket('group-one'),ticket('group-two',seat='A2')]})
    assert result.status_code==200,result.text
    assert len(result.json()['tickets'])==2
    assert {t['bookingGroupId'] for t in result.json()['tickets']}=={'group'}


def test_offline_ticket_is_confirmed_on_sync(setup):
    h,_,_=setup
    data=client.post('/api/v2/sync',headers=h,json={"deviceId":"offline","entities":{"tickets":[ticket(status='À synchroniser',confirmationSource='offline')]}}).json()
    assert not data['conflicts']
    assert data['entities']['tickets'][0]['status']=='Confirmé'
    assert data['entities']['tickets'][0]['confirmationSource']=='server'


def test_refund_cannot_be_undone_by_sync(setup):
    h,_,_=setup
    post(h,'/tickets/confirm',{"ticket":ticket()})
    t=post(h,'/tickets/ticket/refund',{"amount":5000,"reason":"Annulation client"}).json()['ticket']
    r=client.post('/api/v2/sync',headers=h,json={"deviceId":"test","entities":{"tickets":[{**t,"status":"Confirmé"}]}}).json()
    assert r['conflicts'][0]['type']=='refund_protected'
    assert r['entities']['tickets'][0]['status']=='Remboursé'


def test_unconverted_deposit_is_in_cash_overview(setup):
    h,_,_=setup
    data={"id":"reservation","tripId":"trip","seat":"A1","passengerName":"Client","phone":"70000002","amount":5000,"deposit":2000,"expiresAt":(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()}
    assert post(h,'/reservations',data).status_code==200
    overview=client.get('/api/v2/transport/trips/trip/overview',headers=h).json()
    assert overview['expectedCash']==2000
    assert overview['depositIncome']==2000
    assert post(h,'/tickets/confirm',{"reservationId":"reservation","ticket":ticket(paid=5000)}).status_code==200
    overview=client.get('/api/v2/transport/trips/trip/overview',headers=h).json()
    assert overview['expectedCash']==5000
    assert overview['depositIncome']==0


@pytest.mark.parametrize('change',[{"seat":"ZZ"},{"boardingPoint":"Bobo","dropPoint":"Ouaga"},{"boardingPoint":"Unknown"},{"paid":6000},{"paid":-1}])
def test_invalid_booking_is_rejected(setup,change):
    h,_,_=setup
    assert post(h,'/tickets/confirm',{"ticket":ticket(**change)}).status_code==422


def test_legacy_sync_cannot_bypass_seat_guard(setup):
    h,_,_=setup
    assert post(h,'/tickets/confirm',{"ticket":ticket()}).status_code==200
    r=client.post('/api/v2/sync',headers=h,json={"deviceId":"offline","entities":{"tickets":[ticket('other')]}})
    assert r.status_code==200
    assert r.json()['conflicts'][0]['type']=='seat_conflict'
    assert len(r.json()['entities']['tickets'])==1


def test_expired_reservation_releases_seat(setup):
    h,_,_=setup
    r=post(h,'/reservations',{"id":"reservation","tripId":"trip","seat":"A1","passengerName":"Client","phone":"70000002","amount":5000,"expiresAt":(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()})
    assert r.status_code==200,r.text
    assert post(h,'/tickets/confirm',{"ticket":ticket()}).status_code==409
    with m.SessionLocal() as db:
        row=db.scalar(m.select(m.EntityV3).where(m.EntityV3.entity_id=='reservation'))
        row.payload={**row.payload,"expiresAt":(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()};db.commit()
    assert post(h,'/tickets/confirm',{"ticket":ticket()}).status_code==200


def test_reservation_conversion_preserves_deposit(setup):
    h,_,_=setup
    r=post(h,'/reservations',{"id":"reservation","tripId":"trip","seat":"A1","passengerName":"Client","phone":"70000002","amount":5000,"deposit":2000,"boardingPoint":"Ouaga","dropPoint":"Bobo","expiresAt":(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()})
    assert r.status_code==200,r.text
    assert post(h,'/tickets/confirm',{"reservationId":"reservation","ticket":ticket(paid=1000)}).status_code==422
    assert post(h,'/tickets/confirm',{"reservationId":"reservation","ticket":ticket()}).status_code==200
    data=client.post('/api/v2/sync',headers=h,json={"deviceId":"test","entities":{}}).json()['entities']
    assert data['ticket_reservations'][0]['status']=='Convertie'
    assert len(data['tickets'])==1


def test_refund_keeps_receipt_and_releases_seat(setup):
    h,_,_=setup
    post(h,'/tickets/confirm',{"ticket":ticket()})
    r=post(h,'/tickets/ticket/refund',{"amount":4000,"reason":"Annulation client"})
    assert r.status_code==200,r.text
    assert r.json()['ticket']['paid']==5000
    assert post(h,'/tickets/ticket/refund',{"amount":4000,"reason":"Nouvelle demande"}).status_code==409
    assert post(h,'/tickets/confirm',{"ticket":ticket('next')}).status_code==200
    data=client.get('/api/v2/transport/trips/trip/overview',headers=h).json()
    assert data['ticketIncome']==10000 and data['refunds']==4000 and data['net']==6000


def test_bus_change_refuses_missing_seats_and_preserves_tickets(setup):
    h,_,_=setup
    post(h,'/tickets/confirm',{"ticket":ticket()})
    client.post('/api/v2/sync',headers=h,json={"deviceId":"test","entities":{"ticket_buses":[{"id":"small","seats":[{"label":"B1","class":"Simple"}]},{"id":"replacement","name":"Bus 2","seats":[{"label":"A1","class":"Simple"}]}]}})
    assert post(h,'/trips/trip/bus',{"busId":"small","reason":"Panne du bus"}).status_code==409
    r=post(h,'/trips/trip/bus',{"busId":"replacement","reason":"Panne du bus"})
    assert r.status_code==200,r.text
    assert r.json()['tickets'][0]['seat']=='A1'
    assert r.json()['tickets'][0]['tripId']=='trip'


def test_recurrence_does_not_copy_departure_state(setup):
    h,_,_=setup
    date=(datetime.now(timezone.utc)+timedelta(days=20)).date().isoformat()
    one=post(h,'/trips/trip/repeat',{"dates":[date]})
    two=post(h,'/trips/trip/repeat',{"dates":[date]})
    assert one.status_code==200,one.text
    assert one.json()['trips'][0]['id']==two.json()['trips'][0]['id']
    assert 'baggageManifestArrivedAt' not in one.json()['trips'][0]


def test_baggage_warnings_and_capacity(setup):
    h,_,_=setup
    post(h,'/tickets/confirm',{"ticket":ticket()})
    client.post('/api/v2/sync',headers=h,json={"deviceId":"test","entities":{"ticket_baggage":[{"id":"bag","code":"BAG-1","ticketId":"ticket","tripId":"trip","weight":30,"count":2,"paid":1000,"status":"Enregistré"}]}})
    assert client.put('/api/v2/transport/trips/trip/capacity',headers=h,json={"cargoCapacityKg":20,"cargoCapacityCount":1}).status_code==200
    data=client.get('/api/v2/transport/trips/trip/overview',headers=h).json()
    assert {w['kind'] for w in data['warnings']}=={'owner_not_boarded','not_loaded','capacity'}
    assert data['net']==6000


def test_expense_and_closure(setup):
    h,_,_=setup
    post(h,'/tickets/confirm',{"ticket":ticket()})
    assert post(h,'/trips/trip/expenses',{"amount":500,"reason":"Péage route"}).status_code==200
    r=post(h,'/trips/trip/closure',{"countedCash":4400,"note":"Écart à vérifier"})
    assert r.status_code==200,r.text
    assert r.json()['difference']==-100
    assert post(h,'/trips/trip/closure',{"countedCash":4400}).status_code==409


def test_courier_manifest_joins_trip_and_finances(setup):
    h,_,_=setup
    client.post('/api/v2/sync',headers=h,json={"deviceId":"test","entities":{"manifests":[{"id":"manifest","code":"MAN-1","origin":"Ouaga","destination":"Bobo","shipmentIds":["courier"]}]}})
    r=post(h,'/trips/trip/manifests',{"manifestId":"manifest"})
    assert r.status_code==200,r.text
    assert r.json()['shipments'][0]['tripId']=='trip'
    assert r.json()['shipments'][0]['fee']==1000
    data=client.get('/api/v2/transport/trips/trip/overview',headers=h).json()
    assert data['courierIncome']==1000
    assert data['expectedCash']==1000
    assert data['net']==1000


def test_boarding_update_after_departure_preserves_existing_ticket(setup):
    h,cid,_=setup
    t=post(h,'/tickets/confirm',{"ticket":ticket()}).json()['ticket']
    with m.SessionLocal() as db:
        row=db.get(m.EntityV3,{"company_id":cid,"entity_type":"ticket_trips","entity_id":"trip"})
        row.payload={**row.payload,"departureAt":(m.utcnow()-timedelta(hours=6)).isoformat(),"status":"Parti"};db.commit()
    result=client.post('/api/v2/sync',headers=h,json={"deviceId":"test","entities":{"tickets":[{**t,"boarded":True}]}}).json()
    assert not result['conflicts']
    assert result['entities']['tickets'][0]['boarded'] is True


def test_waitlist_deduplicates_and_closes(setup):
    h,_,_=setup
    data={"tripId":"trip","passengerName":"Client","phone":"70000003"}
    one=post(h,'/waitlist',data).json();two=post(h,'/waitlist',data).json()
    assert one['id']==two['id']
    assert post(h,'/waitlist/'+one['id']+'/close',{}).json()['status']=='Traitée'


def test_company_isolation_and_role_check(setup):
    h,cid,_=setup
    with m.SessionLocal() as db:
        other=m.Company(id='other',code='OTHER',name='Other',phone='',logo_url='',active=True,settings={"modules":{"tickets":True}},created_at=m.utcnow());db.add(other)
        user=m.AppUser(id='other-user',company_id='other',username='other',name='Other',password_hash='unused',role='company_admin',agency='Toutes',active=True,modules={},created_at=m.utcnow());db.add(user)
        own=db.scalar(m.select(m.AppUser).where(m.AppUser.company_id==cid,m.AppUser.username=='ouaga'))
        own.modules={"tickets":True,"ticketRoles":["sales"]}
        db.commit()
        h2={"Authorization":"Bearer "+m.make_token(user,other)}
        hs={"Authorization":"Bearer "+m.make_token(own,db.get(m.Company,cid))}
    assert client.get('/api/v2/transport/trips/trip/overview',headers=h2).status_code==404
    assert post(hs,'/trips/trip/closure',{"countedCash":0}).status_code==403
    with m.SessionLocal() as db:
        db.delete(db.get(m.AppUser,'other-user'));db.delete(db.get(m.Company,'other'));db.commit()
