# Validation de YamTrans 4.8.0

## Contrôles réalisés

- API FastAPI : scénarios métier, isolation, droits, écritures concurrentes et erreurs financières dans `server/tests/test_transport.py`.
- Client : règles de sièges, tarifs de ligne adulte/enfant, recettes nettes et sécurité des documents imprimés.
- Interface Electron avec serveur et base temporaires : vente enfant, prix serveur, siège rouge, point de départ automatique, consignation et rapport.
- Coupure simulée après validation serveur : reprise du billet après rechargement, deux billets au total et aucun second encaissement.
- Construction Vite du client et du frontend serveur ; comparaison des sources partagées.

L’imprimante est simulée dans le parcours d’interface. Les appels externes d’IA sont simulés pour contrôler les données envoyées ; aucune clé de fournisseur n’est nécessaire aux tests. L’OCR est exécuté réellement sur une image de test par Tesseract.

## Reproduire les contrôles

```sh
# Serveur, dans son environnement Python avec requirements.txt, pytest et httpx
python -m pytest -q tests/test_transport.py

# Application
npm ci
npm run desktop:test

# Interface Electron sous Linux, avec le dépôt serveur disponible à côté de l’app
YAMTRANS_TEST_PYTHON=/chemin/vers/python npm run desktop:smoke

# Exécutables Windows x64
npm run desktop:windows
```

Le test Electron remplace uniquement le verrou mono-instance dans son programme de démarrage de test, car l’environnement Linux ne fournit pas son socket. Le programme distribué conserve son verrou normal. L’essai ne remplace pas une validation sur PC Windows avec la caméra, le GPS et les imprimantes réellement utilisés.
