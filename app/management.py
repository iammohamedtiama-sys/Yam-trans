"""Operational workload, payroll records and explainable management alerts."""
import hashlib,json,uuid
from datetime import datetime,timedelta,timezone
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from .permissions import CATALOG,PROFILES,allowed
from .transport import lock_company
from .extensions import legacy_trip_time

class Thresholds(BaseModel):
    speedKph:float=Field(default=90,ge=10,le=180,allow_inf_nan=False)
    weeklyHours:float=Field(default=48,ge=1,le=168,allow_inf_nan=False)
    weeklyTrips:int=Field(default=8,ge=1,le=100)
    restHours:float=Field(default=10,ge=1,le=72,allow_inf_nan=False)
    delayedHours:float=Field(default=48,ge=1,le=720,allow_inf_nan=False)
    salesDropPct:float=Field(default=40,ge=1,le=100,allow_inf_nan=False)
class Contract(BaseModel):
    userId:str
    monthlyBase:float=Field(default=0,ge=0,le=100000000,multiple_of=0.01,allow_inf_nan=False)
    perTrip:float=Field(default=0,ge=0,le=10000000,multiple_of=0.01,allow_inf_nan=False)
class Payroll(BaseModel):
    userId:str
    month:str
    bonus:float=Field(default=0,ge=0,le=100000000,multiple_of=0.01,allow_inf_nan=False)
    deduction:float=Field(default=0,ge=0,le=100000000,multiple_of=0.01,allow_inf_nan=False)
    note:str=Field(default='',max_length=500)
class Pay(BaseModel):
    id:str=Field(min_length=1,max_length=120)
    paymentMethod:str=Field(default='Virement',max_length=60)
    reference:str=Field(default='',max_length=120)


def interval(trip):
    start=legacy_trip_time(trip.get('actualDepartureAt') or trip['departureAt'])
    end=legacy_trip_time(trip.get('actualArrivalAt') or trip.get('expectedArrivalAt') or (start+timedelta(hours=6)).isoformat())
    return start,max(start,end)


def workloads(trips,users,thresholds,now):
    result=[];week=now-timedelta(days=7)
    for user in users:
        mods=user.modules or {};roles=mods.get('ticketRoles',[])
        if not (set(roles)&{'driver','conductor'} or mods.get('profile') in {'driver','conductor'}):continue
        assigned=sorted([t for t in trips if user.id in {t.get('driverId'),t.get('conductorId')} and t.get('status')!='Annulé'],key=lambda t:t.get('departureAt',''))
        times=[]
        for trip in assigned:
            try:a,b=interval(trip)
            except HTTPException:continue
            times.append((trip,a,b))
        recent=[(t,a,b) for t,a,b in times if week<=a<=now]
        hours=round(sum((min(b,now)-max(a,week)).total_seconds()/3600 for t,a,b in recent),1)
        alerts=[]
        if len(recent)>thresholds['weeklyTrips']:alerts.append('Voyages sur 7 jours au-dessus du seuil')
        if hours>thresholds['weeklyHours']:alerts.append('Heures de voyage enregistrées au-dessus du seuil')
        for (_,a,b),(_,c,d) in zip(times,times[1:]):
            if c<=now+timedelta(days=7) and c>b and (c-b).total_seconds()<thresholds['restHours']*3600:alerts.append('Repos planifié inférieur au seuil')
            if c<b:alerts.append('Chevauchement d’affectations')
        result.append({'id':user.id,'name':user.name,'profile':mods.get('profile','driver'),'weeklyTrips':len(recent),'weeklyHours':hours,'plannedTrips':sum(a>now for t,a,b in times),'alerts':sorted(set(alerts)), 'assignments':[{'tripId':t['id'],'role':'Chauffeur' if t.get('driverId')==user.id else 'Convoyeur','route':str(t.get('origin',''))+' → '+str(t.get('destination','')),'start':a.isoformat(),'end':b.isoformat(),'status':t.get('status',''),'actualEnd':bool(t.get('actualArrivalAt'))} for t,a,b in times[-100:]]})
    return result


