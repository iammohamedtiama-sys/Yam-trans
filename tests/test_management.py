from datetime import timedelta
import uuid
import pytest
from test_transport import client,m,setup,ticket,post,user_headers,ops
from app.permissions import CATALOG,PROFILES,normalize


def call(h,path,data=None,method='POST'):
    return client.request(method,'/api/v2/management'+path,headers=h,json=data)


def employee(cid,profile='conductor',overrides=None):
    ident=uuid.uuid4().hex
    perms={k:k in PROFILES[profile]['actions'] for k in CATALOG};perms.update(overrides or {})
    with m.SessionLocal() as db:
        u=m.AppUser(id=ident,company_id=cid,username=ident,name=profile+' test',password_hash='not-a-password',role='agency',agency='Ouaga',active=True,created_at=m.utcnow(),modules=normalize({'tickets':True,'courier':True,'baggage':True,'profile':profile,'permissions':perms}))
        db.add(u);db.commit();c=db.get(m.Company,cid);h={'Authorization':'Bearer '+m.make_token(u,c)}
    return h,ident


def test_explicit_deny_blocks_direct_and_sync_writes_even_with_coarse_sales_role(setup):
    h,cid,_=setup;staff,ident=employee(cid,overrides={'tickets.sell':False,'courier.create':False})
    assert post(staff,'/tickets/confirm',{'ticket':ticket()}).status_code==403
    r=client.post('/api/v2/sync',headers=staff,json={'deviceId':'phone','entities':{'shipments':[{'id':'forge','code':'FORGE','origin':'Ouaga','destination':'Bobo','fee':1}]}})
    assert r.status_code==200 and r.json()['conflicts'][0]['type']=='action_forbidden'


def test_conductor_sales_require_assigned_trip_and_dont_grant_refund(setup):
    h,cid,_=setup;staff,ident=employee(cid)
    assert post(staff,'/tickets/confirm',{'ticket':ticket()}).status_code==403
    with m.SessionLocal() as db:
        tr=db.get(m.EntityV3,{'company_id':cid,'entity_type':'ticket_trips','entity_id':'trip'});tr.payload={**tr.payload,'conductorId':ident};db.commit()
    r=post(staff,'/tickets/confirm',{'ticket':ticket()});assert r.status_code==200,r.text
    assert post(staff,'/tickets/ticket/refund',{'amount':5000,'reason':'test'}).status_code==403
    assert call(staff,'/payroll',method='GET').status_code==403


def test_specific_grant_can_enable_gps_configuration_without_whole_manager_role(setup):
    h,cid,_=setup;staff,ident=employee(cid,'custom',{'gps.devices':True})
    r=client.post('/api/v2/gps/devices',headers=staff,json={'busId':'bus','label':'Test'});assert r.status_code==200,r.text
    assert call(staff,'/payroll',method='GET').status_code==403
    assert client.get('/api/v2/extensions/backup',headers=staff).status_code==403


def test_disabled_account_cannot_keep_using_action_grants(setup):
    h,cid,_=setup;staff,ident=employee(cid,'manager')
    with m.SessionLocal() as db:u=db.get(m.AppUser,ident);u.active=False;db.commit()
    assert call(staff,'/insights',method='GET').status_code==401


