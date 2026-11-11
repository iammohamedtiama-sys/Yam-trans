"""Company-scoped action permissions; explicit overrides are authoritative."""
import re
from contextvars import ContextVar
CURRENT_ACTION=ContextVar("yam_authorized_action",default=None)
def verified_action(user):
    action=CURRENT_ACTION.get()
    return bool(action and isinstance((user.modules or {}).get("permissions"),dict) and allowed(user,action))

from fastapi import HTTPException

GROUPS = {
'Tickets': {'tickets.view':'Consulter les billets','tickets.sell':'Vendre / enregistrer un billet','tickets.reserve':'Réserver une place','tickets.cancel_reservation':'Annuler une réservation','tickets.board':'Contrôler et embarquer','tickets.payment':'Encaisser un solde','tickets.refund':'Rembourser un billet','tickets.transfer':'Transférer un billet','tickets.print':'Imprimer / exporter un billet','tickets.customers':'Gérer les clients Tickets','identity.capture':'Photographier et lire une pièce','identity.lookup':'Rechercher par pièce'},
'Exploitation': {'trips.view':'Consulter les départs','trips.manage':'Programmer / modifier les départs','trips.assign':'Affecter les équipages','trips.close':'Clôturer un voyage','trips.expenses':'Enregistrer les charges du voyage','trips.manifest':'Gérer les manifestes','fleet.manage':'Gérer bus et maintenance','gps.view':'Voir les positions GPS','gps.publish':'Transmettre sa position / une étape','gps.share':'Partager / révoquer le suivi public','gps.devices':'Configurer les boîtiers GPS'},
'Courrier': {'courier.view':'Consulter le courrier','courier.create':'Enregistrer un colis','courier.edit':'Modifier un colis','courier.load':'Charger / affecter un colis','courier.receive':'Déclarer une arrivée','courier.deliver':'Remettre au destinataire','courier.payment':'Encaisser le courrier','courier.print':'Imprimer reçus et bordereaux'},
'Bagages': {'baggage.view':'Consulter les bagages','baggage.create':'Enregistrer un bagage','baggage.edit':'Modifier un bagage','baggage.load':'Charger un bagage','baggage.receive':'Déclarer une arrivée bagage','baggage.deliver':'Restituer un bagage','baggage.payment':'Encaisser les bagages','baggage.print':'Imprimer une étiquette / un reçu'},
'Gestion': {'reports.view':'Consulter les rapports financiers','insights.view':'Consulter les suggestions et alertes','insights.configure':'Configurer les seuils d’alerte','insights.ai':'Demander une synthèse IA anonymisée','stock.manage':'Gérer les pièces et mouvements de stock','charters.manage':'Gérer les voyages privés','charters.payment':'Encaisser les voyages privés','parking.manage':'Gérer le parking','notifications.manage':'Configurer et envoyer les notifications','backup.export':'Exporter toutes les données','users.manage':'Gérer les comptes et droits','settings.manage':'Gérer agences, lignes et paramètres'},
'Personnel et paie': {'staff.view':'Voir affectations et charge des équipages','payroll.view':'Consulter les préparations de paie','payroll.prepare':'Préparer une paie','payroll.approve':'Valider une paie','payroll.pay':'Enregistrer un paiement de salaire'} }
CATALOG={k:{'label':v,'group':g} for g,items in GROUPS.items() for k,v in items.items()}
PROFILES={
'driver':{'label':'Chauffeur','actions':['trips.view','gps.publish','tickets.view']},
'conductor':{'label':'Convoyeur','actions':['trips.view','gps.publish','tickets.view','tickets.sell','tickets.reserve','tickets.board','tickets.payment','tickets.print','identity.capture','identity.lookup','baggage.view','baggage.create','baggage.load','baggage.receive','baggage.payment','baggage.print','courier.view','courier.create','courier.load','courier.receive','courier.payment','courier.print']},
'counter':{'label':'Agent de guichet','actions':[k for k in CATALOG if k.startswith(('courier.','baggage.'))]+['tickets.view','tickets.sell','tickets.reserve','tickets.cancel_reservation','tickets.payment','tickets.print','tickets.customers','identity.capture','identity.lookup','trips.view']},
'boarding':{'label':'Contrôleur d’embarquement','actions':['trips.view','tickets.view','tickets.board','identity.capture','identity.lookup']},
'dispatcher':{'label':'Responsable exploitation','actions':[k for k in CATALOG if k.startswith(('trips.','gps.'))]+['tickets.view','fleet.manage','staff.view','insights.view','courier.view','courier.load','baggage.view','baggage.load']},
'cashier':{'label':'Caissier','actions':['tickets.view','tickets.payment','courier.view','courier.payment','baggage.view','baggage.payment','reports.view','charters.payment']},
'accountant':{'label':'Comptable / paie','actions':['reports.view','insights.view','staff.view','payroll.view','payroll.prepare','payroll.pay']},
'mechanic':{'label':'Mécanicien / magasinier','actions':['fleet.manage','stock.manage','trips.view']},
'manager':{'label':'Responsable de gare','actions':list(CATALOG)},
'custom':{'label':'Profil personnalisé','actions':[]}}


