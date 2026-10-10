"""Shared limits for the bounded agent profile, including HTTP retries."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import math
import os
import time


class AgentStop(RuntimeError):
    def __init__(self, reason: str, message: str):
        self.reason = reason
        super().__init__(message)


class BudgetExhausted(AgentStop):
    def __init__(self, message: str, scope="run"):
        self.scope = scope
        super().__init__("budget_exhausted", message)


ACTIVE_BUDGET: ContextVar = ContextVar("patchproof_budget", default=None)
COMPLETION_CAP: ContextVar = ContextVar("patchproof_completion_cap", default=None)


@contextmanager
def completion_cap(value: int):
    token = COMPLETION_CAP.set(value)
    try:
        yield
    finally:
        COMPLETION_CAP.reset(token)


def integer(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise AgentStop("blocked_setup", f"{name} must be an integer.") from error
    if not low <= value <= high:
        raise AgentStop("blocked_setup", f"{name} must be between {low} and {high}.")
    return value


def optional_price(name: str):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as error:
        raise AgentStop("blocked_setup", f"{name} must be a finite positive number.") from error
    if not math.isfinite(value) or value <= 0:
        raise AgentStop("blocked_setup", f"{name} must be a finite positive number.")
    return value


@dataclass(frozen=True)
class Limits:
    steps: int = 40
    requests: int = 32
    tokens: int = 250_000
    commands: int = 64
    seconds: int = 1800
    cost_usd: float | None = None
    input_per_million: float | None = None
    output_per_million: float | None = None

    @classmethod
    def from_env(cls):
        values = dict(
            steps=integer("PATCHPROOF_MAX_AGENT_STEPS", 40, 2, 200),
            requests=integer("PATCHPROOF_MAX_MODEL_REQUESTS", 32, 1, 200),
            tokens=integer("PATCHPROOF_MAX_TOTAL_TOKENS", 250_000, 1000, 5_000_000),
            commands=integer("PATCHPROOF_MAX_SANDBOX_COMMANDS", 64, 1, 300),
            seconds=integer("PATCHPROOF_MAX_RUN_SECONDS", 1800, 30, 7200),
            cost_usd=optional_price("PATCHPROOF_MAX_COST_USD"),
            input_per_million=optional_price("PATCHPROOF_INPUT_USD_PER_MILLION"),
            output_per_million=optional_price("PATCHPROOF_OUTPUT_USD_PER_MILLION"),
        )
        if values["cost_usd"] is not None and any(values[key] is None for key in ("input_per_million", "output_per_million")):
            raise AgentStop("blocked_setup", "A dollar cap requires explicit input and output prices per million tokens.")
        return cls(**values)


class RunBudget:
    def __init__(self, limits: Limits, clock=time.monotonic):
        self.limits, self.clock = limits, clock
        self.started = clock()
        self.steps = self.requests = self.tokens = self.commands = 0
        self.cost = 0.0
        self.ledger: list[dict] = []
        self.on_change = lambda: None

    def remaining(self) -> float:
        remaining = self.limits.seconds - (self.clock() - self.started)
        if remaining <= 0:
            raise BudgetExhausted("Run deadline reached; no further inference or sandbox execution is allowed.")
        return remaining

    def step(self):
        self.remaining()
        if self.steps >= self.limits.steps:
            raise BudgetExhausted("Shared agent step budget exhausted.")
        self.steps += 1
        self.on_change()

    def reserve_request(self, request: dict) -> dict:
        self.remaining()
        if self.requests >= self.limits.requests:
            raise BudgetExhausted("Shared HTTP request budget exhausted (retries count).")
        # UTF-8 bytes plus message overhead conservatively reserve prompt tokens
        # without assuming a model-specific tokenizer. Unknown/failed usage keeps
        # the full reservation. No inferred provider pricing is used.
        prompt = 256 + sum(len(str(message.get("content", "")).encode("utf-8")) + 32
                           for message in request["messages"])
        output = request["max_tokens"]
        reserved = prompt + output
        price = self.price(prompt, output)
        if self.tokens + reserved > self.limits.tokens:
            raise BudgetExhausted("Insufficient total token budget for a conservatively reserved request.")
        if self.limits.cost_usd is not None and self.cost + price > self.limits.cost_usd:
            raise BudgetExhausted("Configured inference cost cap would be exceeded by this request.")
        self.requests += 1
        self.tokens += reserved
        self.cost += price
        entry = {"request": self.requests, "reserved_tokens": reserved,
                 "charged_tokens": reserved, "input_tokens": None, "output_tokens": None,
                 "usage": "reserved_unknown", "cost_usd": price if self.priced else None}
        self.ledger.append(entry)
        self.on_change()
        return entry

    @property
    def priced(self):
        return self.limits.input_per_million is not None and self.limits.output_per_million is not None

    def price(self, prompt: int, output: int) -> float:
        if not self.priced:
            return 0.0
        return (prompt * self.limits.input_per_million + output * self.limits.output_per_million) / 1_000_000

    def record_usage(self, entry: dict, usage):
        def value(key):
            return usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
        prompt, output = value("prompt_tokens"), value("completion_tokens")
        if all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in (prompt, output)):
            actual = prompt + output
            self.tokens += actual - entry["charged_tokens"]
            if self.priced:
                self.cost += self.price(prompt, output) - entry["cost_usd"]
            entry.update(charged_tokens=actual, input_tokens=prompt, output_tokens=output,
                         usage="reported", cost_usd=self.price(prompt, output) if self.priced else None)
        self.on_change()
        if self.tokens > self.limits.tokens or (self.limits.cost_usd is not None and self.cost > self.limits.cost_usd):
            raise BudgetExhausted("Reported usage exceeds the reserved limit; stopping before another call.")
        self.remaining()

    def command_timeout(self, requested: int) -> int:
        remaining = self.remaining()
        if self.commands >= self.limits.commands:
            raise BudgetExhausted("Shared sandbox command budget exhausted.")
        if remaining < 1:
            raise BudgetExhausted("Insufficient run time for another sandbox command.")
        self.commands += 1
        self.on_change()
        return min(requested, int(remaining))

    def snapshot(self) -> dict:
        return {"limits": dict(vars(self.limits)), "steps": self.steps, "http_requests": self.requests,
                "charged_tokens": self.tokens, "sandbox_commands": self.commands,
                "elapsed_seconds": round(self.clock() - self.started, 3),
                "inference_cost_usd": round(self.cost, 8) if self.priced else None,
                "cost_status": "operator_priced" if self.priced else "not_configured",
                "scope": "inference cost only; sandbox billing excluded",
                "requests": [dict(entry) for entry in self.ledger]}


class BudgetedState:
    """Keep all SDK states/branches under one budget, without retaining run writes."""
    def __init__(self, state, budget: RunBudget):
        self.state, self.budget = state, budget

    def __getattr__(self, name):
        return getattr(self.state, name)

    def apply_files(self, **kwargs):
        self.budget.remaining()
        return BudgetedState(self.state.apply_files(**kwargs), self.budget)

    def run(self, **kwargs):
        kwargs["timeout"] = self.budget.command_timeout(kwargs.get("timeout", 600))
        operation = self.state.run(**kwargs)
        budget = self.budget

        class Operation:
            def wait(self):
                result = operation.wait()
                budget.remaining()
                return BudgetedState(result, budget)
        return Operation()
