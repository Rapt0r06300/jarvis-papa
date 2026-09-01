# Jarvis Papa

Assistant personnel **local-first** pour Windows, conçu pour simplifier les tâches quotidiennes : mails, fichiers, agenda, rappels et interaction vocale.

## Principes

- **Local-first** : les données personnelles restent locales autant que possible.
- **Validation humaine** : toute action sensible (envoyer, supprimer, modifier) doit être confirmée avant exécution.
- **Aucun secret dans GitHub** : clés API, mots de passe et jetons restent dans un fichier `.env` local ignoré par Git.
- **Architecture modulaire** : mails, fichiers, voix et agenda sont ajoutés comme services indépendants.
- **Traçabilité** : les actions importantes doivent pouvoir être journalisées et expliquées.

## V1

La première version vise :

1. un serveur local Jarvis ;
2. une page d’accueil simple ;
3. un moteur de commandes ;
4. une politique de sécurité centralisée ;
5. des connecteurs futurs pour mails, fichiers, agenda et voix.

## Démarrage (Windows)

Prérequis : Python 3.12+.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
copy .env.example .env
jarvis-papa
```

Puis ouvrir `http://127.0.0.1:8765`.

## Tests

```powershell
pytest
```

## Sécurité

Jarvis sépare les opérations en trois niveaux :

- **READ** : consultation et recherche, exécutables sans confirmation supplémentaire ;
- **WRITE** : modification locale, confirmation requise par défaut ;
- **DESTRUCTIVE** : suppression, envoi externe ou action irréversible, confirmation explicite obligatoire.

Le but est d'augmenter progressivement l'autonomie sans sacrifier le contrôle de l'utilisateur.
