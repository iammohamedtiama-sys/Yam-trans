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
    post(h,'/tickets/confirm',{"ticket":ticket('existing',seat='A2',fare=7000,paid=7000)})
    result=post(h,'/bookings/confirm',{"bookingId":"group","tickets":[ticket('group-one'),ticket('group-two',seat='A2',fare=7000,paid=7000)]})
    assert result.status_code==409,result.text
    data=client.post('/api/v2/sync',headers=h,json={"deviceId":"test","entities":{}}).json()['entities']['tickets']
    assert [t['id'] for t in data]==['existing']


def test_group_order_confirms_multiple_seats(setup):
    h,_,_=setup
    result=post(h,'/bookings/confirm',{"bookingId":"group","tickets":[ticket('group-one'),ticket('group-two',seat='A2',fare=7000,paid=7000)]})
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

# 4.8 regression cases exercise retries, finance, private data and shared workflows.
def ops(h,path,data=None,method='POST'):
    return client.request(method,'/api/v2/operations'+path,headers=h,json=data)


def configure_route(cid):
    with m.SessionLocal() as db:
        tr=db.get(m.EntityV3,{'company_id':cid,'entity_type':'ticket_trips','entity_id':'trip'})
        tr.payload={**tr.payload,'routeId':'route'}
        db.add(m.EntityV3(company_id=cid,entity_type='ticket_routes',entity_id='route',payload={'id':'route','origin':'Ouaga','destination':'Bobo','fareSimple':5000,'fareVip':7000,'fareChildSimple':2500,'fareChildVip':4000},version=1,updated_at=m.utcnow(),deleted=False));db.commit()


