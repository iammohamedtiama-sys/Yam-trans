"""Isolated traveller accounts and server-priced YengaPay bookings."""
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from . import yengapay
from .journey import journey_stops, canonical_segment
from .transport import active, overlap, bus_seats, route_fare, lock_company, ConfirmRequest

class Credentials(BaseModel):
    email:str=Field(min_length=5,max_length=200)
    password:str=Field(min_length=10,max_length=200)
    name:str=Field(default='',max_length=120)
    phone:str=Field(default='',max_length=30)

class Booking(BaseModel):
    id:str=Field(pattern=r'^[a-zA-Z0-9-]{16,80}$')
    tripId:str=Field(max_length=120)
    seat:str=Field(max_length=20)
    boardingPoint:str=Field(max_length=160)
    dropPoint:str=Field(max_length=160)
    passengerName:str=Field(min_length=2,max_length=120)
    phone:str=Field(min_length=8,max_length=30)
    passengerCategory:str=Field(default='adult',pattern='^(adult|child)$')

def install(app,env):
    Entity,Company=env['EntityV3'],env['Company']; session=env['db_session']; now=env['utcnow']
    def rows(db,cid,kind):
        return [dict(x.payload) for x in db.scalars(select(Entity).where(Entity.company_id==cid,Entity.entity_type==kind,Entity.deleted.is_(False))).all()]
    def get(db,cid,kind,key):
        r=db.get(Entity,{'company_id':cid,'entity_type':kind,'entity_id':key})
        if not r or r.deleted:raise HTTPException(404,'Élément introuvable')
        return dict(r.payload)
    def put(db,cid,kind,item):
        item=dict(item);key=item['id'];r=db.get(Entity,{'company_id':cid,'entity_type':kind,'entity_id':key}); version=(r.version+1) if r else 1
        item.update(companyId=cid,_serverVersion=version,_serverUpdatedAt=now().isoformat())
        if r:r.payload=item;r.version=version;r.updated_at=now()
        else:db.add(Entity(company_id=cid,entity_type=kind,entity_id=key,payload=item,version=version,updated_at=now(),deleted=False))
        db.flush();return item
    def company(db,write=False):
        c=db.scalar(select(Company).where(Company.code==os.getenv('PASSENGER_COMPANY_CODE',env['DEFAULT_COMPANY_CODE']).upper()))
        if not c or not c.active or not (c.settings or {}).get('modules',{}).get('tickets'):raise HTTPException(503,'La réservation en ligne est indisponible pour le moment')
        if write:lock_company(db,Company,c.id)
        return c
    def profile(a):return {k:a.get(k,'') for k in ('id','name','email','phone')}
    def account(db,c,authorization):
        raw=authorization.removeprefix('Bearer ')
        if not raw or raw==authorization:raise HTTPException(401,'Connectez-vous pour retrouver vos billets')
        try:s=get(db,c.id,'passenger_sessions',hashlib.sha256(raw.encode()).hexdigest())
        except HTTPException:raise HTTPException(401,'Session expirée') from None
        if s.get('revoked') or s['expiresAt']<now().isoformat():raise HTTPException(401,'Session expirée')
        return get(db,c.id,'passenger_accounts',s['accountId'])
    def new_session(db,c,a):
        token=secrets.token_urlsafe(40)
        put(db,c.id,'passenger_sessions',{'id':hashlib.sha256(token.encode()).hexdigest(),'accountId':a['id'],'expiresAt':(now()+timedelta(days=30)).isoformat()})
        db.commit();return {'token':token,'profile':profile(a)}
    def public_order(db,c,o):
        safe={k:o.get(k) for k in ('id','amount','status','tripId','seat','boardingPoint','dropPoint','departureAt','passengerName','phone','expiresAt','checkoutUrl','message')}
        if o.get('ticketId'):
            t=get(db,c.id,'tickets',o['ticketId']);safe['ticket']={k:t.get(k) for k in ('id','pnr','passengerName','phone','seat','seatClass','boardingPoint','dropPoint','departureAt','fare','paid','status','boarded','busLabel')}
        return safe
    def departure(tr):
        try:d=datetime.fromisoformat(str(tr['departureAt']).replace('Z','+00:00'));return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
        except (ValueError,KeyError):raise HTTPException(422,'Date du départ à vérifier') from None
    def quote_trip(db,c,tr,segment):
        if tr.get('status') not in {'Publié','Planifié','Opérations','Ouvert à la vente','Embarquement'} or departure(tr)<=now():raise HTTPException(409,'Ce départ est fermé à la réservation')
        bus=get(db,c.id,'ticket_buses',str(tr.get('busId','')))
        if bus.get('active') is False or bus.get('status') in {'Maintenance','En panne','Indisponible','Hors service'}:raise HTTPException(409,'Véhicule indisponible')
        route=next((r for r in rows(db,c.id,'ticket_routes') if r['id']==tr.get('routeId')),{});
        allocated=[x for kind in ('tickets','ticket_holds','ticket_reservations') for x in rows(db,c.id,kind) if active(x) and x.get('tripId')==tr['id']]
        seats=[]
        for s in bus_seats(bus):
            fare=route_fare(route,tr,segment,s['class'])
            valid=fare is not None and fare>=100 and fare==int(fare)
            seats.append({'label':str(s['label']),'class':s['class'],'fare':int(fare) if valid else None,'available':valid and not any(str(x.get('seat'))==str(s['label']) and overlap(tr,segment,x) for x in allocated)})
        return {'id':tr['id'],**segment,'departureAt':tr['departureAt'],'bus':bus.get('name',''),'seats':seats,'available':sum(s['available'] for s in seats)}

    @app.get('/api/v2/passenger/config')
    def config(db=Depends(session)):
        c=company(db);cities={s for t in rows(db,c.id,'ticket_trips') for s in safe_stops(t)}
        return {'company':c.name,'phone':c.phone,'cities':sorted(cities),'paymentEnabled':yengapay.configured(),'currency':'XOF'}
    def safe_stops(tr):
        try:return journey_stops(tr)
        except HTTPException:return []

    @app.get('/api/v2/passenger/trips')
    def search(origin:str,destination:str,date:str,db=Depends(session)):
        c=company(db)
        try:datetime.strptime(date,'%Y-%m-%d')
        except ValueError:raise HTTPException(422,'Date invalide') from None
        result=[]
        for tr in rows(db,c.id,'ticket_trips'):
            if not str(tr.get('departureAt','')).startswith(date):continue
            try:result.append(quote_trip(db,c,tr,canonical_segment(tr,{'boardingPoint':origin,'dropPoint':destination})))
            except HTTPException:continue
        return {'trips':sorted(result,key=lambda t:t['departureAt'])[:100]}

    @app.post('/api/v2/passenger/register')
    def register(req:Credentials,db=Depends(session)):
        c=company(db,True);email=req.email.strip().casefold()
        if '@' not in email or '.' not in email.rsplit('@',1)[-1] or not req.name.strip():raise HTTPException(422,'Nom et adresse e-mail valides requis')
        # Public registration cannot claim or reveal staff customer records by telephone.
        if any(a['email']==email for a in rows(db,c.id,'passenger_accounts')):raise HTTPException(409,'Ce compte existe déjà. Connectez-vous.')
        salt=secrets.token_hex(16);digest=hashlib.pbkdf2_hmac('sha256',req.password.encode(),salt.encode(),210000).hex()
        a=put(db,c.id,'passenger_accounts',{'id':str(uuid.uuid4()),'email':email,'name':req.name.strip(),'phone':req.phone.strip(),'salt':salt,'passwordHash':digest,'createdAt':now().isoformat()})
        return new_session(db,c,a)

    @app.post('/api/v2/passenger/login')
    def login(req:Credentials,db=Depends(session)):
        c=company(db,True);email=req.email.strip().casefold();key=hashlib.sha256(email.encode()).hexdigest()
        try:limit=get(db,c.id,'passenger_login_limits',key)
        except HTTPException:limit={'id':key,'failures':0,'until':now().isoformat()}
        if limit['until']>now().isoformat() and limit['failures']>=8:raise HTTPException(429,'Trop de tentatives. Réessayez dans quinze minutes.')
        a=next((a for a in rows(db,c.id,'passenger_accounts') if a['email']==email),None)
        digest=hashlib.pbkdf2_hmac('sha256',req.password.encode(),(a['salt'] if a else 'invalid-account-salt').encode(),210000).hex()
        if not a or not hmac.compare_digest(digest,a['passwordHash']):
            put(db,c.id,'passenger_login_limits',{'id':key,'failures':(limit['failures'] if limit['until']>now().isoformat() else 0)+1,'until':(now()+timedelta(minutes=15)).isoformat()});db.commit();raise HTTPException(401,'Adresse ou mot de passe incorrect')
        put(db,c.id,'passenger_login_limits',{'id':key,'failures':0,'until':now().isoformat()})
        return new_session(db,c,a)

    @app.get('/api/v2/passenger/me')
    def me(authorization:str=Header(default=''),db=Depends(session)):
        c=company(db);return profile(account(db,c,authorization))

    @app.post('/api/v2/passenger/logout')
    def logout(authorization:str=Header(default=''),db=Depends(session)):
        c=company(db,True);account(db,c,authorization);key=hashlib.sha256(authorization.removeprefix('Bearer ').encode()).hexdigest();s=get(db,c.id,'passenger_sessions',key);put(db,c.id,'passenger_sessions',{**s,'revoked':True});db.commit();return {'ok':True}

    @app.get('/api/v2/passenger/orders')
    def orders(authorization:str=Header(default=''),db=Depends(session)):
        c=company(db);a=account(db,c,authorization)
        return {'orders':[public_order(db,c,o) for o in sorted(rows(db,c.id,'passenger_orders'),key=lambda o:o['createdAt'],reverse=True) if o['accountId']==a['id']]}

    @app.post('/api/v2/passenger/orders')
    def book(req:Booking,authorization:str=Header(default=''),db=Depends(session)):
        c=company(db,True);a=account(db,c,authorization)
        try:existing=get(db,c.id,'passenger_orders',req.id)
        except HTTPException:existing=None
        if existing:
            if existing['accountId']!=a['id']:raise HTTPException(404,'Commande introuvable')
            return public_order(db,c,existing)
        if not yengapay.configured():raise HTTPException(503,'Le paiement en ligne sera disponible après activation par la compagnie.')
        tr=get(db,c.id,'ticket_trips',req.tripId);segment=canonical_segment(tr,req.model_dump());segment['passengerCategory']=req.passengerCategory
        quote=quote_trip(db,c,tr,segment);seat=next((s for s in quote['seats'] if s['label']==req.seat),None)
        if not seat or not seat['available']:raise HTTPException(409,'Ce siège vient d’être pris. Choisissez une autre place.')
        expires=min(now()+timedelta(minutes=15),departure(tr));hold_id='passenger-'+req.id
        put(db,c.id,'ticket_holds',{'id':hold_id,'tripId':req.tripId,'seat':req.seat,**segment,'status':'Bloquée','expiresAt':expires.isoformat(),'createdBy':'passenger:'+a['id'],'deviceId':req.id})
        o=put(db,c.id,'passenger_orders',{'id':req.id,**req.model_dump(exclude={'id'}),**segment,'accountId':a['id'],'pnr':'YT-'+secrets.token_hex(12).upper(),'amount':seat['fare'],'status':'Préparation du paiement','expiresAt':expires.isoformat(),'departureAt':tr['departureAt'],'holdId':hold_id,'createdAt':now().isoformat()});db.commit()
        try:
            intent=yengapay.create(req.id,o['amount'],segment['boardingPoint']+' → '+segment['dropPoint']);iid=yengapay.intent_id(intent);url=yengapay.checkout_url(intent)
            if not iid:raise HTTPException(502,'Identifiant du paiement manquant')
        except HTTPException:
            lock_company(db,Company,c.id);o=get(db,c.id,'passenger_orders',req.id);put(db,c.id,'passenger_orders',{**o,'status':'À vérifier','message':'La création du paiement n’a pas pu être confirmée. Contactez la compagnie avec cette référence avant tout nouveau paiement.'});db.commit();raise
        lock_company(db,Company,c.id);o=get(db,c.id,'passenger_orders',req.id);o=put(db,c.id,'passenger_orders',{**o,'intentId':iid,'checkoutUrl':url,'status':'En attente du paiement'});db.commit();return public_order(db,c,o)

    def verify_order(db,c,a,o):
        if o.get('ticketId') or o.get('status')=='Paiement reçu · assistance requise':return public_order(db,c,o)
        if not o.get('intentId'):raise HTTPException(409,'Paiement à vérifier par la compagnie avec la référence de commande')
        data=yengapay.retrieve(o['intentId'])
        if not yengapay.verified_paid(data,o):return public_order(db,c,o)
        lock_company(db,Company,c.id);db.expire_all();o=get(db,c.id,'passenger_orders',o['id'])
        if o.get('ticketId'):return public_order(db,c,o)
        actor=SimpleNamespace(id='passenger:'+a['id'],name=a['name'],agency='Vente en ligne',role='online_sales',modules={})
        t={'id':'online-'+o['id'],'pnr':o['pnr'],'tripId':o['tripId'],'seat':o['seat'],'boardingPoint':o['boardingPoint'],'dropPoint':o['dropPoint'],'passengerCategory':o['passengerCategory'],'passengerName':o['passengerName'],'phone':o['phone'],'fare':o['amount'],'paid':o['amount'],'paymentMethod':'YengaPay','paymentReference':o['intentId']}
        try:
            # An expired hold must not take precedence over a subsequent counter sale.
            # Seat/fare/status are checked again by the same atomic staff booking rule.
            with db.begin_nested():
                h=get(db,c.id,'ticket_holds',o['holdId'])
                if not active(h):put(db,c.id,'ticket_holds',{**h,'status':'Libérée'})
                result=env['passenger_issue_ticket'](ConfirmRequest(ticket=t,holdId=o['holdId'] if active(h) else ''),c,actor,db)
                o=put(db,c.id,'passenger_orders',{**o,'status':'Billet confirmé','ticketId':result['ticket']['id'],'paidAt':now().isoformat()})
        except HTTPException:
            o=put(db,c.id,'passenger_orders',{**o,'status':'Paiement reçu · assistance requise','message':'Paiement reçu. Votre place nécessite une vérification par la compagnie. Ne payez pas une seconde fois.'})
        db.commit();return public_order(db,c,o)

    @app.post('/api/v2/passenger/orders/{order_id}/verify')
    def verify(order_id:str,authorization:str=Header(default=''),db=Depends(session)):
        c=company(db);a=account(db,c,authorization);o=get(db,c.id,'passenger_orders',order_id)
        if o['accountId']!=a['id']:raise HTTPException(404,'Commande introuvable')
        return verify_order(db,c,a,o)

    def staff_access(db,token,payment=False):
        from .permissions import allowed
        c,u=env['resolve_company_user'](token,db)
        if not allowed(u,'reports.view') or (payment and not allowed(u,'tickets.payment')):raise HTTPException(403,'Action non autorisée')
        return c,u

    @app.get('/api/v2/passenger-admin/orders')
    def staff_orders(token=Depends(env['read_token']),db=Depends(session)):
        c,u=staff_access(db,token)
        fields=('id','amount','status','passengerName','phone','boardingPoint','dropPoint','departureAt','seat','intentId','ticketId','message','createdAt')
        return {'orders':[{k:o.get(k) for k in fields} for o in sorted(rows(db,c.id,'passenger_orders'),key=lambda o:o['createdAt'],reverse=True)[:200]]}

    @app.post('/api/v2/passenger-admin/orders/{order_id}/verify')
    def staff_verify(order_id:str,token=Depends(env['read_token']),db=Depends(session)):
        c,u=staff_access(db,token,True);o=get(db,c.id,'passenger_orders',order_id);a=get(db,c.id,'passenger_accounts',o['accountId'])
        return verify_order(db,c,a,o)
