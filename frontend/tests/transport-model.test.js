import test from 'node:test';
import assert from 'node:assert/strict';
import { allocationActive, segmentFare, peakOccupancy, ticketNetReceipts } from '../src/transport-model.js';

const trip={origin:'Ouaga',destination:'Bobo',stops:'Boromo',fareSimple:5000,fareVip:7000};
test('une réservation expirée libère le siège',()=>{
  assert.equal(allocationActive({status:'Réservée',expiresAt:'2000-01-01T00:00:00Z'}),false);
  assert.equal(allocationActive({status:'Convertie'}),false);
});
test('le tarif du tronçon est repris selon la classe',()=>{
  assert.equal(segmentFare({segmentFares:'Ouaga>Boromo=1500,2500\nBoromo>Bobo=3500,4500'},trip,'Ouaga','Boromo','VIP'),2500);
  assert.equal(segmentFare({},trip,'Ouaga','Bobo','Simple'),5000);
});
test('deux voyageurs successifs ne gonflent pas le taux de remplissage',()=>{
  assert.equal(peakOccupancy(trip,[{boardingPoint:'Ouaga',dropPoint:'Boromo'},{boardingPoint:'Boromo',dropPoint:'Bobo'}]),1);
});
test('le pic de charge compte les voyageurs simultanés',()=>{
  assert.equal(peakOccupancy(trip,[{boardingPoint:'Ouaga',dropPoint:'Bobo'},{boardingPoint:'Boromo',dropPoint:'Bobo'},{boardingPoint:'Ouaga',dropPoint:'Bobo',status:'Remboursé'}]),2);
});
test('les recettes conservent la retenue après un remboursement partiel',()=>{
  assert.equal(ticketNetReceipts({paid:5000,status:'Remboursé',refundedAmount:4000}),1000);
  assert.equal(ticketNetReceipts({paid:5000,status:'Remboursé'}),0);
  assert.equal(ticketNetReceipts({paid:0,fare:5000,status:'Confirmé'}),0);
});

test('le tarif central de ligne reste prioritaire sur celui du bus ou départ',()=>{
  assert.equal(segmentFare({fareSimple:6000,fareVip:8500},{...trip,fareSimple:100},'Ouaga','Bobo','Simple'),6000);
});
test('la catégorie enfant est indépendante de la classe du siège',()=>{
  const route={fareSimple:5000,fareVip:7000,fareChildSimple:2500,fareChildVip:4000};
  assert.equal(segmentFare(route,trip,'Ouaga','Bobo','VIP','child'),4000);
  assert.equal(segmentFare(route,trip,'Ouaga','Bobo','Simple','child'),2500);
});
