const { makeWASocket, useMultiFileAuthState, DisconnectReason, Browsers } = require('@whiskeysockets/baileys');
const pino = require('pino');
const path = require('path');

const AUTH_DIR = path.join(__dirname, '..', '.store', 'auth');

async function connectToWhatsApp() {
    // Suppress logs by setting level to silent so we only print our JSON messages to stdout
    const logger = pino({ level: 'silent' });
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

    const sock = makeWASocket({
        auth: state,
        printQRInTerminal: false,
        logger: logger,
        browser: Browsers.macOS('Chrome')
    });

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            console.log(JSON.stringify({ type: 'WHATSAPP_AUTH_QR', qr: qr }));
        }

        if (connection === 'close') {
            const shouldReconnect = (lastDisconnect.error)?.output?.statusCode !== DisconnectReason.loggedOut;
            if (shouldReconnect) {
                connectToWhatsApp();
            } else {
                console.log(JSON.stringify({ type: 'WHATSAPP_AUTH', status: 'failed', error: 'logged_out' }));
                process.exit(1);
            }
        } else if (connection === 'open') {
            console.log(JSON.stringify({ type: 'WHATSAPP_AUTH', status: 'success' }));
            // We exit after success because this script is just for setup/auth.
            // The actual nanoworker should run another instance of Baileys for message processing if we use it,
            // or the python manager could handle it. Wait, the user wants QR setup.
            setTimeout(() => {
                process.exit(0);
            }, 1000);
        }
    });

    sock.ev.on('creds.update', saveCreds);
}

connectToWhatsApp();
