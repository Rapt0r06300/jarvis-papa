# Architecture cible — Jarvis pour Robert

## Objectif produit

Construire un assistant Windows personnel réellement utile à Robert avec les contraintes suivantes :

- aucun microphone requis ;
- presque aucun texte à taper ;
- Jarvis parle automatiquement uniquement lorsque le contexte le justifie ;
- Thunderbird reste utilisable normalement ;
- prise en charge d'une adresse `@numericable.fr` ;
- recherche instantanée de fichiers ;
- contrôle de Windows, des applications et du navigateur ;
- actions simples réalisables en un ou deux clics ;
- aucune action sensible silencieuse ;
- architecture local-first, auditable et réversible autant que possible.

Le produit ne doit pas être un simple chatbot. Il doit être un **orchestrateur personnel en arrière-plan** qui observe des événements autorisés, propose ou exécute les bonnes actions, et ne sollicite Robert que lorsque sa décision est utile.

---

## 1. Modèle d'interaction : « presque zéro clavier »

### 1.1 Entrée utilisateur

L'absence de microphone ne doit pas conduire à une interface centrée sur une zone de texte.

Entrées prioritaires :

1. **boutons contextuels générés par Jarvis** ;
2. **notifications Windows actionnables** ;
3. **cartes Oui / Non / Plus tard / Ouvrir / Répondre / Classer / Chercher le document** ;
4. **réponses proposées complètes** pour les mails, sélectionnables en un clic ;
5. **sélection de fichiers proposés** plutôt que saisie d'un nom de fichier ;
6. clavier seulement comme solution de secours.

Le nombre d'actions visibles doit rester faible. Jarvis doit calculer les 2 à 5 prochaines actions les plus probables selon le contexte.

### 1.2 Sortie utilisateur

Sorties combinées :

- voix ;
- carte visuelle concise ;
- notification Windows ;
- ouverture directe du bon fichier, mail, dossier ou site lorsque Robert le demande.

La voix ne doit pas lire toute l'interface. Elle sert à :

- répondre à une demande de Robert ;
- signaler une information importante ;
- demander une validation nécessaire ;
- annoncer le résultat d'une action longue ;
- signaler une erreur réellement utile à Robert.

### 1.3 Proactivité

Jarvis doit fonctionner majoritairement en arrière-plan.

Il peut être proactif lorsque :

- un mail présente une forte probabilité d'urgence ou d'action à réaliser ;
- un rendez-vous approche ;
- une pièce jointe ou un document attendu arrive ;
- une tâche demandée auparavant vient de se terminer ;
- une action est bloquée et nécessite le choix de Robert.

Il doit rester silencieux pour :

- logs techniques ;
- synchronisations normales ;
- mails publicitaires ou faibles priorités ;
- événements déjà annoncés ;
- opérations sans conséquence et ne nécessitant aucune décision.

---

## 2. Architecture générale

```text
                   ┌──────────────────────────┐
                   │        Robert            │
                   │ clics / choix / souris   │
                   └────────────┬─────────────┘
                                │
                 ┌──────────────▼──────────────┐
                 │       Jarvis UX Layer       │
                 │ voix + cartes + notifications│
                 └──────────────┬──────────────┘
                                │
                 ┌──────────────▼──────────────┐
                 │     Orchestrateur Jarvis    │
                 │ contexte / mémoire / plans  │
                 └──────┬────────┬────────┬────┘
                        │        │        │
          ┌─────────────▼─┐  ┌───▼────┐  ┌▼──────────────┐
          │ Policy Engine │  │  LLM   │  │ Event Engine  │
          │ déterministe  │  │ local/ │  │ mails, tâches │
          │ permissions   │  │ cloud  │  │ rappels       │
          └─────────────┬─┘  └───┬────┘  └──────┬────────┘
                        │        │              │
                 ┌──────▼────────▼──────────────▼──────┐
                 │            Tool Router              │
                 └──┬────────┬─────────┬─────────┬────┘
                    │        │         │         │
              Thunderbird  Windows   Fichiers  Navigateur
              Extension     UIA/API   Everything Playwright
```

Principe fondamental : **le LLM ne reçoit jamais le droit d'exécuter arbitrairement une commande**. Il propose un appel de tool structuré. Le Policy Engine décide si cet appel est autorisé, nécessite une confirmation ou doit être refusé.

---

## 3. Mails : Thunderbird + Numericable

