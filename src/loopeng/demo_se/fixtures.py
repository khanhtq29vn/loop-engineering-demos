"""Illustrative offline candidates; no AI made these patches.

They intentionally improve over 3 iterations to illustrate verifier feedback.
"""

CANDIDATES = [
'''from decimal import Decimal

def reconcile_ledger(entries):
    if not isinstance(entries, list):
        raise ValueError("entries must be a list")
    balances = {}
    for e in entries:
        if not isinstance(e, dict):
            raise ValueError("entry must be an object")
        txn = e['txn_id']
        account = e['account_id']
        amount = e['amount']
        if not isinstance(txn, str) or not txn.strip() or not isinstance(account, str) or not account.strip() or not isinstance(amount, str):
            raise ValueError("invalid field")
        value = Decimal(amount)
        if not value.is_finite() or value.as_tuple().exponent < -2:
            raise ValueError("invalid decimal amount")
        balances[account] = balances.get(account, Decimal('0')) + value
    return {k: f"{v:.2f}" for k, v in balances.items()}
''',
'''from decimal import Decimal, InvalidOperation

def reconcile_ledger(entries):
    if not isinstance(entries, list):
        raise ValueError('entries must be a list')
    seen = set()
    balances = {}
    for e in entries:
        if not isinstance(e, dict):
            raise ValueError('entry must be an object')
        try:
            txn, account, amount = e['txn_id'], e['account_id'], e['amount']
            if not isinstance(txn, str) or not txn.strip() or not isinstance(account, str) or not account.strip() or not isinstance(amount, str):
                raise ValueError('invalid fields')
            value = Decimal(amount)
            if not value.is_finite() or value.as_tuple().exponent < -2:
                raise ValueError('invalid amount')
        except (KeyError, InvalidOperation) as exc:
            raise ValueError('invalid entry') from exc
        if txn in seen:
            continue
        seen.add(txn)
        balances[account] = balances.get(account, Decimal('0')) + value
    return {k: f"{v:.2f}" for k, v in balances.items()}
''',
'''from decimal import Decimal, InvalidOperation

def reconcile_ledger(entries):
    if not isinstance(entries, list):
        raise ValueError('entries must be a list')
    seen = {}
    balances = {}
    for row in entries:
        if not isinstance(row, dict):
            raise ValueError('each entry must be a dictionary')
        try:
            txn = row['txn_id']
            account = row['account_id']
            amount = row['amount']
            if not isinstance(txn, str) or not txn.strip():
                raise ValueError('txn_id must be nonempty text')
            if not isinstance(account, str) or not account.strip():
                raise ValueError('account_id must be nonempty text')
            if not isinstance(amount, str):
                raise ValueError('amount must be text')
            value = Decimal(amount)
        except (KeyError, InvalidOperation) as exc:
            raise ValueError('invalid entry') from exc
        if not value.is_finite() or value.as_tuple().exponent < -2:
            raise ValueError('amount needs at most two decimal places')
        fingerprint = (account, value)
        if txn in seen:
            if seen[txn] != fingerprint:
                raise ValueError('conflicting transaction ID')
            continue
        seen[txn] = fingerprint
        balances[account] = balances.get(account, Decimal('0.00')) + value
    return {account: format(amount, '.2f') for account, amount in sorted(balances.items())}
''',
]

# Deliberate integrity attack, blocked before writing to any workspace.
TAMPER_PROPOSAL = {'path': 'tests_protected.py', 'content': 'def test_ok(): assert True'}
