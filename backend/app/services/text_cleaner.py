import re
from app.database import get_database


class TextCleaner:
    """Applies user-configurable text cleaning rules from the database."""

    def __init__(self):
        self.db = get_database()

    def clean(self, text: str) -> str:
        if not text:
            return ""
        rules = self.db.get_text_cleaning_rules(enabled_only=True)
        for rule in rules:
            text = self._apply_rule(text, rule)
        return text

    def clean_with_all_rules(self, text: str) -> str:
        """Apply all rules (including disabled) — for testing."""
        if not text:
            return ""
        rules = self.db.get_text_cleaning_rules(enabled_only=False)
        for rule in rules:
            text = self._apply_rule(text, rule)
        return text

    def clean_custom_rules(self, text: str, rules: list) -> str:
        """Apply a custom list of rule dicts — for ad-hoc testing."""
        if not text:
            return ""
        for rule in rules:
            text = self._apply_rule(text, rule)
        return text

    @staticmethod
    def _apply_rule(text: str, rule: dict) -> str:
        try:
            if rule['match_type'] == 'regex':
                if rule['rule_type'] == 'remove':
                    text = re.sub(rule['find_text'], '', text)
                else:
                    text = re.sub(rule['find_text'], rule['replace_text'], text)
            else:
                if rule['rule_type'] == 'remove':
                    text = text.replace(rule['find_text'], '')
                else:
                    text = text.replace(rule['find_text'], rule['replace_text'])
        except Exception as e:
            print(f"⚠️ Text cleaning rule #{rule.get('id', '?')} failed: {e}")
        return text
