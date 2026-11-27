from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor

from test_transport import client, m, setup, ticket, post, ops, user_headers, identity_photo


def ready_trip(cid):
    with m.SessionLocal() as db:
        row=db.get(m.EntityV3,{'company_id':cid,'entity_type':'ticket_trips','entity_id':'trip'})
        row.payload={**row.payload,'departureAt':(m.utcnow()-timedelta(minutes=10)).isoformat(),'expectedArrivalAt':(m.utcnow()+timedelta(hours=2)).isoformat(),'status':'Parti'}
        db.commit()


def create_device(h):
    r=client.post('/api/v2/gps/devices',headers=h,json={'busId':'bus','label':'Boîtier 1','externalId':'TEST-49'})
    assert r.status_code==200,r.text
    return r.json()


def frame(**changes):
    return {'id':'frame-1','recordedAt':m.utcnow().isoformat(),'latitude':12.3,'longitude':-1.5,'accuracy':5,'speedKph':45,**changes}


def ingest(d,p):return client.post('/api/v2/gps/positions',headers={'Authorization':'Bearer '+d['token']},json=p)


def test_document_prefix_and_photo_are_enforced_at_registration_and_sale(setup):
    h,_,_=setup
    for kind,wrong,right in [('CNIB','A12345','B12345'),('Passeport','B12345','A12345')]:
        req={'id':'d'+kind,'customerName':'Client','phone':'70000001','kind':kind,'number':wrong,'photo':identity_photo()}
        assert ops(h,'/documents',req).status_code==422
        assert ops(h,'/documents',{**req,'number':right,'photo':''}).status_code==422
        assert post(h,'/tickets/confirm',{'ticket':ticket(documentNumber=wrong),'document':{'kind':kind,'number':wrong,'photo':identity_photo()}}).status_code==422
    assert post(h,'/tickets/confirm',{'ticket':ticket(documentNumber='B12345'),'document':{'kind':'CNIB','number':'B12345','photo':''}}).status_code==422
    assert post(h,'/tickets/confirm',{'ticket':ticket(documentNumber='B12345')}).status_code==422


def test_passport_photo_replaces_qr_and_duplicate_scan_does_not_board_twice(setup):
    h,cid,_=setup
    assert post(h,'/tickets/confirm',{'ticket':ticket(documentNumber='A12345'),'document':{'kind':'Passeport','number':'A12345','photo':identity_photo()}}).status_code==200
    ready_trip(cid)
    found=ops(h,'/documents/lookup?number=A12345',method='GET')
    assert found.status_code==200 and found.json()['photo']
    request={'tripId':'trip','documentNumber':'A12345'}
    assert post(h,'/tickets/ticket/board',request).json()['alreadyBoarded'] is False
    assert post(h,'/tickets/ticket/board',request).json()['alreadyBoarded'] is True


def test_group_documents_are_atomic_and_a_wrong_passport_rolls_back_every_seat(setup):
    h,_,_=setup
    tickets=[ticket('one',documentNumber='B12345'),ticket('two',documentNumber='A12345',seat='A2',fare=7000,paid=7000)]
    documents={'one':{'kind':'CNIB','number':'B12345','photo':identity_photo()},'two':{'kind':'Passeport','number':'B12345','photo':identity_photo()}}
    req={'bookingId':'group','tickets':tickets,'documents':documents}
    assert post(h,'/bookings/confirm',req).status_code==422
    assert ops(h,'/documents/lookup?number=B12345',method='GET').status_code==404
    documents['two']['number']='A12345'
    assert post(h,'/bookings/confirm',req).status_code==200
    assert len(post(h,'/bookings/confirm',req).json()['tickets'])==2


def test_partial_payment_is_idempotent_and_enables_boarding(setup):
    h,cid,_=setup
    assert post(h,'/tickets/confirm',{'ticket':ticket(paid=1000)}).status_code==200
    ready_trip(cid)
    assert post(h,'/tickets/ticket/board',{'tripId':'trip'}).status_code==409
    req={'id':'payment','amount':4000,'paymentMethod':'Espèces'}
    first=post(h,'/tickets/ticket/payments',req)
    assert first.status_code==200,first.text
    assert first.json()['ticket']['balance']==0
    assert post(h,'/tickets/ticket/payments',req).json()==first.json()
    assert post(h,'/tickets/ticket/payments',{**req,'amount':3000}).status_code==409
    assert post(h,'/tickets/ticket/board',{'tripId':'trip'}).status_code==200


def test_simultaneous_balance_payments_cannot_overcharge(setup):
    h,_,_=setup;post(h,'/tickets/confirm',{'ticket':ticket(paid=1000)})
    with ThreadPoolExecutor(max_workers=4) as pool:
        codes=list(pool.map(lambda i:post(h,'/tickets/ticket/payments',{'id':str(i),'amount':4000}).status_code,range(4)))
    assert codes.count(200)==1 and codes.count(422)==3


def test_sync_cannot_forge_price_payment_or_boarding(setup):
    h,_,_=setup;t=post(h,'/tickets/confirm',{'ticket':ticket(paid=1000)}).json()['ticket']
    for change in [{'fare':1},{'paid':5000,'balance':0},{'boarded':True},{'documentNumber':'B12345'}]:
        r=client.post('/api/v2/sync',headers=h,json={'deviceId':'fake','entities':{'tickets':[{**t,**change}]}}).json()
        assert r['conflicts'][0]['type']=='ticket_server_required'


