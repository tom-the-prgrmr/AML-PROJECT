"""Phase 8: the local investigation assistant (knowledge layer, retrievers, answering).

Importing the package registers the `llm` narrative generator, so ``cases.summary.generator: llm``
can be chosen anywhere the CLI runs.
"""

from aml.assistant.narrative import LlmNarrativeGenerator
from aml.cases.narrative import register_generator

register_generator("llm", lambda settings: LlmNarrativeGenerator(settings))
