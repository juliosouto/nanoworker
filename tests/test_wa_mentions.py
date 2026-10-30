"""
Regression tests for WhatsApp worker mentions (groups).

Root cause: WhatsApp's NATIVE mention (the "@" picker) does not keep the
worker name in the message text - the text becomes "@<phone-number>" and the
real target only exists in contextInfo.mentionedJid - so every native mention
was silently dropped by the mention gate.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

import pytest
from unittest.mock import MagicMock

from utils.message_utils import (
    should_process_wa_message,
    resolve_worker_from_content,
    clean_mention,
    check_wa_permissions,
)

GROUP_JID = '120363000000000000@g.us'
OWN_JID = '5511999999999@s.whatsapp.net'
OWN_LID = '111222333@lid'
SENDER = '5511888888888'


@pytest.fixture
def mock_db(mocker):
    """Fake DB: one whatsapp_config row + two workers (Mini, Flint)."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.fetchone.return_value = {
        'allowed_from': '*',
        'bot_enabled': True,
        'allow_mentions': True,
        'allow_audio_mentions': True,
    }
    cursor.fetchall.return_value = [
        {'id': 1, 'worker_name': 'Mini', 'is_default': False},
        {'id': 2, 'worker_name': 'Flint', 'is_default': True},
    ]
    mocker.patch('database.get_db', return_value=conn)
    return cursor


@pytest.fixture
def require_at(mocker):
    """REQUIRE_AT_PREFIX=true (production default)."""
    mocker.patch('database.get_config', return_value='true')


