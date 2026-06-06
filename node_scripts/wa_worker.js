const { makeWASocket, useMultiFileAuthState, DisconnectReason, Browsers, downloadMediaMessage } = require('@whiskeysockets/baileys');
const express = require('express');
const axios = require('axios');
const path = require('path');
const pino = require('pino');
const fs = require('fs');

const AUTH_DIR = path.join(__dirname, '..', '.store', 'auth');
const FLASK_PORT = process.env.FLASK_PORT || 5000;
const FLASK_WEBHOOK_URL = `http://127.0.0.1:${FLASK_PORT}/api/webhook`;
const PORT = 3000;

let sock = null;
let ownJid = null;
let ownLid = null;
const botSentMsgIds = new Set();
const typingIntervals = {};
const typingTimeouts = {};

function ensureJidSuffix(jid) {
    if (!jid) return jid;
    if (jid.includes('@')) return jid;
    if (jid.includes('-') || jid.startsWith('120363')) {
        return `${jid}@g.us`;
    }
    return `${jid}@s.whatsapp.net`;
}

function clearTyping(jid) {
    if (typingIntervals[jid]) {
        clearInterval(typingIntervals[jid]);
        delete typingIntervals[jid];
    }
    if (typingTimeouts[jid]) {
        clearTimeout(typingTimeouts[jid]);
        delete typingTimeouts[jid];
    }
}

let currentAgentName = null;
let workerNames = [];
let allowMentions = true;
let allowAudioMentions = false;
let requireAtPrefix = true;
let lastAgentNameFetch = 0;

async function getAgentName() {
    const now = Date.now();
    if (now - lastAgentNameFetch > 60000) {
        try {
            const res = await axios.get(`http://127.0.0.1:${FLASK_PORT}/api/config/agent_name`);
            if (res.data) {
                currentAgentName = res.data.agent_name ? res.data.agent_name.toLowerCase() : null;
                workerNames = res.data.worker_names ? res.data.worker_names.map(name => name.toLowerCase()) : [];
                allowMentions = res.data.allow_mentions !== false;
                allowAudioMentions = res.data.allow_audio_mentions === true;
                requireAtPrefix = res.data.require_at_prefix !== false;
            }
        } catch (e) {
            // ignore
        }
        lastAgentNameFetch = now;
    }
    const names = workerNames.length > 0 ? workerNames : (currentAgentName ? [currentAgentName] : []);
    return { name: currentAgentName, workerNames: names, allowMentions: allowMentions, allowAudioMentions: allowAudioMentions, requireAtPrefix: requireAtPrefix };
}

// --- Modular Message Parsing Helpers ---
function extractMessageContent(msg) {
    if (!msg.message) return null;
    let content = msg.message;
    if (content?.ephemeralMessage?.message) return content.ephemeralMessage.message;
    if (content?.viewOnceMessage?.message) return content.viewOnceMessage.message;
    if (content?.documentWithCaptionMessage?.message) return content.documentWithCaptionMessage.message;
    if (content?.viewOnceMessageV2?.message) return content.viewOnceMessageV2.message;
    return content;
}

function getMessageType(msgContent) {
    if (!msgContent) return 'unknown';
    if (msgContent.audioMessage) return 'audio';
    if (msgContent.imageMessage) return 'image';
    if (msgContent.videoMessage) return 'video';
    if (msgContent.documentMessage) return 'document';
    if (msgContent.conversation || (msgContent.extendedTextMessage && msgContent.extendedTextMessage.text)) return 'text';
    return 'other';
}

function extractTextContent(msgContent) {
    if (!msgContent) return '';
    if (msgContent.conversation) return msgContent.conversation;
    if (msgContent.extendedTextMessage?.text) return msgContent.extendedTextMessage.text;
    if (msgContent.imageMessage?.caption) return msgContent.imageMessage.caption;
    if (msgContent.videoMessage?.caption) return msgContent.videoMessage.caption;
    if (msgContent.documentMessage?.caption) return msgContent.documentMessage.caption;
    return '';
}

function isGroupChat(remoteJid) {
    if (!remoteJid) return false;
    return remoteJid.includes('-') || remoteJid.startsWith('120363');
}

function isNoteToSelf(remoteJid, ownJid, ownLid) {
    return remoteJid === ownJid || remoteJid === ownLid;
}

