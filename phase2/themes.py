"""Fixed theme taxonomy and keyword maps for pre-routing."""

THEMES = [
    "Onboarding & Account Setup",
    "KYC & Verification",
    "Payments & Transactions",
    "Portfolio & Statements",
    "Performance & App Stability",
]

THEME_DESCRIPTIONS = {
    "Onboarding & Account Setup": "Registration, first login, account activation, app navigation for new users",
    "KYC & Verification": "Document upload, video verification, rejection reasons, re-submission loops",
    "Payments & Transactions": "Fund transfers, SIP setup, order execution, payment failures, UPI issues",
    "Portfolio & Statements": "P&L display, holdings view, statement downloads, tax documents",
    "Performance & App Stability": "App crashes, slow load times, UI glitches, login issues, battery usage",
}

THEME_KEYWORDS: dict[str, list[str]] = {
    "Onboarding & Account Setup": [
        "signup", "sign up", "register", "registration", "login", "log in",
        "account setup", "onboard", "first time", "new user", "create account",
    ],
    "KYC & Verification": [
        "kyc", "verify", "verification", "document", "pan card", "aadhaar",
        "aadhar", "video kyc", "identity", "rejected",
    ],
    "Payments & Transactions": [
        "payment", "upi", "withdraw", "withdrawal", "deposit", "transfer",
        "sip", "order", "transaction", "add money", "pay", "refund", "charges",
        "brokerage", "trading",
    ],
    "Portfolio & Statements": [
        "portfolio", "holding", "holdings", "statement", "pnl", "p&l", "profit",
        "loss", "tax", "report", "capital gain",
    ],
    "Performance & App Stability": [
        "crash", "crashes", "slow", "lag", "hang", "hanging", "freeze", "bug",
        "glitch", "loading", "stuck", "battery", "slippage", "worst app",
    ],
}