def test_courier_retry_discards_associated_cash_and_persists_alias(setup):
    h,cid,_=setup
    created=datetime.now(timezone.utc).isoformat()
    original={'id':'original','clientOperationId':'key-1','createdBy':'agent','code':'OUA-100','senderName':'Client','senderPhone':'70000001','receiverName':'Dest','receiverPhone':'70000002','origin':'Ouaga','destination':'Bobo','type':'Colis','fee':1000,'paid':1000,'createdAt':created}
    def sync(entities):return client.post('/api/v2/sync',headers=h,json={'deviceId':'terminal','entities':entities})
    assert not sync({'shipments':[original],'payments':[{'id':'p1','shipmentId':'original','amount':1000}]}).json()['conflicts']
    retry={**original,'id':'duplicate','code':'OUA-101','createdAt':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
    r=sync({'shipments':[retry],'payments':[{'id':'p2','shipmentId':'duplicate','amount':1000}]}).json()
    assert set(r['rejectedDuplicateIds'])=={'duplicate','p2'}
    assert r['duplicateMap']['duplicate']=='original'
    assert {p['id'] for p in r['entities']['payments']}=={'p1'}
    later=sync({'payments':[{'id':'p3','shipmentId':'duplicate','amount':1000}]}).json()
    assert later['rejectedDuplicateIds']==['p3']
    assert len(later['entities']['payments'])==1
    assert not any(k in later['entities'] for k in ('operation_aliases','customer_documents'))


def test_reusing_operation_key_with_different_amount_is_rejected(setup):
    h,_,_=setup
    p={'id':'one','clientOperationId':'stable','createdBy':'agent','code':'ONE','fee':1000}
    assert client.post('/api/v2/sync',headers=h,json={'deviceId':'test','entities':{'shipments':[p]}}).status_code==200
    assert client.post('/api/v2/sync',headers=h,json={'deviceId':'test','entities':{'shipments':[{**p,'id':'two','fee':2000}]}}).status_code==409


def test_central_tariff_rejects_modified_price_and_supports_child(setup):
    h,cid,_=setup;configure_route(cid)
    assert post(h,'/tickets/confirm',{'ticket':ticket(fare=4000,paid=4000)}).status_code==422
    child=post(h,'/tickets/confirm',{'ticket':ticket(fare=2500,paid=2500,passengerCategory='child',assistance='Déficience visuelle')})
    assert child.status_code==200,child.text
    assert child.json()['ticket']['seatClass']=='Simple'
    assert child.json()['ticket']['fare']==2500


def test_sync_cannot_bypass_central_tariff(setup):
    h,cid,_=setup;configure_route(cid)
    r=client.post('/api/v2/sync',headers=h,json={'deviceId':'test','entities':{'tickets':[ticket(fare=5,paid=5)]}}).json()
    assert r['conflicts'] and not r['entities']['tickets']


def test_parking_is_idempotent_and_separate_from_transport(setup):
    h,_,_=setup
    p={'id':'parking','registration':'BF-123','vehicleType':'Moto','customerName':'Client','phone':'70000000','condition':'Rayure gauche','rate':500,'pricing':'jour'}
    one=ops(h,'/parking',p);two=ops(h,'/parking',p)
    assert one.status_code==200,one.text
    assert one.json()==two.json()
    assert ops(h,'/parking',{**p,'id':'another'}).status_code==409
    assert ops(h,'/parking/parking/release',{'paid':200,'condition':'Identique'}).status_code==422
    release=ops(h,'/parking/parking/release',{'paid':500,'condition':'Identique'})
    assert release.status_code==200,release.text
    assert ops(h,'/parking/parking/release',{'paid':500,'condition':'Identique'}).json()==release.json()
    report=ops(h,'/analysis',method='GET').json()
    assert report['parkingIncome']==500
    assert report['trips'][0]['income']==0


def test_fleet_retry_creates_one_expense_in_profitability(setup):
    h,_,_=setup
    p={'id':'fuel','busId':'bus','tripId':'trip','kind':'Carburant','label':'Gasoil','amount':10000,'quantity':15}
    assert ops(h,'/fleet',p).status_code==200
    assert ops(h,'/fleet',p).status_code==200
    report=ops(h,'/analysis',method='GET').json()
    assert report['trips'][0]['expenses']==10000
    assert report['trips'][0]['net']==-10000
    assert len(report['suggestions'])==1


def test_public_tracking_has_real_timestamp_and_no_passenger_data(setup):
    h,_,_=setup
    post(h,'/tickets/confirm',{'ticket':ticket(documentNumber='SECRET-ID')})
    share=ops(h,'/trips/trip/share',{}).json();token=share['url'].split('/')[-1]
    event=ops(h,'/trips/trip/tracking',{'id':'position','stage':'Position','latitude':12.3,'longitude':-1.5,'accuracy':20})
    assert event.status_code==200,event.text
    data=client.get('/api/v2/public/voyage/'+token)
    assert data.status_code==200
    assert data.json()['position']['latitude']==12.3
    assert data.json()['position']['createdAt']
    assert 'SECRET-ID' not in data.text and 'Voyageur' not in data.text and '70000001' not in data.text
    assert client.get('/voyage/'+token).status_code==200
    assert ops(h,'/shares/'+share['id'],method='DELETE').status_code==200
    assert client.get('/api/v2/public/voyage/'+token).status_code==404


def test_tracking_rejects_incomplete_or_fake_coordinates(setup):
    h,_,_=setup
    assert ops(h,'/trips/trip/tracking',{'id':'gps','stage':'Position'}).status_code==422
    assert ops(h,'/trips/trip/tracking',{'id':'gps','stage':'Position','latitude':12.3}).status_code==422
    assert ops(h,'/trips/trip/tracking',{'id':'gps','stage':'Position','latitude':200,'longitude':0}).status_code==422


def test_identity_renewal_preserves_customer_and_no_public_document(setup):
    h,_,_=setup
    p={'id':'doc','customerId':'customer','customerName':'Client','phone':'70000001','kind':'CNIB','number':'B 1234'}
    assert ops(h,'/documents',p).status_code==200
    t=post(h,'/tickets/confirm',{'ticket':ticket(documentNumber='B1234')}).json()['ticket']
    assert t['customerId']=='customer'
    assert ops(h,'/documents',{**p,'id':'new','number':'A9999','kind':'Passeport','replacesId':'doc'}).status_code==200
    assert ops(h,'/documents/lookup?number=B1234',method='GET').status_code==404
    result=ops(h,'/documents/lookup?number=A9999',method='GET')
    assert result.status_code==200,result.text
    assert result.json()['tickets'][0]['id']==t['id']
    state=ops(h,'/state',method='GET')
    assert 'B1234' not in state.text and 'A9999' not in state.text


def test_prepaid_pack_redemption_atomic_and_retry_once(setup):
    h,cid,_=setup;configure_route(cid)
    p={'id':'pack','customerId':'customer','customerName':'Client','phone':'70000001','routeId':'route','journeys':10,'amount':45000,'expiresOn':(datetime.now(timezone.utc)+timedelta(days=90)).date().isoformat()}
    assert ops(h,'/packs',p).status_code==200
    assert ops(h,'/packs',p).status_code==200
    t=ticket(packId='pack',customerId='customer',paid=0)
    one=post(h,'/tickets/confirm',{'ticket':t});two=post(h,'/tickets/confirm',{'ticket':t})
    assert one.status_code==200,one.text
    assert one.json()==two.json()
    assert one.json()['ticket']['balance']==0
    state=ops(h,'/state',method='GET').json()
    assert state['travel_packs'][0]['remaining']==9
    report=ops(h,'/analysis',method='GET').json()
    assert report['prepaidIncome']==45000 and report['trips'][0]['cashIncome']==0
    assert report['trips'][0]['prepaidAllocated']==4500 and report['trips'][0]['income']==4500


def test_pack_cannot_be_redeemed_for_other_customer_or_sync(setup):
    h,cid,_=setup;configure_route(cid)
    p={'id':'pack','customerId':'customer','customerName':'Client','phone':'70000001','routeId':'route','journeys':10,'amount':45000,'expiresOn':(datetime.now(timezone.utc)+timedelta(days=90)).date().isoformat()}
    ops(h,'/packs',p)
    assert post(h,'/tickets/confirm',{'ticket':ticket(packId='pack',customerId='other',paid=0)}).status_code==422
    r=client.post('/api/v2/sync',headers=h,json={'deviceId':'test','entities':{'tickets':[ticket(packId='pack',customerId='customer',paid=0)]}}).json()
    assert r['conflicts'][0]['type']=='prepaid_online_required'


def test_transfer_preserves_cash_releases_original_seat_and_retries(setup):
    h,cid,departure=setup
    post(h,'/tickets/confirm',{'ticket':ticket()})
    r=client.post('/api/v2/sync',headers=h,json={'deviceId':'test','entities':{'ticket_trips':[{'id':'new-trip','busId':'bus','origin':'Ouaga','destination':'Bobo','departureAt':departure,'status':'Publié'}]}})
    assert r.status_code==200
    p={'id':'transfer','tripId':'new-trip','seat':'A1','reason':'Voyageur change de départ'}
    one=ops(h,'/tickets/ticket/transfer',p);two=ops(h,'/tickets/ticket/transfer',p)
    assert one.status_code==200,one.text
    assert one.json()==two.json()
    assert one.json()['paid']==5000
    assert len(one.json()['transfers'])==1
    assert post(h,'/tickets/confirm',{'ticket':ticket('next')}).status_code==200


def test_crew_assignment_rejects_free_text_or_unknown_account(setup):
    h,_,_=setup
    assert ops(h,'/trips/trip/crew',{'driverId':'John','conductorId':''},'PUT').status_code==422


def user_headers(cid, ident, roles):
    with m.SessionLocal() as db:
        user=db.get(m.AppUser,ident)
        if not user:
            user=m.AppUser(id=ident,company_id=cid,username=ident,name='Équipage test',password_hash=m.password_hash('not-used'),role='agency',agency='Ouaga',active=True,modules={'tickets':True,'ticketRoles':roles},created_at=m.utcnow());db.add(user)
        else:
            user.company_id=cid;user.active=True;user.modules={'tickets':True,'ticketRoles':roles}
        c=db.get(m.Company,cid);token=m.make_token(user,c);db.commit()
    return {'Authorization':'Bearer '+token}


def test_driver_cannot_read_identity_or_modify_another_trip(setup):
    h,cid,_=setup
    driver=user_headers(cid,'driver-test',['driver'])
    assert ops(driver,'/state',method='GET').status_code==200
    assert ops(driver,'/documents/lookup?number=B1234',method='GET').status_code==403
    assert ops(driver,'/trips/trip/tracking',{'id':'incident','stage':'Incident','message':'Embouteillage'}).status_code==403
    assert ops(h,'/trips/trip/crew',{'driverId':'driver-test','conductorId':''},'PUT').status_code==200
    assert ops(driver,'/trips/trip/tracking',{'id':'incident','stage':'Incident','message':'Embouteillage'}).status_code==200
    assert 'customer_documents' not in ops(driver,'/state',method='GET').json()


def test_sales_agent_cannot_change_tariff_or_take_discount(setup):
    h,cid,_=setup;configure_route(cid)
    sales=user_headers(cid,'sales-test',['sales'])
    assert post(sales,'/tickets/confirm',{'ticket':ticket(fare=4000,paid=4000,discount=1000)}).status_code==403
    r=client.post('/api/v2/sync',headers=sales,json={'deviceId':'test','entities':{'ticket_routes':[{'id':'route','fareSimple':1}]}})
    assert r.status_code==200
    assert r.json()['conflicts'][0]['type']=='tariff_protected'
    assert post(sales,'/tickets/confirm',{'ticket':ticket()}).status_code==200


def test_ocr_reads_local_image_and_rejects_non_images(setup):
    import base64,io
    from PIL import Image,ImageDraw,ImageFont
    h,_,_=setup
    image=Image.new('RGB',(1200,220),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',70)
    draw.text((35,55),'CNIB B12345678',font=font,fill='black')
    buffer=io.BytesIO();image.save(buffer,format='PNG')
    photo='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
    result=ops(h,'/documents/ocr',{'image':photo})
    assert result.status_code==200,result.text
    assert 'B12345678' in result.json()['text']
    assert result.json()['requiresConfirmation'] is True
    assert ops(h,'/documents/ocr',{'image':'data:image/png;base64,aGVsbG8='}).status_code==422
    doc={'id':'photo-doc','customerId':'client','customerName':'Client','phone':'70000000','kind':'CNIB','number':'B12345678','photo':photo}
    assert ops(h,'/documents',doc).status_code==200
    assert ops(h,'/documents/lookup?number=B12345678',method='GET').json()['photo']==photo
    assert photo not in ops(h,'/state',method='GET').text


def test_ai_missing_configuration_is_explicit_not_fake_analysis(setup,monkeypatch):
    h,_,_=setup
    monkeypatch.delenv('YAMTRANS_AI_API_KEY',raising=False);monkeypatch.delenv('YAMTRANS_AI_MODEL',raising=False)
    r=ops(h,'/analysis/ai',{})
    assert r.status_code==503 and 'configurés' in r.json()['detail']


def test_ai_sends_aggregates_without_customer_or_employee_identity(setup,monkeypatch):
    import json
    from app import analysis_ai
    h,_,_=setup
    post(h,'/tickets/confirm',{'ticket':ticket(passengerName='PRIVATE-NAME',documentNumber='PRIVATE-DOC')})
    monkeypatch.setenv('YAMTRANS_AI_API_KEY','test-key');monkeypatch.setenv('YAMTRANS_AI_MODEL','test-model')
    seen=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):return json.dumps({'choices':[{'message':{'content':'Vérifier les coûts saisis.'}}]}).encode()
    def fake(req,**kwargs):
        body=req.data.decode();assert 'PRIVATE-NAME' not in body and 'PRIVATE-DOC' not in body and '70000001' not in body
        seen.append(body);return Response()
    monkeypatch.setattr(analysis_ai.request,'urlopen',fake)
    result=ops(h,'/analysis/ai',{})
    assert result.status_code==200,result.text
    assert result.json()['model']=='test-model' and len(seen)==1


def test_cancelling_prepaid_ticket_restores_one_journey(setup):
    h,cid,_=setup;configure_route(cid)
    p={'id':'pack','customerId':'customer','customerName':'Client','phone':'70000001','routeId':'route','journeys':10,'amount':45000,'expiresOn':(datetime.now(timezone.utc)+timedelta(days=90)).date().isoformat()}
    ops(h,'/packs',p)
    post(h,'/tickets/confirm',{'ticket':ticket(packId='pack',customerId='customer',paid=0)})
    r=post(h,'/tickets/ticket/refund',{'amount':0,'reason':'Annulation du trajet prépayé'})
    assert r.status_code==200,r.text
    assert ops(h,'/state',method='GET').json()['travel_packs'][0]['remaining']==10
    assert post(h,'/tickets/ticket/refund',{'amount':0,'reason':'Même demande'}).status_code==409
    assert ops(h,'/state',method='GET').json()['travel_packs'][0]['remaining']==10


def test_concurrent_prepaid_sales_cannot_overdraw_last_journey(setup):
    h,cid,_=setup;configure_route(cid)
    p={'id':'pack','customerId':'customer','customerName':'Client','phone':'70000001','routeId':'route','journeys':1,'amount':4500,'expiresOn':(datetime.now(timezone.utc)+timedelta(days=90)).date().isoformat()}
    ops(h,'/packs',p)
    # Use two disjoint segments of the same Simple seat: allocation itself permits both.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda n:post(h,'/tickets/confirm',{'ticket':ticket(str(n),packId='pack',customerId='customer',paid=0,boardingPoint='Ouaga' if n==0 else 'Boromo',dropPoint='Boromo' if n==0 else 'Bobo')}).status_code,range(2)))
    assert sorted(results)==[200,409]
    assert ops(h,'/state',method='GET').json()['travel_packs'][0]['remaining']==0


def test_interrupted_confirmation_can_be_recovered_without_reissuing(setup):
    h,_,_=setup
    original=post(h,'/tickets/confirm',{'ticket':ticket()}).json()['ticket']
    recovered=client.get('/api/v2/transport/tickets/ticket',headers=h)
    assert recovered.status_code==200
    assert recovered.json()['ticket']==original
    assert client.get('/api/v2/transport/tickets/missing',headers=h).status_code==404


def test_profitability_uses_peak_seats_for_successive_segments(setup):
    h,_,_=setup
    assert post(h,'/tickets/confirm',{'ticket':ticket('first',dropPoint='Boromo')}).status_code==200
    assert post(h,'/tickets/confirm',{'ticket':ticket('second',boardingPoint='Boromo')}).status_code==200
    report=ops(h,'/analysis',method='GET').json()
    tr=report['trips'][0]
    assert tr['tickets']==2 and tr['peakPassengers']==1 and tr['capacity']==2
    assert tr['occupancyPct']==50
    assert len(report['agents'])==1 and report['agents'][0]['ticketCash']==10000


def test_central_tariff_also_protects_reservation_deposits(setup):
    h,cid,_=setup;configure_route(cid)
    data={"id":"reservation","tripId":"trip","seat":"A1","passengerName":"Client","phone":"70000002","amount":10000,"deposit":10000,"expiresAt":(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()}
    assert post(h,'/reservations',data).status_code==422
    assert post(h,'/reservations',{**data,'amount':5000,'deposit':2000}).status_code==200


def test_customer_identity_and_pack_can_be_created_without_internal_ids(setup):
    h,cid,_=setup;configure_route(cid)
    doc={'id':'d','customerName':'Client lisible','phone':'70000001','kind':'CNIB','number':'B88888'}
    created=ops(h,'/documents',doc)
    assert created.status_code==200,created.text
    customer_id=created.json()['customerId']
    p={'id':'pack','customerName':'Client lisible','phone':'+22670000001','routeId':'route','journeys':10,'amount':45000,'expiresOn':(datetime.now(timezone.utc)+timedelta(days=90)).date().isoformat()}
    pack=ops(h,'/packs',p)
    assert pack.status_code==200,pack.text
    assert pack.json()['customerId']==customer_id
    renewed=ops(h,'/documents',{**doc,'id':'renewed','number':'A77777','kind':'Passeport','previousNumber':'B88888','phone':'70000002'})
    assert renewed.status_code==200,renewed.text
    assert renewed.json()['customerId']==customer_id
    assert ops(h,'/documents/lookup?number=B88888',method='GET').status_code==404


def test_transfer_accepts_the_visible_pnr_instead_of_database_id(setup):
    h,cid,departure=setup
    post(h,'/tickets/confirm',{'ticket':ticket()})
    client.post('/api/v2/sync',headers=h,json={'deviceId':'test','entities':{'ticket_trips':[{'id':'new-trip','busId':'bus','origin':'Ouaga','destination':'Bobo','departureAt':departure,'status':'Publié'}]}})
    result=ops(h,'/tickets/PNR-ticket/transfer',{'id':'move','tripId':'new-trip','seat':'A1','reason':'Départ modifié'})
    assert result.status_code==200,result.text
    assert result.json()['id']=='ticket' and result.json()['tripId']=='new-trip'


def test_sales_cannot_bypass_fixed_tariffs_with_a_discounted_pack(setup):
    h,cid,_=setup;configure_route(cid)
    sales=user_headers(cid,'sales-test',['sales'])
    p={'id':'pack','customerName':'Client','phone':'70000001','routeId':'route','journeys':10,'amount':1,'expiresOn':(datetime.now(timezone.utc)+timedelta(days=90)).date().isoformat()}
    assert ops(sales,'/packs',p).status_code==403
    assert ops(sales,'/packs',{**p,'amount':50000}).status_code==200