def allowed(user, action):
    if action not in CATALOG:return False
    mods=user.modules or {};overrides=mods.get('permissions')
    if isinstance(overrides,dict):return overrides.get(action) is True
    if user.role in {'admin','company_admin','superuser'}:return True
    if mods.get('profile') in PROFILES:return action in PROFILES[mods['profile']]['actions']
    roles=set(mods.get('ticketRoles') or [])
    if 'manager' in roles:return True
    if action.startswith('courier.'):return mods.get('courier',True)
    if action.startswith('baggage.'):return mods.get('baggage',True)
    if action.startswith('payroll.') or action in {'users.manage','settings.manage','backup.export','insights.configure'}:return False
    if action in {'reports.view','insights.view','insights.ai','staff.view'}:return 'reports' in roles or 'dispatch' in roles
    if action in {'identity.capture','identity.lookup','tickets.view','trips.view'}:return bool(roles)
    expected='boarding' if action=='tickets.board' else 'sales' if action.startswith(('tickets.','parking.','charters.payment')) else 'driver' if action=='gps.publish' else 'dispatch'
    return expected in roles or (action=='gps.view' and bool(roles & {'driver','dispatch','reports'}))


def normalize(mods):
    mods=dict(mods or {})
    if 'permissions' in mods:
        value=mods['permissions']
        if not isinstance(value,dict) or any(k not in CATALOG or not isinstance(v,bool) for k,v in value.items()):raise HTTPException(422,'Liste de permissions invalide')
        mods['permissions']={k:value.get(k,False) for k in CATALOG}
        p=mods['permissions'];roles=set()
        if any(p[k] for k in ('tickets.sell','tickets.reserve','tickets.payment','identity.capture','parking.manage','charters.payment')):roles.add('sales')
        if p['tickets.board']:roles.add('boarding')
        if any(p[k] for k in ('trips.manage','trips.assign','fleet.manage','gps.devices','stock.manage','charters.manage','gps.share')):roles.add('dispatch')
        if p['gps.publish'] or mods.get('profile') in {'driver','conductor'}:roles.add('driver')
        if any(p[k] for k in ('reports.view','insights.view','staff.view')):roles.add('reports')
        mods['ticketRoles']=sorted(roles)
    if mods.get('profile')=='conductor':mods['ticketRoles']=sorted(set(mods.get('ticketRoles',[]))|{'conductor','driver'})
    return mods

