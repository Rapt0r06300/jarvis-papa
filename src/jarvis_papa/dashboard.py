from jarvis_papa.config import settings


def dashboard_html() -> str:
    return f"""
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis Papa</title>
  <style>
    :root {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; color-scheme: dark; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #0b1020; color: #f5f7ff; min-height: 100vh; }}
    main {{ width: min(920px, calc(100% - 28px)); margin: 32px auto 70px; }}
    .status {{ display: inline-flex; gap: 9px; align-items: center; padding: 9px 13px; border-radius: 999px; background: #172a23; color: #aef0c8; font-weight: 700; }}
    .dot {{ width: 9px; height: 9px; border-radius: 50%; background: #62db91; }}
    h1 {{ margin: 14px 0 4px; font-size: clamp(38px, 7vw, 66px); }}
    h2 {{ margin-top: 34px; }}
    p {{ color: #b9c2df; line-height: 1.55; }}
    .quick {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-top: 22px; }}
    button {{ border: 0; border-radius: 15px; padding: 15px 18px; font: inherit; font-weight: 750; cursor: pointer; background: #e9eeff; color: #10162a; }}
    button.secondary {{ background: #1c2745; color: #edf1ff; border: 1px solid #344164; }}
    .cards {{ display: grid; gap: 14px; }}
    .card {{ background: #141b31; border: 1px solid #293352; border-radius: 20px; padding: 20px; }}
    .card.high, .card.critical {{ border-color: #876735; }}
    .meta {{ color: #91a0ca; font-size: 14px; }}
    .summary {{ color: #d8def1; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 9px; margin-top: 15px; }}
    .empty {{ padding: 22px; border: 1px dashed #344164; border-radius: 18px; color: #91a0ca; }}
    .files {{ margin-top: 14px; display: grid; gap: 8px; }}
    .file {{ padding: 11px; background: #0f1528; border-radius: 12px; display: flex; gap: 10px; align-items: center; }}
    .file span {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }}
    .answer {{ margin-top: 18px; background: #172a23; border-radius: 16px; padding: 16px; color: #dff8e8; display: none; }}
  </style>
</head>
<body>
<main>
  <div class="status"><span class="dot"></span> Jarvis est prêt</div>
  <h1>Bonjour {settings.user_name}</h1>
  <p>Jarvis te montre seulement l'important. Rien n'est modifié sans deux confirmations.</p>

  <div class="quick">
    <button onclick="dailyBrief()">Fais-moi le point</button>
    <button class="secondary" onclick="startApp('thunderbird')">Ouvrir Thunderbird</button>
    <button class="secondary" onclick="startApp('explorer')">Ouvrir mes fichiers</button>
    <button id="newsletterButton" class="secondary" onclick="sortNewsletters()">Newsletters : 0</button>
  </div>
  <div id="answer" class="answer"></div>

  <h2>Ce qui demande ton attention</h2>
  <div id="cards" class="cards"><div class="empty">Chargement…</div></div>
</main>
<script>
const cardsEl = document.getElementById('cards');
const answerEl = document.getElementById('answer');
const newsletterButton = document.getElementById('newsletterButton');

async function api(path, options={{}}) {{
  const response = await fetch(path, {{headers: {{'Content-Type': 'application/json'}}, ...options}});
  return response.json();
}}

async function doubleConfirm(actionText) {{
  const first = window.confirm(`Autorisation 1 sur 2\n\nJarvis va ${{actionText}}.\n\nContinuer ?`);
  if (!first) return 0;
  const second = window.confirm(`Autorisation 2 sur 2\n\nConfirmation finale : autoriser Jarvis à ${{actionText}} ?`);
  return second ? 2 : 0;
}}

async function startApp(app) {{
  await api('/api/desktop/start', {{method: 'POST', body: JSON.stringify({{app}})}});
}}

async function dailyBrief() {{
  answerEl.style.display = 'block';
  answerEl.textContent = 'Je regarde…';
  const result = await api('/api/assistant/ask', {{
    method: 'POST',
    body: JSON.stringify({{text: 'Dis-moi très simplement ce qui est important maintenant et ce que je dois faire.', speak: true}})
  }});
  answerEl.textContent = result.answer || 'Je ne peux pas faire le point pour le moment.';
}}

function button(label, onClick, secondary=false) {{
  const el = document.createElement('button');
  el.textContent = label;
  if (secondary) el.classList.add('secondary');
  el.onclick = onClick;
  return el;
}}

async function refreshNewsletters() {{
  const data = await api('/api/newsletters');
  newsletterButton.textContent = `Newsletters : ${{data.count || 0}}`;
}}

async function sortNewsletters() {{
  const data = await api('/api/newsletters');
  if (!data.count) {{
    answerEl.style.display = 'block';
    answerEl.textContent = 'Aucune newsletter non importante à ranger.';
    return;
  }}
  const confirmations = await doubleConfirm(`déplacer ${{data.count}} newsletter(s) dans le dossier Newsletters de Thunderbird`);
  if (confirmations !== 2) return;
  const result = await api('/api/newsletters/sort', {{method: 'POST', body: JSON.stringify({{confirmations}})}});
  answerEl.style.display = 'block';
  answerEl.textContent = result.ok ? `${{result.count}} newsletter(s) rangée(s).` : (result.reason || 'Tri non effectué.');
  await refreshNewsletters();
}}

function renderFiles(container, files, card) {{
  const area = document.createElement('div');
  area.className = 'files';
  if (!files.length) area.textContent = 'Je n’ai trouvé aucun document correspondant.';
  for (const file of files) {{
    const row = document.createElement('div');
    row.className = 'file';
    const name = document.createElement('span');
    name.textContent = file.name;
    row.appendChild(name);
    row.appendChild(button('Utiliser', async () => {{
      const confirmations = await doubleConfirm(`préparer un brouillon avec « ${{file.name}} » en pièce jointe`);
      if (confirmations !== 2) return;
      const result = await api(`/api/actions/${{card.id}}/attach`, {{method: 'POST', body: JSON.stringify({{paths: [file.path], confirmations}})}});
      row.replaceChildren(document.createTextNode(result.ok ? 'Brouillon préparé. Rien n’a été envoyé.' : (result.reason || 'Action non effectuée.')));
    }}));
    row.appendChild(button('Ouvrir', async () => {{
      await api('/api/files/open', {{method: 'POST', body: JSON.stringify({{path: file.path}})}});
    }}, true));
    area.appendChild(row);
  }}
  container.appendChild(area);
}}

async function execute(card, option, cardElement) {{
  let confirmations = 0;
  if (option.requires_confirmation) {{
    confirmations = await doubleConfirm(`${{option.label.toLowerCase()}} pour « ${{card.title}} »`);
    if (confirmations !== 2) return;
  }}
  const result = await api(`/api/actions/${{card.id}}/execute`, {{method: 'POST', body: JSON.stringify({{option_id: option.id, confirmations}})}});
  if (!result.ok && result.requires_confirmation) {{
    answerEl.style.display = 'block';
    answerEl.textContent = result.reason || 'Deux confirmations sont obligatoires.';
    return;
  }}
  if (result.results) renderFiles(cardElement, result.results, card);
  if (result.detail) {{
    answerEl.style.display = 'block';
    answerEl.textContent = result.detail;
  }}
}}

async function refresh() {{
  const cards = await api('/api/actions');
  cardsEl.replaceChildren();
  if (!cards.length) {{
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'Rien d’important pour le moment.';
    cardsEl.appendChild(empty);
  }} else {{
    for (const card of cards) {{
      const el = document.createElement('section');
      el.className = `card ${{card.importance || ''}}`;
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
      for (const option of card.options) {{
        actions.appendChild(button(option.label, () => execute(card, option, el), option.id !== 'find-files'));
      }}
      actions.appendChild(button('Plus tard', async () => {{
        await api(`/api/actions/${{card.id}}`, {{method: 'DELETE'}});
        refresh();
      }}, true));
      el.appendChild(actions);
      cardsEl.appendChild(el);
    }}
  }}
  await refreshNewsletters();
}}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""