### 3.1 Choix recommandé

Ne pas lire ni modifier directement les bases ou fichiers internes du profil Thunderbird pendant que Thunderbird fonctionne.

Créer une **MailExtension Thunderbird Manifest V3** dédiée à Jarvis.

Fonctions :

- écouter `messages.onNewMailReceived` ;
- lire sujet, expéditeur, destinataires, en-têtes et contenu lorsque nécessaire ;
- lister et récupérer les pièces jointes ;
- rechercher des mails ;
- marquer, déplacer ou classer un message ;
- ouvrir une réponse avec `compose.beginReply` ;
- enregistrer un brouillon avec `compose.saveMessage` ;
- envoyer avec `compose.sendMessage` uniquement lorsqu'une autorisation explicite existe ;
- communiquer avec le service Windows Jarvis par **Native Messaging**.

### 3.2 Pourquoi Native Messaging

Thunderbird supporte l'API `runtime` permettant à une extension de communiquer avec une application native locale.

Avantages :

- pas de serveur exposé sur le réseau ;
- canal JSON local contrôlé ;
- Thunderbird reste la source de vérité de la messagerie ;
- permissions de l'extension explicites ;
- aucune nécessité de stocker une seconde fois le mot de passe mail dans Jarvis pour la voie principale.

### 3.3 Adresse Numericable

La documentation SFR actuelle indique pour les boîtes `@numericable.fr` :

- IMAP : `imap.numericable.fr`, port `993`, TLS 1.2/1.3 ;
- SMTP : `smtps.numericable.fr`, port `465`, TLS 1.2/1.3 ;
- POP : `pop.numericable.fr`, port `995`, TLS 1.2/1.3.

Thunderbird étant déjà configuré chez Robert, Jarvis devra **d'abord détecter et utiliser le compte existant dans Thunderbird** plutôt que demander de le reconfigurer.

Une intégration IMAP/SMTP directe restera uniquement un fallback futur.

### 3.4 Intelligence mail

Chaque mail entrant reçoit localement une fiche structurée :

- catégorie ;
- importance ;
- urgence ;
- action demandée ;
- date limite détectée ;
- personne/organisation ;
- présence de facture, rendez-vous, pièce jointe ou document demandé ;
- niveau de confiance ;
- suggestions d'actions.

Exemples de sorties :

- « Ce mail ne demande rien » → silence ;
- « Votre assurance demande un justificatif » → Jarvis cherche automatiquement les fichiers probables et propose les 3 meilleurs ;
- « Voulez-vous envoyer le PDF `facture_points.pdf` ? » → choix Oui / Voir / Non ;
- « Voici deux réponses possibles » → deux grandes cartes, pas de saisie obligatoire.

---

## 4. Recherche de fichiers

### 4.1 Niveau 1 — Everything

Utiliser **Everything de voidtools** comme moteur primaire des noms/chemins.

Intégration possible :

- `es.exe` pour la V1 ;
- SDK/IPC pour la version optimisée.

Avantages :

- index local ;
- recherche quasi instantanée ;
- faible consommation ;
- support des métadonnées telles que taille/date ;
- requêtes regex et chemin ;
- fonctionne entièrement localement.

Exemple utilisateur : Robert clique « trouver la facture des pneus ». Jarvis peut rechercher :

- `facture pneus` ;
- fichiers PDF récents ;
- chemins contenant `Point S` ;
- pièces jointes mail pertinentes ;
- documents ouverts récemment.

Il présente ensuite **3 résultats probables**, pas 70 résultats bruts.

### 4.2 Niveau 2 — recherche de contenu

Everything excelle principalement sur les noms et métadonnées. Ajouter ensuite un index de contenu local :

- PDF texte ;
- DOCX ;
- TXT/CSV ;
- noms de pièces jointes ;
- OCR seulement lorsque nécessaire.

Stockage local envisagé : SQLite + FTS5, avec embeddings optionnels pour les recherches sémantiques.

Exemple : « le papier où il y avait 587 euros » peut retrouver un PDF même si `587` n'est pas dans le nom du fichier.

### 4.3 Classement intelligent

Score de résultat combinant :

- correspondance nom ;
- correspondance contenu ;
- date récente ;
- dossier fréquent ;
- type de fichier ;
- personne ou organisme lié au contexte ;
- historique des choix de Robert.

---

## 5. Contrôle de Windows

