# Voix de Jarvis

Jarvis est conçu pour parler à Robert avec une voix féminine française douce, claire et naturelle. Le microphone n'est pas nécessaire.

## Ordre automatique

1. **ElevenLabs** — priorité qualité maximale. Modèle par défaut `eleven_v3`, langue française, débit légèrement ralenti et expressivité modérée.
2. **Azure Speech** — excellent compromis qualité/fiabilité. Voix par défaut `fr-FR-VivienneMultilingualNeural`.
3. **Qwen3-TTS local** — secours hors ligne. Modèle par défaut `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`, avec une consigne de voix féminine française douce et très articulée.
4. **Windows** — dernier recours uniquement afin de ne jamais laisser Robert sans réponse vocale.

Jarvis essaie les fournisseurs dans cet ordre. Une panne ou une configuration absente déclenche automatiquement le suivant.

## Configuration

Les clés ne doivent jamais être ajoutées au dépôt. Elles vont uniquement dans le fichier `.env` local.

### ElevenLabs

Renseigner :

- `JARVIS_ELEVENLABS_API_KEY`
- `JARVIS_ELEVENLABS_VOICE_ID`

Le Voice ID doit correspondre à une voix féminine française choisie dans le compte ElevenLabs.

### Azure Speech

Renseigner :

- `JARVIS_AZURE_SPEECH_KEY`
- `JARVIS_AZURE_SPEECH_REGION`

La voix par défaut est `fr-FR-VivienneMultilingualNeural`. Elle peut être remplacée avec `JARVIS_AZURE_VOICE_NAME`.

### Qwen3-TTS local

Lancer :

```text
INSTALLER_VOIX_LOCALE.bat
```

Cet installateur crée un environnement Python séparé `.venv-qwen-tts`. Le modèle est volumineux et est téléchargé lors de la première utilisation.

La configuration par défaut utilise le GPU CUDA. Pour un PC sans GPU compatible, modifier `JARVIS_QWEN3_TTS_DEVICE` dans `.env`, mais la génération CPU sera beaucoup plus lente.

## Avatar parlant

L'interface contient un avatar féminin en SVG. Quand le moteur vocal commence une phrase :

- la bouche s'anime ;
- la tête bouge légèrement ;
- les yeux clignent naturellement ;
- une petite onde vocale apparaît ;
- la phrase prononcée est affichée sous le visage.

L'animation est volontairement discrète : elle doit rendre Jarvis vivant sans distraire Robert.

## Principes de langage

La qualité du TTS ne suffit pas. Les phrases données au moteur vocal doivent rester :

- courtes ;
- en français naturel ;
- sans jargon ;
- avec le sujet important en premier ;
- précises sur l'action proposée ;
- jamais alarmistes sans raison.

Exemple :

> Robert, j'ai reçu un mail important de l'assurance. Ils demandent la facture des pneus avant vendredi.

plutôt que de lire mot pour mot l'objet et tout le corps du mail.

## Sécurité

Le choix du moteur vocal n'affecte jamais la règle de sécurité : toute action qui modifie, envoie ou supprime quelque chose nécessite toujours deux confirmations explicites de Robert.
