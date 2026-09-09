"""Parse bounded reviewer receipts; no keyword or empty-answer approval."""

from task_protocol import parse_final_answer, ReceiptError

FINAL_ANSWER_MARKER = 'FINAL_ANSWER'
APPROVED_STATUS = 'approved'
REVIEW_STATUSES = {'approved', 'changes_requested', 'requirement_change', 'blocked'}


def review_passed(review_response):
    decision = structured_review_decision(review_response)
    return bool(decision and decision.get('status') == APPROVED_STATUS)


def structured_review_decision(response):
    return structured_final_answer_decision(response, REVIEW_STATUSES)


def structured_final_answer_decision(response, allowed_statuses):
    try:
        decision = parse_final_answer(response)
    except ReceiptError:
        return None
    status = decision.get('status')
    if isinstance(status, str) and status in allowed_statuses:
        return decision
    return None
