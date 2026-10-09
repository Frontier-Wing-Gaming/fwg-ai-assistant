"""Deterministic panel operations: never interpret console output as commands."""
import json
import re
import secrets
import time
from urllib.parse import urlsplit

POWER = {'start', 'stop', 'restart'}

def power_intent(text):
    # Reject questions, negations, compound instructions, and extra targets.
    match = re.fullmatch(r'\s*(?:please\s+)?(start|stop|shutdown|restart|reboot)\s+(.+?)\s*[.!]?\s*', text, re.I)
    if not match: return None
    action = {'shutdown': 'stop', 'reboot': 'restart'}.get(match[1].lower(), match[1].lower())
    target = re.sub(r'\s+server$', '', match[2], flags=re.I).strip().rstrip('.!')
    return action, target

def exact_server(text, user, ns):
    text = re.sub(r'\s+', ' ', text).strip().casefold()
    matches = []
    for alias, item in ns['SERVERS'].items():
        if not ns['permitted'](user, alias, 'status'): continue
        phrases = [alias.replace('_', ' ').replace('-', ' '), item['name']] + item.get('voice_names', [])
        if any(re.sub(r'\s+', ' ', phrase).strip().casefold() == text for phrase in phrases): matches.append(alias)
    return matches[0] if len(matches) == 1 else None

def route(text, username, user, session, ns):
    intent = power_intent(text)
    if intent:
        action, words = intent
        alias = exact_server(words, user, ns)
        if not alias: return ('Name exactly one permitted server, for example start Minecraft. No action was taken.', None)
        if not ns['permitted'](user, alias, action): return (f'Your account does not have {action} permission. No action was taken.', None)
        for key, entry in list(ns['pending'].items()):
            if entry['session'] == session or entry['expires'] < time.time(): ns['pending'].pop(key, None)
        token = secrets.token_urlsafe(24)
        ns['pending'][token] = {'user': username, 'server': alias, 'session': session,
                               'action': action, 'expires': time.time()+90}
        ns['audit'](username, action, alias, 'confirmation_requested')
        return (f'{action.capitalize()} requested for '+ns['SERVERS'][alias]['name']+'. Review the confirmation. No action has been taken.',
                {'token': token, 'server': ns['SERVERS'][alias]['name'], 'action': action})
    if re.search(r'\b(start|stop|shutdown|restart|reboot|kill)\b', text, re.I):
        return ('For power actions, say start, stop, or restart followed by exactly one server name. No action was taken.', None)
    alias = ns['pick_server'](text, user)
    if alias and re.search(r'\b(logs?|console)\b', text, re.I):
        if not ns['permitted'](user, alias, 'logs'): return ('Your account does not have permission to read console output.', None)
        reply = console_answer(alias, ns)
        ns['audit'](username, 'logs', alias, 'queried')
        return reply, None
    if alias and re.search(r'\b(resources?|usage|cpu|memory|ram|disk|network)\b', text, re.I):
        if not ns['permitted'](user, alias, 'resources'): return ('Your account does not have resource usage permission.', None)
        reply = resource_answer(alias, ns)
        ns['audit'](username, 'resources', alias, 'queried')
        return reply, None
    return None

def panel_get(alias, path, ns):
    if urlsplit(ns['PANEL']).scheme != 'https' or not ns['KEY']: raise ValueError('Panel not configured')
    with ns['httpx'].Client(timeout=15, follow_redirects=False) as client:
        r = client.get(ns['PANEL']+'/api/client/servers/'+ns['SERVERS'][alias]['identifier']+path,
                       headers={'Authorization': 'Bearer '+ns['KEY'], 'Accept': 'application/json'})
        r.raise_for_status()
        return r.json()

