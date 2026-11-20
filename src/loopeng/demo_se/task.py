"""Specification used in the programming-loop example."""
SPEC = '''Implement reconcile_ledger(entries):
- entries is a list of dictionaries, each with txn_id, account_id, amount.
- txn_id and account_id must be nonempty strings.
- amount must be a finite decimal STRING of at most 2 fractional places.
- A repeated identical txn_id/account_id/amount event is an idempotent replay: ignore it.
- A txn_id reused for any different account_id or amount raises ValueError.
- Sum signed amounts per account exactly; return mapping account_id -> two-decimal STRING.
- Empty input returns {}. Invalid types/values raise ValueError.
- Do NOT edit or generate tests. Produce only code for ledger.py.
'''

BASELINE = '''from decimal import Decimal\n\ndef reconcile_ledger(entries):\n    balances = {}\n    for e in entries:\n        account = e["account_id"]\n        balances[account] = balances.get(account, 0) + float(e["amount"])\n    return {a: f"{v:.2f}" for a, v in balances.items()}\n'''
