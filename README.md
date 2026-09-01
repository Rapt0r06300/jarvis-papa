# Jarvis Papa

Assistant personnel **local-first** pour Windows, conçu pour rendre les tâches quotidiennes très simples : mails Thunderbird, fichiers, navigation, contrôle Windows, mémoire et assistance intelligente.

## Interface

Jarvis est pensé pour fonctionner **sans microphone** : Robert utilise surtout de gros boutons et quelques choix simples, tandis que Jarvis répond à voix haute quand c'est utile.

L'écran principal reste volontairement léger :

- un visage d'assistante féminine animé lorsqu'elle parle ;
- au maximum quelques tâches importantes à la fois ;
- un résumé très court de ce qu'il faut comprendre ;
- de gros boutons simples ;
- les newsletters non importantes restent discrètes ;
- aucune interface technique n'est imposée à Robert.

## Voix intelligente

Jarvis ne parle pas à chaque événement. Il parle notamment pour :

- résumer rapidement chaque mail important ;
- répondre à une demande de Robert ;
- signaler une information urgente ou une action nécessaire ;
- expliquer précisément une confirmation.

Le moteur vocal essaie automatiquement :

1. **ElevenLabs** pour la qualité maximale ;
2. **Azure Speech** comme solution cloud fiable ;
3. **Qwen3-TTS** pour une voix locale et hors ligne ;
4. une voix Windows en dernier recours.

Qwen3-TTS fonctionne désormais dans un **worker local persistant** : le modèle lourd est chargé une fois puis réutilisé pour les phrases suivantes. Jarvis peut le préchauffer au démarrage et choisit automatiquement un autre port local si un ancien worker a laissé le port prévu occupé après un crash.

Les contenus sensibles utilisent par défaut uniquement `qwen3,windows`. Ils ne sont donc pas envoyés vers un fournisseur vocal cloud sans modification explicite de la configuration locale.

La cible est une voix de jeune femme française adulte, douce, chaleureuse, naturelle, très articulée et jamais volontairement robotique. Voir `docs/VOICE.md`.

## Mails Thunderbird

Le pont Thunderbird permet notamment de :

- détecter les nouveaux mails ;
- identifier les messages importants ;
- produire un résumé court à lire et à prononcer ;
- garder les newsletters non importantes hors de la liste principale ;
- ouvrir le mail d'origine ;
- préparer une réponse ;
- rechercher un document puis préparer un brouillon avec pièce jointe.

Le pont envoie maintenant un **heartbeat** à Jarvis. L'autodiagnostic peut donc distinguer « le pont semble installé » de « Thunderbird et le Native Messaging communiquent réellement maintenant ».

Un brouillon préparé n'est **pas** un mail envoyé.

## Fichiers, Windows et navigateur

Jarvis possède des outils pour :

- rechercher rapidement des fichiers, avec Everything si disponible ;
- ouvrir un fichier ou un dossier ;
- lancer des applications autorisées ;
- inspecter les fenêtres et contrôles Windows avec UI Automation ;
- lire des pages et effectuer certaines tâches web avec Playwright ;
- mémoriser localement des préférences et habitudes utiles.

## Sécurité : deux confirmations

La règle est simple :

- **lire, rechercher, résumer, inspecter ou ouvrir** ne nécessite pas deux autorisations ;
- **modifier, envoyer, supprimer, déplacer, télécharger ou effectuer une autre action sensible** nécessite **deux confirmations explicites successives**.

Les autorisations sensibles sont vérifiées côté serveur, liées à l'action précise, expirent et ne peuvent être utilisées qu'une seule fois. Envoyer artificiellement `confirmations=2` à l'API ne contourne pas la protection.

## Autodiagnostic

Jarvis dispose d'un diagnostic en lecture seule qui contrôle notamment :

- la protection localhost ;
- l'accès au stockage local ;
- les dossiers de recherche de documents ;
- Playwright/Chromium ;
- Ollama et son mode de secours ;
- les moteurs vocaux et l'état du worker Qwen ;
- Thunderbird sous Windows ;
- le manifeste Native Messaging et sa clé de registre ;
- le heartbeat réel Thunderbird ↔ Jarvis ;
- les commandes Thunderbird en attente ou en échec.

Sous Windows, double-cliquer sur :

```text
DIAGNOSTIC_JARVIS.bat
```

L'API expose aussi :

```text
GET /health            -> processus vivant, réponse très rapide
GET /ready             -> diagnostic de disponibilité
GET /api/diagnostics   -> rapport complet
```

`INSTALLER_JARVIS.bat` lance automatiquement un premier diagnostic. `LANCER_JARVIS.bat` attend maintenant que `/health` réponde avant d'ouvrir l'interface dans le navigateur.

## Confidentialité

- Les données restent locales autant que possible.
- Les clés API, mots de passe et jetons ne doivent jamais être ajoutés à GitHub.
- Les clés ElevenLabs/Azure éventuelles sont placées uniquement dans le fichier `.env` local, déjà ignoré par Git.
- Qwen3-TTS et Ollama permettent des fonctions locales sans clé cloud.

## Installation Windows

Prérequis : Python 3.12+.

Installation principale :

```text
INSTALLER_JARVIS.bat
```

Voix locale Qwen3-TTS facultative :

```text
INSTALLER_VOIX_LOCALE.bat
```

Puis lancer :

```text
LANCER_JARVIS.bat
```

L'interface est disponible localement sur `http://127.0.0.1:8765`.

## Tests

```powershell
pytest
```

La CI GitHub compile, lint et teste Jarvis sur **Ubuntu et Windows** à chaque changement sur `main`.
