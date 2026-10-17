"""End-to-end sale/document/boarding invariants using the real API and database."""
import base64
from io import BytesIO
from datetime import datetime, timezone, timedelta
from PIL import Image
from test_transport import client, m, setup, ticket, post, ops, user_headers


def document(**changes):
    out=BytesIO();Image.new('RGB',(60,40),'white').save(out,format='PNG')
    return {'kind':'CNIB','number':' B 12345 ','photo':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode(),**changes}


def today_trip(cid):
    with m.SessionLocal() as db:
        row=db.get(m.EntityV3,{'company_id':cid,'entity_type':'ticket_trips','entity_id':'trip'})
        row.payload={**row.payload,'departureAt':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()};db.commit()


def test_photo_at_sale_links_document_and_ticket_atomically(setup):
    h,cid,_=setup
    req={'ticket':ticket(documentNumber='B12345'),'document':document()}
    r=post(h,'/tickets/confirm',req);assert r.status_code==200,r.text
    t=r.json()['ticket'];assert t['customerId']
    assert 'photo' not in t and 'documentPhoto' not in t
    lookup=ops(h,'/documents/lookup?number=B12345',method='GET').json()
    assert lookup['photo']==req['document']['photo']
    assert lookup['tickets'][0]['id']==t['id']
    assert post(h,'/tickets/confirm',req).json()==r.json()
    with m.SessionLocal() as db:
        docs=db.scalars(m.select(m.EntityV3).where(m.EntityV3.company_id==cid,m.EntityV3.entity_type=='customer_documents')).all()
        assert len(docs)==1


def test_invalid_or_conflicting_piece_does_not_sell_seat(setup):
    h,_,_=setup
    for doc in (document(photo='data:image/png;base64,bm90YW5pbWFnZQ=='),document(expiresOn='2000-01-01'),document(number='OTHER')):
        r=post(h,'/tickets/confirm',{'ticket':ticket(documentNumber='B12345'),'document':doc})
        assert r.status_code==422,r.text
    assert ops(h,'/documents/lookup?number=B12345',method='GET').status_code==404
    assert post(h,'/tickets/confirm',{'ticket':ticket(documentNumber='B12345'),'document':document()}).status_code==200
    assert post(h,'/tickets/confirm',{'ticket':ticket('other',seat='A2',fare=7000,paid=7000,documentNumber='B12345',passengerName='Other'),'document':document()}).status_code==409


def test_piece_can_replace_ticket_and_cannot_board_twice_or_wrong_trip(setup):
    h,cid,_=setup;today_trip(cid)
    assert post(h,'/tickets/confirm',{'ticket':ticket(documentNumber='B12345'),'document':document()}).status_code==200
    assert post(h,'/tickets/ticket/board',{'tripId':'other','documentNumber':'B12345'}).status_code==409
    assert post(h,'/tickets/ticket/board',{'tripId':'trip','documentNumber':'OTHER'}).status_code==403
    r=post(h,'/tickets/ticket/board',{'tripId':'trip','documentNumber':'B12345'})
    assert r.status_code==200,r.text
    assert r.json()['ticket']['boarded'] is True
    assert r.json()['boarding']['method']=='document'
    assert post(h,'/tickets/ticket/board',{'tripId':'trip','documentNumber':'B12345'}).json()['alreadyBoarded'] is True
    with m.SessionLocal() as db:
        boardings=db.scalars(m.select(m.EntityV3).where(m.EntityV3.company_id==cid,m.EntityV3.entity_type=='ticket_boardings')).all()
        assert len(boardings)==1


def test_wrong_day_and_unpaid_ticket_are_blocked(setup):
    h,cid,_=setup
    assert post(h,'/tickets/confirm',{'ticket':ticket(paid=1000)}).status_code==200
    assert post(h,'/tickets/ticket/board',{'tripId':'trip'}).status_code==409
    today_trip(cid)
    r=post(h,'/tickets/ticket/board',{'tripId':'trip'});assert r.status_code==409 and 'solde' in r.text.lower()


def test_document_sale_rollback_when_pack_invalid(setup):
    h,cid,_=setup
    r=post(h,'/tickets/confirm',{'ticket':ticket(documentNumber='B12345',packId='missing',paid=0),'document':document()})
    assert r.status_code==404,r.text
    assert ops(h,'/documents/lookup?number=B12345',method='GET').status_code==404
    with m.SessionLocal() as db:
        assert not db.scalars(m.select(m.EntityV3).where(m.EntityV3.company_id==cid,m.EntityV3.entity_type=='customer_documents')).all()


def test_only_authorized_boarding_account_can_validate(setup):
    h,cid,_=setup;today_trip(cid)
    post(h,'/tickets/confirm',{'ticket':ticket()})
    seller=user_headers(cid,'seller-board-test',['sales'])
    controller=user_headers(cid,'controller-board-test',['boarding'])
    assert post(seller,'/tickets/ticket/board',{'tripId':'trip'}).status_code==403
    assert post(controller,'/tickets/ticket/board',{'tripId':'trip'}).status_code==200


def test_account_edit_changes_password_roles_and_can_deactivate(setup):
    import uuid
    h,cid,_=setup
    username='edit-'+uuid.uuid4().hex[:10]
    r=client.post('/api/v2/admin/users',headers=h,json={'name':'Before','username':username,'password':'before123','role':'agency','agency':'Ouaga','modules':{'tickets':True,'ticketRoles':['sales']}})
    assert r.status_code==200,r.text
    ident=r.json()['id']
    r=client.put('/api/v2/admin/users/'+ident,headers=h,json={'name':'After','newPassword':'after123','modules':{'tickets':True,'ticketRoles':['boarding','driver']}})
    assert r.status_code==200,r.text
    login=client.post('/api/v2/auth/login',json={'company':'YAMTRANS','username':username,'password':'after123'})
    assert login.status_code==200,login.text
    assert login.json()['user']['name']=='After'
    assert set(login.json()['user']['modules']['ticketRoles'])=={'boarding','driver'}
    assert client.post('/api/v2/auth/login',json={'company':'YAMTRANS','username':username,'password':'before123'}).status_code==401
    assert client.put('/api/v2/admin/users/'+ident,headers=h,json={'active':False}).status_code==200
    assert client.get('/api/v2/admin/bootstrap',headers={'Authorization':'Bearer '+login.json()['token']}).status_code==401
    assert client.post('/api/v2/auth/login',json={'company':'YAMTRANS','username':username,'password':'after123'}).status_code==401