@pytest.fixture
def own_identity(mocker):
    """The shared WhatsApp account used by every worker."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        'number': '5511999999999',
        'lid_number': '111222333',
        'jid': '5511999999999@s.whatsapp.net',
        'lid': '111222333@lid',
    }
    mocker.patch('requests.get', return_value=resp)
    return resp


# ---------------------------------------------------------------------------
# Native mentions (contextInfo.mentionedJid)
# ---------------------------------------------------------------------------

def test_native_mention_flag_unlocks_group_gate(mock_db, require_at, own_identity):
    """native_mention=True from the Baileys worker must unlock the group gate."""
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, '@5511999999999 ola', is_group=True,
        return_reason=True, mention_data={'native_mention': True}
    )
    assert allowed is True
    assert reason is None


def test_native_mention_via_mentioned_jid(mock_db, require_at, own_identity):
    """A mentioned_jid pointing at our own account must unlock the group gate."""
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, '@5511999999999 ola', is_group=True,
        return_reason=True,
        mention_data={'mentioned_jid': ['5511999999999@s.whatsapp.net']}
    )
    assert allowed is True
    assert reason is None


def test_native_mention_via_mentioned_lid(mock_db, require_at, own_identity):
    """The LID of our own account must unlock the group gate too."""
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, '@111222333 ola', is_group=True,
        return_reason=True,
        mention_data={'mentioned_jid': ['111222333@lid']}
    )
    assert allowed is True
    assert reason is None


def test_native_mention_of_another_contact_is_ignored(mock_db, require_at, own_identity):
    """Mentioning somebody else must NOT unlock the group gate."""
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, '@5511777777777 ola', is_group=True,
        return_reason=True,
        mention_data={'mentioned_jid': ['5511777777777@s.whatsapp.net']}
    )
    assert allowed is False
    assert reason == 'no_worker_mentioned'


def test_group_message_without_mention_is_dropped(mock_db, require_at, own_identity):
    """Baseline: a plain group message is still ignored."""
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, 'oi pessoal, tudo bem?', is_group=True,
        return_reason=True
    )
    assert allowed is False
    assert reason == 'no_worker_mentioned'




# ---------------------------------------------------------------------------
# Text mentions
# ---------------------------------------------------------------------------

def test_at_mention_in_the_middle_of_the_message(mock_db, require_at, own_identity):
    """@Mini can appear anywhere in the text, not only at the beginning."""
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, 'oi pessoal, @Mini pode me ajudar?', is_group=True,
        return_reason=True
    )
    assert allowed is True
    assert reason is None


def test_at_mention_prefix_is_not_a_false_positive(mock_db, require_at, own_identity):
    """@Miniflores must NOT be treated as a mention of Mini."""
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, 'oi @Miniflores tudo bem?', is_group=True,
        return_reason=True
    )
    assert allowed is False
    assert reason == 'no_worker_mentioned'


def test_flint_mention_in_the_middle_of_the_message(mock_db, require_at, own_identity):
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, 'e ai @Flint, me ajuda?', is_group=True,
        return_reason=True
    )
    assert allowed is True


def test_bare_name_mid_sentence_is_ignored_when_at_required(mock_db, require_at, own_identity):
    """With REQUIRE_AT_PREFIX=true, a bare name mid-sentence must not match."""
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, 'oi Mini, me ajuda?', is_group=True,
        return_reason=True
    )
    assert allowed is False
    assert reason == 'no_worker_mentioned'


def test_bare_name_at_start_works_without_at_prefix(mock_db, mocker, own_identity):
    """With REQUIRE_AT_PREFIX=false, a bare name at the start matches."""
    mocker.patch('database.get_config', return_value='false')
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, 'Mini, me ajuda?', is_group=True,
        return_reason=True
    )
    assert allowed is True
    assert reason is None


def test_bare_name_with_leading_whitespace_without_at_prefix(mock_db, mocker, own_identity):
    """Leading whitespace must not prevent a bare name from matching."""
    mocker.patch('database.get_config', return_value='false')
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, '   Mini, me ajuda?', is_group=True,
        return_reason=True
    )
    assert allowed is True
    assert reason is None


def test_resolve_worker_bare_name_with_leading_whitespace(mock_db, mocker):
    """The bare form must resolve to the right worker even with leading spaces."""
    mocker.patch('database.get_config', return_value='false')
    worker = resolve_worker_from_content('   Mini, me ajuda?')
    assert worker['worker_name'] == 'Mini'




# ---------------------------------------------------------------------------
# Note-to-self vs group
# ---------------------------------------------------------------------------

def test_note_to_self_is_always_allowed(mock_db, require_at, own_identity):
    """Note-to-self bypasses the mention gate (unchanged legacy behavior)."""
    allowed, reason = should_process_wa_message(
        OWN_JID, '5511999999999', 'oi, sem mencao nenhuma', is_group=False,
        return_reason=True
    )
    assert allowed is True
    assert reason is None


def test_note_to_self_via_lid_is_always_allowed(mock_db, require_at, own_identity):
    """The note-to-self LID chat is also exempt from the mention gate."""
    allowed, reason = should_process_wa_message(
        OWN_LID, '5511999999999', 'oi, sem mencao nenhuma', is_group=False,
        return_reason=True
    )
    assert allowed is True
    assert reason is None


def test_sender_not_allowed_is_still_enforced_on_mentions(mock_db, require_at, own_identity):
    """A mention does not bypass the allowed_from list."""
    mock_db.fetchone.return_value = {
        'allowed_from': '5511999999999',
        'bot_enabled': True,
        'allow_mentions': True,
        'allow_audio_mentions': True,
    }
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, '@Mini me ajuda', is_group=True,
        return_reason=True
    )
    assert allowed is False
    assert reason == 'sender_not_allowed'

def test_allow_mentions_false_blocks_native_mention(mock_db, require_at, own_identity):
    """With allow_mentions=false even a native mention must be dropped."""
    mock_db.fetchone.return_value = {
        'allowed_from': '*',
        'bot_enabled': True,
        'allow_mentions': False,
        'allow_audio_mentions': True,
    }
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, '@5511999999999 ola', is_group=True,
        return_reason=True,
        mention_data={'native_mention': True}
    )
    assert allowed is False
    assert reason == 'no_worker_mentioned'


def test_allow_mentions_false_blocks_text_mention(mock_db, require_at, own_identity):
    """With allow_mentions=false a textual @mention must be dropped too."""
    mock_db.fetchone.return_value = {
        'allowed_from': '*',
        'bot_enabled': True,
        'allow_mentions': False,
        'allow_audio_mentions': True,
    }
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, '@Mini me ajuda', is_group=True,
        return_reason=True
    )
    assert allowed is False
    assert reason == 'no_worker_mentioned'




# ---------------------------------------------------------------------------
# Worker resolution
# ---------------------------------------------------------------------------

def test_resolve_worker_from_middle_mention(mock_db, require_at):
    """resolve_worker_from_content must find a mention in the middle of the text."""
    worker = resolve_worker_from_content('oi pessoal, @Mini pode me ajudar?')
    assert worker['worker_name'] == 'Mini'


def test_resolve_worker_flint(mock_db, require_at):
    worker = resolve_worker_from_content('e ai @Flint, me ajuda?')
    assert worker['worker_name'] == 'Flint'


def test_resolve_worker_prefix_false_positive(mock_db, require_at):
    """@Miniflores must fall back to the default worker."""
    worker = resolve_worker_from_content('oi @Miniflores tudo bem?')
    assert worker['worker_name'] == 'Flint'


# ---------------------------------------------------------------------------
# clean_mention
# ---------------------------------------------------------------------------

def test_clean_mention_removes_middle_mention(mock_db, require_at):
    """clean_mention must strip the mention even in the middle of the sentence."""
    assert clean_mention('oi pessoal, @Mini pode me ajudar?') == 'oi pessoal, pode me ajudar?'


def test_clean_mention_keeps_prefix_false_positive(mock_db, require_at):
    """@Miniflores must not be stripped from the content."""
    assert clean_mention('oi @Miniflores tudo bem?') == 'oi @Miniflores tudo bem?'


def test_clean_mention_inside_quoted_block(mock_db, require_at):
    """A mention inside a "[Quoted message from: ...]" block must be stripped."""
    content = '[Quoted message from: Fulano]\n\n@Mini, me ajuda?'
    assert clean_mention(content) == '[Quoted message from: Fulano]\n\n, me ajuda?'


def test_clean_mention_bare_name_inside_quoted_block(mock_db, mocker):
    """The bare form inside a quoted block must be stripped too."""
    mocker.patch('database.get_config', return_value='false')
    content = '[Quoted message from: Fulano]\n\nMini, me ajuda?'
    assert clean_mention(content) == '[Quoted message from: Fulano]\n\n, me ajuda?'


# ---------------------------------------------------------------------------
# check_wa_permissions forwards the mention metadata
# ---------------------------------------------------------------------------

def test_check_wa_permissions_forwards_native_mention(mock_db, require_at, own_identity):
    """The webhook payload must reach should_process_wa_message as mention_data."""
    data = {
        'channel_id': f'wa_web:{GROUP_JID}',
        'sender_id': SENDER,
        'remote_jid': GROUP_JID,
        'native_mention': True,
    }
    allowed, reason = check_wa_permissions(data, '@5511999999999 ola')
    assert allowed is True
    assert reason is None


# ---------------------------------------------------------------------------
# Doubled "@" is not a mention (Node/Python parity regression)
# ---------------------------------------------------------------------------

def test_doubled_at_is_not_a_mention(mock_db, require_at, own_identity):
    """'@@Mini' must NOT unlock the gate: only a single '@' marks a mention."""
    allowed, reason = should_process_wa_message(
        GROUP_JID, SENDER, '@@Mini me ajuda', is_group=True,
        return_reason=True
    )
    assert allowed is False
    assert reason == 'no_worker_mentioned'


def test_doubled_at_is_not_resolved_as_a_worker(mock_db, require_at):
    """'@@Mini' must not resolve to the worker 'Mini'."""
    worker = resolve_worker_from_content('@@Mini me ajuda')
    assert worker['worker_name'] == 'Flint'


def test_doubled_at_is_not_stripped(mock_db, require_at):
    """clean_mention must leave '@@Mini' untouched."""
    assert clean_mention('@@Mini me ajuda') == '@@Mini me ajuda'


# ---------------------------------------------------------------------------
# Node <-> Python matcher parity
# ---------------------------------------------------------------------------

# The very same cases are evaluated by the Python matcher and by the Node
# matcher extracted from node_scripts/wa_worker.js. Any divergence between the
# two implementations is a bug: the Node worker decides what is forwarded and
# the Python backend decides what is processed, so both must agree.
PARITY_CASES = [
    # (text, worker_name, require_at, expected_match)
    ('@Mini tudo', 'Mini', True, True),
    ('oi @Mini tudo', 'Mini', True, True),
    ('oi! @Mini, tudo', 'Mini', True, True),
    ('@@Mini tudo', 'Mini', True, False),
    ('user@mini.com', 'Mini', True, False),
    ('@Miniflores', 'Mini', True, False),
    ('Mini tudo', 'Mini', True, False),
    ('   Mini, me ajuda', 'Mini', False, True),
    ('Mini, me ajuda', 'Mini', False, True),
    ('Minino, me ajuda', 'Mini', False, False),
    ('ola Mini tudo', 'Mini', False, False),
]


def _node_matcher_script():
    """Build a small Node script that reuses the real buildMentionRegex."""
    worker_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'node_scripts', 'wa_worker.js',
    )
    with open(worker_path, 'r', encoding='utf-8') as fh:
        source = fh.read()

    match = re.search(
        r'^function buildMentionRegex\(name, requireAt\) \{.*?^\}',
        source,
        re.MULTILINE | re.DOTALL,
    )
    assert match, 'buildMentionRegex() not found in wa_worker.js'
    function_source = match.group(0)

    script = function_source + """
