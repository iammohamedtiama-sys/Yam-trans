import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote_plus
from urllib import request as urlrequest, error as urlerror

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, UniqueConstraint, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./yamtrans-sync.db")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN_SECRET = os.getenv("TOKEN_SECRET") or os.getenv("SYNC_API_KEY") or "CHANGE-ME-NOW"
CORS_ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]
DEFAULT_COMPANY_CODE = os.getenv("DEFAULT_COMPANY_CODE", "YAMTRANS").strip().upper()
DEFAULT_COMPANY_NAME = os.getenv("COMPANY_NAME", "Yam-Trans")
DEFAULT_COMPANY_PHONE = os.getenv("COMPANY_PHONE", "+226 70 00 00 00")
DEFAULT_ADMIN_USER = os.getenv("DEFAULT_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
PLATFORM_ADMIN_USER = os.getenv("PLATFORM_ADMIN_USER", "platform")
PLATFORM_ADMIN_PASSWORD = os.getenv("PLATFORM_ADMIN_PASSWORD", "ChangeMe-Platform-Admin!")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Tables v3 : on ne modifie pas les anciennes tables afin de conserver une migration sûre.
class Company(Base):
    __tablename__ = "companies_v3"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(80), default="")
    logo_url: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AppUser(Base):
    __tablename__ = "app_users_v3"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(40))
    agency: Mapped[str] = mapped_column(String(160), default="Toutes")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    modules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("company_id", "username", name="uq_v3_user_company_username"),)


class EntityV3(Base):
    __tablename__ = "sync_entities_v3"
    company_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class ShipmentIndexV3(Base):
    __tablename__ = "shipment_index_v3"
    company_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(120), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(120), index=True)
    public_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SequenceV3(Base):
    __tablename__ = "sequences_v3"
    company_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sequence_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    current_value: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Base.metadata.create_all(engine)
with engine.begin() as conn:
    try:
        conn.execute(text("ALTER TABLE app_users_v3 ADD COLUMN IF NOT EXISTS modules JSON"))
    except Exception:
        try: conn.execute(text("ALTER TABLE app_users_v3 ADD COLUMN modules JSON"))
        except Exception: pass