def test_payroll_is_server_calculated_approved_and_paid_exactly_once(setup):
    h,cid,_=setup;staff,ident=employee(cid,'driver')
    assert call(h,'/contracts',{'userId':ident,'monthlyBase':100000,'perTrip':5000},'PUT').status_code==200
    month=m.utcnow().strftime('%Y-%m')
    with m.SessionLocal() as db:
        tr=db.get(m.EntityV3,{'company_id':cid,'entity_type':'ticket_trips','entity_id':'trip'});tr.payload={**tr.payload,'driverId':ident,'departureAt':(m.utcnow()-timedelta(hours=5)).isoformat(),'status':'Arrivé','actualArrivalAt':m.utcnow().isoformat()};db.commit()
    data={'userId':ident,'month':month,'bonus':1000,'deduction':6000}
    r=call(h,'/payroll',data);assert r.status_code==200,r.text;p=r.json();assert p['net']==100000 and p['completedTrips']==1
    assert call(h,'/payroll',data).json()['id']==p['id']
    assert call(h,'/payroll',{**data,'bonus':2000}).status_code==409
    payment={'id':'payment-1','paymentMethod':'Espèces','reference':'recu-1'}
    assert call(h,'/payroll/'+p['id']+'/pay',payment).status_code==409
    assert call(h,'/payroll/'+p['id']+'/approve',{}).status_code==200
    assert call(h,'/payroll/'+p['id']+'/pay',payment).status_code==200
    assert call(h,'/payroll/'+p['id']+'/pay',payment).status_code==200
    assert call(h,'/payroll/'+p['id']+'/pay',{**payment,'id':'another'}).status_code==409
    with m.SessionLocal() as db:
        es=db.scalars(m.select(m.EntityV3).where(m.EntityV3.company_id==cid,m.EntityV3.entity_type=='expenses')).all();assert sum(e.payload.get('payrollId')==p['id'] for e in es)==1
    assert call(staff,'/payroll',method='GET').status_code==403


def test_payroll_separates_prepare_approve_and_payment_permissions(setup):
    h,cid,_=setup;staff,ident=employee(cid,'accountant',{'payroll.pay':False})
    assert call(staff,'/contracts',{'userId':ident,'monthlyBase':10000,'perTrip':0},'PUT').status_code==200
    p=call(staff,'/payroll',{'userId':ident,'month':'2026-11'}).json()
    assert call(staff,'/payroll/'+p['id']+'/approve',{}).status_code==403
    assert call(h,'/payroll/'+p['id']+'/approve',{}).status_code==200
    assert call(staff,'/payroll/'+p['id']+'/pay',{'id':'no'}).status_code==403


def test_cross_company_payroll_reference_is_rejected(setup):
    h,cid,_=setup
    assert call(h,'/contracts',{'userId':'not-in-company','monthlyBase':1,'perTrip':0},'PUT').status_code==422
    assert call(h,'/payroll/other/approve',{}).status_code==404


def test_assignment_rejects_overlap_and_logs_history(setup):
    h,cid,departure=setup;driver,ident=employee(cid,'driver');conv,conductor=employee(cid)
    assert ops(h,'/trips/trip/crew',{'driverId':ident,'conductorId':conductor},'PUT').status_code==200
    with m.SessionLocal() as db:
        tr=db.get(m.EntityV3,{'company_id':cid,'entity_type':'ticket_trips','entity_id':'trip'});p={**tr.payload,'id':'overlap','driverId':'','conductorId':''};db.add(m.EntityV3(company_id=cid,entity_type='ticket_trips',entity_id='overlap',payload=p,version=1,updated_at=m.utcnow(),deleted=False));db.commit()
    assert ops(h,'/trips/overlap/crew',{'driverId':ident,'conductorId':''},'PUT').status_code==409
    report=call(h,'/staff',method='GET').json();assert len(report['history'])==1;assert next(u for u in report['crew'] if u['id']==ident)['plannedTrips']==1


def test_suggestions_include_all_business_channels_and_indicative_route_costs(setup):
    h,cid,_=setup
    assert post(h,'/tickets/confirm',{'ticket':ticket()}).status_code==200
    with m.SessionLocal() as db:
        tr=db.get(m.EntityV3,{'company_id':cid,'entity_type':'ticket_trips','entity_id':'trip'});tr.payload={**tr.payload,'departureAt':(m.utcnow()-timedelta(hours=2)).isoformat()}
        db.add(m.EntityV3(company_id=cid,entity_type='expenses',entity_id='cost',payload={'id':'cost','tripId':'trip','amount':10000,'createdAt':m.utcnow().isoformat()},version=1,updated_at=m.utcnow(),deleted=False));db.commit()
    r=call(h,'/insights',method='GET');assert r.status_code==200,r.text;r=r.json()
    assert set(r['channels'])=={'Tickets','Courrier','Bagages'}
    assert any('Tronçon' in a['title'] for a in r['alerts'])
    assert sum(s['costs'] for s in r['segments'])==10000
    assert 'indicative' in r['method']


