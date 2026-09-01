from __future__ import annotations

from jarvis_papa.dashboard import dashboard_html as _legacy_dashboard_html


_SECURITY_PATCH = r"""
<script>
async function authorize(actionKey, actionText, binding = {}) {
  const started = await api('/api/confirmations/start', {
    method: 'POST',
    body: JSON.stringify({action_key: actionKey, description: actionText, binding})
  });
  if (!started || !started.challenge_id) {
    showAnswer('Je ne peux pas démarrer la double autorisation. Rien ne sera modifié.');
    return '';
  }
  const first = await confirmationModal(1, actionText);
  if (!first) return '';
  const stepOne = await api(`/api/confirmations/${started.challenge_id}/confirm`, {
    method: 'POST', body: '{}'
  });
  if (!stepOne || !stepOne.ok) {
    showAnswer("La première autorisation n'a pas été enregistrée. Rien ne sera modifié.");
    return '';
  }
  const second = await confirmationModal(2, actionText);
  if (!second) return '';
  const stepTwo = await api(`/api/confirmations/${started.challenge_id}/confirm`, {
    method: 'POST', body: '{}'
  });
  if (!stepTwo || !stepTwo.completed || !stepTwo.authorization_token) {
    showAnswer("La double autorisation n'a pas abouti. Rien ne sera modifié.");
    return '';
  }
  return stepTwo.authorization_token;
}

async function waitForVerifiedCommand(commandId, attempts = 40) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const command = await api(`/api/thunderbird/commands/${commandId}`);
    if (command && command.status === 'succeeded') return command;
    if (command && command.status === 'failed') return command;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  return null;
}

async function sendPrepared(card, option) {
  const payload = option && option.payload && typeof option.payload === 'object' ? option.payload : {};
  const draftCommandId = String(payload.draft_command_id || '');
  if (!draftCommandId) {
    showAnswer("Je ne retrouve pas le brouillon préparé. Rien n'est envoyé.");
    return;
  }
  showAnswer("Je vérifie le brouillon exact dans Thunderbird avant de demander l'autorisation d'envoi.");
  const inspect = await api(`/api/advanced/mail/${card.id}/send/inspect`, {
    method: 'POST',
    body: JSON.stringify({draft_command_id: draftCommandId})
  });
  if (!inspect || !inspect.ok || !inspect.command_id) {
    showAnswer((inspect && inspect.detail) || "Je n'ai pas pu vérifier le brouillon. Rien n'est envoyé.");
    return;
  }
  const inspected = await waitForVerifiedCommand(inspect.command_id, 30);
  if (!inspected || inspected.status !== 'succeeded') {
    showAnswer("Thunderbird n'a pas confirmé le contenu du brouillon. Rien n'est envoyé.");
    return;
  }
  const plan = await api(`/api/advanced/mail/${card.id}/send/plan/${inspect.command_id}`);
  if (!plan || !plan.ok) {
    showAnswer((plan && plan.detail) || "Le brouillon n'est pas vérifiable. Rien n'est envoyé.");
    return;
  }
  const binding = plan.binding && typeof plan.binding === 'object' ? plan.binding : {};
  const token = await authorize(
    String(plan.action_key || 'mail.send_reply'),
    String(plan.description || 'Envoyer ce brouillon.'),
    binding
  );
  if (!token) return;
  const requested = await api(`/api/advanced/mail/${card.id}/send`, {
    method: 'POST',
    body: JSON.stringify({inspect_command_id: inspect.command_id, authorization_token: token})
  });
  if (!requested || !requested.ok || !requested.command_id) {
    showAnswer((requested && requested.detail) || "L'envoi a été bloqué.");
    return;
  }
  const sent = await waitForVerifiedCommand(requested.command_id, 40);
  const proof = sent && sent.result && typeof sent.result === 'object' ? sent.result : {};
  if (!sent || sent.status !== 'succeeded' || proof.verified !== true || proof.mode !== 'sendNow') {
    showAnswer("Je n'ai pas reçu une preuve suffisante d'envoi. Je ne considère pas le mail comme envoyé.");
    return;
  }
  showAnswer('Thunderbird a confirmé que le mail a bien été envoyé.');
  await refresh();
}

async function sortNewsletters() {
  const data = await api('/api/newsletters');
  const items = data && Array.isArray(data.items) ? data.items : [];
  const cardIds = items.map(item => String(item.id || '')).filter(Boolean);
  if (!data || Number(data.count || 0) <= 0) {
    showAnswer("Il n'y a aucune newsletter à ranger.");
    return;
  }
  if (cardIds.length !== Number(data.count || 0)) {
    showAnswer("La liste des newsletters vient de changer. Je n'y touche pas et je la rafraîchis.");
    await refresh();
    return;
  }
  const token = await authorize(
    'mail.sort_newsletters',
    'Déplacer les newsletters détectées dans le dossier Newsletters de Thunderbird.',
    {card_ids: cardIds}
  );
  if (!token) return;
  const result = await api('/api/newsletters/sort', {
    method: 'POST', body: JSON.stringify({authorization_token: token})
  });
  showAnswer((result && result.detail) || 'Le rangement a été demandé à Thunderbird.');
  if (result && result.command_id) await waitForCommand(result.command_id);
  await refresh();
}

function renderFiles(card, items) {
  filesBox.innerHTML = '';
  if (!items || !items.length) return;
  const title = document.createElement('div');
  title.className = 'files-title';
  title.textContent = 'Documents trouvés';
  filesBox.appendChild(title);
  items.slice(0, 4).forEach(file => {
    const row = document.createElement('div');
    row.className = 'file-row';
    const name = document.createElement('div');
    name.textContent = file.name || file.path;
    const open = button('Ouvrir', 'secondary', async () => {
      await api('/api/files/open', {method:'POST', body:JSON.stringify({path:file.path})});
    });
    const attach = button('Joindre au brouillon', 'primary', async () => {
      const paths = [file.path];
      const token = await authorize(
        'mail.prepare_reply_attachment',
        `Préparer un brouillon avec le document « ${file.name || file.path} ».`,
        {card_id: card.id, paths}
      );
      if (!token) return;
      const result = await api(`/api/actions/${card.id}/attach`, {
        method:'POST', body:JSON.stringify({paths, authorization_token:token})
      });
      showAnswer((result && result.detail) || 'Le brouillon avec pièce jointe a été demandé.');
      if (result && result.command_id) await waitForCommand(result.command_id);
      await refresh();
    });
    row.append(name, open, attach);
    filesBox.appendChild(row);
  });
}

async function execute(card, option, target) {
  if (String(option.id || '') === 'send-prepared') {
    if (target) target.disabled = true;
    try { await sendPrepared(card, option); }
    finally { if (target) target.disabled = false; }
    return;
  }
  if (target) target.disabled = true;
  try {
    let token = '';
    if (option.requires_confirmation) {
      token = await authorize(
        'mail.prepare_reply',
        'Préparer un brouillon dans Thunderbird. Aucun mail ne sera envoyé.',
        {card_id: card.id, option_id: option.id}
      );
      if (!token) return;
    }
    const result = await api(`/api/actions/${card.id}/execute`, {
      method:'POST',
      body:JSON.stringify({option_id:option.id, authorization_token:token})
    });
    if (!result || !result.ok) {
      showAnswer((result && (result.detail || result.reason)) || "L'action a été bloquée.");
      return;
    }
    if (result.kind === 'search_files') renderFiles(card, result.results || []);
    showAnswer(result.detail || 'Étape terminée.');
    if (result.command_id) await waitForCommand(result.command_id);
    await refresh();
  } finally {
    if (target) target.disabled = false;
  }
}

async function snooze(card) {
  const hours = 4;
  const token = await authorize(
    'actions.snooze',
    'Reporter cette tâche de quatre heures. Elle réapparaîtra automatiquement.',
    {card_id: card.id, hours}
  );
  if (!token) return;
  const result = await api(`/api/actions/${card.id}/snooze`, {
    method:'POST', body:JSON.stringify({hours, authorization_token:token})
  });
  showAnswer((result && result.detail) || 'Je te la reproposerai plus tard.');
  await refresh();
}
</script>
"""


def dashboard_html() -> str:
    """Keep the legacy browser preview safe without weakening server-side bindings."""

    html = _legacy_dashboard_html()
    marker = "</body>"
    if marker not in html:
        return html + _SECURITY_PATCH
    return html.replace(marker, f"{_SECURITY_PATCH}\n{marker}", 1)
