# Jarvis Papa — Robert Autopilot — Roadmap canonique

> Source de vérité d'exécution : GitHub `Rapt0r06300/jarvis-papa`, branche unique `main`.
>
> Audit de départ de ce grand run : `9da1eb54a35c6bc16004a7328935b5b1bac04a06`.
>
> Référence historique fournie : `b3100e6dcdf45ca6782225cefc927e6b0c386d13`.
>
> Catalogue canonique : **220 améliorations réelles**, P0-01 à P10-20.

## VISION

Jarvis Papa n'est pas un chatbot. C'est l'assistant personnel numérique de Robert : il collecte les signaux, comprend ce qu'ils signifient, relie les informations, élimine le bruit, détecte ce qui mérite l'attention, prépare le travail, explique ses recommandations et laisse Robert contrôler les actions importantes.

Pipeline cible :

`SIGNALS -> EVENTS -> ENTITIES -> SITUATIONS -> TASKS -> PROPOSALS -> ACTIONS -> VERIFIED OUTCOMES`

Pipeline d'exécution :

`INGEST -> NORMALIZE -> CLASSIFY -> EXTRACT -> CORRELATE -> SCORE -> PROPOSE -> GOVERN -> EXECUTE -> VERIFY -> LEARN`

Invariant produit : **READ / UNDERSTAND / CLASSIFY / CORRELATE / SUMMARIZE / DRAFT peuvent être fortement autonomes. SEND / DELETE / BUY / TRANSFER / PUBLISH / MODIFY IMPORTANT DATA restent gouvernés.**

## CURRENT STATE — audit P0

Le dépôt est déjà un produit avancé. Il possède notamment : Policy Kernel, authorization gates, transactions vérifiées, emergency stop, mémoire durable/semantic/procedural, Memory Center, RAG local avec provenance, mail intelligence cheap-first, commitments, proactivity, ResourceGovernor/ModelRouter, desktop natif PySide6, Thunderbird native messaging, browser workflow borné, API locale bearer protégée par DPAPI, secret store DPAPI, backup/restore, updater/rollback, evaluation lab, metrics et tracing privacy-safe.

Le delta depuis `b3100e6d…` contient **8 commits**, tous orientés CI/packaging/release/docs/installeur. Aucun nouveau moteur métier Robert Autopilot n'a été introduit dans ce delta.

### Baseline 0.7.0 conservée

- CI run `33656707253` : Ubuntu + Windows `success`.
- Windows EXE run `33656707277` : `success`.
- Tests du build Windows : **110 passed**, une warning de dépréciation non bloquante.
- `Jarvis.exe`, `JarvisNativeHost.exe`, `JarvisDiagnostic.exe` construits.
- `Jarvis-Setup.exe` construit.
- Clean install -> smoke -> uninstall -> reinstall -> smoke -> uninstall : succès.
- Provenance/attestation du setup : succès.
- Installer LFS SHA-256 : `e73b92bd8177446ed808619f1ce963b084075a2cb5fcf1cfd3ba830e9aabdaca`.
- Authenticode : **EXTERNAL BLOCKER** tant que les secrets de certificat ne sont pas configurés.
- Validation physique finale sur le PC de Robert : **EXTERNAL BLOCKER**.

## GAPS confirmés

1. Il n'existe pas encore de modèle canonique `NormalizedEvent -> Entity -> Situation`.
2. Les mails sont classés mais la taxonomie/action-state/thread state reste trop coarse pour l'expérience cible.
3. Commitments/proactivity existent mais ne sont pas encore projetés en situations cross-source.
4. Aucun contrat typé `RUN_STARTED/STAGE_STARTED/PROGRESS_UPDATE/...` n'existe actuellement.
5. Les commandes/colis/marketplaces/banque ne partagent pas encore une couche de corrélation canonique.
6. Le RAG retrouve des documents mais ne les classe pas encore par preuve de situation (order/date/amount/merchant).
7. Le desktop reste trop organisé en surfaces fonctionnelles/techniques plutôt qu'en Today/Decisions/Situations.
8. L'evaluation lab ne mesure pas encore CRITICAL_MISS_RATE, bruit d'alertes, fusion ou time-to-first-useful-info.
9. Les connecteurs futurs doivent déclarer `CONNECTED / DEGRADED / DISCONNECTED / AUTH_REQUIRED`.
10. README avait deux claims devenus obsolètes : ancien nom d'installeur et usage `.env` présenté comme final-user secret path.

## ARCHITECTURE — réutilisation obligatoire

