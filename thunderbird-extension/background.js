const HOST_NAME = "fr.jarvis_papa.host";

let nativePort = null;
let reconnectTimer = null;

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
    for (const message of current.messages || []) {
      yield message;
    }
    if (!current.id) break;
    current = await messenger.messages.continueList(current.id);
  }
}

function collectText(part, output = []) {
  if (!part) return output;
  const contentType = (part.contentType || "").toLowerCase();
  if (contentType.startsWith("text/plain") && typeof part.body === "string") {
    output.push(part.body);
  }
  for (const child of part.parts || []) {
    collectText(child, output);
  }
  return output;
}

async function pushNewMail(folder, message) {
  if (!nativePort) return;
  try {
    const full = await messenger.messages.getFull(message.id, {decodeContent: true});
    const body = collectText(full).join("\n\n").trim();
    nativePort.postMessage({
      type: "new_mail",
      mail: {
        message_id: message.id,
        header_message_id: message.headerMessageId || null,
        author: message.author || "",
        subject: message.subject || "",
        body,
        folder: folder.name || "Inbox"
      }
    });
  } catch (error) {
    console.error("Jarvis could not read incoming mail", error);
  }
}

messenger.messages.onNewMailReceived.addListener(async (folder, page) => {
  for await (const message of iterateMessagePages(page)) {
    await pushNewMail(folder, message);
  }
});

async function resolveMessageId(payload) {
  if (Number.isInteger(payload.message_id)) {
    return payload.message_id;
  }
  if (payload.header_message_id) {
    const page = await messenger.messages.query({
      headerMessageId: payload.header_message_id
    });
    const message = (page.messages || [])[0];
    if (message) return message.id;
  }
  throw new Error("Message Thunderbird introuvable");
}

async function addLocalAttachments(tabId, attachments) {
  for (const attachment of attachments || []) {
    const response = await fetch(attachment.url, {cache: "no-store"});
    if (!response.ok) {
      throw new Error(`Pièce jointe Jarvis inaccessible: ${attachment.name || "fichier"}`);
    }
    const data = await response.arrayBuffer();
    const file = new File(
      [data],
      attachment.name || "document",
      {type: attachment.media_type || "application/octet-stream"}
    );
    await messenger.compose.addAttachment(tabId, {
      file,
      name: attachment.name || file.name
    });
  }
}

async function getOrCreateNewslettersFolder(accountId) {
  const existing = await messenger.folders.query({
    accountId,
    name: "Newsletters"
  });
  if (existing.length) {
    return existing[0];
  }

  const account = await messenger.accounts.get(accountId);
  if (!account || !account.rootFolder) {
    throw new Error("Compte Thunderbird introuvable pour ranger les newsletters");
  }
  return messenger.folders.create(account.rootFolder.id, "Newsletters");
}

async function sortNewsletters(items) {
  const grouped = new Map();

  for (const item of items || []) {
    const messageId = await resolveMessageId(item);
    const message = await messenger.messages.get(messageId);
    const accountId = message.folder && message.folder.accountId;
    if (!accountId) {
      continue;
    }
    if (!grouped.has(accountId)) {
      grouped.set(accountId, []);
    }
    grouped.get(accountId).push(messageId);
  }

  for (const [accountId, messageIds] of grouped.entries()) {
    if (!messageIds.length) continue;
    const folder = await getOrCreateNewslettersFolder(accountId);
    await messenger.messages.move(messageIds, folder.id, {isUserAction: true});
  }
}

async function handleCommand(command) {
  const payload = command.payload || {};

  if (command.kind === "open_message") {
    if (payload.header_message_id) {
      await messenger.messageDisplay.open({headerMessageId: payload.header_message_id});
    } else {
      const messageId = await resolveMessageId(payload);
      await messenger.messageDisplay.open({messageId});
    }
    return;
  }

  if (command.kind === "prepare_reply") {
    const messageId = await resolveMessageId(payload);
    const tab = await messenger.compose.beginReply(messageId, "replyToSender", {
      plainTextBody: payload.body || ""
    });
    await addLocalAttachments(tab.id, payload.attachments || []);
    return;
  }

  if (command.kind === "sort_newsletters") {
    await sortNewsletters(payload.items || []);
    return;
  }

  throw new Error(`Commande Jarvis inconnue: ${command.kind}`);
}

async function handleNativeMessage(message) {
  if (!message || message.type !== "command" || !message.command) {
    return;
  }

  const command = message.command;
  let ok = true;
  let error = null;
  try {
    await handleCommand(command);
  } catch (cause) {
    ok = false;
    error = String(cause);
    console.error("Jarvis Thunderbird command failed", cause);
  }

  if (nativePort) {
    nativePort.postMessage({
      type: "command_ack",
      command_id: command.id,
      ok,
      error
    });
  }
}

connectNativeHost();
