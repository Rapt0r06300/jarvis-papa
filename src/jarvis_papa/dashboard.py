from jarvis_papa.config import settings


_DASHBOARD = r"""
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Jarvis</title>
  <style>
    :root { font-family: "Segoe UI", system-ui, sans-serif; color: #172338; background: #f3f6fa; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: #f3f6fa; }
    button { font: inherit; }
    button:focus-visible, a:focus-visible { outline: 4px solid #79b9ff; outline-offset: 3px; }
    .app { min-height: 100vh; display: grid; grid-template-columns: minmax(270px, 32%) 1fr; max-width: 1500px; margin: auto; background: white; }
    .assistant-pane { position: relative; padding: 22px; display: flex; flex-direction: column; align-items: center; justify-content: center; background: linear-gradient(180deg,#edf5ff,#fbfdff 62%,#fff); border-right: 1px solid #dbe4ef; overflow: hidden; }
    .avatar-wrap { width: min(310px, 88%); }
    .avatar { width: 100%; display: block; filter: drop-shadow(0 18px 30px rgba(35,77,125,.13)); }
    .avatar .head-group { transform-origin: 150px 155px; animation: breathe 4.8s ease-in-out infinite; }
    .avatar .eye-lid { transform-origin: center; animation: blink 5.7s infinite; }
    .avatar .mouth-open { transform-origin: 150px 221px; transform: scaleY(.12); }
    .assistant-pane.speaking .avatar .mouth-open { animation: talk .20s ease-in-out infinite alternate; }
    .assistant-pane.speaking .avatar .head-group { animation: speakingHead 1.2s ease-in-out infinite alternate; }
    @keyframes talk { from { transform: scaleY(.18); } to { transform: scaleY(1.08); } }
    @keyframes breathe { 0%,100% { transform: translateY(0); } 50% { transform: translateY(2px); } }
    @keyframes speakingHead { from { transform: translateY(0) rotate(-.25deg); } to { transform: translateY(2px) rotate(.35deg); } }
    @keyframes blink { 0%,46%,49%,100% { transform: scaleY(1); } 47.2%,48% { transform: scaleY(.08); } }
    .wave { height: 32px; display: flex; align-items: center; gap: 4px; opacity: .2; }
    .wave span { width: 4px; height: 8px; border-radius: 4px; background: #2874c7; }
    .assistant-pane.speaking .wave { opacity: 1; }
    .assistant-pane.speaking .wave span { animation: wave .5s ease-in-out infinite alternate; }
    .wave span:nth-child(2) { animation-delay: .08s; } .wave span:nth-child(3) { animation-delay: .16s; }
    .wave span:nth-child(4) { animation-delay: .24s; } .wave span:nth-child(5) { animation-delay: .32s; }
    @keyframes wave { from { height: 7px; } to { height: 28px; } }
    .speech-caption { width: 100%; min-height: 64px; padding: 12px 14px; border-radius: 16px; color: #33445e; background: rgba(255,255,255,.94); border: 1px solid #d9e5f2; text-align: center; font-size: 17px; line-height: 1.4; }
    .main-pane { padding: 26px 34px 22px; min-width: 0; }
    header { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; }
    h1 { font-size: clamp(31px,4vw,42px); margin: 0 0 6px; letter-spacing: -.025em; }
    .sub { margin: 0; color: #64748b; font-size: 17px; }
    .status { display: inline-flex; align-items: center; gap: 8px; color: #12643a; background: #ecf8f0; border: 1px solid #caead5; border-radius: 999px; padding: 9px 13px; font-weight: 750; white-space: nowrap; }
    .dot { width: 9px; height: 9px; background: #26a269; border-radius: 50%; }
    .toolbar { display: flex; gap: 10px; flex-wrap: wrap; margin: 19px 0 17px; }
    .btn { min-height: 52px; border: 1px solid #cbd7e4; background: white; color: #1d3552; border-radius: 14px; padding: 0 18px; font-weight: 760; cursor: pointer; transition: transform .08s ease,box-shadow .15s ease; }
    .btn:hover { box-shadow: 0 7px 20px rgba(24,56,93,.10); } .btn:active { transform: scale(.985); }
    .btn.primary { background: #1769bd; color: white; border-color: #1769bd; }
    .btn.soft { background: #f7f9fc; }
    .section-title { font-size: 22px; margin: 8px 0 12px; }
    .cards { display: grid; gap: 12px; }
    .card { background: white; border: 1px solid #d6e0eb; border-radius: 18px; padding: 18px 20px; box-shadow: 0 8px 25px rgba(28,55,87,.06); }
    .card.high { border-left: 5px solid #d18b28; padding-left: 17px; } .card.critical { border-left: 5px solid #bd3f4c; padding-left: 17px; }
    .card h3 { margin: 0; font-size: 22px; } .meta { color: #66758a; margin-top: 4px; font-size: 14px; }
    .summary { margin: 8px 0 0; color: #34445b; font-size: 18px; line-height: 1.4; }
    .recommendation { margin: 8px 0 0; color: #244c70; font-size: 15px; font-weight: 650; }
    .deadline { display: inline-block; margin-top: 8px; border-radius: 999px; background: #fff4df; color: #82530d; padding: 5px 9px; font-size: 14px; font-weight: 700; }
    .actions { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 10px; margin-top: 14px; }
    .actions .btn { width: 100%; padding: 0 10px; }
    .empty { padding: 22px; border: 1px dashed #cbd7e5; border-radius: 16px; color: #617087; background: #fafcff; font-size: 17px; }
    .files { margin-top: 13px; display: grid; gap: 8px; }
    .file { display: grid; grid-template-columns: minmax(0,1fr) auto auto; gap: 8px; align-items: center; background: #f6f9fd; border: 1px solid #dce5ef; padding: 9px 10px; border-radius: 12px; }
    .file span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .file .btn { min-height: 44px; }
    .answer { display: none; margin: 0 0 14px; border-radius: 15px; padding: 13px 15px; background: #edf7ff; border: 1px solid #cce4f9; color: #244765; font-size: 17px; }
    .newsletter-line { margin-top: 15px; padding-top: 12px; border-top: 1px solid #e3e9f0; color: #738197; font-size: 14px; display: flex; justify-content: space-between; align-items: center; }
    .link-button { border: 0; background: transparent; color: #50677f; cursor: pointer; text-decoration: underline; padding: 9px; }
    .modal-backdrop { position: fixed; inset: 0; background: rgba(17,28,43,.48); display: none; align-items: center; justify-content: center; z-index: 50; padding: 20px; }
    .modal-backdrop.open { display: flex; } .modal { width: min(530px,100%); background: white; border-radius: 20px; padding: 24px; box-shadow: 0 25px 70px rgba(12,25,43,.28); }
    .modal-step { color: #1769bd; font-weight: 800; margin-bottom: 6px; } .modal h2 { margin: 0 0 10px; font-size: 25px; } .modal p { color: #48596e; font-size: 18px; line-height: 1.45; }
    .modal-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 20px; }
    @media (max-width:900px) { .app { grid-template-columns: 1fr; } .assistant-pane { min-height: 340px; border-right: 0; border-bottom: 1px solid #dbe4ef; } .avatar-wrap { width: 210px; } .main-pane { padding: 22px; } }
    @media (max-width:620px) { .actions { grid-template-columns: 1fr; } header { flex-direction: column; } }
    @media (prefers-reduced-motion: reduce) { *,*::before,*::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; } }
  </style>
</head>
<body>
<div class="app">
  <aside id="assistantPane" class="assistant-pane" aria-label="Assistante Jarvis">
    <div class="avatar-wrap" aria-hidden="true">
      <svg class="avatar" viewBox="0 0 300 350" role="img">
        <defs><linearGradient id="skin" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f1c7aa"/><stop offset="1" stop-color="#e8b596"/></linearGradient><linearGradient id="hair" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#51352d"/><stop offset="1" stop-color="#2f211f"/></linearGradient></defs>
        <path d="M73 335c7-53 35-78 77-78s70 25 77 78" fill="#e9e2d9"/>
        <g class="head-group"><path d="M76 145c0-79 35-119 77-119 52 0 78 42 74 123l-12 74H87z" fill="url(#hair)"/><ellipse cx="150" cy="155" rx="62" ry="82" fill="url(#skin)"/><path d="M90 150c-7-70 22-112 65-112 31 0 58 21 69 62-27-8-48-27-60-48-15 28-39 52-74 64z" fill="url(#hair)"/><path d="M94 144c-9 34-4 76 8 100-24-21-31-67-22-104zM207 126c12 39 8 86-8 115 26-21 34-72 22-113z" fill="url(#hair)"/><path d="M116 142q15-9 29 0" stroke="#6a4438" stroke-width="4" fill="none" stroke-linecap="round"/><path d="M157 142q15-9 29 0" stroke="#6a4438" stroke-width="4" fill="none" stroke-linecap="round"/><g class="eye-lid"><ellipse cx="130" cy="157" rx="8" ry="6" fill="#fff"/><circle cx="131" cy="157" r="4.5" fill="#654739"/><circle cx="132" cy="156" r="1.3" fill="#fff"/></g><g class="eye-lid"><ellipse cx="174" cy="157" rx="8" ry="6" fill="#fff"/><circle cx="173" cy="157" r="4.5" fill="#654739"/><circle cx="174" cy="156" r="1.3" fill="#fff"/></g><path d="M150 164q-4 21 4 25" stroke="#ce9277" stroke-width="3" fill="none" stroke-linecap="round"/><path d="M132 211q18 11 37 0" stroke="#a85457" stroke-width="4" fill="none" stroke-linecap="round"/><ellipse class="mouth-open" cx="151" cy="215" rx="14" ry="6" fill="#8f3d46"/></g>
      </svg>
    </div>
    <div class="wave" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>
    <div id="speechCaption" class="speech-caption" aria-live="polite">Je suis prête. Je te parlerai seulement quand c’est utile.</div>
  </aside>
  <main class="main-pane">
    <header><div><h1>Bonjour __USER__</h1><p class="sub">Je m’occupe du compliqué. Tu choisis simplement quoi faire.</p></div><div class="status"><span class="dot"></span> Jarvis est prêt</div></header>
    <div class="toolbar"><button class="btn primary" onclick="dailyBrief()">Fais-moi le point</button><button class="btn soft" onclick="startApp('thunderbird')">Thunderbird</button><button class="btn soft" onclick="startApp('explorer')">Mes fichiers</button></div>
    <div id="answer" class="answer" aria-live="polite"></div>
    <h2 class="section-title">À faire maintenant</h2>
    <div id="cards" class="cards"><div class="empty">Je regarde ce qui est important…</div></div>
    <div class="newsletter-line"><span id="newsletterText">0 newsletter à ranger</span><button class="link-button" onclick="sortNewsletters()">Ranger maintenant</button></div>
  </main>
</div>
<div id="confirmModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="confirmTitle">
  <div class="modal"><div id="confirmStep" class="modal-step">Autorisation 1 sur 2</div><h2 id="confirmTitle">Vérification</h2><p id="confirmText"></p><div class="modal-actions"><button id="confirmCancel" class="btn soft">Annuler</button><button id="confirmOk" class="btn primary">Oui, continuer</button></div></div>
</div>
<script>
const cardsEl=document.getElementById('cards');const answerEl=document.getElementById('answer');const newsletterText=document.getElementById('newsletterText');const assistantPane=document.getElementById('assistantPane');const speechCaption=document.getElementById('speechCaption');let lastVoiceEvent=0;let speakingTimer=null;let interactionBusy=false;
async function api(path,options={}){const response=await fetch(path,{headers:{'Content-Type':'application/json'},...options});const data=await response.json();if(!response.ok)throw new Error(data.detail||'Erreur Jarvis');return data;}
function showAnswer(text){answerEl.style.display='block';answerEl.textContent=text;}
function showSpeaking(text,duration){assistantPane.classList.add('speaking');speechCaption.textContent=text||'Je te parle.';clearTimeout(speakingTimer);speakingTimer=setTimeout(()=>{assistantPane.classList.remove('speaking');speechCaption.textContent='Je suis prête.';},Math.max(1600,Number(duration||2)*1000));}
async function pollVoiceEvents(){try{const data=await api(`/api/voice/events?after=${lastVoiceEvent}`);for(const event of data.events||[]){lastVoiceEvent=Math.max(lastVoiceEvent,Number(event.id||0));showSpeaking(event.text,event.duration_estimate_seconds);}}catch(_){} }
async function speakConfirmation(text){try{await api('/api/speech/event',{method:'POST',body:JSON.stringify({text,importance:'normal',user_initiated:true,sensitive:true})});}catch(_){} }
function modalConfirm(step,actionText){return new Promise(resolve=>{interactionBusy=true;const modal=document.getElementById('confirmModal');const stepEl=document.getElementById('confirmStep');const textEl=document.getElementById('confirmText');const ok=document.getElementById('confirmOk');const cancel=document.getElementById('confirmCancel');stepEl.textContent=`Autorisation ${step} sur 2`;textEl.textContent=step===1?`Jarvis va ${actionText}. Veux-tu continuer ?`:`Dernière vérification : autoriser Jarvis à ${actionText} ?`;ok.textContent=step===1?'Oui, continuer':'Oui, je confirme';modal.classList.add('open');setTimeout(()=>ok.focus(),30);speakConfirmation(textEl.textContent);const finish=value=>{modal.classList.remove('open');interactionBusy=false;ok.onclick=null;cancel.onclick=null;resolve(value);};ok.onclick=()=>finish(true);cancel.onclick=()=>finish(false);});}
async function authorize(actionKey,actionText){const started=await api('/api/confirmations/start',{method:'POST',body:JSON.stringify({action_key:actionKey,description:actionText})});if(!started.ok||!started.challenge_id)return null;if(!await modalConfirm(1,actionText))return null;const first=await api(`/api/confirmations/${started.challenge_id}/confirm`,{method:'POST',body:'{}'});if(!first.ok||first.step!==1)return null;if(!await modalConfirm(2,actionText))return null;const second=await api(`/api/confirmations/${started.challenge_id}/confirm`,{method:'POST',body:'{}'});return second.completed?second.authorization_token:null;}
async function startApp(app){try{await api('/api/desktop/start',{method:'POST',body:JSON.stringify({app})});}catch(error){showAnswer(error.message);}}
async function dailyBrief(){showAnswer('Je regarde…');try{const result=await api('/api/assistant/ask',{method:'POST',body:JSON.stringify({text:'Dis-moi très simplement ce qui est important maintenant et ce que je dois faire.',speak:true})});showAnswer(result.answer||'Rien à signaler.');}catch(error){showAnswer(error.message);}}
function button(label,onClick,secondary=false){const el=document.createElement('button');el.className=secondary?'btn soft':'btn primary';el.textContent=label;el.onclick=onClick;return el;}
async function refreshNewsletters(){const data=await api('/api/newsletters');const count=Number(data.count||0);newsletterText.textContent=`${count} newsletter${count>1?'s':''} à ranger`;return data;}
async function sortNewsletters(){try{const data=await refreshNewsletters();if(!data.count){showAnswer('Aucune newsletter non importante à ranger.');return;}const token=await authorize('mail.sort_newsletters',`déplacer ${data.count} newsletter(s) dans le dossier Newsletters de Thunderbird`);if(!token)return;const result=await api('/api/newsletters/sort',{method:'POST',body:JSON.stringify({authorization_token:token})});showAnswer(result.detail||'Tri demandé.');if(result.command_id)await waitForCommand(result.command_id);await refreshNewsletters();}catch(error){showAnswer(error.message);}}
async function waitForCommand(commandId){for(let i=0;i<12;i++){await new Promise(resolve=>setTimeout(resolve,650));const history=await api('/api/thunderbird/history');const command=(history||[]).find(item=>item.id===commandId);if(!command)continue;if(command.status==='succeeded'){showAnswer(command.kind==='prepare_reply'?'Le brouillon est prêt dans Thunderbird. Rien n’a été envoyé.':'Thunderbird confirme que l’action a réussi.');return true;}if(command.status==='failed'){showAnswer(`Thunderbird n’a pas pu terminer : ${command.error||'erreur inconnue'}`);return false;}}showAnswer('La demande a été transmise à Thunderbird. J’attends encore sa confirmation.');return null;}
function renderFiles(container,files,card){container.querySelector('.files')?.remove();const area=document.createElement('div');area.className='files';if(!files.length)area.textContent='Je n’ai trouvé aucun document correspondant.';for(const file of files.slice(0,4)){const row=document.createElement('div');row.className='file';const name=document.createElement('span');name.textContent=file.name;row.appendChild(name);row.appendChild(button('Utiliser',async()=>{try{const token=await authorize('mail.prepare_reply_attachment',`préparer un brouillon avec « ${file.name} » en pièce jointe`);if(!token)return;const result=await api(`/api/actions/${card.id}/attach`,{method:'POST',body:JSON.stringify({paths:[file.path],authorization_token:token})});showAnswer(result.detail||'Préparation demandée.');if(result.command_id)await waitForCommand(result.command_id);}catch(error){showAnswer(error.message);}}));row.appendChild(button('Voir',async()=>{try{await api('/api/files/open',{method:'POST',body:JSON.stringify({path:file.path})});}catch(error){showAnswer(error.message);}},true));area.appendChild(row);}container.appendChild(area);}
async function execute(card,option,cardElement){try{let token='';if(option.requires_confirmation){token=await authorize('mail.prepare_reply',`${option.label.toLowerCase()} pour « ${card.title} »`);if(!token)return;}const result=await api(`/api/actions/${card.id}/execute`,{method:'POST',body:JSON.stringify({option_id:option.id,authorization_token:token})});if(result.results)renderFiles(cardElement,result.results,card);if(result.detail)showAnswer(result.detail);if(result.command_id&&option.requires_confirmation)await waitForCommand(result.command_id);}catch(error){showAnswer(error.message);}}
async function snooze(card){try{const token=await authorize('actions.snooze',`remettre « ${card.title} » à plus tard pendant quatre heures`);if(!token)return;const result=await api(`/api/actions/${card.id}/snooze`,{method:'POST',body:JSON.stringify({hours:4,authorization_token:token})});showAnswer(result.detail||'Je te le remontrerai plus tard.');await refresh();}catch(error){showAnswer(error.message);}}
async function refresh(){if(interactionBusy||cardsEl.querySelector('.files'))return;try{const cards=await api('/api/actions');cardsEl.replaceChildren();if(!cards.length){const empty=document.createElement('div');empty.className='empty';empty.textContent='Rien d’important pour le moment.';cardsEl.appendChild(empty);}else{for(const card of cards.slice(0,3)){const el=document.createElement('section');el.className=`card ${card.importance||''}`;const title=document.createElement('h3');title.textContent=card.title;el.appendChild(title);const meta=document.createElement('div');meta.className='meta';meta.textContent=card.source;el.appendChild(meta);const summary=document.createElement('p');summary.className='summary';summary.textContent=card.summary;el.appendChild(summary);const deadline=card.metadata&&card.metadata.deadline_text;if(deadline){const badge=document.createElement('div');badge.className='deadline';badge.textContent=`Échéance : ${deadline}`;el.appendChild(badge);}const recommendation=card.metadata&&card.metadata.recommended_action;if(recommendation){const rec=document.createElement('p');rec.className='recommendation';rec.textContent=`Jarvis conseille : ${recommendation}`;el.appendChild(rec);}const actions=document.createElement('div');actions.className='actions';for(const option of (card.options||[]).slice(0,2))actions.appendChild(button(option.label,()=>execute(card,option,el),option.id!=='find-files'));actions.appendChild(button('Plus tard',()=>snooze(card),true));el.appendChild(actions);cardsEl.appendChild(el);}}await refreshNewsletters();}catch(error){showAnswer(`Jarvis rencontre un problème : ${error.message}`);}}
refresh();pollVoiceEvents();setInterval(()=>{if(!document.hidden)refresh();},15000);setInterval(pollVoiceEvents,800);
</script>
</body>
</html>
"""


def dashboard_html() -> str:
    return _DASHBOARD.replace("__USER__", settings.user_name)
