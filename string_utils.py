def reverse_string(text: str) -> str:
    """
    Validates that text is a string, raises a TypeError otherwise.
    Returns an empty string for empty input, and the reversed string otherwise.
    """
    if not isinstance(text, str):
        raise TypeError("Input must be a string")
    
    return text[::-1]