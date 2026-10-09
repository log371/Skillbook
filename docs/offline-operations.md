# Exploitation hors ligne

## Deux zones

Le poste de préparation connecté télécharge et examine les dépendances, modèles, images et
avis de vulnérabilité. Le serveur isolé ne possède pas la clé privée de signature. Installer
sa clé publique par un canal de confiance indépendant du support contenant les paquets.
Une empreinte fournie sur le même support que le fichier ne suffit pas à authentifier l'émetteur.

## Préparer

1. Vérifier le commit, `uv.lock`, les licences et la provenance des modèles.
2. Construire l'image API et exécuter la CI. Exporter les images avec `docker save` et relever
   leurs digests. Télécharger le modèle dans un environnement Ollama dédié. Exporter son
   volume contenant manifestes et blobs ; conserver l'inventaire et les empreintes des fichiers.
3. Générer le SBOM Python et un SBOM de chaque image avec un outil dédié (non fourni).
4. Comparer les composants à une base de vulnérabilités à jour ; conserver version/date de
   la base, résultats, exceptions motivées et date de prochaine revue. Aucun scan n'est
   équivalent à « aucune vulnérabilité ». Une base périmée doit être signalée comme telle.
5. Créer et signer une release JSON de documents/permissions. Conserver la clé privée
   dans un environnement maîtrisé. Les clés de démo non chiffrées ne sont pas un dispositif HSM.

## Transférer et activer

Pour préparer le modèle avec Ollama installé sur l'hôte, depuis la racine du dépôt
(deux terminaux, poste connecté uniquement) :

```bash
# Terminal 1 : stockage dédié.
mkdir -p state/models
OLLAMA_MODELS="$PWD/state/models" OLLAMA_HOST=127.0.0.1:11435 OLLAMA_NO_CLOUD=1 ollama serve
# Terminal 2 :
OLLAMA_HOST=127.0.0.1:11435 ollama pull qwen2.5:0.5b
```

Arrêter ce serveur de préparation avec Ctrl+C après le téléchargement. Le Compose montera
`state/models` en lecture seule. Sur une autre machine, transférer intégralement ce dossier
après vérification de sa provenance et de ses empreintes. Ne pas publier les poids dans Git.

Test conteneurisé (arrête sa propre pile à la fin, conserve le volume d'audit) :

```bash
uv run --frozen python scripts/smoke.py --compose
```

- Inspecter le support amovible selon la procédure du site. Transférer images, modèles,
  paquet, rapports et instructions. Vérifier signatures et empreintes **avant** import.
- Importer les images avec `docker load` ; restaurer le volume Ollama avant de lancer
  le réseau isolé. Tester d'abord la procédure sur la même architecture CPU/GPU que la cible.
- Pour les documents/permissions, `skillbook verify`, puis `skillbook activate`.
  Ne pas rendre le répertoire opérateur modifiable par l'API. Monter clé publique et releases
  en lecture seule. L'API ne possède aucune route d'activation.
- Redémarrer l'API. Contrôler version et empreinte via `/v1/status`, tester une lecture
  légitime et un refus. Exporter la tête du journal vers un stockage indépendant.

## Retour arrière

Arrêter l'API, conserver les preuves, puis utiliser `skillbook rollback` avec l'identifiant
d'une release déjà installée. Le compteur maximal est conservé. Redémarrer et contrôler.
Une release signée ancienne importée directement via `activate` reste refusée.
Pour images/modèles, restaurer manuellement les exports préalablement vérifiés : leur
remplacement automatique est hors périmètre du CLI v0.1.

## Fréquence et incident

Proposition opératoire à adapter : revue hebdomadaire sur le poste connecté, revue urgente
après un avis critique applicable ; fenêtre de transfert planifiée et procédure d'urgence.
Une base CVE de plus de 7 jours est marquée périmée dans le registre opérateur (ce suivi est
manuel en v0.1). Noter aussi la dernière mise à jour du serveur, pas seulement celle de la base.
En cas de clé compromise : geler les mises à jour, rétablir la confiance par un canal distinct,
révoquer/remplacer la clé publique sur la cible et réexaminer les releases activées.
La signature prouve l'origine et l'intégrité ; elle ne prouve pas que le contenu est sûr.