- Gouvernance : `governance.py`, `authorization_gate.py`, `transactions.py`, `emergency_stop.py`.
- Mail : `mail.py`, `mail_intelligence.py`, `commitments.py`, `thunderbird.py`.
- Proactivité : `proactivity.py`, `daily_brief.py`.
- Mémoire : `memory.py`, `memory_center.py`, `memory_semantic.py`, `procedural_memory.py`.
- Documents : `document_rag.py`.
- Runtime : `runtime_intelligence.py`, ResourceGovernor, ModelRouter.
- Desktop : `professional_desktop.py`.
- Web : `browser_workflow.py`, `web_read.py`.
- Sécurité : `local_api_auth.py`, `secret_store.py`.
- Fiabilité : `system_reliability.py`, `restore_coordinator.py`, `update_manager.py`.
- Qualité : `evaluation_lab.py`, `metrics.py`, `tracing.py`.

Nouvelles abstractions légères :

`SourceAdapter(read-only) -> NormalizedEvent -> Correlator -> SituationStore -> Priority/Proposal`

Les mutations restent séparées et traversent le Policy Kernel existant.

## SECURITY — capability matrix

| Capability | Autonomie | Risque | Approval | Verification |
|---|---|---:|---|---|
| Lire/synchroniser une source | oui si consentie | faible/moyen | consentement source | freshness + provenance |
| Classifier/extract/summarize | oui | moyen | non | schema validation + confidence |
| Corréler | oui mais réversible | moyen/élevé | confirmation si match important ambigu | evidence score |
| Préparer un draft | oui | moyen | non pour préparation | source-grounded |
| Envoyer un mail/message | non par défaut | élevé | oui | receipt + `verified=true` |
| Archiver/supprimer | non | élevé | oui | post-condition |
| Publier/modifier annonce | non | élevé | oui | post-condition |
| Achat/paiement/virement/bénéficiaire | **interdit en autonomie** | critique | politique stricte | aucune voie autonome |
| Lire/importer données bancaires | oui si intégration autorisée | élevé | consentement | provenance/freshness |
| Manipuler secrets/2FA/CVV | **interdit en mémoire/action** | critique | n/a | hard deny |

Toutes les données EMAIL/WEB/PDF/QR/MARKETPLACE/TOOL OUTPUT sont **untrusted data**. Leur texte n'acquiert jamais de privilège système.

## EVALUATION

Métriques à conserver/ajouter : `CRITICAL_MISS_RATE`, precision/recall important, notification noise ratio, situation fusion accuracy, false merge/missed merge, obligation/action-state accuracy, draft accepted/edited/rejected, startup time to first useful information, retries/degraded-source rate et idempotent duplicate rate.

Aucune amélioration critique n'est promue sur un seul benchmark artificiel.

## RELEASE GATES — evidence matrix

| Niveau | Exigence |
|---|---|
| Implemented | code présent |
| Unit | tests unitaires pertinents verts |
| Integration | source/persistence/governance intégrées |
| Security | prompt injection, permissions, secrets, destructive/financial gates |
| Windows E2E | EXE installé réellement testé quand la feature touche le runtime distribué |
| Production Ready | toutes les preuves applicables + aucune blocker critique |
| Signed Release | Authenticode valide + provenance + artefacts |
| Final PC | validation réelle sur le PC de Robert |

`DONE_VERIFIED` signifie : acceptance criteria satisfaits, tests/preuves attachables, pas seulement « le code existe ».

## P0 — preuves exécutées dans ce run

