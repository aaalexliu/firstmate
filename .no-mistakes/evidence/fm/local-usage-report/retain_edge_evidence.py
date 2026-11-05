import importlib.util,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('cases',Path('tests/usage_report_cases.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
E=Path('~/.no-mistakes/evidence/01M6MEX9WY04H2GWMWE52JER8G')
observed={}
for method in ['test_transport_overlap_repairs_native_roles_in_both_orders_and_replays','test_weekly_fit_requires_hourly_fresh_same_window_pairs','test_quota_resets_do_not_train_a_rate','test_unavailable_stale_multiple_lanes_not_fitted']:
 t=m.UsageReport();t.setUp()
 try:
  getattr(t,method)()
  # Retain actual public-product output, rather than the assertions' pass/fail summary.
  observed[method]=dict(facts=t.records(),quota=t.records('quota'),fits=t.records('fits'))
 finally:t.doCleanups()
text=json.dumps(observed,indent=2)
assert 'SECRET_' not in text and 'SENSITIVE_ACCOUNT' not in text
(E/'edge-accounting-observed.json').write_text(text)
fit=observed['test_weekly_fit_requires_hourly_fresh_same_window_pairs']['fits']
print(json.dumps({'actual_fitted_store':fit},indent=2))
