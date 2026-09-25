from typing import List, Union

def calculate_average(numbers: List[Union[int, float]]) -> float:
    """
    Calculate the arithmetic mean of a list of numbers.

    Parameters:
    numbers (List[Union[int, float]]): A list of numerical values (int or float).

    Returns:
    float: The average of the numbers. Returns 0.0 if the list is empty.

    Raises:
    TypeError: If the input is not a list or contains non-numerical values.
    """
    if not isinstance(numbers, list):
        raise TypeError("Input must be a list of numbers.")
    
    if not numbers:
        return 0.0
    
    total = 0.0
    for num in numbers:
        if not isinstance(num, (int, float)) or isinstance(num, bool):
            raise TypeError("All elements in the list must be integers or floats.")
        total += num
        
    return total / len(numbers)