| ID | Résultat | Evidence |
|---|---|---|
| P0-01 | HEAD `9da1eb54a35c6bc16004a7328935b5b1bac04a06`; 8 commits depuis `b3100e6d…`; seul `main`. | GitHub repo/branches/compare/commits |
| P0-02 | Modules métier, sécurité, mémoire, runtime, desktop et intégrations cartographiés. | `src/jarvis_papa/*` |
| P0-03 | CI Python matrix Ubuntu/Windows + Windows EXE/packaging/E2E/provenance revalidés. | Actions `33656707253`, `33656707277`, `33657556876` |
| P0-04 | README détecté obsolète sur nom installeur et `.env`; correction prévue dans ce run. | README + runtime DPAPI |
| P0-05 | PolicyKernel/authorization/transactions/emergency-stop réutilisés; aucun nouveau bypass. | gouvernance existante |
| P0-06 | DurableMemory/semantic/procedural/MemoryCenter/RAG déjà matures; extension situation-aware seulement. | `memory*.py`, `procedural_memory.py`, `document_rag.py` |
| P0-07 | mail_intelligence cheap-first, commitments et proactivity déjà réels; gaps = threads/situations/responsibility. | `mail_intelligence.py`, `commitments.py`, `proactivity.py` |
| P0-08 | PySide6 desktop + QThreadPool existants; futur UX doit simplifier autour décisions/situations. | `professional_desktop.py` |
| P0-09 | ResourceGovernor/ModelRouter/local-first existent; contrat progress events absent. | `runtime_intelligence.py`; recherche `RUN_STARTED` négative |
| P0-10 | Backup borné + restore staged + pre-restore safety; état opérationnel éphémère exclu; updater/rollback vérifiés. | `system_reliability.py`, `restore_coordinator.py`, `update_manager.py` |
| P0-11 | Bearer local API + token DPAPI fail-closed en build Windows; no plaintext fallback. | `local_api_auth.py`, `secret_store.py` |
| P0-12 | Sources externes restent données non fiables; red-team déjà amorcé dans evaluation lab. | mémoire/gouvernance/evaluation |
| P0-13 | Thunderbird native bridge réel; mutation reconnue seulement si `verified=true`. | `thunderbird.py` |
| P0-14 | Browser workflow typé et borné; intégrations officielles/capability detection, aucun CAPTCHA bypass. | `browser_workflow.py` + recherche eBay/Mondial Relay |
| P0-15 | RAG local PDF/DOCX/XLSX avec provenance; gap = ranking par situation/facture. | `document_rag.py` |
| P0-16 | Metrics/tracing privacy-safe + evaluation lab local/no-auto-promote; nouvelles métriques requises. | `metrics.py`, `tracing.py`, `evaluation_lab.py` |
| P0-17 | Matrice autonomie définie. | section SECURITY |
| P0-18 | Matrice preuves/release définie. | section RELEASE GATES |
| P0-19 | Roadmap canonique de 220 améliorations créée. | ce fichier |
| P0-20 | Baseline 0.7.0 : 110 tests, EXE/installer, clean E2E, attestation; signature/final-PC restent externes. | Actions/logs + `ROADMAP_0.7.0_CLOSURE.md` |

## METADATA CONTRACTS PAR WORKSTREAM

Chaque item du catalogue référence le contrat de sa phase. Ce contrat fournit les champs **goal, user value, implementation notes, dependencies, risk, tests, acceptance criteria, evidence required et Done Contract**. Le titre de l'item est le résultat spécifique qui s'ajoute aux critères du contrat. Les détails opérationnels sont synchronisés dans Agiflow.