app = FastAPI(title="YAM TRANS Multi-Sociétés · Courrier & Billetterie", version="4.6.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

ALLOWED_TYPES = {
    "shipments", "customers", "manifests", "withdrawals", "expenses", "payments",
    "agencies", "routes", "stations", "vehicles", "schedules", "audit",
    "tickets", "ticket_buses", "ticket_routes", "ticket_trips", "ticket_boardings",
    "ticket_customers", "ticket_promos", "ticket_refunds", "ticket_reservations", "ticket_baggage", "loyalty_transactions", "notification_logs",
}
GLOBAL_TYPES = {"agencies", "routes", "stations", "vehicles", "schedules", "ticket_buses", "ticket_routes", "ticket_trips", "ticket_promos"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 180_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def password_verify(password: str, encoded: str) -> bool:
    try:
        kind, it, salt64, expected64 = encoded.split("$", 3)
        if kind != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt64), int(it))
        return hmac.compare_digest(base64.b64encode(digest).decode(), expected64)
    except Exception:
        return False


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64urldecode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def make_token(user: AppUser, company: Optional[Company]) -> str:
    payload = {
        "uid": user.id,
        "cid": company.id if company else None,
        "cc": company.code if company else "PLATFORM",
        "role": user.role,
        "agency": user.agency,
        "exp": int((utcnow() + timedelta(days=30)).timestamp()),
    }
    raw = b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = b64url(hmac.new(TOKEN_SECRET.encode(), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{sig}"


def read_token(authorization: str = Header(default="")) -> dict[str, Any]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentification requise")
    token = authorization[7:].strip()
    try:
        raw, sig = token.split(".", 1)
        expected = b64url(hmac.new(TOKEN_SECRET.encode(), raw.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        payload = json.loads(b64urldecode(raw))
        if int(payload.get("exp", 0)) < int(utcnow().timestamp()):
            raise ValueError("expired")
        return payload
    except Exception:
        raise HTTPException(401, "Session invalide ou expirée")


def ensure_seed_data():
    with SessionLocal() as db:
        company = db.scalar(select(Company).where(Company.code == DEFAULT_COMPANY_CODE))
        if not company:
            company = Company(
                id=str(uuid.uuid4()), code=DEFAULT_COMPANY_CODE, name=DEFAULT_COMPANY_NAME,
                phone=DEFAULT_COMPANY_PHONE, logo_url="", active=True,
                settings={"trackingBaseUrl": PUBLIC_BASE_URL + "/suivi", "primaryColor":"#075f4e", "secondaryColor":"#063d34", "accentColor":"#1769df", "trackingTitle":"Suivez votre envoi", "trackingSubtitle":"Du dépôt jusqu’au point de retrait, étape par étape."}, created_at=utcnow(),
            )
            db.add(company)
            db.flush()
        admin = db.scalar(select(AppUser).where(AppUser.company_id == company.id, AppUser.username == DEFAULT_ADMIN_USER))
        if not admin:
            db.add(AppUser(id=str(uuid.uuid4()), company_id=company.id, username=DEFAULT_ADMIN_USER,
                           name="Administrateur", password_hash=password_hash(DEFAULT_ADMIN_PASSWORD),
                           role="company_admin", agency="Toutes", active=True, modules={"courier":True,"tickets":True,"ticketRoles":["sales","boarding","dispatch","manager","reports"]}, created_at=utcnow()))
        # Comptes historiques Yam-Trans conservés pour faciliter la migration v2 -> v3.
        if company.code == "YAMTRANS":
            legacy_users = [
                ("super", "Super utilisateur", "super123", "superuser", "Toutes"),
                ("ouaga", "Agence Ouagadougou", "ouaga123", "agency", "Ouagadougou"),
                ("abidjan", "Agence Abidjan", "abidjan123", "agency", "Abidjan"),
            ]
            for username, name, password, role, agency in legacy_users:
                exists = db.scalar(select(AppUser).where(AppUser.company_id == company.id, AppUser.username == username))
                if not exists:
                    db.add(AppUser(id=str(uuid.uuid4()), company_id=company.id, username=username, name=name,
                                   password_hash=password_hash(password), role=role, agency=agency,
                                   active=True, modules={"courier":True,"tickets":True,"ticketRoles":["sales","boarding","dispatch"]}, created_at=utcnow()))
        platform = db.scalar(select(AppUser).where(AppUser.company_id.is_(None), AppUser.username == PLATFORM_ADMIN_USER))
        if not platform:
            db.add(AppUser(id=str(uuid.uuid4()), company_id=None, username=PLATFORM_ADMIN_USER,
                           name="Super Super Admin", password_hash=password_hash(PLATFORM_ADMIN_PASSWORD),
                           role="platform_admin", agency="Toutes", active=True, modules={"courier":True,"tickets":True,"ticketRoles":["sales","boarding","dispatch"]}, created_at=utcnow()))
        db.commit()

        # Migration automatique des anciennes données vers la société par défaut, une seule fois.
        count = db.scalar(select(EntityV3).where(EntityV3.company_id == company.id).limit(1))
        if not count:
            try:
                rows = db.execute(text("SELECT entity_type, entity_id, payload, updated_at, deleted FROM sync_entities")).mappings().all()
                for r in rows:
                    payload = dict(r["payload"] or {})
                    payload["companyId"] = company.id
                    payload["_serverVersion"] = 1
                    dt = r["updated_at"] or utcnow()
                    db.add(EntityV3(company_id=company.id, entity_type=r["entity_type"], entity_id=r["entity_id"],
                                    payload=payload, version=1, updated_at=dt, deleted=bool(r["deleted"])))
                    if r["entity_type"] == "shipments" and not r["deleted"] and payload.get("code"):
                        code = str(payload["code"]).upper()
                        db.merge(ShipmentIndexV3(company_id=company.id, code=code, entity_id=r["entity_id"],
                                                 public_payload={}, updated_at=dt))
                db.commit()
            except Exception:
                db.rollback()


ensure_seed_data()


class LoginRequest(BaseModel):
    company: str
    username: str
    password: str
    deviceId: str = ""


class SyncRequest(BaseModel):
    deviceId: str
    agency: str = ""
    userId: str = ""
    entities: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class ReserveRequest(BaseModel):
    agencyCode: str
    count: int = Field(default=100, ge=10, le=1000)


class UserCreateRequest(BaseModel):
    name: str
    username: str
    password: str
    role: str = "agency"
    agency: str = "Toutes"
    companyCode: str = ""
    modules: dict[str, Any] = Field(default_factory=lambda:{"courier":True,"baggage":True,"tickets":False,"ticketRoles":["sales"]})


class CompanyCreateRequest(BaseModel):
    code: str
    name: str
    phone: str = ""
    logoUrl: str = ""
    primaryColor: str = "#075f4e"
    secondaryColor: str = "#063d34"
    accentColor: str = "#1769df"
    trackingTitle: str = "Suivez votre envoi"
    trackingSubtitle: str = "Du dépôt jusqu’au point de retrait, étape par étape."
    supportEmail: str = ""
    website: str = ""
    heroImageUrl: str = ""
    adminName: str = "Administrateur"
    adminUsername: str = "admin"
    adminPassword: str
    modules: dict[str, bool] = Field(default_factory=lambda:{"courier":True,"baggage":True,"tickets":False})
    features: dict[str, bool] = Field(default_factory=lambda:{"sms":False,"whatsapp":False})


class CompanyProfileRequest(BaseModel):
    name: str = ""
    phone: str = ""
    logoUrl: str = ""
    primaryColor: str = ""
    secondaryColor: str = ""
    accentColor: str = ""
    trackingTitle: str = ""
    trackingSubtitle: str = ""
    supportEmail: str = ""
    website: str = ""
    heroImageUrl: str = ""


class CompanyPlatformUpdateRequest(BaseModel):
    name: str = ""
    phone: str = ""
    active: Optional[bool] = None
    primaryColor: str = ""
    secondaryColor: str = ""
    accentColor: str = ""
    trackingTitle: str = ""
    trackingSubtitle: str = ""
    supportEmail: str = ""
    website: str = ""
    heroImageUrl: str = ""
    modules: Optional[dict[str, bool]] = None
    features: Optional[dict[str, bool]] = None


class PlatformUserUpdateRequest(BaseModel):
    name: str = ""
    username: str = ""
    role: str = ""
    agency: str = ""
    active: Optional[bool] = None
    newPassword: str = ""
    modules: Optional[dict[str, Any]] = None


class CapabilityRequest(BaseModel):
    modules: dict[str, bool] = Field(default_factory=dict)
    features: dict[str, bool] = Field(default_factory=dict)
    messaging: dict[str, Any] = Field(default_factory=dict)

class PlatformOperationRequest(BaseModel):
    action: str = "update"
    patch: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class NotificationSendRequest(BaseModel):
    channel: str
    to: str
    message: str
    kind: str = "generic"
    reference: str = ""
    ticketUrl: str = ""

def user_public(u: AppUser) -> dict[str, Any]:
    return {"id": u.id, "name": u.name, "username": u.username, "role": u.role, "agency": u.agency, "active": u.active, "modules": u.modules or {"courier":True,"baggage":True,"tickets":False,"ticketRoles":[]}}


def company_public(c: Company, include_logo: bool = True, include_secrets: bool = False) -> dict[str, Any]:
    settings = dict(c.settings or {})
    settings.setdefault("modules", {"courier": True, "tickets": False})
    settings.setdefault("features", {"sms": False, "whatsapp": False})
    if not include_secrets and settings.get("messaging"):
        m=dict(settings.get("messaging") or {})
        for k in ("ikoddiApiKey","whatsappAccessToken"):
            if m.get(k): m[k]="***configured***"
        settings["messaging"]=m
    data = {"id": c.id, "code": c.code, "name": c.name, "phone": c.phone, "active": c.active, "settings": settings, "hasLogo": bool(c.logo_url)}
    data["logo"] = c.logo_url if include_logo else ""
    return data


def require_company(token: dict[str, Any], db: Session) -> Company:
    cid = token.get("cid")
    if not cid:
        raise HTTPException(403, "Cette action nécessite une société")
    company = db.get(Company, cid)
    if not company or not company.active:
        raise HTTPException(403, "Société inactive ou introuvable")
    return company


def entity_id_for(payload: dict[str, Any]) -> str:
    return str(payload.get("id") or payload.get("phone") or payload.get("code") or "").strip()


def canonical_content(payload: dict[str, Any]) -> str:
    p = {k: v for k, v in payload.items() if k not in {"_serverVersion", "_serverUpdatedAt", "_syncConflict"}}
    return json.dumps(p, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def masked_name(value: str) -> str:
    return " ".join((p[:1] + "***") if p else "" for p in str(value or "").split())


def public_shipment(payload: dict[str, Any]) -> dict[str, Any]:
    safe_events = []
    for event in payload.get("events", []) or []:
        if isinstance(event, dict):
            safe_events.append({"status": str(event.get("status", "")), "at": str(event.get("at", "")), "agency": str(event.get("agency", ""))})
    return {
        "code": payload.get("code", ""), "origin": payload.get("origin", ""), "destination": payload.get("destination", ""),
        "type": payload.get("type", ""), "parcelCount": payload.get("parcelCount", 1), "status": payload.get("status", ""),
        "createdAt": payload.get("createdAt", ""), "updatedAt": payload.get("updatedAt", payload.get("createdAt", "")),
        "receiverName": masked_name(payload.get("receiverName", "")), "events": safe_events,
    }


def refresh_shipment_index(db: Session, company_id: str, entity_id: str, payload: dict[str, Any], dt: datetime):
    code = str(payload.get("code", "")).strip().upper()
    if not code:
        return
    idx = db.get(ShipmentIndexV3, {"company_id": company_id, "code": code})
    if idx and idx.entity_id != entity_id:
        raise HTTPException(409, f"Le code {code} est déjà attribué à un autre colis")
    pp = public_shipment(payload)
    if idx is None:
        db.add(ShipmentIndexV3(company_id=company_id, code=code, entity_id=entity_id, public_payload=pp, updated_at=dt))
    else:
        idx.public_payload = pp
        idx.updated_at = dt



def repair_company_shipment_indexes():
    """Répare les collisions historiques de codes puis reconstruit l'index public v3.

    Les doublons viennent des anciennes versions qui incrémentaient les numéros sur chaque téléphone.
    Le plus ancien envoi conserve le code imprimé; les suivants reçoivent un nouveau code officiel.
    """
    with SessionLocal() as db:
        companies = db.scalars(select(Company)).all()
        for company in companies:
            rows = db.scalars(select(EntityV3).where(EntityV3.company_id == company.id, EntityV3.entity_type == "shipments", EntityV3.deleted.is_(False))).all()
            if not rows:
                continue
            by_code: dict[str, list[EntityV3]] = {}
            max_by_prefix: dict[str, int] = {}
            for row in rows:
                code = str((row.payload or {}).get("code", "")).strip().upper()
                if not code:
                    continue
                by_code.setdefault(code, []).append(row)
                m = re.fullmatch(r"([A-Z0-9]+)-(\d+)", code)
                if m:
                    max_by_prefix[m.group(1)] = max(max_by_prefix.get(m.group(1), 0), int(m.group(2)))
            changed_ids: dict[str, tuple[str, str]] = {}
            for code, same_code in by_code.items():
                if len(same_code) <= 1:
                    continue
                same_code.sort(key=lambda r: (str((r.payload or {}).get("createdAt", "")), r.entity_id))
                for row in same_code[1:]:
                    payload = dict(row.payload or {})
                    agency_code = code.split("-", 1)[0] or "COL"
                    max_by_prefix[agency_code] = max_by_prefix.get(agency_code, 0) + 1
                    new_code = f"{agency_code}-{max_by_prefix[agency_code]:05d}"
                    old_code = str(payload.get("code", code))
                    payload["previousCode"] = old_code
                    payload["codeReassigned"] = True
                    payload["code"] = new_code
                    payload["updatedAt"] = utcnow().isoformat()
                    events = list(payload.get("events", []) or [])
                    events.append({"id": str(uuid.uuid4()), "status": payload.get("status", "Enregistré"), "at": utcnow().isoformat(), "agency": payload.get("origin", ""), "note": f"Code régularisé: {old_code} -> {new_code}"})
                    payload["events"] = events
                    row.version = max(1, row.version) + 1
                    payload["_serverVersion"] = row.version
                    payload["_serverUpdatedAt"] = utcnow().isoformat()
                    row.payload = payload
                    row.updated_at = utcnow()
                    changed_ids[row.entity_id] = (old_code, new_code)
            if changed_ids:
                # Corrige aussi les références textuelles auxiliaires; shipmentId reste la vraie clé.
                aux = db.scalars(select(EntityV3).where(EntityV3.company_id == company.id, EntityV3.entity_type.in_(["payments", "withdrawals"]))).all()
                for row in aux:
                    p = dict(row.payload or {})
                    sid = str(p.get("shipmentId", ""))
                    if sid in changed_ids:
                        p["code"] = changed_ids[sid][1]
                        row.version = max(1, row.version) + 1
                        p["_serverVersion"] = row.version
                        p["_serverUpdatedAt"] = utcnow().isoformat()
                        row.payload = p; row.updated_at = utcnow()
            # Recrée l'index public seulement si nécessaire (migration/collision/index incomplet).
            indexes = db.scalars(select(ShipmentIndexV3).where(ShipmentIndexV3.company_id == company.id)).all()
            shipment_rows = [r for r in rows if str((r.payload or {}).get("code", "")).strip()]
            index_by_code = {i.code: i for i in indexes}
            needs_rebuild = bool(changed_ids) or len(indexes) != len(shipment_rows)
            if not needs_rebuild:
                for row in shipment_rows:
                    code = str((row.payload or {}).get("code", "")).strip().upper()
                    idx = index_by_code.get(code)
                    if not idx or idx.entity_id != row.entity_id or not idx.public_payload:
                        needs_rebuild = True
                        break
            if needs_rebuild:
                for idx in indexes:
                    db.delete(idx)
                db.flush()
                for row in shipment_rows:
                    code = str((row.payload or {}).get("code", "")).strip().upper()
                    db.add(ShipmentIndexV3(company_id=company.id, code=code, entity_id=row.entity_id,
                                             public_payload=public_shipment(row.payload or {}), updated_at=row.updated_at or utcnow()))
        db.commit()

repair_company_shipment_indexes()

def agency_public_info(db: Session, company_id: str, name: str) -> dict[str, str]:
    rows = db.scalars(select(EntityV3).where(EntityV3.company_id == company_id, EntityV3.entity_type == "agencies", EntityV3.deleted.is_(False))).all()
    payload = next((r.payload for r in rows if str(r.payload.get("name", "")).casefold() == str(name).casefold()), None)
    if not payload:
        return {}
    lat, lng = str(payload.get("latitude", "") or "").strip(), str(payload.get("longitude", "") or "").strip()
    address = str(payload.get("address", "") or "").strip()
    maps_url = str(payload.get("mapsUrl", "") or "").strip()
    query = f"{lat},{lng}" if lat and lng else f"{payload.get('name','')} {address}".strip()
    if not maps_url and query:
        maps_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"
    return {"name": str(payload.get("name", name)), "city": str(payload.get("city", "")), "address": address,
            "pickupName": str(payload.get("pickupName", "") or payload.get("name", name)),
            "pickupDirections": str(payload.get("pickupDirections", "") or ""), "mapsUrl": maps_url,
            "mapEmbed": f"https://www.google.com/maps?q={quote_plus(query)}&output=embed" if query else ""}


@app.get("/health")
def health():
    return {"status": "ok", "service": "transport-multitenant-sync", "version": "4.6.0", "time": utcnow().isoformat()}


@app.post("/api/v2/auth/login")
def login(req: LoginRequest, db: Session = Depends(db_session)):
    company_code = req.company.strip().upper()
    if company_code in {"PLATFORM", "ROOT", "SUPER"}:
        user = db.scalar(select(AppUser).where(AppUser.company_id.is_(None), AppUser.username == req.username.strip()))
        company = None
    else:
        company = db.scalar(select(Company).where(Company.code == company_code, Company.active.is_(True)))
        if not company:
            raise HTTPException(401, "Société inconnue ou inactive")
        user = db.scalar(select(AppUser).where(AppUser.company_id == company.id, AppUser.username == req.username.strip()))
    if not user or not user.active or not password_verify(req.password, user.password_hash):
        raise HTTPException(401, "Société, identifiant ou mot de passe incorrect")
    token = make_token(user, company)
    if company:
        users = [user_public(u) for u in db.scalars(select(AppUser).where(AppUser.company_id == company.id, AppUser.active.is_(True))).all()]
        companies = []
    else:
        users = [user_public(user)]
        companies = [company_public(c, include_logo=False) for c in db.scalars(select(Company).order_by(Company.name)).all()]
    return {"token": token, "user": user_public(user), "company": company_public(company) if company else {"id": "platform", "code": "PLATFORM", "name": "Administration plateforme", "phone": "", "logo": ""}, "users": users, "companies": companies, "serverTime": utcnow().isoformat()}


@app.post("/api/v2/sequences/reserve")
def reserve_sequence(req: ReserveRequest, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    company = require_company(token, db)
    agency_code = re.sub(r"[^A-Z0-9]", "", req.agencyCode.upper())[:8]
    if not agency_code:
        raise HTTPException(400, "Code agence invalide")
    key = f"shipment:{agency_code}"
    seq = db.get(SequenceV3, {"company_id": company.id, "sequence_key": key})
    if seq is None:
        # Initialise après le plus grand code historique connu pour cette société/agence.
        max_existing = 0
        for idx in db.scalars(select(ShipmentIndexV3).where(ShipmentIndexV3.company_id == company.id)).all():
            m = re.fullmatch(rf"{re.escape(agency_code)}-(\d+)", idx.code)
            if m:
                max_existing = max(max_existing, int(m.group(1)))
        seq = SequenceV3(company_id=company.id, sequence_key=key, current_value=max_existing, updated_at=utcnow())
        db.add(seq)
        db.flush()
    start = seq.current_value + 1
    seq.current_value += req.count
    seq.updated_at = utcnow()
    db.commit()
    return {"agencyCode": agency_code, "start": start, "end": seq.current_value, "next": start, "reserved": req.count}



DUPLICATE_WINDOW_SECONDS = 35
DUPLICATE_OPERATION_TYPES = {"shipments", "tickets", "ticket_baggage"}


def _payload_datetime(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _dup_norm(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(float(value))
    return " ".join(str(value or "").strip().casefold().split())


def operation_duplicate_fingerprint(entity_type: str, payload: dict[str, Any]) -> tuple[str, ...]:
    if entity_type == "shipments":
        keys = ("createdBy", "senderPhone", "senderName", "receiverPhone", "receiverName", "origin", "destination", "type", "parcelCount", "fee", "description")
    elif entity_type == "tickets":
        keys = ("createdBy", "tripId", "phone", "passengerName", "seat", "seatClass", "boardingPoint", "dropPoint", "fare", "paid", "paymentMethod")
    else:
        keys = ("createdBy", "baggageType", "phone", "passengerName", "receiverPhone", "receiverName", "origin", "destination", "tripId", "count", "weight", "paid", "content")
    return tuple(_dup_norm(payload.get(k)) for k in keys)


def find_recent_duplicate(db: Session, company_id: str, entity_type: str, payload: dict[str, Any], device_id: str) -> Optional[EntityV3]:
    if entity_type not in DUPLICATE_OPERATION_TYPES or bool(payload.get("deleted")):
        return None
    created = _payload_datetime(payload.get("createdAt"))
    if not created:
        return None
    fp = operation_duplicate_fingerprint(entity_type, payload)
    if not any(fp):
        return None
    rows = db.scalars(select(EntityV3).where(
        EntityV3.company_id == company_id,
        EntityV3.entity_type == entity_type,
        EntityV3.deleted.is_(False),
    )).all()
    for row in rows:
        other = dict(row.payload or {})
        other_device = str(other.get("_deviceId") or "")
        # Le device est le verrou principal: deux appareils différents peuvent saisir des opérations semblables.
        if device_id and other_device != device_id:
            continue
        other_created = _payload_datetime(other.get("createdAt"))
        if not other_created:
            continue
        try:
            delta = abs((created - other_created).total_seconds())
        except TypeError:
            # anciens timestamps sans timezone
            delta = abs((created.replace(tzinfo=None) - other_created.replace(tzinfo=None)).total_seconds())
        if delta > DUPLICATE_WINDOW_SECONDS:
            continue
        if operation_duplicate_fingerprint(entity_type, other) == fp:
            return row
    return None


def shipment_destination_allowed(db: Session, company_id: str, payload: dict[str, Any]) -> bool:
    """Enforce agency destination restrictions for new/retargeted courier shipments.

    Empty/missing allowedDestinations means all active company agencies are allowed (except same origin,
    which is already blocked by the client). Values may contain agency ids or historical agency names.
    """
    origin = str(payload.get("origin") or "").strip()
    destination = str(payload.get("destination") or "").strip()
    if not origin or not destination:
        return True
    rows = db.scalars(select(EntityV3).where(
        EntityV3.company_id == company_id,
        EntityV3.entity_type == "agencies",
        EntityV3.deleted.is_(False),
    )).all()
    source = next((r for r in rows if str((r.payload or {}).get("name") or "").casefold() == origin.casefold()), None)
    if source is None:
        return True  # compatibilité avec les anciennes sociétés sans fiches agences synchronisées
    allowed = (source.payload or {}).get("allowedDestinations")
    if not isinstance(allowed, list) or not [x for x in allowed if x]:
        return True
    target = next((r for r in rows if str((r.payload or {}).get("name") or "").casefold() == destination.casefold()), None)
    if target is None:
        return False
    target_payload = dict(target.payload or {})
    accepted = {str(x) for x in allowed if x}
    return (
        str(target.entity_id) in accepted
        or str(target_payload.get("id") or "") in accepted
        or destination in accepted
    )


@app.post("/api/v2/sync")
def sync_v2(req: SyncRequest, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    company = require_company(token, db)
    conflicts: list[dict[str, Any]] = []
    rejected_duplicate_ids: list[str] = []
    accepted = 0
    # Les agences passent d'abord afin qu'une modification de destinations autorisées
    # soit appliquée dans la même synchronisation avant les nouveaux envois.
    ordered_entities = list(req.entities.items())
    ordered_entities.sort(key=lambda kv: 0 if kv[0] == "agencies" else 1)
    for entity_type, items in ordered_entities:
        if entity_type not in ALLOWED_TYPES:
            continue
        for incoming in items:
            payload = dict(incoming)
            entity_id = entity_id_for(payload)
            if not entity_id:
                continue
            payload["companyId"] = company.id
            if req.deviceId and not payload.get("_deviceId"):
                payload["_deviceId"] = req.deviceId
            current = db.get(EntityV3, {"company_id": company.id, "entity_type": entity_type, "entity_id": entity_id})
            incoming_version = int(payload.get("_serverVersion") or 0)

            # Courrier et Bagages ne peuvent pas être annulés/supprimés via la synchronisation
            # d'un compte société. L'annulation administrative passe exclusivement par
            # /api/v2/platform/.../operations/... et exige le rôle platform_admin.
            if entity_type in {"shipments", "ticket_baggage"}:
                incoming_cancelled = bool(payload.get("deleted") or payload.get("cancelled") or str(payload.get("status") or "").strip().casefold() in {"annulé", "annule"})
                current_payload = dict(current.payload or {}) if current is not None else {}
                already_cancelled = bool(current and (current.deleted or current_payload.get("cancelled") or str(current_payload.get("status") or "").strip().casefold() in {"annulé", "annule"}))
                if incoming_cancelled and not already_cancelled:
                    conflicts.append({
                        "type": "platform_admin_required",
                        "entityType": entity_type,
                        "id": entity_id,
                        "message": "Annulation réservée au Super Super Admin",
                    })
                    continue

            # Respecte les destinations autorisées définies sur l'agence. On contrôle les
            # nouveaux envois ainsi qu'un éventuel changement de trajet.
            if entity_type == "shipments":
                previous = dict(current.payload or {}) if current is not None else {}
                route_changed = current is None or str(previous.get("origin") or "") != str(payload.get("origin") or "") or str(previous.get("destination") or "") != str(payload.get("destination") or "")
                if route_changed and not shipment_destination_allowed(db, company.id, payload):
                    conflicts.append({
                        "type": "destination_not_allowed",
                        "entityType": entity_type,
                        "id": entity_id,
                        "origin": payload.get("origin", ""),
                        "destination": payload.get("destination", ""),
                        "message": "Destination non autorisée pour cette agence",
                    })
                    continue

            if current is None:
                duplicate = find_recent_duplicate(db, company.id, entity_type, payload, req.deviceId)
                if duplicate is not None:
                    rejected_duplicate_ids.append(entity_id)
                    conflicts.append({
                        "type": "duplicate_operation",
                        "entityType": entity_type,
                        "id": entity_id,
                        "duplicateOf": duplicate.entity_id,
                        "message": "Double enregistrement bloqué par le serveur",
                    })
                    continue
                version = 1
                payload["_serverVersion"] = version
                payload["_serverUpdatedAt"] = utcnow().isoformat()
                current = EntityV3(company_id=company.id, entity_type=entity_type, entity_id=entity_id, payload=payload,
                                   version=version, updated_at=utcnow(), deleted=bool(payload.get("deleted", False)))
                db.add(current)
                accepted += 1
            else:
                same = canonical_content(payload) == canonical_content(current.payload or {})
                if same:
                    pass
                elif incoming_version == current.version:
                    current.version += 1
                    payload["_serverVersion"] = current.version
                    payload["_serverUpdatedAt"] = utcnow().isoformat()
                    current.payload = payload
                    current.updated_at = utcnow()
                    current.deleted = bool(payload.get("deleted", False))
                    accepted += 1
                elif incoming_version == 0 and int((current.payload or {}).get("_serverVersion") or 0) == 0:
                    current.version += 1
                    payload["_serverVersion"] = current.version
                    payload["_serverUpdatedAt"] = utcnow().isoformat()
                    current.payload = payload
                    current.updated_at = utcnow()
                    current.deleted = bool(payload.get("deleted", False))
                    accepted += 1
                else:
                    conflicts.append({"type": "stale_version", "entityType": entity_type, "id": entity_id,
                                      "localVersion": incoming_version, "serverVersion": current.version})
                    continue
            if entity_type == "shipments" and not current.deleted:
                try:
                    refresh_shipment_index(db, company.id, entity_id, current.payload, current.updated_at)
                except HTTPException as exc:
                    conflicts.append({"type": "duplicate_shipment_code", "id": entity_id, "code": payload.get("code", ""), "detail": exc.detail})
                    db.rollback()
                    raise HTTPException(409, detail={"message": exc.detail, "conflicts": conflicts})
    db.commit()

    result: dict[str, list[dict[str, Any]]] = {name: [] for name in ALLOWED_TYPES}
    all_users = db.scalars(select(AppUser).where(AppUser.company_id == company.id)).all()
    user_names = {u.id: u.name for u in all_users}
    rows = db.scalars(select(EntityV3).where(EntityV3.company_id == company.id, EntityV3.deleted.is_(False))).all()
    for row in rows:
        if row.entity_type in result:
            p = dict(row.payload or {})
            p["_serverVersion"] = row.version
            p["_serverUpdatedAt"] = row.updated_at.isoformat()
            creator = str(p.get("createdBy") or "")
            if creator and creator in user_names:
                p["_createdByName"] = user_names[creator]
            result[row.entity_type].append(p)
    users = [user_public(u) for u in all_users if u.active]
    return {"serverTime": utcnow().isoformat(), "company": company_public(company), "users": users,
            "conflicts": conflicts, "rejectedDuplicateIds": rejected_duplicate_ids,
            "accepted": accepted, "entities": result}


@app.get("/api/v2/admin/bootstrap")
def admin_bootstrap(token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    if token.get("role") == "platform_admin":
        return {"companies": [company_public(c, include_logo=False) for c in db.scalars(select(Company).order_by(Company.name)).all()]}
    company = require_company(token, db)
    if token.get("role") not in {"company_admin", "superuser", "admin"}:
        raise HTTPException(403, "Droits administrateur requis")
    users = [user_public(u) for u in db.scalars(select(AppUser).where(AppUser.company_id == company.id)).all()]
    return {"company": company_public(company), "users": users}


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _cancelled(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "").strip().lower()
    return bool(payload.get("cancelled")) or status in {"annulé", "annule", "cancelled", "canceled"}


def _shipment_amount(payload: dict[str, Any]) -> float:
    return 0.0 if _cancelled(payload) else _num(payload.get("fee"))


def _baggage_amount(payload: dict[str, Any]) -> float:
    return 0.0 if _cancelled(payload) else _num(payload.get("paid") if payload.get("paid") is not None else payload.get("amount"))


def company_stats(db: Session, company: Company) -> dict[str, Any]:
    rows = db.scalars(select(EntityV3).where(EntityV3.company_id == company.id, EntityV3.deleted.is_(False))).all()
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_type.setdefault(row.entity_type, []).append(dict(row.payload or {}))
    shipments = by_type.get("shipments", [])
    active_shipments = [x for x in shipments if not _cancelled(x)]
    tickets = by_type.get("tickets", [])
    baggage = by_type.get("ticket_baggage", [])
    active_baggage = [x for x in baggage if not _cancelled(x)]
    boardings = by_type.get("ticket_boardings", [])
    notification_logs = by_type.get("notification_logs", [])
    expenses = by_type.get("expenses", [])
    courier_sales = sum(_shipment_amount(x) for x in shipments)
    baggage_sales = sum(_baggage_amount(x) for x in baggage)
    expense_total = sum(_num(x.get("amount")) for x in expenses)
    statuses: dict[str, int] = {}
    today = utcnow().date().isoformat()
    today_shipments = 0
    today_sales = 0.0
    for x in shipments:
        status = "Annulé" if _cancelled(x) else str(x.get("status") or "Inconnu")
        statuses[status] = statuses.get(status, 0) + 1
        created = str(x.get("createdAt") or x.get("created_at") or "")
        if created.startswith(today):
            today_shipments += 1
            today_sales += _shipment_amount(x)
    user_count = len(db.scalars(select(AppUser).where(AppUser.company_id == company.id, AppUser.active.is_(True))).all())
    return {
        "companyId": company.id, "code": company.code, "name": company.name, "active": company.active,
        "shipments": len(shipments), "activeShipments": len(active_shipments), "cancelledShipments": len(shipments)-len(active_shipments),
        "customers": len(by_type.get("customers", [])), "manifests": len(by_type.get("manifests", [])),
        "withdrawals": len(by_type.get("withdrawals", [])), "agencies": len(by_type.get("agencies", [])), "users": int(user_count),
        "sales": round(courier_sales, 2), "billed": round(courier_sales, 2), "outstanding": 0,
        "expenses": round(expense_total, 2), "net": round(courier_sales + baggage_sales - expense_total, 2),
        "averageTicket": round(courier_sales / len(active_shipments), 2) if active_shipments else 0,
        "baggage": len(baggage), "cancelledBaggage": len(baggage)-len(active_baggage), "baggageRevenue": round(baggage_sales,2),
        "tickets": len(tickets), "ticketRevenue": round(sum(_num(x.get("paid") or x.get("amount")) for x in tickets if not _cancelled(x)),2),
        "boarded": sum(1 for x in tickets if bool(x.get("boarded"))) or len(boardings),
        "smsSent": sum(1 for x in notification_logs if x.get("channel")=="sms" and x.get("status")=="sent"),
        "whatsappSent": sum(1 for x in notification_logs if x.get("channel")=="whatsapp" and x.get("status")=="sent"),
        "todayShipments": today_shipments, "todaySales": round(today_sales, 2), "statuses": statuses,
    }


@app.get("/api/v2/platform/stats")
def platform_stats(token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    if token.get("role") != "platform_admin":
        raise HTTPException(403, "Réservé au Super Super Admin")
    companies = db.scalars(select(Company).order_by(Company.name)).all()
    items = [company_stats(db, c) for c in companies]
    totals = {
        "companies": len(items), "activeCompanies": sum(1 for x in items if x["active"]),
        "shipments": sum(x["shipments"] for x in items), "sales": round(sum(x["sales"] for x in items), 2),
        "expenses": round(sum(x["expenses"] for x in items), 2), "net": round(sum(x["net"] for x in items), 2),
        "outstanding": round(sum(x["outstanding"] for x in items), 2), "users": sum(x["users"] for x in items),
        "agencies": sum(x["agencies"] for x in items), "todayShipments": sum(x["todayShipments"] for x in items),
        "todaySales": round(sum(x["todaySales"] for x in items), 2),
        "tickets": sum(x.get("tickets",0) for x in items), "ticketRevenue": round(sum(x.get("ticketRevenue",0) for x in items),2),
        "baggage": sum(x.get("baggage",0) for x in items), "baggageRevenue": round(sum(x.get("baggageRevenue",0) for x in items),2),
        "smsSent": sum(x.get("smsSent",0) for x in items), "whatsappSent": sum(x.get("whatsappSent",0) for x in items),
    }
    return {"totals": totals, "companies": items, "serverTime": utcnow().isoformat()}


@app.get("/api/v2/platform/companies/{company_id}")
def platform_company_detail(company_id: str, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    if token.get("role") != "platform_admin":
        raise HTTPException(403, "Réservé au Super Super Admin")
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Société introuvable")
    users = [user_public(u) for u in db.scalars(select(AppUser).where(AppUser.company_id == company.id).order_by(AppUser.name)).all()]
    rows = db.scalars(select(EntityV3).where(EntityV3.company_id == company.id, EntityV3.deleted.is_(False))).all()
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_type.setdefault(row.entity_type, []).append(dict(row.payload or {}))
    stats = company_stats(db, company)
    agencies = by_type.get("agencies", [])
    payments = by_type.get("payments", [])
    shipments = by_type.get("shipments", [])
    tickets = by_type.get("tickets", [])
    boardings = by_type.get("ticket_boardings", [])
    notification_logs = by_type.get("notification_logs", [])
    expenses = by_type.get("expenses", [])
    withdrawals = by_type.get("withdrawals", [])
    manifests = by_type.get("manifests", [])
    baggage = by_type.get("ticket_baggage", [])

    def op_date(item: dict[str, Any]) -> str:
        return str(item.get("updatedAt") or item.get("createdAt") or item.get("at") or item.get("date") or item.get("departureAt") or "")

    operations: list[dict[str, Any]] = []
    for sh in shipments:
        operations.append({"type":"shipment","id":sh.get("id",""),"code":sh.get("code",""),"label":f"Envoi {sh.get('code','')}","status":"Annulé" if _cancelled(sh) else sh.get("status",""),"amount":_shipment_amount(sh),"agency":sh.get("origin",""),"at":op_date(sh),"cancelled":_cancelled(sh),"manifestId":sh.get("manifestId", ""),"lockedInManifest":bool(sh.get("manifestId")),"data":{k:v for k,v in sh.items() if k not in {"photo","events","notifications"}}})
    for pay in payments:
        operations.append({"type":"payment","id":pay.get("id",""),"code":pay.get("shipmentCode") or pay.get("code", ""),"label":"Encaissement","status":pay.get("method") or pay.get("paymentMethod", ""),"amount":_num(pay.get("amount")),"agency":pay.get("agency", ""),"at":op_date(pay)})
    for exp in expenses:
        operations.append({"type":"expense","id":exp.get("id",""),"code":"","label":str(exp.get("label") or exp.get("description") or "Dépense"),"status":str(exp.get("category") or ""),"amount":-_num(exp.get("amount")),"agency":exp.get("agency", ""),"at":op_date(exp)})
    for wd in withdrawals:
        operations.append({"type":"withdrawal","id":wd.get("id",""),"code":wd.get("shipmentCode") or wd.get("code", ""),"label":"Retrait colis","status":"Livré","amount":0,"agency":wd.get("agency", ""),"at":op_date(wd)})
    for mf in manifests:
        operations.append({"type":"manifest","id":mf.get("id",""),"code":mf.get("code", ""),"label":f"Bordereau {mf.get('code','')}","status":mf.get("status", ""),"amount":0,"agency":mf.get("origin", ""),"at":op_date(mf)})
    for t in tickets:
        operations.append({"type":"ticket","id":t.get("id",""),"code":t.get("pnr",""),"label":f"Billet {t.get('pnr','')}","status":t.get("status",""),"amount":0 if _cancelled(t) else _num(t.get("paid") or t.get("fare")),"agency":t.get("agency",""),"at":op_date(t)})
    for bg in baggage:
        operations.append({"type":"baggage","id":bg.get("id",""),"code":bg.get("code",""),"label":f"Bagage {bg.get('code','')}","status":"Annulé" if _cancelled(bg) else bg.get("status",""),"amount":_baggage_amount(bg),"agency":bg.get("agency") or bg.get("origin",""),"at":op_date(bg),"cancelled":_cancelled(bg),"data":{k:v for k,v in bg.items() if k not in {"photo","events"}}})
    for b in boardings:
        operations.append({"type":"boarding","id":b.get("id",""),"code":b.get("pnr",""),"label":f"Embarquement {b.get('pnr','')}","status":"Embarqué","amount":0,"agency":b.get("agency",""),"at":op_date(b)})
    operations.sort(key=lambda x: x.get("at") or "", reverse=True)
    payments_sorted = sorted(payments, key=op_date, reverse=True)[:100]
    return {
        "company": company_public(company, include_logo=True, include_secrets=True),
        "stats": stats, "users": users, "agencies": agencies,
        "payments": payments_sorted, "operations": operations[:300],
        "tickets": tickets[:500], "ticketTrips": by_type.get("ticket_trips", [])[:300], "ticketBuses": by_type.get("ticket_buses", [])[:200],
        "notificationLogs": sorted(notification_logs,key=op_date,reverse=True)[:300],
        "serverTime": utcnow().isoformat(),
    }


@app.put("/api/v2/platform/companies/{company_id}/operations/{operation_type}/{operation_id}")
def platform_update_operation(company_id: str, operation_type: str, operation_id: str, req: PlatformOperationRequest, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    if token.get("role") != "platform_admin":
        raise HTTPException(403, "Réservé au Super Super Admin")
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Société introuvable")
    entity_map = {"shipment":"shipments", "baggage":"ticket_baggage"}
    entity_type = entity_map.get(operation_type)
    if not entity_type:
        raise HTTPException(400, "Seules les opérations Courrier et Bagages sont modifiables ici")
    row = db.get(EntityV3, {"company_id": company.id, "entity_type": entity_type, "entity_id": operation_id})
    if not row or row.deleted:
        raise HTTPException(404, "Opération introuvable")
    payload = dict(row.payload or {})
    action = str(req.action or "update").strip().lower()
    if action == "cancel":
        # Même un colis déjà affecté à un bordereau ne peut être annulé que par platform_admin (contrôle ci-dessus).
        if entity_type == "shipments" and payload.get("manifestId"):
            payload["cancelledFromManifest"] = str(payload.get("manifestId"))
        payload["cancelled"] = True
        payload["status"] = "Annulé"
        payload["cancelledAt"] = utcnow().isoformat()
        payload["cancelledBy"] = token.get("uid") or "platform"
        payload["cancelReason"] = str(req.reason or "Correction administrative").strip()
    elif action == "update":
        if _cancelled(payload):
            raise HTTPException(409, "Une opération annulée ne peut plus être modifiée")
        if entity_type == "shipments":
            allowed = {"senderName","senderPhone","receiverName","receiverPhone","origin","destination","type","parcelCount","weight","declaredValue","fee","description"}
        else:
            allowed = {"passengerName","phone","receiverName","receiverPhone","origin","destination","baggageType","pnr","tripId","count","weight","declaredValue","paid","content","notes","paymentMethod"}
        for key, value in (req.patch or {}).items():
            if key in allowed:
                payload[key] = value
        if entity_type == "shipments":
            payload["fee"] = _num(payload.get("fee"))
            payload["paid"] = payload["fee"]
            payload["balance"] = 0
        else:
            payload["paid"] = _num(payload.get("paid"))
            payload["amount"] = payload["paid"]
    else:
        raise HTTPException(400, "Action invalide")
    row.version = max(1, int(row.version or 1)) + 1
    payload["updatedAt"] = utcnow().isoformat()
    payload["_serverVersion"] = row.version
    payload["_serverUpdatedAt"] = utcnow().isoformat()
    row.payload = payload
    row.updated_at = utcnow()
    if entity_type == "shipments":
        refresh_shipment_index(db, company.id, row.entity_id, payload, row.updated_at)
    db.commit()
    return {"ok": True, "entityType": entity_type, "operation": payload}


@app.put("/api/v2/platform/companies/{company_id}/users/{user_id}")
def platform_update_user(company_id: str, user_id: str, req: PlatformUserUpdateRequest, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    if token.get("role") != "platform_admin":
        raise HTTPException(403, "Réservé au Super Super Admin")
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Société introuvable")
    user = db.get(AppUser, user_id)
    if not user or user.company_id != company.id:
        raise HTTPException(404, "Utilisateur introuvable")
    if req.username.strip() and req.username.strip() != user.username:
        exists = db.scalar(select(AppUser).where(AppUser.company_id == company.id, AppUser.username == req.username.strip(), AppUser.id != user.id))
        if exists:
            raise HTTPException(409, "Cet identifiant est déjà utilisé dans cette société")
        user.username = req.username.strip()
    if req.name.strip(): user.name = req.name.strip()
    if req.role.strip():
        if req.role not in {"agency", "admin", "company_admin", "superuser"}:
            raise HTTPException(400, "Rôle invalide")
        user.role = req.role
    if req.agency.strip(): user.agency = req.agency.strip()
    if req.active is not None: user.active = bool(req.active)
    if req.newPassword:
        if len(req.newPassword) < 6: raise HTTPException(400, "Le nouveau mot de passe doit contenir au moins 6 caractères")
        user.password_hash = password_hash(req.newPassword)
    if req.modules is not None:
        cm=dict((company.settings or {}).get("modules") or {"courier":True,"baggage":True,"tickets":False}); mods=dict(req.modules or {})
        mods["courier"]=bool(mods.get("courier")) and bool(cm.get("courier")); mods["baggage"]=bool(mods.get("baggage",True)) and bool(cm.get("baggage",True)); mods["tickets"]=bool(mods.get("tickets")) and bool(cm.get("tickets"))
        mods["ticketRoles"]=[x for x in (mods.get("ticketRoles") or []) if x in {"sales","boarding","dispatch","driver","manager","reports"}]
        user.modules=mods
    db.commit()
    return user_public(user)


@app.put("/api/v2/admin/companies/{company_id}")
def update_platform_company(company_id: str, req: CompanyPlatformUpdateRequest, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    if token.get("role") != "platform_admin":
        raise HTTPException(403, "Réservé au Super Super Admin")
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Société introuvable")
    if req.name.strip(): company.name = req.name.strip()
    if req.phone.strip(): company.phone = req.phone.strip()
    if req.active is not None: company.active = bool(req.active)
    st = dict(company.settings or {})
    for k, v in {
        "primaryColor": req.primaryColor, "secondaryColor": req.secondaryColor, "accentColor": req.accentColor,
        "trackingTitle": req.trackingTitle, "trackingSubtitle": req.trackingSubtitle,
        "supportEmail": req.supportEmail, "website": req.website, "heroImageUrl": req.heroImageUrl,
    }.items():
        if v is not None and str(v).strip(): st[k] = str(v).strip()
    if req.modules is not None: st["modules"]={"courier":bool(req.modules.get("courier")),"tickets":bool(req.modules.get("tickets"))}
    if req.features is not None: st["features"]={"sms":bool(req.features.get("sms")),"whatsapp":bool(req.features.get("whatsapp"))}
    company.settings = st
    db.commit()
    return company_public(company, include_logo=False)


@app.post("/api/v2/admin/companies/{company_id}/logo")
def upload_platform_company_logo(company_id: str, payload: dict[str, Any], token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    if token.get("role") != "platform_admin":
        raise HTTPException(403, "Réservé au Super Super Admin")
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Société introuvable")
    data_url = str(payload.get("dataUrl") or "")
    if not re.match(r"^data:image/(png|jpeg|jpg|webp);base64,", data_url, re.I):
        raise HTTPException(400, "Format logo invalide")
    if len(data_url) > 2_000_000:
        raise HTTPException(413, "Logo trop volumineux. Limite environ 1,5 Mo.")
    company.logo_url = data_url
    db.commit()
    return {"ok": True, "hasLogo": True}


@app.delete("/api/v2/admin/companies/{company_id}")
def delete_platform_company(company_id: str, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    if token.get("role") != "platform_admin":
        raise HTTPException(403, "Réservé au Super Super Admin")
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Société introuvable")
    if company.code == DEFAULT_COMPANY_CODE:
        raise HTTPException(400, "La société par défaut ne peut pas être supprimée. Désactivez-la si nécessaire.")
    for model in (ShipmentIndexV3, SequenceV3, EntityV3):
        for row in db.scalars(select(model).where(model.company_id == company.id)).all():
            db.delete(row)
    for user in db.scalars(select(AppUser).where(AppUser.company_id == company.id)).all():
        db.delete(user)
    db.delete(company)
    db.commit()
    return {"ok": True}


@app.post("/api/v2/admin/companies")
def create_company(req: CompanyCreateRequest, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    if token.get("role") != "platform_admin":
        raise HTTPException(403, "Réservé au Super Super Admin")
    code = re.sub(r"[^A-Z0-9_-]", "", req.code.upper())[:40]
    if not code or code in {"PLATFORM", "ROOT", "SUPER"}:
        raise HTTPException(400, "Code société invalide")
    if db.scalar(select(Company).where(Company.code == code)):
        raise HTTPException(409, "Ce code société existe déjà")
    logo = req.logoUrl.strip()
    if logo and not re.match(r"^data:image/(png|jpeg|jpg|webp);base64,", logo, re.I):
        raise HTTPException(400, "Le logo doit être téléversé depuis un fichier image")
    if len(logo) > 2_000_000:
        raise HTTPException(413, "Logo trop volumineux. Limite environ 1,5 Mo.")
    company = Company(id=str(uuid.uuid4()), code=code, name=req.name.strip(), phone=req.phone.strip(), logo_url=logo, active=True,
                      settings={"trackingBaseUrl": PUBLIC_BASE_URL + "/suivi", "primaryColor":req.primaryColor, "secondaryColor":req.secondaryColor, "accentColor":req.accentColor, "trackingTitle":req.trackingTitle, "trackingSubtitle":req.trackingSubtitle, "supportEmail":req.supportEmail, "website":req.website, "heroImageUrl":req.heroImageUrl, "modules":req.modules, "features":req.features, "messaging":{}}, created_at=utcnow())
    db.add(company); db.flush()
    db.add(AppUser(id=str(uuid.uuid4()), company_id=company.id, username=req.adminUsername.strip(), name=req.adminName.strip(),
                   password_hash=password_hash(req.adminPassword), role="company_admin", agency="Toutes", active=True, modules={"courier":True,"tickets":True,"ticketRoles":["sales","boarding","dispatch","manager","reports"]}, created_at=utcnow()))
    db.commit()
    return company_public(company)


@app.post("/api/v2/admin/users")
def create_user(req: UserCreateRequest, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    if token.get("role") == "platform_admin":
        code = req.companyCode.strip().upper()
        company = db.scalar(select(Company).where(Company.code == code))
        if not company:
            raise HTTPException(404, "Société introuvable")
    else:
        company = require_company(token, db)
        if token.get("role") not in {"company_admin", "superuser", "admin"}:
            raise HTTPException(403, "Droits administrateur requis")
    if db.scalar(select(AppUser).where(AppUser.company_id == company.id, AppUser.username == req.username.strip())):
        raise HTTPException(409, "Cet identifiant existe déjà dans cette société")
    role = req.role if req.role in {"agency", "admin", "company_admin", "superuser"} else "agency"
    cm=dict((company.settings or {}).get("modules") or {"courier":True,"baggage":True,"tickets":False}); mods=dict(req.modules or {})
    mods["courier"]=bool(mods.get("courier")) and bool(cm.get("courier")); mods["baggage"]=bool(mods.get("baggage",True)) and bool(cm.get("baggage",True)); mods["tickets"]=bool(mods.get("tickets")) and bool(cm.get("tickets")); mods["ticketRoles"]=[x for x in (mods.get("ticketRoles") or []) if x in {"sales","boarding","dispatch","driver","manager","reports"}]
    user = AppUser(id=str(uuid.uuid4()), company_id=company.id, username=req.username.strip(), name=req.name.strip(),
                   password_hash=password_hash(req.password), role=role, agency=req.agency or "Toutes", active=True, modules=mods, created_at=utcnow())
    db.add(user); db.commit()
    return user_public(user)


@app.put("/api/v2/admin/users/{user_id}")
def update_company_user(user_id: str, req: PlatformUserUpdateRequest, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    company = require_company(token, db)
    actor_role = token.get("role")
    if actor_role not in {"company_admin", "superuser", "admin"}:
        raise HTTPException(403, "Droits administrateur requis")
    user = db.get(AppUser, user_id)
    if not user or user.company_id != company.id:
        raise HTTPException(404, "Utilisateur introuvable")
    if actor_role == "admin" and user.role in {"company_admin", "superuser"}:
        raise HTTPException(403, "Cet administrateur ne peut pas modifier ce compte")
    if req.username.strip() and req.username.strip() != user.username:
        exists = db.scalar(select(AppUser).where(AppUser.company_id == company.id, AppUser.username == req.username.strip(), AppUser.id != user.id))
        if exists:
            raise HTTPException(409, "Cet identifiant est déjà utilisé")
        user.username = req.username.strip()
    if req.name.strip(): user.name = req.name.strip()
    if req.role.strip():
        allowed_roles = {"agency", "admin"} if actor_role == "admin" else {"agency", "admin", "superuser", "company_admin"}
        if req.role not in allowed_roles:
            raise HTTPException(403, "Rôle non autorisé")
        user.role = req.role
    if req.agency.strip(): user.agency = req.agency.strip()
    if req.active is not None: user.active = bool(req.active)
    if req.newPassword:
        if len(req.newPassword) < 6:
            raise HTTPException(400, "Le nouveau mot de passe doit contenir au moins 6 caractères")
        user.password_hash = password_hash(req.newPassword)
    if req.modules is not None:
        cm=dict((company.settings or {}).get("modules") or {"courier":True,"baggage":True,"tickets":False}); mods=dict(req.modules or {})
        mods["courier"]=bool(mods.get("courier")) and bool(cm.get("courier")); mods["baggage"]=bool(mods.get("baggage",True)) and bool(cm.get("baggage",True)); mods["tickets"]=bool(mods.get("tickets")) and bool(cm.get("tickets"))
        mods["ticketRoles"]=[x for x in (mods.get("ticketRoles") or []) if x in {"sales","boarding","dispatch","driver","manager","reports"}]
        user.modules=mods
    db.commit()
    return user_public(user)


@app.delete("/api/v2/admin/users/{user_id}")
def delete_user(user_id: str, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    company = require_company(token, db)
    if token.get("role") not in {"company_admin", "superuser", "admin"}:
        raise HTTPException(403, "Droits administrateur requis")
    u = db.get(AppUser, user_id)
    if not u or u.company_id != company.id:
        raise HTTPException(404, "Utilisateur introuvable")
    u.active = False; db.commit()
    return {"ok": True}


@app.put("/api/v2/admin/company/profile")
def update_company_profile(req: CompanyProfileRequest, token: dict[str, Any] = Depends(read_token), db: Session = Depends(db_session)):
    company = require_company(token, db)
    if token.get("role") not in {"company_admin", "superuser", "admin"}:
        raise HTTPException(403, "Droits administrateur requis")
    if req.name: company.name = req.name.strip()
    if req.phone: company.phone = req.phone.strip()
    if req.logoUrl: company.logo_url = req.logoUrl.strip()
    st = dict(company.settings or {})
    for k, v in {"primaryColor":req.primaryColor,"secondaryColor":req.secondaryColor,"accentColor":req.accentColor,"trackingTitle":req.trackingTitle,"trackingSubtitle":req.trackingSubtitle,"supportEmail":req.supportEmail,"website":req.website,"heroImageUrl":req.heroImageUrl}.items():
        if v != "": st[k] = v.strip()
    company.settings = st
    db.commit()
    return company_public(company)




@app.post("/api/v2/platform/companies/{company_id}/impersonate")
def platform_impersonate(company_id: str, token: dict[str, Any]=Depends(read_token), db: Session=Depends(db_session)):
    """Ouvre une société avec les droits administrateur complet depuis le compte plateforme.
    Le token d'origine reste côté client pour permettre le retour à la plateforme.
    """
    if token.get("role") != "platform_admin":
        raise HTTPException(403, "Réservé au Super Super Admin")
    company=db.get(Company, company_id)
    if not company or not company.active:
        raise HTTPException(404, "Société introuvable ou inactive")
    # Un utilisateur virtuel est suffisant : les autorisations reposent sur le token signé,
    # et aucune donnée de mot de passe n'est exposée.
    class VirtualUser: pass
    vu=VirtualUser();vu.id=f"platform:{token.get('uid')}:{company.id}";vu.role="company_admin";vu.agency="Toutes"
    signed=make_token(vu,company)
    user={"id":vu.id,"username":"platform-admin","name":"Super Admin Plateforme","role":"company_admin","agency":"Toutes","active":True,"modules":{"courier":True,"tickets":True,"ticketRoles":["sales","boarding","dispatch","driver","reports","manager"]}}
    users=[user_public(u) for u in db.scalars(select(AppUser).where(AppUser.company_id==company.id,AppUser.active.is_(True))).all()]
    return {"token":signed,"user":user,"company":company_public(company),"users":users,"serverTime":utcnow().isoformat(),"impersonatedBy":token.get("uid")}

def _platform_only(token: dict[str, Any]):
    if token.get("role") != "platform_admin": raise HTTPException(403, "Réservé au Super Super Admin")

def _entity_payloads(db: Session, company_id: str, entity_type: str) -> list[dict[str, Any]]:
    return [dict(r.payload or {}) for r in db.scalars(select(EntityV3).where(EntityV3.company_id==company_id, EntityV3.entity_type==entity_type, EntityV3.deleted.is_(False))).all()]

@app.put("/api/v2/platform/companies/{company_id}/capabilities")
def platform_capabilities(company_id: str, req: CapabilityRequest, token: dict[str, Any]=Depends(read_token), db: Session=Depends(db_session)):
    _platform_only(token); company=db.get(Company,company_id)
    if not company: raise HTTPException(404,"Société introuvable")
    st=dict(company.settings or {}); st["modules"]={"courier":bool(req.modules.get("courier")),"tickets":bool(req.modules.get("tickets"))}; st["features"]={"sms":bool(req.features.get("sms")),"whatsapp":bool(req.features.get("whatsapp"))}
    old=dict(st.get("messaging") or {})
    for k,v in (req.messaging or {}).items():
        if v not in (None,"","***configured***"): old[k]=v
    st["messaging"]=old; company.settings=st
    for u in db.scalars(select(AppUser).where(AppUser.company_id==company.id)).all():
        mods=dict(u.modules or {}); mods["courier"]=bool(mods.get("courier")) and st["modules"]["courier"]; mods["tickets"]=bool(mods.get("tickets")) and st["modules"]["tickets"]; u.modules=mods
    db.commit(); return company_public(company,include_logo=False,include_secrets=True)

def _http_json(url: str, payload: dict[str,Any], headers: dict[str,str]) -> tuple[int,str]:
    req=urlrequest.Request(url,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json",**headers},method="POST")
    try:
        with urlrequest.urlopen(req,timeout=15) as resp: return int(resp.status),resp.read().decode("utf-8","ignore")
    except urlerror.HTTPError as exc: return int(exc.code),exc.read().decode("utf-8","ignore")
    except Exception as exc: return 599,str(exc)

def _write_notification_log(db: Session, company: Company, payload: dict[str,Any]):
    eid=str(uuid.uuid4()); dt=utcnow(); p={"id":eid,**payload,"createdAt":dt.isoformat(),"_serverVersion":1,"_serverUpdatedAt":dt.isoformat()}; db.add(EntityV3(company_id=company.id,entity_type="notification_logs",entity_id=eid,payload=p,version=1,updated_at=dt,deleted=False))

@app.post("/api/v2/notifications/send")
def send_notification(req: NotificationSendRequest, token: dict[str,Any]=Depends(read_token), db: Session=Depends(db_session)):
    company=require_company(token,db); ch=req.channel.strip().lower()
    if ch not in {"sms","whatsapp"}: raise HTTPException(400,"Canal invalide")
    st=dict(company.settings or {}); features=dict(st.get("features") or {}); msg=dict(st.get("messaging") or {})
    if not features.get(ch,False): raise HTTPException(403,f"Canal {ch} non autorisé pour cette société")
    phone=re.sub(r"[^0-9+]","",req.to or ""); body=req.message+((" "+req.ticketUrl) if req.ticketUrl and req.ticketUrl not in req.message else "")
    if ch=="sms":
        base=str(msg.get("ikoddiBaseUrl") or "https://api.ikoddi.com").rstrip("/"); gid=str(msg.get("ikoddiGroupId") or ""); key=str(msg.get("ikoddiApiKey") or "")
        if not gid or not key: raise HTTPException(400,"Configuration SMS IKODDI incomplète")
        status,detail=_http_json(f"{base}/api/v1/groups/{gid}/sms",{"sentTo":[phone.lstrip('+')],"message":body,"from":msg.get("ikoddiSenderId") or "YAMTRANS","smsBroadCast":f"yam-{int(utcnow().timestamp())}","countryStringCode":"BF","countryNumberCode":"226","messageType":"sms"},{"x-api-key":key})
    else:
        num=str(msg.get("whatsappPhoneNumberId") or ""); access=str(msg.get("whatsappAccessToken") or ""); ver=str(msg.get("whatsappApiVersion") or "v23.0")
        if not num or not access: raise HTTPException(400,"Configuration WhatsApp Cloud API incomplète")
        status,detail=_http_json(f"https://graph.facebook.com/{ver}/{num}/messages",{"messaging_product":"whatsapp","to":phone.lstrip('+'),"type":"text","text":{"preview_url":True,"body":body}},{"Authorization":f"Bearer {access}"})
    ok=200<=status<300; _write_notification_log(db,company,{"channel":ch,"to":phone,"kind":req.kind,"reference":req.reference,"status":"sent" if ok else "failed","httpStatus":status,"detail":detail[:800]}); db.commit()
    if not ok: raise HTTPException(502,f"Envoi {ch} refusé ({status})")
    return {"ok":True,"channel":ch,"status":status}

@app.get("/api/v2/platform/companies/{company_id}/notifications/stats")
def notification_stats(company_id: str, token: dict[str,Any]=Depends(read_token), db: Session=Depends(db_session)):
    _platform_only(token); company=db.get(Company,company_id)
    if not company: raise HTTPException(404,"Société introuvable")
    logs=_entity_payloads(db,company.id,"notification_logs")
    def c(ch,st=None): return sum(1 for x in logs if x.get("channel")==ch and (st is None or x.get("status")==st))
    return {"sms":{"total":c("sms"),"sent":c("sms","sent"),"failed":c("sms","failed")},"whatsapp":{"total":c("whatsapp"),"sent":c("whatsapp","sent"),"failed":c("whatsapp","failed")},"recent":sorted(logs,key=lambda x:x.get("createdAt",""),reverse=True)[:100]}

@app.get("/api/v2/tickets/public/{company_code}/{pnr}")
def public_ticket(company_code: str, pnr: str, key: str=Query(default=""), db: Session=Depends(db_session)):
    company=find_company(db,company_code); t=next((x for x in _entity_payloads(db,company.id,"tickets") if str(x.get("pnr","")).upper()==pnr.upper()),None)
    if not t: raise HTTPException(404,"Billet introuvable")
    if key and key!=str(t.get("publicToken") or ""): raise HTTPException(403,"Lien invalide")
    out={k:t.get(k) for k in ["pnr","passengerName","origin","destination","departureAt","seat","seatClass","fare","status","boarded","boardingPoint","dropPoint","busLabel"]}; out["company"]=company.name; return out

@app.get("/ticket", response_class=HTMLResponse)
def public_ticket_page(company: str=Query(default=""), pnr: str=Query(default=""), key: str=Query(default=""), db: Session=Depends(db_session)):
    try: t=public_ticket(company,pnr,key,db)
    except HTTPException as exc: return HTMLResponse(f"<h2>{html.escape(str(exc.detail))}</h2>",status_code=exc.status_code)
    c=find_company(db,company); logo=c.logo_url or ""; img=f'<img src="{html.escape(logo)}">' if logo else ''
    return HTMLResponse(f'''<!doctype html><html lang="fr"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Billet {html.escape(pnr)}</title><style>body{{font-family:Arial;background:#f4f7f6;padding:24px;color:#18352f}}.card{{max-width:620px;margin:auto;background:white;border-radius:24px;padding:24px;box-shadow:0 18px 50px #1232}}.head{{display:flex;gap:14px;align-items:center}}.head img{{width:60px;height:60px;object-fit:contain}}.pnr{{font:800 28px monospace;border:2px dashed #075f4e;padding:12px;border-radius:12px;text-align:center}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.box{{background:#f5f8f7;padding:12px;border-radius:12px}}small{{display:block;color:#667}}@media(max-width:520px){{.grid{{grid-template-columns:1fr}}}}</style><div class="card"><div class="head">{img}<div><h2>{html.escape(str(t['company']))}</h2><small>Billet électronique</small></div></div><div class="pnr">{html.escape(pnr)}</div><div class="grid"><div class="box"><small>Passager</small><b>{html.escape(str(t.get('passengerName') or ''))}</b></div><div class="box"><small>Siège</small><b>{html.escape(str(t.get('seat') or ''))} · {html.escape(str(t.get('seatClass') or ''))}</b></div><div class="box"><small>Trajet</small><b>{html.escape(str(t.get('origin') or ''))} → {html.escape(str(t.get('destination') or ''))}</b></div><div class="box"><small>Départ</small><b>{html.escape(str(t.get('departureAt') or ''))}</b></div><div class="box"><small>Embarquement</small><b>{html.escape(str(t.get('boardingPoint') or ''))}</b></div><div class="box"><small>Statut</small><b>{'Embarqué' if t.get('boarded') else html.escape(str(t.get('status') or 'Confirmé'))}</b></div></div><p>Présentez ce billet ou son QR code à l'embarquement.</p></div></html>''')

ADMIN_WEB_HTML = r'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>YAM TRANS</title><meta http-equiv="refresh" content="0;url=/app/"></head><body><p>Ouverture de YAM TRANS… <a href="/app/">Continuer</a></p></body></html>'''

@app.get("/admin-web", response_class=HTMLResponse)
def admin_web(): return HTMLResponse(ADMIN_WEB_HTML)

def find_company(db: Session, code: str) -> Company:
    company = db.scalar(select(Company).where(Company.code == code.upper(), Company.active.is_(True)))
    if not company:
        raise HTTPException(404, "Société introuvable")
    return company


@app.get("/api/v2/track/{company_code}/{code}")
def track_api(company_code: str, code: str, db: Session = Depends(db_session)):
    company = find_company(db, company_code)
    idx = db.get(ShipmentIndexV3, {"company_id": company.id, "code": code.strip().upper()})
    if not idx:
        raise HTTPException(404, "Envoi introuvable")
    return {**idx.public_payload, "company": company_public(company)}


@app.get("/suivi", response_class=HTMLResponse)
def tracking_page(company: str = Query(default=DEFAULT_COMPANY_CODE), code: str = Query(default=""), db: Session = Depends(db_session)):
    company_obj = find_company(db, company)
    code = code.strip().upper()
    result = None
    if code:
        idx = db.get(ShipmentIndexV3, {"company_id": company_obj.id, "code": code})
        result = idx.public_payload if idx else None
    logo = company_obj.logo_url
    brand = html.escape(company_obj.name)
    brand_settings = dict(company_obj.settings or {})
    def _color(key, fallback):
        v = str(brand_settings.get(key) or "").strip()
        return v if re.fullmatch(r"#[0-9A-Fa-f]{6}", v) else fallback
    primary = _color("primaryColor", "#075f4e")
    secondary = _color("secondaryColor", "#063d34")
    accent = _color("accentColor", "#1769df")
    tracking_title = html.escape(str(brand_settings.get("trackingTitle") or "Suivez votre envoi"))
    tracking_subtitle = html.escape(str(brand_settings.get("trackingSubtitle") or "Du dépôt jusqu’au point de retrait, étape par étape."))
    support_email = html.escape(str(brand_settings.get("supportEmail") or ""))
    website = str(brand_settings.get("website") or "").strip()
    logo_html = f'<img class="brand-logo" src="{html.escape(logo)}" alt="Logo">' if logo else '<div class="brand-mark">↗</div>'
    content = ''
    if result:
        stages = [
            ("Enregistré", "Dépôt enregistré", "Votre envoi a été pris en charge."),
            ("En attente de départ", "Préparé pour le départ", "Le colis est rattaché à son expédition."),
            ("Expédié", "En route", "Le véhicule a quitté l’agence de départ."),
            ("Arrivé à destination", "Arrivé à destination", "Le colis est arrivé dans la ville de destination."),
            ("Disponible pour retrait", "Prêt à être retiré", "Vous pouvez vous rendre au point de retrait."),
            ("Livré", "Remis au destinataire", "Le retrait a été enregistré avec succès."),
        ]
        aliases = {"Confirmé": "Enregistré", "Bordereau créé": "En attente de départ"}
        current = aliases.get(str(result.get("status", "")), str(result.get("status", "")))
        names = [s[0] for s in stages]
        current_idx = names.index(current) if current in names else 0
        event_dates = {aliases.get(str(e.get("status", "")), str(e.get("status", ""))): str(e.get("at", "")) for e in result.get("events", []) or [] if isinstance(e, dict)}
        event_dates.setdefault("Enregistré", str(result.get("createdAt", "")))
        steps = []
        for i, (status, title, desc) in enumerate(stages):
            cls = "done" if i < current_idx else "current" if i == current_idx else "future"
            symbol = "✓" if i < current_idx else "●" if i == current_idx else str(i + 1)
            date = event_dates.get(status, "")[:16].replace("T", " · ") or ("Étape en cours" if i == current_idx else "À venir")
            steps.append(f'<li class="step {cls}"><span class="dot">{symbol}</span><div><div class="step-head"><b>{html.escape(title)}</b><small>{html.escape(date)}</small></div><p>{html.escape(desc)}</p></div></li>')
        agency = agency_public_info(db, company_obj.id, str(result.get("destination", "")))
        pickup = ''
        if agency:
            map_html = f'<iframe src="{html.escape(agency["mapEmbed"])}" loading="lazy"></iframe>' if agency.get("mapEmbed") else ''
            btn = f'<a class="maps" href="{html.escape(agency["mapsUrl"])}" target="_blank" rel="noopener">📍 Ouvrir l’itinéraire Google Maps</a>' if agency.get("mapsUrl") else ''
            pickup = f'<section class="card pickup"><span class="kicker">POINT DE RETRAIT</span><h2>{html.escape(agency["pickupName"])}</h2><p>{html.escape(agency["address"])}</p><div class="hint">💡 {html.escape(agency["pickupDirections"])}</div>{map_html}{btn}</section>'
        content = f'<section class="card hero"><span class="badge">Envoi trouvé</span><h1>{html.escape(code)}</h1><div class="route"><b>{html.escape(str(result.get("origin", "")))}</b><span>→</span><b>{html.escape(str(result.get("destination", "")))}</b></div><div class="chips"><span>{html.escape(str(result.get("type", "Envoi")))}</span><span>{result.get("parcelCount",1)} colis</span><span>Destinataire {html.escape(str(result.get("receiverName", "")))}</span></div></section><section class="card"><span class="kicker">SUIVI ÉTAPE PAR ÉTAPE</span><h2>Où en est votre envoi ?</h2><ol>{"".join(steps)}</ol></section>{pickup}'
    elif code:
        content = f'<section class="card missing"><h2>Envoi introuvable</h2><p>Aucun envoi <b>{html.escape(code)}</b> n’existe pour la société {brand}.</p></section>'
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="{primary}"><title>Suivi · {brand}</title><style>
*{{box-sizing:border-box}}:root{{--g:{primary};--g2:{secondary};--accent:{accent};--ink:#102621;--muted:#71817d;--line:#dfeae7;--soft:#eef8f5}}body{{margin:0;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;background:linear-gradient(180deg,#e9f7f2 0,#f8fbfa 340px);color:var(--ink)}}.top{{background:linear-gradient(135deg,var(--g2),var(--g));color:#fff;padding:14px 20px}}.topin{{max-width:850px;margin:auto;display:flex;align-items:center;justify-content:space-between}}.brandbox{{display:flex;align-items:center;gap:10px;font-weight:900}}.brand-logo{{width:36px;height:36px;object-fit:contain;border-radius:9px;background:#fff}}.brand-mark{{width:36px;height:36px;border-radius:10px;background:#fff;color:var(--g);display:grid;place-items:center;font-size:23px}}.wrap{{max-width:820px;margin:auto;padding:32px 15px 60px}}.intro{{text-align:center;margin-bottom:22px}}.intro h1{{font-size:30px;margin:0}}.intro p{{color:var(--muted)}}form{{display:flex;gap:8px;background:white;padding:10px;border-radius:18px;border:1px solid var(--line);box-shadow:0 14px 40px #164e4210}}input{{flex:1;padding:15px;border:1px solid #d5e2de;border-radius:12px;font-size:16px;text-transform:uppercase}}button,.maps{{border:0;border-radius:12px;background:var(--g);color:white;padding:0 20px;font-weight:850;text-decoration:none;display:flex;align-items:center;justify-content:center;min-height:48px}}.card{{background:#fff;border:1px solid var(--line);border-radius:22px;padding:23px;margin-top:17px;box-shadow:0 14px 45px #123d3410}}.hero{{text-align:center}}.badge{{display:inline-block;background:#e5f7f0;color:#087154;border-radius:99px;padding:7px 11px;font-size:11px;font-weight:900}}.hero h1{{font-family:ui-monospace,monospace;font-size:34px;letter-spacing:2px;margin:14px 0}}.route{{display:flex;align-items:center;justify-content:center;gap:20px;background:var(--soft);padding:14px;border-radius:15px}}.route span{{color:var(--g2);font-size:23px}}.chips{{display:flex;justify-content:center;gap:7px;flex-wrap:wrap;margin-top:13px}}.chips span{{font-size:10px;background:#f3f6f5;border-radius:99px;padding:7px 9px;color:#5e706b}}.kicker{{font-size:10px;letter-spacing:.13em;font-weight:900;color:var(--g2)}}.card h2{{margin:6px 0 18px}}ol{{list-style:none;padding:0;margin:0}}.step{{display:grid;grid-template-columns:42px 1fr;gap:12px;position:relative;padding-bottom:20px}}.step:not(:last-child):before{{content:"";position:absolute;left:20px;top:40px;bottom:0;width:2px;background:#dce6e3}}.step.done:not(:last-child):before{{background:#2aa27e}}.dot{{width:42px;height:42px;border-radius:50%;border:2px solid #d7e1de;display:grid;place-items:center;font-weight:900;color:#95a49f;background:#fff;z-index:1}}.done .dot{{background:var(--g2);border-color:var(--g2);color:#fff}}.current .dot{{border:7px solid #8ed9c5;color:var(--g);box-shadow:0 0 0 4px #e5f7f1}}.future{{opacity:.48}}.step-head{{display:flex;justify-content:space-between;gap:10px}}.step-head small{{color:#82918d}}.step p{{font-size:12px;color:var(--muted);margin:5px 0}}.pickup iframe{{width:100%;height:250px;border:0;border-radius:15px;margin:14px 0}}.pickup>p{{color:var(--muted)}}.hint{{background:#fff6df;border:1px solid #f4dfae;border-radius:12px;padding:12px;margin:12px 0;font-size:12px}}.maps{{background:var(--accent)}}.missing{{text-align:center}}footer{{text-align:center;color:#7b8b87;font-size:10px;margin-top:25px}}.card{{animation:ytReveal .45s ease both}}.current .dot{{animation:ytPulse 1.8s infinite}}@keyframes ytReveal{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}@keyframes ytPulse{{50%{{box-shadow:0 0 0 10px transparent}}}}button,.maps{{transition:.18s ease;position:relative;overflow:hidden}}button:active,.maps:active{{transform:scale(.975)}}@media(max-width:600px){{.wrap{{padding:22px 12px 45px}}form{{display:grid}}button{{height:49px}}.hero h1{{font-size:27px}}.card{{padding:18px;border-radius:18px}}.step-head{{display:block}}.step-head small{{display:block;margin-top:3px}}}}
</style></head><body><div class="top"><div class="topin"><div class="brandbox">{logo_html}<span>{brand}</span></div><span>● Suivi sécurisé</span></div></div><main class="wrap"><div class="intro"><h1>{tracking_title}</h1><p>{tracking_subtitle}</p></div><form><input type="hidden" name="company" value="{html.escape(company_obj.code)}"><input name="code" value="{html.escape(code)}" placeholder="Code · OUA-00001" required><button>Suivre</button></form>{content}<footer>Besoin d’aide ? {html.escape(company_obj.phone or '')}{(' · '+support_email) if support_email else ''}{(' · '+html.escape(website)) if website else ''}</footer></main></body></html>'''


@app.get("/")
def root():
    return {"service": "Transport Multi-Sociétés", "version": "4.6.0", "health": f"{PUBLIC_BASE_URL}/health", "tracking": f"{PUBLIC_BASE_URL}/suivi?company={DEFAULT_COMPANY_CODE}&code=OUA-00001"}


# Interface web complète : le même client que l'application Android, avec les mêmes rôles.
# Les fichiers sont construits dans /webapp au moment du packaging de la release.
WEBAPP_DIR=os.getenv("WEBAPP_DIR", "/app/webapp")
if os.path.isdir(WEBAPP_DIR):
    _assets_dir=os.path.join(WEBAPP_DIR, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/app/assets", StaticFiles(directory=_assets_dir), name="yamtrans-web-assets")

    @app.get("/app", include_in_schema=False)
    @app.get("/app/", include_in_schema=False)
    def yamtrans_web_root():
        return FileResponse(os.path.join(WEBAPP_DIR, "index.html"))

    @app.get("/app/{full_path:path}", include_in_schema=False)
    def yamtrans_web_routes(full_path: str):
        # Chaque rubrique a une vraie URL partageable, mais le frontend reste une SPA.
        candidate=os.path.abspath(os.path.join(WEBAPP_DIR, full_path))
        root=os.path.abspath(WEBAPP_DIR)
        if candidate.startswith(root + os.sep) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(WEBAPP_DIR, "index.html"))
