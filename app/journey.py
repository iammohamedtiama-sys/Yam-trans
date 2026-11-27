"""Canonical stop resolution shared by booking, allocations, fares and passenger search."""
import re
import unicodedata
from fastapi import HTTPException


def stop_name(value):
    if isinstance(value,dict):
        value=value.get('name') or value.get('label') or ''
    return re.sub(r'\s+',' ',str(value or '')).strip()


def stop_key(value):
    value=unicodedata.normalize('NFKD',stop_name(value))
    return ''.join(c for c in value if not unicodedata.combining(c)).casefold()


def journey_stops(trip):
    middle=trip.get('stops') or []
    if isinstance(middle,str):middle=re.split(r'[,;\n\r]+',middle)
    if not isinstance(middle,list):raise HTTPException(422,'Les arrêts de la ligne sont invalides')
    origin,destination=stop_name(trip.get('origin')),stop_name(trip.get('destination'))
    if not origin or not destination:raise HTTPException(422,'Départ et destination de la ligne requis')
    result=[];seen=set()
    for raw in [origin,*middle,destination]:
        name=stop_name(raw)
        if not name:continue
        key=stop_key(name)
        if result and stop_key(result[-1])==key:continue
        if key in seen:raise HTTPException(422,'Arrêt répété sur la ligne : '+name+'. Précisez des étapes distinctes.')
        seen.add(key);result.append(name)
    if len(result)<2:raise HTTPException(422,'Le départ et la destination doivent être différents')
    return result


def journey_span(trip,item):
    stops=journey_stops(trip);keys=[stop_key(s) for s in stops]
    found=[]
    for field,default in [('boardingPoint','origin'),('dropPoint','destination')]:
        value=item.get(field) or trip.get(default)
        try:found.append(keys.index(stop_key(value)))
        except ValueError:
            raise HTTPException(422,'Arrêt « '+stop_name(value)+' » absent de ce trajet. Arrêts disponibles : '+' → '.join(stops)+'. Actualisez le départ puis choisissez à nouveau le siège.')
    if found[0]>=found[1]:raise HTTPException(422,'La descente doit suivre l’embarquement')
    return tuple(found)


def canonical_segment(trip,item):
    start,end=journey_span(trip,item);stops=journey_stops(trip)
    return {'boardingPoint':stops[start],'dropPoint':stops[end]}
