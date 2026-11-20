"""Approved public sources and their distinct raw field semantics."""
SOURCES = {
    'tencent': {'name': '腾讯招聘', 'url': 'https://careers.tencent.com',
                'raw_fields': {'description_raw': 'Responsibility', 'requirements_raw': 'Requirement', 'additional_requirements_raw': 'ImportantItem'}},
    'netease': {'name': '网易招聘', 'url': 'https://hr.163.com',
                'raw_fields': {'description_raw': 'description', 'requirements_raw': 'requirement'}},
    'xiaomi': {'name': '小米招聘', 'url': 'https://hr.xiaomi.com',
               'raw_fields': {'description_raw': 'description', 'requirements_raw': 'requirement'}},
    'jd': {'name': '京东招聘', 'url': 'https://zhaopin.jd.com',
           'raw_fields': {'description_raw': 'workContent', 'requirements_raw': 'qualification'}},
}
BASELINE_SOURCES = frozenset(('tencent', 'netease'))
EXPANSION_SOURCES = frozenset(SOURCES)


def raw_posts(source, payload):
    if source == 'tencent':
        return [payload['Data']]
    if source == 'netease':
        data = payload['data']
        return data['list'] if 'list' in data else [data]
    if source == 'xiaomi':
        return payload['data']['list']
    if source == 'jd' and isinstance(payload, list):
        return payload
    raise ValueError('Unsupported source/raw response')


def raw_identity(source, post):
    key = {'tencent': 'PostId', 'netease': 'id', 'jd': 'requirementId'}.get(source)
    value = (post.get('jobPostId') or post.get('id')) if source == 'xiaomi' else post.get(key)
    if value is None:
        raise ValueError('Missing raw source identity')
    return str(value)
