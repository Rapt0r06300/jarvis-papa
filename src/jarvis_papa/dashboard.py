from jarvis_papa.config import settings


_DASHBOARD = r"""
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis</title>
  <style>
    :root {
      font-family: "Segoe UI", system-ui, sans-serif;
      color: #182235;
      background: #f4f7fb;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: #f4f7fb; overflow-x: hidden; }
    button { font: inherit; }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(250px, 31%) 1fr;
      max-width: 1500px;
      margin: 0 auto;
      background: #fff;
    }
    .assistant-pane {
      position: relative;
      padding: 24px 24px 20px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: linear-gradient(180deg, #edf5ff 0%, #f9fbff 58%, #ffffff 100%);
      border-right: 1px solid #dbe4ef;
      overflow: hidden;
    }
    .avatar-wrap { width: min(310px, 92%); position: relative; }
    .avatar { width: 100%; display: block; filter: drop-shadow(0 16px 30px rgba(35, 77, 125, .12)); }
    .avatar .head-group { transform-origin: 150px 155px; animation: breathe 4.5s ease-in-out infinite; }
    .avatar .eye-lid { transform-origin: center; animation: blink 5.4s infinite; }
    .avatar .mouth-open { transform-origin: 150px 221px; transform: scaleY(.18); transition: transform .12s ease; }
    .assistant-pane.speaking .avatar .mouth-open { animation: talk .22s ease-in-out infinite alternate; }
    .assistant-pane.speaking .avatar .head-group { animation: speakingHead 1.3s ease-in-out infinite alternate; }
    @keyframes talk { from { transform: scaleY(.18); } to { transform: scaleY(1.15); } }
    @keyframes breathe { 0%,100% { transform: translateY(0); } 50% { transform: translateY(2px); } }
    @keyframes speakingHead { from { transform: translateY(0) rotate(-.3deg); } to { transform: translateY(2px) rotate(.4deg); } }
    @keyframes blink { 0%, 46%, 49%, 100% { transform: scaleY(1); } 47.2%, 48% { transform: scaleY(.08); } }
    .wave { height: 34px; display: flex; align-items: center; gap: 4px; margin-top: -4px; opacity: .22; }
    .wave span { width: 4px; height: 9px; border-radius: 4px; background: #2874c7; }
    .assistant-pane.speaking .wave { opacity: 1; }
    .assistant-pane.speaking .wave span { animation: wave .55s ease-in-out infinite alternate; }
    .wave span:nth-child(2) { animation-delay: .08s !important; }
    .wave span:nth-child(3) { animation-delay: .16s !important; }
    .wave span:nth-child(4) { animation-delay: .24s !important; }
    .wave span:nth-child(5) { animation-delay: .32s !important; }
    @keyframes wave { from { height: 8px; } to { height: 30px; } }
    .speech-caption {
      width: 100%;
      min-height: 66px;
      margin-top: 8px;
      padding: 12px 14px;
      border-radius: 16px;
      color: #33445e;
      background: rgba(255,255,255,.9);
      border: 1px solid #d9e5f2;
      text-align: center;
      font-size: 16px;
      line-height: 1.4;
    }
    .main-pane { padding: 26px 34px 22px; min-width: 0; }
    header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
    h1 { font-size: clamp(30px, 4vw, 42px); line-height: 1.05; margin: 0 0 8px; letter-spacing: -.025em; }
    .sub { margin: 0; color: #64748b; font-size: 17px; }
    .status { display: inline-flex; align-items: center; gap: 8px; color: #12643a; background: #ecf8f0; border: 1px solid #caead5; border-radius: 999px; padding: 9px 13px; font-weight: 700; white-space: nowrap; }
    .dot { width: 9px; height: 9px; background: #26a269; border-radius: 50%; }
    .toolbar { display: flex; gap: 10px; flex-wrap: wrap; margin: 20px 0 18px; }
    .btn {
      min-height: 52px;
      border: 1px solid #cfd9e5;
      background: #fff;
      color: #1f3552;
      border-radius: 14px;
      padding: 0 18px;
      font-weight: 750;
      cursor: pointer;
      transition: transform .08s ease, box-shadow .15s ease, background .15s ease;
    }
    .btn:hover { box-shadow: 0 8px 22px rgba(24, 56, 93, .10); }
    .btn:active { transform: scale(.985); }
    .btn.primary { background: #1769bd; color: white; border-color: #1769bd; }
    .btn.soft { background: #f7f9fc; }
    .section-title { font-size: 22px; margin: 8px 0 12px; }
    .cards { display: grid; gap: 12px; }
    .card {
      background: white;
      border: 1px solid #d6e0eb;
      border-radius: 18px;
      padding: 18px 20px;
      box-shadow: 0 8px 25px rgba(28, 55, 87, .06);
    }
    .card.high, .card.critical { border-left: 5px solid #d18b28; padding-left: 17px; }
    .card h3 { margin: 0; font-size: 22px; }
    .meta { color: #66758a; margin-top: 4px; font-size: 14px; }
    .summary { margin: 8px 0 0; color: #34445b; font-size: 18px; line-height: 1.4; }
    .actions { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 15px; }
    .actions .btn { width: 100%; padding: 0 12px; }
    .empty { padding: 22px; border: 1px dashed #cbd7e5; border-radius: 16px; color: #617087; background: #fafcff; font-size: 17px; }
    .files { margin-top: 13px; display: grid; gap: 8px; }
    .file { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 8px; align-items: center; background: #f6f9fd; border: 1px solid #dce5ef; padding: 9px 10px; border-radius: 12px; }
    .file span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .file .btn { min-height: 44px; }
    .answer { display: none; margin: 0 0 14px; border-radius: 15px; padding: 13px 15px; background: #edf7ff; border: 1px solid #cce4f9; color: #244765; font-size: 17px; }
    .newsletter-line { margin-top: 16px; padding-top: 12px; border-top: 1px solid #e3e9f0; color: #738197; font-size: 14px; display: flex; justify-content: space-between; align-items: center; }
    .link-button { border: 0; background: transparent; color: #50677f; cursor: pointer; text-decoration: underline; padding: 8px; }
    .modal-backdrop { position: fixed; inset: 0; background: rgba(17, 28, 43, .45); display: none; align-items: center; justify-content: center; z-index: 50; padding: 20px; }
    .modal-backdrop.open { display: flex; }
    .modal { width: min(520px, 100%); background: white; border-radius: 20px; padding: 24px; box-shadow: 0 25px 70px rgba(12, 25, 43, .28); }
    .modal-step { color: #1769bd; font-weight: 800; margin-bottom: 6px; }
    .modal h2 { margin: 0 0 10px; font-size: 25px; }
    .modal p { color: #48596e; font-size: 18px; line-height: 1.45; }
    .modal-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 20px; }
    @media (max-width: 900px) {
      body { overflow: auto; }
      .app { grid-template-columns: 1fr; }
      .assistant-pane { min-height: 360px; border-right: 0; border-bottom: 1px solid #dbe4ef; }
      .avatar-wrap { width: 220px; }
      .main-pane { padding: 22px; }
    }
    @media (max-width: 620px) { .actions { grid-template-columns: 1fr; } header { flex-direction: column; } }
  </style>
</head>
<body>
<div class="app">
  <aside id="assistantPane" class="assistant-pane" aria-label="Assistante Jarvis">
    <div class="avatar-wrap" aria-hidden="true">
      <svg class="avatar" viewBox="0 0 300 350" role="img">
        <defs>
          <linearGradient id="skin" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f1c7aa"/><stop offset="1" stop-color="#e8b596"/></linearGradient>
          <linearGradient id="hair" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#51352d"/><stop offset="1" stop-color="#2f211f"/></linearGradient>
        </defs>
        <path d="M73 335c7-53 35-78 77-78s70 25 77 78" fill="#e9e2d9"/>
        <g class="head-group">
          <path d="M76 145c0-79 35-119 77-119 52 0 78 42 74 123l-12 74H87z" fill="url(#hair)"/>
          <ellipse cx="150" cy="155" rx="62" ry="82" fill="url(#skin)"/>
          <path d="M90 150c-7-70 22-112 65-112 31 0 58 21 69 62-27-8-48-27-60-48-15 28-39 52-74 64z" fill="url(#hair)"/>
          <path d="M94 144c-9 34-4 76 8 100-24-21-31-67-22-104zM207 126c12 39 8 86-8 115 26-21 34-72 22-113z" fill="url(#hair)"/>
          <path d="M116 142q15-9 29 0" stroke="#6a4438" stroke-width="4" fill="none" stroke-linecap="round"/>
          <path d="M157 142q15-9 29 0" stroke="#6a4438" stroke-width="4" fill="none" stroke-linecap="round"/>
          <g class="eye-lid"><ellipse cx="130" cy="157" rx="8" ry="6" fill="#fff"/><circle cx="131" cy="157" r="4.5" fill="#654739"/><circle cx="132" cy="156" r="1.3" fill="#fff"/></g>
          <g class="eye-lid"><ellipse cx="174" cy="157" rx="8" ry="6" fill="#fff"/><circle cx="173" cy="157" r="4.5" fill="#654739"/><circle cx="174" cy="156" r="1.3" fill="#fff"/></g>
          <path d="M150 164q-4 21 4 25" stroke="#ce9277" stroke-width="3" fill="none" stroke-linecap="round"/>
          <path d="M132 211q18 11 37 0" stroke="#a85457" stroke-width="4" fill="none" stroke-linecap="round"/>
          <ellipse class="mouth-open" cx="151" cy="215" rx="14" ry="6" fill="#8f3d46"/>
          <circle cx="91" cy="174" r="5" fill="#eee8df"/><circle cx="211" cy="174" r="5" fill="#eee8df"/>
        </g>
      </svg>
    </div>
    <div class="wave" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>
    <div id="speechCaption" class="speech-caption">Je suis prête. Je te parlerai seulement quand c’est utile.</div>
  </aside>

  <main class="main-pane">
    <header>
      <div>
        <h1>Bonjour __USER__</h1>
        <p class="sub">Je m’occupe du compliqué. Tu choisis simplement quoi faire.</p>
      </div>
      <div class="status"><span class="dot"></span> Jarvis est prêt</div>
    </header>

    <div class="toolbar">
      <button class="btn primary" onclick="dailyBrief()">Fais-moi le point</button>
      <button class="btn soft" onclick="startApp('thunderbird')">Thunderbird</button>
      <button class="btn soft" onclick="startApp('explorer')">Mes fichiers</button>
    </div>

    <div id="answer" class="answer"></div>
    <h2 class="section-title">À faire maintenant</h2>
    <div id="cards" class="cards"><div class="empty">Je regarde ce qui est important…</div></div>

    <div class="newsletter-line">
      <span id="newsletterText">0 newsletter rangée</span>
      <button class="link-button" onclick="sortNewsletters()">Ranger maintenant</button>
    </div>
  </main>
</div>

<div id="confirmModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="confirmTitle">
  <div class="modal">
    <div id="confirmStep" class="modal-step">Autorisation 1 sur 2</div>
    <h2 id="confirmTitle">Vérification</h2>
    <p id="confirmText"></p>
    <div class="modal-actions">
      <button id="confirmCancel" class="btn soft">Annuler</button>
      <button id="confirmOk" class="btn primary">Oui, continuer</button>
    </div>
  </div>
</div>

<script>
const cardsEl = document.getElementById('cards');
const answerEl = document.getElementById('answer');
const newsletterText = document.getElementById('newsletterText');
const assistantPane = document.getElementById('assistantPane');
const speechCaption = document.getElementById('speechCaption');
let lastVoiceEvent = 0;
let speakingTimer = null;

async function api(path, options={}) {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
  return response.json();
}

function showSpeaking(text, duration) {
  assistantPane.classList.add('speaking');
  speechCaption.textContent = text || 'Je te parle.';
  clearTimeout(speakingTimer);
  speakingTimer = setTimeout(() => {
    assistantPane.classList.remove('speaking');
    speechCaption.textContent = 'Je suis prête.';
  }, Math.max(1600, Number(duration || 2) * 1000));
}

async function pollVoiceEvents() {
  try {
    const data = await api(`/api/voice/events?after=${lastVoiceEvent}`);
    for (const event of data.events || []) {
      lastVoiceEvent = Math.max(lastVoiceEvent, Number(event.id || 0));
      showSpeaking(event.text, event.duration_estimate_seconds);
    }
  } catch (_) { /* the main app may still be starting */ }
}

function modalConfirm(step, actionText) {
  return new Promise(resolve => {
    const modal = document.getElementById('confirmModal');
    const stepEl = document.getElementById('confirmStep');
    const textEl = document.getElementById('confirmText');
    const ok = document.getElementById('confirmOk');
    const cancel = document.getElementById('confirmCancel');
    stepEl.textContent = `Autorisation ${step} sur 2`;
    textEl.textContent = step === 1
      ? `Jarvis va ${actionText}. Veux-tu continuer ?`
      : `Dernière vérification : autoriser Jarvis à ${actionText} ?`;
    ok.textContent = step === 1 ? 'Oui, continuer' : 'Oui, je confirme';
    modal.classList.add('open');
    const finish = value => {
      modal.classList.remove('open');
      ok.onclick = null;
      cancel.onclick = null;
      resolve(value);
    };
    ok.onclick = () => finish(true);
    cancel.onclick = () => finish(false);
  });
}

async function doubleConfirm(actionText) {
  if (!await modalConfirm(1, actionText)) return 0;
  if (!await modalConfirm(2, actionText)) return 0;
  return 2;
}

async function startApp(app) {
  await api('/api/desktop/start', {method: 'POST', body: JSON.stringify({app})});
}

async function dailyBrief() {
  answerEl.style.display = 'block';
  answerEl.textContent = 'Je regarde…';
  const result = await api('/api/assistant/ask', {
    method: 'POST',
    body: JSON.stringify({text: 'Dis-moi très simplement ce qui est important maintenant et ce que je dois faire.', speak: true})
  });
  answerEl.textContent = result.answer || 'Je ne peux pas faire le point pour le moment.';
}

function button(label, onClick, secondary=false) {
  const el = document.createElement('button');
  el.className = secondary ? 'btn soft' : 'btn primary';
  el.textContent = label;
  el.onclick = onClick;
  return el;
}

async function refreshNewsletters() {
  const data = await api('/api/newsletters');
  const count = Number(data.count || 0);
  newsletterText.textContent = `${count} newsletter${count > 1 ? 's' : ''} à ranger`;
}

async function sortNewsletters() {
  const data = await api('/api/newsletters');
  if (!data.count) {
    answerEl.style.display = 'block';
    answerEl.textContent = 'Aucune newsletter non importante à ranger.';
    return;
  }
  const confirmations = await doubleConfirm(`déplacer ${data.count} newsletter(s) dans le dossier Newsletters de Thunderbird`);
  if (confirmations !== 2) return;
  const result = await api('/api/newsletters/sort', {method: 'POST', body: JSON.stringify({confirmations})});
  answerEl.style.display = 'block';
  answerEl.textContent = result.ok ? `${result.count} newsletter(s) rangée(s).` : (result.reason || 'Tri non effectué.');
  await refreshNewsletters();
}

function renderFiles(container, files, card) {
  const area = document.createElement('div');
  area.className = 'files';
  if (!files.length) area.textContent = 'Je n’ai trouvé aucun document correspondant.';
  for (const file of files.slice(0, 4)) {
    const row = document.createElement('div');
    row.className = 'file';
    const name = document.createElement('span');
    name.textContent = file.name;
    row.appendChild(name);
    row.appendChild(button('Utiliser', async () => {
      const confirmations = await doubleConfirm(`préparer un brouillon avec « ${file.name} » en pièce jointe`);
      if (confirmations !== 2) return;
      const result = await api(`/api/actions/${card.id}/attach`, {method: 'POST', body: JSON.stringify({paths: [file.path], confirmations})});
      row.replaceChildren(document.createTextNode(result.ok ? 'Brouillon préparé. Rien n’a été envoyé.' : (result.reason || 'Action non effectuée.')));
    }));
    row.appendChild(button('Voir', async () => {
      await api('/api/files/open', {method: 'POST', body: JSON.stringify({path: file.path})});
    }, true));
    area.appendChild(row);
  }
  container.appendChild(area);
}

async function execute(card, option, cardElement) {
  let confirmations = 0;
  if (option.requires_confirmation) {
    confirmations = await doubleConfirm(`${option.label.toLowerCase()} pour « ${card.title} »`);
    if (confirmations !== 2) return;
  }
  const result = await api(`/api/actions/${card.id}/execute`, {method: 'POST', body: JSON.stringify({option_id: option.id, confirmations})});
  if (!result.ok && result.requires_confirmation) {
    answerEl.style.display = 'block';
    answerEl.textContent = result.reason || 'Deux confirmations sont obligatoires.';
    return;
  }
  if (result.results) renderFiles(cardElement, result.results, card);
  if (result.detail) {
    answerEl.style.display = 'block';
    answerEl.textContent = result.detail;
  }
}

async function refresh() {
  const cards = await api('/api/actions');
  cardsEl.replaceChildren();
  if (!cards.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'Rien d’important pour le moment.';
    cardsEl.appendChild(empty);
  } else {
    for (const card of cards.slice(0, 3)) {
      const el = document.createElement('section');
      el.className = `card ${card.importance || ''}`;
      const title = document.createElement('h3');
      title.textContent = card.title;
      el.appendChild(title);
      const meta = document.createElement('div');
      meta.className = 'meta';
      meta.textContent = card.source;
      el.appendChild(meta);
      const summary = document.createElement('p');
      summary.className = 'summary';
      summary.textContent = card.summary;
      el.appendChild(summary);
      const actions = document.createElement('div');
      actions.className = 'actions';
      for (const option of card.options.slice(0, 2)) {
        actions.appendChild(button(option.label, () => execute(card, option, el), option.id !== 'find-files'));
      }
      actions.appendChild(button('Plus tard', async () => {
        await api(`/api/actions/${card.id}`, {method: 'DELETE'});
        refresh();
      }, true));
      el.appendChild(actions);
      cardsEl.appendChild(el);
    }
  }
  await refreshNewsletters();
}

refresh();
pollVoiceEvents();
setInterval(refresh, 5000);
setInterval(pollVoiceEvents, 700);
</script>
</body>
</html>
"""


def dashboard_html() -> str:
    return _DASHBOARD.replace("__USER__", settings.user_name)
