import pytest
from test_transport import client, m, setup, post


def comparable(record):
    return {k:v for k,v in record.items() if k != '_serverUpdatedAt'}


def sync(headers, entities):
    response=client.post('/api/v2/sync',headers=headers,json={'deviceId':'manifest-test','entities':entities})
    assert response.status_code==200,response.text
    return response.json()


def manifest(headers, **changes):
    data=sync(headers,{'manifests':[{'id':'manifest','code':'BRD-TEST','origin':'Ouaga','destination':'Bobo','departureAt':m.utcnow().isoformat(),'shipmentIds':['courier'],'route':'Route initiale',**changes}]})
    assert not data['conflicts'],data
    return data['entities']['manifests'][0]


@pytest.mark.parametrize('patch',[
    {'route':'Route modifiée'}, {'shipmentIds':[]}, {'arrivedAt':''},
    {'arrivedBy':'autre-agent'}, {'deleted':True}, {'destination':'Abidjan'},
    {'expectedParcelCount':200},
])
def test_arrival_seals_manifest_even_for_company_administrator(setup,patch):
    headers,_,_=setup
    original=manifest(headers,dispatchedAt=m.utcnow().isoformat(),arrivedAt=m.utcnow().isoformat(),arrivedBy='agent')
    result=sync(headers,{'manifests':[{**original,**patch}]})
    assert result['conflicts'][0]['type']=='manifest_locked'
    assert result['conflicts'][0]['entityType']=='manifests'
    assert comparable(result['entities']['manifests'][0])==comparable(original)


def test_pre_arrival_edit_and_first_arrival_are_allowed_and_cached_resync_is_read_only(setup):
    headers,_,_=setup
    original=manifest(headers,dispatchedAt=m.utcnow().isoformat())
    edited=sync(headers,{'manifests':[{**original,'route':'Route corrigée'}]})
    assert not edited['conflicts']
    arrived=sync(headers,{'manifests':[{**edited['entities']['manifests'][0],'arrivedAt':m.utcnow().isoformat()}]})
    assert not arrived['conflicts']
    sealed=arrived['entities']['manifests'][0]
    unchanged=sync(headers,{'manifests':[{**sealed,'updatedAt':'local-cache','_createdByName':'Agent'}]})
    assert not unchanged['conflicts']
    assert comparable(unchanged['entities']['manifests'][0])==comparable(sealed)


def test_old_offline_edit_cannot_remove_arrival_confirmation(setup):
    headers,_,_=setup
    old=manifest(headers,dispatchedAt=m.utcnow().isoformat())
    arrived=sync(headers,{'manifests':[{**old,'arrivedAt':m.utcnow().isoformat()}]})['entities']['manifests'][0]
    result=sync(headers,{'manifests':[{**old,'driver':'Modifié hors connexion'}]})
    assert result['conflicts'][0]['type']=='manifest_locked'
    assert comparable(result['entities']['manifests'][0])==comparable(arrived)


def test_locked_manifest_membership_is_immutable_but_delivery_can_continue(setup):
    headers,_,_=setup
    mf=manifest(headers)
    attached=sync(headers,{'shipments':[dict(sync(headers,{})['entities']['shipments'][0],manifestId=mf['id'])]})['entities']['shipments'][0]
    sync(headers,{'manifests':[{**mf,'arrivedAt':m.utcnow().isoformat()}]})
    detached=sync(headers,{'shipments':[{**attached,'manifestId':''}]})
    assert detached['conflicts'][0]['type']=='manifest_locked'
    assert detached['entities']['shipments'][0]['manifestId']==mf['id']
    added=sync(headers,{'shipments':[{'id':'extra','code':'OUA-EXTRA','origin':'Ouaga','destination':'Bobo','manifestId':mf['id'],'fee':1000}]})
    assert added['conflicts'][0]['type']=='manifest_locked'
    assert len(added['entities']['shipments'])==1
    delivered=sync(headers,{'shipments':[{**attached,'status':'Disponible pour retrait'}]})
    assert not delivered['conflicts']
    assert delivered['entities']['shipments'][0]['status']=='Disponible pour retrait'


def test_link_endpoint_cannot_modify_sealed_manifest_and_same_link_retry_is_read_only(setup):
    headers,_,_=setup
    mf=manifest(headers,arrivedAt=m.utcnow().isoformat())
    assert post(headers,'/trips/trip/manifests',{'manifestId':mf['id']}).status_code==409
    assert comparable(sync(headers,{})['entities']['manifests'][0])==comparable(mf)


def test_existing_trip_link_remains_idempotent_after_arrival(setup):
    headers,_,_=setup
    mf=manifest(headers,tripId='trip',arrivedAt=m.utcnow().isoformat())
    r=post(headers,'/trips/trip/manifests',{'manifestId':mf['id']})
    assert r.status_code==200,r.text
    assert comparable(r.json()['manifest'])==comparable(mf)
