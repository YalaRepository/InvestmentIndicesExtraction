from pathlib import Path


def detect_provider(path: Path) -> str:
    name = path.name.lower()
    if "allan gray" in name:
        return "Allan Gray"
    if "agp stable" in name:
        return "AGP Stable"
    if "ijg" in name:
        return "IJG"
    if "m&g" in name or "mandg" in name:
        return "M&G"
    if "ninety one" in name:
        return "Ninety One"
    if "sanlam" in name:
        return "Sanlam"
    if "allegrow" in name:
        return "Allegrow"
    if "contributions_and_withdrawals" in name:
        return "NAM Contributions"
    if "monthly_reports" in name:
        return "NAM Monthly"
    return "Unknown"
