"""Optional AI interpretation of aggregate reports. Never executes recommendations."""
import json
import os
from urllib import request, error
from fastapi import HTTPException


def interpret(report):
    key=os.getenv('YAMTRANS_AI_API_KEY','')
    model=os.getenv('YAMTRANS_AI_MODEL','')
    endpoint=os.getenv('YAMTRANS_AI_ENDPOINT','https://api.openai.com/v1/chat/completions')
    if not key or not model:
        raise HTTPException(503,'L’assistant IA nécessite une clé et un modèle configurés sur le serveur. Les analyses chiffrées restent disponibles.')
    if not endpoint.startswith('https://'):
        raise HTTPException(503,'Le fournisseur IA doit utiliser HTTPS')
    # No customer, employee, phone, identity document or precise GPS is sent.
    aggregate={'trips':[{'reference':f'Départ {i+1}',**{k:t[k] for k in ('departureAt','tickets','occupancyPct','cashIncome','prepaidAllocated','income','expenses','net')}} for i,t in enumerate(report['trips'][:150])],
        'crewWorkload':[{'reference':f'Agent {i+1}','weeklyTrips':p['weeklyTrips'],'alerts':p['alerts']} for i,p in enumerate(report['crew'])],
        'unallocatedExpenses':report['unallocatedExpenses'],'parkingIncome':report['parkingIncome'],'prepaidIncome':report['prepaidIncome']}
    body={'model':model,'messages':[{'role':'system','content':'Tu aides une compagnie de transport. Réponds en français clair avec au plus 6 observations et actions à examiner. Utilise uniquement les chiffres fournis. Distingue encaissements et revenus de voyages prépayés pour ne pas les compter deux fois. Les coûts peuvent être incomplets. Ne conclus pas à une fraude ni à une fatigue médicale, ne recommande aucune sanction individuelle et ne prends aucune décision automatiquement. Les références sont anonymisées.'},{'role':'user','content':json.dumps(aggregate,ensure_ascii=False)}]}
    req=request.Request(endpoint,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    try:
        with request.urlopen(req,timeout=40) as response:
            payload=json.loads(response.read(1000000))
        answer=payload['choices'][0]['message']['content']
        if not isinstance(answer,str) or not answer.strip():raise ValueError()
        return {'text':answer[:16000],'model':model,'method':'Analyse IA de données agrégées et anonymisées. Suggestions à vérifier par un responsable.'}
    except (error.URLError,KeyError,ValueError,TypeError):
        raise HTTPException(502,'Le fournisseur IA n’a pas répondu correctement. Le rapport chiffré reste disponible.') from None
