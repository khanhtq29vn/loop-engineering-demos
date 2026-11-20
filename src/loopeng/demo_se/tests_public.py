"""Visible tests supplied to the software proposer and verifier."""
import unittest
from ledger import reconcile_ledger


def e(txn, account, amount):
    return {'txn_id': txn, 'account_id': account, 'amount': amount}


class PublicAcceptance(unittest.TestCase):
    def test_basic_exact_aggregation(self):
        self.assertEqual(reconcile_ledger([e('1','A','2.25'),e('2','A','-0.10'),e('3','B','1.00')]), {'A':'2.15','B':'1.00'})

    def test_empty(self):
        self.assertEqual(reconcile_ledger([]), {})

    def test_identical_replay_ignored(self):
        self.assertEqual(reconcile_ledger([e('x','A','0.10'),e('x','A','0.10')]), {'A':'0.10'})

    def test_amount_string_and_precision(self):
        with self.assertRaises(ValueError):
            reconcile_ledger([e('a','B', 0.1)])
        with self.assertRaises(ValueError):
            reconcile_ledger([e('b','B','0.001')])
