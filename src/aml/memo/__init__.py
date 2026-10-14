"""Phase 8d: classify transaction memos into a closed set of categories with the local LLM.

A memo label is a ranking feature and nothing more: no module here raises an alert, records a
decision, changes a case or suppresses anything. Memo text is untrusted data. A rule layer catches
known instruction-like text before any model call, the model only ever sees one memo as a JSON
string value, and its reply is accepted only as one of six fixed category names.
"""
