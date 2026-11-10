"""Pagination helpers."""


def page_count(total_items: int, per_page: int) -> int:
    """Number of pages needed to show `total_items` items."""
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    return -(-total_items // per_page)


def paginate(items: list, page: int, per_page: int) -> list:
    """Items on the 1-based `page`. Pages past the end are empty."""
    if page < 1:
        raise ValueError("page numbers start at 1")
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    start = (page - 1) * per_page
    return items[start : start + per_page]


def page_window(current: int, total_pages: int, size: int = 5) -> list[int]:
    """Page numbers to show in a pager.

    Returns `size` consecutive pages centred on `current`. Near the first or last
    page the window is shifted, not shortened, so it still holds `size` pages
    (or all pages if there are fewer than `size`).
    """
    if total_pages <= 0:
        return []
    size = min(size, total_pages)
    start = current - size // 2
    start = max(1, min(start, total_pages - size + 1))
    return list(range(start, start + size))
