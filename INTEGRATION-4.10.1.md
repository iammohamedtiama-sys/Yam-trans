# YAM TRANS — Correctif serveur 4.10.1

Les sessions ouvertes depuis « Administration plateforme → Ouvrir la société » sont désormais reconnues dans la billetterie, les services avancés, le pilotage et le suivi GPS.

Le serveur résout l’acteur opérationnel après vérification du compte plateforme réel et de la société ciblée. Les opérations conservent l’identifiant de la session déléguée pour leur traçabilité. La désactivation ou la perte du rôle administrateur révoque immédiatement cet accès ; une société inactive ou un module Tickets désactivé reste inaccessible.

Validation : 104 tests serveur réussis, dont sept tests supplémentaires couvrant les lectures, écritures, restrictions de modules et révocations des sessions déléguées. Aucun changement du client Android n’est requis pour ce correctif.
