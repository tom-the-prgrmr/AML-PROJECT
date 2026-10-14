"""Phase 9c dashboard figures, read from the tables and the evaluators of earlier phases.

Read only: nothing here writes a table or an audit row, and nothing imports the web layer.
"""

from aml.metrics.detections import detections
from aml.metrics.funnel import funnel
from aml.metrics.samples import auto_cleared_sample, suppression

__all__ = ["auto_cleared_sample", "detections", "funnel", "suppression"]
