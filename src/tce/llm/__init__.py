"""Subscription-only LLM access for TCE.

CONTRACT (stable - other packages import only these names):

    from tce.llm import LLMRequest, LLMResult, complete, get_llm_client
    from tce.llm import LLMPolicyError, LLMUnavailable, POLICY_MODEL

- complete(req) enqueues (or reuses, by idempotency key) one llm_jobs row and
  waits for a subscription worker to finish it. It raises LLMUnavailable when
  the job is waiting for capacity, failed, or the wait timed out. It never
  calls a metered API and never substitutes another model.
- get_llm_client(agent_name) returns an object with `.messages.create(**kw)`
  shaped like the Anthropic SDK response (content[0].text, usage.*), so legacy
  call sites keep working while routing through complete().
  `.messages.batches` raises LLMPolicyError.
"""

from tce.llm.provider import (
    POLICY_MODEL,
    LLMPolicyError,
    LLMRequest,
    LLMResult,
    LLMUnavailable,
    complete,
    get_llm_client,
)

__all__ = [
    "POLICY_MODEL",
    "LLMPolicyError",
    "LLMRequest",
    "LLMResult",
    "LLMUnavailable",
    "complete",
    "get_llm_client",
]