### 5.1 Hiérarchie obligatoire des méthodes

Jarvis ne doit pas commencer par simuler des clics à des coordonnées écran.

Ordre :

1. **API ou commande native déterministe** ;
2. **API spécifique de l'application** ;
3. **Microsoft UI Automation (UIA)** ;
4. **Win32 / MSAA fallback** ;
5. **clavier/souris simulés** ;
6. **vision/OCR + coordonnées**, seulement en dernier recours.

### 5.2 Outils Windows

- Python `subprocess`, `os.startfile`, Win32/Shell APIs pour ouvrir logiciels, fichiers et dossiers ;
- PowerShell pour opérations système explicites ;
- `pywinauto` avec backend UIA pour applications de bureau ;
- fallback Win32 pour anciennes applications ;
- captures/OCR uniquement si un contrôle n'est pas exposé par UIA.

Chaque action UIA doit suivre :

```text
observer -> trouver l'élément -> vérifier qu'il est actionnable
-> agir -> vérifier le résultat -> journaliser
```

Ne jamais répéter aveuglément un clic après un échec.

### 5.3 Exemples utiles

- ouvrir Thunderbird ;
- ouvrir un dossier précis ;
- lancer un logiciel ;
- fermer une fenêtre après confirmation si données non enregistrées ;
- ouvrir le panneau son/imprimantes ;
- retrouver une fenêtre perdue ;
- lancer une impression puis demander confirmation avant impression réelle si nécessaire ;
- copier une information dans le presse-papiers ;
- organiser des fichiers ;
- télécharger un document demandé ;
- joindre un fichier au bon mail.

---

## 6. Navigateur

Utiliser **Playwright** pour le contenu web, pas des clics écran.

Principes :

- locators par rôle/label/texte accessible ;
- auto-wait ;
- profil persistant Jarvis séparé lorsque possible ;
- téléchargements capturés et enregistrés dans un dossier contrôlé ;
- file chooser traité explicitement ;
- UI Automation Windows seulement pour les fenêtres natives autour du navigateur (boîte de fichier, dialogue OS, etc.).

Exemples :

- rechercher une information ;
- ouvrir le site officiel approprié ;
- télécharger un formulaire ;
- retrouver une facture dans un espace client ;
- préremplir un formulaire ;
- s'arrêter avant une validation financière, contractuelle ou autre action sensible.

---

## 7. Interface Robert

### 7.1 Trois états

#### Invisible

Jarvis travaille en arrière-plan. Aucun tableau de bord permanent nécessaire.

#### Carte contextuelle

Petite fenêtre ou notification avec 2 à 5 actions maximum.

Exemple :

```text
Assurance — document demandé

J'ai trouvé 2 fichiers qui semblent correspondre.

[Facture Point S 587 €]   [Rapport expertise]
[Voir le mail]            [Plus tard]
```

Jarvis peut en parallèle dire une phrase courte.

#### Tableau de bord

Ouvert seulement lorsque Robert souhaite voir l'ensemble :

- important aujourd'hui ;
- mails à traiter ;
- tâches en attente ;
- documents récents ;
- historique des actions Jarvis.

### 7.2 Notifications Windows

Utiliser les notifications Windows actionnables pour permettre une réponse sans ouvrir Jarvis.

Actions typiques :

- Oui ;
- Non ;
- Plus tard ;
- Ouvrir ;
- Envoyer ;
- Voir avant ;
- Classer ;
- Réponse 1 / Réponse 2.

Limiter fortement la fréquence. Une notification silencieuse peut être placée dans le Centre de notifications si elle ne mérite pas d'interrompre Robert.

---

## 8. Voix

Le moteur existant `speech.py` constitue une bonne fondation pour la logique de prise de parole.

Architecture TTS à rendre interchangeable :

1. Windows SAPI — fallback toujours disponible ;
2. moteur neural local optionnel pour une voix française plus naturelle ;
3. moteur cloud optionnel si un jour la qualité maximale est prioritaire sur le mode hors-ligne.

La décision **quand parler** doit rester indépendante du moteur **comment parler**.

Ajouter :

- file d'attente audio ;
- priorité des annonces ;
- interruption d'une annonce faible priorité par une critique ;
- longueur maximale avant résumé ;
- mémoire des annonces déjà dites ;
- période de calme configurable ;
- détection de contenu sensible avant lecture à voix haute.

