from typing import List, Union

def calculate_average(numbers: List[Union[int, float]]) -> float:
    """
    Calculate the arithmetic mean of a list of numbers.
    Returns 0.0 if the input list is empty.

    Args:
        numbers (List[Union[int, float]]): A list of numerical values.

    Returns:
        float: The average of the numbers, or 0.0 if the list is empty.

    Raises:
        TypeError: If the input is not a list or contains non-numerical values.
    """
    if not isinstance(numbers, list):
        raise TypeError("Input must be a list")
    
    if not numbers:
        return 0.0
        
    for number in numbers:
        if not isinstance(number, (int, float)) or isinstance(number, bool):
            raise TypeError("All elements in the list must be numbers (int or float)")
            
    return float(sum(numbers) / len(numbers))