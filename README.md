# Jarvis Papa

Jarvis Papa est un assistant personnel **local-first pour Windows** : mails Thunderbird, documents, applications, navigation, mémoire, voix et aide intelligente.

La transformation produit vers l'assistant proactif centré situations de Robert est pilotée par la roadmap canonique : [`docs/ROADMAP_ROBERT_AUTOPILOT.md`](docs/ROADMAP_ROBERT_AUTOPILOT.md).

## Une vraie application Windows

Depuis la version **0.6.0**, l'interface principale n'est plus une page web. Jarvis possède une **fenêtre Windows native PySide6** et se lance avec `Jarvis.exe`.

Robert n'a donc pas besoin d'ouvrir Chrome, Edge ou un autre navigateur pour utiliser Jarvis. Un petit service HTTP reste uniquement actif sur `127.0.0.1` en arrière-plan pour le pont Thunderbird et les composants internes ; il n'est pas l'interface utilisateur.

La fenêtre native garde l'expérience volontairement simple :

- visage féminin animé quand Jarvis parle ;
- `Bonjour Robert` et état de Jarvis clairement visibles ;
- bouton **Fais-moi le point** ;
- boutons **Ouvrir mes mails** et **Ouvrir mes documents** ;
- au maximum trois tâches importantes visibles ;
- résumés et recommandations très courts ;
- sélection simple d'un document trouvé ;
- deux fenêtres de confirmation successives avant toute modification sensible ;
- newsletters discrètes.

## Installation normale

Le livrable Windows principal est :

```text
Jarvis-Setup.exe
```

Le dépôt publie également l'installeur canonique via Git LFS dans :

```text
installer\Jarvis-Setup.exe
```

Il installe l'application dans le profil Windows, crée :

- un raccourci **Jarvis** sur le Bureau ;
- un raccourci **Jarvis** dans le menu Démarrer ;
- `JarvisDiagnostic.exe` ;
- `JarvisNativeHost.exe` pour Thunderbird ;
- le manifeste Native Messaging et sa clé de registre utilisateur ;
- l'extension Thunderbird `.xpi` dans le dossier d'installation.

Après installation, Robert lance simplement :

```text
Jarvis.exe
```

Aucune installation de Python n'est nécessaire pour utiliser le programme empaqueté : PyInstaller embarque l'environnement nécessaire dans l'application Windows.

Les données modifiables et la configuration restent séparées du programme dans :

```text
%LOCALAPPDATA%\JarvisPapa
```

Elles ne sont pas supprimées automatiquement à la désinstallation, afin de ne pas perdre la mémoire/configuration de Jarvis par accident.

## Fabrication des exécutables

Le workflow GitHub Actions `Windows EXE` construit sous Windows :

1. `Jarvis.exe` en mode **onedir/windowed** pour un démarrage fiable et sans console ;
2. `JarvisNativeHost.exe` pour le pont Thunderbird ;
3. `JarvisDiagnostic.exe` ;
4. l'extension Thunderbird `.xpi` ;
5. `Jarvis-Setup.exe` avec Inno Setup.

Le workflow lance aussi réellement le `Jarvis.exe` empaqueté en mode graphique hors écran et vérifie que son service local répond avant de publier l'artefact. PyInstaller doit construire un exécutable Windows sur Windows, ce que fait précisément ce workflow.

## Voix intelligente

Jarvis parle automatiquement quand c'est utile. L'ordre de secours est :

1. **ElevenLabs** — qualité maximale ;
2. **Azure Speech** — excellente qualité/fiabilité ;
3. **Qwen3-TTS** — voix locale si son environnement local est installé ;
4. **voix Windows** — dernier recours.

Qwen3-TTS utilise un worker local persistant : le modèle lourd reste chargé entre les phrases. Les contenus sensibles utilisent par défaut uniquement la chaîne locale `qwen3,windows`, sauf changement explicite de configuration.

La cible est une voix de jeune femme française adulte, douce, chaleureuse, naturelle, très articulée et jamais volontairement robotique. Voir `docs/VOICE.md`.

## Thunderbird

Le pont Thunderbird peut :

- détecter les nouveaux mails ;
- identifier les messages importants ;
- produire un résumé court ;
- préparer une réponse ;
- chercher un document et préparer un brouillon avec pièce jointe ;
- ranger les newsletters après autorisation ;
- confirmer à Jarvis qu'une commande a réellement réussi ou échoué.

Le Native Host envoie un **heartbeat** à Jarvis : l'autodiagnostic distingue donc une installation théorique d'une connexion Thunderbird réellement vivante.

Un brouillon préparé n'est **jamais** considéré comme un mail envoyé.

## Sécurité : deux confirmations réelles

- Lire, rechercher, résumer, inspecter ou ouvrir : pas de double autorisation.
- Modifier, envoyer, supprimer, déplacer, télécharger ou toute autre action sensible : **deux confirmations explicites successives**.

Les autorisations sont imposées côté serveur, liées à l'action exacte, expirent et sont à usage unique. Un simple compteur envoyé par l'interface ne peut pas contourner cette règle.

## Autodiagnostic

`JarvisDiagnostic.exe` vérifie notamment : stockage, localhost, fichiers, navigateur Playwright, Ollama, moteurs vocaux, worker Qwen, Windows, Thunderbird, Native Messaging, heartbeat et commandes Thunderbird en échec.

Le service interne expose aussi :

```text
GET /health
GET /ready
GET /api/diagnostics
```

## Confidentialité

- Données locales autant que possible.
- Aucune clé API ou mot de passe dans GitHub.
- Dans l'application Windows empaquetée, les secrets locaux sont stockés via le **secret store DPAPI**. Le build final ne repose pas sur un `.env` utilisateur en clair ; les anciens secrets `.env` peuvent être migrés vers le stockage protégé puis le fichier legacy supprimé.
- Un `.env` peut encore être utilisé dans un **contexte de développement depuis les sources**, mais ce n'est pas le contrat de stockage du produit Windows final.
- Le service interne écoute uniquement sur localhost par défaut et ses routes protégées utilisent un bearer token local stocké via DPAPI.

## Mode développeur

Les anciens scripts `.bat` restent disponibles pour développer ou dépanner depuis les sources. `LANCER_JARVIS.bat` lance désormais lui aussi **la fenêtre native**, sans ouvrir de navigateur.

```text
INSTALLER_JARVIS.bat
LANCER_JARVIS.bat
DIAGNOSTIC_JARVIS.bat
```

## Tests

```powershell
pytest
```

La CI compile, lint et teste Jarvis sur **Ubuntu et Windows**. Le workflow séparé **Windows EXE** valide en plus les exécutables et l'installateur réels.
