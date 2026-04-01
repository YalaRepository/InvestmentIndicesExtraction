from dataclasses import dataclass


@dataclass
class FundValueMatch:
    value: str
    source: str
    page: int
