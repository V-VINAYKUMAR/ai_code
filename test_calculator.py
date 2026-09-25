import unittest
from typing import List, Union

def calculate_average(numbers: List[Union[int, float]]) -> float:
    """
    Calculate the arithmetic mean of a list of numbers.

    Parameters:
    numbers (List[Union[int, float]]): A list of numerical values (int or float).

    Returns:
    float: The average of the numbers.
    """
    if not numbers:
        raise ValueError("Cannot calculate the average of an empty list.")
    return sum(numbers) / len(numbers)

class TestCalculateAverage(unittest.TestCase):
    
    def test_calculate_average_integers(self):
        """Test calculating the average of a list of positive integers."""
        numbers = [10, 20, 30, 40, 50]
        result = calculate_average(numbers)
        self.assertEqual(result, 30.0)

    def test_calculate_average_floats_and_ints(self):
        """Test calculating the average of a mixed list of integers and floats."""
        numbers = [1.5, 2.5, 5]
        result = calculate_average(numbers)
        self.assertAlmostEqual(result, 3.0)

    def test_calculate_average_empty_list(self):
        """Test that passing an empty list raises a ValueError."""
        numbers = []
        with self.assertRaises(ValueError):
            calculate_average(numbers)

if __name__ == "__main__":
    unittest.main()