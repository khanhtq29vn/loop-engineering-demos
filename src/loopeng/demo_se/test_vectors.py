"""Host-side acceptance oracle. Expected answers are NEVER mounted into Docker.

The candidate sees test INPUTS only via stdin. The host compares actual results
with expected outputs/exceptions after the sandbox process exits.
"""
from __future__ import annotations


def event(t,account,amount):
    return {'txn_id':t,'account_id':account,'amount':amount}


def public_cases():
    return [
        {'name':'exact_aggregation','entries':[event('1','A','2.25'),event('2','A','-0.10'),event('3','B','1.00')], 'expected':{'A':'2.15','B':'1.00'}},
        {'name':'empty','entries':[],'expected':{}},
        {'name':'idempotent_replay','entries':[event('x','A','0.10'),event('x','A','0.10')],'expected':{'A':'0.10'}},
        {'name':'invalid_nonstring','entries':[event('a','B',0.1)],'expected_exception':'ValueError'},
        {'name':'too_many_fractional_places','entries':[event('b','B','0.001')],'expected_exception':'ValueError'},
    ]


def protected_cases():
    return [
        {'name':'conflict_amount','entries':[event('id','A','2.00'),event('id','A','3.00')],'expected_exception':'ValueError'},
        {'name':'conflict_account','entries':[event('id','A','2.00'),event('id','B','2.00')],'expected_exception':'ValueError'},
        {'name':'non_finite_nan','entries':[event('id','A','NaN')],'expected_exception':'ValueError'},
        {'name':'non_finite_inf','entries':[event('id','A','Infinity')],'expected_exception':'ValueError'},
        {'name':'missing_field','entries':[{'account_id':'A','amount':'2.00'}],'expected_exception':'ValueError'},
        {'name':'empty_txn_id','entries':[event('','A','2.00')],'expected_exception':'ValueError'},
        {'name':'empty_account_id','entries':[event('id','','2.00')],'expected_exception':'ValueError'},
        {'name':'lots_of_pennies','entries':[event(f'id{i}','A','0.01') for i in range(100)],'expected':{'A':'1.00'}},
        {'name':'negative_balance','entries':[event('r','B','-1.23')],'expected':{'B':'-1.23'}},
        {'name':'invalid_boolean','entries':[event('id','A',True)],'expected_exception':'ValueError'},
    ]