function checkMentions(text, agentConfig) {
    if (!text || !agentConfig.allowMentions || !agentConfig.workerNames || agentConfig.workerNames.length === 0) {
        return false;
    }
    const textLower = text.toLowerCase().trim();
    for (const name of agentConfig.workerNames) {
        const nameClean = name.trim();
        const nameNoSpaces = nameClean.replace(/\s+/g, '');
        if (textLower.startsWith(`@${nameClean}`) || textLower.startsWith(`@${nameNoSpaces}`)) {
            return true;
        }
        if (!agentConfig.requireAtPrefix) {
            if (textLower.startsWith(nameClean) || textLower.startsWith(nameNoSpaces)) {
                return true;
            }
        }
    }
    return false;
}

function shouldForwardMessage(context, agentConfig) {
    // A única exceção: chat com si mesmo
    if (context.isSelf) {
        return true;
    }
    
    // Se possui menção, passa (texto já tem a menção)
    if (context.hasMention) {
        return true;
    }
    
    // Se for áudio, permitimos o envio para o backend caso configurado,
    // para que a transcrição avalie a menção do lado de lá.
    if (context.isAudio && agentConfig.allowAudioMentions) {
        return true;
    }
    
    return false;
}
// ----------------------------------------

async function connectToWhatsApp() {
    const logger = pino({ level: 'silent' });
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

    sock = makeWASocket({
        auth: state,
        printQRInTerminal: false,
        logger: logger,
        browser: Browsers.macOS('Chrome')
    });

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect } = update;

        if (connection === 'close') {
            const statusCode = (lastDisconnect.error)?.output?.statusCode;
            
            // 440 / 409 indicate a session conflict (another instance using the same credentials)
            if (statusCode === 440 || statusCode === 409) {
                console.error(`❌ Session conflict detected (status ${statusCode}). Another instance is likely running.`);
                console.error('Terminating this orphaned instance to resolve the conflict.');
                process.exit(1);
            }
            
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            console.log('WhatsApp connection closed. Reconnecting:', shouldReconnect, 'Reason:', statusCode, lastDisconnect.error?.message);
            if (shouldReconnect) {
                setTimeout(connectToWhatsApp, 2000);
            }
        } else if (connection === 'open') {
            console.log('✅ WhatsApp Worker connected successfully!');
            // Extract the user's own JID and LID base
            if (sock.user) {
                if (sock.user.id) {
                    const userNumber = sock.user.id.split(':')[0];
                    ownJid = `${userNumber}@s.whatsapp.net`;
                }
                if (sock.user.lid) {
                    const lidNumber = sock.user.lid.split(':')[0];
                    ownLid = `${lidNumber}@lid`;
                }
                console.log(`📡 Monitoring exclusively for own number: ${ownJid} / ${ownLid}`);
            }
        }
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('messages.upsert', async (m) => {
        // Messages sent by the user on their phone to themselves might come as 'append' instead of 'notify'
        if (m.type !== 'notify' && m.type !== 'append') return;
        
        for (const msg of m.messages) {
            if (!msg.message) continue;

            const msgContent = extractMessageContent(msg);
            if (!msgContent) continue;

            const remoteJid = msg.key.remoteJid;
            console.log(`[DEBUG] Received message from remoteJid: ${remoteJid}, type: ${m.type}, fromMe: ${msg.key.fromMe}`);
            
            // Ignore messages older than 10 minutes (600 seconds)
            const now = Math.floor(Date.now() / 1000);
            const msgTimestamp = msg.messageTimestamp;
            if (msgTimestamp && (now - msgTimestamp > 600)) {
                console.log(`[DEBUG] Ignored old message from ${remoteJid} (age: ${now - msgTimestamp}s)`);
                continue;
            }

            // Prevent infinite loop by ignoring messages we just sent via the bot
            if (msg.key.id && botSentMsgIds.has(msg.key.id)) {
                continue;
            }

            const agentConfig = await getAgentName();
            const textContent = extractTextContent(msgContent);
            const msgType = getMessageType(msgContent);
            
            const context = {
                isGroup: isGroupChat(remoteJid),
                isSelf: isNoteToSelf(remoteJid, ownJid, ownLid),
                isAudio: msgType === 'audio',
                hasMention: checkMentions(textContent, agentConfig)
            };

            if (!shouldForwardMessage(context, agentConfig)) {
                continue;
            }

            // In personal chat, msg.key.fromMe might be true for messages we send,
            // or if we use WhatsApp Web, we can just treat the personal chat as the channel.
            
            // Extract text or audio
            let text = '';
            let audioBase64 = null;
            let imageBase64 = null;
            let mimeType = null;

            if (msgContent.conversation) {
                text = msgContent.conversation;
            } else if (msgContent.extendedTextMessage && msgContent.extendedTextMessage.text) {
                text = msgContent.extendedTextMessage.text;
            } else if (msgContent.audioMessage) {
                text = '[Audio received, waiting for transcription...]';
                mimeType = msgContent.audioMessage.mimetype || 'audio/ogg';
                try {
                    const buffer = await downloadMediaMessage(
                        msg,
                        'buffer',
                        { },
                        { 
                            logger: pino({ level: 'silent' }),
                            reuploadRequest: sock.updateMediaMessage
                        }
                    );
                    audioBase64 = buffer.toString('base64');
                    console.log(`[Baileys Inbound] Audio downloaded, size: ${buffer.length} bytes`);
                } catch (err) {
                    console.error('Failed to download audio:', err.message);
                    text = '[Error downloading received audio]';
                }
            } else if (msgContent.imageMessage) {
                text = msgContent.imageMessage.caption || '[Image received]';
                mimeType = msgContent.imageMessage.mimetype || 'image/jpeg';
                try {
                    const buffer = await downloadMediaMessage(
                        msg,
                        'buffer',
                        { },
                        { 
                            logger: pino({ level: 'silent' }),
                            reuploadRequest: sock.updateMediaMessage
                        }
                    );
                    imageBase64 = buffer.toString('base64');
                    console.log(`[Baileys Inbound] Image downloaded, size: ${buffer.length} bytes`);
                } catch (err) {
                    console.error('Failed to download image:', err.message);
                    text = '[Error downloading received image]';
                }
            }

            if (!text) continue;

            // Use remoteJid as the base channel ID, but extract actual participant if available (e.g. for groups)
            const channelIdBase = remoteJid.split('@')[0];
            let actualSenderJid = msg.key.participant || msg.key.remoteJid;
            if (msg.key.fromMe && ownJid) {
                actualSenderJid = ownJid;
            }
            const senderId = actualSenderJid.split('@')[0];

            console.log(`[Baileys Inbound] ${senderId} (in ${channelIdBase}): ${text}`);

            try {
                const payload = {
                    channel_id: `wa_web:${channelIdBase}`,
                    sender_id: senderId,
                    sender_name: msg.pushName || '',
                    sender_jid: actualSenderJid,
                    remote_jid: remoteJid,
                    content: text,
                    message_id: msg.key.id
                };
                if (audioBase64) {
                    payload.audio_base64 = audioBase64;
                    payload.mimetype = mimeType;
                }
                if (imageBase64) {
                    payload.image_base64 = imageBase64;
                    payload.mimetype = mimeType;
                }
                await axios.post(FLASK_WEBHOOK_URL, payload);
            } catch (err) {
                console.error('Failed to forward message to Flask:', err.message);
            }
        }
    });
}

