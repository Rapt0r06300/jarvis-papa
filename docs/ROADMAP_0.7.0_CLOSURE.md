# Jarvis Papa 0.7.0 — roadmap canonique de clôture

Date de référence : 2026-09-02  
Branche de clôture : `closure/grand-run-20260902`  
Base : `main@3a4e5bca60d9cc5062e727d13b6a7b11b22326b0`

Ce fichier est la source de vérité pour la clôture 0.7.0. L'ancien document d'architecture reste utile comme conception historique, mais ses cases ne doivent plus être utilisées pour déduire l'état réel du produit.

## Règle de statut

- **DONE** : implémenté et déjà prouvé par une gate exécutable pertinente.
- **IMPLEMENTED / PROOF BLOCKED** : code et tests/gates ajoutés, mais la preuve automatique ne peut pas actuellement démarrer à cause d'une dépendance externe.
- **EXTERNAL BLOCKER** : nécessite une ressource ou une action hors du dépôt ; il est interdit de marquer DONE sans preuve réelle.

## État des chantiers de clôture

| Chantier | État | Preuve / contrat de sortie |
| --- | --- | --- |
| Policy Kernel et doubles autorisations exactes | DONE | Présent sur `main` avant ce run ; chaque grant consommé repasse par le Policy Kernel. |
| Mémoire protégée / DPAPI / mémoire sémantique | DONE | Présent sur `main` avant ce run. |
| Onboarding natif et UI Windows canonique | DONE | Présent sur `main` avant ce run. |
| Thunderbird + Native Messaging | DONE pour l'implémentation | Déjà présent ; validation finale du compte réel reste dans la gate PC physique. |
| Everything/fallback + recherche documentaire | DONE | Présent sur `main` avant ce run. |
| UI Automation Windows + Playwright | DONE | Présent sur `main` avant ce run. |
| Updater fail-closed | IMPLEMENTED / PROOF BLOCKED | HTTPS obligatoire, SHA-256 obligatoire, Authenticode `Valid` obligatoire sous Windows, downgrade automatique refusé. CI actuellement incapable de démarrer ses steps. |
| Rollback de version | IMPLEMENTED / PROOF BLOCKED | L'installeur courant est conservé localement ; la version précédente est conservée avant update ; rollback refuse tout installeur non signé. |
| Autostart Windows | IMPLEMENTED / PROOF BLOCKED | HKCU `...\Run`, sans élévation admin ; installateur et interface utilisent le même contrat. Le Windows E2E vérifie création et suppression. |
| Notifications natives | IMPLEMENTED / PROOF BLOCKED | QSystemTrayIcon relié au bus proactif ; seules les priorités `important` et `urgent` interrompent l'utilisateur. AppUserModelID `JarvisPapa.Desktop` aligné entre processus et raccourcis. |
| Sauvegardes | IMPLEMENTED / PROOF BLOCKED | ZIP borné, données durables uniquement, chemins de restauration allowlistés, DPAPI conservé chiffré. |
| Restauration | IMPLEMENTED / PROOF BLOCKED | Double autorisation exacte ; restauration uniquement depuis le dépôt Jarvis ; application différée avant ouverture des bases au prochain lancement. |
| Crash recovery | IMPLEMENTED / PROOF BLOCKED | Marqueur de session ; détection d'arrêt non propre ; sauvegarde de sécurité avant reprise ; nettoyage au shutdown normal. |
| Clean install / uninstall / reinstall E2E automatisé | IMPLEMENTED / PROOF BLOCKED | Le workflow 0.7.0 vérifie app, routes maintenance, autostart, cache rollback, hash installeur et persistance des données. GitHub Actions ne lance actuellement aucune step. |
| Signature Authenticode | EXTERNAL BLOCKER | Le workflow sait signer, mais aucun certificat de signature réel n'est configuré. Une release non signée est interdite par la gate 0.7.0. |
| Release GitHub 0.7.0 | EXTERNAL BLOCKER | Nouveau workflow de release : exige un build Windows réussi du même SHA, `signing-status.txt = SIGNED` et SHA-256 exact avant publication. Aucune release ne doit être créée avant ces preuves. |
| Validation PC réel de Robert | EXTERNAL BLOCKER | Exécuter `validate_final_pc.ps1` sur le PC final et obtenir les preuves Thunderbird, audio, fichiers, navigation et démarrage réel. |

## Incident GitHub Actions actuel

Les runs `CI` et `Windows EXE` du HEAD `main` ont été relancés le 2026-09-02. Les jobs échouent de nouveau avant la première étape : aucun checkout, aucune installation, aucun lint et aucun test ne sont exécutés. Ce symptôme doit être traité comme un blocage de provisioning/compte GitHub Actions jusqu'à preuve contraire, pas comme un échec de code.

### Gate de reprise

1. rétablir l'exécution des runners GitHub Actions ;
2. obtenir `python -m compileall -q src tests`, `ruff check .` et `pytest -q` verts sur Ubuntu et Windows ;
3. obtenir le workflow `Windows EXE` 0.7.0 vert sur le commit exact de `main` ;
4. configurer une identité de signature Authenticode réelle et obtenir `SIGNED` pour les EXE et l'installeur ;
5. refaire le workflow Windows et vérifier son E2E install/uninstall/reinstall ;
6. exécuter `validate_final_pc.ps1` sur le PC final de Robert ;
7. seulement alors déclencher `Release Jarvis Papa` et vérifier l'existence de `v0.7.0` avec son installeur et son SHA-256.

## Contrat de clôture définitive

La roadmap 0.7.0 est **CLOSED** uniquement lorsque les quatre preuves suivantes existent simultanément :

- CI Ubuntu + Windows verte sur le SHA publié ;
- Windows EXE + clean E2E verts avec Authenticode `Valid` ;
- validation du PC réel de Robert sans FAIL critique ;
- GitHub Release `v0.7.0` publiée depuis exactement le même SHA.

Tant qu'une de ces preuves manque, le projet peut être fonctionnellement implémenté mais la release n'est pas déclarée terminée.
