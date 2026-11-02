"""Контрактный тест правил обязательных полей.

Обе версии сервера (PHP и Python) обязаны вести себя так, как описано в public/schema.json (раздел required):
по заявке со всеми обязательными ответами выдаётся 201, а без любого из них — 422 с ошибкой именно по этому полю.
Вызывается из tools/test_php.py и tools/test_telegram.py: run(сервер, check).
"""
import copy, json, os, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = json.load(open(os.path.join(ROOT, 'public', 'schema.json'), encoding='utf-8'))
RULES = SCHEMA['required']


def first_key(group):
    return next(k for k in SCHEMA[group] if not k.startswith('_'))


def answer(spec):
    """Допустимый ответ для поля по его описанию в schema.json."""
    if spec['type'] == 'choice':
        return first_key(spec['group'])
    if spec['type'] == 'list':
        return [first_key(spec['group'])]
    return 'Достаточно длинный текст'


def names_for(category):
    return RULES['by_category']['all'] + RULES['by_category'].get(category, [])


def error_key(name):
    return 'project.' + ('features.' if RULES['fields'][name]['in'] == 'features' else '') + name


def payload(category, skip=None):
    project = {'category': category, 'city': first_key('city'), 'dimensions_known': False, 'attachment_ids': [], 'features': {}, 'style_preferences': []}
    for name in names_for(category):
        if name != skip:
            spec = RULES['fields'][name]
            (project['features'] if spec['in'] == 'features' else project)[name] = answer(spec)
    return {'schema_version': SCHEMA['schema_version'], 'submission_id': str(uuid.uuid4()), 'lead_type': 'project', 'locale': 'ru',
            'customer': {'name': 'Тест', 'phone': '+77001234567'}, 'consent': {'project_contact': True}, 'source': {'page': '/contract'}, 'project': copy.deepcopy(project)}


def post(server, body, n):
    # у каждого запроса свой адрес отправителя: проверка не упирается в лимит частоты
    headers = {'Content-Type': 'application/json', 'X-Forwarded-For': '203.0.113.%d' % (n % 250 + 1)}
    return server.req('/api/leads', json.dumps(body).encode(), headers)


def run(server, check):
    print('J. обязательные поля: сервер ведёт себя по schema.json')
    n = 0
    for category in SCHEMA['category']:
        n += 1
        status, _ = post(server, payload(category), n)
        check(status == 201, '%s: заявка со всеми обязательными ответами (%d) принята' % (category, len(names_for(category))))
        for name in names_for(category):
            n += 1
            status, data = post(server, payload(category, skip=name), n)
            check(status == 422 and error_key(name) in (data.get('errors') or {}),
                  '%s: без «%s» отказ 422 с ошибкой %s' % (category, name, error_key(name)))
