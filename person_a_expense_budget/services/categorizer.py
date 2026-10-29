"""Rule-based merchant categorizer for Person A.

Transparent, deterministic keyword rules - no ML, so every suggestion is
explainable in a demo/viva. Rules are evaluated in a fixed priority order;
the first matching rule wins.
"""
from typing import Optional

# Priority order matters: a "Netflix" charge is a subscription before it is
# entertainment; "Amazon" (without Prime) is shopping.
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    (
        "Subscriptions",
        [
            "netflix", "spotify", "prime", "hotstar", "jio cinema", "jiocinema",
            "sonyliv", "zee5", "youtube premium", "gaana", "jiosaavn", "wynk",
            "adobe", "microsoft 365", "office 365", "icloud", "google one",
            "canva", "chatgpt", "notion", "subscription",
        ],
    ),
    (
        "Entertainment",
        [
            "bookmyshow", "pvr", "inox", "cinema", "movie", "steam", "epic games",
            "playstation", "xbox", " bowling", "amusement", "event", "concert",
        ],
    ),
    (
        "Food",
        [
            "swiggy", "zomato", "restaurant", "hotel", "cafe", "coffee", "starbucks",
            "cbcr", "domino", "pizza", "burger", "kfc", "mcdonald", "dunzo",
            "grocery", "supermarket", "dmart ready", "aavin", "bakery", "food",
        ],
    ),
    (
        "Travel",
        [
            "uber", "ola", "rapido", "irctc", "redbus", "abhibus", "indigo",
            "vistara", "air india", "metro", "suburban rail", "petrol", "fuel",
            "indian oil", "hp petrol", "bp fuel", "toll", "fastag", "parking",
        ],
    ),
    (
        "Bills",
        [
            "electricity", "tneb", "tangedco", "water bill", "gas bill",
            "broadband", "act fibernet", "jiofiber", "airtel", "jio recharge",
            "bsnl", "vodafone", "recharge", "mobile bill", "rent", "maintenance",
        ],
    ),
    (
        "Shopping",
        [
            "amazon", "flipkart", "myntra", "ajio", "nykaa", "decathlon", "croma",
            "reliance digital", "vijay sales", "ikea", "pepperfry", "shopping",
            "mall", "zalora", "tata cliq",
        ],
    ),
]

FALLBACK_CATEGORY = "Uncategorized"


def categorize_merchant(merchant: str) -> tuple[str, Optional[str], str]:
    """Return (category, matched_keyword, confidence) for a merchant string.

    confidence is "rule" when a keyword matched, "fallback" otherwise.
    """
    needle = (merchant or "").lower().strip()
    if needle:
        for category, keywords in CATEGORY_RULES:
            for keyword in keywords:
                if keyword in needle:
                    return category, keyword, "rule"
    return FALLBACK_CATEGORY, None, "fallback"
