"""Effective label availability, shared by tagging and query matching."""


def association_counts(tags: list[dict], assignments: list[set[str]]) -> dict[str, dict[str, int]]:
    """Count each record once per tag; direct assignments take precedence."""
    by_id = {tag['id']: tag for tag in tags}
    ancestors = {}
    for identifier, tag in by_id.items():
        inherited, seen, parent = set(), {identifier}, tag.get('parent_id')
        while parent in by_id and parent not in seen:
            node = by_id[parent]
            if node['dimension_id'] != tag['dimension_id']:
                break
            seen.add(parent)
            inherited.add(parent)
            parent = node.get('parent_id')
        ancestors[identifier] = inherited
    counts = {identifier: {'direct': 0, 'indirect': 0} for identifier in by_id}
    for assigned in assignments:
        direct = assigned & by_id.keys()
        indirect = set()
        for identifier in direct:
            counts[identifier]['direct'] += 1
            indirect.update(ancestors[identifier])
        for identifier in indirect - direct:
            counts[identifier]['indirect'] += 1
    return counts


def enabled_tag_ids(taxonomy: dict) -> set[str]:
    dimensions = {item['id']: item for item in taxonomy.get('dimensions', [])}
    tags = {item['id']: item for item in taxonomy.get('tags', [])}
    enabled = set()
    for identifier, tag in tags.items():
        dimension = dimensions.get(tag['dimension_id'])
        if not dimension or not dimension.get('enabled', True):
            continue
        node, seen = tag, set()
        while node:
            if (node['id'] in seen or not node.get('enabled', True)
                    or node['dimension_id'] != tag['dimension_id']):
                break
            seen.add(node['id'])
            parent = node.get('parent_id')
            if not parent:
                enabled.add(identifier)
                break
            node = tags.get(parent)
    return enabled
