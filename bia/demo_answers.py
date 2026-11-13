"""Compatibility entry point. Demo and production share one implementation."""
import sys
import answer_engine
sys.modules[__name__] = answer_engine
