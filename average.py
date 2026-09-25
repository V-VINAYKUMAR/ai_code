def calculate_average(numbers: list) -> float:
    """
    Calculate the arithmetic mean of a list of numbers.

    Parameters:
    numbers (list): A list of numerical values (int or float).

    Returns:
    float: The average of the numbers. Returns 0.0 if the list is empty.

    Raises:
    TypeError: If the input is not a list or contains non-numerical values.
    """
    if not isinstance(numbers, list):
        raise TypeError("Input must be a list")

    if not numbers:
        return 0.0

    total = 0.0
    for number in numbers:
        if not isinstance(number, (int, float)):
            raise TypeError("All elements in the list must be integers or floats")
        total += number

    return total / len(numbers)