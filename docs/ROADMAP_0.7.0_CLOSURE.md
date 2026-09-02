# Jarvis Papa 0.7.0 — roadmap canonique de clôture

Date de référence : 2026-09-02  
Branche canonique et unique source de vérité : `main`

Ce fichier est la source de vérité pour la clôture 0.7.0. Aucun développement permanent ne doit rester sur une branche parallèle : `main` est l'unique branche de travail et de livraison.

## Règle de statut

- **DONE** : implémenté et déjà prouvé par une gate exécutable pertinente.
- **IMPLEMENTED / EXACT-SHA REVALIDATION** : implémenté et déjà exercé, mais tout changement de source, packaging ou workflow impose une nouvelle preuve sur le SHA exact à publier.
- **EXTERNAL BLOCKER** : nécessite une ressource ou une action hors du dépôt ; il est interdit de marquer DONE sans preuve réelle.

## Contrat binaire Windows

- L'application installée s'appelle **`Jarvis.exe`**.
- L'installeur final s'appelle **`Jarvis-Setup.exe`**.
- L'emplacement canonique du binaire dans le dépôt est **`installer/Jarvis-Setup.exe`**.
- La racine contient **`.gitattributes`** avec un contrat Git LFS explicite pour `installer/*.exe`.
- Le workflow de publication refuse le push si `installer/Jarvis-Setup.exe` n'est pas couvert par l'attribut `filter=lfs` ou si l'objet indexé n'est pas un pointeur Git LFS.
- Après un build Windows réussi du SHA courant de `main`, le workflow copie automatiquement `Jarvis-Setup.exe`, son SHA-256, le manifeste des livrables et le statut Authenticode dans `installer/`, puis les pousse sur `main`.
- La publication refuse un artifact périmé si `main` a bougé depuis le build Windows.
- La GitHub Release `v0.7.0` reste plus stricte : elle doit exposer le même installeur et refuse toute publication tant que la signature Authenticode n'est pas valide.

## État des chantiers de clôture

| Chantier | État | Preuve / contrat de sortie |
| --- | --- | --- |
| Policy Kernel et doubles autorisations exactes | DONE | Chaque grant consommé repasse par le Policy Kernel. |
| Mémoire protégée / mémoire sémantique | DONE | Provenance, confiance, expiration, conflits, déduplication, filtrage secrets/cartes/tokens et prompt-injection, rappel sémantique borné. |
| Secrets Windows / stockage protégé | DONE | Le stockage sensible reste séparé de la mémoire durable et les tests de sécurité couvrent le contrat. |
| Onboarding natif et UI Windows canonique | DONE | Interface native PySide6 canonique. |
| Thunderbird + Native Messaging | DONE pour l'implémentation | Validation finale du compte réel reste dans la gate PC physique. |
| Everything/fallback + recherche documentaire | DONE | Recherche sûre déjà intégrée. |
| UI Automation Windows + Playwright | DONE | Automatisation sémantique et refus des clics ambigus. |
| Updater fail-closed | IMPLEMENTED / EXACT-SHA REVALIDATION | HTTPS, SHA-256, Authenticode `Valid` sous Windows, downgrade automatique refusé. |
| Rollback de version | IMPLEMENTED / EXACT-SHA REVALIDATION | Installeur courant/précédent conservé localement ; rollback refuse tout installeur non signé. |
| Autostart Windows | IMPLEMENTED / EXACT-SHA REVALIDATION | HKCU `...\\Run`, sans élévation admin ; E2E vérifie création et suppression. |
| Notifications natives | IMPLEMENTED / EXACT-SHA REVALIDATION | QSystemTrayIcon relié au bus proactif ; interruptions limitées aux priorités importantes/urgentes. |
| Sauvegardes | IMPLEMENTED / EXACT-SHA REVALIDATION | ZIP borné, données durables seulement, secrets protégés conservés chiffrés, états opérationnels de sécurité exclus de la restauration. |
| Restauration | IMPLEMENTED / EXACT-SHA REVALIDATION | Double autorisation ; archive gérée par Jarvis ; application différée avant ouverture des bases. |
| Crash recovery | IMPLEMENTED / EXACT-SHA REVALIDATION | Marqueur de session, détection d'arrêt non propre et sauvegarde de sécurité. |
| `Jarvis.exe` | IMPLEMENTED / EXACT-SHA REVALIDATION | PyInstaller construit `dist\\Jarvis\\Jarvis.exe`; métadonnées Windows et Inno Setup sont alignés. |
| `Jarvis-Setup.exe` | IMPLEMENTED / EXACT-SHA REVALIDATION | Inno Setup construit l'installeur qui installe `Jarvis.exe`. |
| Git LFS pour l'installeur | DONE | `.gitattributes` existe et le publisher refuse un EXE indexé autrement qu'en pointeur LFS. |
| Installeur présent dans le repo | IMPLEMENTED / EXACT-SHA REVALIDATION | Publication automatique uniquement après succès du Windows EXE sur le SHA courant de `main`; hash et provenance conservés. |
| Clean install / uninstall / reinstall E2E | IMPLEMENTED / EXACT-SHA REVALIDATION | Vérifie `Jarvis.exe`, routes maintenance, autostart, cache rollback, hash installeur et persistance des données. |
| Suppression des branches parallèles | DONE | `main` est la seule branche du dépôt ; aucun workflow n'essaie désormais de gérer une branche de clôture obsolète. |
| Provenance GitHub de l'installeur | IMPLEMENTED / EXACT-SHA REVALIDATION | Le build Windows génère une attestation GitHub pour `Jarvis-Setup.exe` avant publication de l'artifact. |
| Signature Authenticode | EXTERNAL BLOCKER | Le workflow sait signer, mais aucun certificat de signature réel n'est actuellement prouvé/configuré. |
| Release GitHub 0.7.0 | EXTERNAL BLOCKER | Elle exige le même artifact, le SHA enregistré et un statut Authenticode `SIGNED`. |
| Validation PC réel de Robert | EXTERNAL BLOCKER | Exécuter `validate_final_pc.ps1` sur le PC final et obtenir les preuves Thunderbird, audio, fichiers, navigation et démarrage réel. |