- **P0** — Goal: vérité dépôt/baseline. User value: zéro reconstruction/régression. Impl: audit code/runtime/docs. Dependencies: aucune. Risk: critique si omis. Tests: GitHub/CI/Windows/docs. Acceptance: preuve exacte. Evidence: SHA/fichiers/logs. Done: conclusion sourcée.
- **P1** — Goal: événements/entités/situations typés. User value: raisonnement par cas réel. Impl: schémas validés/idempotence/persistence versionnée. Dependencies: P0. Risk: moyen. Tests: unit+integration+migration+governance. Acceptance: provenance/confidence/validation. Evidence: tests/fixtures/migrations. Done: sans régression.
- **P2** — Goal: sens/action/thread mail. User value: bruit éliminé. Impl: cheap-first puis LLM ambigu. Dependencies: P1+Thunderbird+commitments. Risk: élevé. Tests: taxonomie/threads/phishing/injection. Acceptance: pas de suppression autonome, UNKNOWN_IMPORTANT conservateur. Evidence: benchmark. Done: recall important + sécurité.
- **P3** — Goal: progression vraie/non bloquante. User value: Jarvis visible sans théâtre. Impl: événements moteur -> UI/TTS + workers. Dependencies: P1/runtime. Risk: moyen. Tests: ordre/throttle/cancel/reprise/TTS. Acceptance: aucune narration sans événement. Evidence: runtime/E2E. Done: UI responsive.
- **P4** — Goal: commande/colis = situation. User value: codes/délais retrouvés. Impl: mail-first/API officielle si autorisée. Dependencies: P1/P2/RAG. Risk: élevé. Tests: delay/pickup/refund/QR/dedupe. Acceptance: jamais de QR/code inventé. Evidence: fixtures+E2E. Done: une situation cohérente.
- **P5** — Goal: eBay/Leboncoin. User value: décisions/drafts rapides. Impl: read/draft-first + gouvernance. Dependencies: P1/P2. Risk: élevé. Tests: offers/questions/phishing/completion. Acceptance: aucune transaction autonome. Evidence: benchmark+policy tests. Done: écritures gouvernées/vérifiées.
- **P6** — Goal: banque read-only. User value: opérations expliquées/rapprochées. Impl: local/déterministe, contexte minimal. Dependencies: P1/P4/P7. Risk: critique. Tests: anomalies/refunds/phishing/hard-deny. Acceptance: zéro voie autonome de transfert/paiement. Evidence: policy+privacy benchmark. Done: analyse prudente et sourcée.
- **P7** — Goal: corrélation cross-source. User value: une information, pas un silo. Impl: evidence scoring + match states + unified search. Dependencies: P1+adapters. Risk: élevé. Tests: false/missed merge/correction/freshness. Acceptance: fusion incertaine réversible. Evidence: fusion benchmark. Done: qualité mesurée.
- **P8** — Goal: apprentissage contrôlé. User value: Jarvis s'adapte sans surapprendre. Impl: Memory Center/procedural memory existants. Dependencies: P1/P2/P5. Risk: élevé. Tests: promotion/conflit/oubli/secret/expiry. Acceptance: préférences visibles/corrigibles. Evidence: memory benchmark. Done: apprentissage réversible.
- **P9** — Goal: desktop Robert-first. User value: comprendre immédiatement quoi faire. Impl: conserver PySide6, Today/Jarvis/Decisions/Situations/Search. Dependencies: données P1-P8. Risk: moyen. Tests: DPI/clavier/contraste/TTS. Acceptance: pas de jargon, recommandation + max 2 alternatives. Evidence: Windows UI/E2E. Done: flows primaires simples.
- **P10** — Goal: preuve production. User value: robustesse réelle. Impl: étendre evaluation_lab/datasets/Windows installé. Dependencies: phases fonctionnelles. Risk: critique. Tests: stress/injection/crash/offline/outage/installed EXE. Acceptance: aucune gate masquée. Evidence: CI/E2E/signature/final-PC. Done: Production Ready seulement avec preuves.

## CATALOGUE DES 220 AMÉLIORATIONS

### P0
- **P0-01** [DONE_VERIFIED] — Resolve and record the real main HEAD and commit delta
- **P0-02** [DONE_VERIFIED] — Build a code-level capability map of Jarvis Papa
- **P0-03** [DONE_VERIFIED] — Build the test and CI coverage matrix
- **P0-04** [DONE_VERIFIED] — Reconcile documentation claims against runtime evidence
- **P0-05** [DONE_VERIFIED] — Inventory governance and authorization reuse points
- **P0-06** [DONE_VERIFIED] — Inventory memory, semantic memory, procedural memory and RAG reuse
- **P0-07** [DONE_VERIFIED] — Audit proactivity, priority briefing and commitments modules
- **P0-08** [DONE_VERIFIED] — Audit the native desktop UX surfaces and interaction model
- **P0-09** [DONE_VERIFIED] — Audit background workers, async execution and resource governor
- **P0-10** [DONE_VERIFIED] — Audit persistence, migrations, backup/restore, updater and rollback
- **P0-11** [DONE_VERIFIED] — Audit local API authentication, DPAPI and secret boundaries
- **P0-12** [DONE_VERIFIED] — Audit untrusted-data and prompt-injection handling across sources
- **P0-13** [DONE_VERIFIED] — Audit Thunderbird and email ingestion capabilities
- **P0-14** [DONE_VERIFIED] — Audit browser/web automation and allowed integration patterns
- **P0-15** [DONE_VERIFIED] — Audit document search, PDF/image extraction and provenance
- **P0-16** [DONE_VERIFIED] — Audit metrics, tracing and evaluation lab
- **P0-17** [DONE_VERIFIED] — Define the Robert Autopilot capability and risk matrix
- **P0-18** [DONE_VERIFIED] — Define the evidence and release-readiness matrix
- **P0-19** [DONE_VERIFIED] — Create docs/ROADMAP_ROBERT_AUTOPILOT.md as canonical repo roadmap
- **P0-20** [DONE_VERIFIED] — Establish a no-regression baseline for the existing 0.7.0 product

