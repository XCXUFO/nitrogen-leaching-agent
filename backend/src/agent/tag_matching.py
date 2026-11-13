"""Versioned name/path index. Suggested aliases can never become hard filters."""
import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from src.utils.taxonomy import enabled_tag_ids

DEFAULT_ALIASES = Path(__file__).resolve().parents[2] / 'data/retrieval/aliases.json'


def normalize(value):
    value=' '.join(unicodedata.normalize('NFKC', value).casefold().split())
    return re.sub(r'\s*/\s*',' / ',value)


class TagIndex:
    def __init__(self, taxonomy, aliases, base_aliases):
        self.configuration = {'taxonomy':taxonomy, 'aliases':aliases, 'base_aliases':base_aliases}
        self.tags = {t['id']: t for t in taxonomy.get('tags', [])}
        self.dimensions = {d['id']: d for d in taxonomy.get('dimensions', [])}
        self.enabled = enabled_tag_ids(taxonomy)
        self.lookup = {}
        self._descendants = {}
        def add(word, identifier, method, relation='exact', review='approved'):
            if identifier in self.enabled:
                self.lookup.setdefault(normalize(word), []).append((identifier, method, relation, review))
        for identifier in sorted(self.enabled):
            tag = self.tags[identifier]
            add(tag['name'], identifier, 'exact_name')
            add(tag.get('path', tag['name']), identifier, 'exact_path')
            for word in base_aliases.get(tag['name'], ()):
                add(word, identifier, 'controlled_alias')
        for entry in aliases.get('entries', []):
            for word in entry['expressions']:
                for identifier in entry['tag_ids']:
                    add(word, identifier, 'configured_alias', entry['relation'], entry['review_status'])
        self.alias_version = aliases.get('version', 'none')
        self.version = hashlib.sha256(json.dumps([taxonomy, aliases, base_aliases], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.words = set(self.lookup) | {normalize(w) for name, words in base_aliases.items() for w in (name, *words)}
        self.pattern = re.compile('|'.join(re.escape(w) for w in sorted(self.words, key=lambda w: (-len(w), w)))) if self.words else None

    def extract(self, query):
        return list(dict.fromkeys(m.group() for m in self.pattern.finditer(normalize(query)))) if self.pattern else []

    def descendants(self, identifier):
        if identifier in self._descendants: return self._descendants[identifier]
        found = {identifier}
        while True:
            more = {i for i in self.enabled if self.tags[i].get('parent_id') in found}
            if more <= found:
                self._descendants[identifier]=sorted(found & self.enabled)
                return self._descendants[identifier]
            found |= more

    def candidates(self, original, canonical):
        records = self.lookup.get(normalize(original)) or self.lookup.get(normalize(canonical)) or []
        result = {}
        for identifier, method, relation, review in records:
            if identifier in result: continue
            tag = self.tags[identifier]
            result[identifier] = {'id': identifier, 'path': tag.get('path', tag['name']),
                'dimension_id': tag['dimension_id'], 'method': method, 'relation': relation,
                'review_status': review, 'descendant_ids': self.descendants(identifier)}
        return list(result.values())


@lru_cache(maxsize=32)
def compiled(payload, alias_payload, base_payload):
    return TagIndex(json.loads(payload), json.loads(alias_payload), json.loads(base_payload))


def tag_index(taxonomy, base_aliases, alias_path=None):
    # Counts do not invalidate semantic caches. Read current states each request.
    snapshot = {'dimensions': [{k: d[k] for k in ('id', 'name', 'enabled') if k in d} for d in taxonomy.get('dimensions', [])],
        'tags': [{k: t[k] for k in ('id', 'name', 'dimension_id', 'parent_id', 'enabled', 'path', 'updated_at') if k in t} for t in taxonomy.get('tags', [])]}
    degraded = None
    try:
        aliases = json.loads(Path(alias_path or DEFAULT_ALIASES).read_text(encoding='utf-8'))
        if not isinstance(aliases.get('entries'), list): raise ValueError('invalid alias entries')
        if any(not all(key in entry for key in ('expressions','tag_ids','relation','review_status')) for entry in aliases['entries']):
            raise ValueError('invalid alias record')
    except (OSError, ValueError, TypeError):
        aliases = {'version': 'unavailable', 'entries': []}
        degraded = 'aliases_unavailable'
    encode = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)
    return compiled(encode(snapshot), encode(aliases), encode(base_aliases)), degraded