## Incident GitHub Actions historique — résolu

Un ancien état avait montré des runs sans étapes démarrées. Ce diagnostic n'est plus actuel : les runners GitHub Actions démarrent normalement sur Ubuntu et Windows.

Un build Windows ultérieur de `main` a exécuté avec succès les gates produit substantielles : lint, **110 tests**, génération de l'icône, construction de `Jarvis.exe`, du Native Host et de `JarvisDiagnostic.exe`, smoke tests, Inno Setup, `Jarvis-Setup.exe`, clean install/uninstall/reinstall, vérification des livrables et upload de l'artifact.

Ce run avait été marqué rouge uniquement à cause d'une dernière étape de housekeeping qui tentait de supprimer une branche temporaire déjà absente. Cette étape a été retirée. Elle ne faisait pas partie du produit ni de ses gates fonctionnelles.

Règle permanente : un succès historique ne remplace jamais la preuve sur le SHA à publier. Toute modification de code, packaging ou workflow impose le passage du build Windows et de la CI sur le SHA exact courant.

## Durcissement de supply chain

Les workflows utilisent les générations actuelles des actions officielles GitHub compatibles Node 24. Le build Windows applique un principe de moindre privilège, calcule les SHA-256, conserve un manifeste, produit une attestation de provenance GitHub du setup et publie l'artifact uniquement après les gates E2E.

Le publisher :

1. refuse tout build qui ne correspond plus au `main` courant ;
2. télécharge l'artifact du run exact ;
3. recalcule le SHA-256 avant publication ;
4. vérifie le contrat Git LFS ;
5. refuse un `.exe` indexé comme blob Git ordinaire ;
6. enregistre le SHA source et l'identifiant du run Windows avec l'installeur.

La Release :

1. refuse tout changement hors `installer/**` depuis le SHA construit ;
2. vérifie le run Windows enregistré ;
3. vérifie Git LFS et le SHA-256 ;
4. recroise le binaire du repo avec l'artifact du run exact ;
5. refuse toute Release officielle si Authenticode n'est pas `SIGNED`.

## Gate de clôture 0.7.0

1. obtenir `CI` verte sur Ubuntu et Windows pour le SHA source à publier ;
2. obtenir `Windows EXE` vert sur ce même SHA ;
3. vérifier la construction et le smoke de `Jarvis.exe` et `JarvisDiagnostic.exe` ;
4. vérifier le clean install → uninstall → reinstall de `Jarvis-Setup.exe` ;
5. vérifier l'attestation de provenance et les SHA-256 ;
6. vérifier que le publisher matérialise `installer/Jarvis-Setup.exe` via Git LFS avec `build-source-sha.txt` et `build-run-id.txt` ;
7. configurer une identité de signature Authenticode réelle et obtenir `SIGNED` pour `Jarvis.exe`, les exécutables auxiliaires et `Jarvis-Setup.exe` ;
8. refaire le build Windows signé sur le SHA de Release ;
9. exécuter `validate_final_pc.ps1` sur le PC final de Robert ;
10. déclencher `Release Jarvis Papa` et vérifier `v0.7.0` avec le même `Jarvis-Setup.exe`.

## Contrat de clôture définitive

La roadmap 0.7.0 est **CLOSED** uniquement lorsque les preuves suivantes existent simultanément :

- seule la branche `main` subsiste ;
- `installer/Jarvis-Setup.exe` existe dans le repo via Git LFS et installe réellement `Jarvis.exe` ;
- CI Ubuntu + Windows verte sur le SHA publié ;
- Windows EXE + clean E2E verts sur ce SHA ;
- SHA-256 et provenance GitHub vérifiables ;
- Authenticode `Valid` pour la Release officielle ;
- validation du PC réel de Robert sans FAIL critique ;
- GitHub Release `v0.7.0` publiée depuis exactement l'état source construit avec `Jarvis-Setup.exe`.

Tant qu'une de ces preuves manque, le code réalisable peut être en place mais la clôture de livraison reste incomplète. Les dépendances réellement externes ne doivent jamais être maquillées en DONE.