def install(app,env):
    E,U,C=env['EntityV3'],env['AppUser'],env['Company'];session,auth,now=env['db_session'],env['read_token'],env['utcnow']
    def access(db,token,action,write=False):
        if write:lock_company(db,C,token.get('cid'))
        c,u=env['resolve_company_user'](token,db)
        if not allowed(u,action):raise HTTPException(403,'Action non autorisée : '+CATALOG[action]['label'])
        return c,u
    def rows(db,cid,kind):return [dict(r.payload) for r in db.scalars(select(E).where(E.company_id==cid,E.entity_type==kind,E.deleted.is_(False))).all()]
    def get(db,cid,kind,ident):
        r=db.get(E,{'company_id':cid,'entity_type':kind,'entity_id':ident})
        if not r or r.deleted:raise HTTPException(404,'Enregistrement introuvable dans cette société')
        return dict(r.payload)
    def put(db,cid,kind,p):
        p=dict(p);ident=p.get('id') or str(uuid.uuid4());r=db.get(E,{'company_id':cid,'entity_type':kind,'entity_id':ident});v=r.version+1 if r else 1;p.update(id=ident,companyId=cid,updatedAt=now().isoformat(),_serverVersion=v)
        if r:r.payload=p;r.version=v;r.updated_at=now()
        else:db.add(E(company_id=cid,entity_type=kind,entity_id=ident,payload=p,version=v,updated_at=now(),deleted=False))
        db.flush();return p
    def person(db,cid,ident):
        u=db.get(U,ident)
        if not u or u.company_id!=cid or not u.active:raise HTTPException(422,'Utilisateur actif de cette société requis')
        return u
    def thresholds(c):return {**Thresholds().model_dump(),**(c.settings or {}).get('managementThresholds',{})}
    def audit(db,c,u,action,ref):put(db,c.id,'audit',{'createdBy':u.id,'user':u.name,'action':action,'details':ref,'at':now().isoformat()})
    @app.get('/api/v2/management/catalog')
    def catalog(token=Depends(auth),db=Depends(session)):
        c,u=env['resolve_company_user'](token,db)
        return {'actions':CATALOG,'profiles':PROFILES,'effective':{a:allowed(u,a) for a in CATALOG}}
    @app.get('/api/v2/management/staff')
    def staff(token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'staff.view');people=db.scalars(select(U).where(U.company_id==c.id)).all()
        return {'users':[{'id':x.id,'name':x.name,'active':x.active,'profile':(x.modules or {}).get('profile',''),'ticketRoles':(x.modules or {}).get('ticketRoles',[])} for x in people], 'crew':workloads(rows(db,c.id,'ticket_trips'),people,thresholds(c),now()),'thresholds':thresholds(c),'history':rows(db,c.id,'staff_assignments')[-200:]}
    @app.put('/api/v2/management/thresholds')
    def settings(req:Thresholds,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'insights.configure',True);c.settings={**(c.settings or {}),'managementThresholds':req.model_dump(),'crewRestHours':req.restHours,'crewWeeklyTrips':req.weeklyTrips};audit(db,c,u,'Seuils de gestion modifiés','');db.commit();return req.model_dump()
    @app.get('/api/v2/management/payroll')
    def salaries(token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'payroll.view');return {'contracts':rows(db,c.id,'staff_contracts'),'payroll':rows(db,c.id,'payroll')}
    @app.put('/api/v2/management/contracts')
    def contract(req:Contract,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'payroll.prepare',True);person(db,c.id,req.userId);p=put(db,c.id,'staff_contracts',{**req.model_dump(),'id':req.userId});audit(db,c,u,'Barème de paie modifié',req.userId);db.commit();return p
    @app.post('/api/v2/management/payroll')
    def prepare(req:Payroll,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'payroll.prepare',True);employee=person(db,c.id,req.userId)
        try:start=datetime.strptime(req.month,'%Y-%m').replace(tzinfo=timezone.utc);assert start.strftime('%Y-%m')==req.month
        except (ValueError,AssertionError):raise HTTPException(422,'Mois attendu : AAAA-MM')
        ident=hashlib.sha256((req.userId+':'+req.month).encode()).hexdigest();old=next((p for p in rows(db,c.id,'payroll') if p['id']==ident),None)
        digest=hashlib.sha256(json.dumps(req.model_dump(),sort_keys=True).encode()).hexdigest()
        if old:
            if old['requestHash']!=digest:raise HTTPException(409,'Une paie existe déjà pour cet utilisateur et ce mois')
            return old
        bar=get(db,c.id,'staff_contracts',req.userId)
        completed=[t for t in rows(db,c.id,'ticket_trips') if req.userId in {t.get('driverId'),t.get('conductorId')} and t.get('status') in {'Arrivé','Terminé','Clôturé'} and str(t.get('actualArrivalAt') or t.get('departureAt',''))[:7]==req.month and legacy_trip_time(t.get('actualDepartureAt') or t['departureAt'])<=now()]
        gross=round(bar['monthlyBase']+bar['perTrip']*len(completed)+req.bonus,2);net=round(gross-req.deduction,2)
        if net<0:raise HTTPException(422,'Les retenues dépassent le brut')
        p=put(db,c.id,'payroll',{**req.model_dump(),'id':ident,'requestHash':digest,'employeeName':employee.name,'base':bar['monthlyBase'],'perTrip':bar['perTrip'],'completedTrips':len(completed),'tripIds':[t['id'] for t in completed],'gross':gross,'net':net,'status':'Préparée','createdBy':u.id,'createdAt':now().isoformat()});audit(db,c,u,'Paie préparée',ident);db.commit();return p
    @app.post('/api/v2/management/payroll/{ident}/approve')
    def approve(ident:str,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'payroll.approve',True);p=get(db,c.id,'payroll',ident)
        if p['status']=='Payée':raise HTTPException(409,'Paie déjà payée')
        if p['status']=='Validée':return p
        p=put(db,c.id,'payroll',{**p,'status':'Validée','approvedBy':u.id,'approvedAt':now().isoformat()});audit(db,c,u,'Paie validée',ident);db.commit();return p
    @app.post('/api/v2/management/payroll/{ident}/pay')
    def pay(ident:str,req:Pay,token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'payroll.pay',True);p=get(db,c.id,'payroll',ident)
        if p['status']=='Payée':
            if p.get('paymentId')!=req.id or p.get('paymentMethod')!=req.paymentMethod or p.get('reference')!=req.reference:raise HTTPException(409,'Paiement déjà enregistré avec une autre référence')
            return p
        if p['status']!='Validée':raise HTTPException(409,'Validez la paie avant d’enregistrer le paiement')
        p=put(db,c.id,'payroll',{**p,**req.model_dump(exclude={'id'}),'paymentId':req.id,'paidAt':now().isoformat(),'paidBy':u.id,'status':'Payée'})
        put(db,c.id,'expenses',{'id':'payroll-'+ident,'category':'Salaires','amount':p['net'],'description':'Paie '+p['month'],'payrollId':ident,'createdBy':u.id,'agency':u.agency,'createdAt':now().isoformat(),'paymentMethod':req.paymentMethod});audit(db,c,u,'Paiement de paie enregistré',ident);db.commit();return p

    def insights(db,c,start,end):
        try:
            finish=datetime.strptime(end,'%Y-%m-%d').replace(tzinfo=timezone.utc)+timedelta(days=1) if end else now()+timedelta(seconds=1)
            begin=datetime.strptime(start,'%Y-%m-%d').replace(tzinfo=timezone.utc) if start else finish-timedelta(days=30)
            if not begin<finish or (finish-begin).days>367:raise ValueError()
        except ValueError:raise HTTPException(422,'Période invalide, maximum un an')
        policy=thresholds(c);people=db.scalars(select(U).where(U.company_id==c.id)).all();trips=rows(db,c.id,'ticket_trips');tripmap={t['id']:t for t in trips};alerts=[]
        def add(key,severity,title,detail,action,**extra):alerts.append({'id':key,'severity':severity,'title':title,'detail':detail,'action':action,**extra})
        def in_period(p):
            try:return begin<=legacy_trip_time(p.get('createdAt') or p.get('departureAt') or p.get('depositedAt') or '')<finish
            except HTTPException:return False
        data={k:[p for p in rows(db,c.id,k) if in_period(p) and not p.get('cancelled') and p.get('status') not in {'Annulé','Remboursé'}] for k in ('tickets','shipments','ticket_baggage','expenses')}
        segments={};agents={};channels={}
        for kind,label in [('tickets','Tickets'),('shipments','Courrier'),('ticket_baggage','Bagages')]:
            records=data[kind];income=sum(float(p.get('paid',p.get('fee',0)) or 0) for p in records);late=0
            for p in records:
                agent=str(p.get('createdBy') or 'Non attribué');a=agents.setdefault(agent,{'id':agent,'name':next((u.name for u in people if u.id==agent),'Agent non attribué'),'tickets':0,'courier':0,'baggage':0,'cash':0,'previousCash':0});a[{'tickets':'tickets','shipments':'courier','ticket_baggage':'baggage'}[kind]]+=1;a['cash']+=float(p.get('paid',p.get('fee',0)) or 0)
                if kind!='tickets' and p.get('status') not in {'Livré','Remis','Retiré','Retrait','Terminé'} and not p.get('deliveredAt') and not p.get('withdrawnAt'):
                    try:age=(now()-legacy_trip_time(p.get('createdAt') or '')).total_seconds()/3600
                    except HTTPException:age=0
                    if age>policy['delayedHours']:late+=1
            channels[label]={'records':len(records),'cash':round(income,2),'delayed':late}
            if late:add('late-'+kind,'warning',label+' : dossiers anciens',f'{late} dossier(s) dépassent {policy["delayedHours"]:g} h sans remise enregistrée.','Contrôler les arrivées et relancer les agences concernées.',module=label)
        # Comparable previous period, without attributing performance to a person's quality.
        duration=finish-begin
        for kind in ('tickets','shipments','ticket_baggage'):
            for p in rows(db,c.id,kind):
                try:at=legacy_trip_time(p.get('createdAt') or '')
                except HTTPException:continue
                if begin-duration<=at<begin and not p.get('cancelled') and p.get('status') not in {'Annulé','Remboursé'}:
                    agent=str(p.get('createdBy') or 'Non attribué');a=agents.setdefault(agent,{'id':agent,'name':next((u.name for u in people if u.id==agent),'Agent non attribué'),'tickets':0,'courier':0,'baggage':0,'cash':0,'previousCash':0})
                    a['previousCash']+=float(p.get('paid',p.get('fee',0)) or 0)
        for a in agents.values():
            a['changePct']=round((a['cash']/a['previousCash']-1)*100,1) if a['previousCash'] else None
            if a['changePct'] is not None and a['changePct']<=-policy['salesDropPct']:add('sales-'+a['id'],'warning','Baisse des encaissements au guichet',f'{a["name"]} : {a["changePct"]:g} % sur deux périodes de même durée.','Vérifier présence, horaires, volume de départs et qualité de saisie avant toute conclusion sur l’agent.')
        from .transport import stops_for,span
        all_tickets=[t for t in rows(db,c.id,'tickets') if t.get('status') not in {'Annulé','Remboursé'} and not t.get('cancelled')];all_costs=rows(db,c.id,'expenses');all_courier=rows(db,c.id,'shipments');all_baggage=rows(db,c.id,'ticket_baggage')
        packs={p['id']:p for p in rows(db,c.id,'travel_packs')};refunds=rows(db,c.id,'ticket_refunds')
        for tr in trips:
            try:at=legacy_trip_time(tr['departureAt'])
            except HTTPException:continue
            if not begin<=at<finish or tr.get('status')=='Annulé':continue
            stops=stops_for(tr);n=max(1,len(stops)-1);cost=sum(float(p.get('amount') or 0) for p in all_costs if p.get('tripId')==tr['id'])
            for i in range(n):
                key=str(stops[i])+' → '+str(stops[i+1]);s=segments.setdefault(key,{'route':key,'revenue':0,'costs':0,'passengers':0,'departures':0,'costRecords':0});s['costs']+=cost/n;s['departures']+=1;s['costRecords']+=bool(cost)
                for t in all_tickets:
                    if t.get('tripId')!=tr['id']:continue
                    try:a,b=span(tr,t)
                    except HTTPException:continue
                    if a<=i<b:
                        pack=packs.get(t.get('packId'));value=float(pack.get('amount') or 0)/max(1,int(pack.get('journeys') or 1)) if pack else float(t.get('fare') or 0)
                        value-=sum(float(r.get('amount') or 0) for r in refunds if r.get('ticketId')==t['id'] and in_period(r))
                        s['revenue']+=value/max(1,b-a);s['passengers']+=1
                for kind in ('shipments','ticket_baggage'):
                    s['revenue']+=sum(float(p.get('fee',p.get('fare',p.get('amount',p.get('paid',0)))) or 0)/n for p in (all_courier if kind=='shipments' else all_baggage) if p.get('tripId')==tr['id'] and not p.get('cancelled') and p.get('status') not in {'Annulé','Remboursé'})
        for s in segments.values():
            s.update(revenue=round(s['revenue'],2),costs=round(s['costs'],2),margin=round(s['revenue']-s['costs'],2))
            if s['margin']<0:add('segment-'+s['route'],'warning','Tronçon à examiner : '+s['route'],f'Marge indicative {s["margin"]:,.0f} FCFA sur les montants et charges saisis.','Contrôler remplissage, tarification et charges avant de modifier la desserte.')
            if not s['costRecords']:add('cost-'+s['route'],'info','Charges non renseignées : '+s['route'],'Impossible de conclure sur la rentabilité sans charges.','Compléter carburant, péages et autres coûts du voyage.')
        crew=workloads(trips,people,policy,now())
        for p in crew:
            for i,message in enumerate(p['alerts']):add('crew-'+p['id']+str(i),'warning',p['name']+' : charge de voyages',f'{p["weeklyTrips"]} voyages et {p["weeklyHours"]:g} h sur 7 jours. '+message,'Examiner le planning et rééquilibrer les affectations ; les heures enregistrées ne mesurent pas la fatigue.',userId=p['id'])
        # At least two fresh consecutive measurements, not one noisy GPS sample.
        positions=rows(db,c.id,'gps_positions')+rows(db,c.id,'tracking_events');streams={}
        for p in positions:
            if p.get('speedKph') is None or (p.get('accuracy') is not None and float(p['accuracy'])>100):continue
            try:at=legacy_trip_time(p.get('recordedAt') or p.get('createdAt',''))
            except HTTPException:continue
            if not begin<=at<finish:continue
            key=(p.get('tripId'),p.get('deviceId') or p.get('createdBy','phone'));streams.setdefault(key,{})[(at.isoformat(),p.get('speedKph'))]=(p,at)
        for (tid,device),items in streams.items():
            ordered=sorted(items.values(),key=lambda x:x[1]);pairs=[(p,q,b) for (p,a),(q,b) in zip(ordered,ordered[1:]) if 10<=(b-a).total_seconds()<=120 and p['speedKph']>policy['speedKph'] and q['speedKph']>policy['speedKph']]
            if pairs:
                p,q,at=pairs[-1];tr=tripmap.get(tid,{})
                add('speed-'+str(tid)+str(device),'critical' if 0<=(now()-at).total_seconds()<=300 else 'warning','Dépassement de vitesse GPS à vérifier',f'{max(p["speedKph"],q["speedKph"]):g} km/h mesurés pour un seuil interne de {policy["speedKph"]:g} km/h ; au moins deux mesures consécutives.','Contacter l’équipage selon la procédure interne et vérifier le contexte. Ce seuil ne remplace pas les limites routières.',tripId=tid,driverId=tr.get('driverId',''),at=at.isoformat())
        for part in rows(db,c.id,'stock_items'):
            quantity=sum(float(m.get('quantity') or 0)*(1 if m.get('direction')=='Entrée' else -1) for m in rows(db,c.id,'stock_movements') if m.get('itemId')==part['id'])
            if quantity<=float(part.get('minimum') or 0):add('stock-'+part['id'],'warning','Stock à réapprovisionner : '+str(part.get('name','Pièce')),f'Quantité enregistrée : {quantity:g}.','Vérifier le stock physique et planifier le réapprovisionnement.')
        for item in rows(db,c.id,'fleet_events'):
            if item.get('dueDate') and not item.get('completed'):
                try:days=(datetime.strptime(item['dueDate'],'%Y-%m-%d').date()-now().date()).days
                except ValueError:continue
                if days<=14:add('fleet-'+item['id'],'warning','Échéance flotte : '+str(item.get('label','Entretien')),f'Échéance dans {days} jour(s).','Contrôler l’échéance et programmer l’intervention avec l’exploitation.')
        birthdays={p.get('id') for p in rows(db,c.id,'ticket_customers') if p.get('active') is not False and str(p.get('birthDate') or '')[5:]==now().strftime('%m-%d')}
        if birthdays:add('birthdays-today','info','Anniversaires clients aujourd’hui',f'{len(birthdays)} client(s) avec une date de naissance renseignée.','Consulter la rubrique Clients et vérifier le destinataire avant de préparer un message.')
        unallocated=sum(float(e.get('amount') or 0) for e in data['expenses'] if not e.get('tripId'))
        if unallocated:add('unallocated','info','Charges non affectées à un voyage',f'{unallocated:,.0f} FCFA ne sont pas répartis dans les tronçons.','Affecter les charges pertinentes ; la marge des tronçons reste indicative.')
        return {'period':{'start':begin.date().isoformat(),'end':(finish-timedelta(seconds=1)).date().isoformat()},'thresholds':policy,'channels':channels,'segments':list(segments.values()),'agents':list(agents.values()),'crew':crew,'alerts':alerts,'unallocatedExpenses':unallocated,'method':'Encaissements par date d’opération ; tronçons par date de départ avec leurs billets et charges enregistrés. Recettes de billets réparties entre leurs tronçons ; charges du voyage réparties à parts égales faute de distances. Marge indicative, sans coûts absents ni conclusion automatique sur le personnel.'}
    @app.get('/api/v2/management/insights')
    def recommendations(start:str='',end:str='',token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'insights.view');return insights(db,c,start,end)
    @app.post('/api/v2/management/insights/ai')
    def ai(start:str='',end:str='',token=Depends(auth),db=Depends(session)):
        c,u=access(db,token,'insights.ai');r=insights(db,c,start,end)
        from .analysis_ai import interpret
        report={'trips':[{'departureAt':r['period']['end'],'tickets':s['passengers'],'occupancyPct':None,'cashIncome':s['revenue'],'prepaidAllocated':0,'income':s['revenue'],'expenses':s['costs'],'net':s['margin']} for s in r['segments']], 'crew':[{'weeklyTrips':s['weeklyTrips'],'alerts':s['alerts']} for s in r['crew']], 'unallocatedExpenses':r['unallocatedExpenses'],'parkingIncome':0,'prepaidIncome':0,'management':{'channels':r['channels'],'alertCounts':{k:sum(a['severity']==k for a in r['alerts']) for k in ('info','warning','critical')}}}
        return interpret(report)
