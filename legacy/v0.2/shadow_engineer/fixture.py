ISSUE = "normalize_tags should strip whitespace, drop empty tags, and deduplicate case-insensitively while preserving first spelling and order."
SOURCE = {
    "app/__init__.py": "",
    "app/tags.py": "def normalize_tags(tags):\n    return list(dict.fromkeys(tags))\n",
    "tests/test_existing.py": "from app.tags import normalize_tags\ndef test_empty():\n    assert normalize_tags([]) == []\ndef test_order():\n    assert normalize_tags(['b', 'a', 'b']) == ['b', 'a']\n",
}
REGRESSION = "from app.tags import normalize_tags\ndef test_whitespace_and_case():\n    assert normalize_tags([' Python ', '', 'python', 'AI', ' ai ', ' ']) == ['Python', 'AI']\n"
CANDIDATES = [
    {"app/tags.py": "def normalize_tags(tags):\n    return list(dict.fromkeys(tags))\n"},
    {"app/tags.py": "def normalize_tags(tags):\n    return sorted(set(t.strip().lower() for t in tags if t.strip()))\n"},
    {"app/tags.py": "def normalize_tags(tags):\n    seen = set()\n    result = []\n    for tag in tags:\n        tag = tag.strip()\n        key = tag.casefold()\n        if tag and key not in seen:\n            seen.add(key)\n            result.append(tag)\n    return result\n"},
]
