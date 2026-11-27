from concurrent.futures import ThreadPoolExecutor
from test_transport import client,m,setup,post,ticket
from app import yengapay
import pytest
from fastapi import HTTPException

def register(email='client@example.com'):
    r=client.post('/api/v2/passenger/register',json={'email':email,'password':'Strong-pass-123','name':'Client Voyageur','phone':'70000001'})
    assert r.status_code==200,r.text
    return {'Authorization':'Bearer '+r.json()['token']}

@pytest.fixture()
def payment(monkeypatch):
    monkeypatch.setattr(yengapay,'configured',lambda:True)
    monkeypatch.setattr(yengapay,'create',lambda ref,amount,title:{'id':'yp-'+ref,'checkoutPageUrlWithPaymentToken':'https://checkout.yengapay.com/pay/test'})
    monkeypatch.setattr(yengapay,'retrieve',lambda ident:{'id':ident,'reference':ident.removeprefix('yp-'),'paymentAmount':5000,'currency':'XOF','paymentStatus':'DONE'})

def booking(ident='client-order-0000001',**kwargs):return {'id':ident,'tripId':'trip','seat':'A1','boardingPoint':' OUAGA ','dropPoint':'bobo','passengerName':'Client Voyageur','phone':'70000001',**kwargs}

def test_server_price_and_concurrent_verifications(setup,payment):
    h=register();r=client.post('/api/v2/passenger/orders',headers=h,json={**booking(),'amount':1,'paid':5000})
    assert r.status_code==200,r.text
    assert r.json()['amount']==5000
    with ThreadPoolExecutor(max_workers=3) as pool:replies=list(pool.map(lambda _:client.post('/api/v2/passenger/orders/client-order-0000001/verify',headers=h),range(3)))
    assert all(r.status_code==200 for r in replies),[r.text for r in replies]
    assert len({r.json()['ticket']['id'] for r in replies})==1
    state=client.post('/api/v2/sync',headers=setup[0],json={'deviceId':'check','entities':{}}).json()['entities']
    assert len(state['tickets'])==1 and state['tickets'][0]['paymentMethod']=='YengaPay'
    assert not any(k.startswith('passenger_') for k in state)

def test_customer_isolation_and_private_backup(setup,payment):
    h=register();other=register('other@example.com');assert client.post('/api/v2/passenger/orders',headers=h,json=booking()).status_code==200
    assert client.post('/api/v2/passenger/orders/client-order-0000001/verify',headers=other).status_code==404
    assert client.get('/api/v2/passenger/orders',headers=other).json()['orders']==[]
    assert client.get('/api/v2/passenger/me',headers=setup[0]).status_code==401
    assert not any(k.startswith('passenger_') for k in client.get('/api/v2/extensions/backup',headers=setup[0]).json()['entities'])

def test_wrong_amount_never_issues_ticket(setup,payment,monkeypatch):
    h=register();client.post('/api/v2/passenger/orders',headers=h,json=booking())
    monkeypatch.setattr(yengapay,'retrieve',lambda _: {'id':'yp-client-order-0000001','reference':'client-order-0000001','paymentAmount':1,'status':'DONE'})
    assert client.post('/api/v2/passenger/orders/client-order-0000001/verify',headers=h).status_code==409
    assert 'ticket' not in client.get('/api/v2/passenger/orders',headers=h).json()['orders'][0]

def test_pending_and_idempotent_creation(setup,payment,monkeypatch):
    h=register();calls=[]
    monkeypatch.setattr(yengapay,'create',lambda ref,*args:calls.append(ref) or {'id':'yp-'+ref,'checkoutPageUrlWithPaymentToken':'https://checkout.yengapay.com/pay/test'})
    for _ in range(2):assert client.post('/api/v2/passenger/orders',headers=h,json=booking()).status_code==200
    assert len(calls)==1
    assert post(setup[0],'/holds',{'tripId':'trip','seat':'A1','deviceId':'counter'}).status_code==409
    monkeypatch.setattr(yengapay,'retrieve',lambda _: {'paymentStatus':'PENDING'})
    r=client.post('/api/v2/passenger/orders/client-order-0000001/verify',headers=h);assert r.status_code==200 and 'ticket' not in r.json()

def test_invalid_segment_and_seat(setup,payment):
    h=register()
    for change in ({'boardingPoint':'Paris'},{'boardingPoint':'Bobo','dropPoint':'Ouaga'},{'seat':'Z99'}):assert client.post('/api/v2/passenger/orders',headers=h,json=booking(**change)).status_code in (409,422)

def test_late_payment_never_oversells(setup,payment):
    h=register();client.post('/api/v2/passenger/orders',headers=h,json=booking())
    with m.SessionLocal() as db:
        r=db.get(m.EntityV3,{'company_id':setup[1],'entity_type':'ticket_holds','entity_id':'passenger-client-order-0000001'});r.payload={**r.payload,'expiresAt':'2000-01-01T00:00:00+00:00'};db.commit()
    assert post(setup[0],'/tickets/confirm',{'ticket':ticket()}).status_code==200
    r=client.post('/api/v2/passenger/orders/client-order-0000001/verify',headers=h)
    assert r.status_code==200,r.text
    assert r.json()['status']=='Paiement reçu · assistance requise' and 'ticket' not in r.json()

def test_logout_and_rate_limit(setup):
    h=register();assert client.post('/api/v2/passenger/logout',headers=h).status_code==200
    assert client.get('/api/v2/passenger/me',headers=h).status_code==401
    for _ in range(8):assert client.post('/api/v2/passenger/login',json={'email':'client@example.com','password':'wrong-password'}).status_code==401
    assert client.post('/api/v2/passenger/login',json={'email':'client@example.com','password':'Strong-pass-123'}).status_code==429

@pytest.mark.parametrize('change',[{'reference':'elsewhere'},{'id':'other'},{'paymentAmount':'NaN'},{'currency':'EUR'},{'paymentAmount':5000.01}])
def test_payment_validation(change):
    with pytest.raises(HTTPException):yengapay.verified_paid({'id':'one','reference':'ref','paymentAmount':5000,'status':'DONE',**change},{'intentId':'one','id':'ref','amount':5000})


def test_staff_can_review_and_verify_without_exposing_account_secrets(setup,payment):
    h=register();client.post('/api/v2/passenger/orders',headers=h,json=booking())
    assert client.get('/api/v2/passenger-admin/orders',headers=h).status_code==401
    reply=client.get('/api/v2/passenger-admin/orders',headers=setup[0])
    assert reply.status_code==200,reply.text
    assert len(reply.json()['orders'])==1
    assert not any(k in reply.text for k in ('passwordHash','salt','checkoutUrl'))
    verified=client.post('/api/v2/passenger-admin/orders/client-order-0000001/verify',headers=setup[0])
    assert verified.status_code==200,verified.text
    assert verified.json()['ticket']['paid']==5000
