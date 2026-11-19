"""Internal references, never accepted from model-generated facts or clients."""
from app.schemas.memory import MemorySnapshot


def request_id():
    from app.scoped.requests import current_request_id
    from app.scoped.trace import logical_request_id
    from app.scoped.context import current_scope
    return (current_request_id() or logical_request_id() or '') if current_scope() else ''


def entries(snapshot):
    return [*snapshot.archive, *snapshot.summaries, *snapshot.short_term]


def tag_values(entry, key):
    prefix = f'trace.{key}='
    return {tag[len(prefix):] for tag in entry.tags if tag.startswith(prefix)}


def current_references(snapshot: MemorySnapshot):
    rid = request_id()
    if not rid:
        return []
    return [f'r:{rid}', *(f'e:{entry.entry_id}' for entry in entries(snapshot)
                         if rid in tag_values(entry, 'request_id'))]


def forget_plan(snapshot, targets, session_store, npc):
    """Compute dependency closure before any mutation, including session replies."""
    records = entries(snapshot)
    removed = {str(value) for value in targets}
    requests = set()
    while True:
        previous = (removed.copy(), requests.copy())
        for entry in records:
            if (str(entry.entry_id) in removed or
                    'trace.attribution_truncated=true' in entry.tags or
                    tag_values(entry, 'depends_on_request_id') & requests or
                    tag_values(entry, 'depends_on_entry_id') & removed):
                removed.add(str(entry.entry_id))
                requests.update(tag_values(entry, 'request_id'))
        requests.update(session_store.affected_requests(npc, removed, requests))
        if previous == (removed, requests):
            break
    return removed, requests


def prune_snapshot(snapshot, removed, requests):
    for layer in ('archive', 'summaries', 'short_term'):
        setattr(snapshot, layer, [entry for entry in getattr(snapshot, layer)
                                 if str(entry.entry_id) not in removed])
    refs = {*(f'e:{value}' for value in removed), *(f'r:{value}' for value in requests)}
    # Unknown legacy attribution is cleared conservatively; known unrelated
    # topics survive. A mixed topic is cleared as a whole, not reinterpreted.
    snapshot.impressions = [item for item in snapshot.impressions
                            if snapshot._memory_links.get(item.topic)
                            and '' not in snapshot._memory_links[item.topic]
                            and not refs.intersection(snapshot._memory_links[item.topic])]
    kept = {item.topic for item in snapshot.impressions}
    snapshot._memory_links = {topic: values for topic, values in snapshot._memory_links.items() if topic in kept}
