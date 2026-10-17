"""Additive operational modules. Private data never enters public tracking views."""
import math
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Literal
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from .transport import lock_company

PRIVATE_TYPES = {'parking', 'fleet_events', 'customer_documents', 'travel_packs', 'tracking_events', 'trip_shares'}

class ParkingRequest(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    registration: str = Field(min_length=1, max_length=80)
    vehicleType: Literal['Moto', 'Voiture']
    customerName: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=3, max_length=50)
    condition: str = Field(min_length=1, max_length=1000)
    rate: float = Field(ge=0, allow_inf_nan=False)
    pricing: Literal['jour', 'forfait']

class ReleaseRequest(BaseModel):
    paid: float = Field(ge=0, allow_inf_nan=False)
    condition: str = Field(min_length=1, max_length=1000)

class FleetRequest(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    busId: str = Field(min_length=1, max_length=120)
    tripId: str = ''
    kind: Literal['Carburant', 'Maintenance', 'Pièce détachée', 'Document']
    label: str = Field(min_length=1, max_length=200)
    amount: float = Field(ge=0, allow_inf_nan=False)
    quantity: float = Field(default=0, ge=0, allow_inf_nan=False)
    odometer: float = Field(default=0, ge=0, allow_inf_nan=False)
    dueDate: str = ''
    paymentMethod: Literal['Espèces', 'Mobile Money', 'Virement'] = 'Espèces'

class CrewPolicy(BaseModel):
    restHours: float = Field(ge=1, le=72, allow_inf_nan=False)
    weeklyTrips: int = Field(ge=1, le=100)


class CrewRequest(BaseModel):
    driverId: str
    conductorId: str = ''

class TrackingRequest(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    stage: Literal['Position', 'Embarquement', 'Parti', 'Approche', 'Entrée en gare', 'Arrivé', 'Incident']
    message: str = Field(default='', max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    accuracy: float | None = Field(default=None, ge=0, allow_inf_nan=False)

class OcrRequest(BaseModel):
    image: str = Field(max_length=7_000_000)


class DocumentRequest(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    customerId: str = Field(default='', max_length=120)
    customerName: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=3, max_length=50)
    kind: Literal['CNIB', 'Passeport', 'Autre']
    number: str = Field(min_length=3, max_length=100)
    expiresOn: str = ''
    replacesId: str = ''
    previousNumber: str = Field(default='',max_length=100)
    photo: str = Field(default='',max_length=7_000_000)

class PackRequest(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    customerId: str = Field(default='', max_length=120)
    customerName: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=3, max_length=50)
    routeId: str = Field(min_length=1, max_length=120)
    seatClass: Literal['Simple', 'VIP'] = 'Simple'
    journeys: int = Field(default=10, ge=1, le=365)
    amount: float = Field(gt=0, allow_inf_nan=False)
    expiresOn: str
    paymentMethod: Literal['Espèces', 'Mobile Money', 'Virement'] = 'Espèces'

class TransferRequest(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    tripId: str
    seat: str
    reason: str = Field(min_length=3, max_length=500)


def install(app, env):
    Entity, Company, User = env['EntityV3'], env['Company'], env['AppUser']
    session, auth, now = env['db_session'], env['read_token'], env['utcnow']

    def rows(db, cid, kind):
        return [dict(x.payload) for x in db.scalars(select(Entity).where(Entity.company_id==cid, Entity.entity_type==kind, Entity.deleted.is_(False))).all()]

    def get(db, cid, kind, ident):
        row=db.get(Entity, {'company_id':cid,'entity_type':kind,'entity_id':ident})
        if not row or row.deleted:
            raise HTTPException(404, 'Élément introuvable dans cette société')
        return dict(row.payload)

    def put(db,cid,kind,payload):
        p=dict(payload)
        ident=str(p.get('id') or uuid.uuid4())
        row=db.get(Entity,{'company_id':cid,'entity_type':kind,'entity_id':ident})
        version=row.version+1 if row else 1
        p.update(id=ident,companyId=cid,_serverVersion=version,updatedAt=now().isoformat())
        if row:
            row.payload=p;row.version=version;row.updated_at=now()
        else:
            db.add(Entity(company_id=cid,entity_type=kind,entity_id=ident,payload=p,version=version,updated_at=now(),deleted=False))
        db.flush()
        return p

    def access(db,token,role='dispatch',write=False):
        if write: lock_company(db,Company,token.get('cid'))
        c=env['require_company'](token,db);u=db.get(User,token.get('uid'))
        if not u or not u.active or u.company_id!=c.id:
            raise HTTPException(403,'Compte société actif requis')
        roles=(u.modules or {}).get('ticketRoles',[])
        if not (c.settings or {}).get('modules',{}).get('tickets'):
            raise HTTPException(403,'Module Tickets requis')
        if u.role not in {'admin','company_admin','superuser'} and (not (u.modules or {}).get('tickets') or ((role not in roles if role!='any' else not any(r in roles for r in ('sales','dispatch','driver','boarding','reports'))) and 'manager' not in roles)):
            raise HTTPException(403,'Droit insuffisant')
        return c,u

    def audit(db,c,u,action,reference):
        put(db,c.id,'audit',{'action':action,'details':reference,'at':now().isoformat(),'createdBy':u.id,'user':u.name,'agency':u.agency})

    def retry(db,c,u,kind,ident):
        row=db.get(Entity,{'company_id':c.id,'entity_type':kind,'entity_id':ident})
        if row:
            if row.payload.get('createdBy')!=u.id:
                raise HTTPException(403,'Référence utilisée par un autre agent')
            return dict(row.payload)

    def date(value):
        try: return datetime.strptime(value,'%Y-%m-%d').date()
        except ValueError: raise HTTPException(422,'Date invalide (AAAA-MM-JJ)')

    def crew_validate(db,cid,p):
        for key in ('driverId','conductorId'):
            ident=str(p.get(key) or '')
            if key=='driverId' and not ident:
                raise HTTPException(422,'Chauffeur requis')
            if not ident: continue
            person=db.get(User,ident)
            if not person or person.company_id!=cid or not person.active or not (person.modules or {}).get('tickets') or 'driver' not in (person.modules or {}).get('ticketRoles',[]):
                raise HTTPException(422,'Choisissez un compte équipage actif de cette société')
        if p.get('driverId')==p.get('conductorId'):
            raise HTTPException(422,'Chauffeur et convoyeur doivent être distincts')
    env['validate_crew']=crew_validate

    def resolve_customer(db,cid,req):
        phone=''.join(ch for ch in req.phone if ch.isdigit())
        if len(phone)==8:phone='226'+phone
        name=' '.join(req.customerName.casefold().split())
        if req.customerId:
            known=next((p for kind in ('ticket_customers','customers') for p in rows(db,cid,kind) if p.get('id')==req.customerId),None)
            # Compatibility with stable customers created by older private document records.
            if not known and not any(p.get('customerId')==req.customerId for p in rows(db,cid,'customer_documents')):
                put(db,cid,'ticket_customers',{'id':req.customerId,'name':req.customerName,'phone':'+'+phone,'points':0,'createdAt':now().isoformat()})
            return req.customerId
        for kind in ('ticket_customers','customers'):
            for person in rows(db,cid,kind):
                other=''.join(ch for ch in str(person.get('phone') or '') if ch.isdigit())
                if len(other)==8:other='226'+other
                if other==phone and ' '.join(str(person.get('name') or '').casefold().split())==name:
                    return person['id']
        ident=str(uuid.uuid4())
        put(db,cid,'ticket_customers',{'id':ident,'name':req.customerName,'phone':'+'+phone,'points':0,'createdAt':now().isoformat()})
        return ident

    @app.get('/api/v2/operations/state')
    def state(token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'any')
        # The general operational dashboard must not expose identity documents.
        result={}
        roles=(u.modules or {}).get('ticketRoles',[])
        manager=u.role in {'admin','company_admin','superuser'} or 'manager' in roles
        if manager or 'sales' in roles:
            result['travel_packs']=rows(db,c.id,'travel_packs')
            result['parking']=rows(db,c.id,'parking')
        if manager or 'dispatch' in roles:
            result.update({k:rows(db,c.id,k) for k in ('parking','fleet_events','tracking_events','trip_shares')})
        return result

    @app.post('/api/v2/operations/parking')
    def park(req:ParkingRequest,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'sales',True)
        old=retry(db,c,u,'parking',req.id)
        if old:return old
        if any(p.get('status')=='Déposé' and p.get('registration','').strip().upper()==req.registration.strip().upper() for p in rows(db,c.id,'parking')):
            raise HTTPException(409,'Ce véhicule est déjà consigné')
        item=put(db,c.id,'parking',{**req.model_dump(),'status':'Déposé','depositedAt':now().isoformat(),'createdBy':u.id,'createdByName':u.name,'agency':u.agency})
        audit(db,c,u,'Véhicule consigné',req.registration);db.commit();return item

    @app.post('/api/v2/operations/parking/{ident}/release')
    def release(ident:str,req:ReleaseRequest,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'sales',True);p=get(db,c.id,'parking',ident)
        if p['status']=='Restitué':return p
        elapsed=(now()-datetime.fromisoformat(p['depositedAt'])).total_seconds()
        days=max(1,math.ceil(elapsed/86400))
        due=float(p['rate'])*(days if p['pricing']=='jour' else 1)
        if not math.isclose(req.paid,due,abs_tol=0.001):raise HTTPException(422,f'Montant attendu : {due:g} FCFA')
        item=put(db,c.id,'parking',{**p,'status':'Restitué','releasedAt':now().isoformat(),'releasedBy':u.id,'releaseCondition':req.condition,'days':days,'paid':due})
        audit(db,c,u,'Véhicule restitué',ident);db.commit();return item

    @app.post('/api/v2/operations/fleet')
    def fleet(req:FleetRequest,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'dispatch',True)
        old=retry(db,c,u,'fleet_events',req.id)
        if old:return old
        get(db,c.id,'ticket_buses',req.busId)
        if req.tripId and get(db,c.id,'ticket_trips',req.tripId).get('busId')!=req.busId:
            raise HTTPException(422,'Le bus ne correspond pas au départ')
        if req.dueDate:date(req.dueDate)
        item=put(db,c.id,'fleet_events',{**req.model_dump(),'createdAt':now().isoformat(),'createdBy':u.id,'createdByName':u.name,'agency':u.agency})
        if req.amount:
            put(db,c.id,'expenses',{'id':'fleet-'+req.id,'tripId':req.tripId,'busId':req.busId,'category':req.kind,'amount':req.amount,'paymentMethod':req.paymentMethod,'description':req.label,'label':req.label,'createdAt':item['createdAt'],'createdBy':u.id,'agency':u.agency,'fleetEventId':req.id})
        audit(db,c,u,'Événement flotte',req.id);db.commit();return item

    @app.put('/api/v2/operations/trips/{ident}/crew')
    def crew(ident:str,req:CrewRequest,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'dispatch',True);p=req.model_dump();crew_validate(db,c.id,p)
        tr=get(db,c.id,'ticket_trips',ident)
        result=put(db,c.id,'ticket_trips',{**tr,**p,'driver':db.get(User,req.driverId).name,'conductor':db.get(User,req.conductorId).name if req.conductorId else ''})
        audit(db,c,u,'Équipage affecté',ident);db.commit();return result

    @app.post('/api/v2/operations/trips/{ident}/share')
    def share(ident:str,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'dispatch',True);get(db,c.id,'ticket_trips',ident)
        existing=next((p for p in rows(db,c.id,'trip_shares') if p['tripId']==ident and p.get('active')),None)
        item=existing or put(db,c.id,'trip_shares',{'tripId':ident,'token':secrets.token_urlsafe(32),'active':True,'createdBy':u.id,'createdAt':now().isoformat()})
        db.commit();return {'url':env['PUBLIC_BASE_URL']+'/voyage/'+item['token'],'id':item['id']}

    @app.delete('/api/v2/operations/shares/{ident}')
    def revoke(ident:str,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'dispatch',True);p=get(db,c.id,'trip_shares',ident)
        put(db,c.id,'trip_shares',{**p,'active':False});db.commit();return {'revoked':True}

    @app.post('/api/v2/operations/trips/{ident}/tracking')
    def tracking(ident:str,req:TrackingRequest,token=Depends(auth),db=Depends(session)):
        # Drivers can update only journeys to which they are assigned.
        c,u=access(db,token,'any',True);tr=get(db,c.id,'ticket_trips',ident)
        if u.role not in {'admin','company_admin','superuser'} and not any(r in (u.modules or {}).get('ticketRoles',[]) for r in ('manager','dispatch')) and u.id not in {tr.get('driverId'),tr.get('conductorId')}:
            raise HTTPException(403,'Vous ne faites pas partie de cet équipage')
        old=retry(db,c,u,'tracking_events',req.id)
        if old:return old
        if (req.latitude is None)!=(req.longitude is None) or (req.stage=='Position' and req.latitude is None):
            raise HTTPException(422,'Position GPS complète requise')
        item=put(db,c.id,'tracking_events',{**req.model_dump(),'tripId':ident,'createdAt':now().isoformat(),'createdBy':u.id})
        if req.stage in {'Parti','Arrivé','Embarquement'}:
            put(db,c.id,'ticket_trips',{**tr,'status':req.stage,'actualArrivalAt':item['createdAt']} if req.stage=='Arrivé' else {**tr,'status':req.stage})
        db.commit();return item

    def public_data(db,token):
        share=next((r for r in db.scalars(select(Entity).where(Entity.entity_type=='trip_shares',Entity.deleted.is_(False))).all() if secrets.compare_digest(str((r.payload or {}).get('token','')),token) and r.payload.get('active')),None)
        if not share:raise HTTPException(404,'Lien indisponible ou révoqué')
        c=db.get(Company,share.company_id)
        if not c or not c.active:raise HTTPException(404,'Lien indisponible')
        tr=get(db,c.id,'ticket_trips',share.payload['tripId'])
        events=sorted((p for p in rows(db,c.id,'tracking_events') if p['tripId']==tr['id']),key=lambda p:p['createdAt'],reverse=True)
        position=next((p for p in events if p.get('latitude') is not None),None)
        return {'company':c.name,'trip':{k:tr.get(k) for k in ('origin','destination','stops','departureAt','status','actualArrivalAt')},'events':[{k:p.get(k) for k in ('stage','message','createdAt')} for p in events[:50]],'position':{k:position.get(k) for k in ('latitude','longitude','accuracy','createdAt')} if position else None,'serverTime':now().isoformat()}

    @app.get('/api/v2/public/voyage/{token}')
    def public_tracking(token:str,db=Depends(session)):return public_data(db,token)

    @app.get('/voyage/{token}',response_class=HTMLResponse)
    def tracking_page(token:str,db=Depends(session)):
        public_data(db,token)
        # No interpolation of personal or operational text into executable HTML.
        import json
        endpoint=json.dumps('/api/v2/public/voyage/'+token)
        return HTMLResponse('''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Suivi du voyage · YamTrans</title><style>body{font:17px system-ui;background:#081b30;color:white;margin:0;padding:24px}main{max-width:850px;margin:auto}h1{font-size:36px}.card{background:#142f48;padding:22px;border-radius:18px;margin:16px 0}small{color:#b9cad9}a{color:#6ee7b7}.event{border-left:3px solid #34d399;padding:12px;margin:12px}</style><main><small>SUIVI DU VOYAGE</small><h1 id="route">Chargement…</h1><div class="card" id="status"></div><div class="card" id="position"></div><div id="events"></div></main><script>const url='''+endpoint+''';async function refresh(){try{const r=await fetch(url);if(!r.ok)throw Error('Lien indisponible');const d=await r.json();document.querySelector('#route').textContent=d.trip.origin+' → '+d.trip.destination;document.querySelector('#status').textContent=d.company+' · '+d.trip.status+' · départ '+new Date(d.trip.departureAt).toLocaleString('fr-FR');const box=document.querySelector('#position');box.replaceChildren();if(d.position){const p=d.position,age=Date.now()-Date.parse(p.createdAt);box.append((age>300000?'Position ancienne · ':'Dernière position · ')+new Date(p.createdAt).toLocaleString('fr-FR')+' ');const a=document.createElement('a');a.href='https://www.openstreetmap.org/?mlat='+p.latitude+'&mlon='+p.longitude+'#map=13/'+p.latitude+'/'+p.longitude;a.textContent='Voir sur la carte';a.target='_blank';a.rel='noopener';box.append(a)}else box.textContent='Position non transmise par l’équipage';const host=document.querySelector('#events');host.replaceChildren();for(const e of d.events){const div=document.createElement('div');div.className='event';div.textContent=e.stage+' · '+e.message+' · '+new Date(e.createdAt).toLocaleString('fr-FR');host.append(div)}}catch(e){document.querySelector('#status').textContent='Suivi indisponible. Les informations affichées peuvent être anciennes.'}}refresh();setInterval(refresh,30000)</script></html>''')

    @app.post('/api/v2/operations/documents/ocr')
    def ocr(req:OcrRequest,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'any')
        if u.role not in {'admin','company_admin','superuser'} and not any(r in (u.modules or {}).get('ticketRoles',[]) for r in ('sales','boarding','manager')):
            raise HTTPException(403,'Droit identité client requis')
        from .identity_ocr import recognize
        result=recognize(req.image)
        audit(db,c,u,'Lecture OCR de pièce','Photo temporaire, confirmation manuelle requise');db.commit();return result

    @app.post('/api/v2/operations/documents')
    def document(req:DocumentRequest,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'sales',True)
        old=retry(db,c,u,'customer_documents',req.id)
        if old:return {'id':old['id'],'customerId':old['customerId']}
        if req.photo:
            from .identity_ocr import decode_image
            decode_image(req.photo)
        number=''.join(req.number.upper().split())
        if req.expiresOn and date(req.expiresOn)<now().date():raise HTTPException(422,'La pièce est déjà expirée')
        matches=[p for p in rows(db,c.id,'customer_documents') if p['number']==number and p.get('active')]
        if matches:raise HTTPException(409,'Cette pièce est déjà enregistrée')
        previous=None
        if req.replacesId:
            previous=get(db,c.id,'customer_documents',req.replacesId)
        elif req.previousNumber:
            previous_number=''.join(req.previousNumber.upper().split())
            previous=next((p for p in rows(db,c.id,'customer_documents') if p.get('number')==previous_number and p.get('active')),None)
            if not previous:raise HTTPException(404,'Ancienne pièce introuvable : vérifiez son numéro')
        customer_id=previous['customerId'] if previous else resolve_customer(db,c.id,req)
        if previous:
            if req.customerId and previous['customerId']!=req.customerId:raise HTTPException(422,'Le renouvellement doit conserver le même client')
            put(db,c.id,'customer_documents',{**previous,'active':False,'replacedBy':req.id})
            customer=next((p for p in rows(db,c.id,'ticket_customers') if p['id']==customer_id),{'id':customer_id,'points':0})
            put(db,c.id,'ticket_customers',{**customer,'name':req.customerName,'phone':req.phone})
        item=put(db,c.id,'customer_documents',{**req.model_dump(),'customerId':customer_id,'replacesId':previous['id'] if previous else '', 'number':number,'active':True,'createdBy':u.id,'createdAt':now().isoformat()})
        audit(db,c,u,'Pièce client enregistrée',customer_id);db.commit();return {'id':item['id'],'customerId':item['customerId']}

    @app.get('/api/v2/operations/documents/lookup')
    def lookup(number:str,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'boarding')
        number=''.join(number.upper().split())
        p=next((p for p in rows(db,c.id,'customer_documents') if p['number']==number and p.get('active')),None)
        if not p:raise HTTPException(404,'Pièce non reconnue')
        if p.get('expiresOn') and date(p['expiresOn'])<now().date():raise HTTPException(409,'Pièce expirée : renouvellement requis')
        audit(db,c,u,'Consultation pièce client',p['customerId']);db.commit()
        # No document number/photo in the response and no phone-only identity substitution.
        tickets=[t for t in rows(db,c.id,'tickets') if t.get('customerId')==p['customerId'] or ''.join(str(t.get('documentNumber') or '').upper().split())==number]
        return {'customerId':p['customerId'],'customerName':p['customerName'],'photo':p.get('photo',''),'tickets':[t for t in tickets if t.get('status') not in {'Annulé','Remboursé'}]}

    @app.post('/api/v2/operations/packs')
    def pack(req:PackRequest,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'sales',True)
        old=retry(db,c,u,'travel_packs',req.id)
        if old:return old
        get(db,c.id,'ticket_routes',req.routeId)
        if date(req.expiresOn)<now().date():raise HTTPException(422,'Expiration passée')
        customer_id=resolve_customer(db,c.id,req)
        item=put(db,c.id,'travel_packs',{**req.model_dump(),'customerId':customer_id,'remaining':req.journeys,'createdBy':u.id,'createdByName':u.name,'createdAt':now().isoformat(),'agency':u.agency,'redemptions':[]})
        audit(db,c,u,'Carnet prépayé vendu',req.id);db.commit();return item

    @app.post('/api/v2/operations/tickets/{ident}/transfer')
    def transfer(ident:str,req:TransferRequest,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'manager',True)
        try:t=get(db,c.id,'tickets',ident)
        except HTTPException as exc:
            if exc.status_code!=404:raise
            t=next((p for p in rows(db,c.id,'tickets') if str(p.get('pnr') or '').upper()==ident.upper()),None)
            if not t:raise HTTPException(404,'Billet introuvable : vérifiez le PNR')
        ident=t['id']
        history=t.get('transfers',[])
        if any(x.get('id')==req.id for x in history):return t
        if t.get('status') in {'Annulé','Remboursé'} or t.get('boarded'):raise HTTPException(409,'Billet annulé, remboursé ou déjà embarqué')
        tr=get(db,c.id,'ticket_trips',req.tripId)
        if tr.get('origin')!=t.get('origin') or tr.get('destination')!=t.get('destination'):
            raise HTTPException(422,'Le transfert doit conserver le trajet du billet')
        candidate={**t,'tripId':req.tripId,'seat':req.seat,'boardingPoint':tr['origin'],'dropPoint':tr['destination']}
        env['validate_transport_seat'](db,c.id,candidate,exclude_id=ident)
        bus=get(db,c.id,'ticket_buses',tr['busId'])
        from .transport import bus_seats
        seat=next(s for s in bus_seats(bus) if str(s['label'])==req.seat)
        if seat['class']!=t.get('seatClass','Simple'):raise HTTPException(422,'Conservez la classe du billet; une différence tarifaire doit être régularisée au guichet')
        history=[*history,{'id':req.id,'fromTripId':t['tripId'],'fromSeat':t['seat'],'toTripId':req.tripId,'toSeat':req.seat,'reason':req.reason,'at':now().isoformat(),'by':u.id}]
        result=put(db,c.id,'tickets',{**candidate,'origin':tr['origin'],'destination':tr['destination'],'departureAt':tr['departureAt'],'transfers':history,'busLabel':bus.get('name','')})
        audit(db,c,u,'Billet transféré',ident);db.commit();return result

    @app.put('/api/v2/operations/crew-policy')
    def policy(req:CrewPolicy,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'manager',True)
        c.settings={**(c.settings or {}),'crewRestHours':req.restHours,'crewWeeklyTrips':req.weeklyTrips}
        audit(db,c,u,'Seuils de planning modifiés',str(req.model_dump()));db.commit();return req.model_dump()

    @app.get('/api/v2/operations/analysis')
    def analysis(start:str='',end:str='',agent:str='',token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'reports')
        begin=date(start) if start else None;finish=date(end) if end else None
        def selected(p):
            at=str(p.get('createdAt') or p.get('depositedAt') or '')[:10]
            return bool(at and (not begin or at>=str(begin)) and (not finish or at<=str(finish)) and (not agent or p.get('createdBy')==agent))
        trips=rows(db,c.id,'ticket_trips');tickets=rows(db,c.id,'tickets');costs=rows(db,c.id,'expenses');bags=rows(db,c.id,'ticket_baggage');shipments=rows(db,c.id,'shipments');refunds=rows(db,c.id,'ticket_refunds')
        reports=[]
        packs_by_id={p['id']:p for p in rows(db,c.id,'travel_packs')}
        for tr in trips:
            ts=[t for t in tickets if t.get('tripId')==tr['id'] and selected(t)]
            es=[e for e in costs if e.get('tripId')==tr['id'] and selected(e)]
            income=sum(float(t.get('paid') or 0) for t in ts if t.get('status')!='Annulé')+sum(float(b.get('paid') or 0) for b in bags if b.get('tripId')==tr['id'] and selected(b) and not b.get('cancelled') and b.get('status') not in {'Annulé','Remboursé'})+sum(float(s.get('paid',s.get('fee',0)) or 0) for s in shipments if s.get('tripId')==tr['id'] and selected(s) and not s.get('cancelled') and s.get('status') not in {'Annulé','Remboursé'})-sum(float(f.get('amount') or 0) for f in refunds if f.get('tripId')==tr['id'] and selected(f))
            cash_income=income
            prepaid_allocated=sum(float(packs_by_id.get(t.get('packId'),{}).get('amount') or 0)/max(1,int(packs_by_id.get(t.get('packId'),{}).get('journeys') or 1)) for t in ts if t.get('packId') and t.get('status') not in {'Annulé','Remboursé'})
            income+=prepaid_allocated
            expense=sum(float(e.get('amount') or 0) for e in es)
            from .transport import stops_for, span, active, bus_seats
            bus_row=db.get(Entity,{'company_id':c.id,'entity_type':'ticket_buses','entity_id':str(tr.get('busId') or '')})
            capacity=len(bus_seats(bus_row.payload)) if bus_row and not bus_row.deleted else 0
            occupied=[]
            for passenger in tickets:
                if passenger.get('tripId')!=tr['id'] or not active(passenger):continue
                try:occupied.append(span(tr,passenger))
                except HTTPException:occupied.append((0,max(1,len(stops_for(tr))-1)))
            peak=max([sum(a<=i<b for a,b in occupied) for i in range(max(1,len(stops_for(tr))-1))],default=0)
            reports.append({'id':tr['id'],'route':tr['origin']+' → '+tr['destination'],'departureAt':tr['departureAt'],'peakPassengers':peak,'capacity':capacity,'occupancyPct':round(100*peak/capacity,1) if capacity else None,'tickets':len([t for t in ts if t.get('status') not in {'Annulé','Remboursé'}]),'cashIncome':cash_income,'prepaidAllocated':prepaid_allocated,'income':income,'expenses':expense,'net':income-expense})
        crew=[]
        rest_hours=float((c.settings or {}).get('crewRestHours',10));weekly_limit=float((c.settings or {}).get('crewWeeklyTrips',8))
        week=now()-timedelta(days=7)
        for person in db.scalars(select(User).where(User.company_id==c.id,User.active.is_(True))).all():
            if 'driver' not in (person.modules or {}).get('ticketRoles',[]):continue
            assigned=sorted([t for t in trips if person.id in {t.get('driverId'),t.get('conductorId')}],key=lambda t:t['departureAt'])
            recent=[t for t in assigned if week.isoformat()<=t['departureAt']<=now().isoformat()]
            alerts=[]
            for a,b in zip(assigned,assigned[1:]):
                end_at=a.get('actualArrivalAt')
                if end_at and 0<=(datetime.fromisoformat(b['departureAt'].replace('Z','+00:00'))-datetime.fromisoformat(end_at.replace('Z','+00:00'))).total_seconds()<rest_hours*3600:alerts.append('Repos entre voyages inférieur au seuil configuré')
            if len(recent)>weekly_limit:alerts.append('Nombre de voyages supérieur au seuil hebdomadaire')
            if not recent:alerts.append('Aucun voyage sur les 7 derniers jours')
            crew.append({'id':person.id,'name':person.name,'weeklyTrips':len(recent),'alerts':sorted(set(alerts))})
        agents=[]
        for person in db.scalars(select(User).where(User.company_id==c.id)).all():
            by_agent=lambda p:p.get('createdBy')==person.id and selected(p)
            sold=[t for t in tickets if by_agent(t) and t.get('status')!='Annulé']
            courier=sum(float(p.get('paid',p.get('fee',0)) or 0) for p in shipments if by_agent(p) and not p.get('cancelled') and p.get('status') not in {'Annulé','Remboursé'})
            baggage=sum(float(p.get('paid') or 0) for p in bags if by_agent(p) and not p.get('cancelled') and p.get('status') not in {'Annulé','Remboursé'})
            paid=sum(float(p.get('paid') or 0) for p in sold)
            refunded=sum(float(p.get('amount') or 0) for p in refunds if by_agent(p))
            expense=sum(float(p.get('amount') or 0) for p in costs if by_agent(p))
            if sold or courier or baggage or refunded or expense:
                agents.append({'id':person.id,'name':person.name,'tickets':len(sold),'ticketCash':paid,'courierCash':courier,'baggageCash':baggage,'refunds':refunded,'expenses':expense,'netCash':paid+courier+baggage-refunded-expense})
        parking=sum(float(p.get('paid') or 0) for p in rows(db,c.id,'parking') if selected(p))
        packs=sum(float(p.get('amount') or 0) for p in rows(db,c.id,'travel_packs') if selected(p))
        return {'trips':reports,'crew':crew,'agents':agents,'parkingIncome':parking,'prepaidIncome':packs,'unallocatedExpenses':sum(float(e.get('amount') or 0) for e in costs if not e.get('tripId') and selected(e)),'suggestions':[{'tripId':t['id'],'message':'Recettes inférieures aux dépenses saisies : vérifier les coûts et le remplissage avant de modifier les départs.'} for t in reports if t['net']<0],'method':'Analyse calculée à partir des opérations enregistrées; ne mesure pas la fatigue et ne constitue pas une analyse par IA.'}

    @app.post('/api/v2/operations/analysis/ai')
    def ai(start:str='',end:str='',agent:str='',token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'reports')
        report=analysis(start,end,agent,token,db)
        from .analysis_ai import interpret
        result=interpret(report)
        audit(db,c,u,'Analyse IA demandée','Rapport agrégé sans données nominatives');db.commit();return result
