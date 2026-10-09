# Contrôles et preuves

Correspondances thématiques avec ENISA ; pas une certification ni une couverture exhaustive
de ses 22 playbooks. Les tests nommés sont dans `tests/`.

| Objectif | Implémentation | Preuve reproductible | Limite |
|---|---|---|---|
| Défaut restrictif | Outil unique et IDs autorisés | `test_policy.py` | Pas d'exécution de code tiers |
| Authentification | Jeton aléatoire obligatoire | `test_api.py` | Un seul utilisateur, TLS hors périmètre |
| Intégrité des mises à jour | Ed25519, clé distincte | `test_releases.py` | Administrateur et clé de confiance |
| Maintenabilité | Lockfile, versions, rollback | CLI `demo` et tests releases | Images/modèles gérés manuellement |
| Traçabilité | SQLite et chaîne de hashes | `test_audit.py` | Checkpoint externe nécessaire |
| Inventaire | SBOM + composants modèles observés | `test_inventory.py`, artefacts CI | Ni OS ni provenance d'entraînement |
| Résilience | Bornes, délai et refus si audit indisponible | `test_api.py`, `test_provider.py` | Pas de protection DDoS hôte |
| Évaluation IA | Corpus bénin/malveillant | CLI `evaluate --live` | Corpus réduit, aucun taux généralisable |
| Vulnérabilités hors ligne | Procédure avec dates de fraîcheur | `docs/offline-operations.md` | Suivi manuel en v0.1 |

## Critères de sortie v0.1

Lint, tests, démo de release et build Docker verts ; rapport de validation distinguant
tests simulés et modèle réel. Aucun secret/poids de modèle dans Git. Ne déclarer aucun
contrôle effectivement vérifié si seule sa configuration a été écrite.
