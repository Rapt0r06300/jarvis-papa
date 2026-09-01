# Autodiagnostic Jarvis Papa

Le diagnostic est **strictement en lecture seule**, à l'exception d'un petit fichier temporaire créé puis supprimé pour vérifier que le dossier runtime est réellement inscriptible.

## Lancer le diagnostic

Sous Windows :

```text
DIAGNOSTIC_JARVIS.bat
```

Ou depuis l'environnement Python :

```powershell
python -m jarvis_papa.diagnostics
python -m jarvis_papa.diagnostics --json
```

## Endpoints

- `GET /health` : liveness très rapide. Il répond si le processus web fonctionne.
- `GET /ready` : readiness. Il exécute les contrôles opérationnels et renvoie HTTP 503 uniquement en présence d'une erreur critique.
- `GET /api/diagnostics` : même rapport complet, toujours accessible en lecture seule.
- `GET /api/thunderbird/bridge/status` : état du dernier heartbeat du pont Thunderbird.
- `GET /api/voice/status` : disponibilité des moteurs vocaux et état du worker Qwen.

## Niveaux

- `ok` : contrôle réussi.
- `warning` : fonctionnalité dégradée, mais Jarvis peut continuer grâce à un secours ou sans cette fonction.
- `info` : information ou contrôle non applicable à l'environnement courant.
- `error` : problème critique qui empêche de considérer Jarvis comme prêt.

Le score 0–100 est un indicateur de synthèse. La propriété `ready` reste l'autorité pour la readiness.

## Contrôles réalisés

### Protection locale

Vérifie que Jarvis reste lié à `127.0.0.1`, `localhost` ou `::1`. Une exposition réseau accidentelle est classée comme erreur critique.

### Stockage runtime

Vérifie que Jarvis peut créer son dossier runtime, y écrire un fichier temporaire, puis le supprimer.

### Recherche de documents

Vérifie qu'au moins un dossier autorisé existe et indique le backend actif, par exemple Everything ou le fallback local.

### Navigateur

Vérifie la disponibilité de Playwright/Chromium. Une absence est un avertissement, car le reste de Jarvis continue de fonctionner.

### IA locale

Vérifie Ollama et le modèle configuré. Une panne est un avertissement, car Jarvis conserve son mode secrétaire déterministe de secours.

### Voix

Vérifie qu'au moins un moteur vocal est disponible. Le statut Qwen expose aussi le préchauffage, le PID, le port et la santé du worker quand il tourne.

### Thunderbird Windows

Vérifie séparément :

1. la présence de Thunderbird ;
2. le manifeste Native Messaging dans `%APPDATA%\Mozilla\NativeMessagingHosts` ;
3. le nom du host et l'ID d'extension autorisé ;
4. l'existence de l'exécutable `jarvis-native-host` référencé ;
5. la clé `HKCU\Software\Mozilla\NativeMessagingHosts\fr.jarvis_papa.host` ;
6. la cohérence entre registre et manifeste ;
7. le heartbeat réel du Native Host ;
8. les commandes Thunderbird en attente ou en échec.

Le heartbeat est important : un manifeste parfaitement installé ne prouve pas que Thunderbird communique réellement avec Jarvis. Quand l'extension est ouverte et connectée, le Native Host envoie périodiquement un signal de vie.

## Remédiation

Chaque avertissement ou erreur contient une phrase `remediation` directement exploitable. Le diagnostic doit privilégier des instructions simples plutôt que des codes d'erreur bruts.

Le diagnostic ne doit jamais afficher les clés API, jetons d'autorisation, mots de passe ou contenu complet des mails.