# Each server action has its own permission, including direct API calls.
ROUTES=[
('POST',r'/transport/(?:tickets|bookings)/confirm','tickets.sell'),('POST',r'/transport/holds','tickets.reserve'),('DELETE',r'/transport/holds/[^/]+','tickets.reserve'),('POST',r'/transport/reservations','tickets.reserve'),('POST',r'/transport/reservations/[^/]+/cancel','tickets.cancel_reservation'),
('POST',r'/transport/tickets/[^/]+/board','tickets.board'),('POST',r'/transport/tickets/[^/]+/payments','tickets.payment'),('POST',r'/transport/tickets/[^/]+/refund','tickets.refund'),('GET',r'/transport/tickets/[^/]+','tickets.view'),('POST',r'/transport/trips/[^/]+/closure','trips.close'),('POST',r'/transport/trips/[^/]+/expenses','trips.expenses'),('POST',r'/transport/trips/[^/]+/manifests','trips.manifest'),('POST',r'/transport/trips/[^/]+/(?:bus|repeat)','trips.manage'),('PUT',r'/transport/trips/[^/]+/capacity','trips.manage'),('POST',r'/transport/waitlist(?:/[^/]+/close)?','tickets.reserve'),
('PUT',r'/operations/trips/[^/]+/crew','trips.assign'),('POST',r'/operations/trips/[^/]+/tracking','gps.publish'),('POST',r'/operations/trips/[^/]+/share','gps.share'),('DELETE',r'/operations/shares/[^/]+','gps.share'),('POST',r'/operations/documents/ocr','identity.capture'),('POST',r'/operations/documents','identity.capture'),('GET',r'/operations/documents/lookup','identity.lookup'),('POST',r'/operations/tickets/[^/]+/transfer','tickets.transfer'),('POST',r'/operations/fleet','fleet.manage'),('POST',r'/operations/parking(?:/[^/]+/release)?','parking.manage'),('POST',r'/operations/packs','tickets.payment'),('PUT',r'/operations/crew-policy','trips.assign'),('GET',r'/operations/analysis','reports.view'),('POST',r'/operations/analysis/ai','insights.ai'),
('GET',r'/gps/fleet','gps.view'),('GET',r'/gps/devices','gps.devices'),('POST',r'/gps/devices(?:/[^/]+/rotate)?','gps.devices'),('PUT',r'/gps/devices/[^/]+','gps.devices'),
('POST',r'/extensions/stock/(?:items|movements)','stock.manage'),('POST',r'/extensions/schedules','trips.manage'),('POST',r'/extensions/charters','charters.manage'),('POST',r'/extensions/charters/[^/]+/payments','charters.payment'),('POST',r'/extensions/charters/[^/]+/status','charters.manage'),('POST',r'/extensions/parking/slots','parking.manage'),('PUT',r'/extensions/preferences','notifications.manage'),('POST',r'/extensions/notifications/dispatch','notifications.manage'),('GET',r'/extensions/search','trips.view'),('GET',r'/extensions/backup','backup.export'),
('GET',r'/admin/bootstrap','users.manage'),('PUT',r'/admin/company/profile','settings.manage'),('POST',r'/admin/users','users.manage'),('PUT',r'/admin/users/[^/]+','users.manage'),('DELETE',r'/admin/users/[^/]+','users.manage')]


def install(app,env):
    from starlette.responses import JSONResponse
    @app.middleware('http')
    async def action_guard(request,call_next):
        path=request.url.path.removeprefix('/api/v2');action=next((a for method,p,a in ROUTES if method==request.method and re.fullmatch(p,path)),None)
        if action:
            try:
                token=env['read_token'](request.headers.get('authorization',''))
                if token.get('role')!='platform_admin':
                    with env['SessionLocal']() as db:
                        c,u=env['resolve_company_user'](token,db)
                        if not allowed(u,action):raise HTTPException(403,'Action non autorisée : '+CATALOG[action]['label'])
                        if request.method in {'POST','PUT'} and action in {'tickets.sell','tickets.reserve','tickets.board','gps.publish'}:
                            try:body=await request.json()
                            except Exception:body={}
                            tickets=body.get('tickets') or [body.get('ticket') or body]
                            route_trip=re.search(r'/trips/([^/]+)/',path)
                            for item in tickets:
                                if action=='tickets.sell' and float(item.get('paid') or 0)>0 and not allowed(u,'tickets.payment'):raise HTTPException(403,'Encaissement non autorisé pour ce compte')
                                tid=item.get('tripId') or (route_trip.group(1) if route_trip else '')
                                if not tid:continue
                                tr=db.get(env['EntityV3'],{'company_id':c.id,'entity_type':'ticket_trips','entity_id':tid})
                                if (u.modules or {}).get('profile') in {'driver','conductor'} and tr and u.id not in {tr.payload.get('driverId'),tr.payload.get('conductorId')}:raise HTTPException(403,'Ce voyage ne vous est pas affecté')
                        module='courier' if action.startswith('courier.') else 'baggage' if action.startswith('baggage.') else 'tickets' if action.startswith(('tickets.','trips.','gps.','identity.')) else None
                        if module and not (c.settings or {}).get('modules',{}).get(module,module!='tickets'):raise HTTPException(403,'Module non activé pour cette société')
            except HTTPException as e:return JSONResponse({'detail':e.detail},status_code=e.status_code)
        mark=CURRENT_ACTION.set(action)
        try:return await call_next(request)
        finally:CURRENT_ACTION.reset(mark)