### P1
- **P1-01** [PLANNED] — Define a typed NormalizedEvent contract
- **P1-02** [PLANNED] — Define the read-only SourceAdapter interface
- **P1-03** [PLANNED] — Implement deterministic event identity and idempotent ingestion
- **P1-04** [PLANNED] — Define canonical Entity models and typed identifiers
- **P1-05** [PLANNED] — Define the canonical Situation model
- **P1-06** [PLANNED] — Define Task, Proposal, Action and Outcome domain contracts
- **P1-07** [PLANNED] — Standardize confidence and provenance propagation
- **P1-08** [PLANNED] — Implement POSSIBLE_MATCH / LIKELY_MATCH / CONFIRMED_MATCH relation states
- **P1-09** [PLANNED] — Implement ordered situation timelines
- **P1-10** [PLANNED] — Implement explicit situation state machines per domain
- **P1-11** [PLANNED] — Implement correlation and situation dedupe keys
- **P1-12** [PLANNED] — Add versioned persistent storage for situations and events
- **P1-13** [PLANNED] — Add safe migration and rollback tests for new situation state
- **P1-14** [PLANNED] — Persist processed-event checkpoints for incremental resume
- **P1-15** [PLANNED] — Build the incremental situation orchestrator pipeline
- **P1-16** [PLANNED] — Implement explainable situation priority scoring
- **P1-17** [PLANNED] — Implement situation completion and task-cleanup rules
- **P1-18** [PLANNED] — Add EXPECTED_EVENT tracking and overdue escalation
- **P1-19** [PLANNED] — Route Situation actions through existing governance and verification receipts
- **P1-20** [PLANNED] — Extend search indexing across situations, entities and timelines

### P2
- **P2-01** [PLANNED] — Build a hybrid cheap-first email triage pipeline
- **P2-02** [PLANNED] — Implement the evolving email intent taxonomy
- **P2-03** [PLANNED] — Extract structured email meaning with typed schema
- **P2-04** [PLANNED] — Implement email action-state classification
- **P2-05** [PLANNED] — Group messages into durable conversation threads
- **P2-06** [PLANNED] — Derive thread-level latest state and open question
- **P2-07** [PLANNED] — Integrate commitment extraction into thread and situation state
- **P2-08** [PLANNED] — Model responsibility states for conversations
- **P2-09** [PLANNED] — Implement briefing suppression classes for mail
- **P2-10** [PLANNED] — Add sender/domain trust and spoofing signals
- **P2-11** [PLANNED] — Sanitize HTML email and block active/remote content by default
- **P2-12** [PLANNED] — Add bounded recent-mail backfill policy for first deployment
- **P2-13** [PLANNED] — Prioritize fresh actionable mail ahead of bulk backlog
- **P2-14** [PLANNED] — Build concise per-thread structured summaries
- **P2-15** [PLANNED] — Add classification correction capture from Robert
- **P2-16** [PLANNED] — Implement read-only/draft-first email autonomy mode
- **P2-17** [PLANNED] — Generate draft replies from situation context rather than single mail
- **P2-18** [PLANNED] — Detect stale unanswered inbound conversations
- **P2-19** [PLANNED] — Aggregate briefing counts by situation instead of message count
- **P2-20** [PLANNED] — Build email intelligence regression benchmark

### P3
- **P3-01** [PLANNED] — Define typed runtime progress events
- **P3-02** [PLANNED] — Add a shared runtime event bus for orchestrator, UI and TTS
- **P3-03** [PLANNED] — Enforce truthful progress narration
- **P3-04** [PLANNED] — Add stage-level progress adapters for major workflows
- **P3-05** [PLANNED] — Implement progress throttling policy
- **P3-06** [PLANNED] — Merge burst progress updates into one human update
- **P3-07** [PLANNED] — Provide immediate visual acknowledgment for long operations
- **P3-08** [PLANNED] — Move long analysis off the GUI thread
- **P3-09** [PLANNED] — Implement safe user cancellation
- **P3-10** [PLANNED] — Resume interrupted runs from checkpoints
- **P3-11** [PLANNED] — Add priority preemption for genuinely urgent discoveries
- **P3-12** [PLANNED] — Implement a priority-aware TTS queue
- **P3-13** [PLANNED] — Prevent overlapping or duplicated TTS speech
- **P3-14** [PLANNED] — Keep text UI fully functional when TTS fails
- **P3-15** [PLANNED] — Produce a concise final run synthesis
- **P3-16** [PLANNED] — Humanize partial-source failure messages
- **P3-17** [PLANNED] — Track CURRENT versus LAST_KNOWN source freshness
- **P3-18** [PLANNED] — Add a simple 'Ce que Jarvis fait' activity surface
- **P3-19** [PLANNED] — Add evidence-based 'Ce que Jarvis a fait aujourd’hui' history
- **P3-20** [PLANNED] — Measure startup time to first useful information

