"""Local pre-match after upstream intent/keyword extraction. Python 3.9+, stdlib only.

This returns candidates and stable IDs. It does not retrieve documents, invoke
skills, infer user intent, or modify the live application.
"""
import argparse
import json
import unicodedata
from pathlib import Path


def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


class Matcher:
    def __init__(self, folder=None, with_proposed_aliases=False):
        self.folder = Path(folder) if folder else Path(__file__).resolve().parent
        self.taxonomy = json.loads((self.folder / 'taxonomy.json').read_text())
        self.tags = {tag['id']: tag for tag in self.taxonomy['tags']}
        self.index = {}
        self.descendants = {identifier: [] for identifier in self.tags}
        for tag in self.tags.values():
            if not tag['effective_enabled']:
                continue
            for ancestor in tag['ancestor_ids']:
                self.descendants[ancestor].append(tag['id'])
            for term in {tag['name'], tag['path']}:
                self.index.setdefault(normalize(term), []).append((tag['id'], 'exact_name_or_path', None))
        if with_proposed_aliases:
            aliases = json.loads((self.folder / 'aliases.proposed.json').read_text())
            for entry in aliases['entries']:
                for expression in entry['expressions']:
                    for identifier in entry['tag_ids']:
                        if identifier not in self.tags or not self.tags[identifier]['effective_enabled']:
                            raise ValueError('Alias references an unavailable tag: ' + identifier)
                        self.index.setdefault(normalize(expression), []).append((identifier, entry['relation'], entry['review_status']))
        self.skills = {item['id']: item for item in json.loads((self.folder / 'skills.json').read_text())['skills']}
        self.intents = {item['intent']: item for item in json.loads((self.folder / 'intent_skill_mapping.json').read_text())['entries']}

    def match(self, keywords, intents=()):
        mappings, unmatched = [], []
        for item in keywords:
            entry = {'term': item} if isinstance(item, str) else dict(item)
            term = entry['term']
            polarity = entry.get('polarity', 'include')
            if polarity not in {'include', 'exclude'}:
                raise ValueError('polarity must be include or exclude')
            hits = self.index.get(normalize(term), [])
            if entry.get('dimension_key'):
                hits = [hit for hit in hits if self.tags[hit[0]]['dimension_key'] == entry['dimension_key']]
            if not hits:
                unmatched.append(entry)
                continue
            # Prefer an existing exact name/path over a proposed alias collision.
            exact = [hit for hit in hits if hit[1] == 'exact_name_or_path']
            hits = exact or hits
            candidates = {}
            for identifier, method, review_status in hits:
                tag = self.tags[identifier]
                candidates[identifier] = dict(id=identifier, dimension_key=tag['dimension_key'],
                                              path=tag['path'], method=method, review_status=review_status,
                                              descendant_ids=list(self.descendants[identifier]))
            ambiguous = len(candidates) != 1
            explicit = bool(entry.get('explicit_tag_filter'))
            filter_allowed = explicit and not ambiguous and bool(exact)
            mappings.append(dict(term=term, polarity=polarity, source=entry.get('source', 'current_user'),
                                 condition_id=entry.get('condition_id'), object_group=entry.get('object_group', 'subject'),
                                 status='ambiguous' if ambiguous else 'matched',
                                 usage='explicit_tag_filter' if filter_allowed else 'ranking_signal',
                                 requires_resolution=explicit and not filter_allowed,
                                 candidates=list(candidates.values())))
        skill_ids, unresolved_intents = [], []
        for intent in intents:
            if intent not in self.intents:
                unresolved_intents.append(intent)
                continue
            for name in self.intents[intent]['skills']:
                if name not in skill_ids:
                    skill_ids.append(name)
        return dict(schema_version='local-prematch-v1', input_keywords=keywords, input_intents=list(intents),
                    mappings=mappings, unmatched_keywords=unmatched, unresolved_intents=unresolved_intents,
                    skill_candidates=[dict(id=name, title=self.skills[name]['title'],
                                           observed_status=self.skills[name]['observed_status']) for name in skill_ids],
                    fallback=dict(keep_original_query=True, keep_unmatched_keywords=True,
                                  retrieve_untagged_content=True, runtime_access_checks_required=True),
                    note='关键词和意图由上游提供；输出是初步候选，不表示资料符合条件或 skill 已执行。')


def main():
    parser = argparse.ArgumentParser(description='Match extracted keywords and intents against the exported taxonomy.')
    parser.add_argument('keywords', nargs='*', help='Extracted terms, not a whole sentence')
    parser.add_argument('--intent', action='append', default=[], help='Upstream intent; repeat for multiple tasks')
    parser.add_argument('--with-proposed-aliases', action='store_true', help='Include unreviewed local alias/topic suggestions')
    parser.add_argument('--input', type=Path, help='JSON with keywords[] and intents[]; supports negative and explicit tag filters')
    args = parser.parse_args()
    payload = json.loads(args.input.read_text()) if args.input else dict(keywords=args.keywords, intents=args.intent)
    matcher = Matcher(with_proposed_aliases=args.with_proposed_aliases)
    print(json.dumps(matcher.match(payload.get('keywords', []), payload.get('intents', [])), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
