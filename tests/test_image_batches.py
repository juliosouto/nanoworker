"""Several WhatsApp images sent together with one caption: the Baileys worker
groups them into one message (extra_images), the webhook saves them, the
router stores them in messages_in.extra_attachments and the processor sends
all of them to the model."""
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest

from database import get_db

PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


@pytest.fixture
def db(mock_db_path):
    import database
    database.init_db()
    yield


# --------------------------------------------------------------------------
# Webhook: save_extra_images
# --------------------------------------------------------------------------

def test_save_extra_images_saves_each_image(tmp_path, monkeypatch):
    from routes.webhooks import save_extra_images
    monkeypatch.setattr("utils.file_utils.get_temp_dir", lambda: str(tmp_path))

    saved = save_extra_images({"extra_images": [
        {"image_base64": PNG_B64, "mimetype": "image/png"},
        {"image_base64": PNG_B64},
        {"mimetype": "image/jpeg"},  # no data: skipped
        "junk",
    ]})

    assert [s["mime_type"] for s in saved] == ["image/png", "image/jpeg"]
    for s in saved:
        assert s["path"].startswith("path:")
        assert os.path.exists(s["path"][5:])


def test_save_extra_images_none_without_extras():
    from routes.webhooks import save_extra_images
    assert save_extra_images({}) is None
    assert save_extra_images({"extra_images": "x"}) is None
    assert save_extra_images({"extra_images": []}) is None


# --------------------------------------------------------------------------
# Router: extra_attachments stored as JSON
# --------------------------------------------------------------------------

def test_route_inbound_stores_extra_attachments(db, mocker):
    mocker.patch("threading.Thread.start")
    mocker.patch("utils.message_utils.get_default_worker", return_value={"worker_name": "w"})
    from router import route_inbound_message

    extras = [{"path": "path:/tmp/a.jpg", "mime_type": "image/jpeg"}]
    m_id, _, _ = route_inbound_message("c-batch", "@w veja", image_base64="path:/tmp/main.jpg",
                                       extra_attachments=extras)
    m_id2, _, _ = route_inbound_message("c-batch", "@w sem extras")

    conn = get_db()
    rows = {r["id"]: r["extra_attachments"] for r in conn.execute(
        "SELECT id, extra_attachments FROM messages_in")}
    conn.close()
    assert json.loads(rows[m_id]) == extras
    assert rows[m_id2] is None


# --------------------------------------------------------------------------
# Processor: _extra_image_parts
# --------------------------------------------------------------------------

def _insert_message(extra_attachments):
    conn = get_db()
    conn.execute("INSERT INTO sessions (id, agent_id, channel_id) VALUES ('s', 'agent-1', 'c')")
    conn.execute("INSERT INTO messages_in (id, session_id, content, extra_attachments) VALUES (?, 's', 'x', ?)",
                 ("m", extra_attachments))
    conn.commit()
    return conn


def test_extra_image_parts_builds_parts_and_note(db, tmp_path):
    from agent.message_processor import _extra_image_parts
    files = []
    for name in ("b.png", "c.png"):
        f = tmp_path / name
        f.write_bytes(b"\x89PNG")
        files.append({"path": f"path:{f}", "mime_type": "image/png"})
    conn = _insert_message(json.dumps(files + [{"path": "path:/missing.png"}]))

    parts = _extra_image_parts(None, conn.cursor(), "m", has_main_image=True)
    conn.close()

    media = [p for p in parts if not isinstance(p, str)]
    texts = [p for p in parts if isinstance(p, str)]
    assert len(media) == 2  # the missing file is skipped
    assert texts[0] == f"[Attached Document File Path: {tmp_path / 'b.png'}]"
    assert texts[-1].startswith("[3 images were sent together")


@pytest.mark.parametrize("raw", [None, "", "not json", "{}", "[]"])
def test_extra_image_parts_fails_open(db, raw):
    from agent.message_processor import _extra_image_parts
    conn = _insert_message(raw)
    assert _extra_image_parts(None, conn.cursor(), "m", has_main_image=True) == []
    conn.close()


def test_extra_image_parts_unknown_message(db):
    from agent.message_processor import _extra_image_parts
    conn = get_db()
    assert _extra_image_parts(None, conn.cursor(), "nope", has_main_image=False) == []
    conn.close()


# --------------------------------------------------------------------------
# Baileys worker: image batching (real code from wa_worker.js run in Node)
# --------------------------------------------------------------------------

