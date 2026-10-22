"""Model-callable current API conversation messages, never cross-channel sends.

The standalone send engine intentionally remains unregistered. This wrapper
has a stable schema for native runs and can deliver only inside the host-bound
ContextVar scope. Tool construction must not depend on request-local check_fn
state (the model schemas are assembled before the worker scope is entered).
"""
import json
from gateway.interactive_messages import send_current_message, current_interaction_context
from tools.send_message_tool import SEND_MESSAGE_SCHEMA
from tools.registry import registry
from copy import deepcopy

CURRENT_MESSAGE_SCHEMA = deepcopy(SEND_MESSAGE_SCHEMA)
CURRENT_MESSAGE_SCHEMA['description'] = (
    "Send text and optional Telegram-compatible inline buttons to this API conversation only. "
    "Use action='context' only when the bound context is needed and not already supplied. "
    "Page context describes the UI; it does not restrict task targets. "
    "A button is display data: host metadata may propose typed actions, but the host validates and registers them; "
    "financial actions always need the user's separate review and confirmation."
)
CURRENT_MESSAGE_SCHEMA['parameters'] = {
    'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['send', 'context'], 'description': 'send publishes; context reads this run\'s trusted host context without delivery.'},
        'target': {'type': 'string', 'enum': ['current']},
        'message': {'type': 'string', 'description': 'Required for send: plain text, 1–4096 characters. Use message, not text. This current API transport has no attachment delivery.'},
        'reply_markup': SEND_MESSAGE_SCHEMA['parameters']['properties']['reply_markup'],
        'metadata': SEND_MESSAGE_SCHEMA['parameters']['properties']['metadata'],
    }, 'additionalProperties': False,
}

def current_message(args, **kwargs):
    if args.get('target', 'current') != 'current':
        return json.dumps({'error': 'This tool can deliver only to the current API conversation'})
    if args.get('action', 'send') == 'context':
        return json.dumps({'context': current_interaction_context()}, ensure_ascii=False)
    if args.get('action', 'send') != 'send':
        return json.dumps({'error': 'Unsupported current-conversation action'})
    return json.dumps(send_current_message(args.get('message'), args.get('reply_markup'), args.get('metadata')), ensure_ascii=False)

registry.register(name='send_message',toolset='api_interactions',schema=CURRENT_MESSAGE_SCHEMA,handler=current_message,emoji='💬')