const cases = JSON.parse(process.argv[2]);
const results = cases.map(c =>
    buildMentionRegex(c.name, c.requireAt).test(c.text.toLowerCase().trim())
);
console.log(JSON.stringify(results));
"""
    return script


@pytest.fixture(scope='module')
def node_matcher():
    """Skip the whole parity test when Node is not available."""
    if not shutil.which('node'):
        pytest.skip('node is not installed')
    script = _node_matcher_script()
    tmp = tempfile.NamedTemporaryFile('w', suffix='.js', delete=False)
    try:
        tmp.write(script)
        tmp.close()
        yield tmp.name
    finally:
        os.unlink(tmp.name)


def test_node_and_python_matchers_agree(node_matcher):
    """The Node and the Python matcher must return the same result."""
    payload = json.dumps([
        {'text': text, 'name': name, 'requireAt': require_at}
        for text, name, require_at, _ in PARITY_CASES
    ])
    proc = subprocess.run(
        ['node', node_matcher, payload],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f'node failed: {proc.stderr}'
    node_results = json.loads(proc.stdout)

    from utils.message_utils import _mention_regex

    python_results = []
    for text, name, require_at, _ in PARITY_CASES:
        pattern = _mention_regex(name, require_at=require_at)
        python_results.append(bool(pattern and pattern.search(text)))

    assert node_results == python_results, (
        'Node/Python matcher divergence:\n'
        f'cases={PARITY_CASES}\n'
        f'node={node_results}\n'
        f'python={python_results}'
    )


def test_parity_cases_have_the_expected_outcome(node_matcher):
    """The parity table itself must reflect the documented behavior."""
    payload = json.dumps([
        {'text': text, 'name': name, 'requireAt': require_at}
        for text, name, require_at, _ in PARITY_CASES
    ])
    proc = subprocess.run(
        ['node', node_matcher, payload],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f'node failed: {proc.stderr}'
    node_results = json.loads(proc.stdout)

    expected = [expected for _, _, _, expected in PARITY_CASES]
    assert node_results == expected

