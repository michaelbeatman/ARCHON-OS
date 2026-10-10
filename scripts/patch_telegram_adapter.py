import os
import sys

adapter_path = '/opt/hermes/plugins/platforms/telegram/adapter.py'
with open(adapter_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add mirror helper function if not present
helper_def = '''
def _mirror_to_archon_inbox(msg):
    try:
        import json, time, datetime, os
        os.makedirs('/opt/data/inbox/telegram', exist_ok=True)
        u = getattr(msg, 'from_user', None)
        s_name = f'@{u.username}' if (u and getattr(u, 'username', None)) else (getattr(u, 'first_name', 'User') if u else 'User')
        doc = {
            'id': f'tg_{int(time.time())}_{getattr(msg, "message_id", "0")}',
            'type': 'TEXT',
            'sender': f'{s_name} ({getattr(u, "id", "")})',
            'chat_id': getattr(getattr(msg, 'chat', None), 'id', ''),
            'text': getattr(msg, 'text', '') or '',
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'mtime': time.time()
        }
        with open(f'/opt/data/inbox/telegram/msg_{int(time.time())}_{getattr(msg, "message_id", "0")}.json', 'w', encoding='utf-8') as tf:
            json.dump(doc, tf, ensure_ascii=False, indent=2)
    except Exception as _e:
        logger.warning('[Telegram] Archon mirror failed: %s', _e)
'''

if 'def _mirror_to_archon_inbox(msg):' not in content:
    content = helper_def + '\n' + content

# 2. In _handle_text_message
target_text = '''    async def _handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages.

        Telegram clients split long messages into multiple updates.  Buffer
        rapid successive text messages from the same user/chat and aggregate
        them into a single MessageEvent before dispatching.
        """
        msg = self._effective_update_message(update)
        if not msg or not msg.text:
            return'''

replacement_text = target_text + '\n        _mirror_to_archon_inbox(msg)'

if target_text in content and '_mirror_to_archon_inbox(msg)' not in content:
    content = content.replace(target_text, replacement_text, 1)

# 3. In _handle_command
target_cmd = '''    async def _handle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming command messages."""
        msg = self._effective_update_message(update)
        if not msg or not msg.text:
            return'''

replacement_cmd = target_cmd + '\n        _mirror_to_archon_inbox(msg)'

if target_cmd in content:
    content = content.replace(target_cmd, replacement_cmd, 1)

with open(adapter_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("ENHANCED_PATCH_SUCCESS")
