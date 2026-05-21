const { makeWASocket, useMultiFileAuthState, DisconnectReason, Browsers, downloadMediaMessage } = require('@whiskeysockets/baileys');
const express = require('express');
const axios = require('axios');
const path = require('path');
const pino = require('pino');
const fs = require('fs');

const AUTH_DIR = path.join(__dirname, '..', '.store', 'auth');
const FLASK_WEBHOOK_URL = 'http://127.0.0.1:5000/api/webhook';
const PORT = 3000;

let sock = null;
let ownJid = null;
let ownLid = null;
const botSentMsgIds = new Set();

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

            const remoteJid = msg.key.remoteJid;
            console.log(`[DEBUG] Received message from remoteJid: ${remoteJid}, type: ${m.type}, fromMe: ${msg.key.fromMe}`);
            
            // Only process messages sent in the chat with oneself
            if (remoteJid !== ownJid && remoteJid !== ownLid) {
                continue;
            }

            // Prevent infinite loop by ignoring messages we just sent via the bot
            if (msg.key.id && botSentMsgIds.has(msg.key.id)) {
                continue;
            }

            // In personal chat, msg.key.fromMe might be true for messages we send,
            // or if we use WhatsApp Web, we can just treat the personal chat as the channel.
            
            // Extract text or audio
            let text = '';
            let audioBase64 = null;
            let imageBase64 = null;
            let mimeType = null;

            if (msg.message.conversation) {
                text = msg.message.conversation;
            } else if (msg.message.extendedTextMessage && msg.message.extendedTextMessage.text) {
                text = msg.message.extendedTextMessage.text;
            } else if (msg.message.audioMessage) {
                text = '[Áudio recebido, aguardando transcrição...]';
                mimeType = msg.message.audioMessage.mimetype || 'audio/ogg';
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
                    text = '[Erro ao baixar áudio recebido]';
                }
            } else if (msg.message.imageMessage) {
                text = msg.message.imageMessage.caption || '[Imagem recebida]';
                mimeType = msg.message.imageMessage.mimetype || 'image/jpeg';
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
                    text = '[Erro ao baixar imagem recebida]';
                }
            }

            if (!text) continue;

            // Generate a sender ID (just using the base number)
            const senderId = remoteJid.split('@')[0];

            console.log(`[Baileys Inbound] ${senderId}: ${text}`);

            try {
                const payload = {
                    channel_id: `wa_web:${senderId}`,
                    sender_id: senderId,
                    content: text
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

app.post('/send', async (req, res) => {
    if (!sock || !ownJid) {
        return res.status(503).json({ error: 'WhatsApp client is not ready' });
    }

    const { text, jid } = req.body;
    if (!text) {
        return res.status(400).json({ error: 'Missing text parameter' });
    }

    // Use provided jid or fallback to ownJid
    const targetJid = jid || ownJid;

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

    const targetJid = jid || ownJid;

    try {
        console.log(`[Baileys Outbound File] to ${targetJid}: ${file_path}`);
        const messagePayload = {
            document: { url: file_path },
            mimetype: mimetype || 'application/octet-stream',
            fileName: file_name || 'file'
        };
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
        res.status(500).json({ error: 'Failed to send file' });
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

    const targetJid = jid || ownJid;

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

    const targetJid = jid || ownJid;

    try {
        console.log(`[Baileys Presence] Sending ${state} to ${targetJid}`);
        await sock.presenceSubscribe(targetJid);
        await sock.sendPresenceUpdate(state, targetJid);
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
