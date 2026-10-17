"""Transport workflows over the existing tenant-scoped entity store.

No third-party application code is imported. All writes use the same company
transaction lock as legacy sync, including PostgreSQL deployments with workers.
"""
import math
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text


READ_ONLY_TYPES = {"ticket_holds", "ticket_waitlist", "ticket_closures"}
INACTIVE = {"Annulé", "Annulée", "Remboursé", "Expirée", "Convertie", "Libérée"}


def active(item):
    if item.get("deleted") or item.get("cancelled") or item.get("status") in INACTIVE:
        return False
    if item.get("expiresAt"):
        try:
            expiry = datetime.fromisoformat(item["expiresAt"].replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= datetime.now(timezone.utc):
                return False
        except (ValueError, TypeError):
            return False
    return True


def stops_for(trip):
    middle = trip.get("stops") or []
    if isinstance(middle, str):
        middle = middle.split(",")
    return [str(x).strip() for x in [trip.get("origin"), *middle, trip.get("destination")] if str(x or "").strip()]


def span(trip, item):
    stops = stops_for(trip)
    try:
        start = stops.index(str(item.get("boardingPoint") or trip.get("origin")))
        end = stops.index(str(item.get("dropPoint") or trip.get("destination")))
    except ValueError:
        raise HTTPException(422, "Arrêt inconnu sur cette ligne")
    if start >= end:
        raise HTTPException(422, "La descente doit suivre l’embarquement")
    return start, end


def overlap(trip, a, b):
    ai, aj = span(trip, a)
    try:
        bi, bj = span(trip, b)
    except HTTPException:
        return True  # Historical malformed records occupy the seat conservatively.
    return max(ai, bi) < min(aj, bj)


def bus_seats(bus):
    if bus.get("seats"):
        return bus["seats"]
    # Same fallback labels as the historical YamTrans client.
    return ([{"label":f"V{i+1}","class":"VIP"} for i in range(int(bus.get("vipSeats") or 0))]
            + [{"label":str(i+1),"class":"Simple"} for i in range(int(bus.get("simpleSeats") or 0))])


def route_fare(route, trip, payload, seat_class):
    """None preserves a historical route without a centrally configured tariff."""
    import re
    for line in re.split(r"[\n;]", str(route.get("segmentFares") or "")):
        match = re.fullmatch(r"\s*(.+?)\s*>\s*(.+?)\s*=\s*([\d.]+)\s*,\s*([\d.]+)\s*", line)
        if match and match[1].strip() == (payload.get("boardingPoint") or trip.get("origin")) and match[2].strip() == (payload.get("dropPoint") or trip.get("destination")):
            return float(match[4 if seat_class == "VIP" else 3])
    adult = "fareVip" if seat_class == "VIP" else "fareSimple"
    key = ("fareChildVip" if seat_class == "VIP" else "fareChildSimple") if payload.get("passengerCategory") == "child" else adult
    value = route.get(key, route.get(adult))
    if value is None or value == "":
        return None
    try:
        result = float(value)
        if not math.isfinite(result) or result < 0:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise HTTPException(422, "Tarif de ligne invalide")


def lock_company(db, Company, company_id):
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    else:
        db.scalar(select(Company).where(Company.id == company_id).with_for_update())


class SeatRequest(BaseModel):
    tripId: str = Field(min_length=1, max_length=120)
    seat: str = Field(min_length=1, max_length=30)
    boardingPoint: str = ""
    dropPoint: str = ""
    deviceId: str = Field(default="", max_length=120)
    holdId: str = ""


class ConfirmRequest(BaseModel):
    ticket: dict
    document: dict | None = None
    holdId: str = ""
    reservationId: str = ""


class BatchRequest(BaseModel):
    tickets: list[dict] = Field(min_length=1, max_length=20)
    bookingId: str = Field(min_length=1, max_length=120)


class RefundRequest(BaseModel):
    amount: float = Field(ge=0, allow_inf_nan=False)
    reason: str = Field(min_length=3, max_length=500)


class BoardingRequest(BaseModel):
    tripId: str = Field(min_length=1, max_length=120)
    documentNumber: str = Field(default='', max_length=100)


class WaitRequest(BaseModel):
    tripId: str
    passengerName: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=5, max_length=40)
    seatClass: str = "Simple"
    boardingPoint: str = ""
    dropPoint: str = ""


class ChangeBusRequest(BaseModel):
    busId: str
    reason: str = Field(min_length=3, max_length=500)


class RepeatRequest(BaseModel):
    dates: list[str] = Field(min_length=1, max_length=60)


class CloseRequest(BaseModel):
    countedCash: float = Field(ge=0, allow_inf_nan=False)
    note: str = Field(default="", max_length=500)


class ReservationRequest(SeatRequest):
    id: str = Field(min_length=1, max_length=120)
    passengerName: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=5, max_length=40)
    amount: float = Field(ge=0, allow_inf_nan=False)
    deposit: float = Field(default=0, ge=0, allow_inf_nan=False)
    expiresAt: str
    paymentMethod: str = "Espèces"


class CapacityRequest(BaseModel):
    cargoCapacityKg: float = Field(default=0, ge=0, allow_inf_nan=False)
    cargoCapacityCount: int = Field(default=0, ge=0)