// Set up the Express server for outbound messages
const app = express();
app.use(express.json());

app.get('/me', (req, res) => {
    if (!sock || !ownJid) {
        return res.status(503).json({ error: 'WhatsApp client is not ready' });
    }
    const number = ownJid.split('@')[0];
    const lid_number = ownLid ? ownLid.split('@')[0] : null;
    res.json({ number: number, jid: ownJid, lid_number: lid_number, lid: ownLid });
});

app.post('/send', async (req, res) => {
    if (!sock || !ownJid) {
        return res.status(503).json({ error: 'WhatsApp client is not ready' });
    }

    const { text, jid } = req.body;
    if (!text) {
        return res.status(400).json({ error: 'Missing text parameter' });
    }

    // Use provided jid or fallback to ownJid
    const targetJid = ensureJidSuffix(jid || ownJid);

    clearTyping(targetJid);

    try {
        console.log(`[Baileys Outbound] to ${targetJid}: ${text}`);
        const sentMsg = await sock.sendMessage(targetJid, { text: text });
        if (sentMsg && sentMsg.key && sentMsg.key.id) {
            botSentMsgIds.add(sentMsg.key.id);
            // Optional: prevent the Set from growing indefinitely
            if (botSentMsgIds.size > 1000) botSentMsgIds.clear();
        }
        res.json({ status: 'sent', target: targetJid });
    } catch (err) {
        console.error('Failed to send message via Baileys:', err);
        res.status(500).json({ error: 'Failed to send message' });
    }
});