---

## 9. Moteur d'intelligence

### 9.1 LLM local possible

Ollama sous Windows supporte :

- modèles locaux ;
- tool calling ;
- sorties structurées JSON ;
- API locale ;
- compatibilité OpenAI.

Usage recommandé :

- classification de mails ;
- résumé ;
- extraction de tâches ;
- génération de réponses ;
- planification de recherche de fichiers ;
- sélection d'outils.

### 9.2 Modèle hybride

Prévoir une interface fournisseur pour pouvoir utiliser :

- un petit modèle local pour les tâches répétitives et privées ;
- un modèle plus puissant pour les demandes complexes, si autorisé ;
- aucun LLM pour les actions entièrement déterministes.

La sécurité ne dépend jamais du LLM.

---

## 10. Mémoire personnelle

Jarvis doit apprendre progressivement :

- dossiers de fichiers souvent choisis ;
- expéditeurs importants ;
- newsletters toujours ignorées ;
- types de réponses préférés ;
- logiciels fréquemment ouverts ;
- routines acceptées ;
- actions refusées ;
- horaires où Robert préfère ne pas être interrompu.

La mémoire doit être locale, visible et réinitialisable.

Ne jamais apprendre une automatisation destructrice uniquement parce que Robert l'a acceptée une fois.

---

## 11. Sécurité et permissions

Remplacer progressivement les trois niveaux actuels par une politique plus précise :

### READ

- lire mail ;
- chercher fichier ;
- lire agenda ;
- inspecter fenêtres ;
- rechercher sur Internet.

Exécution généralement automatique.

### REVERSIBLE_WRITE

- marquer un mail lu ;
- déplacer vers un dossier ;
- créer un brouillon ;
- copier ou renommer un fichier ;
- ouvrir/fermer une application sans perte de données.

Peut devenir automatique pour certains workflows appris et explicitement autorisés.

### EXTERNAL_SIDE_EFFECT

- envoyer un mail ;
- publier un formulaire ;
- transmettre un document ;
- envoyer une pièce jointe ;
- contacter une personne.

Confirmation obligatoire par défaut.

### DESTRUCTIVE

- supprimer définitivement ;
- écraser un fichier ;
- vider une corbeille ;
- modifier une configuration système critique ;
- action irréversible.

Confirmation forte obligatoire, avec présentation claire de la conséquence.

### Garanties

- journal local des actions ;
- idempotency key pour éviter les doubles envois ;
- kill switch global ;
- mode dry-run ;
- délai/cooldown sur actions répétées ;
- vérification de post-condition ;
- aucune clé/secrets dans GitHub.

---

## 12. Scénarios cibles

### Scénario A — nouveau mail important

1. Thunderbird reçoit le message.
2. Extension Jarvis reçoit l'événement après les filtres/junk.
3. Jarvis classe le mail.
4. S'il est banal : rien.
5. S'il demande une action : recherche des éléments nécessaires.
6. Jarvis parle brièvement.
7. Une carte montre les actions possibles.
8. Robert clique.
9. Jarvis exécute et vérifie.

### Scénario B — document demandé par mail

1. Mail : « Merci de nous envoyer la facture ».
2. Jarvis extrait `facture` + contexte de l'organisme.
3. Everything trouve les candidats par nom/date.
4. Index de contenu affine les résultats.
5. Jarvis présente les 2 ou 3 meilleurs.
6. Robert choisit le document.
7. Jarvis génère une réponse et attache le fichier.
8. Robert voit le destinataire + fichier + résumé de réponse.
9. Un clic confirme l'envoi.

### Scénario C — recherche de fichier sans taper

Une carte « Documents récents » peut être contextuelle :

- Factures ;
- Administratif ;
- Photos ;
- Téléchargements ;
- Documents reçus par mail ;
- Fichiers utilisés récemment.

Les choix précédents servent à prédire ce que Robert cherche.

### Scénario D — tâche web

1. Robert clique une action proposée.
2. Jarvis ouvre le navigateur.
3. Playwright agit via DOM/ARIA.
4. Téléchargement détecté et classé.
5. Si un dialogue Windows apparaît, UIA prend le relais.
6. Toute soumission sensible attend la confirmation.

---

## 13. Roadmap recommandée

### Phase 0 — fondations actuelles

