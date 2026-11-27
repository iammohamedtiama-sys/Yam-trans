"""The platform's existing company session must work without bypassing revocation."""
import uuid

import pytest

from test_transport import client, m, setup, ticket, post


@pytest.fixture()
def delegated(setup):
    h, cid, _ = setup
    with m.SessionLocal() as db:
        actor = db.scalar(m.select(m.AppUser).where(m.AppUser.role == 'platform_admin'))
        actor_id = actor.id
        root = {'Authorization': 'Bearer ' + m.make_token(actor, None)}
    r = client.post('/api/v2/platform/companies/' + cid + '/impersonate', headers=root)
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['token']}, cid, actor_id, root


READS = ['/api/v2/extensions/state', '/api/v2/operations/state', '/api/v2/gps/fleet']


def test_existing_platform_company_session_can_use_all_operational_modules(delegated):
    h, cid, actor_id, _ = delegated
    for path in READS:
        r = client.get(path, headers=h)
        assert r.status_code == 200, (path, r.text)
    r = client.post('/api/v2/extensions/stock/items', headers=h,
                    json={'id': 'part', 'sku': 'TEST', 'name': 'Filtre', 'minimum': 1})
    assert r.status_code == 200, r.text
    r = post(h, '/tickets/confirm', {'ticket': ticket()})
    assert r.status_code == 200, r.text
    r = client.post('/api/v2/gps/devices', headers=h,
                    json={'busId': 'bus', 'label': 'Test accès délégué'})
    assert r.status_code == 200, r.text
    assert r.json()['device']['companyId'] == cid
    assert r.json()['device']['createdBy'] == 'platform:' + actor_id + ':' + cid


@pytest.mark.parametrize('change', ['inactive', 'demoted'])
def test_delegation_is_revoked_immediately_for_disabled_or_demoted_actor(delegated, change):
    h, _, actor_id, _ = delegated
    with m.SessionLocal() as db:
        actor = db.get(m.AppUser, actor_id)
        old_active, old_role = actor.active, actor.role
        if change == 'inactive': actor.active = False
        else: actor.role = 'agency'
        db.commit()
    try:
        for path in READS:
            assert client.get(path, headers=h).status_code == 401
        assert post(h, '/tickets/confirm', {'ticket': ticket()}).status_code == 401
    finally:
        with m.SessionLocal() as db:
            actor = db.get(m.AppUser, actor_id)
            actor.active, actor.role = old_active, old_role
            db.commit()


def test_delegation_cannot_be_retargeted_to_another_company(delegated):
    _, cid, actor_id, _ = delegated
    with m.SessionLocal() as db:
        other = m.Company(id=str(uuid.uuid4()), code='ISOLATE-' + uuid.uuid4().hex[:8],
                          name='Test isolation', active=True, created_at=m.utcnow(),
                          settings={'modules': {'tickets': True}})
        db.add(other)
        db.commit()
        fake_actor = m.SimpleNamespace(id='platform:' + actor_id + ':' + cid,
                                      role='company_admin', agency='Toutes')
        h = {'Authorization': 'Bearer ' + m.make_token(fake_actor, other)}
    for path in READS:
        assert client.get(path, headers=h).status_code == 401
    assert post(h, '/tickets/confirm', {'ticket': ticket()}).status_code == 401


@pytest.mark.parametrize('change', ['company_inactive', 'tickets_disabled'])
def test_delegation_keeps_company_and_module_restrictions(delegated, change):
    h, cid, _, _ = delegated
    with m.SessionLocal() as db:
        c = db.get(m.Company, cid)
        old_active, old_settings = c.active, c.settings
        if change == 'company_inactive': c.active = False
        else: c.settings = {**c.settings, 'modules': {**c.settings['modules'], 'tickets': False}}
        db.commit()
    try:
        for path in READS:
            assert client.get(path, headers=h).status_code == 403
        assert post(h, '/tickets/confirm', {'ticket': ticket()}).status_code == 403
    finally:
        with m.SessionLocal() as db:
            c = db.get(m.Company, cid)
            c.active, c.settings = old_active, old_settings
            db.commit()


def test_root_platform_session_still_requires_opening_a_company(delegated):
    _, _, _, root = delegated
    for path in READS:
        assert client.get(path, headers=root).status_code == 403
