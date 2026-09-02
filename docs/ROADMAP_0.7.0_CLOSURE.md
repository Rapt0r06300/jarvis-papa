# Jarvis Papa 0.7.0 — roadmap canonique de clôture

Date de référence : 2026-09-02  
Branche canonique et unique source de vérité : `main`

Ce fichier est la source de vérité pour la clôture 0.7.0. Aucun développement permanent ne doit rester sur une branche parallèle : `main` est l'unique branche de travail et de livraison.

## Règle de statut

- **DONE** : implémenté et déjà prouvé par une gate exécutable pertinente.
- **IMPLEMENTED / PROOF BLOCKED** : code et tests/gates ajoutés, mais la preuve automatique ne peut pas actuellement démarrer à cause d'une dépendance externe.
- **EXTERNAL BLOCKER** : nécessite une ressource ou une action hors du dépôt ; il est interdit de marquer DONE sans preuve réelle.

## Contrat binaire Windows

- L'application installée s'appelle **`Jarvis.exe`**.
- L'installeur final s'appelle **`Jarvis-Setup.exe`**.
- L'emplacement canonique du binaire dans le dépôt est **`installer/Jarvis-Setup.exe`**.
- `installer/*.exe` est suivi par **Git LFS**, car GitHub bloque les fichiers Git ordinaires supérieurs à 100 MiB et l'installeur Jarvis dépasse cette taille.
- Après un build Windows réussi de `main`, le workflow copie automatiquement `Jarvis-Setup.exe`, son SHA-256, le manifeste des livrables et le statut Authenticode dans `installer/`, puis les pousse sur `main`.
- La GitHub Release `v0.7.0` reste plus stricte : elle doit exposer le même installeur et refuse toute publication tant que la signature Authenticode n'est pas valide.

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
| Sauvegardes | IMPLEMENTED / PROOF BLOCKED | ZIP borné, données durables seulement, secrets DPAPI conservés chiffrés, états opérationnels de sécurité exclus de la restauration. |
| Restauration | IMPLEMENTED / PROOF BLOCKED | Double autorisation ; archive gérée par Jarvis ; application différée avant ouverture des bases. |
| Crash recovery | IMPLEMENTED / PROOF BLOCKED | Marqueur de session, détection d'arrêt non propre et sauvegarde de sécurité. |
| `Jarvis.exe` | IMPLEMENTED / PROOF BLOCKED | PyInstaller construit `dist\\Jarvis\\Jarvis.exe`; métadonnées Windows et Inno Setup sont alignés. |
| `Jarvis-Setup.exe` | IMPLEMENTED / PROOF BLOCKED | Inno Setup construit l'installeur qui installe `Jarvis.exe`. |
| Installeur présent dans le repo | IMPLEMENTED / PROOF BLOCKED | `.gitattributes` suit `installer/*.exe` par Git LFS ; le workflow Windows publie automatiquement `installer/Jarvis-Setup.exe` après un build `main` réussi. |
| Clean install / uninstall / reinstall E2E | IMPLEMENTED / PROOF BLOCKED | Vérifie `Jarvis.exe`, routes maintenance, autostart, cache rollback, hash installeur et persistance des données. |
| Suppression des branches parallèles | IMPLEMENTED / PROOF BLOCKED | `main` est déjà l'unique source de vérité ; le workflow Windows supprime la branche temporaire de clôture après un build réussi. |
| Signature Authenticode | EXTERNAL BLOCKER | Le workflow sait signer, mais aucun certificat de signature réel n'est actuellement prouvé/configuré. |
| Release GitHub 0.7.0 | EXTERNAL BLOCKER | Doit publier directement `Jarvis-Setup.exe` + SHA-256 depuis le même SHA après build signé réussi. |
| Validation PC réel de Robert | EXTERNAL BLOCKER | Exécuter `validate_final_pc.ps1` sur le PC final et obtenir les preuves Thunderbird, audio, fichiers, navigation et démarrage réel. |

## Incident GitHub Actions actuel

Après le merge sur `main`, les workflows `CI` et `Windows EXE` ont été relancés une nouvelle fois. Ubuntu et Windows échouent toujours avant la première étape : `steps = null`, aucun checkout, aucun lint, aucun test et aucun build ne démarrent.

Le statut public GitHub Actions est actuellement annoncé opérationnel. Le blocage est donc vraisemblablement spécifique au compte ou au repository (provisioning, quota, facturation ou politique Actions), mais aucune preuve accessible ne permet d'attribuer une cause unique.

Ce symptôme n'est **pas** une preuve d'échec de Ruff, pytest, PyInstaller ou Inno Setup : aucun de ces outils n'est exécuté.

### Gate de reprise

1. rétablir la capacité du compte/repository à démarrer un runner GitHub Actions ;
2. obtenir `ruff check .` et `pytest -q` verts ;
3. obtenir le workflow `Windows EXE` vert sur le commit exact de `main` ;
4. vérifier que le workflow matérialise `Jarvis.exe`, construit `Jarvis-Setup.exe` et pousse `installer/Jarvis-Setup.exe` via Git LFS sur `main` ;
5. vérifier que la branche temporaire de clôture a été supprimée ;
6. configurer une identité de signature Authenticode réelle et obtenir `SIGNED` pour `Jarvis.exe`, les exécutables auxiliaires et `Jarvis-Setup.exe` ;
7. refaire le workflow Windows et vérifier le clean install/uninstall/reinstall ;
8. exécuter `validate_final_pc.ps1` sur le PC final de Robert ;
9. déclencher `Release Jarvis Papa` et vérifier `v0.7.0` avec `Jarvis-Setup.exe`.

## Contrat de clôture définitive

La roadmap 0.7.0 est **CLOSED** uniquement lorsque les preuves suivantes existent simultanément :

- seule la branche `main` subsiste ;
- `installer/Jarvis-Setup.exe` existe dans le repo via Git LFS et installe réellement `Jarvis.exe` ;
- CI Ubuntu + Windows verte sur le SHA publié ;
- Windows EXE + clean E2E verts ;
- Authenticode `Valid` pour la Release officielle ;
- validation du PC réel de Robert sans FAIL critique ;
- GitHub Release `v0.7.0` publiée depuis exactement le même SHA avec `Jarvis-Setup.exe`.

Tant qu'une de ces preuves manque, tout le code réalisable est en place mais la clôture de livraison reste bloquée par une dépendance externe vérifiable.