### P4
- **P4-01** [PLANNED] — Define canonical Order entity and lifecycle
- **P4-02** [PLANNED] — Define canonical Shipment entity and lifecycle
- **P4-03** [PLANNED] — Parse Amazon order emails into normalized events
- **P4-04** [PLANNED] — Extract order confirmation facts
- **P4-05** [PLANNED] — Extract Amazon shipment and tracking updates
- **P4-06** [PLANNED] — Detect order and delivery delays
- **P4-07** [PLANNED] — Detect delivery confirmation and close shipment tasks
- **P4-08** [PLANNED] — Model return and refund lifecycle
- **P4-09** [PLANNED] — Link invoices and receipts to orders
- **P4-10** [PLANNED] — Parse Mondial Relay arrival emails
- **P4-11** [PLANNED] — Extract and normalize pickup point details
- **P4-12** [PLANNED] — Calculate pickup deadline from explicit source rules
- **P4-13** [PLANNED] — Extract pickup codes with provenance and limited retention
- **P4-14** [PLANNED] — Display real QR source without reconstructing it
- **P4-15** [PLANNED] — Normalize carrier tracking numbers
- **P4-16** [PLANNED] — Correlate Amazon orders with carrier shipments
- **P4-17** [PLANNED] — Correlate Amazon and Mondial Relay pickup events
- **P4-18** [PLANNED] — Implement pickup reminder, snooze and acknowledgement policy
- **P4-19** [PLANNED] — Build an order-centric briefing projection
- **P4-20** [PLANNED] — Build order/parcel synthetic benchmark and E2E scenario

### P5
- **P5-01** [PLANNED] — Define a read-only MarketplaceAdapter contract
- **P5-02** [PLANNED] — Recognize eBay emails and messages
- **P5-03** [PLANNED] — Recognize Leboncoin emails and messages
- **P5-04** [PLANNED] — Define MarketplaceListing entity
- **P5-05** [PLANNED] — Model marketplace conversation, buyer and seller identities
- **P5-06** [PLANNED] — Extract buyer questions and requested decisions
- **P5-07** [PLANNED] — Extract negotiation offers and proposed prices
- **P5-08** [PLANNED] — Retrieve and ground the current asking price
- **P5-09** [PLANNED] — Build explainable negotiation recommendations
- **P5-10** [PLANNED] — Generate grounded marketplace reply drafts
- **P5-11** [PLANNED] — Learn Robert's marketplace response style safely
- **P5-12** [PLANNED] — Detect shipping versus hand-delivery intent
- **P5-13** [PLANNED] — Detect appointment and location proposals
- **P5-14** [PLANNED] — Model active sale, payment and shipping-required lifecycle
- **P5-15** [PLANNED] — Track stale buyer conversations without noisy alerts
- **P5-16** [PLANNED] — Close marketplace situations when sale completes
- **P5-17** [PLANNED] — Detect suspicious off-platform payment, secret and link requests
- **P5-18** [PLANNED] — Enforce marketplace transaction-mutation prohibition
- **P5-19** [PLANNED] — Define marketplace decision-card data contract
- **P5-20** [PLANNED] — Build synthetic eBay/Leboncoin evaluation scenarios

### P6
- **P6-01** [PLANNED] — Classify banking data sensitivity explicitly
- **P6-02** [PLANNED] — Define a read-only BankDataAdapter contract
- **P6-03** [PLANNED] — Recognize bank emails with trust and phishing context
- **P6-04** [PLANNED] — Import structured statements or transaction exports when available
- **P6-05** [PLANNED] — Define normalized Transaction entity
- **P6-06** [PLANNED] — Normalize merchant aliases with controlled confidence
- **P6-07** [PLANNED] — Detect probable duplicate transactions
- **P6-08** [PLANNED] — Detect unusual transaction amounts with explainable baselines
- **P6-09** [PLANNED] — Detect unknown or newly seen merchants
- **P6-10** [PLANNED] — Detect transactions without matching known situations
- **P6-11** [PLANNED] — Track expected refunds from commerce situations
- **P6-12** [PLANNED] — Match observed credits to expected refunds
- **P6-13** [PLANNED] — Correlate purchases to bank transactions
- **P6-14** [PLANNED] — Correlate invoices to bank transactions
- **P6-15** [PLANNED] — Detect bank or administrative requests for documents
- **P6-16** [PLANNED] — Explain transactions in simple French
- **P6-17** [PLANNED] — Use cautious anomaly language instead of fraud claims
- **P6-18** [PLANNED] — Hard-deny autonomous financial mutations
- **P6-19** [PLANNED] — Minimize LLM exposure for bank data
- **P6-20** [PLANNED] — Build synthetic banking/phishing reconciliation benchmark