app.post('/send_file', async (req, res) => {
    if (!sock || !ownJid) {
        return res.status(503).json({ error: 'WhatsApp client is not ready' });
    }

    const { file_path, mimetype, file_name, caption, jid } = req.body;
    if (!file_path) {
        return res.status(400).json({ error: 'Missing file_path parameter' });
    }

    const targetJid = ensureJidSuffix(jid || ownJid);

    clearTyping(targetJid);

    try {
        console.log(`[Baileys Outbound File] to ${targetJid}: ${file_path}`);
        
        const fileBuffer = await fs.promises.readFile(file_path);
        let messagePayload = {};
        
        if (mimetype && mimetype.startsWith('image/')) {
            messagePayload = {
                image: fileBuffer,
                mimetype: mimetype,
                fileName: file_name || 'image'
            };
        } else if (mimetype && mimetype.startsWith('video/')) {
            messagePayload = {
                video: fileBuffer,
                mimetype: mimetype,
                fileName: file_name || 'video'
            };
        } else {
            messagePayload = {
                document: fileBuffer,
                mimetype: mimetype || 'application/octet-stream',
                fileName: file_name || 'file'
            };
        }

        if (caption) {
            messagePayload.caption = caption;
        }

        const sentMsg = await sock.sendMessage(targetJid, messagePayload);
        if (sentMsg && sentMsg.key && sentMsg.key.id) {
            botSentMsgIds.add(sentMsg.key.id);
            if (botSentMsgIds.size > 1000) botSentMsgIds.clear();
        }
        res.json({ status: 'sent', target: targetJid });
    } catch (err) {
        console.error('Failed to send file via Baileys:', err);
        res.status(500).json({ error: 'Failed to send file', details: err.message || err.toString() });
    }
});

app.post('/send_audio', async (req, res) => {
    if (!sock || !ownJid) {
        return res.status(503).json({ error: 'WhatsApp client is not ready' });
    }

    const { file_path, jid } = req.body;
    if (!file_path) {
        return res.status(400).json({ error: 'Missing file_path parameter' });
    }

    const targetJid = ensureJidSuffix(jid || ownJid);

    clearTyping(targetJid);

    try {
        console.log(`[Baileys Outbound Audio] to ${targetJid}: ${file_path}`);
        const messagePayload = {
            audio: { url: file_path },
            mimetype: 'audio/ogg; codecs=opus', // Correct mimetype for ogg/opus PTT
            ptt: true
        };

        const sentMsg = await sock.sendMessage(targetJid, messagePayload);
        if (sentMsg && sentMsg.key && sentMsg.key.id) {
            botSentMsgIds.add(sentMsg.key.id);
            if (botSentMsgIds.size > 1000) botSentMsgIds.clear();
        }
        
        try {
            fs.unlinkSync(file_path);
        } catch(e) {
            console.error(`Failed to delete temp audio file: ${file_path}`, e);
        }

        res.json({ status: 'sent', target: targetJid });
    } catch (err) {
        console.error('Failed to send audio via Baileys:', err);
        res.status(500).json({ error: 'Failed to send audio' });
    }
});

app.post('/presence', async (req, res) => {
    if (!sock || !ownJid) {
        return res.status(503).json({ error: 'WhatsApp client is not ready' });
    }

    const { state, jid } = req.body;
    if (!state) {
        return res.status(400).json({ error: 'Missing state parameter' });
    }

    const targetJid = ensureJidSuffix(jid || ownJid);

    try {
        console.log(`[Baileys Presence] Sending ${state} to ${targetJid}`);
        
        if (state === 'composing' || state === 'recording') {
            clearTyping(targetJid);
            
            const sendUpdate = async () => {
                try {
                    await sock.presenceSubscribe(targetJid);
                    await sock.sendPresenceUpdate(state, targetJid);
                } catch (e) {
                    console.error('Interval presence error:', e.message);
                }
            };
            
            await sendUpdate();
            typingIntervals[targetJid] = setInterval(sendUpdate, 10000);
            typingTimeouts[targetJid] = setTimeout(() => {
                clearTyping(targetJid);
            }, 3 * 60 * 1000);
        } else {
            clearTyping(targetJid);
            await sock.presenceSubscribe(targetJid);
            await sock.sendPresenceUpdate(state, targetJid);
        }

        res.json({ status: 'sent', target: targetJid, state: state });
    } catch (err) {
        console.error('Failed to send presence via Baileys:', err);
        res.status(500).json({ error: 'Failed to send presence' });
    }
});

app.listen(PORT, () => {
    console.log(`🚀 Baileys Outbound Bridge listening on port ${PORT}`);
});

connectToWhatsApp();
