"""Server-only Checkout adapter. Provider replies never define the amount due."""
import json
import os
from decimal import Decimal, InvalidOperation
from urllib import request
from urllib.parse import quote, urlsplit
from fastapi import HTTPException

BASES={'https://api.yengapay.com/api/v1','https://api.sandbox.yengapay.com/api/v1'}

def configured():
    return all(os.getenv(k,'').strip() for k in ('YENGAPAY_API_KEY','YENGAPAY_GROUP_ID','YENGAPAY_PROJECT_ID'))

def api(method, suffix, body=None):
    if not configured():raise HTTPException(503,'Le paiement en ligne sera disponible après activation par la compagnie.')
    base=os.getenv('YENGAPAY_BASE_URL','https://api.yengapay.com/api/v1').rstrip('/')
    if base not in BASES:raise HTTPException(503,'Configuration du paiement à vérifier')
    group=quote(os.environ['YENGAPAY_GROUP_ID'],safe=''); project=quote(os.environ['YENGAPAY_PROJECT_ID'],safe='')
    url=base+'/groups/'+group+suffix.replace('{project}',project)
    req=request.Request(url,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'x-api-key':os.environ['YENGAPAY_API_KEY'],'Content-Type':'application/json','Accept':'application/json'})
    # No redirects: an API key must never be forwarded to another host.
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    try:
        with request.build_opener(NoRedirect).open(req,timeout=12) as reply:
            raw=reply.read(1_000_001)
            if len(raw)>1_000_000:raise ValueError()
            data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError()
            return data.get('data',data) if isinstance(data.get('data',data),dict) else data
    except Exception:raise HTTPException(502,'Réponse du paiement indisponible. Vérifiez cette commande avant de recommencer.') from None

def create(reference, amount, title):
    return api('POST','/payment-intent/{project}',{'paymentAmount':amount,'reference':reference,'articles':[{'title':title,'description':'Billet de transport YAM TRANS','price':amount}]})

def retrieve(intent):
    return api('GET','/payment-intent/project/{project}/intent/'+quote(intent,safe=''))

def intent_id(data):return str(data.get('id') or data.get('paymentIntentId') or data.get('yengaPaymentIntentId') or '')

def checkout_url(data):
    url=str(data.get('checkoutPageUrlWithPaymentToken') or '')
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or not (parsed.hostname=='yengapay.com' or (parsed.hostname or '').endswith('.yengapay.com')):
        raise HTTPException(502,'Lien de paiement invalide. Contactez la compagnie avec la référence de commande.')
    return url

def verified_paid(data, order):
    status=str(data.get('paymentStatus') or data.get('transactionStatus') or data.get('status') or '').upper()
    if status not in {'DONE','SUCCESS','SUCCESSFUL','SUCCEEDED','CONFIRMED','PAID','COMPLETED','VALIDATED'}:return False
    try:amount=Decimal(str(data.get('paymentAmount',data.get('amount',''))))
    except InvalidOperation:raise HTTPException(409,'Montant reçu à vérifier auprès de la compagnie') from None
    if not amount.is_finite() or amount!=Decimal(str(order['amount'])) or str(data.get('reference') or '')!=order['id'] or intent_id(data)!=order['intentId'] or str(data.get('currency') or data.get('paymentCurrency') or 'XOF').upper()!='XOF':
        raise HTTPException(409,'Le paiement reçu ne correspond pas à cette commande. Contactez la compagnie.')
    return True
