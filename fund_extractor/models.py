from dataclasses import dataclass


@dataclass
class FundValueMatch:
    value: str
    source: str
    page: int
    column_headings: str