class ExpenseRequest(BaseModel):
    amount: float = Field(gt=0, allow_inf_nan=False)
    reason: str = Field(min_length=3, max_length=500)
    paymentMethod: str = "Espèces"


class ManifestRequest(BaseModel):
    manifestId: str


def install(app, env):
    Entity, Company, User = env["EntityV3"], env["Company"], env["AppUser"]
    session, auth, now = env["db_session"], env["read_token"], env["utcnow"]

    def access(db, token, role, write=False):
        if write:
            lock_company(db, Company, token.get("cid"))
        c = env["require_company"](token, db)
        u = db.get(User, token.get("uid"))
        if not u or not u.active or u.company_id != c.id:
            raise HTTPException(403, "Compte société actif requis")
        if not (c.settings or {}).get("modules", {}).get("tickets", False):
            raise HTTPException(403, "Module Tickets non activé")
        manager = u.role in {"company_admin", "superuser", "admin"}
        roles = (u.modules or {}).get("ticketRoles", [])
        if not manager and (not (u.modules or {}).get("tickets") or (role not in roles and "manager" not in roles)):
            raise HTTPException(403, "Droit billetterie insuffisant")
        return c, u

    def rows(db, cid, kind):
        return [dict(r.payload) for r in db.scalars(select(Entity).where(Entity.company_id == cid, Entity.entity_type == kind, Entity.deleted.is_(False))).all()]

    def get(db, cid, kind, ident):
        row = db.get(Entity, {"company_id": cid, "entity_type": kind, "entity_id": ident})
        if not row or row.deleted:
            raise HTTPException(404, "Opération introuvable dans cette société")
        return dict(row.payload)

    def put(db, cid, kind, item):
        item = dict(item)
        ident = str(item.get("id") or uuid.uuid4())
        row = db.get(Entity, {"company_id": cid, "entity_type": kind, "entity_id": ident})
        version = row.version + 1 if row else 1
        item.update(id=ident, companyId=cid, _serverVersion=version, _serverUpdatedAt=now().isoformat(), updatedAt=now().isoformat())
        if row:
            row.payload, row.version, row.updated_at = item, version, now()
        else:
            db.add(Entity(company_id=cid, entity_type=kind, entity_id=ident, payload=item, version=version, updated_at=now(), deleted=False))
        db.flush()
        return item

    def audit(db, c, u, action, ref):
        put(db, c.id, "audit", {"id":str(uuid.uuid4()), "action":action, "details":ref, "at":now().isoformat(), "user":u.name, "createdBy":u.id, "agency":u.agency})

    def bookable(db, cid, trip_id):
        trip = get(db, cid, "ticket_trips", trip_id)
        if trip.get("status", "Publié") not in {"Publié", "Planifié", "Opérations", "Ouvert à la vente", "Embarquement"}:
            raise HTTPException(409, "Ce départ n’est plus ouvert à la vente")
        try:
            departure = datetime.fromisoformat(trip["departureAt"].replace("Z", "+00:00"))
            if departure.tzinfo is None:
                departure = departure.replace(tzinfo=timezone.utc)
            # Preserve the historical guichet's four-hour sale window. Explicit
            # Parti/Arrivé/Clôturé statuses still close sales immediately.
            if departure <= now()-timedelta(hours=4):
                raise HTTPException(409, "L’heure de départ est dépassée")
        except (KeyError, ValueError, TypeError):
            raise HTTPException(422, "Date de départ invalide")
        return trip

    def validate_seat(db, cid, payload, exclude_id="", reservation_id="", hold_id=""):
        trip = bookable(db, cid, payload["tripId"])
        span(trip, payload)
        bus = get(db, cid, "ticket_buses", str(trip.get("busId") or ""))
        labels = {str(x.get("label")) for x in bus_seats(bus)}
        if str(payload.get("seat")) not in labels:
            raise HTTPException(422, "Siège absent du plan du bus")
        for kind in ("tickets", "ticket_reservations", "ticket_holds"):
            for other in rows(db, cid, kind):
                if not active(other) or other.get("tripId") != payload["tripId"] or str(other.get("seat")) != str(payload.get("seat")):
                    continue
                if (kind == "tickets" and other.get("id") == exclude_id) or (kind == "ticket_reservations" and other.get("id") == reservation_id) or (kind == "ticket_holds" and other.get("id") == hold_id):
                    continue
                if overlap(trip, payload, other):
                    raise HTTPException(409, "Ce siège est déjà vendu ou réservé sur ce tronçon")
        return trip

    def validate_tariff(db, cid, payload, manager=False):
        tr = get(db, cid, "ticket_trips", str(payload.get("tripId") or ""))
        bus = get(db, cid, "ticket_buses", str(tr.get("busId") or ""))
        seat = next((s for s in bus_seats(bus) if str(s.get("label")) == str(payload.get("seat"))), None)
        if not seat:
            raise HTTPException(422, "Siège absent du plan du bus")
        route_row = db.get(Entity, {"company_id":cid,"entity_type":"ticket_routes","entity_id":str(tr.get("routeId") or "")})
        base = route_fare(route_row.payload if route_row and not route_row.deleted else {}, tr, payload, seat.get("class") or "Simple")
        if base is not None:
            discount = float(payload.get("discount") or 0)
            if discount < 0 or discount > base or (discount and not manager):
                raise HTTPException(403, "Seul le responsable peut autoriser une remise")
            if not math.isclose(float(payload.get("fare") or 0), base-discount, abs_tol=0.001):
                raise HTTPException(422, "Le tarif doit correspondre à la ligne et à la catégorie du voyageur")
        return base

    env["validate_transport_tariff"] = validate_tariff

    # Exposed to the legacy synchronization path: identical seat rules and lock.
    env["validate_transport_seat"] = validate_seat

    @app.post("/api/v2/transport/reservations")
    def reserve(req: ReservationRequest, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"sales",True)
        existing=db.get(Entity,{"company_id":c.id,"entity_type":"ticket_reservations","entity_id":req.id})
        if existing:
            if existing.payload.get("createdBy")!=u.id:
                raise HTTPException(403,"Réservation d’un autre agent")
            return existing.payload
        tr=validate_seat(db,c.id,req.model_dump())
        validate_tariff(db,c.id,{**req.model_dump(),"fare":req.amount,"discount":0},False)
        try:
            expiry=datetime.fromisoformat(req.expiresAt.replace("Z","+00:00"))
            if expiry.tzinfo is None:
                expiry=expiry.replace(tzinfo=timezone.utc)
            departure=datetime.fromisoformat(tr["departureAt"].replace("Z","+00:00"))
            if departure.tzinfo is None:
                departure=departure.replace(tzinfo=timezone.utc)
            if not now()<expiry<=departure:
                raise ValueError()
        except (ValueError,TypeError):
            raise HTTPException(422,"L’expiration doit être future et précéder le départ")
        if req.deposit>req.amount:
            raise HTTPException(422,"L’acompte dépasse le tarif")
        item=put(db,c.id,"ticket_reservations",{**req.model_dump(),"code":"RSV-"+req.id.replace("-","")[:10].upper(),"status":"Payée" if req.deposit>=req.amount else "Partiellement payée" if req.deposit else "Réservée","expiresAt":expiry.isoformat(),"createdBy":u.id,"createdByName":u.name,"agency":u.agency,"createdAt":now().isoformat()})
        db.commit()
        return item

    @app.post("/api/v2/transport/reservations/{ident}/cancel")
    def cancel_reservation(ident: str, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"sales",True)
        r=get(db,c.id,"ticket_reservations",ident)
        if r.get("status")=="Convertie":
            raise HTTPException(409,"La réservation a déjà été convertie")
        if float(r.get("deposit") or 0)>0:
            raise HTTPException(409,"Convertissez la réservation en billet puis traitez le remboursement de l’acompte")
        result=put(db,c.id,"ticket_reservations",{**r,"status":"Annulée","cancelledBy":u.id,"cancelledAt":now().isoformat()})
        db.commit()
        return result

    @app.put("/api/v2/transport/trips/{trip_id}/capacity")
    def capacity(trip_id: str, req: CapacityRequest, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"dispatch",True)
        tr=get(db,c.id,"ticket_trips",trip_id)
        result=put(db,c.id,"ticket_trips",{**tr,**req.model_dump()})
        audit(db,c,u,"Capacité de soute modifiée",trip_id)
        db.commit()
        return result

    @app.post("/api/v2/transport/trips/{trip_id}/expenses")
    def expense(trip_id: str, req: ExpenseRequest, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"reports",True)
        get(db,c.id,"ticket_trips",trip_id)
        result=put(db,c.id,"expenses",{**req.model_dump(),"tripId":trip_id,"description":req.reason,"label":req.reason,"category":"Voyage","createdAt":now().isoformat(),"createdBy":u.id,"agency":u.agency})
        audit(db,c,u,"Dépense du départ",trip_id)
        db.commit()
        return result

    @app.post("/api/v2/transport/trips/{trip_id}/manifests")
    def link_manifest(trip_id: str, req: ManifestRequest, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"dispatch",True)
        if (c.settings or {}).get("modules",{}).get("courier") is False or ((u.modules or {}).get("courier") is False and u.role not in {"company_admin","superuser","admin"}):
            raise HTTPException(403,"Droit Courrier requis")
        tr=get(db,c.id,"ticket_trips",trip_id)
        manifest=get(db,c.id,"manifests",req.manifestId)
        if manifest.get("tripId") and manifest["tripId"]!=trip_id:
            raise HTTPException(409,"Ce bordereau est déjà rattaché à un autre départ")
        span(tr,{"boardingPoint":manifest.get("origin"),"dropPoint":manifest.get("destination")})
        linked=put(db,c.id,"manifests",{**manifest,"tripId":trip_id})
        shipments=[]
        for ident in manifest.get("shipmentIds") or []:
            sh=get(db,c.id,"shipments",ident)
            shipments.append(put(db,c.id,"shipments",{**sh,"tripId":trip_id}))
        audit(db,c,u,"Bordereau rattaché au départ",req.manifestId+" : "+trip_id)
        db.commit()
        return {"manifest":linked,"shipments":shipments}

    @app.post("/api/v2/transport/holds")
    def hold(req: SeatRequest, token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, "sales", True)
        item = req.model_dump()
        if req.holdId:
            old = get(db, c.id, "ticket_holds", req.holdId)
            if old.get("createdBy") != u.id or old.get("deviceId") != req.deviceId:
                raise HTTPException(403, "Réservation temporaire d’un autre guichet")
        validate_seat(db, c.id, item, hold_id=req.holdId)
        # One live hold per user/device; changing seats releases the previous one.
        for old in rows(db, c.id, "ticket_holds"):
            if old.get("createdBy") == u.id and old.get("deviceId") == req.deviceId and active(old):
                put(db, c.id, "ticket_holds", {**old, "status":"Libérée"})
        result = put(db, c.id, "ticket_holds", {**item, "id":str(uuid.uuid4()), "createdBy":u.id, "status":"Réservée", "expiresAt":(now()+timedelta(minutes=5)).isoformat()})
        db.commit()
        return result

    @app.delete("/api/v2/transport/holds/{hold_id}")
    def release(hold_id: str, token=Depends(auth), db=Depends(session)):
        c, u = access(db, token, "sales", True)
        item = get(db, c.id, "ticket_holds", hold_id)
        if item.get("createdBy") != u.id:
            raise HTTPException(403, "Réservation temporaire d’un autre agent")
        result = put(db, c.id, "ticket_holds", {**item, "status":"Libérée"})
        db.commit()
        return result

    def issue_ticket(req, c, u, db):
        t = dict(req.ticket)
        if any(not str(t.get(k) or "").strip() for k in ("id","tripId","seat","passengerName","phone")):
            raise HTTPException(422, "Référence, voyage, siège, passager et téléphone requis")
        existing = db.get(Entity, {"company_id":c.id,"entity_type":"tickets","entity_id":str(t["id"])})
        if existing:
            if existing.payload.get("createdBy") != u.id:
                raise HTTPException(403, "Billet d’un autre agent")
            # Retry returns the original operation without charging or allocating twice.
            return {"ticket":existing.payload}
        reservation = None
        if req.reservationId:
            reservation = get(db, c.id, "ticket_reservations", req.reservationId)
            if not active(reservation) or reservation.get("tripId") != t.get("tripId") or str(reservation.get("seat")) != str(t.get("seat")):
                raise HTTPException(409, "Réservation expirée ou différente du billet")
        if req.holdId:
            h = get(db, c.id, "ticket_holds", req.holdId)
            if h.get("createdBy") != u.id or not active(h) or any(str(h.get(k) or "") != str(t.get(k) or "") for k in ("tripId","seat","boardingPoint","dropPoint")):
                raise HTTPException(409, "Le blocage du siège a expiré ou a changé")
        trip = validate_seat(db, c.id, t, reservation_id=req.reservationId, hold_id=req.holdId)
        for field in ("fare", "paid", "discount"):
            try:
                val = float(t.get(field) or 0)
            except (ValueError, TypeError):
                raise HTTPException(422, "Montant invalide")
            if not math.isfinite(val) or val < 0:
                raise HTTPException(422, "Montant invalide")
            t[field] = val
        validate_tariff(db, c.id, t, u.role in {"company_admin","superuser","admin"} or "manager" in (u.modules or {}).get("ticketRoles", []))
        if t["paid"] > t["fare"]:
            raise HTTPException(422, "Le paiement dépasse le tarif")
        if reservation and t["paid"] < float(reservation.get("deposit") or 0):
            raise HTTPException(422, "Le billet doit reprendre l’acompte déjà versé")
        if reservation and float(reservation.get("deposit") or 0)>0 and t.get("paymentMethod","Espèces")!=reservation.get("paymentMethod","Espèces"):
            raise HTTPException(422,"Le complément doit utiliser le même mode de paiement que l’acompte")
        if reservation and any(str(reservation.get(k) or trip.get(default) or "")!=str(t.get(k) or trip.get(default) or "") for k,default in (("boardingPoint","origin"),("dropPoint","destination"))):
            raise HTTPException(422,"Le billet doit reprendre le tronçon de la réservation")
        bus=get(db,c.id,"ticket_buses",trip["busId"])
        seat=next(s for s in bus_seats(bus) if str(s.get("label"))==str(t["seat"]))
        t["seatClass"]=seat.get("class") or "Simple"
        t["busLabel"]=f'{bus.get("name","")} {bus.get("registration","")}'.strip()
        # Register the private document in the same transaction as the paid ticket.
        # Never copy the photograph into tickets, sync payloads or public views.
        t.pop("documentPhoto", None)
        t.pop("photo", None)
        if req.document is not None:
            from .operations import DocumentRequest
            from pydantic import ValidationError
            try:
                doc_req=DocumentRequest.model_validate({**req.document,"id":"sale-document-"+str(t["id"]),"customerName":t["passengerName"],"phone":t["phone"]})
            except ValidationError:
                raise HTTPException(422,"Informations de la pièce incomplètes ou invalides")
            number="".join(doc_req.number.upper().split())
            if number!="".join(str(t.get("documentNumber") or "").upper().split()):
                raise HTTPException(422,"Le numéro confirmé doit correspondre à la pièce du billet")
            if doc_req.expiresOn:
                try: expired=datetime.strptime(doc_req.expiresOn,"%Y-%m-%d").date()<now().date()
                except ValueError: raise HTTPException(422,"Date d’expiration invalide")
                if expired: raise HTTPException(422,"Pièce expirée : renouvellement requis")
            if doc_req.photo:
                from .identity_ocr import decode_image
                decode_image(doc_req.photo)
            same_name=lambda a,b:" ".join(str(a).casefold().split())==" ".join(str(b).casefold().split())
            same_phone=lambda a,b:"".join(x for x in str(a) if x.isdigit())=="".join(x for x in str(b) if x.isdigit())
            registered=next((d for d in rows(db,c.id,"customer_documents") if d.get("active") and d.get("number")==number),None)
            if registered:
                if not same_name(registered.get("customerName"),t["passengerName"]) or not same_phone(registered.get("phone"),t["phone"]):
                    raise HTTPException(409,"Cette pièce appartient à un autre profil : contrôlez le nom et le téléphone dans Identité client")
                if registered.get("expiresOn") and registered["expiresOn"]<now().date().isoformat():
                    raise HTTPException(409,"Pièce expirée : renouvellement requis")
                customer_id=registered["customerId"]
                if doc_req.photo:
                    put(db,c.id,"customer_documents",{**registered,"photo":doc_req.photo})
            else:
                customer=next((cst for cst in rows(db,c.id,"ticket_customers") if same_phone(cst.get("phone"),t["phone"]) and same_name(cst.get("name"),t["passengerName"])),None)
                customer_id=customer["id"] if customer else str(uuid.uuid4())
                if not customer: put(db,c.id,"ticket_customers",{"id":customer_id,"name":t["passengerName"],"phone":t["phone"],"points":0})
                put(db,c.id,"customer_documents",{**doc_req.model_dump(),"customerId":customer_id,"number":number,"active":True,"createdBy":u.id,"createdAt":now().isoformat()})
            if t.get("customerId") and t["customerId"]!=customer_id:
                raise HTTPException(422,"La pièce et le carnet ne correspondent pas au même client")
            t["customerId"]=customer_id
            t["documentNumber"]=number
            audit(db,c,u,"Pièce contrôlée à la vente",str(t["id"]))
        pack = None
        if t.get("packId"):
            pack=get(db,c.id,"travel_packs",str(t["packId"]))
            if pack.get("customerId") != t.get("customerId") or pack.get("routeId") != trip.get("routeId") or pack.get("seatClass") != t["seatClass"]:
                raise HTTPException(422,"Le carnet ne correspond pas au client, à la ligne ou à la classe")
            if str(pack.get("expiresOn") or "") < now().date().isoformat() or int(pack.get("remaining") or 0)<1:
                raise HTTPException(409,"Carnet expiré ou épuisé")
            if t["paid"] != 0:
                raise HTTPException(422,"Un voyage prépayé ne doit pas être encaissé une seconde fois")
        if t.get("documentNumber"):
            normalized="".join(str(t["documentNumber"]).upper().split())
            doc=next((d for d in rows(db,c.id,"customer_documents") if d.get("active") and d.get("number")==normalized),None)
            if doc:
                if t.get("customerId") and t["customerId"] != doc["customerId"]:
                    raise HTTPException(422,"La pièce et le carnet ne correspondent pas au même client")
                t["customerId"]=doc["customerId"]
        t.update(createdBy=u.id, createdByName=u.name, agency=u.agency, status="Confirmé", boarded=False, noShow=False, balance=max(0,t["fare"]-t["paid"]), origin=trip.get("origin"), destination=trip.get("destination"), departureAt=trip.get("departureAt"), createdAt=now().isoformat(), confirmationSource="server")
        t = put(db, c.id, "tickets", t)
        if pack:
            t=put(db,c.id,"tickets",{**t,"balance":0,"paymentMethod":"Carnet prépayé"})
            put(db,c.id,"travel_packs",{**pack,"remaining":int(pack["remaining"])-1,"redemptions":[*pack.get("redemptions",[]),{"ticketId":t["id"],"at":now().isoformat()}]})
        if req.holdId:
            put(db, c.id, "ticket_holds", {**h,"status":"Convertie","ticketId":t["id"]})
        if reservation:
            put(db, c.id, "ticket_reservations", {**reservation,"status":"Convertie","ticketId":t["id"]})
        audit(db,c,u,"Billet confirmé",str(t.get("pnr") or t["id"]))
        return {"ticket":t}

    @app.get("/api/v2/transport/tickets/{ticket_id}")
    def recover_ticket(ticket_id: str, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"sales",True)
        t=get(db,c.id,"tickets",ticket_id)
        if t.get("createdBy")!=u.id and u.role not in {"admin","company_admin","superuser"}:
            raise HTTPException(403,"Billet d’un autre agent")
        db.commit()
        return {"ticket":t}

    @app.post("/api/v2/transport/tickets/confirm")
    def confirm(req: ConfirmRequest, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"sales",True)
        result=issue_ticket(req,c,u,db)
        customer_id=result['ticket'].get('customerId')
        if customer_id:
            result['customer']=next((p for p in rows(db,c.id,'ticket_customers') if p['id']==customer_id),None)
        db.commit()
        return result

    @app.post("/api/v2/transport/tickets/{ticket_id}/board")
    def board_ticket(ticket_id: str, req: BoardingRequest, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"boarding",True)
        t=get(db,c.id,"tickets",ticket_id)
        if t.get("tripId")!=req.tripId:
            raise HTTPException(409,"Mauvais départ : faites transférer le billet par un responsable")
        if not active(t): raise HTTPException(409,"Billet annulé ou remboursé")
        trip=get(db,c.id,"ticket_trips",req.tripId)
        try: departure=datetime.fromisoformat(str(trip.get("departureAt") or '').replace('Z','+00:00'))
        except ValueError: raise HTTPException(422,"Date du départ invalide")
        if departure.date()!=now().date():
            raise HTTPException(409,"Ce billet concerne un autre jour : transfert requis")
        if trip.get("status") in {"Annulé","Terminé","Clôturé","Arrivé"}:
            raise HTTPException(409,"Embarquement fermé pour ce départ")
        if req.documentNumber:
            number="".join(req.documentNumber.upper().split())
            doc=next((d for d in rows(db,c.id,"customer_documents") if d.get("active") and d.get("number")==number),None)
            if not doc or (t.get("customerId")!=doc.get("customerId") and "".join(str(t.get("documentNumber") or "").upper().split())!=number):
                raise HTTPException(403,"Cette pièce ne correspond pas au billet")
            if doc.get("expiresOn") and doc["expiresOn"]<now().date().isoformat():
                raise HTTPException(409,"Pièce expirée : renouvellement requis")
        if t.get("boarded"):
            db.commit();return {"ticket":t,"alreadyBoarded":True}
        if float(t.get("balance") or 0)>0:
            raise HTTPException(409,"Le solde du billet doit être réglé avant embarquement")
        stamp=now().isoformat()
        t=put(db,c.id,"tickets",{**t,"boarded":True,"boardedAt":stamp,"boardedBy":u.id,"noShow":False})
        boarding=put(db,c.id,"ticket_boardings",{"id":"boarding-"+ticket_id,"ticketId":ticket_id,"pnr":t.get("pnr"),"tripId":req.tripId,"agency":u.agency,"createdBy":u.id,"createdAt":stamp,"method":"document" if req.documentNumber else "ticket"})
        audit(db,c,u,"Embarquement confirmé",str(t.get("pnr") or ticket_id));db.commit()
        return {"ticket":t,"boarding":boarding,"alreadyBoarded":False}

    @app.post("/api/v2/transport/bookings/confirm")
    def confirm_batch(req: BatchRequest, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"sales",True)
        ids=[str(t.get("id") or "") for t in req.tickets]
        if len(set(ids))!=len(ids):
            raise HTTPException(422,"Chaque billet doit avoir une référence distincte")
        result=[]
        for t in req.tickets:
            result.append(issue_ticket(ConfirmRequest(ticket={**t,"bookingGroupId":req.bookingId}),c,u,db)["ticket"])
        db.commit()
        return {"bookingId":req.bookingId,"tickets":result}

    @app.post("/api/v2/transport/tickets/{ticket_id}/refund")
    def refund(ticket_id: str, req: RefundRequest, token=Depends(auth), db=Depends(session)):
        c,u = access(db,token,"manager",True)
        t = get(db,c.id,"tickets",ticket_id)
        if not active(t) or t.get("boarded"):
            raise HTTPException(409,"Billet annulé, remboursé ou déjà embarqué")
        if req.amount > float(t.get("paid") or 0):
            raise HTTPException(422,"Le remboursement dépasse le montant encaissé")
        r = put(db,c.id,"ticket_refunds",{"ticketId":ticket_id,"pnr":t.get("pnr"),"tripId":t.get("tripId"),"amount":req.amount,"reason":req.reason,"status":"Validé","paymentMethod":t.get("paymentMethod"),"agency":u.agency,"createdBy":u.id,"createdByName":u.name,"createdAt":now().isoformat()})
        t = put(db,c.id,"tickets",{**t,"status":"Remboursé","refundId":r["id"],"refundedAmount":req.amount,"refundReason":req.reason,"cancelledAt":now().isoformat()})
        if t.get("packId"):
            pack=get(db,c.id,"travel_packs",t["packId"])
            redemptions=[{**r,"returnedAt":now().isoformat()} if r.get("ticketId")==ticket_id else r for r in pack.get("redemptions",[])]
            put(db,c.id,"travel_packs",{**pack,"remaining":min(int(pack["journeys"]),int(pack["remaining"])+1),"redemptions":redemptions})
        audit(db,c,u,"Billet remboursé",str(t.get("pnr")))
        db.commit()
        return {"ticket":t,"refund":r}

    @app.post("/api/v2/transport/waitlist")
    def add_wait(req: WaitRequest, token=Depends(auth), db=Depends(session)):
        c,u = access(db,token,"sales",True)
        tr = bookable(db,c.id,req.tripId)
        span(tr,req.model_dump())
        existing = next((r for r in rows(db,c.id,"ticket_waitlist") if r.get("tripId")==req.tripId and r.get("phone")==req.phone and r.get("status")=="En attente"),None)
        if existing:
            return existing
        r=put(db,c.id,"ticket_waitlist",{**req.model_dump(),"status":"En attente","createdAt":now().isoformat(),"createdBy":u.id,"agency":u.agency})
        db.commit()
        return r

    @app.post("/api/v2/transport/waitlist/{ident}/close")
    def close_wait(ident: str, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"sales",True)
        r=get(db,c.id,"ticket_waitlist",ident)
        result=put(db,c.id,"ticket_waitlist",{**r,"status":"Traitée","closedBy":u.id,"closedAt":now().isoformat()})
        db.commit()
        return result

    @app.post("/api/v2/transport/trips/{trip_id}/bus")
    def change_bus(trip_id: str, req: ChangeBusRequest, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"dispatch",True)
        tr=get(db,c.id,"ticket_trips",trip_id)
        bus=get(db,c.id,"ticket_buses",req.busId)
        if tr.get("status") in {"Annulé","Terminé","Arrivé"} or bus.get("active") is False or bus.get("status") in {"En panne","Maintenance","Indisponible"}:
            raise HTTPException(409,"Départ ou bus indisponible")
        labels={str(s.get("label")):s for s in bus_seats(bus)}
        allocated=[r for kind in ("tickets","ticket_reservations","ticket_holds") for r in rows(db,c.id,kind) if r.get("tripId")==trip_id and active(r)]
        missing=sorted({str(r.get("seat")) for r in allocated if str(r.get("seat")) not in labels})
        if missing:
            raise HTTPException(409,"Le nouveau plan ne contient pas les sièges occupés : "+", ".join(missing))
        for r in allocated:
            new_class=labels[str(r["seat"])].get("class")
            if r.get("seatClass") and new_class and r["seatClass"]!=new_class:
                raise HTTPException(409,"Classe de siège différente : "+str(r["seat"]))
        old=tr.get("busId")
        tr=put(db,c.id,"ticket_trips",{**tr,"busId":req.busId,"busChanges":[*(tr.get("busChanges") or []),{"from":old,"to":req.busId,"reason":req.reason,"at":now().isoformat(),"by":u.id}]})
        changed=[]
        for t in rows(db,c.id,"tickets"):
            if t.get("tripId")==trip_id and active(t):
                changed.append(put(db,c.id,"tickets",{**t,"busLabel":f'{bus.get("name","")} {bus.get("registration","")}'.strip()}))
        audit(db,c,u,"Bus remplacé",trip_id+" : "+req.reason)
        db.commit()
        return {"trip":tr,"tickets":changed}

    @app.post("/api/v2/transport/trips/{trip_id}/repeat")
    def repeat(trip_id: str, req: RepeatRequest, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"dispatch",True)
        tr=get(db,c.id,"ticket_trips",trip_id)
        try:
            original=datetime.fromisoformat(tr["departureAt"].replace("Z","+00:00"))
            dates=sorted({datetime.strptime(d,"%Y-%m-%d").date() for d in req.dates})
        except (ValueError,KeyError):
            raise HTTPException(422,"Dates au format AAAA-MM-JJ requises")
        result=[]
        for d in dates:
            at=original.replace(year=d.year,month=d.month,day=d.day)
            if at.replace(tzinfo=timezone.utc)<=now():
                raise HTTPException(422,"Choisissez des départs futurs")
            ident=str(uuid.uuid5(uuid.NAMESPACE_URL,c.id+":"+trip_id+":"+d.isoformat()))
            existing=db.get(Entity,{"company_id":c.id,"entity_type":"ticket_trips","entity_id":ident})
            if existing:
                result.append(existing.payload)
                continue
            # Explicit allowlist prevents copying arrival/manifest/dispatch state.
            copy={k:tr[k] for k in ("routeId","busId","origin","destination","stops","boardingPoint","dropPoint","fareSimple","fareVip","fareChildSimple","fareChildVip","capacityOverride","driver","conductor","driverId","conductorId","cargoCapacityKg","cargoCapacityCount") if k in tr}
            result.append(put(db,c.id,"ticket_trips",{**copy,"id":ident,"departureAt":at.isoformat(),"status":"Planifié","repeatSourceId":trip_id,"createdAt":now().isoformat(),"createdBy":u.id}))
        audit(db,c,u,"Départs récurrents créés",trip_id)
        db.commit()
        return {"trips":result}

    def overview(db,cid,trip_id):
        tr=get(db,cid,"ticket_trips",trip_id)
        tickets=[t for t in rows(db,cid,"tickets") if t.get("tripId")==trip_id and active(t)]
        bags=[b for b in rows(db,cid,"ticket_baggage") if b.get("tripId")==trip_id and active(b)]
        shipments=[s for s in rows(db,cid,"shipments") if s.get("tripId")==trip_id and active(s)]
        linked={t["id"]:t for t in tickets}
        warnings=[]
        for b in bags:
            t=linked.get(b.get("ticketId"))
            if b.get("baggageType","accompanied")=="accompanied" and (not t or not t.get("boarded")):
                warnings.append({"kind":"owner_not_boarded","code":b.get("code"),"message":"Bagage accompagné sans passager embarqué"})
            if b.get("status") not in {"Chargé","Arrivé","Retiré"}:
                warnings.append({"kind":"not_loaded","code":b.get("code"),"message":"Bagage non chargé"})
        for sh in shipments:
            if sh.get("status") not in {"Expédié","Arrivé à destination","Disponible pour retrait","Livré"}:
                warnings.append({"kind":"courier_not_dispatched","code":sh.get("code"),"message":"Colis du bordereau non expédié"})
        weight=sum(float(b.get("weight") or 0) for b in [*bags,*shipments])
        count=sum(int(b.get("count") or 1) for b in bags)+sum(int(s.get("parcelCount") or 1) for s in shipments)
        for field,total in (("cargoCapacityKg",weight),("cargoCapacityCount",count)):
            if float(tr.get(field) or 0)>0 and total>float(tr[field]):
                warnings.append({"kind":"capacity","message":"Capacité de soute dépassée : "+field})
        refunds=[r for r in rows(db,cid,"ticket_refunds") if r.get("tripId")==trip_id and r.get("status")=="Validé"]
        expenses=[e for e in rows(db,cid,"expenses") if e.get("tripId")==trip_id and active(e)]
        deposits=[r for r in rows(db,cid,"ticket_reservations") if r.get("tripId")==trip_id and r.get("status")!="Convertie" and not r.get("deleted")]
        deposit_income=sum(float(r.get("deposit") or 0) for r in deposits)
        # Original receipts remain receipts after a refund; refunds are distinct outflows.
        all_tickets=[t for t in rows(db,cid,"tickets") if t.get("tripId")==trip_id and (active(t) or t.get("status")=="Remboursé")]
        ticket_income=sum(float(t.get("paid") or 0) for t in all_tickets)
        bag_income=sum(float(b.get("paid") or 0) for b in bags)
        courier_income=sum(float(s.get("fee") or 0) for s in shipments)
        refunded=sum(float(r.get("amount") or 0) for r in refunds)
        cost=sum(float(e.get("amount") or 0) for e in expenses)
        cash=sum(float(t.get("paid") or 0) for t in all_tickets if t.get("paymentMethod","Espèces")=="Espèces")+sum(float(b.get("paid") or 0) for b in bags if b.get("paymentMethod","Espèces")=="Espèces")+sum(float(r.get("deposit") or 0) for r in deposits if r.get("paymentMethod","Espèces")=="Espèces")-sum(float(r.get("amount") or 0) for r in refunds if r.get("paymentMethod","Espèces")=="Espèces")-sum(float(e.get("amount") or 0) for e in expenses if e.get("paymentMethod","Espèces")=="Espèces")
        closures=[r for r in rows(db,cid,"ticket_closures") if r.get("tripId")==trip_id]
        cash+=sum(float(s.get("fee") or 0) for s in shipments if s.get("paymentMethod","Espèces")=="Espèces")
        return {"trip":tr,"tickets":tickets,"baggage":bags,"shipments":shipments,"warnings":warnings,"weightKg":weight,"baggageCount":count,"boarded":sum(bool(t.get("boarded")) for t in tickets),"ticketIncome":ticket_income,"baggageIncome":bag_income,"courierIncome":courier_income,"depositIncome":deposit_income,"refunds":refunded,"expenses":cost,"net":ticket_income+bag_income+courier_income+deposit_income-refunded-cost,"expectedCash":cash,"closures":closures}

    @app.get("/api/v2/transport/trips/{trip_id}/overview")
    def read_overview(trip_id: str, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"dispatch")
        result=overview(db,c.id,trip_id)
        if u.role not in {"company_admin","superuser","admin"} and not set((u.modules or {}).get("ticketRoles",[])) & {"reports","manager"}:
            for key in ("ticketIncome","baggageIncome","courierIncome","depositIncome","refunds","expenses","net","expectedCash","closures"):
                result.pop(key,None)
        return result

    @app.post("/api/v2/transport/trips/{trip_id}/closure")
    def closure(trip_id: str, req: CloseRequest, token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"reports",True)
        if any(r.get("tripId")==trip_id for r in rows(db,c.id,"ticket_closures")):
            raise HTTPException(409,"Ce départ a déjà une clôture ; consultez le relevé enregistré")
        data=overview(db,c.id,trip_id)
        snapshot={k:data[k] for k in ("ticketIncome","baggageIncome","courierIncome","depositIncome","refunds","expenses","net","expectedCash")}
        result=put(db,c.id,"ticket_closures",{"tripId":trip_id,**snapshot,**req.model_dump(),"difference":req.countedCash-data["expectedCash"],"createdAt":now().isoformat(),"createdBy":u.id,"createdByName":u.name})
        audit(db,c,u,"Clôture du départ",trip_id)
        db.commit()
        return result

    @app.get("/api/v2/transport/state")
    def state(token=Depends(auth), db=Depends(session)):
        c,u=access(db,token,"sales")
        return {"holds":[{k:r.get(k) for k in ("id","tripId","seat","boardingPoint","dropPoint","status","expiresAt")} for r in rows(db,c.id,"ticket_holds") if active(r)],"waitlist":rows(db,c.id,"ticket_waitlist")}