### P7
- **P7-01** [PLANNED] — Build a cross-source correlation service
- **P7-02** [PLANNED] — Define strong/medium/weak correlation evidence scoring
- **P7-03** [PLANNED] — Create a controlled merchant alias registry
- **P7-04** [PLANNED] — Create controlled person/contact alias relations
- **P7-05** [PLANNED] — Deduplicate logical documents by content hash and metadata
- **P7-06** [PLANNED] — Rank invoice/document candidates by situation evidence
- **P7-07** [PLANNED] — Link orders to invoices automatically when evidence is strong
- **P7-08** [PLANNED] — Link document requests to matching local documents
- **P7-09** [PLANNED] — Link transactions to invoices through combined evidence
- **P7-10** [PLANNED] — Link shipments to orders using strongest available identifiers
- **P7-11** [PLANNED] — Link marketplace conversations to listings and items
- **P7-12** [PLANNED] — Support safe relation merge, split and correction
- **P7-13** [PLANNED] — Add user confirm/reject controls for uncertain correlations
- **P7-14** [PLANNED] — Keep an audit trail of correlation decisions
- **P7-15** [PLANNED] — Define a unified search result contract
- **P7-16** [PLANNED] — Resolve conversational referents such as 'celui-là' and 'le deuxième'
- **P7-17** [PLANNED] — Build a privacy-minimized situation context builder for LLMs
- **P7-18** [PLANNED] — Propagate fact freshness and age across correlations
- **P7-19** [PLANNED] — Provide deep links/actions back to source evidence
- **P7-20** [PLANNED] — Measure cross-source fusion quality

### P8
- **P8-01** [PLANNED] — Project situation memory into the existing Memory Center
- **P8-02** [PLANNED] — Define controlled preference evidence with count, scope, provenance and expiry
- **P8-03** [PLANNED] — Add thresholds for promoting corrections into preferences
- **P8-04** [PLANNED] — Learn reply-style preferences from approved drafts
- **P8-05** [PLANNED] — Learn negotiation preferences conservatively
- **P8-06** [PLANNED] — Learn reminder preferences from snooze and acknowledgement patterns
- **P8-07** [PLANNED] — Learn noise-category preferences with critical safeguards
- **P8-08** [PLANNED] — Detect repeated workflow patterns as procedural-memory candidates
- **P8-09** [PLANNED] — Keep learned procedures proposal-first for external actions
- **P8-10** [PLANNED] — Preserve provenance links for every learned preference
- **P8-11** [PLANNED] — Classify memory retention by data sensitivity
- **P8-12** [PLANNED] — Apply short-lived retention to parcel pickup codes
- **P8-13** [PLANNED] — Reassert hard memory exclusions for passwords, CVV, tokens, cookies and 2FA
- **P8-14** [PLANNED] — Show learned preferences in Memory Center
- **P8-15** [PLANNED] — Add Correct and Forget controls for learned preferences
- **P8-16** [PLANNED] — Resolve conflicting preference evidence
- **P8-17** [PLANNED] — Decay stale inferred preferences
- **P8-18** [PLANNED] — Measure draft acceptance, edit and rejection outcomes
- **P8-19** [PLANNED] — Retrieve memory context by active situation scope
- **P8-20** [PLANNED] — Build learning/memory safety benchmark

### P9
- **P9-01** [PLANNED] — Build a Robert-first Today landing view
- **P9-02** [PLANNED] — Build a simple Jarvis activity view
- **P9-03** [PLANNED] — Centralize all pending decisions in one Decisions view
- **P9-04** [PLANNED] — Add a concise Situations view
- **P9-05** [PLANNED] — Add unified Search as a first-class desktop surface
- **P9-06** [PLANNED] — Remove technical jargon from Robert-facing primary UI
- **P9-07** [PLANNED] — Standardize decision cards around recommendation plus two alternatives
- **P9-08** [PLANNED] — Build parcel decision/action cards
- **P9-09** [PLANNED] — Build marketplace negotiation decision cards
- **P9-10** [PLANNED] — Build cautious bank review cards
- **P9-11** [PLANNED] — Render situation timelines for quick comprehension
- **P9-12** [PLANNED] — Add simple 'Pourquoi tu me montres ça ?' explanations
- **P9-13** [PLANNED] — Humanize uncertainty wording
- **P9-14** [PLANNED] — Certify layout at Windows 125% scaling
- **P9-15** [PLANNED] — Certify layout at Windows 150% scaling
- **P9-16** [PLANNED] — Certify layout at Windows 175% scaling
- **P9-17** [PLANNED] — Make primary workflows keyboard-complete
- **P9-18** [PLANNED] — Improve readability, contrast and non-color-only state cues
- **P9-19** [PLANNED] — Prioritize TTS output while keeping microphone secondary
- **P9-20** [PLANNED] — Build a 100% synthetic Robert Autopilot demo mode

