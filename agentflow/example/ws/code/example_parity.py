import json
ok = all((i % 2 == 0) for i in (0, 2, 4, 6, 8))
print('REPRO_RESULT: ' + json.dumps({
    'result': 'supports' if ok else 'refutes',
    'observations': {'n_checked': 5},
    'counterexample': None,
    'negation_kind': 'not_proved',
}))
