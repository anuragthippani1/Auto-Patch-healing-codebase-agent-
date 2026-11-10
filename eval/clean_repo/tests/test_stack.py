import pytest

from toolkit.stack import Stack, balanced_brackets


def test_push_and_pop_are_last_in_first_out():
    stack = Stack()
    stack.push(1)
    stack.push(2)
    assert stack.pop() == 2
    assert stack.pop() == 1


def test_pop_from_empty_stack_fails():
    with pytest.raises(IndexError):
        Stack().pop()


def test_peek_does_not_remove():
    stack = Stack()
    stack.push("a")
    assert stack.peek() == "a"
    assert len(stack) == 1


def test_is_empty():
    stack = Stack()
    assert stack.is_empty()
    stack.push(1)
    assert not stack.is_empty()


def test_balanced_brackets_accepts_nested_pairs():
    assert balanced_brackets("(a[b]{c})")
    assert balanced_brackets("")
    assert balanced_brackets("no brackets")


def test_balanced_brackets_rejects_mismatch_and_unclosed():
    assert not balanced_brackets("(]")
    assert not balanced_brackets("((")


def test_balanced_brackets_rejects_close_before_open():
    assert balanced_brackets(")(") is False
    assert balanced_brackets("())") is False
