const HOST_NAME = "fr.jarvis_papa.host";
const COMPLETED_KEY = "jarvisCompletedCommands";

let nativePort = null;
let reconnectTimer = null;
let completedCommands = new Map();

async function loadCompletedCommands() {
  try {
    const stored = await messenger.storage.local.get(COMPLETED_KEY);
    const values = stored && stored[COMPLETED_KEY];
    if (!Array.isArray(values)) return;
    const entries = [];
    for (const value of values) {
      if (typeof value === "string") entries.push([value, {verified: false}]);
      else if (value && typeof value === "object" && typeof value.id === "string") {
        entries.push([value.id, value.result && typeof value.result === "object" ? value.result : {}]);
      }
    }
    completedCommands = new Map(entries.slice(-120));
  } catch (error) {
    console.error("Jarvis could not load command history", error);
  }
}

async function rememberCompletedCommand(commandId, result = {}) {
  completedCommands.set(commandId, result);
  const values = Array.from(completedCommands.entries()).slice(-120).map(([id, storedResult]) => ({id, result: storedResult}));
  completedCommands = new Map(values.map(item => [item.id, item.result]));
  try {
    await messenger.storage.local.set({[COMPLETED_KEY]: values});
  } catch (error) {
    console.error("Jarvis could not save command history", error);
  }
}

function connectNativeHost() {
  try {
    nativePort = messenger.runtime.connectNative(HOST_NAME);
    nativePort.onMessage.addListener(handleNativeMessage);
    nativePort.onDisconnect.addListener(() => {
      nativePort = null;
      if (!reconnectTimer) {
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          connectNativeHost();
        }, 5000);
      }
    });
    nativePort.postMessage({type: "ping"});
  } catch (error) {
    console.error("Jarvis native host unavailable", error);
  }
}

async function* iterateMessagePages(page) {
  let current = page;
  while (current) {
    for (const message of current.messages || []) yield message;
    if (!current.id) break;
    current = await messenger.messages.continueList(current.id);
  }
}

function htmlToText(html) {
  if (!html) return "";
  try {
    const document = new DOMParser().parseFromString(html, "text/html");
    return (document && document.body && document.body.innerText) || "";
  } catch (_) {
    return String(html).replace(/<style[\s\S]*?<\/style>/gi, " ")
      .replace(/<script[\s\S]*?<\/script>/gi, " ")
      .replace(/<[^>]+>/g, " ");
  }
}

function collectText(part, output = []) {
  if (!part) return output;
  const contentType = (part.contentType || "").toLowerCase();
  if (contentType.startsWith("text/plain") && typeof part.body === "string") {
    output.push(part.body);
  } else if (contentType.startsWith("text/html") && typeof part.body === "string" && output.length === 0) {
    const text = htmlToText(part.body).trim();
    if (text) output.push(text);
  }
  for (const child of part.parts || []) collectText(child, output);
  return output;
}

function headerPresent(headers, name) {
  if (!headers || typeof headers !== "object") return false;
  const value = headers[name] || headers[name.toLowerCase()] || headers[name.toUpperCase()];
  if (Array.isArray(value)) return value.some(item => String(item || "").trim());
  return Boolean(String(value || "").trim());
}

async function pushNewMail(folder, message) {
  if (!nativePort) return;
  try {
    const full = await messenger.messages.getFull(message.id, {decodeContent: true});
    const body = collectText(full).join("\n\n").replace(/\s+/g, " ").trim().slice(0, 50000);
    const date = message.date instanceof Date ? message.date.toISOString() : (message.date ? String(message.date) : null);
    nativePort.postMessage({
      type: "new_mail",
      mail: {
        message_id: message.id,
        header_message_id: message.headerMessageId || null,
        author: message.author || "",
        subject: message.subject || "",
        body,
        folder: folder.name || "Inbox",
        list_unsubscribe: headerPresent(full.headers, "list-unsubscribe"),
        junk: Boolean(message.junk),
        date
      }
    });
  } catch (error) {
    console.error("Jarvis could not read incoming mail", error);
  }
}

messenger.messages.onNewMailReceived.addListener(async (folder, page) => {
  for await (const message of iterateMessagePages(page)) await pushNewMail(folder, message);
});

async function resolveMessageId(payload) {
  if (Number.isInteger(payload.message_id)) return payload.message_id;
  if (payload.header_message_id) {
    const page = await messenger.messages.query({headerMessageId: payload.header_message_id});
    const message = (page.messages || [])[0];
    if (message) return message.id;
  }
  throw new Error("Message Thunderbird introuvable");
}

async function addLocalAttachments(tabId, attachments) {
  for (const attachment of attachments || []) {
    const response = await fetch(attachment.url, {cache: "no-store", credentials: "omit"});
    if (!response.ok) throw new Error(`Pièce jointe Jarvis inaccessible: ${attachment.name || "fichier"}`);
    const data = await response.arrayBuffer();
    const file = new File([data], attachment.name || "document", {type: attachment.media_type || "application/octet-stream"});
    await messenger.compose.addAttachment(tabId, {file, name: attachment.name || file.name});
  }
}

async function getOrCreateNewslettersFolder(accountId) {
  const existing = await messenger.folders.query({accountId, name: "Newsletters"});
  if (existing.length) return existing[0];
  const account = await messenger.accounts.get(accountId);
  if (!account || !account.rootFolder) throw new Error("Compte Thunderbird introuvable pour ranger les newsletters");
  return messenger.folders.create(account.rootFolder.id, "Newsletters");
}