- [x] serveur local FastAPI ;
- [x] sécurité initiale ;
- [x] politique de parole intelligente ;
- [x] TTS Windows de base ;
- [ ] journal d'événements unifié ;
- [ ] bus d'événements et Tool Router.

### Phase 1 — UX zéro-clavier

- [ ] notifications Windows avec boutons ;
- [ ] cartes contextuelles ;
- [ ] propositions d'actions dynamiques ;
- [ ] historique « ce que Jarvis a fait » ;
- [ ] réponses Oui/Non/Plus tard sans clavier ;
- [ ] démarrage automatique Windows.

### Phase 2 — Thunderbird

- [ ] MailExtension Manifest V3 ;
- [ ] Native Messaging host ;
- [ ] détection du compte existant ;
- [ ] événements nouveaux mails ;
- [ ] lecture + pièces jointes ;
- [ ] classement importance/action ;
- [ ] brouillons de réponse ;
- [ ] confirmation avant envoi ;
- [ ] anti-double-envoi.

### Phase 3 — fichiers

- [ ] installation/détection Everything ;
- [ ] wrapper `es.exe` ;
- [ ] recherche instantanée ;
- [ ] ranking contextuel ;
- [ ] ouverture dossier/fichier ;
- [ ] index contenu SQLite FTS ;
- [ ] PDF/DOCX ;
- [ ] OCR fallback ;
- [ ] suggestions automatiques de pièces jointes.

### Phase 4 — contrôle Windows

- [ ] Tool Windows Shell ;
- [ ] lancement/fermeture apps ;
- [ ] UI Automation via pywinauto ;
- [ ] découverte sémantique des contrôles ;
- [ ] post-condition obligatoire ;
- [ ] fallback clavier/souris ;
- [ ] OCR/vision uniquement en dernier recours.

### Phase 5 — navigateur

- [ ] Playwright ;
- [ ] session persistante contrôlée ;
- [ ] recherche web ;
- [ ] téléchargements ;
- [ ] formulaires ;
- [ ] passage UIA pour dialogues natifs ;
- [ ] confirmation avant soumission sensible.

### Phase 6 — intelligence et mémoire

- [ ] provider LLM abstrait ;
- [ ] Ollama local ;
- [ ] tool calling structuré ;
- [ ] mémoire de préférences locale ;
- [ ] détection tâches/dates/personnes ;
- [ ] apprentissage des suggestions acceptées/refusées ;
- [ ] mode cloud optionnel.

### Phase 7 — fiabilisation

- [ ] packaging Windows ;
- [ ] installateur unique ;
- [ ] mises à jour sûres ;
- [ ] backup config ;
- [ ] kill switch ;
- [ ] dry-run ;
- [ ] diagnostics ;
- [ ] tests UI réels ;
- [ ] tests Thunderbird réels ;
- [ ] tests de reprise après crash ;
- [ ] audit sécurité.

---

## 14. Sources techniques principales étudiées

- Thunderbird WebExtension APIs : https://webextension-api.thunderbird.net/
- Thunderbird developer docs : https://developer.thunderbird.net/add-ons
- Mozilla Native Messaging : https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging
- SFR configuration Numericable : https://assistance.sfr.fr/sfrmail-appli/sfrmail/configurer-messagerie-recevoir-email-sfr.html
- Microsoft UI Automation : https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiauto-win32
- pywinauto : https://github.com/pywinauto/pywinauto
- Everything SDK : https://www.voidtools.com/support/everything/sdk/
- Everything CLI : https://www.voidtools.com/support/everything/command_line_interface/
- Playwright locators : https://playwright.dev/docs/locators
- Microsoft Agent UX : https://microsoft.design/articles/ux-design-for-agents/
- Microsoft Windows notification UX : https://learn.microsoft.com/en-us/windows/apps/develop/notifications/app-notifications/app-notifications-ux-guidance
- Ollama tool calling : https://docs.ollama.com/capabilities/tool-calling
- Ollama structured outputs : https://docs.ollama.com/capabilities/structured-outputs

---

## Décision d'architecture

La cible à privilégier est donc :

**FastAPI local + Event Bus + Policy Engine + Thunderbird MailExtension/Native Messaging + Everything + Windows UI Automation + Playwright + notifications actionnables + TTS intelligent + LLM local/cloud interchangeable.**

Cette architecture réduit fortement le besoin de clavier tout en conservant un contrôle humain clair sur les actions qui ont une conséquence réelle.
