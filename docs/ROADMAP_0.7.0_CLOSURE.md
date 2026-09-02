# Jarvis Papa 0.7.0 — roadmap canonique de clôture

Date de référence : 2026-09-02  
Branche canonique : `main`

Ce fichier est la source de vérité pour la clôture 0.7.0. Aucun développement permanent ne doit rester sur une branche parallèle : `main` est l'unique branche de travail et de livraison.

## Règle de statut

- **DONE** : implémenté et déjà prouvé par une gate exécutable pertinente.
- **IMPLEMENTED / PROOF BLOCKED** : code et tests/gates ajoutés, mais la preuve automatique ne peut pas actuellement démarrer à cause d'une dépendance externe.
- **EXTERNAL BLOCKER** : nécessite une ressource ou une action hors du dépôt ; il est interdit de marquer DONE sans preuve réelle.

## Contrat binaire Windows

- L'application installée s'appelle **`Jarvis.exe`**.
- L'installeur final s'appelle **`Jarvis-Setup.exe`**.
- Le gros installeur n'est pas versionné dans les sources Git.
- La **GitHub Release `v0.7.0`** doit exposer directement `Jarvis-Setup.exe` comme binaire de téléchargement, accompagné de son SHA-256 et du statut de signature.
- Le workflow de release ne publie qu'un installeur provenant d'un build Windows réussi du même SHA.

## État des chantiers de clôture

| Chantier | État | Preuve / contrat de sortie |
| --- | --- | --- |
| Policy Kernel et doubles autorisations exactes | DONE | Chaque grant consommé repasse par le Policy Kernel. |
| Mémoire protégée / DPAPI / mémoire sémantique | DONE | Présent dans l'architecture livrée. |
| Onboarding natif et UI Windows canonique | DONE | Interface native PySide6 canonique. |
| Thunderbird + Native Messaging | DONE pour l'implémentation | Validation finale du compte réel reste dans la gate PC physique. |
| Everything/fallback + recherche documentaire | DONE | Recherche sûre déjà intégrée. |
| UI Automation Windows + Playwright | DONE | Automatisation sémantique et refus des clics ambigus. |
| Updater fail-closed | IMPLEMENTED / PROOF BLOCKED | HTTPS, SHA-256, Authenticode `Valid` sous Windows, downgrade automatique refusé. |
| Rollback de version | IMPLEMENTED / PROOF BLOCKED | Installeur courant/précédent conservé localement ; rollback refuse tout installeur non signé. |
| Autostart Windows | IMPLEMENTED / PROOF BLOCKED | HKCU `...\\Run`, sans élévation admin ; E2E vérifie création et suppression. |
| Notifications natives | IMPLEMENTED / PROOF BLOCKED | QSystemTrayIcon relié au bus proactif ; interruptions limitées aux priorités importantes/urgentes. |
| Sauvegardes | IMPLEMENTED / PROOF BLOCKED | ZIP borné, données durables seulement, secrets DPAPI conservés chiffrés. |
| Restauration | IMPLEMENTED / PROOF BLOCKED | Double autorisation ; archive gérée par Jarvis ; application différée avant ouverture des bases. |
| Crash recovery | IMPLEMENTED / PROOF BLOCKED | Marqueur de session, détection d'arrêt non propre et sauvegarde de sécurité. |
| `Jarvis.exe` | IMPLEMENTED / PROOF BLOCKED | PyInstaller construit `dist\\Jarvis\\Jarvis.exe`; métadonnées Windows alignées. |
| `Jarvis-Setup.exe` | IMPLEMENTED / PROOF BLOCKED | Inno Setup construit l'installeur qui installe `Jarvis.exe`. |
| Clean install / uninstall / reinstall E2E | IMPLEMENTED / PROOF BLOCKED | Vérifie `Jarvis.exe`, routes maintenance, autostart, cache rollback, hash installeur et persistance des données. |
| Signature Authenticode | EXTERNAL BLOCKER | Le workflow sait signer, mais aucun certificat de signature réel n'est actuellement prouvé/configuré. |
| Release GitHub 0.7.0 | EXTERNAL BLOCKER | Doit publier directement `Jarvis-Setup.exe` + SHA-256 depuis le même SHA après build signé réussi. |
| Validation PC réel de Robert | EXTERNAL BLOCKER | Exécuter `validate_final_pc.ps1` sur le PC final et obtenir les preuves Thunderbird, audio, fichiers, navigation et démarrage réel. |

## Incident GitHub Actions actuel

Les derniers runs observés échouent avant la première étape : aucun checkout, aucune installation, aucun lint et aucun test ne sont exécutés. Ce symptôme est un blocage d'exécution GitHub Actions jusqu'à preuve contraire, pas une preuve d'échec du code.

### Gate de reprise

1. rétablir l'exécution des runners GitHub Actions ;
2. obtenir `ruff check .` et `pytest -q` verts ;
3. obtenir le workflow `Windows EXE` vert sur le commit exact de `main` ;
4. configurer une identité de signature Authenticode réelle et obtenir `SIGNED` pour `Jarvis.exe`, les exécutables auxiliaires et `Jarvis-Setup.exe` ;
5. refaire le workflow Windows et vérifier le clean install/uninstall/reinstall ;
6. exécuter `validate_final_pc.ps1` sur le PC final de Robert ;
7. déclencher `Release Jarvis Papa` et vérifier `v0.7.0` avec `Jarvis-Setup.exe` téléchargeable directement depuis la Release.

## Contrat de clôture définitive

La roadmap 0.7.0 est **CLOSED** uniquement lorsque les quatre preuves suivantes existent simultanément :

- CI Ubuntu + Windows verte sur le SHA publié ;
- Windows EXE + clean E2E verts avec Authenticode `Valid` ;
- validation du PC réel de Robert sans FAIL critique ;
- GitHub Release `v0.7.0` publiée depuis exactement le même SHA avec `Jarvis-Setup.exe`.

Tant qu'une de ces preuves manque, le projet peut être fonctionnellement implémenté mais la release n'est pas déclarée terminée.
