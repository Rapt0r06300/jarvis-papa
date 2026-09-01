# Jarvis Papa

Assistant personnel **local-first** pour Windows, conçu pour Robert afin de simplifier les tâches quotidiennes : mails, fichiers, agenda, rappels et assistance intelligente.

## Interaction de Robert

Le PC de Robert n'a pas de microphone. Jarvis est donc conçu en **clics + clavier en entrée, voix en sortie**.

Il n'existe pas de bouton « faire parler Jarvis ». La prise de parole est décidée automatiquement par le moteur vocal :

- une réponse à une demande directe de Robert est dite à voix haute ;
- une information critique est dite à voix haute ;
- une action nécessitant l'attention ou la confirmation de Robert est dite à voix haute ;
- une information importante peut être annoncée spontanément ;
- les informations de fond, les synchronisations et le bruit technique restent silencieux ;
- les annonces répétitives sont temporairement dédupliquées pour éviter de déranger Robert.

La synthèse vocale utilise les haut-parleurs de Windows et ne nécessite aucun microphone.

## Principes

- **Local-first** : les données personnelles restent locales autant que possible.
- **Validation humaine** : toute action sensible (envoyer, supprimer, modifier) doit être confirmée avant exécution.
- **Aucun secret dans GitHub** : clés API, mots de passe et jetons restent dans un fichier `.env` local ignoré par Git.
- **Architecture modulaire** : mails, fichiers, voix et agenda sont ajoutés comme services indépendants.
- **Traçabilité** : les actions importantes doivent pouvoir être journalisées et expliquées.
- **Voix non intrusive** : Jarvis parle lorsque cela apporte une vraie valeur, pas à chaque événement.

## V1

La première version contient :

1. un serveur local Jarvis ;
2. une page d'accueil personnalisée pour Robert ;
3. une politique de sécurité centralisée ;
4. un moteur de décision vocale ;
5. une sortie vocale Windows sans microphone ;
6. des connecteurs futurs pour mails, fichiers et agenda.

## Démarrage (Windows)

Prérequis : Python 3.12+.

Le plus simple est d'exécuter une fois :

```text
INSTALLER_JARVIS.bat
```

Puis, pour lancer Jarvis :

```text
LANCER_JARVIS.bat
```

Démarrage manuel :

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

Le but est d'augmenter progressivement l'autonomie sans sacrifier le contrôle de Robert.