def test_overspeed_needs_two_valid_consecutive_measurements(setup):
    h,cid,_=setup
    def point(ident,speed,seconds,accuracy=5):
        with m.SessionLocal() as db:
            p={'id':ident,'tripId':'trip','speedKph':speed,'accuracy':accuracy,'createdBy':'driver','latitude':12,'longitude':-1,'createdAt':(m.utcnow()-timedelta(seconds=seconds)).isoformat()};db.add(m.EntityV3(company_id=cid,entity_type='tracking_events',entity_id=ident,payload=p,version=1,updated_at=m.utcnow(),deleted=False));db.commit()
    point('one',120,40)
    assert not any(a['severity']=='critical' for a in call(h,'/insights',method='GET').json()['alerts'])
    point('noise',130,30,500)
    assert not any(a['severity']=='critical' for a in call(h,'/insights',method='GET').json()['alerts'])
    point('two',115,20)
    alerts=call(h,'/insights',method='GET').json()['alerts'];assert len([a for a in alerts if a['severity']=='critical'])==1


def test_permission_payload_rejects_unknown_or_non_boolean_actions(setup):
    with pytest.raises(Exception):normalize({'permissions':{'tickets.sell':'true'}})
    with pytest.raises(Exception):normalize({'permissions':{'invented.action':True}})


def test_user_manager_cannot_escalate_into_privileged_accounts(setup):
    h,cid,_=setup;staff,ident=employee(cid,'manager')
    assert client.get('/api/v2/admin/bootstrap',headers=staff).status_code==200
    payload={'name':'Guichet','username':uuid.uuid4().hex,'password':'test-password-123','role':'agency','modules':normalize({'courier':True,'tickets':True,'profile':'counter','permissions':{k:k in PROFILES['counter']['actions'] for k in CATALOG}})}
    r=client.post('/api/v2/admin/users',headers=staff,json=payload);assert r.status_code==200,r.text
    assert client.post('/api/v2/admin/users',headers=staff,json={**payload,'username':uuid.uuid4().hex,'role':'company_admin'}).status_code==403
    owner=client.get('/api/v2/admin/bootstrap',headers=h).json()['users'];owner=next(u for u in owner if u['role']=='company_admin')
    assert client.put('/api/v2/admin/users/'+owner['id'],headers=staff,json={'name':'No'}).status_code==403
    assert client.delete('/api/v2/admin/users/'+owner['id'],headers=staff).status_code==403


def test_initial_ticket_payment_is_separately_authorized(setup):
    h,cid,_=setup;staff,ident=employee(cid,'counter',{'tickets.payment':False})
    assert post(staff,'/tickets/confirm',{'ticket':ticket()}).status_code==403
    assert post(staff,'/tickets/confirm',{'ticket':ticket(paid=0)}).status_code==200


def test_concurrent_payroll_payments_record_one_expense(setup):
    from concurrent.futures import ThreadPoolExecutor
    h,cid,_=setup;staff,ident=employee(cid,'driver')
    call(h,'/contracts',{'userId':ident,'monthlyBase':120000,'perTrip':0},'PUT')
    p=call(h,'/payroll',{'userId':ident,'month':'2026-11'}).json();call(h,'/payroll/'+p['id']+'/approve',{})
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes=list(pool.map(lambda i:call(h,'/payroll/'+p['id']+'/pay',{'id':'pay-'+str(i),'paymentMethod':'Espèces'}).status_code,range(2)))
    assert sorted(codes)==[200,409]
    with m.SessionLocal() as db:
        rows=db.scalars(m.select(m.EntityV3).where(m.EntityV3.company_id==cid,m.EntityV3.entity_type=='expenses')).all();assert len([r for r in rows if r.payload.get('payrollId')==p['id']])==1


def test_disabled_module_overrides_checked_actions(setup):
    h,cid,_=setup;staff,ident=employee(cid,'counter')
    with m.SessionLocal() as db:
        u=db.get(m.AppUser,ident);u.modules={**u.modules,'tickets':False};db.commit()
    assert post(staff,'/tickets/confirm',{'ticket':ticket()}).status_code==403