def test_gps_secret_is_only_returned_on_create_and_manager_rotation(setup):
    h,_,_=setup;d=create_device(h)
    listed=client.get('/api/v2/gps/devices',headers=h)
    assert d['token'] not in listed.text and 'tokenHash' not in listed.text
    assert client.get('/api/v2/gps/fleet',headers=h).status_code==200
    assert ingest({'token':'invalid'},frame()).status_code==401
    rotated=client.post('/api/v2/gps/devices/'+d['device']['id']+'/rotate',headers=h,json={})
    assert rotated.status_code==200
    assert ingest(d,frame()).status_code==401
    assert ingest(rotated.json(),frame()).status_code==200


def test_gps_device_auth_cannot_use_staff_or_another_bus(setup):
    h,cid,_=setup;d=create_device(h)
    assert client.post('/api/v2/gps/positions',headers=h,json=frame()).status_code==401
    seller=user_headers(cid,'gps-sales',['sales'])
    assert client.get('/api/v2/gps/fleet',headers=seller).status_code==403
    assert client.post('/api/v2/gps/devices',headers=seller,json={'busId':'bus','label':'bad'}).status_code==403
    assert ingest(d,frame(tripId='other')).status_code==422


def test_gps_frame_is_idempotent_and_tracks_current_trip(setup):
    h,cid,_=setup;ready_trip(cid);d=create_device(h);p=frame()
    first=ingest(d,p);assert first.status_code==200,first.text
    assert first.json()['tripId']=='trip'
    assert ingest(d,p).json()['duplicate'] is True
    assert ingest(d,{**p,'latitude':13}).status_code==409
    fleet=client.get('/api/v2/gps/fleet',headers=h).json()
    assert fleet['buses'][0]['position']['source']=='device'
    assert fleet['buses'][0]['position']['speedKph']==45


def test_gps_old_frames_cannot_rewind_fleet_or_public_tracking(setup):
    h,cid,_=setup;ready_trip(cid);d=create_device(h)
    latest=frame(id='new',latitude=13)
    assert ingest(d,latest).status_code==200
    assert ingest(d,frame(id='old',recordedAt=(m.utcnow()-timedelta(minutes=20)).isoformat(),latitude=10)).status_code==200
    assert client.get('/api/v2/gps/fleet',headers=h).json()['buses'][0]['position']['latitude']==13
    share=ops(h,'/trips/trip/share',{}).json()['url'].split('/')[-1]
    public=client.get('/api/v2/public/voyage/'+share)
    assert public.json()['position']['latitude']==13
    assert public.json()['position']['createdAt']==latest['recordedAt']
    page=client.get('/voyage/'+share)
    assert 'openstreetmap.org/export/embed.html' in page.text
    assert d['token'] not in public.text and 'passengerName' not in public.text


def test_gps_rejects_bad_coordinates_future_and_expired_frames(setup):
    h,_,_=setup;d=create_device(h)
    for p in [frame(latitude=91),frame(longitude=181),frame(speedKph=-1),frame(recordedAt=(m.utcnow()+timedelta(hours=1)).isoformat()),frame(recordedAt=(m.utcnow()-timedelta(days=8)).isoformat())]:
        assert ingest(d,p).status_code==422


def test_revoked_device_and_disabled_company_stop_ingestion(setup):
    h,cid,_=setup;d=create_device(h)
    assert client.put('/api/v2/gps/devices/'+d['device']['id'],headers=h,json={'active':False}).status_code==200
    assert ingest(d,frame()).status_code==403
    assert client.put('/api/v2/gps/devices/'+d['device']['id'],headers=h,json={'active':True}).status_code==200
    with m.SessionLocal() as db:
        c=db.get(m.Company,cid);c.active=False;db.commit()
    assert ingest(d,frame()).status_code==403
    with m.SessionLocal() as db:
        c=db.get(m.Company,cid);c.active=True;db.commit()


def test_driver_only_sees_their_assigned_vehicles(setup):
    h,cid,_=setup;driver=user_headers(cid,'gps-driver',['driver'])
    assert client.get('/api/v2/gps/fleet',headers=driver).json()['buses']==[]
    assert ops(h,'/trips/trip/crew',{'driverId':'gps-driver'},'PUT').status_code==200
    assert len(client.get('/api/v2/gps/fleet',headers=driver).json()['buses'])==1
    assert client.get('/api/v2/gps/devices',headers=driver).status_code==403


def test_complete_export_does_not_expose_tracker_secret_or_hash(setup):
    h,_,_=setup;d=create_device(h)
    backup=client.get('/api/v2/extensions/backup',headers=h)
    assert d['token'] not in backup.text and 'tokenHash' not in backup.text


def test_real_tesseract_reads_a_synthetic_document_number(setup):
    import base64, shutil
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont
    import pytest
    if not shutil.which('tesseract'):pytest.skip('Tesseract not installed')
    h,_,_=setup
    image=Image.new('RGB',(1400,700),'white');draw=ImageDraw.Draw(image);font=ImageFont.truetype('DejaVuSans.ttf',52)
    draw.text((60,80),'CARTE NATIONALE IDENTITE',fill='black',font=font);draw.text((60,230),'CNIB B12345678',fill='black',font=font)
    out=BytesIO();image.save(out,format='PNG')
    result=ops(h,'/documents/ocr',{'image':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()})
    assert result.status_code==200,result.text
    assert 'B12345678' in result.json()['text']
