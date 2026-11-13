"""Turn reviewed tag mappings into a bounded, auditable literature corpus."""
from src.agent.understanding import explicit_tag_spans


def literature_scope(library, mapping, understanding=None):
    understanding = understanding or {}
    mappings = (mapping or {}).get('mappings', [])
    explicit = bool(explicit_tag_spans(understanding.get('raw_query','')) or
                    any(m.get('usage')=='explicit_tag_filter' for m in mappings))
    selected=[]
    for item in mappings:
        if explicit and item.get('usage')!='explicit_tag_filter':
            continue
        if item.get('requires_resolution') or item.get('status')!='matched':
            continue
        candidates=[c for c in item.get('candidates',[]) if c.get('review_status')=='approved' and
                    c.get('method') in {'exact_name','exact_path','controlled_alias','configured_alias'} and
                    c.get('relation','exact')=='exact']
        if candidates and (item.get('polarity')!='exclude' or explicit):
            selected.append((item,candidates))
    if not selected and not explicit:
        return {'mode':'unrestricted','reason':'no_reliable_tag_mapping','filters':[]}

    with library.lock:
        rows=library.db.execute("""SELECT p.*,s.content_key FROM papers p JOIN literature_search_sync s ON s.paper_id=p.id
            WHERE p.deleted=0 AND p.usage='normal' AND s.status='ready'""").fetchall()
        papers=[library.paper(row) for row in rows]
        papers=[p for p,row in zip(papers,rows) if library.search_index.content_key(p)==row['content_key']]
    universe={p['id'] for p in papers}
    members={}
    for paper in papers:
        for tag_id in paper['tag_ids']:
            members.setdefault(tag_id,set()).add(paper['id'])
    conditions={c['condition_id']:c for c in understanding.get('conditions',[])}
    groups,excluded,filters={},set(),[]
    for item,candidates in selected:
        tags={t for c in candidates for t in c.get('descendant_ids',[c['id']])}
        ids=set().union(*(members.get(t,set()) for t in tags))
        filters.append({'term':item.get('canonical') or item.get('term'),'paths':[c['path'] for c in candidates],
                        'tag_ids':sorted(tags),'polarity':item.get('polarity','include')})
        if item.get('polarity')=='exclude':
            excluded.update(ids)
            continue
        object_groups={conditions[cid].get('object_group','subject') for cid in item.get('condition_ids',[]) if cid in conditions}
        for group in object_groups or {item.get('object_group','subject')}:
            # Same dimension is OR; different dimensions are AND. Object
            # comparisons retain their pairs instead of mixing crop/region.
            dimension=candidates[0]['dimension_id']
            groups.setdefault(group,{}).setdefault(dimension,set()).update(ids)
    def intersect(dimensions):
        result=set(universe)
        for ids in dimensions.values(): result.intersection_update(ids)
        return result
    admitted=intersect(groups.pop('subject',{}))
    if groups:
        admitted.intersection_update(set().union(*(intersect(dims) for dims in groups.values())))
    admitted.difference_update(excluded)
    if explicit and (not selected or (mapping or {}).get('unresolved_filters') or any(m.get('requires_resolution') for m in mappings)):
        admitted.clear()

    # Filter Chroma before vector recall and expensive cross-encoder reranking.
    # Source variants cover the verified legacy collection as well as new IDs.
    from src.rag.documents import PAPERS_DIR
    chosen=[p for p in papers if p['id'] in admitted]
    sources=set()
    for paper in chosen:
        name=paper['filename']
        sources.update((name, f'data/papers/{name}', f'../data/papers/{name}', str((PAPERS_DIR/name).resolve()),
                        f"managed://{paper['id']}/{name}"))
    where={'$or':[{'paper_id':{'$in':sorted(admitted)}},
                  {'file_sha256':{'$in':sorted({p['sha256'] for p in chosen})}},
                  {'source':{'$in':sorted(sources)}}]} if admitted else None
    return {'mode':'explicit_tags' if explicit else 'inferred_tags','paper_ids':sorted(admitted),
            'paper_count':len(admitted),'total_papers':len(universe),'filters':filters,'where':where,
            'reason':'matched_tags' if admitted else 'tag_scope_empty'}


def scope_snapshot(scope):
    return {k:v for k,v in scope.items() if k!='where'}


def may_expand_scope(scope):
    """One bounded local retry; never relax explicit scope or mask an outage."""
    return (scope.get('mode')=='inferred_tags' and not scope.get('expanded')
            and not scope.get('retrieval_failed')
            and scope.get('paper_count',0)<scope.get('total_papers',0))
