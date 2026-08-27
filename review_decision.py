"""Parse structured reviewer final answers."""

import json
import re


FINAL_ANSWER_MARKER = "FINAL_ANSWER"
APPROVED_STATUS = "approved"


def review_passed(review_response, approval_token):
    """Return whether a reviewer response approves the current gate.

    Prefer the structured FINAL_ANSWER JSON contract. Fall back to the legacy
    token check so existing tests, mocks, and older agent transcripts continue
    to work.
    """
    if review_response is None or not str(review_response).strip():
        return True
    response = str(review_response)
    decision = structured_review_decision(response)
    if decision is not None:
        return (
            decision.get("status") == APPROVED_STATUS
            and decision.get("approval_token") == approval_token
        )
    return approval_token in response


def structured_review_decision(response):
    """Extract the last FINAL_ANSWER JSON object from a response."""
    for candidate in _candidate_json_texts(response):
        parsed = _parse_json_object(candidate)
        if _is_review_decision(parsed):
            return parsed
    return None


def structured_final_answer_decision(response, allowed_statuses):
    """Extract a FINAL_ANSWER JSON object with a status allowed by one caller."""
    if not isinstance(response, str):
        return None
    marker_index = response.rfind(FINAL_ANSWER_MARKER)
    if marker_index < 0:
        return None
    tail = response[marker_index + len(FINAL_ANSWER_MARKER):].lstrip()
    if tail.startswith(":"):
        tail = tail[1:].lstrip()
    candidates = [tail]
    if tail.startswith("```"):
        fence_match = re.match(r"```(?:json)?\s*(.*?)\s*```", tail, re.DOTALL | re.IGNORECASE)
        if fence_match:
            candidates.insert(0, fence_match.group(1))
    for candidate in candidates:
        parsed = _parse_json_object(candidate)
        if (
            isinstance(parsed, dict)
            and parsed.get("status") in allowed_statuses
            and "approval_token" in parsed
        ):
            return parsed
    return None


def _candidate_json_texts(response):
    marker_index = response.rfind(FINAL_ANSWER_MARKER)
    if marker_index >= 0:
        tail = response[marker_index + len(FINAL_ANSWER_MARKER):].lstrip()
        if tail.startswith(":"):
            tail = tail[1:].lstrip()
        if tail.startswith("```"):
            fence_match = re.match(r"```(?:json)?\s*(.*?)\s*```", tail, re.DOTALL | re.IGNORECASE)
            if fence_match:
                yield fence_match.group(1)
        yield tail

    fenced_blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL | re.IGNORECASE)
    for block in reversed(fenced_blocks):
        yield block


def _parse_json_object(text):
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _end = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _is_review_decision(value):
    return (
        isinstance(value, dict)
        and value.get("status") in {APPROVED_STATUS, "changes_requested", "requirement_change"}
        and "approval_token" in value
    )
