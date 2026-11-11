"""Authenticated HTTP GPS ingestion, independent from passenger/account credentials."""
import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from .transport import lock_company
from .extensions import legacy_trip_time, parse_time


class DeviceRequest(BaseModel):
    busId: str
    label: str = Field(min_length=1, max_length=120)
    externalId: str = Field(default='', max_length=120)


class DeviceState(BaseModel):
    active: bool


class Position(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    recordedAt: str
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)
    speedKph: float | None = Field(default=None, ge=0, le=400, allow_inf_nan=False)
    heading: float | None = Field(default=None, ge=0, lt=360, allow_inf_nan=False)
    tripId: str = ''


def install(app, env):
    Entity, Company, User=env['EntityV3'],env['Company'],env['AppUser']
    auth,session,now=env['read_token'],env['db_session'],env['utcnow']

    def rows(db,cid,kind):
        return [dict(r.payload) for r in db.scalars(select(Entity).where(Entity.company_id==cid,Entity.entity_type==kind,Entity.deleted.is_(False))).all()]

    def get(db,cid,kind,ident):
        row=db.get(Entity,{'company_id':cid,'entity_type':kind,'entity_id':ident})
        if not row or row.deleted:raise HTTPException(404,'Élément GPS introuvable dans cette société')
        return dict(row.payload)

    def put(db,cid,kind,p):
        p=dict(p);ident=p.get('id') or str(uuid.uuid4())
        row=db.get(Entity,{'company_id':cid,'entity_type':kind,'entity_id':ident});version=row.version+1 if row else 1
        p.update(id=ident,companyId=cid,_serverVersion=version,updatedAt=now().isoformat())
        if row:row.payload=p;row.version=version;row.updated_at=now()
        else:db.add(Entity(company_id=cid,entity_type=kind,entity_id=ident,payload=p,version=version,updated_at=now(),deleted=False))
        db.flush();return p

    def access(db,token,write=False,manage=False):
        if write:lock_company(db,Company,token.get('cid'))
        c,u=env['resolve_company_user'](token,db)
        roles=set((u.modules or {}).get('ticketRoles',[]));manager=u.role in {'admin','company_admin','superuser'} or 'manager' in roles
        if not (c.settings or {}).get('modules',{}).get('tickets') or (not manager and (not (u.modules or {}).get('tickets') or not roles & {'dispatch','driver','reports'})) or (manage and not manager):
            raise HTTPException(403,'Droit de suivi GPS insuffisant')
        return c,u,manager or bool(roles & {'dispatch','reports'})

    def public_device(device):return {k:v for k,v in device.items() if k!='tokenHash'}

    @app.get('/api/v2/gps/devices')
    def devices(token=Depends(auth),db=Depends(session)):
        c,u,broad=access(db,token,manage=True)
        return {'devices':[public_device(d) for d in rows(db,c.id,'gps_devices')]}

    @app.post('/api/v2/gps/devices')
    def create(req:DeviceRequest,token=Depends(auth),db=Depends(session)):
        c,u,broad=access(db,token,True,True);get(db,c.id,'ticket_buses',req.busId)
        if any(d['active'] and d['busId']==req.busId for d in rows(db,c.id,'gps_devices')):
            raise HTTPException(409,'Un boîtier actif est déjà associé à ce bus')
        if req.externalId and any(d.get('externalId')==req.externalId for d in rows(db,c.id,'gps_devices')):
            raise HTTPException(409,'Cette référence de boîtier est déjà enregistrée')
        secret='ygps_'+secrets.token_urlsafe(36)
        device=put(db,c.id,'gps_devices',{**req.model_dump(),'active':True,'tokenHash':hashlib.sha256(secret.encode()).hexdigest(),'createdBy':u.id,'createdAt':now().isoformat()})
        db.commit();return {'device':public_device(device),'token':secret,'endpoint':env['PUBLIC_BASE_URL']+'/api/v2/gps/positions'}

    @app.post('/api/v2/gps/devices/{ident}/rotate')
    def rotate(ident:str,token=Depends(auth),db=Depends(session)):
        c,u,broad=access(db,token,True,True);d=get(db,c.id,'gps_devices',ident)
        secret='ygps_'+secrets.token_urlsafe(36);d=put(db,c.id,'gps_devices',{**d,'tokenHash':hashlib.sha256(secret.encode()).hexdigest()})
        db.commit();return {'device':public_device(d),'token':secret,'endpoint':env['PUBLIC_BASE_URL']+'/api/v2/gps/positions'}

    @app.put('/api/v2/gps/devices/{ident}')
    def change(ident:str,req:DeviceState,token=Depends(auth),db=Depends(session)):
        c,u,broad=access(db,token,True,True);d=get(db,c.id,'gps_devices',ident)
        if req.active and any(x['id']!=ident and x['active'] and x['busId']==d['busId'] for x in rows(db,c.id,'gps_devices')):
            raise HTTPException(409,'Un autre boîtier actif est associé au bus')
        d=put(db,c.id,'gps_devices',{**d,'active':req.active});db.commit();return public_device(d)

    @app.post('/api/v2/gps/positions')
    def ingest(req:Position,authorization:str=Header(default=''),db=Depends(session)):
        if not authorization.startswith('Bearer ygps_'):raise HTTPException(401,'Clé GPS requise')
        digest=hashlib.sha256(authorization[7:].encode()).hexdigest()
        row=db.scalar(select(Entity).where(Entity.entity_type=='gps_devices',Entity.deleted.is_(False),Entity.payload['tokenHash'].as_string()==digest))
        if not row or not hmac.compare_digest(row.payload.get('tokenHash',''),digest):raise HTTPException(401,'Clé GPS inconnue')
        cid=row.company_id;lock_company(db,Company,cid);d=get(db,cid,'gps_devices',row.entity_id);c=db.get(Company,cid)
        if not c or not c.active or not d['active'] or not hmac.compare_digest(d['tokenHash'],digest):raise HTTPException(403,'Boîtier ou société désactivé')
        if not (c.settings or {}).get('modules',{}).get('tickets'):raise HTTPException(403,'Module de suivi désactivé')
        get(db,cid,'ticket_buses',d['busId'])
        recorded=parse_time(req.recordedAt)
        if recorded>now()+timedelta(minutes=2) or recorded<now()-timedelta(days=7):raise HTTPException(422,'Horodatage GPS hors plage : sept jours maximum, sans date future')
        ident=hashlib.sha256((d['id']+':'+req.id).encode()).hexdigest()
        fingerprint=hashlib.sha256(req.model_dump_json().encode()).hexdigest()
        old=db.get(Entity,{'company_id':cid,'entity_type':'gps_positions','entity_id':ident})
        if old:
            if old.payload.get('requestHash')!=fingerprint:raise HTTPException(409,'Trame GPS réutilisée avec un autre contenu')
            db.commit();return {'accepted':True,'duplicate':True,'tripId':old.payload.get('tripId','')}
        candidates=[]
        for tr in rows(db,cid,'ticket_trips'):
            if tr.get('busId')!=d['busId'] or tr.get('status') in {'Annulé','Terminé','Clôturé'}:continue
            start=legacy_trip_time(tr['departureAt'])
            end=legacy_trip_time(tr['expectedArrivalAt']) if tr.get('expectedArrivalAt') else start+timedelta(minutes=int(tr.get('durationMinutes') or 240))
            if start-timedelta(hours=1)<=recorded<=end+timedelta(hours=2):candidates.append(tr)
        if req.tripId:
            selected=next((t for t in candidates if t['id']==req.tripId),None)
            if not selected:raise HTTPException(422,'Le voyage ne correspond pas au bus ou à l’heure de la position')
        else:
            if len(candidates)>1:raise HTTPException(409,'Plusieurs voyages possibles : transmettez le tripId')
            selected=candidates[0] if candidates else None
        trip_id=selected['id'] if selected else ''
        p=put(db,cid,'gps_positions',{**req.model_dump(),'id':ident,'deviceId':d['id'],'busId':d['busId'],'tripId':trip_id,'recordedAt':recorded.isoformat(),'createdAt':now().isoformat(),'source':'device','requestHash':fingerprint})
        last=db.get(Entity,{'company_id':cid,'entity_type':'gps_last','entity_id':d['busId']})
        if not last or parse_time(last.payload['recordedAt'])<=recorded:
            put(db,cid,'gps_last',{**p,'id':d['busId']})
        if trip_id:
            latest_id='gps-'+hashlib.sha256((trip_id+':'+d['id']).encode()).hexdigest()
            latest=db.get(Entity,{'company_id':cid,'entity_type':'tracking_events','entity_id':latest_id})
            if not latest or parse_time(latest.payload['recordedAt'])<=recorded:
                put(db,cid,'tracking_events',{**p,'id':latest_id,'stage':'Position','message':'','createdBy':'gps:'+d['id']})
        stale=db.scalars(select(Entity).where(Entity.company_id==cid,Entity.entity_type=='gps_positions',Entity.payload['deviceId'].as_string()==d['id']).order_by(Entity.updated_at.desc()).offset(1000)).all()
        for point in stale:db.delete(point)
        db.commit();return {'accepted':True,'duplicate':False,'tripId':trip_id}

    @app.get('/api/v2/gps/fleet')
    def fleet(token=Depends(auth),db=Depends(session)):
        c,u,broad=access(db,token)
        trips=rows(db,c.id,'ticket_trips')
        if not broad:trips=[t for t in trips if u.id in {t.get('driverId'),t.get('conductorId')}]
        bus_ids={t.get('busId') for t in trips}
        buses=rows(db,c.id,'ticket_buses')
        if not broad:buses=[b for b in buses if b['id'] in bus_ids]
        trip_bus={t['id']:t.get('busId') for t in trips}
        tracking=rows(db,c.id,'tracking_events')
        latest_by_bus={p['id']:p for p in rows(db,c.id,'gps_last')} if broad else {}
        result=[]
        for bus in buses:
            events=[p for p in tracking if trip_bus.get(p.get('tripId'))==bus['id'] and p.get('latitude') is not None]
            last=latest_by_bus.get(bus['id'])
            if last:events.append(last)
            events.sort(key=lambda p:legacy_trip_time(p.get('recordedAt') or p['createdAt']),reverse=True)
            pos=events[0] if events else None
            allowed=('latitude','longitude','accuracy','speedKph','heading','tripId','source')
            safe={k:pos.get(k) for k in allowed} if pos else None
            if safe:
                at=legacy_trip_time(pos.get('recordedAt') or pos['createdAt']);safe.update(recordedAt=at.isoformat(),ageSeconds=max(0,int((now()-at).total_seconds())),source=pos.get('source') or 'phone')
            result.append({'id':bus['id'],'name':bus.get('name'),'registration':bus.get('registration'),'position':safe})
        return {'buses':result,'trips':[{k:t.get(k) for k in ('id','busId','origin','destination','departureAt','status')} for t in trips],
                'devices':[public_device(d) for d in rows(db,c.id,'gps_devices')] if is_manager(u) else [],'serverTime':now().isoformat()}

    def is_manager(u):return u.role in {'admin','company_admin','superuser'} or 'manager' in (u.modules or {}).get('ticketRoles',[])