async function sortNewsletters(items) {
  const grouped = new Map();
  for (const item of items || []) {
    const messageId = await resolveMessageId(item);
    const message = await messenger.messages.get(messageId);
    const accountId = message.folder && message.folder.accountId;
    if (!accountId) continue;
    if (!grouped.has(accountId)) grouped.set(accountId, []);
    grouped.get(accountId).push(messageId);
  }
  for (const [accountId, messageIds] of grouped.entries()) {
    if (!messageIds.length) continue;
    const folder = await getOrCreateNewslettersFolder(accountId);
    await messenger.messages.move(messageIds, folder.id, {isUserAction: true});
  }
}

async function inspectAccounts() {
  const accounts = await messenger.accounts.list();
  let mailAccountCount = 0;
  let folderAccessibleCount = 0;
  for (const account of accounts || []) {
    const type = String(account.type || "").toLowerCase();
    if (type === "imap" || type === "pop3" || type === "pop") mailAccountCount += 1;
    if (account.rootFolder) folderAccessibleCount += 1;
  }
  return {
    verified: true,
    account_count: Array.isArray(accounts) ? accounts.length : 0,
    mail_account_count: mailAccountCount,
    folder_accessible_count: folderAccessibleCount
  };
}

function recipientText(value) {
  if (typeof value === "string") return value.trim();
  if (!value || typeof value !== "object") return String(value || "").trim();
  return String(value.email || value.address || value.name || "").trim();
}

function recipientList(values) {
  return (Array.isArray(values) ? values : []).map(recipientText).filter(Boolean);
}

async function sha256Hex(text) {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest)).map(byte => byte.toString(16).padStart(2, "0")).join("");
}

async function composeSnapshot(tabId) {
  const details = await messenger.compose.getComposeDetails(tabId);
  const attachments = await messenger.compose.listAttachments(tabId);
  const to = recipientList(details.to);
  const cc = recipientList(details.cc);
  const bcc = recipientList(details.bcc);
  const snapshot = {
    to,
    cc,
    bcc,
    subject: String(details.subject || ""),
    body: details.isPlainText ? String(details.plainTextBody || "") : String(details.body || ""),
    is_plain_text: Boolean(details.isPlainText),
    attachments: (attachments || []).map(item => ({
      name: String(item.name || ""),
      size: Number(item.size || 0)
    })).sort((left, right) => `${left.name}:${left.size}`.localeCompare(`${right.name}:${right.size}`))
  };
  const composeDigest = await sha256Hex(JSON.stringify(snapshot));
  return {
    snapshot,
    result: {
      compose_tab_id: tabId,
      compose_digest: composeDigest,
      recipient_display: to.join(", ") || cc.join(", ") || "destinataire du brouillon",
      subject: snapshot.subject,
      attachment_names: snapshot.attachments.map(item => item.name).filter(Boolean),
      verified: true
    }
  };
}

async function handleCommand(command) {
  const payload = command.payload || {};
  if (command.kind === "open_message") {
    if (payload.header_message_id) await messenger.messageDisplay.open({headerMessageId: payload.header_message_id});
    else await messenger.messageDisplay.open({messageId: await resolveMessageId(payload)});
    return {verified: true};
  }
  if (command.kind === "prepare_reply") {
    const messageId = await resolveMessageId(payload);
    const tab = await messenger.compose.beginReply(messageId, "replyToSender", {plainTextBody: payload.body || ""});
    await addLocalAttachments(tab.id, payload.attachments || []);
    return {compose_tab_id: tab.id, verified: true};
  }
  if (command.kind === "inspect_compose") {
    const tabId = Number(payload.compose_tab_id || 0);
    if (!Number.isInteger(tabId) || tabId <= 0) throw new Error("Brouillon Thunderbird introuvable");
    return (await composeSnapshot(tabId)).result;
  }
  if (command.kind === "inspect_accounts") {
    return inspectAccounts();
  }
  if (command.kind === "send_reply") {
    const tabId = Number(payload.compose_tab_id || 0);
    const expectedDigest = String(payload.expected_compose_digest || "");
    if (!Number.isInteger(tabId) || tabId <= 0 || !expectedDigest) throw new Error("Preuve d'envoi Jarvis incomplète");
    const current = await composeSnapshot(tabId);
    if (current.result.compose_digest !== expectedDigest) {
      throw new Error("Le brouillon a changé depuis les autorisations. Jarvis refuse l'envoi : vérifie puis confirme à nouveau.");
    }
    const sent = await messenger.compose.sendMessage(tabId, {mode: "sendNow"});
    const verified = sent && sent.mode === "sendNow" && Boolean(sent.headerMessageId);
    if (!verified) throw new Error("Thunderbird n'a pas confirmé l'envoi immédiat du mail");
    return {
      mode: sent.mode,
      header_message_id: sent.headerMessageId,
      sent_copy_count: Array.isArray(sent.messages) ? sent.messages.length : 0,
      compose_tab_id: tabId,
      verified: true
    };
  }
  if (command.kind === "sort_newsletters") {
    await sortNewsletters(payload.items || []);
    return {verified: true};
  }
  throw new Error(`Commande Jarvis inconnue: ${command.kind}`);
}

async function handleNativeMessage(message) {
  if (!message || message.type !== "command" || !message.command) return;
  const command = message.command;
  if (completedCommands.has(command.id)) {
    const result = {...(completedCommands.get(command.id) || {}), duplicate: true};
    if (nativePort) nativePort.postMessage({type: "command_ack", command_id: command.id, ok: true, result, error: null});
    return;
  }

  let ok = true;
  let error = null;
  let result = {};
  try {
    result = await handleCommand(command) || {};
    await rememberCompletedCommand(command.id, result);
  } catch (cause) {
    ok = false;
    error = String(cause).slice(0, 1200);
    console.error("Jarvis Thunderbird command failed", cause);
  }
  if (nativePort) nativePort.postMessage({type: "command_ack", command_id: command.id, ok, result, error});
}

loadCompletedCommands().finally(connectNativeHost);
