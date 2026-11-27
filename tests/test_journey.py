import pytest
from fastapi import HTTPException
from test_transport import m
from app.journey import journey_stops, journey_span, canonical_segment
from app.transport import route_fare

@pytest.mark.parametrize('middle', [' Boromo ; Houndé\n', [' Boromo ', {'name':'Houndé'}], 'Boromo,Houndé'])
def test_stop_encodings(middle):
    tr={'origin':' Ouagadougou\u00a0','destination':' BOBO ','stops':middle}
    assert journey_stops(tr)==['Ouagadougou','Boromo','Houndé','BOBO']
    assert canonical_segment(tr,{'boardingPoint':'ouagadougou','dropPoint':'HOUNDE '})=={'boardingPoint':'Ouagadougou','dropPoint':'Houndé'}

@pytest.mark.parametrize('item', [{'boardingPoint':'Paris'}, {'boardingPoint':'Bobo','dropPoint':'Ouaga'}, {'boardingPoint':'Ouaga','dropPoint':'Ouaga'}])
def test_unknown_and_reverse_rejected(item):
    with pytest.raises(HTTPException): journey_span({'origin':'Ouaga','destination':'Bobo'},item)

def test_adjacent_duplicates_collapse_but_ambiguous_loop_rejected():
    assert journey_stops({'origin':'Ouaga','stops':['ouaga','Boromo','boromo'],'destination':'BOBO'})==['Ouaga','Boromo','BOBO']
    with pytest.raises(HTTPException):journey_stops({'origin':'Ouaga','stops':['Bobo'],'destination':'ouaga'})

def test_segment_fare_normalizes_stops_and_rejects_invalid_amount():
    route={'segmentFares':'Ouaga>Houndé=1500,2500'}
    tr={'origin':'Ouaga','destination':'Bobo'}
    segment={'boardingPoint':' OUAGA ','dropPoint':'HOUNDE'}
    assert route_fare(route,tr,segment,'Simple')==1500
    with pytest.raises(HTTPException):route_fare({'segmentFares':'Ouaga>Houndé=NaN,2500'},tr,segment,'Simple')


def test_night_boarding_crosses_midnight_but_does_not_open_other_days():
    from datetime import datetime,timezone,timedelta
    from app.transport import boarding_day_allowed
    at=datetime(2026,11,26,23,50,tzinfo=timezone.utc)
    assert boarding_day_allowed(at+timedelta(minutes=30),at)
    assert boarding_day_allowed(at-timedelta(hours=2),at)
    assert not boarding_day_allowed(at+timedelta(days=1),at)
