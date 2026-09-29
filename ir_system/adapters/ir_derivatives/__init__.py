"""Self-computed derivatives analytics for IR System (basis monitor, implied volatility, Greeks, surfaces).

Nothing in this package imports ir_search: the bridge injects a data-fetching callable, so the
analytics stay testable with fakes and the bridge remains the single ir_search boundary.
"""
