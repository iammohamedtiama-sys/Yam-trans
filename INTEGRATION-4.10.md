# YAM TRANS 4.10 — Téléphone, identité et suivi GPS

Cette version complète les services 4.9 avec les parcours de billetterie sur téléphone, la capture des pièces et le suivi des véhicules.

## Utilisation

- Navigation mobile propre au service actif, boutons tactiles, retours de pression, zones de sécurité et zoom accessible.
- Vente sur un écran compact ; le plan du bus s’ouvre dans une fenêtre dédiée et revient au formulaire après sélection. Les valeurs du formulaire sont conservées.
- CNIB et passeport pris directement avec la caméra. Aucun import de galerie dans ces parcours. La caméra est libérée à la fermeture ou au changement de page.
- Lecture du document puis vérification humaine du numéro et de la photo : CNIB commençant par B, passeport par A. Une photo illisible permet une correction manuelle confirmée ; elle ne produit pas une identité supposée fiable.
- Recherche du billet et contrôle d’embarquement avec ce numéro, en complément du QR et du PNR. La confirmation reste explicite et le serveur refuse les doubles embarquements.
- Capture des pièces également disponible pour les voyageurs d’une réservation groupée.
- Encaissement du solde depuis le détail du billet, sans dépasser le montant dû, avec protection contre les répétitions et modification frauduleuse par synchronisation.
- Bagages accessibles dans le menu Tickets.

## GPS

La page Suivi des véhicules rassemble les dernières positions des téléphones et des boîtiers. La carte indique la date, la source, la précision et, si reçue, la vitesse. Une position de plus de cinq minutes est signalée comme ancienne. La mise à jour de la page se fait toutes les trente secondes lorsqu’elle est visible.

La localisation du téléphone utilise les permissions du système. Le suivi continu nécessite de conserver l’application ouverte ; cette version ne promet pas de suivi en arrière-plan.

Un responsable associe un boîtier à un bus dans la page de suivi. La clé est affichée une seule fois, renouvelable et révocable. Elle est conservée sous forme de condensat côté serveur et exclue des sauvegardes exportées. Chaque boîtier utilise sa propre clé, distincte des comptes agents.

### Envoi depuis un boîtier ou une passerelle

`POST /api/v2/gps/positions`, avec `Content-Type: application/json` et `Authorization: Bearer <clé du boîtier>`.

```json
{
  "id": "frame-000001",
  "recordedAt": "2026-11-11T10:30:00Z",
  "latitude": 12.3714,
  "longitude": -1.5197,
  "accuracy": 10,
  "speedKph": 35,
  "heading": 90,
  "tripId": "identifiant-du-voyage"
}
```

Le champ `id` identifie une mesure : renvoyer la même mesure est sans doublon ; modifier son contenu sous le même identifiant est refusé. `tripId` peut être omis lorsqu’un seul voyage correspond au bus et à la date. Une correspondance ambiguë impose de le préciser. Les coordonnées invalides, dates futures de plus de deux minutes et mesures vieilles de plus de sept jours sont refusées. Une mesure reçue tardivement ne remplace pas une position plus récente. L’historique interne est limité à mille mesures par boîtier.

L’interface HTTP JSON est prête. Le raccordement d’un matériel utilisant TCP ou un protocole constructeur nécessite sa passerelle ou son adaptateur ; le modèle de boîtier n’est pas encore choisi.

## Vérification

- 97 tests serveur : réservations, paiements, droits et isolation des sociétés, pièces, embarquement, GPS, export et OCR Tesseract sur une image synthétique.
- 25 tests JavaScript : identité, modèles, caméra, annulation, permissions, géolocalisation et interface.
- Parcours navigateur avec API réelle et base temporaire aux largeurs 320, 360, 390, 430, 768 et 1280 pixels : absence de débordement horizontal, bus de 52 places, photo, vente, solde, embarquement répété, position téléphone et boîtier, carte et pages Tickets.
- Dans le navigateur de test, la vidéo caméra est simulée et le résultat OCR du parcours est contrôlé. La reconnaissance OCR réelle fait l’objet du test serveur séparé. Les tuiles de carte externes sont remplacées pendant l’essai automatique.
- Constructions web et synchronisation des ressources Android vérifiées. Un nouvel APK, les permissions sur un téléphone physique, une véritable CNIB et un boîtier embarqué restent à vérifier sur le matériel cible.

Les modifications sont proposées dans les demandes de fusion existantes ; elles ne constituent pas un déploiement en production.