_NODE_HARNESS = r"""
process.env.IMAGE_BATCH_WINDOW_MS = '40';
const forwarded = [];
let downloads = 0;
const sock = { updateMediaMessage: null };
const pino = () => null;
async function downloadMediaMessage(msg) {
    downloads++;
    if (msg.key.id === 'bad') throw new Error('boom');
    return Buffer.from('img-' + msg.key.id);
}
async function forwardInbound(msg, msgContent, flow, mentionedJids, nativeMention, imageBatch) {
    forwarded.push({ lead: msg.key.id, ids: imageBatch.map(e => e.msg.key.id),
                     text: imageBatchText(imageBatch),
                     images: (await downloadBatchImages(imageBatch)).length });
}
const agentConfig = { workerNames: ['w'] };
function img(id, from, caption, flow) {
    const msgContent = { imageMessage: { caption, mimetype: 'image/jpeg' } };
    return { msg: { key: { id, remoteJid: 'g@g.us', participant: from } }, msgContent, flow,
             mentionedJids: [], nativeMention: false, textContent: caption || '', agentConfig };
}
/*BATCH_CODE*/
(async () => {
    // Caption with mention on the first of three photos.
    queueImageForBatch(img('a1', 'p1', '@w compare', 'process'));
    queueImageForBatch(img('a2', 'p1', '', false));
    queueImageForBatch(img('a3', 'p1', undefined, false));
    // Another sender, no mention anywhere: dropped.
    queueImageForBatch(img('b1', 'p2', 'nada', false));
    // Caption on the LAST photo, one download fails.
    queueImageForBatch(img('c1', 'p3', '', false));
    queueImageForBatch(img('bad', 'p3', '', false));
    queueImageForBatch(img('c3', 'p3', '@w o que é?', 'process'));
    await new Promise(r => setTimeout(r, 150));
    const texts = {
        single: imageBatchText([img('x', 'p', '', 'process')]),
        many: imageBatchText([img('x', 'p', '', 'process'), img('y', 'p', '', false)]),
        captions: imageBatchText([img('x', 'p', ' um ', 'process'), img('y', 'p', 'dois', false)]),
    };
    // A non-image message flushes the pending batch at once.
    queueImageForBatch(img('d1', 'p4', '@w oi', 'process'));
    await flushImageBatch(imageBatchKey(img('t', 'p4').msg));
    const flushedNow = forwarded.length;
    console.log(JSON.stringify({ forwarded, texts, flushedNow, pending: imageBatches.size }));
})();
"""


def _batch_code():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "node_scripts", "wa_worker.js")
    src = open(path, encoding="utf-8").read()
    m = re.search(r"^// --- Image batches ---\n.*?(?=^// Downloads the media of one inbound message)",
                  src, re.MULTILINE | re.DOTALL)
    assert m, "image batch section not found in wa_worker.js"
    return m.group(0)


@pytest.fixture(scope="module")
def batch_result():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = _NODE_HARNESS.replace("/*BATCH_CODE*/", _batch_code())
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tmp:
        tmp.write(script)
    try:
        proc = subprocess.run(["node", tmp.name], capture_output=True, text=True, timeout=30)
    finally:
        os.unlink(tmp.name)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_batch_forwards_all_images_once(batch_result):
    by_lead = {f["lead"]: f for f in batch_result["forwarded"]}
    assert by_lead["a1"]["ids"] == ["a1", "a2", "a3"]
    assert by_lead["a1"]["text"] == "@w compare"
    assert by_lead["a1"]["images"] == 3


def test_batch_caption_on_last_image_leads(batch_result):
    by_lead = {f["lead"]: f for f in batch_result["forwarded"]}
    assert by_lead["c3"]["ids"] == ["c1", "bad", "c3"]
    assert by_lead["c3"]["text"] == "@w o que é?"
    assert by_lead["c3"]["images"] == 2  # the failed download is skipped


def test_batch_without_mention_is_dropped(batch_result):
    assert "b1" not in {f["lead"] for f in batch_result["forwarded"]}


def test_batch_texts(batch_result):
    assert batch_result["texts"] == {
        "single": "[Image received]",
        "many": "[2 images received]",
        "captions": "um\n\ndois",
    }


def test_other_message_flushes_pending_batch(batch_result):
    assert batch_result["flushedNow"] == 3
    assert batch_result["forwarded"][-1]["lead"] == "d1"
    assert batch_result["pending"] == 0