### P10
- **P10-01** [PLANNED] — Generate a reproducible 150-email 'journée de Robert' dataset
- **P10-02** [PLANNED] — Add a 500-event stress dataset and performance harness
- **P10-03** [PLANNED] — Add CRITICAL_MISS_RATE as a first-class quality metric
- **P10-04** [PLANNED] — Measure notification noise ratio
- **P10-05** [PLANNED] — Measure situation-fusion accuracy
- **P10-06** [PLANNED] — Measure task and obligation detection quality
- **P10-07** [PLANNED] — Measure draft acceptance, edit and rejection rates by domain
- **P10-08** [PLANNED] — Gate startup time to first useful information
- **P10-09** [PLANNED] — Build prompt-injection red-team matrix across every untrusted source
- **P10-10** [PLANNED] — Build phishing/lookalike/link safety red-team cases
- **P10-11** [PLANNED] — Add duplicate-ingestion idempotence E2E
- **P10-12** [PLANNED] — Add crash-during-analysis resume E2E
- **P10-13** [PLANNED] — Add offline/local-capability E2E
- **P10-14** [PLANNED] — Add marketplace-source outage isolation E2E
- **P10-15** [PLANNED] — Add Internet-outage graceful degradation tests
- **P10-16** [PLANNED] — Add TTS-outage E2E
- **P10-17** [PLANNED] — Add Windows accessibility/scaling certification suite
- **P10-18** [PLANNED] — Extend installed Jarvis.exe smoke/E2E to Robert Autopilot
- **P10-19** [PLANNED] — Extend installer/update/rollback/backup E2E for situation state
- **P10-20** [PLANNED] — Create final Robert Autopilot PC certification and signed-release gate

## DEPENDENCIES / ORDRE D'EXÉCUTION

Premier milestone : **ROBERT AUTOPILOT MVP**.

1. P0 vérité/baseline.
2. P1 Situation Engine minimal.
3. P2 email intelligence + thread/commitment.
4. P3 progression vraie et runtime non bloquant.
5. P4 commandes/colis.
6. P9 surfaces Today/Decisions/Situations dès que P1-P4 sont fiables.
7. P5/P6/P7/P8 renforcent marketplace, banque, corrélation et personnalisation.
8. P10 verrouille toute promotion production.

Priorité interne : `VALUE_TO_ROBERT × FREQUENCY × RELIABILITY_GAIN ÷ COMPLEXITY_RISK`.

## DONE CONTRACTS GLOBAUX

Une feature n'est `DONE_VERIFIED` que si :

1. le comportement est présent dans le code/runtime visé ;
2. les tests applicables sont verts ;
3. la gouvernance existante n'est pas contournée ;
4. les données externes restent non privilégiées ;
5. les mutations critiques produisent un résultat vérifié, pas « tool called = success » ;
6. la provenance/confiance est conservée pour les déductions importantes ;
7. les données persistées ont stratégie migration/backup/rollback ;
8. les secrets/2FA/CVV/tokens/cookies ne sont pas mémorisés ;
9. l'UI Robert-facing ne dépend pas de jargon technique ;
10. les preuves Windows installé sont ajoutées quand le packaging/runtime est impacté.

## EXTERNAL BLOCKERS CONNUS

- Certificat Authenticode réel et secrets Actions associés.
- Validation physique finale sur le PC de Robert.
- Credentials/approbations propres à certaines APIs tierces lorsque ces APIs sont choisies.
- Aucune de ces dépendances ne bloque P1/P2/P3/P4 email-first et local-first.

## NEXT EXECUTION BLOCK

Après P0, le meilleur ratio valeur/risque est **MVP-1A — Situation Domain Contracts** : `NormalizedEvent`, `SourceAdapter`, idempotence, `Entity`, `Situation`, `Task/Proposal/Action/Outcome`, confiance/provenance.
