"""Small shared helpers with no project dependencies."""
import re
import unidecode

def clean_title(title):
    """Convert a book title to an SEO-friendly "slug" (URL/file-name safe).

    Example: "Đấu Phá Thương Khung!" -> "dau-pha-thuong-khung".

    Args:
        title: any value (usually a Vietnamese str); None/"" are allowed.

    Returns:
        Lowercase ASCII slug with words joined by single hyphens, or "" if
        the title is empty or contains nothing usable.

    Used for `books.seo_title_basic`, which is part of DOCX/cover file names.
    """
    if not title:
        return ""
    title = str(title)
    # unidecode transliterates Unicode to closest ASCII: "Đấu" -> "Dau".
    title = unidecode.unidecode(title)
    title = title.lower()
    # Regex pieces: [^...] = any char NOT in the set; \w = letter/digit/_;
    # \s = whitespace; '-' literal. So: drop punctuation and symbols.
    title = re.sub(r'[^\w\s-]', '', title)
    # One or more whitespace chars (`+`) -> a single hyphen.
    title = re.sub(r'[\s]+', '-', title)
    # Collapse runs of hyphens ("a--b" -> "a-b").
    title = re.sub(r'-+', '-', title)
    title = title.strip('-')
    # `x if cond else y` is Python's ternary expression. (Here title is
    # already a str, so this is equivalent to `return title`.)
    return title if title else ""
