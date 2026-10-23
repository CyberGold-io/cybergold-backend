"""Funding outcomes mapped to the existing faucet HTTP contract by its route."""


class FundingError(Exception):
    def __init__(self, code, retry=None, replace=False, diagnostics=None):
        super().__init__(code)
        self.code, self.retry, self.replace = code, retry, replace
        self.diagnostics = diagnostics