SYNC_ACTIONS={'shipments':('courier.create','courier.edit'),'ticket_baggage':('baggage.create','baggage.edit'),'tickets':('tickets.sell','tickets.sell'),'ticket_reservations':('tickets.reserve','tickets.reserve'),'ticket_buses':('fleet.manage','fleet.manage'),'ticket_routes':('trips.manage','trips.manage'),'ticket_trips':('trips.manage','trips.manage'),'ticket_customers':('tickets.customers','tickets.customers'),'customers':('courier.create','courier.edit'),'expenses':('trips.expenses','trips.expenses'),'payments':('courier.payment','courier.payment'),'withdrawals':('courier.deliver','courier.deliver'),'manifests':('courier.load','courier.load'),'ticket_boardings':('tickets.board','tickets.board'),'ticket_promos':('trips.manage','trips.manage'),'ticket_refunds':('tickets.refund','tickets.refund'),'loyalty_transactions':('tickets.customers','tickets.customers'),'notification_logs':('notifications.manage','notifications.manage'),'agencies':('settings.manage','settings.manage'),'routes':('settings.manage','settings.manage'),'stations':('settings.manage','settings.manage'),'vehicles':('fleet.manage','fleet.manage'),'schedules':('trips.manage','trips.manage'),'audit':('courier.view','courier.view')}
def sync_actions(kind,p,old):
    actions={SYNC_ACTIONS.get(kind,('settings.manage','settings.manage'))[bool(old)]}
    if kind in {'shipments','ticket_baggage'} and not old:
        prefix='courier' if kind=='shipments' else 'baggage'
        if float(p.get('paid',p.get('fee',0)) or 0)>0:actions.add(prefix+'.payment')
        if any(x in str(p.get('status','')).casefold() for x in ('livr','remis','retir')):actions.add(prefix+'.deliver')
    if kind in {'shipments','ticket_baggage'} and old:
        prefix='courier' if kind=='shipments' else 'baggage'
        if p.get('status')!=old.get('status'):
            status=str(p.get('status','')).casefold()
            actions={prefix+('.deliver' if any(x in status for x in ('livr','remis','retir')) else '.receive' if 'arriv' in status else '.load')}
        if any(p.get(k)!=old.get(k) for k in ('fee','fare','amount','description','sender','recipient')):actions.add(prefix+'.edit')
        if any(p.get(k)!=old.get(k) for k in ('deliveredAt','withdrawnAt','deliveredTo')):actions.add(prefix+'.deliver')
        if any(p.get(k)!=old.get(k) for k in ('paid','paymentMethod')):actions.add(prefix+'.payment')
        if any(p.get(k)!=old.get(k) for k in ('tripId','manifestId','loadedAt')):actions.add(prefix+'.load')
    if kind=='ticket_trips' and old and any(p.get(k)!=old.get(k) for k in ('driverId','conductorId')):actions.add('trips.assign')
    if kind=='expenses' and (p.get('payrollId') or (old or {}).get('payrollId')):actions={'payroll.pay'}
    return actions
