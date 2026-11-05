"""Public contract failures contain categories and known field names, never model data."""
from collections.abc import Mapping
import math
import time

from pydantic import ValidationError


CONTRACT_CATEGORIES = frozenset({
    'invalid_json', 'empty_response', 'schema_incompatible', 'missing_required_field',
    'incorrect_type', 'pydantic_validation_error', 'unknown_evidence_reference',
    'unknown_memory_reference', 'stale_context', 'internal_error',
})
PROVIDER_CATEGORIES = frozenset({
    'disabled', 'invalid_provider', 'invalid_config', 'invalid_request', 'context_too_large',
    'model_missing', 'unavailable', 'server_error', 'response_too_large', 'malformed_response',
    'timeout', 'network_error', 'thinking_unsupported', 'schema_mismatch', 'cancelled',
})
PUBLIC_CATEGORIES = CONTRACT_CATEGORIES | PROVIDER_CATEGORIES
FIELD_NAMES = frozenset({
    'version', 'thoughts', 'proposal', 'reconsiderations', 'category', 'text', 'evidence_ids',
    'memory_ids', 'uncertainty', 'intent', 'preferred_subject', 'motivation', 'constraints',
    'priority', 'ttl_seconds', 'memory_id', 'question', 'source_event_ids',
    'source_memory_ids', 'expires_at', 'captured_at', 'context_id',
    'message', 'content', 'schema',
})
COUNTERS = frozenset({'invalid_evidence_references', 'invalid_memory_references',
                      'referenced_facts', 'referenced_memories', 'accepted_thoughts'})
FLAGS = frozenset({'json_valid', 'pydantic_valid', 'parser_accepted'})


def _fields(values):
    if not isinstance(values, (list, tuple, set)):
        return []
    result=set()
    for value in values:
        if isinstance(value,str):
            parts=value.split('.')
            known=[part for part in parts if part in FIELD_NAMES or part.isascii() and part.isdigit() and len(part)<=7]
        elif isinstance(value,(tuple,list)):
            # Pydantic uses ints for array indexes. A numeric string here is an
            # arbitrary extra object key, so it must not be exposed as an index.
            known=[str(part) for part in value if type(part) is int and 0<=part<=1000000
                   or isinstance(part,str) and part in FIELD_NAMES]
        else:
            continue
        # Unknown keys (including extra fields supplied by a model) never leave this boundary.
        if any(part in FIELD_NAMES for part in known):result.add('.'.join(known))
    return sorted(result)[:32]


def _public(value, fallback='internal_error'):
    value=value if isinstance(value,Mapping) else {}
    category=value.get('category',fallback)
    if not isinstance(category,str) or category not in PUBLIC_CATEGORIES:category='internal_error'
    result={'category':category,'fields':_fields(value.get('fields',()))}
    for key in COUNTERS:
        count=value.get(key)
        if type(count) is int and 0<=count<=1000000:result[key]=count
    for key in FLAGS:
        flag=value.get(key)
        if type(flag) is bool:result[key]=flag
    return result


class MindContractError(ValueError):
    def __init__(self, category, fields=(), diagnostics=None):
        public=_public({**(dict(diagnostics) if isinstance(diagnostics,Mapping) else {}),
                        'category':category,'fields':fields})
        self.category=public['category']
        self.fields=public['fields']
        self.diagnostics=public
        super().__init__(self.category)

    def diagnostic(self):
        return _public(self.diagnostics)


def classify_validation_error(exc):
    """Read Pydantic error types/locations only, with no input, ctx or messages."""
    if not isinstance(exc,ValidationError):return MindContractError('internal_error')
    errors=exc.errors(include_url=False,include_context=False,include_input=False)
    types={error.get('type') for error in errors}
    category=('missing_required_field' if 'missing' in types else
              'incorrect_type' if any(isinstance(kind,str) and (kind.endswith('_type') or kind=='none_required') for kind in types) else
              'schema_incompatible' if 'literal_error' in types else 'pydantic_validation_error')
    return MindContractError(category,[error.get('loc',()) for error in errors],
                             {'json_valid':True,'pydantic_valid':False})


def safe_public_error(exc):
    """Sanitize exceptions from either the canonical parser or an optional provider."""
    if isinstance(exc,ValidationError):return classify_validation_error(exc).diagnostic()
    diagnostics=getattr(exc,'diagnostics',None)
    category=getattr(exc,'category','internal_error')
    return _public(diagnostics,category)


safe_error=safe_public_error


def ensure_fresh_context(context, *, clock=None):
    """Optional expiry boundary for inference; parsing historical proofs stays time independent."""
    if not isinstance(context,dict):raise MindContractError('incorrect_type') from None
    if 'expires_at' not in context:return
    expiry=context['expires_at']
    if type(expiry) not in (int,float) or not math.isfinite(expiry):
        raise MindContractError('incorrect_type',['expires_at']) from None
    if (clock or time.time)()>=expiry:
        raise MindContractError('stale_context',['expires_at']) from None
