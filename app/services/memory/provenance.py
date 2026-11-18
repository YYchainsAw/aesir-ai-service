"""Server-authored trace references in the existing MemoryEntry.tags field.

Legacy entries without trace tags remain explicitly unattributed. No source is
inferred from their text, and no executable client action is inferred here.
"""
from app.scoped.context import current_scope


def merge_tags(*groups):
    """Keep original plus latest 31 references per trace key; journals own history."""
    values = list(dict.fromkeys(tag for group in groups for tag in group))
    by_key = {}
    for tag in values:
        if tag.startswith('trace.') and '=' in tag:
            by_key.setdefault(tag.split('=', 1)[0], []).append(tag)
    keep = {tag for refs in by_key.values() for tag in (refs[:1] + refs[-31:])}
    return [tag for tag in values if not tag.startswith('trace.') or '=' not in tag or tag in keep]


def trace_tags(tags=()):
    from app.scoped.requests import current_request_id
    from app.scoped.trace import logical_request_id
    scope = current_scope()
    values = list(tags)
    if scope is not None:
        values += [f'trace.{key}={value}' for key, value in scope.npc.as_dict().items()]
        values += [f'trace.run_id={scope.run_id}', f'trace.memory_epoch={scope.memory_epoch}']
        request_id = current_request_id() or logical_request_id()
        if request_id:
            values.append(f'trace.request_id={request_id}')
    return merge_tags(values)