def resource_answer(alias, ns):
    try:
        data = panel_get(alias, '/resources', ns)['attributes']
        r = data.get('resources', {})
        fields = []
        for field, label, divisor, unit in [('cpu_absolute','CPU',1,'percent'),
            ('memory_bytes','RAM',1024**3,'gigabytes'), ('disk_bytes','Disk',1024**3,'gigabytes'),
            ('network_rx_bytes','Network received',1024**2,'megabytes'), ('network_tx_bytes','Network sent',1024**2,'megabytes')]:
            value = r.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool): fields.append(f'{label} {value/divisor:.1f} {unit}')
        return ns['SERVERS'][alias]['name']+' is '+str(data.get('current_state', 'unknown'))+'. '+('. '.join(fields)+'.' if fields else 'No resource figures returned.')+' Network figures are counters, not speeds.'
    except Exception: return 'I could not verify resource usage. Check panel connectivity and account permissions.'

def clean_line(line, ns):
    line = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(line))
    line = ''.join(c for c in line if c.isprintable() or c == ' ')
    for secret in [ns.get('KEY', '')]:
        if secret: line = line.replace(secret, '[redacted]')
    line = re.sub(r'(?i)\b(password|secret|token|authorization|api[_-]?key)\s*[:=]\s*\S+', r'\1=[redacted]', line)
    return line[:180]

def console_answer(alias, ns):
    try:
        from websockets.sync.client import connect
        data = panel_get(alias, '/websocket', ns)['data']
        if urlsplit(data['socket']).scheme != 'wss': return 'Console access requires a secure WSS connection to the game node.'
        lines = []; authenticated = False
        # No persistent connection and no send-command capability.
        with connect(data['socket'], origin=ns['PANEL'], open_timeout=5, close_timeout=1,
                     max_size=256*1024) as ws:
            ws.send(json.dumps({'event': 'auth', 'args': [data['token']]}))
            deadline = time.monotonic()+5
            while time.monotonic() < deadline:
                try: message = json.loads(ws.recv(timeout=max(0.01, deadline-time.monotonic())))
                except TimeoutError: break
                event = message.get('event')
                if event == 'auth success':
                    authenticated = True
                    ws.send(json.dumps({'event': 'send logs', 'args': []}))
                    deadline = time.monotonic()+2
                elif event in ('jwt error','token expired','daemon error'): raise ValueError('Console refused')
                elif event == 'console output' and authenticated:
                    for value in message.get('args', []):
                        for line in str(value).splitlines():
                            cleaned = clean_line(line, ns)
                            if cleaned: lines.append(cleaned)
                    lines = lines[-3:]
        if not authenticated: return 'I could not authenticate the console connection.'
        if not lines: return 'The console returned no recent output. This does not establish whether the server is healthy.'
        return 'Recent console output from '+ns['SERVERS'][alias]['name']+'. '+ ' | '.join(lines)
    except Exception: return 'I could not read the console. Check websocket permissions and secure connectivity to the game node.'

async def execute_power(entry, ns, source):
    alias, action, username = entry['server'], entry['action'], entry['user']
    if action not in POWER: raise ValueError('Unsupported action')
    await ns['protected_thread'](ns['audit'], username, action, alias, source+'_confirmed_attempt')
    try:
        if urlsplit(ns['PANEL']).scheme != 'https' or not ns['KEY']: raise ValueError('Panel not configured')
        async with ns['httpx'].AsyncClient(timeout=15, follow_redirects=False) as client:
            r = await client.post(ns['PANEL']+'/api/client/servers/'+ns['SERVERS'][alias]['identifier']+'/power',
                json={'signal': action}, headers={'Authorization': 'Bearer '+ns['KEY'], 'Accept': 'application/json'})
    except Exception:
        await ns['protected_thread'](ns['audit'], username, action, alias, source+'_outcome_unknown')
        return {'message': 'The '+action+' outcome is unknown. Check the panel before trying again.', 'accepted': False}
    accepted = r.status_code == 204
    await ns['protected_thread'](ns['audit'], username, action, alias, source+('_accepted' if accepted else '_rejected_'+str(r.status_code)))
    return {'message': ('Pterodactyl accepted the '+action+' request for '+ns['SERVERS'][alias]['name']+'. Check status to verify completion.') if accepted else ('Pterodactyl rejected the '+action+' request. Check permissions and server state.'), 'accepted': accepted}
